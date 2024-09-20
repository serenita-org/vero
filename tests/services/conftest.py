import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs
from providers import MultiBeaconNode, BeaconChain, RemoteSigner
from services import (
    ValidatorStatusTrackerService,
    AttestationService,
    BlockProposalService,
)
from services.validator_duty_service import ValidatorDutyServiceOptions


@pytest.fixture
def validator_duty_service_options(
    multi_beacon_node: MultiBeaconNode,
    beacon_chain: BeaconChain,
    remote_signer: RemoteSigner,
    validator_status_tracker: ValidatorStatusTrackerService,
    scheduler: AsyncIOScheduler,
    cli_args: CLIArgs,
) -> ValidatorDutyServiceOptions:
    return dict(
        multi_beacon_node=multi_beacon_node,
        beacon_chain=beacon_chain,
        remote_signer=remote_signer,
        validator_status_tracker_service=validator_status_tracker,
        scheduler=scheduler,
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
