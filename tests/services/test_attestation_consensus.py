import asyncio
import re
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import nullcontext
from copy import deepcopy
from typing import Any

import pytest
from aioresponses import CallbackResult, aioresponses
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs
from providers import BeaconChain, MultiBeaconNode
from schemas import SchemaBeaconAPI
from schemas.validator import ValidatorIndexPubkey
from services import AttestationService, ValidatorStatusTrackerService
from spec.attestation import AttestationData
from spec.base import SpecElectra
from tasks import TaskManager


@pytest.fixture(scope="session")
def _cli_args_for_file(cli_args: CLIArgs) -> CLIArgs:
    _cli_args_for_file = deepcopy(cli_args)
    _cli_args_for_file.attestation_consensus_threshold = 2
    return _cli_args_for_file


@pytest.fixture
async def multi_beacon_node_three_inited_nodes(
    mocked_fork_response: dict,  # type: ignore[type-arg]
    mocked_genesis_response: dict,  # type: ignore[type-arg]
    spec: SpecElectra,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
    _cli_args_for_file: CLIArgs,
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
        cli_args=_cli_args_for_file,
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
    multi_beacon_node_three_inited_nodes: MultiBeaconNode,
    beacon_chain: BeaconChain,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
    _cli_args_for_file: CLIArgs,
) -> AttestationService:
    validator_status_tracker_service = ValidatorStatusTrackerService(
        multi_beacon_node=multi_beacon_node_three_inited_nodes,
        beacon_chain=beacon_chain,
        remote_signer=None,  # type: ignore[arg-type]
        scheduler=scheduler,
        task_manager=task_manager,
    )

    return AttestationService(
        multi_beacon_node=multi_beacon_node_three_inited_nodes,
        beacon_chain=beacon_chain,
        remote_signer=None,  # type: ignore[arg-type]
        validator_status_tracker_service=validator_status_tracker_service,
        scheduler=scheduler,
        task_manager=task_manager,
        cli_args=_cli_args_for_file,
    )


@pytest.fixture
def _add_duty_for_next_slot(
    beacon_chain: BeaconChain,
    attestation_service: AttestationService,
    random_active_validator: ValidatorIndexPubkey,
) -> None:
    duty_slot = beacon_chain.current_slot + 1
    attestation_service.attester_duties[beacon_chain.current_epoch].add(
        SchemaBeaconAPI.AttesterDutyWithSelectionProof(
            pubkey=random_active_validator.pubkey,
            validator_index=str(random_active_validator.index),
            committee_index="12",
            committee_length="20",
            committees_at_slot="3",
            validator_committee_index="3",
            slot=str(duty_slot),
            is_aggregator=False,
            selection_proof=b"",
        )
    )


def _create_att_data_callback(
    block_root: str | None = None,
    delay: float = 0.0,
) -> Callable[..., Coroutine[Any, Any, CallbackResult]]:
    async def _f(*args: Any, **kwargs: Any) -> CallbackResult:
        await asyncio.sleep(delay)
        if block_root:
            return CallbackResult(
                payload={
                    "data": AttestationData(beacon_block_root=block_root).to_obj(),
                },
            )
        raise ValueError("No exception or response to return")

    return _f


@pytest.mark.parametrize(
    argnames=(
        "response_callbacks_by_bn_host",
        "timeout_expected",
        "expected_returned_att_data_block_root",
        "expected_log_messages",
    ),
    argvalues=[
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            [
                "Produced attestation data without expected root using ['beacon-node-a', 'beacon-node-b']",
            ],
            id="identical head on all beacon nodes",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb"
                    ),
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc"
                    ),
                ],
            },
            True,
            "",
            [],
            id="different head on all beacon nodes",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb"
                    ),
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc"
                    ),
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        delay=0.1,
                    ),
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            [
                "Produced attestation data without expected root using ['beacon-node-a', 'beacon-node-c']",
            ],
            id="delayed consensus simple",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        delay=0.01,
                    ),
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        delay=0.02,
                    ),
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb"
                    ),
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        delay=0.01,
                    ),
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        delay=0.02,
                    ),
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc"
                    ),
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        delay=0.1,
                    ),
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            [
                "Produced attestation data without expected root using ['beacon-node-a', 'beacon-node-c']",
            ],
            id="delayed consensus complex",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                ],
                "beacon-node-b": [
                    TimeoutError(),
                    TimeoutError(),
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb"
                    ),
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc"
                    ),
                    TimeoutError(),
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            [
                "Produced attestation data without expected root using ['beacon-node-a', 'beacon-node-c']",
            ],
            id="delayed consensus exceptions",
        ),
    ],
)
@pytest.mark.usefixtures("_add_duty_for_next_slot")
async def test_produce_attestation_data_without_head_event(
    attestation_service: AttestationService,
    beacon_chain: BeaconChain,
    response_callbacks_by_bn_host: dict[
        str, list[Coroutine[Any, Any, CallbackResult] | Exception]
    ],
    timeout_expected: bool,
    expected_returned_att_data_block_root: str,
    expected_log_messages: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await beacon_chain.wait_for_next_slot()

    with aioresponses() as m:
        for host, callbacks in response_callbacks_by_bn_host.items():
            url_re = re.compile(
                rf"http://{host}:1234/eth/v1/validator/attestation_data.*"
            )
            for cb in callbacks:
                kwargs = dict(
                    callback=cb if not isinstance(cb, Exception) else None,
                    exception=cb if isinstance(cb, Exception) else None,
                )
                m.get(url=url_re, **kwargs)

        ctx = pytest.raises(TimeoutError) if timeout_expected else nullcontext()
        with ctx:
            att_data = await attestation_service._produce_attestation_data(
                slot=beacon_chain.current_slot, expected_block_root=None
            )

    if not timeout_expected:
        assert str(att_data.beacon_block_root) == expected_returned_att_data_block_root

    for message in expected_log_messages:
        assert message in caplog.messages


async def _simulate_head_event(
    slot: int,
    block_root: str,
    bn_host: str,
    delay: float,
    attestation_service: AttestationService,
) -> None:
    await asyncio.sleep(delay)
    await attestation_service.handle_head_event(
        SchemaBeaconAPI.HeadEvent(
            execution_optimistic=False,
            slot=str(slot),
            block=block_root,
            previous_duty_dependent_root="",
            current_duty_dependent_root="",
        ),
        beacon_node_host=bn_host,
    )


@pytest.mark.parametrize(
    argnames=(
        "initial_head_event_block_root",
        "initial_head_event_bn_host",
        "head_event_confirmations",
        "response_callbacks_by_bn_host",
        "timeout_expected",
        "expected_returned_att_data_block_root",
        "expected_log_messages",
    ),
    argvalues=[
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            "beacon-node-a",
            {
                "beacon-node-b": [
                    (
                        "0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        0.001,
                    )
                ]
            },
            {},
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            [],
            id="head event with fast confirmation",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            "beacon-node-a",
            {
                "beacon-node-c": [
                    (
                        "0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        0.3,
                    )
                ],
            },
            {},
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            [],
            id="head event with slow confirmation",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            "beacon-node-a",
            {},
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb"
                    ),
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb"
                    ),
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000bbbb",
            [
                "Produced attestation data without expected root using ['beacon-node-b', 'beacon-node-c']",
            ],
            id="head event without confirmations -> fallback success",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            "beacon-node-a",
            {},
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
                    ),
                ],
                "beacon-node-b": [],
                "beacon-node-c": [],
            },
            True,
            "0x000000000000000000000000000000000000000000000000000000000000bbbb",
            [],
            id="head event without confirmations -> fallback failure",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            "beacon-node-a",
            {
                "beacon-node-a": [
                    (
                        "0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        0.001,
                    )
                ],
            },
            {},
            True,
            "",
            [
                "Consensus was not reached for slot",
            ],
            id="head event with confirmation from initial beacon node - should not count",
        ),
    ],
)
@pytest.mark.usefixtures("_add_duty_for_next_slot")
async def test_produce_attestation_data_with_head_event(
    attestation_service: AttestationService,
    beacon_chain: BeaconChain,
    initial_head_event_block_root: str,
    initial_head_event_bn_host: str,
    head_event_confirmations: dict[str, list[tuple[str, float]]],
    response_callbacks_by_bn_host: dict[str, list[CallbackResult]],
    timeout_expected: bool,
    expected_returned_att_data_block_root: str,
    expected_log_messages: list[str],
    task_manager: TaskManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await beacon_chain.wait_for_next_slot()

    # Simulate initial received head event
    attestation_service.block_root_to_beacon_node_hosts[
        initial_head_event_block_root
    ] = {initial_head_event_bn_host}

    # Simulate subsequent delayed head event confirmations
    _head_event_tasks = set()
    for bn_host, confs in head_event_confirmations.items():
        for block_root, delay in confs:
            _head_event_tasks.add(
                asyncio.create_task(
                    _simulate_head_event(
                        slot=beacon_chain.current_slot,
                        block_root=block_root,
                        bn_host=bn_host,
                        delay=delay,
                        attestation_service=attestation_service,
                    )
                )
            )

    with aioresponses() as m:
        # Register attestation data callback for beacon node that emitted the head event
        m.get(
            re.compile(
                rf"http://{initial_head_event_bn_host}:1234/eth/v1/validator/attestation_data.*"
            ),
            callback=_create_att_data_callback(
                block_root=initial_head_event_block_root, delay=0.1
            ),
        )

        for host, callbacks in response_callbacks_by_bn_host.items():
            for cb in callbacks:
                m.get(
                    re.compile(
                        rf"http://{host}:1234/eth/v1/validator/attestation_data.*"
                    ),
                    callback=cb,
                )

        ctx = pytest.raises(TimeoutError) if timeout_expected else nullcontext()
        with ctx:
            att_data = await attestation_service._produce_attestation_data(
                slot=beacon_chain.current_slot,
                expected_block_root=initial_head_event_block_root,
            )

    if not timeout_expected:
        assert str(att_data.beacon_block_root) == expected_returned_att_data_block_root

    for message in expected_log_messages:
        assert any(message in m for m in caplog.messages)


# TODO see if we can test it on a higher level here, calling .attest() and .handle_head_event()
#  ... we don't have tests yet for late/conflicting head events
