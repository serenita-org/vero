import asyncio
import hashlib
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
from tests.ssz_objects import make_attestation_data


def _valid_root(value: str) -> str:
    try:
        raw = bytes.fromhex(value.removeprefix("0x"))
    except ValueError:
        raw = b""
    if len(raw) == 32:
        return f"0x{raw.hex()}"
    return f"0x{hashlib.sha256(value.encode()).hexdigest()}"


def _checkpoint(epoch: str | int, root: str) -> Checkpoint:
    return Checkpoint(
        epoch=int(epoch),
        root=bytes.fromhex(_valid_root(root).removeprefix("0x")),
    )


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
    block_root: str,
    source: Checkpoint,
    target: Checkpoint,
    delay: float = 0.0,
) -> Callable[..., Coroutine[Any, Any, CallbackResult]]:
    async def _f(*args: Any, **kwargs: Any) -> CallbackResult:
        await asyncio.sleep(delay)
        if block_root:
            attestation_data = make_attestation_data(
                slot=123,
                beacon_block_root=_valid_root(block_root),
                source={"epoch": source.epoch, "root": f"0x{source.root.hex()}"},
                target={"epoch": target.epoch, "root": f"0x{target.root.hex()}"},
            )
            return CallbackResult(
                body=msgspec.json.encode(
                    {"data": msgspec.Raw(attestation_data.to_json())}
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
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
                    )
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
                    )
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
                    )
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            _checkpoint(epoch="0", root="0x0000"),
            _checkpoint(epoch="1", root="0x0001"),
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
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(50)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(50)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
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
                        block_root="0x0000000000000000000000000000000000000000000000000000000000000new",
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(10)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x0000000000000000000000000000000000000000000000000000000000000old",
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(5)
                ]
                + [
                    _create_att_data_callback(
                        block_root="0x0000000000000000000000000000000000000000000000000000000000000new",
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(5)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x00000000000000000000000000000000000000000000000000000000very-old",
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(10)
                ],
            },
            False,
            "0x0000000000000000000000000000000000000000000000000000000000000new",
            _checkpoint(epoch="0", root="0x0000"),
            _checkpoint(epoch="1", root="0x0001"),
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
                        source=_checkpoint(epoch="1", root="0x0001"),
                        target=_checkpoint(epoch="2", root="0x0002"),
                        delay=0.01,
                    )
                    for _ in range(100)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
                    )
                    for _ in range(100)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=_checkpoint(epoch="0", root="0x0000"),
                        target=_checkpoint(epoch="1", root="0x0001"),
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
                        block_root="0xepoch-2-first-slot",
                        source=_checkpoint(epoch="1", root="0x0001"),
                        target=_checkpoint(epoch="2", root="0xepoch-2-first-slot"),
                    )
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0xepoch-1-last-slot",
                        source=_checkpoint(epoch="1", root="0x0001"),
                        target=_checkpoint(epoch="2", root="0xepoch-1-last-slot"),
                    )
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0xepoch-1-last-slot",
                        source=_checkpoint(epoch="1", root="0x0001"),
                        target=_checkpoint(epoch="2", root="0xepoch-1-last-slot"),
                    )
                ],
            },
            False,
            "0xepoch-1-last-slot",
            _checkpoint(epoch="1", root="0x0001"),
            _checkpoint(epoch="2", root="0xepoch-1-last-slot"),
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
    expected_att_data_block_root: str,
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
            assert f"0x{att_data.beacon_block_root.hex()}" == _valid_root(
                expected_att_data_block_root
            )
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
                        source=_checkpoint(epoch="2", root="0x0002"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=_checkpoint(epoch="2", root="0x0002"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=_checkpoint(epoch="2", root="0x0002"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            _checkpoint(epoch="2", root="0x0002"),
            _checkpoint(epoch="3", root="0x0003"),
            [],
            id="success: identical head, source, target",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=_checkpoint(epoch="2", root="0x0002"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=_checkpoint(epoch="2", root="0x0002"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=_checkpoint(epoch="2", root="0x0002"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            _checkpoint(epoch="2", root="0x0002"),
            _checkpoint(epoch="3", root="0x0003"),
            [
                "Got matching AttestationData from beacon-node-a",
                "Confirming finality checkpoints "
                f"source={_checkpoint(epoch=2, root='0x0002')} => "
                f"target={_checkpoint(epoch=3, root='0x0003')}",
            ],
            id="success: unconfirmed head, same source and target",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=_checkpoint(epoch="2", root="0x0002"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=_checkpoint(epoch="2", root="0x0002"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=_checkpoint(epoch="1", root="0x0001"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(2)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            _checkpoint(epoch="2", root="0x0002"),
            _checkpoint(epoch="3", root="0x0003"),
            [
                "Confirming finality checkpoints "
                f"source={_checkpoint(epoch=2, root='0x0002')} => "
                f"target={_checkpoint(epoch=3, root='0x0003')}",
            ],
            id="success: unconfirmed head, 2/3 source and target",
        ),
        pytest.param(
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            {
                "beacon-node-a": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=_checkpoint(epoch="2", root="0x0002"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(100)
                ],
                "beacon-node-b": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=_checkpoint(epoch="1", root="0x0001"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(10)
                ]
                + [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000aaaa",
                        source=_checkpoint(epoch="2", root="0x0002"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(50)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=_checkpoint(epoch="1", root="0x0001"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(100)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000aaaa",
            _checkpoint(epoch="2", root="0x0002"),
            _checkpoint(epoch="3", root="0x0003"),
            [
                "Timed out confirming finality checkpoints "
                f"att_data.source={_checkpoint(epoch=2, root='0x0002')}, "
                f"att_data.target={_checkpoint(epoch=3, root='0x0003')}",
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
                        source=_checkpoint(epoch="1", root="0x0001"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(30)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000bbbb",
                        source=_checkpoint(epoch="1", root="0x0001"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(30)
                ],
            },
            False,
            "0x000000000000000000000000000000000000000000000000000000000000bbbb",
            _checkpoint(epoch="1", root="0x0001"),
            _checkpoint(epoch="3", root="0x0003"),
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
                        source=_checkpoint(epoch="1", root="0x0001"),
                        target=_checkpoint(epoch="3", root="0x0003"),
                    )
                    for _ in range(30)
                ],
                "beacon-node-c": [
                    _create_att_data_callback(
                        block_root="0x000000000000000000000000000000000000000000000000000000000000cccc",
                        source=_checkpoint(epoch="1", root="0x0001"),
                        target=_checkpoint(epoch="3", root="0x0003"),
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
    initial_head_event_block_root: str,
    att_data_callbacks_by_bn_host: dict[
        str, list[Callable[..., Coroutine[Any, Any, CallbackResult]]]
    ],
    timeout_expected: bool,
    expected_att_data_block_root: str,
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
                    head_event_block_root=_valid_root(initial_head_event_block_root),
                ),
                timeout=next_slot_start_ts - time.time(),
            )
            assert f"0x{att_data.beacon_block_root.hex()}" == _valid_root(
                expected_att_data_block_root
            )
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

    s = _checkpoint(epoch="123", root="0x000123")
    t = _checkpoint(epoch="124", root="0x000124")

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
            source=_checkpoint(epoch=i, root=f"0x000{i}"),
            target=_checkpoint(epoch=i - 1, root=f"0x000{i - 1}"),
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
        epoch: _checkpoint(epoch=epoch, root="0x_root"),
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
