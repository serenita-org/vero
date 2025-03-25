from typing import Any

import msgspec.json
import pytest
from aiohttp.test_utils import TestClient
from aiohttp.web_app import Application

from schemas import SchemaKeymanagerAPI


@pytest.mark.enable_keymanager_api
async def test_gas_limit_lifecycle(test_client: TestClient[Any, Application]) -> None:
    # Import a key
    pubkey = "0x" + "a" * 96
    resp = await test_client.post(
        "/eth/v1/remotekeys",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.ImportRemoteKeysRequest(
                remote_keys=[
                    SchemaKeymanagerAPI.RemoteKey(pubkey=pubkey, url="http://whatever"),
                ]
            )
        ),
    )
    assert resp.status == 200

    # Its gas limit value should not be set yet
    resp = await test_client.get(f"/eth/v1/validator/{pubkey}/gas_limit")
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ListGasLimitResponse
    )
    assert response.data.pubkey == pubkey
    assert response.data.gas_limit is None

    # Set its gas limit value
    gas_limit_value = "20000000"
    resp = await test_client.post(
        f"/eth/v1/validator/{pubkey}/gas_limit",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.SetGasLimitRequest(
                gas_limit=gas_limit_value,
            )
        ),
    )
    assert resp.status == 202

    # Its gas limit value should be set now
    resp = await test_client.get(f"/eth/v1/validator/{pubkey}/gas_limit")
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ListGasLimitResponse
    )
    assert response.data.pubkey == pubkey
    assert response.data.gas_limit == gas_limit_value

    # Delete its configured gas limit value
    resp = await test_client.delete(f"/eth/v1/validator/{pubkey}/gas_limit")
    assert resp.status == 204

    # Its gas limit value should be unset again
    resp = await test_client.get(f"/eth/v1/validator/{pubkey}/gas_limit")
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ListGasLimitResponse
    )
    assert response.data.pubkey == pubkey
    assert response.data.gas_limit is None


async def test_nonexistent_pubkey(test_client: TestClient[Any, Application]) -> None:
    nonexistent_pubkey = "0x" + "a" * 96

    # Get its gas limit value
    resp = await test_client.get(f"/eth/v1/validator/{nonexistent_pubkey}/gas_limit")
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{nonexistent_pubkey}')"

    # Set its gas limit value
    gas_limit_value = "20000000"
    resp = await test_client.post(
        f"/eth/v1/validator/{nonexistent_pubkey}/gas_limit",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.SetGasLimitRequest(
                gas_limit=gas_limit_value,
            )
        ),
    )
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{nonexistent_pubkey}')"

    # Delete its gas limit value
    resp = await test_client.delete(f"/eth/v1/validator/{nonexistent_pubkey}/gas_limit")
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{nonexistent_pubkey}')"
