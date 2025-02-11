from collections.abc import Awaitable, Callable
from typing import Any

import msgspec.json
import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient
from aiohttp.web_app import Application

from api.keymanager.endpoints import routes
from schemas import SchemaKeymanagerAPI


@pytest.fixture
async def cli(
    aiohttp_client: Callable[[Application], Awaitable[TestClient[Any, Application]]],
) -> TestClient[Any, Application]:
    app = web.Application()
    app.add_routes(routes)
    return await aiohttp_client(app)


async def test_remote_keys_get(cli: TestClient[Any, Application]) -> None:
    resp = await cli.get("/eth/v1/remotekeys")
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ListRemoteKeysResponse
    )
    assert len(response.data) == 2


async def test_remote_keys_post(cli: TestClient[Any, Application]) -> None:
    resp = await cli.post(
        "/eth/v1/remotekeys",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.ImportRemoteKeysRequest(
                remote_keys=[
                    SchemaKeymanagerAPI.RemoteKey(pubkey="0xa", url="http://whatever"),
                    SchemaKeymanagerAPI.RemoteKey(pubkey="0xb", url="http://whatever"),
                    SchemaKeymanagerAPI.RemoteKey(pubkey="0xc", url="http://whatever"),
                ]
            )
        ),
    )
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ImportRemoteKeysResponse
    )
    assert len(response.data) == 3


async def test_remote_keys_delete(cli: TestClient[Any, Application]) -> None:
    resp = await cli.delete(
        "/eth/v1/remotekeys",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.DeleteRemoteKeysRequest(
                pubkeys=[
                    "0xa",
                    "0xb",
                    "0xc",
                ]
            )
        ),
    )
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.DeleteRemoteKeysResponse
    )
    assert len(response.data) == 3
