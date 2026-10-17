import asyncio
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
from schemas.keymanager_api import (
    BuilderConfig,
    ResolvedBuilderConfig,
    ResolvedBuilderEntry,
)

from ._api_client import ApiClient
from ._headers import (
    DATE_MILLISECONDS,
    ETH_CONSENSUS_VERSION,
    X_TIMEOUT_MS,
    ContentType,
)
from .builder_config import (
    bid_score,
    get_default_auth_data as get_default_auth_data,
    resolve_builder_config,
)

if TYPE_CHECKING:
    from providers import SignatureProvider

    from .keymanager import Keymanager
    from .multi_beacon_node import MultiBeaconNode
    from .vero import Vero

_MAX_RESPONSE_BYTES = 64 * 2**20  # 64 MiB
_MAX_ERROR_RESPONSE_BYTES = 1 * 2**20  # 1 MiB


class Builder(ApiClient):
    def __init__(self, base_url: str, vero: "Vero", auth_data: str | None = None):
        super().__init__(
            base_url=URL(base_url).with_path(URL(base_url).path.rstrip("/") + "/"),
            metrics=vero.metrics,
            service_type=ServiceType.BUILDER,
            timeout=ClientTimeout(total=10.0),
        )

        self.bid_selection_disabled = vero.cli_args.enable_bid_selection is False
        self.cli_args = vero.cli_args
        self.url = base_url
        self.auth_data = auth_data or "0x" + get_default_auth_data(self.base_url).hex()

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
                        data=self.auth_data,
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

    def prune(self, *, finished_proposal_slot: int) -> None:
        for cache_key in list(self._bid_request_auth_cache):
            proposal_slot, _ = cache_key
            if proposal_slot <= finished_proposal_slot:
                del self._bid_request_auth_cache[cache_key]

    @property
    def has_pending_auth(self) -> bool:
        return bool(self._bid_request_auth_cache)

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

    async def submit_builder_preferences(
        self,
        slot: int,
        proposer_pubkey: str,
        fork_version: SchemaShared.ForkVersion,
        max_execution_payment: str | None = None,
    ) -> None:
        if self.bid_selection_disabled:
            return

        endpoint = "/eth/v1/builder/builder_preferences/{proposer_pubkey}"
        headers = {
            ETH_CONSENSUS_VERSION: fork_version.value,
        }

        data = SchemaBuilderAPI.BuilderPreferencesRequest(
            preferences=SchemaBuilderAPI.BuilderPreferences(
                max_execution_payment=max_execution_payment
                if max_execution_payment is not None
                else str(self.cli_args.builder_max_execution_payment),
            ),
            auth=self.get_signed_builder_request_auth(
                slot=slot,
                proposer_pubkey=proposer_pubkey,
            ),
        )

        _ = await self.make_request(
            method="POST",
            endpoint=endpoint,
            formatted_endpoint_string_params=dict(
                proposer_pubkey=proposer_pubkey,
            ),
            headers=headers,
            data=msgspec.json.encode(data),
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
        config: ResolvedBuilderEntry | None = None,
        allowed_builder_indices: set[str] | None = None,
        fee_recipient: str | None = None,
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
            fee_recipient = fee_recipient or self.cli_args.fee_recipient
            if bid.message.fee_recipient.lower() != fee_recipient.lower():
                raise ValueError(
                    f"Fee recipient mismatch in bid from {self.base_url}: {bid.message.fee_recipient} != {fee_recipient}"
                )
            if (
                allowed_builder_indices is not None
                and bid.message.builder_index not in allowed_builder_indices
            ):
                raise ValueError(
                    f"Bid from {self.base_url} has an unapproved builder index"
                )

            max_payment = (
                int(config.max_execution_payment)
                if config
                else self.cli_args.builder_max_execution_payment
            )
            if int(bid.message.execution_payment) > max_payment:
                raise ValueError(
                    f"Invalid execution payment in bid from {self.base_url}. "
                    f"{int(bid.message.execution_payment):,} exceeds configured max execution payment {max_payment:,}"
                )
            _bid_total_value = bid.total_value
            min_bid = int(config.min_bid) if config else self.cli_args.builder_min_bid
            if _bid_total_value < min_bid:
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
            self.logger.warning(f"Failed to submit block to {self.base_url}: {e!r}")


class MultiBuilder:
    def __init__(
        self,
        vero: "Vero",
        keymanager: "Keymanager | None" = None,
        multi_beacon_node: "MultiBeaconNode | None" = None,
        signature_provider: "SignatureProvider | None" = None,
    ):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.tracer = trace.get_tracer(self.__class__.__name__)
        self.vero = vero
        self.keymanager = keymanager
        self.multi_beacon_node = multi_beacon_node
        self.signature_provider = signature_provider
        self.builders = [Builder(url, vero=vero) for url in vero.cli_args.builder_urls]
        self._builder_clients = {(b.url, b.auth_data): b for b in self.builders}
        self._builder_indices: dict[str, str] = {}

    def get_config(self, pubkey: str) -> ResolvedBuilderConfig:
        if self.keymanager is not None:
            return self.keymanager.resolve_builder_config(pubkey)
        return resolve_builder_config(BuilderConfig(), self.vero.cli_args)

    def get_builder_entries(
        self, pubkey: str, config: ResolvedBuilderConfig | None = None
    ) -> list[tuple[Builder, ResolvedBuilderEntry]]:
        result = []
        for entry in (
            config if config is not None else self.get_config(pubkey)
        ).builders:
            identity = (entry.url, entry.auth_data)
            builder = self._builder_clients.get(identity)
            if builder is None:
                builder = Builder(entry.url, vero=self.vero, auth_data=entry.auth_data)
                self._builder_clients[identity] = builder
                self.builders.append(builder)
            result.append((builder, entry))
        return result

    def get_fee_recipient(self, pubkey: str) -> str:
        if self.keymanager is not None:
            return self.keymanager.pubkey_to_fee_recipient_override.get(
                pubkey, self.vero.cli_args.fee_recipient
            )
        return self.vero.cli_args.fee_recipient

    async def _load_builder_indices(self, entries: list[ResolvedBuilderEntry]) -> None:
        missing = {
            pk.lower() for e in entries for pk in e.builder_pubkeys
        } - self._builder_indices.keys()
        if missing and self.multi_beacon_node is not None:
            self._builder_indices.update(
                await self.multi_beacon_node.get_builders(sorted(missing))
            )

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
        *,
        load_builder_indices: bool = True,
        config: ResolvedBuilderConfig | None = None,
    ) -> None:
        entries = self.get_builder_entries(proposer_duty.pubkey, config)
        results = await asyncio.gather(
            *(
                b.cache_bid_request_auth_data(
                    proposer_duty=proposer_duty,
                    signature_provider=signature_provider,
                )
                for b, _ in entries
            ),
            return_exceptions=True,
        )
        for (builder, _), result in zip(entries, results, strict=True):
            if isinstance(result, BaseException):
                self.logger.warning(
                    f"Failed to sign builder authentication for {builder.base_url}: {result!r}"
                )
        if not load_builder_indices or not self.vero.cli_args.enable_bid_selection:
            return
        try:
            await self._load_builder_indices([entry for _, entry in entries])
        except Exception as e:
            self.logger.warning(f"Failed to load builder indices: {e!r}")

    def prune(self, *, finished_proposal_slot: int) -> None:
        for builder in self.builders:
            builder.prune(finished_proposal_slot=finished_proposal_slot)
        # Retire clients removed by configuration changes once their duties finish.
        configured = {
            (url, "0x" + get_default_auth_data(URL(url)).hex())
            for url in self.vero.cli_args.builder_urls
        }
        if self.keymanager is not None:
            for pubkey in self.keymanager.pubkey_to_builder_config:
                configured.update(
                    (entry.url, entry.auth_data)
                    for entry in self.get_config(pubkey).builders
                )
        for identity, builder in list(self._builder_clients.items()):
            if identity not in configured and not builder.has_pending_auth:
                self.vero.task_manager.create_task(builder.client_session.close())
                self.builders.remove(builder)
                del self._builder_clients[identity]

    async def submit_builder_preferences(
        self,
        slot: int,
        proposer_pubkey: str,
        fork_version: SchemaShared.ForkVersion,
    ) -> None:
        entries = self.get_builder_entries(proposer_pubkey)
        results = await asyncio.gather(
            *(
                b.submit_builder_preferences(
                    slot=slot,
                    proposer_pubkey=proposer_pubkey,
                    fork_version=fork_version,
                    max_execution_payment=entry.max_execution_payment,
                )
                for b, entry in entries
            ),
            return_exceptions=True,
        )
        submitted_count = 0
        for builder, result in zip((b for b, _ in entries), results, strict=True):
            if isinstance(result, BaseException):
                self.logger.error(
                    f"Failed to submit builder preferences for slot {slot} to {builder.base_url}: {result!r}"
                )
            else:
                submitted_count += 1
        self.logger.info(
            f"Submitted builder preferences for slot {slot} to {submitted_count}/{len(entries)} builders"
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
        config: ResolvedBuilderConfig | None = None,
    ) -> tuple[Builder, SchemaShared.SignedExecutionPayloadBid] | None:
        """Gets the get execution payload bid response from all builders and returns
        the best one by its reported value.

        Most of the logic in here makes sure we don't wait too long for a builder to
        return a bid.

        If no bid is returned within the soft timeout, we wait until the hard timeout
        for any builder to return a bid and use that.

        Note: Bears similarities with the MultiBeaconNode._produce_best_block function.
        """
        config = config if config is not None else self.get_config(proposer_pubkey)
        if self.signature_provider is not None:
            await self.cache_bid_request_auth_data(
                SchemaBeaconAPI.ProposerDuty(
                    pubkey=proposer_pubkey, validator_index="0", slot=str(slot)
                ),
                self.signature_provider,
                load_builder_indices=False,
                config=config,
            )
        entries = self.get_builder_entries(proposer_pubkey, config)
        if not entries:
            return None
        config_by_builder = dict(entries)
        fee_recipient = self.get_fee_recipient(proposer_pubkey)

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
                        config=entry,
                        allowed_builder_indices={
                            self._builder_indices[pk.lower()]
                            for pk in entry.builder_pubkeys
                            if pk.lower() in self._builder_indices
                        }
                        if entry.builder_pubkeys
                        else None,
                        fee_recipient=fee_recipient,
                    )
                )
                for builder, entry in entries
            }
            start_time = asyncio.get_running_loop().time()
            remaining_soft_timeout = soft_timeout

            best_builder = None
            best_bid = None
            best_bid_value_gwei = -1
            best_bid_score = (-1, -1)

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
                    entry = config_by_builder[builder]
                    bid_value_gwei = bid.total_value
                    score = bid_score(bid_value_gwei, int(entry.builder_boost_factor))
                    if score > best_bid_score:
                        best_bid_score = score
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
                    f"Returning best direct bid with value {best_bid_value_gwei:,}"
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
                        f"Returning first direct bid with value {bid.total_value:,}"
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
