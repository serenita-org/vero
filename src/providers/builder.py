import asyncio
import logging

import aiohttp
import msgspec.json
from aiohttp import web

from schemas import SchemaBuilderAPI


class Builder:
    def __init__(self, base_url: str):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.base_url = base_url
        # TODO client session, metrics, ...

    async def get_execution_payload_bid(
        self, slot: int, parent_hash: str, parent_root: str, proposer_pubkey: str
    ) -> SchemaBuilderAPI.SignedExecutionPayloadBid | None:
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
                return resp_decoded.data


class MultiBuilder:
    def __init__(self, builder_urls: list[str]):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.builders = [Builder(url) for url in builder_urls]

    async def get_execution_payload_bid(
        self, slot: int, parent_hash: str, parent_root: str, proposer_pubkey: str
    ) -> SchemaBuilderAPI.SignedExecutionPayloadBid | None:
        # TODO early return if no builders enabled / ...
        if len(self.builders) == 0:
            return None

        # TODO pass on Builder API headers - timeout, date-milliseconds
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
        best_bid_value = -1
        for result in results:
            if isinstance(result, BaseException):
                # TODO log warning and continue
                continue

            if result is None:
                # No bid from builder
                continue

            bid: SchemaBuilderAPI.SignedExecutionPayloadBid = result
            # TODO also account for bid execution payment I guess?
            bid_value = int(bid.message.value) + int(bid.message.execution_payment)
            if bid_value > best_bid_value:
                best_bid = bid
                best_bid_value = bid_value

        if best_bid is None:
            self.logger.warning("No bid retrieved from builders")
            return None

        self.logger.info(f"Picked best bid with value {best_bid_value}")
        self.logger.debug(f"Best bid: {best_bid}")
        return best_bid
