from typing import Any

import pytest
from aiohttp.test_utils import TestClient
from aiohttp.web_app import Application

from args import CLIArgs, get_parser
from providers import Keymanager
from schemas.keymanager_api import RemoteKey

PUBKEY = "0x" + "ab" * 48
PATH = f"/eth/v1/validator/{PUBKEY}/builder_config"
pytestmark = pytest.mark.parametrize("enable_keymanager_api", [True], indirect=True)


async def test_omitted_execution_payment_cap_defaults_to_zero(
    test_client: TestClient[Any, Application], keymanager: Keymanager, cli_args: CLIArgs
) -> None:
    # Other API tests deliberately use a nonzero CLI override of 123.
    cli_args.builder_max_execution_payment = get_parser().get_default(
        "builder_max_execution_payment"
    )
    assert cli_args.builder_max_execution_payment == 0
    cli_args.builder_urls = ["https://default.example"]
    await keymanager.import_remote_keys([RemoteKey(PUBKEY, "http://signer")])
    response = await test_client.get(PATH)
    assert (await response.json())["data"]["builders"][0][
        "max_execution_payment"
    ] == "0"
    response = await test_client.post(
        PATH, json={"builders": [{"url": "https://custom.example"}]}
    )
    assert response.status == 202
    response = await test_client.get(PATH)
    assert (await response.json())["data"]["builders"][0][
        "max_execution_payment"
    ] == "0"


async def test_builder_config_lifecycle(
    test_client: TestClient[Any, Application], keymanager: Keymanager, cli_args: CLIArgs
) -> None:
    cli_args.builder_urls = ["https://default.example"]
    await keymanager.import_remote_keys([RemoteKey(PUBKEY, "http://signer")])
    resp = await test_client.get(PATH)
    defaults = (await resp.json())["data"]
    assert defaults == {
        "min_bid": "0",
        "builder_boost_factor": "90",
        "builders": [
            {
                "url": "https://default.example",
                "auth_data": "0x" + b"default.example".hex(),
                "builder_pubkeys": [],
                "max_execution_payment": "123",
                "min_bid": "0",
                "builder_boost_factor": "90",
            }
        ],
    }
    config = {
        "min_bid": "7",
        "builder_boost_factor": "120",
        "builders": [
            {
                "url": "https://custom.example",
                "auth_data": "0xAABB",
                "max_execution_payment": "0",
            },
            {
                "url": "https://custom.example",
                "auth_data": "0xcc",
                "min_bid": "11",
                "builder_boost_factor": "0",
            },
        ],
    }
    assert (await test_client.post(PATH, json=config)).status == 202
    resp = await test_client.get(PATH)
    resolved = (await resp.json())["data"]
    assert resolved["builders"][0]["auth_data"] == "0xaabb"
    assert resolved["builders"][0]["min_bid"] == "7"
    assert resolved["builders"][0]["builder_boost_factor"] == "120"
    assert resolved["builders"][1]["min_bid"] == "11"
    assert resolved["builders"][1]["max_execution_payment"] == "123"
    assert resolved["builders"][1]["builder_boost_factor"] == "0"

    # POST replaces the entire document; omitted builders inherit the global list.
    assert (await test_client.post(PATH, json={"min_bid": "9"})).status == 202
    resolved = (await (await test_client.get(PATH)).json())["data"]
    assert resolved["builder_boost_factor"] == "90"
    assert resolved["builders"][0]["url"] == "https://default.example"
    assert resolved["builders"][0]["min_bid"] == "9"

    # An empty list disables direct builders, while {} and DELETE restore defaults.
    assert (await test_client.post(PATH, json={"builders": []})).status == 202
    assert (await (await test_client.get(PATH)).json())["data"]["builders"] == []
    assert (await test_client.post(PATH, json={})).status == 202
    assert (await (await test_client.get(PATH)).json())["data"] == defaults
    assert (await test_client.delete(PATH)).status == 204
    assert (await test_client.delete(PATH)).status == 204
    assert (await (await test_client.get(PATH)).json())["data"] == defaults


@pytest.mark.parametrize(
    "config",
    [
        None,
        [],
        {"min_bid": None},
        {"min_bid": 1},
        {"min_bid": "-1"},
        {"min_bid": str(2**64)},
        {"builder_boost_factor": str(2**64)},
        {"builders": None},
        {"builders": [{}]},
        {"builders": [{"url": ""}]},
        {"builders": [{"url": "builder.example"}]},
        {"builders": [{"url": "https://builder bad"}]},
        {"builders": [{"url": "https://builder.example\n"}]},
        {"builders": [{"url": "ftp://builder.example"}]},
        {"builders": [{"url": "http://builder.example:bad"}]},
        {"builders": [{"url": "http://" + "x" * 2048}]},
        {"builders": [{"url": "http://builder", "auth_data": "0x"}]},
        {"builders": [{"url": "http://builder", "auth_data": "0xabc"}]},
        {"builders": [{"url": "http://builder", "auth_data": "0x" + "00" * 4097}]},
        {"builders": [{"url": "http://builder", "builder_pubkeys": ["0x123"]}]},
        {"builders": [{"url": "http://builder", "builder_pubkeys": [PUBKEY] * 65}]},
        {"builders": [{"url": "http://builder", "max_execution_payment": str(2**64)}]},
        {"builders": [{"url": "http://builder", "min_bid": str(2**64)}]},
        {"builders": [{"url": "http://builder", "builder_boost_factor": str(2**64)}]},
        {"builders": [{"url": f"http://builder-{i}"} for i in range(65)]},
        {"builders": [{"url": "http://builder"}, {"url": "http://builder"}]},
        {
            "builders": [
                {"url": "http://builder", "auth_data": "0xAB"},
                {"url": "http://builder", "auth_data": "0xab"},
            ]
        },
        {
            "builders": [
                {"url": "http://builder"},
                {"url": "http://builder", "auth_data": "0x" + b"builder".hex()},
            ]
        },
    ],
)
async def test_invalid_config_is_atomic(
    test_client: TestClient[Any, Application], keymanager: Keymanager, config: Any
) -> None:
    await keymanager.import_remote_keys([RemoteKey(PUBKEY, "http://signer")])
    assert (await test_client.post(PATH, json={"min_bid": "42"})).status == 202
    response = (
        await test_client.post(PATH, data="null")
        if config is None
        else await test_client.post(PATH, json=config)
    )
    assert response.status == 400
    assert (await (await test_client.get(PATH)).json())["data"]["min_bid"] == "42"


async def test_not_found_auth_and_bad_path(
    test_client: TestClient[Any, Application],
) -> None:
    for method in ("get", "post", "delete"):
        response = await test_client.request(method, PATH, json={})
        assert response.status == 404
        response = await test_client.request(
            method, PATH, json={}, headers={"Authorization": "Bearer invalid"}
        )
        assert response.status == 403
        response = await test_client.request(
            method, "/eth/v1/validator/invalid/builder_config", json={}
        )
        assert response.status == 400
    assert (await test_client.post(PATH, data="{")).status == 400


async def test_persistence_and_remote_key_deletion(
    test_client: TestClient[Any, Application], keymanager: Keymanager, cli_args: CLIArgs
) -> None:
    await keymanager.import_remote_keys([RemoteKey(PUBKEY, "http://signer")])
    assert (await test_client.post(PATH, json={"min_bid": "8"})).status == 202
    restarted = Keymanager(
        db=keymanager.db,
        multi_beacon_node=keymanager.multi_beacon_node,
        vero=keymanager.vero,
        process_pool_executor=keymanager.process_pool_executor,
    )
    assert restarted.get_builder_config(PUBKEY).min_bid == "8"
    cli_args.builder_min_bid = 10
    cli_args.builder_boost_factor = 130
    assert restarted.get_builder_config(PUBKEY).min_bid == "8"
    assert restarted.get_builder_config(PUBKEY).builder_boost_factor == "130"
    await keymanager.delete_remote_keys([PUBKEY])
    await keymanager.import_remote_keys([RemoteKey(PUBKEY, "http://signer")])
    assert (await (await test_client.get(PATH)).json())["data"]["min_bid"] == "10"


async def test_maximum_values_and_resubmitted_defaults(
    test_client: TestClient[Any, Application], keymanager: Keymanager, cli_args: CLIArgs
) -> None:
    await keymanager.import_remote_keys([RemoteKey(PUBKEY, "http://signer")])
    max_uint64 = str(2**64 - 1)
    config = {
        "min_bid": max_uint64,
        "builder_boost_factor": max_uint64,
        "builders": [
            {
                "url": "https://builder.example/"
                + "x" * (2048 - len("https://builder.example/")),
                "auth_data": "0x" + "ff" * 4096,
                "builder_pubkeys": [PUBKEY] * 64,
                "max_execution_payment": max_uint64,
            }
        ],
    }
    assert (await test_client.post(PATH, json=config)).status == 202
    assert (await (await test_client.get(PATH)).json())["data"]["builders"][0][
        "min_bid"
    ] == max_uint64
    config = {"builders": [{"url": f"http://builder-{i}"} for i in range(64)]}
    assert (await test_client.post(PATH, json=config)).status == 202
    assert len((await (await test_client.get(PATH)).json())["data"]["builders"]) == 64

    assert (await test_client.post(PATH, json={})).status == 202
    resolved = (await (await test_client.get(PATH)).json())["data"]
    assert (await test_client.post(PATH, json=resolved)).status == 202
    cli_args.builder_min_bid = 555
    cli_args.builder_boost_factor = 150
    assert (await (await test_client.get(PATH)).json())["data"] == resolved
    assert (await test_client.post(PATH, json={})).status == 202
    assert (await (await test_client.get(PATH)).json())["data"]["min_bid"] == "555"
