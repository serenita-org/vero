import asyncio
from unittest import mock

import pytest

from providers import BeaconChain, Keymanager, Vero
from schemas import SchemaBeaconAPI
from schemas.shared import ForkVersion
from schemas.validator import ValidatorIndexPubkey
from services import BlockProposalService
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
async def test_publish_payload_envelope(
    block_proposal_service: BlockProposalService,
    beacon_chain: BeaconChain,
    random_active_validator: ValidatorIndexPubkey,
    fork_version: ForkVersion,
    caplog: pytest.LogCaptureFixture,
) -> None:
    slot = beacon_chain.current_slot + 1
    duty = SchemaBeaconAPI.ProposerDuty(
        pubkey=random_active_validator.pubkey,
        validator_index=str(random_active_validator.index),
        slot=str(slot),
    )

    await block_proposal_service._publish_payload_envelope(
        slot=slot,
        duty=duty,
        beacon_block_root=ZERO_ROOT,
        beacon_node=block_proposal_service.multi_beacon_node.beacon_nodes[0],
    )

    assert any("Published payload envelope" in m for m in caplog.messages)


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


@pytest.mark.parametrize("fail_all_first_epoch", [False, True])
async def test_submit_proposer_preferences_signing_failures(
    block_proposal_service: BlockProposalService,
    fail_all_first_epoch: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = block_proposal_service
    epoch = max(
        service.beacon_chain.current_epoch + 1, service.beacon_chain.GLOAS_FORK_EPOCH
    )
    first_slot = epoch * service.beacon_chain.SLOTS_PER_EPOCH
    service.proposer_duties.clear()
    service.proposer_duties.update(
        {
            epoch: {
                SchemaBeaconAPI.ProposerDuty(
                    pubkey="bad", validator_index="1", slot=str(first_slot)
                ),
                SchemaBeaconAPI.ProposerDuty(
                    pubkey="good", validator_index="2", slot=str(first_slot + 1)
                ),
            },
            epoch + 1: {
                SchemaBeaconAPI.ProposerDuty(
                    pubkey="later",
                    validator_index="3",
                    slot=str(first_slot + service.beacon_chain.SLOTS_PER_EPOCH),
                )
            },
        }
    )
    service.proposer_duties_dependent_roots = {epoch: ZERO_ROOT, epoch + 1: ZERO_ROOT}

    async def sign(message: object, identifier: str) -> tuple[object, str, None]:
        if identifier == "bad" or (fail_all_first_epoch and identifier == "good"):
            raise RuntimeError("signing failed")
        return message, "signature", None

    with (
        mock.patch.object(service.signature_provider, "sign", side_effect=sign),
        mock.patch.object(
            service.multi_beacon_node, "submit_proposer_preferences"
        ) as submit,
    ):
        await service.submit_proposer_preferences()

    submitted = [
        preferences.validator_index
        for call in submit.call_args_list
        for preferences, _ in call.kwargs["signed_proposer_preferences"]
    ]
    assert submitted == (["3"] if fail_all_first_epoch else ["2", "3"])
    assert any(
        "Failed to sign proposer preferences for validator bad" in m
        for m in caplog.messages
    )


async def test_duty_refresh_schedules_proposer_preferences(
    block_proposal_service: BlockProposalService,
) -> None:
    service = block_proposal_service
    service.proposer_duties_dependent_roots.clear()
    with mock.patch.object(service.task_manager, "create_task") as create_task:
        await service._update_duties()
        preferences_calls = [
            call
            for call in create_task.call_args_list
            if call.args[0].cr_code.co_name == "submit_proposer_preferences"
        ]
        for call in create_task.call_args_list:
            call.args[0].close()

    assert len(preferences_calls) == 1
    assert service.proposer_duties_dependent_roots
    assert set(service.proposer_duties) <= set(service.proposer_duties_dependent_roots)
