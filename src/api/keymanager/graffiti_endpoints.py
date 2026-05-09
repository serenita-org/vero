"""
Implements the Keymanager API Graffiti endpoints.
https://ethereum.github.io/keymanager-APIs
"""

from typing import TYPE_CHECKING

import msgspec.json
from aiohttp import web

from schemas import SchemaKeymanagerAPI
from spec.utils import encode_graffiti

from ._app_keys import APP_KEY_KEYMANAGER

if TYPE_CHECKING:
    from providers import Keymanager

routes = web.RouteTableDef()


@routes.get("/eth/v1/validator/{pubkey}/graffiti")
async def graffiti_get(request: web.Request) -> web.Response:
    pubkey = request.match_info["pubkey"]
    keymanager: Keymanager = request.app[APP_KEY_KEYMANAGER]

    resp = SchemaKeymanagerAPI.GraffitiResponse(data=keymanager.get_graffiti(pubkey))

    return web.json_response(body=msgspec.json.encode(resp))


@routes.post("/eth/v1/validator/{pubkey}/graffiti")
async def graffiti_post(request: web.Request) -> web.Response:
    request_data = msgspec.json.decode(
        await request.content.read(), type=SchemaKeymanagerAPI.SetGraffitiRequest
    )

    pubkey = request.match_info["pubkey"]
    keymanager: Keymanager = request.app[APP_KEY_KEYMANAGER]

    # Check if it can be encoded within 32 bytes
    _ = encode_graffiti(request_data.graffiti)

    keymanager.set_graffiti(pubkey=pubkey, graffiti=request_data.graffiti)
    return web.Response(status=202)


@routes.delete("/eth/v1/validator/{pubkey}/graffiti")
async def graffiti_delete(request: web.Request) -> web.Response:
    pubkey = request.match_info["pubkey"]
    keymanager: Keymanager = request.app[APP_KEY_KEYMANAGER]

    keymanager.delete_configured_graffiti_value(pubkey=pubkey)

    return web.Response(status=204)
