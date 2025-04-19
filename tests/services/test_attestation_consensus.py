import asyncio
import re
from collections.abc import AsyncGenerator

import pytest
from aioresponses import CallbackResult, aioresponses
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs
from providers import BeaconChain, MultiBeaconNode, RemoteSigner
from services import AttestationService, ValidatorStatusTrackerService
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
        cli_args=cli_args,
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


@pytest.fixture
async def attestation_service(
    multi_beacon_node: MultiBeaconNode,
    beacon_chain: BeaconChain,
    remote_signer: RemoteSigner,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
    cli_args: CLIArgs,
) -> AttestationService:
    validator_status_tracker_service = ValidatorStatusTrackerService(
        multi_beacon_node=multi_beacon_node,
        beacon_chain=beacon_chain,
        remote_signer=remote_signer,
        scheduler=scheduler,
        task_manager=task_manager,
    )
    await validator_status_tracker_service.initialize()

    return AttestationService(
        multi_beacon_node=multi_beacon_node,
        beacon_chain=beacon_chain,
        remote_signer=remote_signer,
        validator_status_tracker_service=validator_status_tracker_service,
        scheduler=scheduler,
        task_manager=task_manager,
        cli_args=cli_args,
    )


async def test_attest_no_head_event(
    attestation_service: AttestationService, beacon_chain: BeaconChain
) -> None:
    await attestation_service.update_duties()
    await attestation_service.on_new_slot(
        slot=beacon_chain.current_slot, is_new_epoch=False
    )
    await asyncio.sleep(1)
