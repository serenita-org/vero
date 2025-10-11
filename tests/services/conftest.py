from typing import TYPE_CHECKING

import pytest

from services import (
    AttestationService,
    BlockProposalService,
    SyncCommitteeService,
    ValidatorStatusTrackerService,
)
from services.validator_duty_service import ValidatorDutyServiceOptions

if TYPE_CHECKING:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    from args import CLIArgs
    from providers import (
        BeaconChain,
        DutyCache,
        Keymanager,
        MultiBeaconNode,
        SignatureProvider,
    )
    from tasks import TaskManager


@pytest.fixture
def validator_duty_service_options(
    multi_beacon_node: MultiBeaconNode,
    beacon_chain: BeaconChain,
    signature_provider: SignatureProvider,
    keymanager: Keymanager,
    duty_cache: DutyCache,
    validator_status_tracker: ValidatorStatusTrackerService,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
    cli_args: CLIArgs,
) -> ValidatorDutyServiceOptions:
    return ValidatorDutyServiceOptions(
        multi_beacon_node=multi_beacon_node,
        beacon_chain=beacon_chain,
        signature_provider=signature_provider,
        keymanager=keymanager,
        duty_cache=duty_cache,
        validator_status_tracker_service=validator_status_tracker,
        scheduler=scheduler,
        task_manager=task_manager,
        cli_args=cli_args,
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
