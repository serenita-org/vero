"""
Implements the Keymanager API Voluntary Exit endpoints.
https://ethereum.github.io/keymanager-APIs
"""

from typing import TYPE_CHECKING

import msgspec.json
from aiohttp import web

from schemas import SchemaKeymanagerAPI

if TYPE_CHECKING:
    from providers import Keymanager

routes = web.RouteTableDef()


@routes.post("/eth/v1/validator/{pubkey}/voluntary_exit")
async def voluntary_exit_post(request: web.Request) -> web.Response:
    # Minimum epoch for processing exit. Defaults to the current epoch if not set.
    epoch = request.query.get("epoch")

    pubkey = request.match_info["pubkey"]
    keymanager: Keymanager = request.app["keymanager"]

    signed_voluntary_exit = await keymanager.sign_voluntary_exit_message(
        pubkey=pubkey,
        epoch=int(epoch) if epoch else None,
    )

    return web.json_response(
        body=msgspec.json.encode(
            SchemaKeymanagerAPI.SignVoluntaryExitResponse(data=signed_voluntary_exit)
        )
    )
