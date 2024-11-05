import pytest

from schemas import SchemaBeaconAPI
from services import (
    AttestationService,
    BlockProposalService,
    ValidatorStatusTrackerService,
)
from services.validator_status_tracker import _SLASHING_DETECTED


@pytest.fixture
def _reset_slashing_detected_metric() -> None:
    # Resets the value of this metric
    # before each test
    _SLASHING_DETECTED.set(0)


@pytest.mark.parametrize(
    ("event", "our_validator_affected"),
    [
        pytest.param(
            SchemaBeaconAPI.AttesterSlashingEvent(
                attestation_1=SchemaBeaconAPI.AttesterSlashingEventAttestation(
                    attesting_indices=["1", "2", "3", "4", "5"],
                ),
                attestation_2=SchemaBeaconAPI.AttesterSlashingEventAttestation(
                    attesting_indices=["4", "8", "9", "10"],
                ),
            ),
            True,
            id="Attester slashing for 'our' validator (#4)",
        ),
        pytest.param(
            SchemaBeaconAPI.AttesterSlashingEvent(
                attestation_1=SchemaBeaconAPI.AttesterSlashingEventAttestation(
                    attesting_indices=["1", "2", "3", "4", "5", "10", "11"],
                ),
                attestation_2=SchemaBeaconAPI.AttesterSlashingEventAttestation(
                    attesting_indices=["10", "11"],
                ),
            ),
            False,
            id="Attester slashings for a validator not managed by 'us' (#10, #11)",
        ),
        pytest.param(
            SchemaBeaconAPI.ProposerSlashingEvent(
                signed_header_1=SchemaBeaconAPI.ProposerSlashingEventData(
                    message=SchemaBeaconAPI.ProposerSlashingEventMessage(
                        proposer_index="4",
                    ),
                ),
                signed_header_2=SchemaBeaconAPI.ProposerSlashingEventData(
                    message=SchemaBeaconAPI.ProposerSlashingEventMessage(
                        proposer_index="4",
                    ),
                ),
            ),
            True,
            id="Proposer slashing for 'our' validator (#4)",
        ),
        pytest.param(
            SchemaBeaconAPI.ProposerSlashingEvent(
                signed_header_1=SchemaBeaconAPI.ProposerSlashingEventData(
                    message=SchemaBeaconAPI.ProposerSlashingEventMessage(
                        proposer_index="10",
                    ),
                ),
                signed_header_2=SchemaBeaconAPI.ProposerSlashingEventData(
                    message=SchemaBeaconAPI.ProposerSlashingEventMessage(
                        proposer_index="10",
                    ),
                ),
            ),
            False,
            id="Proposer slashing for 'our' validator (#4)",
        ),
    ],
)
@pytest.mark.usefixtures("_reset_slashing_detected_metric")
async def test_handle_slashing_event(
    event: SchemaBeaconAPI.AttesterSlashingEvent
    | SchemaBeaconAPI.ProposerSlashingEvent,
    our_validator_affected: bool,
    validator_status_tracker: ValidatorStatusTrackerService,
    attestation_service: AttestationService,
    block_proposal_service: BlockProposalService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await validator_status_tracker.handle_slashing_event(event=event)

    event_type = (
        "attester"
        if isinstance(event, SchemaBeaconAPI.AttesterSlashingEvent)
        else "proposer"
    )
    assert any(f"Processed {event_type} slashing event" in m for m in caplog.messages)

    if not our_validator_affected:
        assert validator_status_tracker.slashing_detected is False
        assert _SLASHING_DETECTED._value.get() == 0

    if our_validator_affected:
        assert any("Slashing detected" in m for m in caplog.messages)
        assert any(record.levelname == "CRITICAL" for record in caplog.records)

        # ValidatorStatusTracker property value should be set
        assert validator_status_tracker.slashing_detected is True

        # Metric value should be set
        assert _SLASHING_DETECTED._value.get() == 1

        # Slashable services should stop performing duties
        with pytest.raises(RuntimeError, match="Slashing detected"):
            await attestation_service.attest_if_not_yet_attested(slot=124)

        with pytest.raises(RuntimeError, match="Slashing detected"):
            await block_proposal_service.propose_block(slot=124)
