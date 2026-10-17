"""Implements the Keymanager API builder configuration endpoints."""

import msgspec.json
from aiohttp import web

from schemas import SchemaKeymanagerAPI

from ._app_keys import APP_KEY_KEYMANAGER

routes = web.RouteTableDef()


@routes.get("/eth/v1/validator/{pubkey}/builder_config")
async def builder_config_get(request: web.Request) -> web.Response:
    keymanager = request.app[APP_KEY_KEYMANAGER]
    response = SchemaKeymanagerAPI.GetBuilderConfigResponse(
        data=keymanager.get_builder_config(request.match_info["pubkey"])
    )
    return web.json_response(body=msgspec.json.encode(response))


@routes.post("/eth/v1/validator/{pubkey}/builder_config")
async def builder_config_post(request: web.Request) -> web.Response:
    config = msgspec.json.decode(
        await request.content.read(), type=SchemaKeymanagerAPI.BuilderConfig
    )
    keymanager = request.app[APP_KEY_KEYMANAGER]
    keymanager.set_builder_config(request.match_info["pubkey"], config)
    return web.Response(status=202)


@routes.delete("/eth/v1/validator/{pubkey}/builder_config")
async def builder_config_delete(request: web.Request) -> web.Response:
    keymanager = request.app[APP_KEY_KEYMANAGER]
    keymanager.delete_builder_config(request.match_info["pubkey"])
    return web.Response(status=204)
