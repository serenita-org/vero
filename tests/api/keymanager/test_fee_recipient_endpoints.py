from typing import Any

import msgspec.json
from aiohttp.test_utils import TestClient
from aiohttp.web_app import Application

from providers import Keymanager
from schemas import SchemaKeymanagerAPI


async def test_fee_recipient_lifecycle(
    keymanager: Keymanager,
    test_client: TestClient[Any, Application],
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

    # Its fee recipient should not be set yet
    resp = await test_client.get(f"/eth/v1/validator/{pubkey}/feerecipient")
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ListFeeRecipientResponse
    )
    assert response.data.pubkey == pubkey
    assert response.data.ethaddress is None
    assert keymanager.pubkey_to_fee_recipient_override.get(pubkey) is None

    # Set its fee recipient
    fee_recipient_address = "0x" + "a" * 40
    resp = await test_client.post(
        f"/eth/v1/validator/{pubkey}/feerecipient",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.SetFeeRecipientRequest(
                ethaddress=fee_recipient_address,
            )
        ),
    )
    assert resp.status == 202

    # Its fee recipient should be set now
    resp = await test_client.get(f"/eth/v1/validator/{pubkey}/feerecipient")
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ListFeeRecipientResponse
    )
    assert response.data.pubkey == pubkey
    assert response.data.ethaddress == fee_recipient_address
    assert (
        keymanager.pubkey_to_fee_recipient_override.get(pubkey) == fee_recipient_address
    )

    # Delete its configured fee recipient
    resp = await test_client.delete(f"/eth/v1/validator/{pubkey}/feerecipient")
    assert resp.status == 204

    # Its fee recipient should be unset again
    resp = await test_client.get(f"/eth/v1/validator/{pubkey}/feerecipient")
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ListFeeRecipientResponse
    )
    assert response.data.pubkey == pubkey
    assert response.data.ethaddress is None
    assert keymanager.pubkey_to_fee_recipient_override.get(pubkey) is None


async def test_nonexistent_pubkey(test_client: TestClient[Any, Application]) -> None:
    nonexistent_pubkey = "0x" + "a" * 96

    # Get its fee recipient
    resp = await test_client.get(f"/eth/v1/validator/{nonexistent_pubkey}/feerecipient")
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{nonexistent_pubkey}')"

    # Set its fee recipient
    fee_recipient_address = "0x" + "a" * 40
    resp = await test_client.post(
        f"/eth/v1/validator/{nonexistent_pubkey}/feerecipient",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.SetFeeRecipientRequest(
                ethaddress=fee_recipient_address,
            )
        ),
    )
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{nonexistent_pubkey}')"

    # Delete its fee recipient
    resp = await test_client.delete(
        f"/eth/v1/validator/{nonexistent_pubkey}/feerecipient"
    )
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{nonexistent_pubkey}')"


async def test_bad_request(test_client: TestClient[Any, Application]) -> None:
    invalid_pubkey = "0x" + "x" * 96

    # Get its fee recipient
    resp = await test_client.get(f"/eth/v1/validator/{invalid_pubkey}/feerecipient")
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{invalid_pubkey}')"
