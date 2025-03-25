"""
Implements the Keymanager API Remote Key Manager endpoints.
https://ethereum.github.io/keymanager-APIs
"""

from typing import TYPE_CHECKING

import msgspec.json
from aiohttp import web

from schemas import SchemaKeymanagerAPI

if TYPE_CHECKING:
    from providers import Keymanager

routes = web.RouteTableDef()


@routes.get("/eth/v1/remotekeys")
async def remote_keys_get(request: web.Request) -> web.Response:
    keymanager: Keymanager = request.app["keymanager"]

    remote_keys = SchemaKeymanagerAPI.ListRemoteKeysResponse(
        data=[
            SchemaKeymanagerAPI.RemoteKeyWithReadOnlyStatus(
                pubkey=remote_key.pubkey,
                url=remote_key.url,
                readonly=False,
            )
            for remote_key in keymanager.list_remote_keys()
        ]
    )

    return web.json_response(body=msgspec.json.encode(remote_keys))


@routes.post("/eth/v1/remotekeys")
async def remote_keys_post(request: web.Request) -> web.Response:
    request_data = msgspec.json.decode(
        await request.content.read(),
        type=SchemaKeymanagerAPI.ImportRemoteKeysRequest,
    )

    keymanager: Keymanager = request.app["keymanager"]
    import_status_messages = await keymanager.import_remote_keys(
        remote_keys=request_data.remote_keys
    )

    return web.json_response(
        body=msgspec.json.encode(
            SchemaKeymanagerAPI.ImportRemoteKeysResponse(
                data=import_status_messages,
            )
        ),
    )


@routes.delete("/eth/v1/remotekeys")
async def remote_keys_delete(request: web.Request) -> web.Response:
    request_data = msgspec.json.decode(
        await request.content.read(),
        type=SchemaKeymanagerAPI.DeleteRemoteKeysRequest,
    )

    keymanager: Keymanager = request.app["keymanager"]
    delete_status_messages = await keymanager.delete_remote_keys(
        pubkeys=request_data.pubkeys
    )

    return web.json_response(
        body=msgspec.json.encode(
            SchemaKeymanagerAPI.DeleteRemoteKeysResponse(
                data=delete_status_messages,
            )
        ),
    )
