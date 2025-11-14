import re
from collections.abc import AsyncGenerator
from copy import deepcopy

import pytest
from aioresponses import CallbackResult, aioresponses

from args import CLIArgs
from providers import MultiBeaconNode, Vero


@pytest.fixture
async def vero_three_nodes(cli_args: CLIArgs) -> Vero:
    _cli_args_override = deepcopy(cli_args)
    _cli_args_override.beacon_node_urls = [
        "http://beacon-node-a:1234",
        "http://beacon-node-b:1234",
        "http://beacon-node-c:1234",
    ]
    _cli_args_override.attestation_consensus_threshold = 2
    return Vero(cli_args=_cli_args_override)


@pytest.fixture
async def multi_beacon_node_three_inited_nodes(
    mocked_fork_response: dict,  # type: ignore[type-arg]
    mocked_genesis_response: dict,  # type: ignore[type-arg]
    vero_three_nodes: Vero,
) -> AsyncGenerator[MultiBeaconNode, None]:
    mbn = MultiBeaconNode(vero=vero_three_nodes)
    with aioresponses() as m:
        m.get(
            re.compile(r"http://beacon-node-\w:1234/eth/v1/beacon/states/head/fork"),
            callback=lambda *args, **kwargs: CallbackResult(
                payload=mocked_fork_response,
            ),
            repeat=True,
        )
        m.get(
            re.compile(r"http://beacon-node-\w:1234/eth/v1/beacon/genesis"),
            callback=lambda *args, **kwargs: CallbackResult(
                payload=mocked_genesis_response,
            ),
            repeat=True,
        )
        m.get(
            re.compile(r"http://beacon-node-\w:1234/eth/v1/config/spec"),
            callback=lambda *args, **kwargs: CallbackResult(
                payload=dict(data=vero_three_nodes.spec.to_obj()),
            ),
            repeat=True,
        )
        m.get(
            re.compile(r"http://beacon-node-\w:1234/eth/v1/node/version"),
            callback=lambda *args, **kwargs: CallbackResult(
                payload=dict(data=dict(version="beacon-node/test")),
            ),
            repeat=True,
        )
        await mbn.initialize()
    yield mbn
    for beacon_node in mbn.beacon_nodes:
        if not beacon_node.client_session.closed:
            await beacon_node.client_session.close()
