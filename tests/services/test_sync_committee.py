import os

import pytest

from providers import BeaconChain
from schemas import SchemaBeaconAPI
from schemas.validator import ValidatorIndexPubkey
from services import SyncCommitteeService
from services.sync_committee import (
    _VC_PUBLISHED_SYNC_COMMITTEE_MESSAGES,
    _VC_PUBLISHED_SYNC_COMMITTEE_CONTRIBUTIONS,
)
from services.validator_duty_service import ValidatorDutyServiceOptions
from spec.base import SpecDeneb


@pytest.fixture
def sync_committee_service(
    validator_duty_service_options: ValidatorDutyServiceOptions,
) -> SyncCommitteeService:
    return SyncCommitteeService(**validator_duty_service_options)


async def test_update_duties(sync_committee_service: SyncCommitteeService) -> None:
    # This test just checks that no exception is thrown
    assert len(sync_committee_service.sync_duties) == 0
    await sync_committee_service._update_duties()
    assert len(sync_committee_service.sync_duties) > 0


async def test_produce_sync_message_if_not_yet_produced(
    sync_committee_service: SyncCommitteeService,
    beacon_chain: BeaconChain,
    random_active_validator: ValidatorIndexPubkey,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Populate the service with a sync duty
    duty_slot = beacon_chain.current_slot

    # See https://github.com/ethereum/consensus-specs/blob/dev/specs/altair/validator.md#sync-committee
    sync_period = beacon_chain.compute_sync_period_for_slot(duty_slot + 1)

    sync_committee_service.sync_duties[sync_period] = [
        SchemaBeaconAPI.SyncDuty(
            pubkey=random_active_validator.pubkey,
            validator_index=random_active_validator.index,
            validator_sync_committee_indices=[1, 3],
        )
    ]

    sync_messages_published_before = _VC_PUBLISHED_SYNC_COMMITTEE_MESSAGES._value.get()
    await sync_committee_service.produce_sync_message_if_not_yet_produced(
        duty_slot=duty_slot,
    )

    assert any("Published sync committee messages" in m for m in caplog.messages)
    assert (
        _VC_PUBLISHED_SYNC_COMMITTEE_MESSAGES._value.get()
        == sync_messages_published_before + 1
    )


async def test_aggregate_sync_messages(
    sync_committee_service: SyncCommitteeService,
    beacon_chain: BeaconChain,
    spec_deneb: SpecDeneb,
    random_active_validator: ValidatorIndexPubkey,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Populate the service with a sync contribution duty
    duty_slot = beacon_chain.current_slot

    duties_with_proofs = [
        SchemaBeaconAPI.SyncDutyWithSelectionProofs(
            pubkey=random_active_validator.pubkey,
            validator_index=random_active_validator.index,
            validator_sync_committee_indices=[1, 3],
            selection_proofs=[
                SchemaBeaconAPI.SyncDutySubCommitteeSelectionProof(
                    slot=duty_slot + 1,
                    subcommittee_index=subcommittee_index,
                    is_aggregator=True,
                    selection_proof=os.urandom(96),
                )
                for subcommittee_index in range(0, 5)
            ],
        )
    ]

    contributions_produced_before = (
        _VC_PUBLISHED_SYNC_COMMITTEE_CONTRIBUTIONS._value.get()
    )
    await sync_committee_service.aggregate_sync_messages(
        duties_with_proofs=duties_with_proofs,
        duty_slot=duty_slot,
        beacon_block_root="0x" + os.urandom(32).hex(),
    )

    assert any(
        "Published sync committee contribution and proofs" in m for m in caplog.messages
    )
    assert (
        _VC_PUBLISHED_SYNC_COMMITTEE_CONTRIBUTIONS._value.get()
        > contributions_produced_before
    )
