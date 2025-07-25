import re
from collections.abc import AsyncGenerator
from copy import deepcopy

import pytest
from aioresponses import CallbackResult, aioresponses
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs
from providers import MultiBeaconNode
from spec.base import SpecElectra
from tasks import TaskManager


@pytest.fixture
async def multi_beacon_node_three_inited_nodes(
    mocked_fork_response: dict,  # type: ignore[type-arg]
    mocked_genesis_response: dict,  # type: ignore[type-arg]
    spec: SpecElectra,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
    cli_args: CLIArgs,
) -> AsyncGenerator[MultiBeaconNode, None]:
    _cli_args_override = deepcopy(cli_args)
    _cli_args_override.attestation_consensus_threshold = 2
    mbn = MultiBeaconNode(
        beacon_node_urls=[
            "http://beacon-node-a:1234",
            "http://beacon-node-b:1234",
            "http://beacon-node-c:1234",
        ],
        beacon_node_urls_proposal=[],
        spec=spec,
        scheduler=scheduler,
        task_manager=task_manager,
        cli_args=_cli_args_override,
    )
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
                payload=dict(data=spec.to_obj()),
            ),
            repeat=True,
        )
        m.get(
            re.compile(r"http://beacon-node-\w:1234/eth/v1/node/version"),
            callback=lambda *args, **kwargs: CallbackResult(
                payload=dict(data=dict(version="vero/test")),
            ),
            repeat=True,
        )
        await mbn.initialize()
    yield mbn
    for beacon_node in mbn.beacon_nodes:
        if not beacon_node.client_session.closed:
            await beacon_node.client_session.close()
