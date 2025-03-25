import asyncio
import datetime
import random
from asyncio import AbstractEventLoop
from collections.abc import AsyncGenerator, Generator
from unittest import mock

import milagro_bls_binding as bls
import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs, _process_attestation_consensus_threshold
from observability import init_observability
from providers import BeaconChain, MultiBeaconNode, RemoteSigner
from schemas import SchemaBeaconAPI
from schemas.beacon_api import ForkVersion
from schemas.validator import ACTIVE_STATUSES, ValidatorIndexPubkey
from services import ValidatorStatusTrackerService
from spec import SpecAttestation, SpecBeaconBlock, SpecSyncCommittee
from spec.base import SpecElectra, Fork, Genesis, Version
from spec.common import Epoch
from spec.configs import Network, get_network_spec
from tasks import TaskManager

# A few more global fixtures defined separately
from tests.mock_api.base import *
from tests.mock_api.beacon_node import *
from tests.mock_api.beacon_node import (
    _mocked_beacon_node_endpoints,
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
        network=Network._TESTS,
        network_custom_config_path=None,
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
        disable_slashing_detection=False,
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
def spec(request: pytest.FixtureRequest) -> SpecElectra:
    return get_network_spec(network=Network._TESTS)


@pytest.fixture(autouse=True, scope="session")
def _init_spec(spec: SpecElectra) -> None:
    SpecAttestation.initialize(spec=spec)
    SpecBeaconBlock.initialize(spec=spec)
    SpecSyncCommittee.initialize(spec=spec)


@pytest.fixture
def fork_version(
    request: pytest.FixtureRequest, beacon_chain: BeaconChain
) -> Generator[None, None, None]:
    requested_fork_version = getattr(request, "param", ForkVersion.ELECTRA)

    with mock.patch.object(
        beacon_chain, "current_fork_version", requested_fork_version
    ):
        yield


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
def task_manager() -> TaskManager:
    return TaskManager(shutdown_event=asyncio.Event())


@pytest.fixture
async def validator_status_tracker(
    multi_beacon_node: MultiBeaconNode,
    beacon_chain: BeaconChain,
    remote_signer: RemoteSigner,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
) -> ValidatorStatusTrackerService:
    validator_status_tracker = ValidatorStatusTrackerService(
        multi_beacon_node=multi_beacon_node,
        beacon_chain=beacon_chain,
        remote_signer=remote_signer,
        scheduler=scheduler,
        task_manager=task_manager,
    )
    await validator_status_tracker.initialize()
    return validator_status_tracker


@pytest.fixture
async def multi_beacon_node(
    cli_args: CLIArgs,
    _mocked_beacon_node_endpoints: None,
    spec: SpecElectra,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
    beacon_chain: BeaconChain,
) -> AsyncGenerator[MultiBeaconNode, None]:
    async with MultiBeaconNode(
        beacon_node_urls=cli_args.beacon_node_urls,
        beacon_node_urls_proposal=cli_args.beacon_node_urls_proposal,
        spec=spec,
        scheduler=scheduler,
        task_manager=task_manager,
        cli_args=cli_args,
    ) as mbn:
        yield mbn


@pytest.fixture(scope="session")
def genesis(spec: SpecElectra) -> Genesis:
    # Fake genesis 1 hour ago
    return Genesis(
        genesis_time=int(
            (
                datetime.datetime.now(tz=datetime.UTC) - datetime.timedelta(hours=1)
            ).timestamp()
        ),
        genesis_validators_root="0x9143aa7c615a7f7115e2b6aac319c03529df8242ae705fba9df39b79c59fa8b1",
        genesis_fork_version=spec.GENESIS_FORK_VERSION,
    )


@pytest.fixture
async def beacon_chain(
    spec: SpecElectra, task_manager: TaskManager, genesis: Genesis
) -> BeaconChain:
    bc = BeaconChain(spec=spec, task_manager=task_manager)
    bc.initialize(genesis=genesis)
    return bc
