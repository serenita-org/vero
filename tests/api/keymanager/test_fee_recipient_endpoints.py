from typing import TYPE_CHECKING, Any

import msgspec.json

from schemas import SchemaKeymanagerAPI

if TYPE_CHECKING:
    from aiohttp.test_utils import TestClient
    from aiohttp.web_app import Application

    from providers import Keymanager


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
    # We return the default fee recipient provided via CLI arguments if
    # it was not overridden via the Keymanager API
    assert response.data.ethaddress == "0xfee0000000000000000000000000000000000000"
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
    # We return the default fee recipient provided via CLI arguments if
    # it was not overridden via the Keymanager API
    assert response.data.ethaddress == "0xfee0000000000000000000000000000000000000"
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


async def test_zero_address_as_fr(test_client: TestClient[Any, Application]) -> None:
    pubkey = "0x" + "a" * 96
    zero_address = "0x" + "0" * 40

    # Attempt to set the fee recipient to the 0x00 address
    resp = await test_client.post(
        f"/eth/v1/validator/{pubkey}/feerecipient",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.SetFeeRecipientRequest(
                ethaddress=zero_address,
            )
        ),
    )
    assert resp.status == 400
    data = await resp.json()
    assert (
        data["message"]
        == "Cannot specify the 0x00 fee recipient address through the API."
    )
