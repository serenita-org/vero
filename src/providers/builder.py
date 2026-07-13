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

    #
    async def get_execution_payload_bid(self, slot: int, parent_hash: str, parent_root: str, proposer_pubkey: str) -> SchemaBuilderAPI.SignedExecutionPayloadBid:
        async with aiohttp.ClientSession(base_url=self.base_url) as session:
            url_path = f"/eth/v1/builder/execution_payload_bid/{slot}/{parent_hash}/{parent_root}/{proposer_pubkey}"
            async with session.post(url_path) as resp:
                if not resp.ok:
                    raise ValueError(f"NOK response received for get-bid request: {await resp.text()}")

                if resp.status == web.HTTPNoContent.status_code:
                    # No bid is available
                    self.logger.info(f"No bid available for slot {slot}")
                    return None

                resp_bytes = await resp.read()

                resp_decoded = msgspec.json.decode(
                    resp_bytes, type=SchemaBuilderAPI.GetExecutionPayloadBidResponse
                )
                return resp_decoded.data
