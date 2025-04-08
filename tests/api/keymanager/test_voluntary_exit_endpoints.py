from typing import Any

import msgspec.json
import pytest
from aiohttp.test_utils import TestClient
from aiohttp.web_app import Application

from schemas import SchemaKeymanagerAPI
from schemas.validator import ValidatorIndexPubkey


@pytest.mark.parametrize(
    argnames=("exit_epoch"),
    argvalues=[
        pytest.param(
            None,
            id="Not provided -> defaults to current epoch",
        ),
        pytest.param(
            0,
            id="Genesis - epoch 0",
        ),
        pytest.param(
            1_000,
            id="Future - epoch 1,000",
        ),
    ],
)
async def test_voluntary_exit_lifecycle(
    exit_epoch: int | None,
    random_active_validator: ValidatorIndexPubkey,
    test_client: TestClient[Any, Application],
    remote_signer_url: str,
) -> None:
    # Import a key
    pubkey = random_active_validator.pubkey

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
    params = {}
    if exit_epoch is not None:
        params.update(dict(epoch=exit_epoch))

    resp = await test_client.post(
        f"/eth/v1/validator/{pubkey}/voluntary_exit", params=params
    )
    assert resp.status == 200
    # Decoding the message is successful
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.SignVoluntaryExitResponse
    )
    if exit_epoch is not None:
        assert int(response.data.message.epoch) == exit_epoch


async def test_pubkey_inactive(test_client: TestClient[Any, Application]) -> None:
    """
    Validator pubkey that is not active on the beacon chain.
    """
    nonexistent_pubkey = "0x" + "a" * 96

    # Attempt to get its voluntary exit message
    resp = await test_client.post(
        f"/eth/v1/validator/{nonexistent_pubkey}/voluntary_exit"
    )
    assert resp.status == 500
    data = await resp.json()
    assert (
        data["message"]
        == f"ValueError('Failed to find validator index for pubkey: {nonexistent_pubkey}')"
    )


async def test_pubkey_not_registered(
    random_active_validator: ValidatorIndexPubkey,
    test_client: TestClient[Any, Application],
) -> None:
    """
    Validator pubkey that was never registered with the Keymanager API
    """
    # Attempt to get its voluntary exit message
    resp = await test_client.post(
        f"/eth/v1/validator/{random_active_validator.pubkey}/voluntary_exit"
    )
    assert resp.status == 500
    data = await resp.json()
    assert data["message"] == f"PubkeyNotFound('{random_active_validator.pubkey}')"
