import stat
from collections.abc import Awaitable, Callable
from typing import Any

import msgspec
import pytest
from aiohttp.test_utils import TestClient
from aiohttp.web_app import Application

from api.keymanager.api import _create_app, _get_bearer_token_value
from args import CLIArgs
from providers import Keymanager
from schemas import SchemaKeymanagerAPI


async def test_bearer_auth(
    aiohttp_client: Callable[[Application], Awaitable[TestClient[Any, Application]]],
    keymanager: Keymanager,
    cli_args: CLIArgs,
) -> None:
    app = _create_app(keymanager=keymanager, cli_args=cli_args)
    test_client = await aiohttp_client(app)
    assert len(test_client.app["bearer_token"]) == 64

    # Make a request without a value for the Authorization header
    resp = await test_client.get(
        "/eth/v1/remotekeys",
    )
    assert resp.status == 401

    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ErrorResponse
    )
    assert response.message == "No value provided for Authorization header"

    # Make a request with a wrong value for the Authorization header
    resp = await test_client.get(
        "/eth/v1/remotekeys", headers={"Authorization": "Bearer wrong-value"}
    )
    assert resp.status == 403

    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ErrorResponse
    )
    assert response.message == "Invalid value provided for Authorization header"

    # Make a request with the correct value for the Authorization header
    resp = await test_client.get(
        "/eth/v1/remotekeys",
        headers={"Authorization": f"Bearer {test_client.app['bearer_token']}"},
    )
    assert resp.status == 200


async def test_bad_request_data_format(
    test_client: TestClient[Any, Application],
    keymanager: Keymanager,
    cli_args: CLIArgs,
) -> None:
    # Submitting data that does not conform to the spec
    # causes a 400 status code to be returned along with
    # an explanatory message in JSON format.
    resp = await test_client.post(
        "/eth/v1/remotekeys",
        json=dict(remote_keys=[dict(pubkey="0xinvalid", url="http://...")]),
    )
    assert resp.status == 400
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ErrorResponse
    )
    assert (
        response.message
        == "ValidationError(\"Expected `str` matching regex '^0x[a-fA-F0-9]{96}$' - at `$.remote_keys[0].pubkey`\")"
    )


async def test_bad_request_malformed_json(
    test_client: TestClient[Any, Application],
) -> None:
    resp = await test_client.post(
        "/eth/v1/remotekeys",
        data='{"remote_keys": [',
    )
    assert resp.status == 400
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ErrorResponse
    )
    assert response.message == "DecodeError('Input data was truncated')"


def test_get_bearer_token_value_creates_owner_only_token_file(
    cli_args: CLIArgs,
) -> None:
    assert not cli_args.keymanager_api_token_file_path.exists()
    token = _get_bearer_token_value(cli_args=cli_args)

    assert cli_args.keymanager_api_token_file_path.read_text() == token
    assert stat.S_IMODE(cli_args.keymanager_api_token_file_path.stat().st_mode) == 0o600


def test_get_bearer_token_value_rejects_insecure_existing_token_file(
    cli_args: CLIArgs,
) -> None:
    cli_args.keymanager_api_token_file_path.write_text("token-value")
    cli_args.keymanager_api_token_file_path.chmod(0o644)

    with pytest.raises(
        PermissionError,
        match="must have permissions set to 0o600",
    ):
        _get_bearer_token_value(cli_args=cli_args)
