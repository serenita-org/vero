from typing import Any

import msgspec.json
from aiohttp.test_utils import TestClient
from aiohttp.web_app import Application

from providers import Keymanager
from schemas import SchemaKeymanagerAPI


async def test_graffiti_lifecycle(
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

    # Its graffiti should not be set yet
    resp = await test_client.get(f"/eth/v1/validator/{pubkey}/graffiti")
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.GraffitiResponse
    )
    assert response.data.pubkey == pubkey
    assert response.data.graffiti is None
    assert keymanager.pubkey_to_graffiti_override.get(pubkey) is None

    # Set its graffiti
    graffiti_value = "Vero rocks"
    resp = await test_client.post(
        f"/eth/v1/validator/{pubkey}/graffiti",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.SetGraffitiRequest(
                graffiti=graffiti_value,
            )
        ),
    )
    assert resp.status == 202

    # Its graffiti should be set now
    resp = await test_client.get(f"/eth/v1/validator/{pubkey}/graffiti")
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.GraffitiResponse
    )
    assert response.data.pubkey == pubkey
    assert response.data.graffiti == graffiti_value
    assert keymanager.pubkey_to_graffiti_override.get(pubkey) == graffiti_value

    # Delete its configured graffiti
    resp = await test_client.delete(f"/eth/v1/validator/{pubkey}/graffiti")
    assert resp.status == 204

    # Its graffiti should be unset again
    resp = await test_client.get(f"/eth/v1/validator/{pubkey}/graffiti")
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.GraffitiResponse
    )
    assert response.data.pubkey == pubkey
    assert response.data.graffiti is None
    assert keymanager.pubkey_to_graffiti_override.get(pubkey) is None


async def test_nonexistent_pubkey(test_client: TestClient[Any, Application]) -> None:
    nonexistent_pubkey = "0x" + "a" * 96

    # Get its graffiti
    resp = await test_client.get(f"/eth/v1/validator/{nonexistent_pubkey}/graffiti")
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{nonexistent_pubkey}')"

    # Set its graffiti
    graffiti = "Vero rocks"
    resp = await test_client.post(
        f"/eth/v1/validator/{nonexistent_pubkey}/graffiti",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.SetGraffitiRequest(graffiti=graffiti)
        ),
    )
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{nonexistent_pubkey}')"

    # Delete its graffiti
    resp = await test_client.delete(f"/eth/v1/validator/{nonexistent_pubkey}/graffiti")
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{nonexistent_pubkey}')"


async def test_set_emoji(test_client: TestClient[Any, Application]) -> None:
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

    # Set its graffiti
    graffiti_value = "🔥 Vero 🔥"
    resp = await test_client.post(
        f"/eth/v1/validator/{pubkey}/graffiti",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.SetGraffitiRequest(graffiti=graffiti_value)
        ),
    )
    assert resp.status == 202

    # Its graffiti should be set now
    resp = await test_client.get(f"/eth/v1/validator/{pubkey}/graffiti")
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.GraffitiResponse
    )
    assert response.data.graffiti == graffiti_value


async def test_set_graffiti_too_long(
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

    # Set its graffiti
    graffiti_value = "🔥🔥🔥🔥🔥🔥 Vero 🔥🔥🔥🔥🔥🔥"
    resp = await test_client.post(
        f"/eth/v1/validator/{pubkey}/graffiti",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.SetGraffitiRequest(graffiti=graffiti_value)
        ),
    )
    assert resp.status == 500
    response = msgspec.json.decode(await resp.text())
    assert (
        "Encoded graffiti exceeds the maximum length of 32 bytes" in response["message"]
    )
    assert keymanager.pubkey_to_graffiti_override.get(pubkey) is None
