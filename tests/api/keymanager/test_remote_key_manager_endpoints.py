import random
from typing import Any

import msgspec.json
from aiohttp.test_utils import TestClient
from aiohttp.web_app import Application

from schemas import SchemaKeymanagerAPI


async def test_remote_keymanager_lifecycle(
    test_client: TestClient[Any, Application],
) -> None:
    # List the keys - there should be 0 at this point
    resp = await test_client.get("/eth/v1/remotekeys")
    assert resp.status == 200
    response_list_1 = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ListRemoteKeysResponse
    )
    assert len(response_list_1.data) == 0

    # Import some keys
    keys_to_add = [
        SchemaKeymanagerAPI.RemoteKey(pubkey="0x" + "a" * 96, url="http://whatever"),
        SchemaKeymanagerAPI.RemoteKey(pubkey="0x" + "b" * 96, url="http://whatever"),
    ]
    resp = await test_client.post(
        "/eth/v1/remotekeys",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.ImportRemoteKeysRequest(remote_keys=keys_to_add)
        ),
    )
    assert resp.status == 200
    response_import = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ImportRemoteKeysResponse
    )
    assert len(response_import.data) == 2
    assert all(
        d.status == SchemaKeymanagerAPI.ImportStatus.IMPORTED
        for d in response_import.data
    )

    # List the keys again - the keys should now show up
    resp = await test_client.get("/eth/v1/remotekeys")
    assert resp.status == 200
    response_list_2 = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ListRemoteKeysResponse
    )
    assert len(response_list_2.data) == 2

    # Try to import the same keys again
    # -> their import status should be reported as DUPLICATE
    resp = await test_client.post(
        "/eth/v1/remotekeys",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.ImportRemoteKeysRequest(remote_keys=keys_to_add)
        ),
    )
    assert resp.status == 200
    response_import_2 = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ImportRemoteKeysResponse
    )
    assert all(
        d.status == SchemaKeymanagerAPI.ImportStatus.DUPLICATE
        for d in response_import_2.data
    )

    # Delete one of the keys
    key_to_delete: SchemaKeymanagerAPI.RemoteKey = random.choice(keys_to_add)
    resp = await test_client.delete(
        "/eth/v1/remotekeys",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.DeleteRemoteKeysRequest(pubkeys=[key_to_delete.pubkey])
        ),
    )
    assert resp.status == 200
    response_delete = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.DeleteRemoteKeysResponse
    )
    assert len(response_delete.data) == 1
    assert all(
        d.status == SchemaKeymanagerAPI.DeleteStatus.DELETED
        for d in response_delete.data
    )

    # List the keys again. Only one key should remain now - the one we did not delete
    resp = await test_client.get("/eth/v1/remotekeys")
    assert resp.status == 200
    response_list_3 = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.ListRemoteKeysResponse
    )
    assert len(response_list_3.data) == 1
    assert response_list_3.data[0].pubkey != key_to_delete.pubkey


async def test_nonexistent_pubkey(test_client: TestClient[Any, Application]) -> None:
    nonexistent_pubkey = "0x" + "a" * 96

    # Attempt to delete it
    resp = await test_client.delete(
        "/eth/v1/remotekeys",
        data=msgspec.json.encode(
            SchemaKeymanagerAPI.DeleteRemoteKeysRequest(pubkeys=[nonexistent_pubkey])
        ),
    )
    assert resp.status == 200
    response = msgspec.json.decode(
        await resp.text(), type=SchemaKeymanagerAPI.DeleteRemoteKeysResponse
    )
    assert len(response.data) == 1
    assert all(
        d.status == SchemaKeymanagerAPI.DeleteStatus.NOT_FOUND for d in response.data
    )
