import asyncio
import logging
import sys
from time import time_ns
from types import TracebackType
from typing import TYPE_CHECKING, Self
from urllib.parse import urlparse

import aiohttp
import msgspec.json
from aiohttp import ClientTimeout, web
from aiohttp.hdrs import ACCEPT, CONTENT_TYPE, USER_AGENT
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from yarl import URL

from observability import ErrorType, get_service_name, get_service_version
from observability.api_client import RequestLatency, ServiceType
from schemas import SchemaBeaconAPI, SchemaBuilderAPI, SchemaRemoteSigner, SchemaShared

from ._headers import (
    DATE_MILLISECONDS,
    ETH_CONSENSUS_VERSION,
    X_TIMEOUT_MS,
    ContentType,
)
from ._response import raise_for_response_size

if TYPE_CHECKING:
    from providers import SignatureProvider

    from .vero import Vero

_MAX_RESPONSE_BYTES = 64 * 2**20  # 64 MiB
_MAX_ERROR_RESPONSE_BYTES = 1 * 2**20  # 1 MiB


class Builder:
    def __init__(self, base_url: str, vero: "Vero"):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.metrics = vero.metrics
        self.tracer = trace.get_tracer(self.__class__.__name__)
        self.base_url = URL(base_url)
        _host = urlparse(base_url).hostname or ""
        if not _host:
            raise ValueError(f"Failed to parse hostname from {base_url}")

        self.client_session = aiohttp.ClientSession(
            base_url=self.base_url,
            headers={
                ACCEPT: ContentType.JSON.value,
                CONTENT_TYPE: ContentType.JSON.value,
                USER_AGENT: f"{get_service_name()}/{get_service_version()}",
            },
            trace_configs=[
                RequestLatency(host=_host, service_type=ServiceType.BUILDER),
            ],
            # Default aiohttp read buffer is only 64KB which is not always enough,
            # resulting in ValueError("Chunk too big")
            read_bufsize=2**19,
        )

        self._bid_request_auth_cache: dict[
            tuple[int, str], SchemaBuilderAPI.SignedBuilderRequestAuth
        ] = {}

    # TODO refactor -> ApiClient base class?
    @staticmethod
    async def _read_error_text(response: aiohttp.ClientResponse) -> str:
        raise_for_response_size(response, _MAX_ERROR_RESPONSE_BYTES)
        return await response.text()

    async def _cache_bid_request_auth_data(
        self,
        proposer_duty: SchemaBeaconAPI.ProposerDuty,
        signature_provider: "SignatureProvider",
    ) -> None:
        _cache_key = (int(proposer_duty.slot), proposer_duty.pubkey)
        if _cache_key in self._bid_request_auth_cache:
            return

        self.logger.info(f"Caching builder request data for {_cache_key}")

        message, signature, _ = await signature_provider.sign(
            message=SchemaRemoteSigner.BuilderRequestAuthSignableMessage(
                builder_request_auth=SchemaRemoteSigner.VersionedBuilderRequestAuth(
                    data=SchemaShared.BuilderRequestAuth(
                        # TODO support variable data from Keymgr API
                        data="0x" + str(self.base_url).encode().hex(),
                        slot=proposer_duty.slot,
                    ),
                ),
            ),
            identifier=proposer_duty.pubkey,
        )

        self._bid_request_auth_cache[_cache_key] = (
            SchemaBuilderAPI.SignedBuilderRequestAuth(
                message=message.builder_request_auth.data,
                signature=signature,
            )
        )

    async def get_status(self) -> None:
        async with self.client_session.get(
            "/eth/v1/builder/status", timeout=ClientTimeout(total=1.0)
        ) as resp:
            # Consume the response body so the connection is eligible for reuse.
            _ = await resp.read()

            if not resp.ok:
                self.logger.warning(
                    f"NOK status code {resp.status} for status request to {self.base_url}"
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
    ) -> SchemaShared.SignedExecutionPayloadBid | None:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.get_execution_payload_bid",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": str(self.base_url),
            },
        ):
            # TODO Content-Type header
            #      ... do we even want to bother with SSZ for this tiny object?
            #          maybe? We do then send it to N beacon nodes so savings are not just 1x
            # TODO SignedBuilderRequestAuth in request body - seems to be required now?
            url_path = f"/eth/v1/builder/execution_payload_bid/{slot}/{parent_hash}/{parent_root}/{proposer_pubkey}"

            _cache_key = (slot, proposer_pubkey)
            try:
                signed_builder_request_auth = self._bid_request_auth_cache.pop(
                    _cache_key
                )
            except KeyError:
                if "pytest" in sys.modules:
                    # use mocked value for tests
                    signed_builder_request_auth = (
                        SchemaBuilderAPI.SignedBuilderRequestAuth(
                            message=None,
                            signature=None,
                        )
                    )
                else:
                    self.logger.error(
                        f"No builder request auth for {_cache_key} -> {self.base_url}"
                    )
                    return None

            headers = {
                ETH_CONSENSUS_VERSION: fork_version.value,
                DATE_MILLISECONDS: str(time_ns() // 1_000_000),
                X_TIMEOUT_MS: str(int(soft_timeout * 1_000)),
            }
            timeout = ClientTimeout(total=hard_timeout)
            async with self.client_session.post(
                url_path,
                headers=headers,
                timeout=timeout,
                data=msgspec.json.encode(signed_builder_request_auth),
            ) as resp:
                if not resp.ok:
                    self.metrics.errors_c.labels(
                        error_type=ErrorType.BUILDER_GET_BID.value,
                    ).inc()
                    raise ValueError(
                        f"Received status code {resp.status} for request to {resp.request_info.url}"
                        f" Full response text: {await Builder._read_error_text(resp)}",
                    )

                if resp.status == web.HTTPNoContent.status_code:
                    # No bid is available
                    self.logger.info(f"No bid available from {self.base_url}")
                    return None

                resp_bytes = await resp.read()

                # parse based on Eth-Consensus-Version response header?
                # or just check it is Gloas for now...
                resp_fork_version = resp.headers[ETH_CONSENSUS_VERSION]
                if resp_fork_version != SchemaShared.ForkVersion.GLOAS.value:
                    raise NotImplementedError

                resp_decoded = msgspec.json.decode(
                    resp_bytes, type=SchemaBuilderAPI.GetExecutionPayloadBidResponse
                )
                self.logger.debug(
                    f"Received bid from {self.base_url}: {resp_decoded.data}"
                )
                self.logger.info(f"Bid with value {resp_decoded.data.total_value} received from {self.base_url}")

                # TODO Lodestar's bid verification
                # https://github.com/ChainSafe/lodestar/blob/unstable/packages/beacon-node/src/execution/builder/validateBid.ts

                # TODO bid verification? or shall we just let the beacon node handle
                #  all this?
                #  see https://github.com/ethereum/consensus-specs/blob/master/specs/gloas/validator.md#signed-execution-payload-bid
                # 1) signature verification - requires knowing the builder's pubkey
                # 2) builder balance - must cover the bid.value
                # 3) bid.slot - correct value
                # 4) bid.parent_block_hash + bid.parent_block_root - correct values
                # 5) bid.prev_randao
                # 6) fee recipient in signed_execution_payload_bid.message
                # 7) no trusted payment should be present (at least yet)
                # 8) trusted payment is <= max execution payment

                return resp_decoded.data


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
                b._cache_bid_request_auth_data(
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
    ) -> SchemaShared.SignedExecutionPayloadBid | None:
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

        # TODO pass on Builder API headers - timeout, date-milliseconds
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.get_execution_payload_bid",
            kind=SpanKind.CLIENT,
        ):
            tasks = [
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
            ]
            pending = tasks
            start_time = asyncio.get_running_loop().time()
            remaining_soft_timeout = soft_timeout

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

                    bid: SchemaShared.SignedExecutionPayloadBid = result
                    bid_value_gwei = bid.total_value
                    if bid_value_gwei > best_bid_value_gwei:
                        best_bid = bid
                        best_bid_value_gwei = bid_value_gwei

                # Calculate remaining timeout
                elapsed_time = asyncio.get_running_loop().time() - start_time
                remaining_soft_timeout = max(soft_timeout - elapsed_time, 0)

            # Soft timeout reached or all tasks finished
            # If we have a bid at this point, we use it
            if best_bid:
                self.logger.info(f"Selected best bid with value {best_bid_value_gwei}")
                for task in pending:
                    if not task.done():
                        task.cancel()
                return best_bid
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

                    self.logger.info(
                        f"Selected first bid with value {result.total_value}"
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
