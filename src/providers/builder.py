import asyncio
import logging
from types import TracebackType
from typing import TYPE_CHECKING, Self
from urllib.parse import urlparse

import aiohttp
import msgspec.json
from aiohttp import ClientTimeout, web
from aiohttp.hdrs import ACCEPT, CONTENT_TYPE, USER_AGENT
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from observability import ErrorType, get_service_name, get_service_version
from observability.api_client import RequestLatency, ServiceType
from schemas import SchemaBuilderAPI, SchemaShared

from ._headers import ContentType
from ._response import raise_for_response_size

if TYPE_CHECKING:
    from .vero import Vero

_TIMEOUT_DEFAULT_CONNECT = 2
_TIMEOUT_DEFAULT_TOTAL = 10
_MAX_RESPONSE_BYTES = 64 * 2**20  # 64 MiB
_MAX_ERROR_RESPONSE_BYTES = 1 * 2**20  # 1 MiB


class Builder:
    def __init__(self, base_url: str, vero: "Vero"):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.metrics = vero.metrics
        self.tracer = trace.get_tracer(self.__class__.__name__)
        self.base_url = base_url
        _host = urlparse(self.base_url).hostname or ""
        if not _host:
            raise ValueError(f"Failed to parse hostname from {base_url}")

        self.client_session = aiohttp.ClientSession(
            base_url=self.base_url,
            timeout=ClientTimeout(
                connect=_TIMEOUT_DEFAULT_CONNECT,
                total=_TIMEOUT_DEFAULT_TOTAL,
            ),
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

    # TODO refactor -> ApiClient base class?
    @staticmethod
    async def _read_error_text(response: aiohttp.ClientResponse) -> str:
        raise_for_response_size(response, _MAX_ERROR_RESPONSE_BYTES)
        return await response.text()

    async def get_execution_payload_bid(
        self, slot: int, parent_hash: str, parent_root: str, proposer_pubkey: str
    ) -> SchemaShared.SignedExecutionPayloadBid | None:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.get_execution_payload_bid",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.base_url,
            },
        ):
            url_path = f"/eth/v1/builder/execution_payload_bid/{slot}/{parent_hash}/{parent_root}/{proposer_pubkey}"
            async with self.client_session.post(url_path) as resp:
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
                    self.logger.info(f"No bid available for slot {slot}")
                    return None

                resp_bytes = await resp.read()

                resp_decoded = msgspec.json.decode(
                    resp_bytes, type=SchemaBuilderAPI.GetExecutionPayloadBidResponse
                )

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

                return resp_decoded.data


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

    async def get_execution_payload_bid(
        self, slot: int, parent_hash: str, parent_root: str, proposer_pubkey: str
    ) -> SchemaShared.SignedExecutionPayloadBid | None:
        # TODO early return if no builders enabled / ...
        if len(self.builders) == 0:
            return None

        # TODO pass on Builder API headers - timeout, date-milliseconds
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.get_execution_payload_bid",
            kind=SpanKind.CLIENT,
        ):
            results = await asyncio.gather(
                *[
                    builder.get_execution_payload_bid(
                        slot=slot,
                        parent_hash=parent_hash,
                        parent_root=parent_root,
                        proposer_pubkey=proposer_pubkey,
                    )
                    for builder in self.builders
                ],
                return_exceptions=True,
            )

            # TODO we probably want to do as_completed here with a timeout?
            best_bid = None
            best_bid_value_gwei = -1
            for result in results:
                if isinstance(result, BaseException):
                    self.logger.warning(f"Failed to get bid from builder: {result!r}")
                    continue

                if result is None:
                    # No bid from builder
                    continue

                bid: SchemaShared.SignedExecutionPayloadBid = result
                bid_value_gwei = int(bid.message.value) + int(
                    bid.message.execution_payment
                )
                if bid_value_gwei > best_bid_value_gwei:
                    best_bid = bid
                    best_bid_value_gwei = bid_value_gwei

            if best_bid is None:
                self.logger.warning("No bid retrieved from builders")
                return None

            self.logger.info(f"Picked best bid with value {best_bid_value_gwei}")
            self.logger.debug(f"Best bid: {best_bid}")
            return best_bid
