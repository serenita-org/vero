from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from aiohttp.test_utils import TestClient
from aiohttp.web_app import Application

from api.keymanager.api import _create_app
from args import CLIArgs
from providers import Keymanager


@pytest.fixture
async def test_client(
    aiohttp_client: Callable[..., Awaitable[TestClient[Any, Application]]],
    keymanager: Keymanager,
    cli_args: CLIArgs,
) -> TestClient[Any, Application]:
    app = _create_app(keymanager=keymanager, cli_args=cli_args)
    return await aiohttp_client(
        app, headers={"Authorization": f"Bearer {app['bearer_token']}"}
    )
