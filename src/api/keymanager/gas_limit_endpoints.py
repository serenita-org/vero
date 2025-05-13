"""
Implements the Keymanager API Gas Limit endpoints.
https://ethereum.github.io/keymanager-APIs
"""

from typing import TYPE_CHECKING

import msgspec.json
from aiohttp import web

from schemas import SchemaKeymanagerAPI

if TYPE_CHECKING:
    from providers import Keymanager

routes = web.RouteTableDef()


@routes.get("/eth/v1/validator/{pubkey}/gas_limit")
async def gas_limit_get(request: web.Request) -> web.Response:
    pubkey = request.match_info["pubkey"]
    keymanager: Keymanager = request.app["keymanager"]

    resp = SchemaKeymanagerAPI.ListGasLimitResponse(
        data=keymanager.get_gas_limit(pubkey)
    )

    return web.json_response(body=msgspec.json.encode(resp))


@routes.post("/eth/v1/validator/{pubkey}/gas_limit")
async def gas_limit_post(request: web.Request) -> web.Response:
    request_data = msgspec.json.decode(
        await request.content.read(), type=SchemaKeymanagerAPI.SetGasLimitRequest
    )

    pubkey = request.match_info["pubkey"]
    keymanager: Keymanager = request.app["keymanager"]

    keymanager.set_gas_limit(pubkey=pubkey, gas_limit=request_data.gas_limit)

    return web.Response(status=202)


@routes.delete("/eth/v1/validator/{pubkey}/gas_limit")
async def gas_limit_delete(request: web.Request) -> web.Response:
    pubkey = request.match_info["pubkey"]
    keymanager: Keymanager = request.app["keymanager"]

    keymanager.delete_configured_gas_limit(pubkey=pubkey)

    return web.Response(status=204)
