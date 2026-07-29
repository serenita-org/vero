import asyncio
import re
import time
from collections.abc import Callable, Coroutine
from contextlib import nullcontext
from typing import Any

import msgspec.json
import pytest
from aioresponses import CallbackResult, aioresponses

from args import CLIArgs
from providers import AttestationDataProvider, BeaconChain, MultiBeaconNode, Vero
from schemas import SchemaBeaconAPI
from spec import Checkpoint
from tests.ssz_objects import attestation_data_obj


def _root(value: int) -> bytes:
    return bytes.fromhex(f"{value:064x}")


ROOT_0 = _root(0)
ROOT_1 = _root(1)
ROOT_2 = _root(2)
ROOT_3 = _root(3)
ROOT_A = _root(0xAAAA)
ROOT_B = _root(0xBBBB)
ROOT_C = _root(0xCCCC)
NEW_HEAD_ROOT = _root(0x1000)
OLD_HEAD_ROOT = _root(0x1001)
VERY_OLD_HEAD_ROOT = _root(0x1002)
EPOCH_2_FIRST_SLOT_ROOT = _root(0x2000)
EPOCH_1_LAST_SLOT_ROOT = _root(0x2001)


@pytest.fixture
async def attestation_data_provider(
    multi_beacon_node: MultiBeaconNode,
    vero: Vero,
) -> AttestationDataProvider:
    adp = AttestationDataProvider(
        multi_beacon_node=multi_beacon_node,
        scheduler=vero.scheduler,
        spec=vero.spec,
    )
    # Default timeout is 1000 ms which doesn't work well for tests
    # where the slot time is 1000 ms - it doesn't leave any room for
    # the fallback mechanism.
    # => We lower the timeout here to be able to test what happens
    # when the timeout is reached
    adp._timeout_head_event_checkpoint_confirmation = 0.1
    return adp


def _create_att_data_callback(
    block_root: bytes,
    source: Checkpoint,
    target: Checkpoint,
    delay: float = 0.0,
) -> Callable[..., Coroutine[Any, Any, CallbackResult]]:
    async def _f(*args: Any, **kwargs: Any) -> CallbackResult:
        await asyncio.sleep(delay)
        attestation_data = attestation_data_obj(
            slot="123",
            beacon_block_root=f"0x{block_root.hex()}",
            source={"epoch": str(source.epoch), "root": f"0x{source.root.hex()}"},
            target={"epoch": str(target.epoch), "root": f"0x{target.root.hex()}"},
        )
        return CallbackResult(body=msgspec.json.encode({"data": attestation_data}))

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
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                ],
            },
            False,
            ROOT_A,
            Checkpoint(epoch=0, root=ROOT_0),
            Checkpoint(epoch=1, root=ROOT_1),
            [
                "Produced AttestationData without head event using ['beacon-node-a', 'beacon-node-b']",
            ],
            id="success: identical head, source, target",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                    for _ in range(50)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root=ROOT_B,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                    for _ in range(50)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root=ROOT_C,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                    for _ in range(50)
                ],
            },
            True,
            None,
            None,
            None,
            [],
            id="timeout: different head on all beacon nodes",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root=NEW_HEAD_ROOT,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                    for _ in range(10)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root=OLD_HEAD_ROOT,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                    for _ in range(5)
                ]
                + [
                    _create_att_data_callback(
                        block_root=NEW_HEAD_ROOT,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                    for _ in range(5)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root=VERY_OLD_HEAD_ROOT,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                    for _ in range(10)
                ],
            },
            False,
            NEW_HEAD_ROOT,
            Checkpoint(epoch=0, root=ROOT_0),
            Checkpoint(epoch=1, root=ROOT_1),
            [
                "Produced AttestationData without head event using ['beacon-node-a', 'beacon-node-b']",
            ],
            id="success: delayed consensus",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=1, root=ROOT_1),
                        target=Checkpoint(epoch=2, root=ROOT_2),
                        delay=0.01,
                    )
                    for _ in range(100)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                    for _ in range(100)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root=ROOT_C,
                        source=Checkpoint(epoch=0, root=ROOT_0),
                        target=Checkpoint(epoch=1, root=ROOT_1),
                    )
                    for _ in range(100)
                ],
            },
            True,
            None,
            None,
            None,
            [],
            id="timeout: consensus on head block root without checkpoint confirmation",
        ),
        pytest.param(
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root=EPOCH_2_FIRST_SLOT_ROOT,
                        source=Checkpoint(epoch=1, root=ROOT_1),
                        target=Checkpoint(epoch=2, root=EPOCH_2_FIRST_SLOT_ROOT),
                    )
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root=EPOCH_1_LAST_SLOT_ROOT,
                        source=Checkpoint(epoch=1, root=ROOT_1),
                        target=Checkpoint(epoch=2, root=EPOCH_1_LAST_SLOT_ROOT),
                    )
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root=EPOCH_1_LAST_SLOT_ROOT,
                        source=Checkpoint(epoch=1, root=ROOT_1),
                        target=Checkpoint(epoch=2, root=EPOCH_1_LAST_SLOT_ROOT),
                    )
                ],
            },
            False,
            EPOCH_1_LAST_SLOT_ROOT,
            Checkpoint(epoch=1, root=ROOT_1),
            Checkpoint(epoch=2, root=EPOCH_1_LAST_SLOT_ROOT),
            [
                "Produced AttestationData without head event using ['beacon-node-b', 'beacon-node-c']",
            ],
            id="success: late block proposal on epoch transition",
        ),
    ],
)
@pytest.mark.parametrize(
    argnames="cli_args",
    argvalues=[
        pytest.param(
            {
                "beacon_node_urls": [
                    "http://beacon-node-a:1234",
                    "http://beacon-node-b:1234",
                    "http://beacon-node-c:1234",
                ],
            },
            id="3 beacon nodes",
        )
    ],
    indirect=True,
)
async def test_produce_attestation_data_without_head_event(
    attestation_data_provider: AttestationDataProvider,
    beacon_chain: BeaconChain,
    att_data_callbacks_by_bn_host: dict[
        str, list[Coroutine[Any, Any, CallbackResult] | Exception]
    ],
    timeout_expected: bool,
    expected_att_data_block_root: bytes | None,
    expected_att_data_source: Checkpoint,
    expected_att_data_target: Checkpoint,
    expected_log_messages: list[str],
    cli_args: CLIArgs,
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
            assert att_data.beacon_block_root == expected_att_data_block_root
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
            ROOT_A,
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=2, root=ROOT_2),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(2)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=2, root=ROOT_2),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(2)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=2, root=ROOT_2),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(2)
                ],
            },
            False,
            ROOT_A,
            Checkpoint(epoch=2, root=ROOT_2),
            Checkpoint(epoch=3, root=ROOT_3),
            [],
            id="success: identical head, source, target",
        ),
        pytest.param(
            ROOT_A,
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=2, root=ROOT_2),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(2)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root=ROOT_B,
                        source=Checkpoint(epoch=2, root=ROOT_2),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(2)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root=ROOT_C,
                        source=Checkpoint(epoch=2, root=ROOT_2),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(2)
                ],
            },
            False,
            ROOT_A,
            Checkpoint(epoch=2, root=ROOT_2),
            Checkpoint(epoch=3, root=ROOT_3),
            [
                "Got matching AttestationData from beacon-node-a",
                (
                    "Confirming finality checkpoints "
                    f"source={Checkpoint(epoch=2, root=ROOT_2)} => "
                    f"target={Checkpoint(epoch=3, root=ROOT_3)}"
                ),
            ],
            id="success: unconfirmed head, same source and target",
        ),
        pytest.param(
            ROOT_A,
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=2, root=ROOT_2),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(2)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root=ROOT_B,
                        source=Checkpoint(epoch=2, root=ROOT_2),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(2)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root=ROOT_C,
                        source=Checkpoint(epoch=1, root=ROOT_1),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(2)
                ],
            },
            False,
            ROOT_A,
            Checkpoint(epoch=2, root=ROOT_2),
            Checkpoint(epoch=3, root=ROOT_3),
            [
                (
                    "Confirming finality checkpoints "
                    f"source={Checkpoint(epoch=2, root=ROOT_2)} => "
                    f"target={Checkpoint(epoch=3, root=ROOT_3)}"
                ),
            ],
            id="success: unconfirmed head, 2/3 source and target",
        ),
        pytest.param(
            ROOT_A,
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=2, root=ROOT_2),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(100)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root=ROOT_B,
                        source=Checkpoint(epoch=1, root=ROOT_1),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(10)
                ]
                + [
                    _create_att_data_callback(
                        block_root=ROOT_A,
                        source=Checkpoint(epoch=2, root=ROOT_2),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(50)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root=ROOT_C,
                        source=Checkpoint(epoch=1, root=ROOT_1),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(100)
                ],
            },
            False,
            ROOT_A,
            Checkpoint(epoch=2, root=ROOT_2),
            Checkpoint(epoch=3, root=ROOT_3),
            [
                (
                    "Timed out confirming finality checkpoints "
                    f"att_data.source={Checkpoint(epoch=2, root=ROOT_2)}, "
                    f"att_data.target={Checkpoint(epoch=3, root=ROOT_3)}"
                ),
                "Produced AttestationData without head event using ['beacon-node-a', 'beacon-node-b']",
            ],
            id="success: delayed consensus - slow head processing",
        ),
        pytest.param(
            ROOT_A,
            {
                "beacon-node-a": [],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root=ROOT_B,
                        source=Checkpoint(epoch=1, root=ROOT_1),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(30)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root=ROOT_B,
                        source=Checkpoint(epoch=1, root=ROOT_1),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(30)
                ],
            },
            False,
            ROOT_B,
            Checkpoint(epoch=1, root=ROOT_1),
            Checkpoint(epoch=3, root=ROOT_3),
            [
                "Timed out waiting for AttestationData matching head block root: 0x000000000000000000000000000000000000000000000000000000000000aaaa",
                "Produced AttestationData without head event using ['beacon-node-b', 'beacon-node-c']",
            ],
            id="success: head-emitting node stops responding, no further confirmations, fallback succeeds",
        ),
        pytest.param(
            ROOT_A,
            {
                "beacon-node-a": [],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root=ROOT_B,
                        source=Checkpoint(epoch=1, root=ROOT_1),
                        target=Checkpoint(epoch=3, root=ROOT_3),
                    )
                    for _ in range(30)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root=ROOT_C,
                        source=Checkpoint(epoch=1, root=ROOT_1),
                        target=Checkpoint(epoch=3, root=ROOT_3),
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
            id="timeout: head-emitting node stops responding, no further confirmations, fallback fails",
        ),
    ],
)
@pytest.mark.parametrize(
    argnames="cli_args",
    argvalues=[
        pytest.param(
            {
                "beacon_node_urls": [
                    "http://beacon-node-a:1234",
                    "http://beacon-node-b:1234",
                    "http://beacon-node-c:1234",
                ],
            },
            id="3 beacon nodes",
        )
    ],
    indirect=True,
)
async def test_produce_attestation_data_with_head_event(
    attestation_data_provider: AttestationDataProvider,
    beacon_chain: BeaconChain,
    initial_head_event_block_root: bytes,
    att_data_callbacks_by_bn_host: dict[
        str, list[Callable[..., Coroutine[Any, Any, CallbackResult]]]
    ],
    timeout_expected: bool,
    expected_att_data_block_root: bytes | None,
    expected_att_data_source: Checkpoint,
    expected_att_data_target: Checkpoint,
    expected_log_messages: list[str],
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
                    slot=slot,
                    head_event_block_root=f"0x{initial_head_event_block_root.hex()}",
                ),
                timeout=next_slot_start_ts - time.time(),
            )
            assert att_data.beacon_block_root == expected_att_data_block_root
            assert att_data.source == expected_att_data_source
            assert att_data.target == expected_att_data_target

    for message in expected_log_messages:
        assert any(message in m for m in caplog.messages), (
            f"Message not found in logs: {message}"
        )


async def test_checkpoint_confirmed_from_cache(
    attestation_data_provider: AttestationDataProvider, caplog: pytest.LogCaptureFixture
) -> None:
    assert len(attestation_data_provider.source_checkpoint_confirmation_cache) == 0
    assert len(attestation_data_provider.target_checkpoint_confirmation_cache) == 0

    s = Checkpoint(epoch=123, root=_root(123))
    t = Checkpoint(epoch=124, root=_root(124))

    attestation_data_provider._cache_checkpoints(source=s, target=t)

    await attestation_data_provider._confirm_finality_checkpoints(
        source=s, target=t, slot=3940
    )

    assert (
        f"Finality checkpoints confirmed from cache (source={s}, target={t})"
        in caplog.messages
    )


async def test_checkpoint_cache_pruning(
    attestation_data_provider: AttestationDataProvider, caplog: pytest.LogCaptureFixture
) -> None:
    for i in range(20):
        attestation_data_provider._cache_checkpoints(
            source=Checkpoint(epoch=i, root=_root(i)),
            target=Checkpoint(epoch=i - 1, root=_root(i)),
        )

    assert len(attestation_data_provider.source_checkpoint_confirmation_cache) == 20
    assert len(attestation_data_provider.target_checkpoint_confirmation_cache) == 20

    attestation_data_provider.prune()

    assert len(attestation_data_provider.source_checkpoint_confirmation_cache) == 3
    assert len(attestation_data_provider.target_checkpoint_confirmation_cache) == 3

    assert all(
        e in attestation_data_provider.source_checkpoint_confirmation_cache
        for e in (17, 18, 19)
    )
    assert all(
        e in attestation_data_provider.target_checkpoint_confirmation_cache
        for e in (16, 17, 18)
    )


@pytest.mark.parametrize(
    argnames=("slot_into_epoch", "depth", "expected_to_invalidate"),
    argvalues=[
        pytest.param(
            10, 2, False, id="does not cross epoch boundary - no invalidation"
        ),
        pytest.param(2, 5, True, id="crosses epoch boundary - invalidation expected"),
    ],
)
async def test_reorg_checkpoint_invalidation(
    slot_into_epoch: int,
    depth: int,
    expected_to_invalidate: bool,
    attestation_data_provider: AttestationDataProvider,
) -> None:
    epoch = 123
    new_head_slot = (
        epoch * attestation_data_provider.spec.SLOTS_PER_EPOCH + slot_into_epoch
    )

    attestation_data_provider.source_checkpoint_confirmation_cache = {
        epoch: Checkpoint(epoch=epoch, root=_root(epoch)),
    }
    await attestation_data_provider.handle_reorg_event(
        event=SchemaBeaconAPI.ChainReorgEvent(
            slot=str(new_head_slot),
            depth=str(depth),
            old_head_block="0x_old_head",
            new_head_block="0x_new_head",
            execution_optimistic=False,
        )
    )
    if expected_to_invalidate:
        assert len(attestation_data_provider.source_checkpoint_confirmation_cache) == 0
    else:
        assert len(attestation_data_provider.source_checkpoint_confirmation_cache) == 1
