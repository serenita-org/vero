from typing import TYPE_CHECKING, Any

import msgspec.json

from schemas import SchemaKeymanagerAPI

if TYPE_CHECKING:
    from aiohttp.test_utils import TestClient
    from aiohttp.web_app import Application

    from providers import Keymanager


async def test_gas_limit_lifecycle(
    keymanager: Keymanager, test_client: TestClient[Any, Application]
) -> None:
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
    # We return the default gas limit value provided via CLI arguments if
    # it was not overridden via the Keymanager API
    assert response.data.gas_limit == "30000000"
    assert keymanager.pubkey_to_gas_limit_override.get(pubkey) is None

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
    assert keymanager.pubkey_to_gas_limit_override.get(pubkey) == gas_limit_value

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
    # We return the default gas limit value provided via CLI arguments if
    # it was not overridden via the Keymanager API
    assert response.data.gas_limit == "30000000"
    assert keymanager.pubkey_to_gas_limit_override.get(pubkey) is None


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
