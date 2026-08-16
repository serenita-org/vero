import asyncio
import logging
from types import TracebackType
from typing import TYPE_CHECKING, Self

import aiohttp
import msgspec.json
from aiohttp import web
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from schemas import SchemaBuilderAPI

if TYPE_CHECKING:
    from .vero import Vero


class Builder:
    def __init__(self, base_url: str):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.tracer = trace.get_tracer(self.__class__.__name__)
        self.base_url = base_url
        # TODO client session, metrics, ...

    async def get_execution_payload_bid(
        self, slot: int, parent_hash: str, parent_root: str, proposer_pubkey: str
    ) -> SchemaBuilderAPI.SignedExecutionPayloadBid | None:
        with self.tracer.start_as_current_span(
            name=f"{self.__class__.__name__}.get_execution_payload_bid",
            kind=SpanKind.CLIENT,
            attributes={
                "server.address": self.base_url,
            },
        ):
            async with aiohttp.ClientSession(base_url=self.base_url) as session:
                url_path = f"/eth/v1/builder/execution_payload_bid/{slot}/{parent_hash}/{parent_root}/{proposer_pubkey}"
                async with session.post(url_path) as resp:
                    if not resp.ok:
                        raise ValueError(
                            f"NOK response received for get-bid request: {await resp.text()}"
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
        self.builders = [Builder(url) for url in vero.cli_args.builder_urls]

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
        pass
        # TODO
        # await asyncio.gather(
        #     *[
        #         b.client_session.close()
        #         for b in self.builders
        #         if not b.client_session.closed
        #     ],
        # )

    async def get_execution_payload_bid(
        self, slot: int, parent_hash: str, parent_root: str, proposer_pubkey: str
    ) -> SchemaBuilderAPI.SignedExecutionPayloadBid | None:
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
            best_bid_value_wei = -1
            for result in results:
                if isinstance(result, BaseException):
                    # TODO log warning and continue
                    continue

                if result is None:
                    # No bid from builder
                    continue

                bid: SchemaBuilderAPI.SignedExecutionPayloadBid = result
                bid_value_wei = 1e9 * int(bid.message.value) + int(
                    bid.message.execution_payment
                )
                if bid_value_wei > best_bid_value_wei:
                    best_bid = bid
                    best_bid_value_wei = bid_value_wei

            if best_bid is None:
                self.logger.warning("No bid retrieved from builders")
                return None

            self.logger.info(f"Picked best bid with value {best_bid_value_wei}")
            self.logger.debug(f"Best bid: {best_bid}")
            return best_bid
