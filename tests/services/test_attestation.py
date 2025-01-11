import asyncio
import os
import random

import pytest

from providers import BeaconChain
from schemas import SchemaBeaconAPI
from schemas.validator import ValidatorIndexPubkey
from services import AttestationService
from services.attestation import (
    _VC_PUBLISHED_AGGREGATE_ATTESTATIONS,
    _VC_PUBLISHED_ATTESTATIONS,
)
from spec.attestation import AttestationData
from spec.base import SpecDeneb


async def test_update_duties(attestation_service: AttestationService) -> None:
    # This test just checks that no exception is thrown
    assert len(attestation_service.attester_duties) == 0
    await attestation_service._update_duties()
    assert len(attestation_service.attester_duties) > 0


async def test_attest_if_not_yet_attested(
    attestation_service: AttestationService,
    beacon_chain: BeaconChain,
    spec_deneb: SpecDeneb,
    random_active_validator: ValidatorIndexPubkey,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Populate the service with an attester duty
    duty_slot = beacon_chain.current_slot + 1
    duty_epoch = duty_slot // beacon_chain.spec.SLOTS_PER_EPOCH

    attestation_service.attester_duties[duty_epoch].add(
        SchemaBeaconAPI.AttesterDutyWithSelectionProof(
            pubkey=random_active_validator.pubkey,
            validator_index=str(random_active_validator.index),
            committee_index=str(
                random.randint(
                    0,
                    spec_deneb.TARGET_AGGREGATORS_PER_COMMITTEE,
                )
            ),
            committee_length=str(spec_deneb.TARGET_AGGREGATORS_PER_COMMITTEE),
            committees_at_slot=str(random.randint(0, 10)),
            validator_committee_index=str(
                random.randint(
                    0,
                    spec_deneb.TARGET_AGGREGATORS_PER_COMMITTEE - 1,
                )
            ),
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
    argnames=[
        "slot_offset",
    ],
    argvalues=[pytest.param(10, id="future slot"), pytest.param(-10, id="past slot")],
)
async def test_attest_to_invalid_slot(
    slot_offset: int,
    attestation_service: AttestationService,
    beacon_chain: BeaconChain,
    caplog: pytest.LogCaptureFixture,
) -> None:
    atts_published_before = _VC_PUBLISHED_ATTESTATIONS._value.get()
    await attestation_service.attest_if_not_yet_attested(
        slot=beacon_chain.current_slot + slot_offset
    )

    assert any("Invalid slot for attestation" in m for m in caplog.messages)
    assert _VC_PUBLISHED_ATTESTATIONS._value.get() == atts_published_before


async def test_aggregate_attestations(
    attestation_service: AttestationService,
    beacon_chain: BeaconChain,
    spec_deneb: SpecDeneb,
    random_active_validator: ValidatorIndexPubkey,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Create an attester aggregation duty
    duty_slot = beacon_chain.current_slot

    slot_attester_duties = {
        SchemaBeaconAPI.AttesterDutyWithSelectionProof(
            pubkey=random_active_validator.pubkey,
            validator_index=str(random_active_validator.index),
            committee_index=str(123),
            committee_length=str(spec_deneb.TARGET_AGGREGATORS_PER_COMMITTEE),
            committees_at_slot=str(random.randint(0, 10)),
            validator_committee_index=str(
                random.randint(
                    0,
                    spec_deneb.TARGET_AGGREGATORS_PER_COMMITTEE,
                )
            ),
            slot=str(duty_slot),
            is_aggregator=True,
            selection_proof=os.urandom(96),
        ),
    }

    att_data = AttestationData(
        slot=duty_slot,
        index=0,
        beacon_block_root="0x" + os.urandom(32).hex(),
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
