import pytest

from providers import (
    DutyCache,
    Keymanager,
    MultiBeaconNode,
    SignatureProvider,
    Vero,
)
from services import (
    AttestationService,
    BlockProposalService,
    SyncCommitteeService,
    ValidatorStatusTrackerService,
)
from services.validator_duty_service import ValidatorDutyServiceOptions


@pytest.fixture
def validator_duty_service_options(
    multi_beacon_node: MultiBeaconNode,
    signature_provider: SignatureProvider,
    keymanager: Keymanager,
    duty_cache: DutyCache,
    validator_status_tracker: ValidatorStatusTrackerService,
    vero: Vero,
) -> ValidatorDutyServiceOptions:
    return ValidatorDutyServiceOptions(
        multi_beacon_node=multi_beacon_node,
        signature_provider=signature_provider,
        keymanager=keymanager,
        duty_cache=duty_cache,
        validator_status_tracker_service=validator_status_tracker,
        vero=vero,
    )


@pytest.fixture
def attestation_service(
    validator_duty_service_options: ValidatorDutyServiceOptions,
) -> AttestationService:
    return AttestationService(**validator_duty_service_options)


@pytest.fixture
def block_proposal_service(
    validator_duty_service_options: ValidatorDutyServiceOptions,
) -> BlockProposalService:
    return BlockProposalService(**validator_duty_service_options)


@pytest.fixture
def sync_committee_service(
    validator_duty_service_options: ValidatorDutyServiceOptions,
) -> SyncCommitteeService:
    return SyncCommitteeService(**validator_duty_service_options)
