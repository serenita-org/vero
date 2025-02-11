"""
See https://ethereum.github.io/keymanager-APIs

There are some TODOs left like the required token authentication ...
"""

import asyncio
from concurrent.futures import ProcessPoolExecutor

import aiohttp
import msgspec.json
from aiohttp import web

from providers import RemoteSigner
from schemas import SchemaKeymanagerAPI

routes = web.RouteTableDef()

# TODO pass from init
shutdown_event = asyncio.Event()
remote_signer = RemoteSigner(url="http://whatever")

json_encoder = msgspec.json.Encoder()
json_decoder = msgspec.json.Decoder()
JSON_CONTENT_TYPE = "application/json"

app = web.Application()


@routes.get("/eth/v1/remotekeys")
async def remote_keys_get(_: aiohttp.web.Request) -> aiohttp.web.Response:
    # TODO keys = remote_signer.get_public_keys()
    keys = ["0xa", "0xb"]

    remote_keys = SchemaKeymanagerAPI.ListRemoteKeysResponse(
        data=[
            SchemaKeymanagerAPI.RemoteKeyWithReadOnlyStatus(
                pubkey=k,
                url=remote_signer.url,
                readonly=True,
            )
            for k in keys
        ]
    )

    return web.Response(
        body=json_encoder.encode(remote_keys), content_type=JSON_CONTENT_TYPE
    )


@routes.post("/eth/v1/remotekeys")
async def remote_keys_post(request: aiohttp.web.Request) -> aiohttp.web.Response:
    request_data = msgspec.json.decode(
        await request.content.read(), type=SchemaKeymanagerAPI.ImportRemoteKeysRequest
    )

    responses: list[SchemaKeymanagerAPI.ImportStatusMessage] = [
        SchemaKeymanagerAPI.ImportStatusMessage(
            status=SchemaKeymanagerAPI.ImportStatus.ERROR, message="I/O error"
        )
        for _ in request_data.remote_keys
    ]

    return web.Response(
        body=json_encoder.encode(
            SchemaKeymanagerAPI.ImportRemoteKeysResponse(
                data=responses,
            )
        ),
        content_type=JSON_CONTENT_TYPE,
    )


@routes.delete("/eth/v1/remotekeys")
async def remote_keys_delete(request: aiohttp.web.Request) -> aiohttp.web.Response:
    request_data = msgspec.json.decode(
        await request.content.read(), type=SchemaKeymanagerAPI.DeleteRemoteKeysRequest
    )

    responses: list[SchemaKeymanagerAPI.DeleteStatusMessage] = [
        SchemaKeymanagerAPI.DeleteStatusMessage(
            status=SchemaKeymanagerAPI.DeleteStatus.ERROR,
            message="",
        )
        for _ in request_data.pubkeys
    ]

    return web.Response(
        body=json_encoder.encode(
            SchemaKeymanagerAPI.DeleteRemoteKeysResponse(
                data=responses,
            )
        ),
        content_type=JSON_CONTENT_TYPE,
    )


def start_server() -> None:
    app = web.Application()
    app.add_routes(routes)
    web.run_app(app)

    # TODO - when integratin with rest of the app, figure this out,
    #  also shutdown handling
    # runner = web.AppRunner(app)
    # await runner.setup()
    # site = web.TCPSite(runner, 'localhost', 8080)
    # await site.start()
    #
    # while not shutdown_event.is_set():
    #     await asyncio.sleep(30)  # sleep forever
    #     shutdown_event.set()


async def run() -> None:
    await asyncio.get_running_loop().run_in_executor(
        ProcessPoolExecutor(), start_server
    )


if __name__ == "__main__":
    asyncio.run(run())
