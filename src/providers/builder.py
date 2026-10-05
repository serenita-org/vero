import asyncio
import ipaddress
import logging
from time import time_ns
from types import TracebackType
from typing import TYPE_CHECKING, Self

import msgspec.json
from aiohttp import ClientTimeout, web
from aiohttp.hdrs import CONTENT_TYPE
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from yarl import URL

from observability import ErrorType
from observability.api_client import ServiceType
from schemas import SchemaBeaconAPI, SchemaBuilderAPI, SchemaRemoteSigner, SchemaShared

from ._api_client import ApiClient
from ._headers import (
    DATE_MILLISECONDS,
    ETH_CONSENSUS_VERSION,
    X_TIMEOUT_MS,
    ContentType,
)

if TYPE_CHECKING:
    from providers import SignatureProvider

    from .vero import Vero

_MAX_RESPONSE_BYTES = 64 * 2**20  # 64 MiB
_MAX_ERROR_RESPONSE_BYTES = 1 * 2**20  # 1 MiB


def get_default_auth_data(url: URL) -> bytes:
    host = url.host
    if host is None:
        raise ValueError(f"No host in URL: {url}")

    if ":" in host:  # IPv6 literal
        host = f"[{ipaddress.IPv6Address(host).compressed}]"

    return host.encode("ascii")


class Builder(ApiClient):
    def __init__(self, base_url: str, vero: "Vero"):
        super().__init__(
            base_url=base_url,
            metrics=vero.metrics,
            service_type=ServiceType.BUILDER,
            timeout=ClientTimeout(total=10.0),
        )

        self.bid_selection_disabled = vero.cli_args.disable_bid_selection
        self.cli_args = vero.cli_args

        self._bid_request_auth_cache: dict[
            tuple[int, str], SchemaShared.SignedBuilderRequestAuth
        ] = {}

    async def cache_bid_request_auth_data(
        self,
        proposer_duty: SchemaBeaconAPI.ProposerDuty,
        signature_provider: "SignatureProvider",
    ) -> None:
        _cache_key = (int(proposer_duty.slot), proposer_duty.pubkey)
        if _cache_key in self._bid_request_auth_cache:
            return

        self.logger.debug(f"Caching bid request auth data for {_cache_key}")

        message, signature, _ = await signature_provider.sign(
            message=SchemaRemoteSigner.BuilderRequestAuthSignableMessage(
                builder_request_auth=SchemaRemoteSigner.VersionedBuilderRequestAuth(
                    data=SchemaShared.BuilderRequestAuth(
                        # TODO [Gloas] support variable data from Keymgr API
                        data="0x" + get_default_auth_data(url=self.base_url).hex(),
                        slot=proposer_duty.slot,
                    ),
                ),
            ),
            identifier=proposer_duty.pubkey,
        )

        self._bid_request_auth_cache[_cache_key] = (
            SchemaShared.SignedBuilderRequestAuth(
                message=message.builder_request_auth.data,
                signature=signature,
            )
        )

    async def get_status(self) -> None:
        if self.bid_selection_disabled:
            return

        _ = await self.make_request(
            method="GET",
            endpoint="/eth/v1/builder/status",
            timeout=ClientTimeout(total=1.0),
        )

    def get_signed_builder_request_auth(
        self,
        slot: int,
        proposer_pubkey: str,
    ) -> SchemaShared.SignedBuilderRequestAuth:
        _cache_key = (slot, proposer_pubkey)
        try:
            return self._bid_request_auth_cache[_cache_key]
        except KeyError:
            raise KeyError(
                f"No builder request auth for {_cache_key} -> {self.base_url}"
            ) from None

    async def get_execution_payload_bid(
        self,
        slot: int,
        parent_hash: str,
        parent_root: str,
        proposer_pubkey: str,
        fork_version: SchemaShared.ForkVersion,
        soft_timeout: float,
        hard_timeout: float,
    ) -> tuple[Self, SchemaShared.SignedExecutionPayloadBid] | None:
        if self.bid_selection_disabled:
            return None

        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.get_execution_payload_bid",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": str(self.base_url),
            },
        ) as tracer_span:
            endpoint = "/eth/v1/builder/execution_payload_bid/{slot}/{parent_hash}/{parent_root}/{proposer_pubkey}"
            formatted_endpoint_string_params: dict[str, str | int] = dict(
                slot=slot,
                parent_hash=parent_hash,
                parent_root=parent_root,
                proposer_pubkey=proposer_pubkey,
            )

            try:
                signed_builder_request_auth = self.get_signed_builder_request_auth(
                    slot=slot,
                    proposer_pubkey=proposer_pubkey,
                )
            except KeyError:
                self.logger.error(
                    f"Cannot get bid from {self.base_url} - no builder request auth for {(slot, proposer_pubkey)}"
                )
                return None

            headers = {
                ETH_CONSENSUS_VERSION: fork_version.value,
                DATE_MILLISECONDS: str(time_ns() // 1_000_000),
                X_TIMEOUT_MS: str(int(soft_timeout * 1_000)),
            }
            timeout = ClientTimeout(total=hard_timeout)

            try:
                resp_bytes, _content_type, resp = await self.make_request(
                    method="POST",
                    endpoint=endpoint,
                    formatted_endpoint_string_params=formatted_endpoint_string_params,
                    headers=headers,
                    timeout=timeout,
                    data=msgspec.json.encode(signed_builder_request_auth),
                )
            except Exception as e:
                self.metrics.errors_c.labels(
                    error_type=ErrorType.BUILDER_GET_BID.value,
                ).inc()
                raise ValueError(
                    f"Failed to get bid from {self.base_url}: {e!r}"
                ) from e

            # OK response
            if resp.status == web.HTTPNoContent.status_code:
                # No bid is available
                self.logger.info(f"No bid available from {self.base_url}")
                return None

            bid_response = msgspec.json.decode(
                resp_bytes, type=SchemaBuilderAPI.GetExecutionPayloadBidResponse
            )
            if bid_response.version != fork_version:
                raise ValueError(
                    f"Fork version mismatch in bid from {self.base_url}: {bid_response.version} != {fork_version}"
                )

            bid = bid_response.data

            if int(bid.message.slot) != slot:
                raise ValueError(
                    f"Slot mismatch in bid from {self.base_url}: {bid.message.slot} != {slot}"
                )
            if bid.message.parent_block_hash != parent_hash:
                raise ValueError(
                    f"Parent hash mismatch in bid from {self.base_url}: {bid.message.parent_block_hash} != {parent_hash}"
                )
            if bid.message.parent_block_root != parent_root:
                raise ValueError(
                    f"Parent root mismatch in bid from {self.base_url}: {bid.message.parent_block_root} != {parent_root}"
                )
            if bid.message.fee_recipient.lower() != self.cli_args.fee_recipient:
                raise ValueError(
                    f"Fee recipient mismatch in bid from {self.base_url}: {bid.message.fee_recipient} != {self.cli_args.fee_recipient}"
                )
            if (
                int(bid.message.execution_payment)
                > self.cli_args.builder_max_execution_payment
            ):
                raise ValueError(
                    f"Invalid execution payment in bid from {self.base_url}. {int(bid.message.execution_payment):,} exceeds configured max execution payment {self.cli_args.builder_max_execution_payment:,}"
                )

            _bid_total_value = bid.total_value
            if _bid_total_value < self.cli_args.builder_min_bid:
                self.logger.debug(
                    f"Ignoring bid event with value {_bid_total_value:,} below configured min bid"
                )
                return None

            self.logger.info(
                f"Received bid with value {_bid_total_value:,} from {self.base_url}"
            )
            tracer_span.add_event(
                "GetExecutionPayloadBidResponse",
                attributes=dict(
                    value=int(bid.message.value),
                    execution_payment=int(bid.message.execution_payment),
                    total_value=_bid_total_value,
                ),
            )

            return self, bid

    async def submit_signed_beacon_block(
        self,
        fork_version: SchemaShared.ForkVersion,
        data: bytes,
        content_type: ContentType,
    ) -> None:
        endpoint = "/eth/v1/builder/beacon_blocks"
        headers = {
            ETH_CONSENSUS_VERSION: fork_version.value,
            CONTENT_TYPE: content_type.value,
        }
        try:
            with self.tracer.start_as_current_span(
                name=f"{self.__class__.__name__}.submit_signed_beacon_block",
                kind=SpanKind.CLIENT,
                attributes={
                    "server.address": str(self.base_url),
                },
            ):
                await self.make_request(
                    method="POST",
                    endpoint=endpoint,
                    data=data,
                    headers=headers,
                )
        except Exception as e:
            self.metrics.errors_c.labels(
                error_type=ErrorType.BUILDER_SUBMIT_BLOCK.value,
            ).inc()
            self.logger.error(f"Failed to submit block to {self.base_url}: {e!r}")


# TODO submit builder preferences
#  - this is for max_execution_payment and SignedBuilderRequestAuth


class MultiBuilder:
    def __init__(self, vero: "Vero"):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.tracer = trace.get_tracer(self.__class__.__name__)
        self.builders = [Builder(url, vero=vero) for url in vero.cli_args.builder_urls]

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._close_client_sessions()

    async def _close_client_sessions(self) -> None:
        await asyncio.gather(
            *[
                b.client_session.close()
                for b in self.builders
                if not b.client_session.closed
            ],
        )

    async def warm_connections(self) -> None:
        self.logger.debug("Pre-warming builder connections with status requests")

        await asyncio.gather(
            *(b.get_status() for b in self.builders),
            return_exceptions=True,
        )

    async def cache_bid_request_auth_data(
        self,
        proposer_duty: SchemaBeaconAPI.ProposerDuty,
        signature_provider: "SignatureProvider",
    ) -> None:
        await asyncio.gather(
            *(
                b.cache_bid_request_auth_data(
                    proposer_duty=proposer_duty,
                    signature_provider=signature_provider,
                )
                for b in self.builders
            )
        )

    async def get_execution_payload_bid(
        self,
        slot: int,
        parent_hash: str,
        parent_root: str,
        proposer_pubkey: str,
        fork_version: SchemaShared.ForkVersion,
        soft_timeout: float,
        hard_timeout: float,
    ) -> tuple[Builder, SchemaShared.SignedExecutionPayloadBid] | None:
        """Gets the get execution payload bid response from all builders and returns
        the best one by its reported value.

        Most of the logic in here makes sure we don't wait too long for a builder to
        return a bid.

        If no bid is returned within the soft timeout, we wait until the hard timeout
        for any builder to return a bid and use that.

        Note: Bears similarities with the MultiBeaconNode._produce_best_block function.
        """
        if len(self.builders) == 0:
            return None

        if fork_version != SchemaShared.ForkVersion.GLOAS:
            raise NotImplementedError

        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.get_execution_payload_bid",
            kind=SpanKind.CLIENT,
        ):
            pending = {
                asyncio.create_task(
                    builder.get_execution_payload_bid(
                        slot=slot,
                        parent_hash=parent_hash,
                        parent_root=parent_root,
                        proposer_pubkey=proposer_pubkey,
                        fork_version=fork_version,
                        soft_timeout=soft_timeout,
                        hard_timeout=hard_timeout,
                    )
                )
                for builder in self.builders
            }
            start_time = asyncio.get_running_loop().time()
            remaining_soft_timeout = soft_timeout

            best_builder = None
            best_bid = None
            best_bid_value_gwei = -1

            while pending and remaining_soft_timeout > 0:
                done, pending = await asyncio.wait(
                    pending,
                    timeout=remaining_soft_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for coro in done:
                    try:
                        result = await coro
                    except Exception as e:
                        self.logger.warning(f"Failed to get bid from builder: {e!r}")
                        continue

                    if result is None:
                        # No bid from builder
                        continue

                    builder, bid = result
                    bid_value_gwei = bid.total_value
                    if bid_value_gwei > best_bid_value_gwei:
                        best_builder = builder
                        best_bid = bid
                        best_bid_value_gwei = bid_value_gwei

                # Calculate remaining timeout
                elapsed_time = asyncio.get_running_loop().time() - start_time
                remaining_soft_timeout = max(soft_timeout - elapsed_time, 0)

            # Soft timeout reached or all tasks finished
            # If we have a bid at this point, we use it
            if best_bid:
                self.logger.info(
                    f"Selected best bid with value {best_bid_value_gwei:,}"
                )
                for task in pending:
                    if not task.done():
                        task.cancel()
                return best_builder, best_bid  # type: ignore[return-value]
            if not pending:
                self.logger.info("No bids returned by builders")
                return None

            # Soft timeout reached, but we have no bid yet and we have pending tasks.
            # We wait until hard timeout for any builder to return a bid
            self.logger.warning("Bid selection soft timeout reached.")
            # Wait until hard timeout for any builder to return a bid
            elapsed_time = asyncio.get_running_loop().time() - start_time
            remaining_hard_timeout = max(hard_timeout - elapsed_time, 0)
            while pending and remaining_hard_timeout > 0:
                done, pending = await asyncio.wait(
                    pending,
                    timeout=remaining_hard_timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )

                for coro in done:
                    try:
                        result = await coro
                    except Exception as e:
                        self.logger.warning(f"Failed to get bid from builder: {e!r}")
                        continue

                    if result is None:
                        # No bid from builder
                        continue

                    builder, bid = result
                    self.logger.info(
                        f"Selected first bid with value {bid.total_value:,}"
                    )
                    for task in pending:
                        if not task.done():
                            task.cancel()
                    return result

                # Calculate remaining timeout
                elapsed_time = asyncio.get_running_loop().time() - start_time
                remaining_hard_timeout = max(hard_timeout - elapsed_time, 0)

            if pending:
                self.logger.warning("Bid selection hard timeout reached")
                for task in pending:
                    if not task.done():
                        task.cancel()
            return None


# TODO submit BuilderPreferencesRequest to /eth/v1/builder/builder_preferences/{proposer_pubkey} ?
#  see https://ethereum.github.io/builder-specs/?urls.primaryName=dev#/Builder/submitBuilderPreferences
#  used for max_execution_payment
