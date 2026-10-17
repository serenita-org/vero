import asyncio
from unittest.mock import AsyncMock

import pytest

from observability import HandledRuntimeError
from providers import BeaconChain, Keymanager, Vero
from schemas import SchemaBeaconAPI
from schemas.shared import ForkVersion
from schemas.validator import ValidatorIndexPubkey
from services import BlockProposalService
from spec.base import GasLimitScheduleEntry
from spec.common import Uint64
from spec.configs import Network
from tests.ssz_objects import ZERO_ROOT


@pytest.mark.parametrize(
    "enable_keymanager_api",
    [
        pytest.param(False, id="signature_provider: RemoteSigner"),
        pytest.param(True, id="signature_provider: Keymanager"),
    ],
    indirect=True,
)
async def test_update_duties(
    block_proposal_service: BlockProposalService,
    enable_keymanager_api: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # This test just checks that no exception is thrown
    assert len(block_proposal_service.proposer_duties) == 0
    await block_proposal_service._update_duties()
    assert any("Updated duties" in m for m in caplog.messages)
    assert len(block_proposal_service.proposer_duties) > 0


@pytest.mark.parametrize(
    "enable_keymanager_api",
    [
        pytest.param(False, id="signature_provider: RemoteSigner"),
        pytest.param(True, id="signature_provider: Keymanager"),
    ],
    indirect=True,
)
async def test_prepare_beacon_proposer(
    block_proposal_service: BlockProposalService,
    enable_keymanager_api: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # This test just checks that no exception is thrown
    await block_proposal_service.prepare_beacon_proposer()


@pytest.mark.parametrize(
    "enable_keymanager_api",
    [
        pytest.param(False, id="signature_provider: RemoteSigner"),
        pytest.param(True, id="signature_provider: Keymanager"),
    ],
    indirect=True,
)
async def test_register_validators(
    block_proposal_service: BlockProposalService,
    beacon_chain: BeaconChain,
    enable_keymanager_api: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # This test just checks that no exception is thrown
    await block_proposal_service.register_validators(
        current_slot=beacon_chain.current_slot
    )


@pytest.mark.parametrize("enable_keymanager_api", [False, True], indirect=True)
@pytest.mark.parametrize("configured", [None, 60_000_000, 90_000_000])
async def test_proposer_preferences_gas_limit_schedule(
    block_proposal_service: BlockProposalService,
    beacon_chain: BeaconChain,
    vero: Vero,
    random_active_validator: ValidatorIndexPubkey,
    enable_keymanager_api: bool,
    configured: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vero.cli_args.gas_limit = configured
    vero.spec.GAS_LIMIT_SCHEDULE = [
        GasLimitScheduleEntry(Uint64(10), Uint64(60_000_000)),
        GasLimitScheduleEntry(Uint64(11), Uint64(75_000_000)),
    ]
    slots_per_epoch = beacon_chain.SLOTS_PER_EPOCH
    current_slot = 10 * slots_per_epoch - 1
    monkeypatch.setattr(
        BeaconChain, "current_slot", property(lambda self: current_slot)
    )
    sign = AsyncMock(wraps=block_proposal_service.signature_provider.sign)
    submit = AsyncMock()
    monkeypatch.setattr(block_proposal_service.signature_provider, "sign", sign)
    monkeypatch.setattr(
        block_proposal_service.multi_beacon_node, "submit_proposer_preferences", submit
    )

    for epoch in (10, 11):
        block_proposal_service.proposer_duties[epoch].add(
            SchemaBeaconAPI.ProposerDuty(
                pubkey=random_active_validator.pubkey,
                validator_index=str(random_active_validator.index),
                slot=str(epoch * slots_per_epoch),
            )
        )
        block_proposal_service.proposer_duties_dependent_roots[epoch] = ZERO_ROOT

    await block_proposal_service.submit_proposer_preferences()
    assert sign.await_count == 2
    assert submit.await_count == 2
    preferences = {
        int(
            call.kwargs["message"].proposer_preferences.data.proposal_slot
        ): call.kwargs["message"].proposer_preferences.data.target_gas_limit
        for call in sign.await_args_list
    }
    assert preferences == {
        10 * slots_per_epoch: str(configured if configured is not None else 60_000_000),
        11 * slots_per_epoch: str(configured if configured is not None else 75_000_000),
    }

    if enable_keymanager_api:
        # A per-validator override takes precedence over both CLI and schedule.
        block_proposal_service.keymanager.set_gas_limit(
            random_active_validator.pubkey, "50000000"
        )
        sign.reset_mock()
        await block_proposal_service.submit_proposer_preferences()
        assert sign.await_count == 2
        assert all(
            call.kwargs["message"].proposer_preferences.data.target_gas_limit
            == "50000000"
            for call in sign.await_args_list
        )


@pytest.mark.parametrize("fork_version", [ForkVersion.FULU], indirect=True)
@pytest.mark.parametrize("enable_keymanager_api", [False, True], indirect=True)
async def test_pre_gloas_registration_ignores_gas_limit_schedule(
    block_proposal_service: BlockProposalService,
    beacon_chain: BeaconChain,
    vero: Vero,
    random_active_validator: ValidatorIndexPubkey,
    fork_version: ForkVersion,
    enable_keymanager_api: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vero.cli_args.use_external_builder = True
    vero.cli_args.network = Network.HOODI
    vero.cli_args.gas_limit = None
    vero.spec.GLOAS_FORK_EPOCH = Uint64(10)
    vero.spec.GAS_LIMIT_SCHEDULE = [
        GasLimitScheduleEntry(Uint64(0), Uint64(75_000_000))
    ]
    sign = AsyncMock(wraps=block_proposal_service.signature_provider.sign)
    submit = AsyncMock()
    monkeypatch.setattr(block_proposal_service.signature_provider, "sign", sign)
    monkeypatch.setattr(
        block_proposal_service.multi_beacon_node, "register_validator", submit
    )
    await block_proposal_service.register_validators(
        current_slot=10 * beacon_chain.SLOTS_PER_EPOCH - 1,
        pubkeys_to_register=[random_active_validator.pubkey],
    )
    sign.assert_awaited_once()
    assert (
        sign.call_args.kwargs["message"].validator_registration.gas_limit == "60000000"
    )
    submit.assert_awaited_once()


@pytest.mark.parametrize(
    "execution_payload_blinded",
    [pytest.param(False, id="Unblinded"), pytest.param(True, id="Blinded")],
    indirect=True,
)
@pytest.mark.parametrize(
    argnames="cli_args",
    argvalues=[
        pytest.param(
            {
                "force_json_wire_format": False,
            },
            id="Prefer SSZ",
        ),
        pytest.param(
            {
                "force_json_wire_format": True,
            },
            id="Force JSON",
        ),
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "fork_version",
    [
        pytest.param(ForkVersion.ELECTRA, id="Electra"),
        pytest.param(ForkVersion.FULU, id="Fulu"),
        pytest.param(ForkVersion.GLOAS, id="Gloas"),
    ],
    indirect=True,
)
@pytest.mark.parametrize(
    "enable_keymanager_api",
    [
        pytest.param(False, id="signature_provider: RemoteSigner"),
        pytest.param(True, id="signature_provider: Keymanager"),
    ],
    indirect=True,
)
async def test_publish_block(
    block_proposal_service: BlockProposalService,
    beacon_chain: BeaconChain,
    random_active_validator: ValidatorIndexPubkey,
    execution_payload_blinded: bool,
    fork_version: ForkVersion,
    enable_keymanager_api: bool,
    keymanager: Keymanager,
    vero: Vero,
    caplog: pytest.LogCaptureFixture,
) -> None:
    if keymanager.enabled:
        keymanager.set_graffiti(random_active_validator.pubkey, "overridden")

    # Populate the service with a proposal duty
    duty_slot = beacon_chain.current_slot + 1

    block_proposal_service.proposer_duties[
        duty_slot // beacon_chain.SLOTS_PER_EPOCH
    ].add(
        SchemaBeaconAPI.ProposerDuty(
            pubkey=random_active_validator.pubkey,
            validator_index=str(random_active_validator.index),
            slot=str(duty_slot),
        ),
    )
    block_proposal_service._last_slot_duty_started_for = 0
    block_proposal_service._last_slot_duty_completed_for = 0

    blocks_published_before = vero.metrics.vc_published_blocks_c._value.get()

    # Wait for duty slot
    await asyncio.sleep(max(0.0, -beacon_chain.time_since_slot_start(duty_slot)))

    await block_proposal_service.propose_block(slot=duty_slot)

    assert any("Published block" in m for m in caplog.messages)
    assert (
        vero.metrics.vc_published_blocks_c._value.get() == blocks_published_before + 1
    )
    assert block_proposal_service._last_slot_duty_started_for == duty_slot
    assert block_proposal_service._last_slot_duty_completed_for == duty_slot

    if keymanager.enabled:
        assert any(
            "Using Keymanager-provided graffiti: overridden" in m
            for m in caplog.messages
        )


@pytest.mark.parametrize(
    argnames="cli_args",
    argvalues=[
        pytest.param({"force_json_wire_format": False}, id="Prefer SSZ"),
        pytest.param({"force_json_wire_format": True}, id="Force JSON"),
    ],
    indirect=True,
)
@pytest.mark.parametrize("block_publication_outcome", ["success", "timeout", "failure"])
async def test_publish_payload_envelope(
    block_proposal_service: BlockProposalService,
    beacon_chain: BeaconChain,
    random_active_validator: ValidatorIndexPubkey,
    fork_version: ForkVersion,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    block_publication_outcome: str,
) -> None:
    slot = beacon_chain.current_slot + 1
    duty = SchemaBeaconAPI.ProposerDuty(
        pubkey=random_active_validator.pubkey,
        validator_index=str(random_active_validator.index),
        slot=str(slot),
    )

    beacon_node = block_proposal_service.multi_beacon_node.beacon_nodes[0]
    fetch_envelope = AsyncMock(wraps=beacon_node.get_execution_payload_envelope)
    monkeypatch.setattr(beacon_node, "get_execution_payload_envelope", fetch_envelope)
    block_publication_started = asyncio.Event()
    finish_block_publication = asyncio.Event()

    async def publish_block() -> None:
        block_publication_started.set()
        await finish_block_publication.wait()
        if block_publication_outcome == "failure":
            raise RuntimeError("Block publication failed")

    block_task = asyncio.create_task(publish_block())
    envelope_task = asyncio.create_task(
        block_proposal_service._publish_payload_envelope(
            slot=slot,
            duty=duty,
            beacon_block_root=ZERO_ROOT,
            beacon_node=beacon_node,
            block_publication_task=block_task,
        )
    )
    try:
        await block_publication_started.wait()
        await asyncio.sleep(0)
        fetch_envelope.assert_not_awaited()
        if block_publication_outcome != "timeout":
            finish_block_publication.set()

        if block_publication_outcome == "failure":
            with pytest.raises(HandledRuntimeError):
                await envelope_task
            fetch_envelope.assert_not_awaited()
        else:
            await envelope_task
            fetch_envelope.assert_awaited_once()
            assert any("Published payload envelope" in m for m in caplog.messages)
            if block_publication_outcome == "timeout":
                assert not block_task.done()
                assert any(
                    "Block publication still pending" in m for m in caplog.messages
                )
    finally:
        finish_block_publication.set()
        await asyncio.gather(block_task, envelope_task, return_exceptions=True)


@pytest.mark.parametrize(
    "beacon_node_urls_proposal",
    [
        pytest.param([], id="No proposal beacon nodes specified"),
        pytest.param(
            [
                "http://beacon-node-proposal-1:1234",
                "http://beacon-node-proposal-2:1234",
            ],
            id="Beacon nodes explicitly specified for block proposals",
        ),
    ],
    indirect=True,
)
async def test_block_proposal_beacon_node_urls_proposal(
    block_proposal_service: BlockProposalService,
    beacon_chain: BeaconChain,
    random_active_validator: ValidatorIndexPubkey,
    beacon_node_urls_proposal: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The provided proposal beacon node URLs should be exclusively used for block proposals,
    if specified.
    """
    # Populate the service with a proposal duty
    duty_slot = beacon_chain.current_slot + 1

    block_proposal_service.proposer_duties[
        duty_slot // beacon_chain.SLOTS_PER_EPOCH
    ].add(
        SchemaBeaconAPI.ProposerDuty(
            pubkey=random_active_validator.pubkey,
            validator_index=str(random_active_validator.index),
            slot=str(duty_slot),
        ),
    )

    # Wait for duty slot
    await asyncio.sleep(max(0.0, -beacon_chain.time_since_slot_start(duty_slot)))
    await block_proposal_service.propose_block(slot=duty_slot)

    _override_log_string = "Overriding beacon nodes for block proposal"
    if len(beacon_node_urls_proposal) > 0:
        assert any(_override_log_string in m for m in caplog.messages)
    else:
        assert all(_override_log_string not in m for m in caplog.messages)
