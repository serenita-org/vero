"""
Implements the Keymanager API Fee Recipient endpoints.
https://ethereum.github.io/keymanager-APIs
"""

from typing import TYPE_CHECKING

import msgspec.json
from aiohttp import web

from schemas import SchemaKeymanagerAPI

if TYPE_CHECKING:
    from providers import Keymanager

routes = web.RouteTableDef()


@routes.get("/eth/v1/validator/{pubkey}/feerecipient")
async def fee_recipient_get(request: web.Request) -> web.Response:
    pubkey = request.match_info["pubkey"]
    keymanager: Keymanager = request.app["keymanager"]

    resp = SchemaKeymanagerAPI.ListFeeRecipientResponse(
        data=keymanager.get_fee_recipient(pubkey)
    )

    return web.json_response(body=msgspec.json.encode(resp))


@routes.post("/eth/v1/validator/{pubkey}/feerecipient")
async def fee_recipient_post(request: web.Request) -> web.Response:
    request_data = msgspec.json.decode(
        await request.content.read(),
        type=SchemaKeymanagerAPI.SetFeeRecipientRequest,
    )

    pubkey = request.match_info["pubkey"]
    keymanager: Keymanager = request.app["keymanager"]

    keymanager.set_fee_recipient(pubkey=pubkey, fee_recipient=request_data.ethaddress)

    return web.Response(status=202)


@routes.delete("/eth/v1/validator/{pubkey}/feerecipient")
async def fee_recipient_delete(request: web.Request) -> web.Response:
    pubkey = request.match_info["pubkey"]
    keymanager: Keymanager = request.app["keymanager"]

    keymanager.delete_configured_fee_recipient(pubkey=pubkey)

    return web.Response(status=204)
