import random
from asyncio import AbstractEventLoop
from collections.abc import AsyncGenerator

import milagro_bls_binding as bls
import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs, _process_attestation_consensus_threshold
from observability import init_observability
from providers import BeaconChain, MultiBeaconNode, RemoteSigner
from schemas import SchemaBeaconAPI
from schemas.validator import ACTIVE_STATUSES, ValidatorIndexPubkey
from services import ValidatorStatusTrackerService
from spec.configs import Network

# A few more global fixtures defined separately
from tests.mock_api.base import *
from tests.mock_api.beacon_node import *
from tests.mock_api.beacon_node import (
    _beacon_block_class_init,
    _mocked_beacon_node_endpoints,
    _sync_committee_contribution_class_init,
)
from tests.mock_api.remote_signer import *
from tests.mock_api.remote_signer import _mocked_remote_signer_endpoints


@pytest.fixture
def beacon_node_urls_proposal(request: pytest.FixtureRequest) -> list[str]:
    return getattr(request, "param", [])


@pytest.fixture
def cli_args(
    remote_signer_url: str,
    beacon_node_url: str,
    beacon_node_urls_proposal: list[str],
) -> CLIArgs:
    return CLIArgs(
        network=Network.FETCH,
        remote_signer_url=remote_signer_url,
        beacon_node_urls=[beacon_node_url],
        beacon_node_urls_proposal=beacon_node_urls_proposal,
        attestation_consensus_threshold=_process_attestation_consensus_threshold(
            None, [beacon_node_url]
        ),
        fee_recipient="0x0000000000000000000000000000000000000000",
        data_dir="/tmp/vero_tests",
        use_external_builder=False,
        builder_boost_factor=90,
        graffiti=b"pytest",
        gas_limit=30_000_000,
        metrics_address="localhost",
        metrics_port=8000,
        metrics_multiprocess_mode=False,
        log_level="INFO",
    )


@pytest.fixture(autouse=True, scope="session")
def _init_observability() -> None:
    init_observability(
        metrics_address="localhost",
        metrics_port=8080,
        metrics_multiprocess_mode=False,
        log_level="DEBUG",
    )


@pytest.fixture(scope="session")
def validator_privkeys() -> list[bytes]:
    return [
        bytes.fromhex(
            "3790d84ccaa187d6446929de4334244f1533290f3ec59c35bbabe29b65cf75f5"
        ),
        bytes.fromhex(
            "6159530651e3024960127c55e55b76c5c4a993ed20d86e823e4071facd77ef46"
        ),
        bytes.fromhex(
            "06d2402dea01ef37a38d5e88c1373233a63714111d1444e60b3d7a77995f6c69"
        ),
        bytes.fromhex(
            "1a642fe520729113c35da46751cdf68485412a7d9dfe64deb91ccee9e84c0ec3"
        ),
        bytes.fromhex(
            "1da22e7f7b0970f9d6deffe15b861dfd8673e130977b680f4aa9c668a38855af"
        ),
    ]


@pytest.fixture(scope="session")
def validators(validator_privkeys: list[bytes]) -> list[ValidatorIndexPubkey]:
    return [
        ValidatorIndexPubkey(
            index=0,
            pubkey="0x" + bls.SkToPk(validator_privkeys[0]).hex(),
            status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=1,
            pubkey="0x" + bls.SkToPk(validator_privkeys[1]).hex(),
            status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=2,
            pubkey="0x" + bls.SkToPk(validator_privkeys[2]).hex(),
            status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=3,
            pubkey="0x" + bls.SkToPk(validator_privkeys[3]).hex(),
            status=SchemaBeaconAPI.ValidatorStatus.PENDING_QUEUED,
        ),
        ValidatorIndexPubkey(
            index=4,
            pubkey="0x" + bls.SkToPk(validator_privkeys[4]).hex(),
            status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_EXITING,
        ),
    ]


@pytest.fixture(scope="session")
def random_active_validator(
    validators: list[ValidatorIndexPubkey],
) -> ValidatorIndexPubkey:
    return random.choice([v for v in validators if v.status in ACTIVE_STATUSES])


@pytest.fixture
async def remote_signer(
    cli_args: CLIArgs,
    _mocked_remote_signer_endpoints: None,
) -> AsyncGenerator[RemoteSigner, None]:
    async with RemoteSigner(url=cli_args.remote_signer_url) as remote_signer:
        yield remote_signer


@pytest.fixture
async def scheduler(
    event_loop: AbstractEventLoop,
) -> AsyncGenerator[AsyncIOScheduler, None]:
    _scheduler = AsyncIOScheduler(event_loop=event_loop)
    _scheduler.start()
    yield _scheduler
    _scheduler.shutdown(wait=False)


@pytest.fixture
async def validator_status_tracker(
    multi_beacon_node: MultiBeaconNode,
    beacon_chain: BeaconChain,
    remote_signer: RemoteSigner,
    scheduler: AsyncIOScheduler,
) -> ValidatorStatusTrackerService:
    validator_status_tracker = ValidatorStatusTrackerService(
        multi_beacon_node=multi_beacon_node,
        beacon_chain=beacon_chain,
        remote_signer=remote_signer,
        scheduler=scheduler,
    )
    await validator_status_tracker.initialize()
    return validator_status_tracker


@pytest.fixture
async def multi_beacon_node(
    cli_args: CLIArgs,
    _mocked_beacon_node_endpoints: None,
    scheduler: AsyncIOScheduler,
) -> AsyncGenerator[MultiBeaconNode, None]:
    async with MultiBeaconNode(
        beacon_node_urls=cli_args.beacon_node_urls,
        beacon_node_urls_proposal=cli_args.beacon_node_urls_proposal,
        scheduler=scheduler,
        cli_args=cli_args,
    ) as mbn:
        yield mbn


@pytest.fixture
async def beacon_chain(multi_beacon_node: MultiBeaconNode) -> BeaconChain:
    return BeaconChain(multi_beacon_node=multi_beacon_node)
