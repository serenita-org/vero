import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs
from providers import BeaconChain, MultiBeaconNode, RemoteSigner
from services import (
    AttestationService,
    BlockProposalService,
    ValidatorStatusTrackerService,
)
from services.validator_duty_service import ValidatorDutyServiceOptions
from spec.base import SpecDeneb
from tasks import TaskManager


@pytest.fixture
def validator_duty_service_options(
    multi_beacon_node: MultiBeaconNode,
    beacon_chain: BeaconChain,
    spec_deneb: SpecDeneb,
    remote_signer: RemoteSigner,
    validator_status_tracker: ValidatorStatusTrackerService,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
    cli_args: CLIArgs,
) -> ValidatorDutyServiceOptions:
    return dict(
        multi_beacon_node=multi_beacon_node,
        beacon_chain=beacon_chain,
        spec=spec_deneb,
        remote_signer=remote_signer,
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
