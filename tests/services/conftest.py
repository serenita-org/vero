from typing import Any

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs
from providers import MultiBeaconNode, BeaconChain, RemoteSigner
from services import (
    ValidatorStatusTrackerService,
    AttestationService,
    BlockProposalService,
)


@pytest.fixture
def validator_service_kwargs(
    multi_beacon_node: MultiBeaconNode,
    beacon_chain: BeaconChain,
    remote_signer: RemoteSigner,
    validator_status_tracker: ValidatorStatusTrackerService,
    scheduler: AsyncIOScheduler,
    cli_args: CLIArgs,
) -> dict[str, Any]:
    return dict(
        multi_beacon_node=multi_beacon_node,
        beacon_chain=beacon_chain,
        remote_signer=remote_signer,
        validator_status_tracker_service=validator_status_tracker,
        scheduler=scheduler,
        cli_args=cli_args,
    )


@pytest.fixture
def attestation_service(validator_service_kwargs) -> AttestationService:
    return AttestationService(**validator_service_kwargs)


@pytest.fixture
def block_proposal_service(validator_service_kwargs) -> BlockProposalService:
    return BlockProposalService(**validator_service_kwargs)
