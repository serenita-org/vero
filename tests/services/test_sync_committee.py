import os

import pytest

from providers import BeaconChain, Vero
from schemas import SchemaBeaconAPI
from schemas.validator import ValidatorIndexPubkey
from services import SyncCommitteeService


@pytest.mark.parametrize(
    "enable_keymanager_api",
    [
        pytest.param(False, id="signature_provider: RemoteSigner"),
        pytest.param(True, id="signature_provider: Keymanager"),
    ],
    indirect=True,
)
async def test_update_duties(
    sync_committee_service: SyncCommitteeService, enable_keymanager_api: bool
) -> None:
    # This test just checks that no exception is thrown
    assert len(sync_committee_service.sync_duties) == 0
    await sync_committee_service._update_duties()
    assert len(sync_committee_service.sync_duties) > 0


@pytest.mark.parametrize(
    "enable_keymanager_api",
    [
        pytest.param(False, id="signature_provider: RemoteSigner"),
        pytest.param(True, id="signature_provider: Keymanager"),
    ],
    indirect=True,
)
async def test_produce_sync_message(
    sync_committee_service: SyncCommitteeService,
    beacon_chain: BeaconChain,
    random_active_validator: ValidatorIndexPubkey,
    enable_keymanager_api: bool,
    vero: Vero,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Populate the service with a sync duty
    duty_slot = beacon_chain.current_slot

    # See https://github.com/ethereum/consensus-specs/blob/dev/specs/altair/validator.md#sync-committee
    sync_period = beacon_chain.compute_sync_period_for_slot(duty_slot + 1)

    sync_committee_service.sync_duties[sync_period] = [
        SchemaBeaconAPI.SyncDuty(
            pubkey=random_active_validator.pubkey,
            validator_index=str(random_active_validator.index),
            validator_sync_committee_indices=["1", "3"],
        ),
    ]
    sync_committee_service._last_slot_duty_started_for = 0
    sync_committee_service._last_slot_duty_completed_for = 0

    sync_messages_published_before = (
        vero.metrics.vc_published_sync_committee_messages_c._value.get()
    )
    await sync_committee_service.produce_sync_message(duty_slot=duty_slot)

    assert any("Published sync committee messages" in m for m in caplog.messages)
    assert (
        vero.metrics.vc_published_sync_committee_messages_c._value.get()
        == sync_messages_published_before + 1
    )
    assert sync_committee_service._last_slot_duty_started_for == duty_slot
    assert sync_committee_service._last_slot_duty_completed_for == duty_slot


@pytest.mark.parametrize(
    "enable_keymanager_api",
    [
        pytest.param(False, id="signature_provider: RemoteSigner"),
        pytest.param(True, id="signature_provider: Keymanager"),
    ],
    indirect=True,
)
async def test_aggregate_sync_messages(
    sync_committee_service: SyncCommitteeService,
    beacon_chain: BeaconChain,
    random_active_validator: ValidatorIndexPubkey,
    enable_keymanager_api: bool,
    vero: Vero,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Populate the service with a sync contribution duty
    duty_slot = beacon_chain.current_slot

    duties_with_proofs = [
        SchemaBeaconAPI.SyncDutyWithSelectionProofs(
            pubkey=random_active_validator.pubkey,
            validator_index=str(random_active_validator.index),
            validator_sync_committee_indices=["1", "3"],
            selection_proofs=[
                SchemaBeaconAPI.SyncDutySubCommitteeSelectionProof(
                    slot=duty_slot + 1,
                    subcommittee_index=subcommittee_index,
                    is_aggregator=True,
                    selection_proof=os.urandom(96),
                )
                for subcommittee_index in range(5)
            ],
        ),
    ]

    contributions_produced_before = (
        vero.metrics.vc_published_sync_committee_contributions_c._value.get()
    )
    await sync_committee_service.aggregate_sync_messages(
        duty_slot=duty_slot,
        beacon_block_root="0x" + os.urandom(32).hex(),
        duties_with_proofs=duties_with_proofs,
    )

    assert any(
        "Published sync committee contribution and proofs" in m for m in caplog.messages
    )
    assert (
        vero.metrics.vc_published_sync_committee_contributions_c._value.get()
        > contributions_produced_before
    )


async def test_update_duties_exited_validators(
    vero: Vero, caplog: pytest.LogCaptureFixture
) -> None:
    """
    # Tests that we update sync duties for exited validators too since
    # it is possible for an exited validator to be scheduled for
    # sync commitee duties (when scheduled shortly before the
    # validator exits).
    # See https://ethresear.ch/t/sync-committees-exited-validators-participating-in-sync-committee/15634
    """

    class MockValidatorStatusTrackerService:
        def __init__(self) -> None:
            self.active_or_pending_indices = [1, 2, 3]
            self.exited_or_withdrawal_indices = [4, 5]

    service = SyncCommitteeService(
        multi_beacon_node=None,  # type: ignore[arg-type]
        signature_provider=None,  # type: ignore[arg-type]
        keymanager=None,  # type: ignore[arg-type]
        duty_cache=None,  # type: ignore[arg-type]
        validator_status_tracker_service=MockValidatorStatusTrackerService(),  # type: ignore[arg-type]
        vero=vero,
    )

    with pytest.raises(
        AttributeError, match="'NoneType' object has no attribute 'get_sync_duties'"
    ):
        await service._update_duties()

    # We should be requesting duties for the exited validators too
    assert any(
        "Updating sync commitee duties for 5 validators" in m for m in caplog.messages
    )
