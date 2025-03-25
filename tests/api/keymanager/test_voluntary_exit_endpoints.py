from typing import Any

import milagro_bls_binding as bls
import msgspec.json
import pytest
from aiohttp.test_utils import TestClient
from aiohttp.web_app import Application

from schemas import SchemaKeymanagerAPI


@pytest.mark.enable_keymanager_api
async def test_voluntary_exit_lifecycle(
    validator_privkeys: list[bytes],
    test_client: TestClient[Any, Application],
) -> None:
    # Import a key
    pubkey = "0x" + bls.SkToPk(next(iter(validator_privkeys))).hex()
    remote_signer_url = "http://remote-signer:9000"

    resp = await test_client.post(
        "/eth/v1/remotekeys",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.ImportRemoteKeysRequest(
                remote_keys=[
                    SchemaKeymanagerAPI.RemoteKey(pubkey=pubkey, url=remote_signer_url)
                ]
            )
        ),
    )
    assert resp.status == 200

    # Get its voluntary exit message
    resp = await test_client.post(f"/eth/v1/validator/{pubkey}/voluntary_exit")
    assert resp.status == 200
    # Decoding the message is successful
    _ = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.SignVoluntaryExitResponse
    )


@pytest.mark.enable_keymanager_api
async def test_nonexistent_pubkey(test_client: TestClient[Any, Application]) -> None:
    nonexistent_pubkey = "0x" + "a" * 96

    # Attempt to get its voluntary exit message
    resp = await test_client.post(
        f"/eth/v1/validator/{nonexistent_pubkey}/voluntary_exit"
    )
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{nonexistent_pubkey}')"
