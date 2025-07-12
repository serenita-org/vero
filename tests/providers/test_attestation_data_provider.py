import asyncio
import re
import time
from collections.abc import AsyncGenerator, Callable, Coroutine
from contextlib import nullcontext
from copy import deepcopy
from typing import Any

import msgspec.json
import pytest
from aioresponses import CallbackResult, aioresponses
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs
from providers import AttestationDataProvider, BeaconChain, DutyCache, MultiBeaconNode
from schemas import SchemaBeaconAPI
from spec.base import SpecElectra
from tasks import TaskManager


@pytest.fixture
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
async def attestation_data_provider(
    multi_beacon_node_three_inited_nodes: MultiBeaconNode,
    duty_cache: DutyCache,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
    _cli_args_for_file: CLIArgs,
) -> AttestationDataProvider:
    adp = AttestationDataProvider(
        multi_beacon_node=multi_beacon_node_three_inited_nodes,
        scheduler=scheduler,
    )
    # Default timeout is 1000 ms which doesn't work well for tests
    # where the slot time is 1000 ms - it doesn't leave any room for
    # the fallback mechanism.
    # => We lower the timeout here to be able to test what happens
    # when the timeout is reached
    adp._timeout_confirm_finality_checkpoints = 0.1
    return adp


def _create_att_data_callback(
    block_root: str,
    source: SchemaBeaconAPI.Checkpoint,
    target: SchemaBeaconAPI.Checkpoint,
    delay: float = 0.0,
) -> Callable[..., Coroutine[Any, Any, CallbackResult]]:
    async def _f(*args: Any, **kwargs: Any) -> CallbackResult:
        await asyncio.sleep(delay)
        if block_root:
            return CallbackResult(
                body=msgspec.json.encode(
                    SchemaBeaconAPI.ProduceAttestationDataResponse(
                        data=SchemaBeaconAPI.AttestationData(
                            slot="123",
                            index="0",
                            beacon_block_root=block_root,
                            source=source,
                            target=target,
                        )
                    )
                )
            )
        raise ValueError("No exception or response to return")

    return _f


@pytest.mark.parametrize(
    argnames=(
        "att_data_callbacks_by_bn_host",
        "timeout_expected",
        "expected_att_data_block_root",
        "expected_att_data_source",
        "expected_att_data_target",
        "expected_log_messages",
    ),
    argvalues=[
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(2)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
            SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
            [
                "Produced AttestationData without head event using ['beacon-node-a', 'beacon-node-b']",
            ],
            id="success: identical head, source, target",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(50)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(50)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(50)
                ],
            },
            True,
            None,
            None,
            None,
            [],
            id="failure: different head on all beacon nodes",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(10)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(5)
                ]
                + [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(5)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(10)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
            SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
            [
                "Produced AttestationData without head event using ['beacon-node-a', 'beacon-node-b']",
            ],
            id="success: delayed consensus",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
                        delay=0.01,
                    )
                    for _ in range(100)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(100)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=SchemaBeaconAPI.Checkpoint(epoch="0", root="0x0000"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(100)
                ],
            },
            True,
            None,
            None,
            None,
            [],
            id="failure: consensus on head block root without checkpoint confirmation",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0xepoch-2-first-slot",
                        source=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                        target=SchemaBeaconAPI.Checkpoint(
                            epoch="2", root="0xepoch-2-first-slot"
                        ),
                    )
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0xepoch-1-last-slot",
                        source=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                        target=SchemaBeaconAPI.Checkpoint(
                            epoch="2", root="0xepoch-1-last-slot"
                        ),
                    )
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0xepoch-1-last-slot",
                        source=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                        target=SchemaBeaconAPI.Checkpoint(
                            epoch="2", root="0xepoch-1-last-slot"
                        ),
                    )
                ],
            },
            False,
            "0xepoch-1-last-slot",
            SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
            SchemaBeaconAPI.Checkpoint(epoch="2", root="0xepoch-1-last-slot"),
            [
                "Produced AttestationData without head event using ['beacon-node-b', 'beacon-node-c']",
            ],
            id="success: late block proposal on epoch transition",
        ),
    ],
)
async def test_produce_attestation_data_without_head_event(
    attestation_data_provider: AttestationDataProvider,
    beacon_chain: BeaconChain,
    att_data_callbacks_by_bn_host: dict[
        str, list[Coroutine[Any, Any, CallbackResult] | Exception]
    ],
    timeout_expected: bool,
    expected_att_data_block_root: str,
    expected_att_data_source: SchemaBeaconAPI.Checkpoint,
    expected_att_data_target: SchemaBeaconAPI.Checkpoint,
    expected_log_messages: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await beacon_chain.wait_for_next_slot()

    with aioresponses() as m:
        for host, callbacks in att_data_callbacks_by_bn_host.items():
            url_re = re.compile(
                rf"http://{host}:1234/eth/v1/validator/attestation_data.*"
            )
            for cb in callbacks:
                kwargs = dict(
                    callback=cb if not isinstance(cb, Exception) else None,
                    exception=cb if isinstance(cb, Exception) else None,
                )
                m.get(url=url_re, **kwargs)

        slot = beacon_chain.current_slot
        next_slot_start_ts = beacon_chain.get_timestamp_for_slot(slot + 1)

        ctx = pytest.raises(TimeoutError) if timeout_expected else nullcontext()
        with ctx:
            att_data = await asyncio.wait_for(
                attestation_data_provider.produce_attestation_data(
                    slot=slot, head_event_block_root=None
                ),
                timeout=next_slot_start_ts - time.time(),
            )
            assert str(att_data.beacon_block_root) == expected_att_data_block_root
            assert att_data.source == expected_att_data_source
            assert att_data.target == expected_att_data_target

    for message in expected_log_messages:
        assert any(message in m for m in caplog.messages), (
            f"Message not found in logs: {message}"
        )


@pytest.mark.parametrize(
    argnames=(
        "initial_head_event_block_root",
        "att_data_callbacks_by_bn_host",
        "timeout_expected",
        "expected_att_data_block_root",
        "expected_att_data_source",
        "expected_att_data_target",
        "expected_log_messages",
    ),
    argvalues=[
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
            SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
            [],
            id="success: identical head, source, target",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
            SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
            [
                "Got matching AttestationData from beacon-node-a",
                "Confirming finality checkpoints source=Checkpoint(epoch='2', root='0x0002') => target=Checkpoint(epoch='3', root='0x0003')",
            ],
            id="success: unconfirmed head, same source and target",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
            SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
            [
                "Confirming finality checkpoints source=Checkpoint(epoch='2', root='0x0002') => target=Checkpoint(epoch='3', root='0x0003')",
            ],
            id="success: unconfirmed head, 2/3 source and target",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(100)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(10)
                ]
                + [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(50)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(100)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            SchemaBeaconAPI.Checkpoint(epoch="2", root="0x0002"),
            SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
            [
                "Timed out confirming finality checkpoints att_data.source=Checkpoint(epoch='2', root='0x0002'), att_data.target=Checkpoint(epoch='3', root='0x0003')",
                "Produced AttestationData without head event using ['beacon-node-a', 'beacon-node-b']",
            ],
            id="success: delayed consensus - slow head processing",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            {
                "beacon-node-a": [],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(30)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(30)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000bbbb",
            SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
            SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
            [
                "Timed out waiting for AttestationData matching head block root: 0x000000000000000000000000000000000000000000000000000000000000aaaa",
                "Produced AttestationData without head event using ['beacon-node-b', 'beacon-node-c']",
            ],
            id="success: head-emitting node stops responding, no further confirmations, fallback succeeds",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            {
                "beacon-node-a": [],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(30)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=SchemaBeaconAPI.Checkpoint(epoch="1", root="0x0001"),
                        target=SchemaBeaconAPI.Checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(30)
                ],
            },
            True,
            None,
            None,
            None,
            [
                "Timed out waiting for AttestationData matching head block root: 0x000000000000000000000000000000000000000000000000000000000000aaaa",
            ],
            id="failure: head-emitting node stops responding, no further confirmations, fallback fails",
        ),
        # TODO are there more test cases to cover? yes, failures -> timeouts, ...
        # pytest.param(
        #     "0x000000000000000000000000000000000000000000000000000000000000aaaa",
        #     {
        #         "beacon-node-a": [
        #             _create_att_data_callback(
        #                 block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa"
        #             ),
        #         ],
        #         "beacon-node-b": [],
        #         "beacon-node-c": [],
        #     },
        #     True,
        #     True,
        #     "0x000000000000000000000000000000000000000000000000000000000000bbbb",
        #     [],
        #     id="head event without confirmations -> fallback failure",
        # ),
        # pytest.param(
        #     "0x000000000000000000000000000000000000000000000000000000000000aaaa",
        #     {},
        #     True,
        #     True,
        #     "",
        #     [
        #         "Consensus was not reached for slot",
        #     ],
        #     id="head event with confirmation from initial beacon node - should not count",
        # ),
        # pytest.param(
        #     "0x000000000000000000000000000000000000000000000000000000000000aaaa",
        #     {},
        #     False,
        #     True,
        #     "",
        #     [
        #         "Timed out confirming source checkpoint",
        #     ],
        #     id="source checkpoint not confirmed",
        # ),
    ],
)
async def test_produce_attestation_data_with_head_event(
    attestation_data_provider: AttestationDataProvider,
    beacon_chain: BeaconChain,
    initial_head_event_block_root: str,
    att_data_callbacks_by_bn_host: dict[
        str, list[Callable[..., Coroutine[Any, Any, CallbackResult]]]
    ],
    timeout_expected: bool,
    expected_att_data_block_root: str,
    expected_att_data_source: SchemaBeaconAPI.Checkpoint,
    expected_att_data_target: SchemaBeaconAPI.Checkpoint,
    expected_log_messages: list[str],
    task_manager: TaskManager,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await beacon_chain.wait_for_next_slot()

    with aioresponses() as m:
        for host, callbacks in att_data_callbacks_by_bn_host.items():
            for cb in callbacks:
                m.get(
                    re.compile(
                        rf"http://{host}:1234/eth/v1/validator/attestation_data.*"
                    ),
                    callback=cb,
                )

        slot = beacon_chain.current_slot
        next_slot_start_ts = beacon_chain.get_timestamp_for_slot(slot + 1)

        ctx = pytest.raises(TimeoutError) if timeout_expected else nullcontext()
        with ctx:
            att_data = await asyncio.wait_for(
                attestation_data_provider.produce_attestation_data(
                    slot=slot, head_event_block_root=initial_head_event_block_root
                ),
                timeout=next_slot_start_ts - time.time(),
            )
            assert str(att_data.beacon_block_root) == expected_att_data_block_root
            assert att_data.source == expected_att_data_source
            assert att_data.target == expected_att_data_target

    for message in expected_log_messages:
        assert any(message in m for m in caplog.messages), (
            f"Message not found in logs: {message}"
        )


async def test_caching(
    attestation_data_provider: AttestationDataProvider, caplog: pytest.LogCaptureFixture
) -> None:
    assert len(attestation_data_provider.source_checkpoint_confirmation_cache) == 0
    assert len(attestation_data_provider.target_checkpoint_confirmation_cache) == 0

    s = SchemaBeaconAPI.Checkpoint(epoch="123", root="0x000123")
    t = SchemaBeaconAPI.Checkpoint(epoch="124", root="0x000124")

    attestation_data_provider._cache_checkpoints(source=s, target=t)

    await attestation_data_provider._confirm_finality_checkpoints(
        source=s, target=t, slot=3940
    )

    expected_log_message = "Finality checkpoints confirmed from cache (source=Checkpoint(epoch='123', root='0x000123'), target=Checkpoint(epoch='124', root='0x000124'))"
    assert expected_log_message in caplog.messages
