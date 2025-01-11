import random
from asyncio import AbstractEventLoop
from collections.abc import AsyncGenerator

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs, _process_attestation_consensus_threshold
from observability import init_observability
from providers import BeaconChain, MultiBeaconNode, RemoteSigner
from schemas import SchemaBeaconAPI
from schemas.validator import ACTIVE_STATUSES, ValidatorIndexPubkey
from services import ValidatorStatusTrackerService
from spec.configs import Network
from tasks import TaskManager

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
def validators() -> list[ValidatorIndexPubkey]:
    return [
        ValidatorIndexPubkey(
            index=0,
            pubkey="0x8c87f7a01e54215ac177fb706d78e9edf762f15f34ba81103094da450f1683ced257d4270fc030a9a803aaa060edf16a",
            status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=1,
            pubkey="0xa728ab62714bada6b46f11dc0262c70fe4c45bb4d167fb4d709a49ec14ead5d0da7d5a57175f1c6b3a89a40f42be7439",
            status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=2,
            pubkey="0x832b8286f5d6535fd941c6c4ed8b9b20d214fc6aa726ce4fba1c9dbb4f278132646304f550e557231b6932aa02cf08d3",
            status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=3,
            pubkey="0xb99d27eeea8c7f9201926801acae031a9aa558428a47d403cfeda91260087dc77cb7e97f213b552c179d60be5d8dd671",
            status=SchemaBeaconAPI.ValidatorStatus.PENDING_QUEUED,
        ),
        ValidatorIndexPubkey(
            index=4,
            pubkey="0xa3ad41f12e889eb1f4e9d23247a7d8fc665f7e7bcd76e1ca61a1c54fc31fb30dd6cf12992969ab0899f0514d2f2aa852",
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
    return TaskManager()


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
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
) -> AsyncGenerator[MultiBeaconNode, None]:
    async with MultiBeaconNode(
        beacon_node_urls=cli_args.beacon_node_urls,
        beacon_node_urls_proposal=cli_args.beacon_node_urls_proposal,
        scheduler=scheduler,
        task_manager=task_manager,
        cli_args=cli_args,
    ) as mbn:
        yield mbn


@pytest.fixture
async def beacon_chain(
    multi_beacon_node: MultiBeaconNode, task_manager: TaskManager
) -> BeaconChain:
    return BeaconChain(multi_beacon_node=multi_beacon_node, task_manager=task_manager)
