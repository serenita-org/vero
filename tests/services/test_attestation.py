import asyncio
import os

import pytest

from providers import BeaconChain
from schemas import SchemaBeaconAPI
from schemas.beacon_api import ForkVersion, ValidatorStatus
from schemas.validator import ValidatorIndexPubkey
from services import AttestationService
from services.attestation import (
    _VC_PUBLISHED_AGGREGATE_ATTESTATIONS,
    _VC_PUBLISHED_ATTESTATIONS,
)


@pytest.mark.parametrize(
    "enable_keymanager_api",
    [
        pytest.param(False, id="signature_provider: RemoteSigner"),
        pytest.param(True, id="signature_provider: Keymanager"),
    ],
    indirect=True,
)
async def test_update_duties(attestation_service: AttestationService) -> None:
    # This test just checks that no exception is thrown
    assert len(attestation_service.attester_duties) == 0
    await attestation_service._update_duties()
    assert len(attestation_service.attester_duties) > 0


@pytest.mark.parametrize(
    "fork_version",
    [
        pytest.param(ForkVersion.ELECTRA, id="Electra"),
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
async def test_attest_if_not_yet_attested(
    attestation_service: AttestationService,
    beacon_chain: BeaconChain,
    validators: list[ValidatorIndexPubkey],
    fork_version: ForkVersion,
    enable_keymanager_api: bool,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Populate the service with an attester duty
    duty_slot = beacon_chain.current_slot + 1
    duty_epoch = duty_slot // beacon_chain.SLOTS_PER_EPOCH

    first_active_validator = next(
        v for v in validators if v.status == ValidatorStatus.ACTIVE_ONGOING
    )

    attestation_service.attester_duties[duty_epoch].add(
        SchemaBeaconAPI.AttesterDutyWithSelectionProof(
            pubkey=first_active_validator.pubkey,
            validator_index=str(first_active_validator.index),
            committee_index=str(14),
            committee_length=str(16),
            committees_at_slot=str(20),
            validator_committee_index=str(9),
            slot=str(duty_slot),
            is_aggregator=False,
            selection_proof=os.urandom(96),
        ),
    )
    attestation_service._last_slot_duty_started_for = 0
    attestation_service._last_slot_duty_completed_for = 0

    atts_published_before = _VC_PUBLISHED_ATTESTATIONS._value.get()

    # Wait for slot to start
    await asyncio.sleep(max(0.0, -beacon_chain.time_since_slot_start(duty_slot)))
    await attestation_service.attest_if_not_yet_attested(slot=duty_slot)

    assert any("Published attestations" in m for m in caplog.messages)
    assert _VC_PUBLISHED_ATTESTATIONS._value.get() == atts_published_before + 1
    assert attestation_service._last_slot_duty_started_for == duty_slot
    assert attestation_service._last_slot_duty_completed_for == duty_slot


@pytest.mark.parametrize(
    argnames="slot_offset",
    argvalues=[pytest.param(10, id="future slot"), pytest.param(-10, id="past slot")],
)
async def test_attest_to_invalid_slot(
    slot_offset: int,
    attestation_service: AttestationService,
    beacon_chain: BeaconChain,
    caplog: pytest.LogCaptureFixture,
) -> None:
    atts_published_before = _VC_PUBLISHED_ATTESTATIONS._value.get()
    with pytest.raises(RuntimeError, match="Invalid slot for attestation: "):
        await attestation_service.attest_if_not_yet_attested(
            slot=beacon_chain.current_slot + slot_offset
        )

    assert _VC_PUBLISHED_ATTESTATIONS._value.get() == atts_published_before


@pytest.mark.parametrize(
    "fork_version",
    [
        pytest.param(ForkVersion.ELECTRA, id="Electra"),
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
async def test_aggregate_attestations(
    attestation_service: AttestationService,
    beacon_chain: BeaconChain,
    fork_version: ForkVersion,
    enable_keymanager_api: bool,
    validators: list[ValidatorIndexPubkey],
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Create an attester aggregation duty
    duty_slot = beacon_chain.current_slot

    second_active_validator = [
        v for v in validators if v.status == ValidatorStatus.ACTIVE_ONGOING
    ][1]

    slot_attester_duties = {
        SchemaBeaconAPI.AttesterDutyWithSelectionProof(
            pubkey=second_active_validator.pubkey,
            validator_index=str(second_active_validator.index),
            committee_index=str(14),
            committee_length=str(16),
            committees_at_slot=str(20),
            validator_committee_index=str(9),
            slot=str(duty_slot),
            is_aggregator=True,
            selection_proof=os.urandom(96),
        ),
    }

    att_data = SchemaBeaconAPI.AttestationData(
        slot=str(duty_slot),
        index="0",
        beacon_block_root="0x9f19cc6499596bdf19be76d80b878ee3326e68cf2ed69cbada9a1f4fe13c51b3",
        source=SchemaBeaconAPI.Checkpoint(
            epoch="0",
            root="0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        ),
        target=SchemaBeaconAPI.Checkpoint(
            epoch="1",
            root="0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        ),
    )

    aggregates_produced_before = _VC_PUBLISHED_AGGREGATE_ATTESTATIONS._value.get()
    await attestation_service.aggregate_attestations(
        slot=duty_slot,
        att_data=att_data,
        aggregator_duties=[d for d in slot_attester_duties if d.is_aggregator],
    )

    assert any("Published aggregate and proofs" in m for m in caplog.messages)
    assert (
        _VC_PUBLISHED_AGGREGATE_ATTESTATIONS._value.get()
        == aggregates_produced_before + 1
    )
