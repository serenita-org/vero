import asyncio
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import prometheus_client
import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs, _process_attestation_consensus_threshold
from observability import init_observability
from providers import (
    BeaconChain,
    MultiBeaconNode,
    RemoteSigner,
    Keymanager,
    DB,
    SignatureProvider,
    DutyCache,
)
from schemas import SchemaBeaconAPI, SchemaKeymanagerAPI
from schemas.beacon_api import ForkVersion
from schemas.validator import ACTIVE_STATUSES, ValidatorIndexPubkey
from services import ValidatorStatusTrackerService
from spec import SpecAttestation, SpecBeaconBlock, SpecSyncCommittee
from spec.base import SpecFulu, Fork, Genesis, Version
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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator


@pytest.fixture(scope="session")
def beacon_node_urls_proposal(request: pytest.FixtureRequest) -> list[str]:
    return getattr(request, "param", [])


@pytest.fixture
def enable_keymanager_api(request: pytest.FixtureRequest) -> bool:
    # Default to false if not otherwise requested through indirect parametrization
    return getattr(request, "param", False)


@pytest.fixture
def cli_args(
    remote_signer_url: str,
    beacon_node_url: str,
    beacon_node_urls_proposal: list[str],
    enable_keymanager_api: bool,
    tmp_path: Path,
) -> CLIArgs:
    return CLIArgs(
        network=Network._TESTS,
        network_custom_config_path=None,
        remote_signer_url=None if enable_keymanager_api else remote_signer_url,
        beacon_node_urls=[beacon_node_url],
        beacon_node_urls_proposal=beacon_node_urls_proposal,
        attestation_consensus_threshold=_process_attestation_consensus_threshold(
            None, [beacon_node_url]
        ),
        fee_recipient="0xfee0000000000000000000000000000000000000",
        data_dir=str(tmp_path),
        graffiti=b"graffiti-in-pytest",
        gas_limit=30_000_000,
        use_external_builder=False,
        builder_boost_factor=90,
        enable_doppelganger_detection=False,
        enable_keymanager_api=enable_keymanager_api,
        keymanager_api_token_file_path=tmp_path / "keymanager-api-token.txt",
        keymanager_api_address="localhost",
        keymanager_api_port=8001,
        metrics_address="localhost",
        metrics_port=8000,
        log_level=logging.INFO,
        disable_slashing_detection=False,
    )


@pytest.fixture(autouse=True, scope="session")
def _init_observability() -> None:
    init_observability(
        metrics_address="localhost",
        metrics_port=8080,
        log_level=logging.DEBUG,
        data_dir=Path("/tmp"),
    )


@pytest.fixture(scope="session")
def spec() -> SpecFulu:
    return get_network_spec(network=Network._TESTS)


@pytest.fixture(autouse=True, scope="session")
def _init_spec(spec: SpecFulu) -> None:
    SpecAttestation.initialize(spec=spec)
    SpecBeaconBlock.initialize(spec=spec)
    SpecSyncCommittee.initialize(spec=spec)


@pytest.fixture
def fork_version(
    request: pytest.FixtureRequest, beacon_chain: BeaconChain
) -> Generator[None]:
    requested_fork_version = getattr(request, "param", ForkVersion.FULU)

    with mock.patch.object(
        beacon_chain, "current_fork_version", requested_fork_version
    ):
        yield


@pytest.fixture(scope="session")
def validators() -> list[ValidatorIndexPubkey]:
    return [
        ValidatorIndexPubkey(
            index=0,
            pubkey="0x96bfa404bc76604bd7dfa6e3ea278fd485c9ed2bfdc327fc4c4b30558d5d9f52b5bdfe655f6d7268575e36f83aae12bf",
            status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=1,
            pubkey="0x9268da601a7bd2bfd2360b2a7d5454c81162f4c45e9064bbc924053fbabb469a5575a2c94706789aa67f3a537486a584",
            status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=2,
            pubkey="0xb8e2957d19485687399c6f494362c7dba493af0a14f9a12f42e4162cb8863680b215140f664f391df9bba9a94e7d21f6",
            status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=3,
            pubkey="0xa726a29d893ed05045fdb1b6f67e9b9ed3e2aca6799b5398877b89f499aa2348d6d7958af5578e86102dc2faad1da6af",
            status=SchemaBeaconAPI.ValidatorStatus.PENDING_QUEUED,
        ),
        ValidatorIndexPubkey(
            index=4,
            pubkey="0xb30b39cb658f0ee7de717cd29d99dec29d9cc335d7ffc7cc9c6ceff24d2eab60a12ad0ce6cabf6ee981184f869cede1f",
            status=SchemaBeaconAPI.ValidatorStatus.ACTIVE_EXITING,
        ),
    ]


@pytest.fixture(scope="session")
def random_active_validator(
    validators: list[ValidatorIndexPubkey],
) -> ValidatorIndexPubkey:
    return random.choice([v for v in validators if v.status in ACTIVE_STATUSES])


@pytest.fixture
async def scheduler() -> AsyncGenerator[AsyncIOScheduler]:
    _scheduler = AsyncIOScheduler(event_loop=asyncio.get_running_loop())
    _scheduler.start()
    yield _scheduler
    _scheduler.shutdown(wait=False)


@pytest.fixture
def shutdown_event() -> asyncio.Event:
    return asyncio.Event()


@pytest.fixture
async def task_manager(
    shutdown_event: asyncio.Event,
) -> AsyncGenerator[TaskManager]:
    t = TaskManager(shutdown_event=shutdown_event)
    yield t
    t.cancel_all()


@pytest.fixture
def empty_db(tmp_path: Path) -> Generator[DB]:
    with DB(data_dir=str(tmp_path)) as db:
        db.run_migrations()
        yield db


@pytest.fixture(scope="session")
def thread_pool_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor()


@pytest.fixture
async def keymanager(
    empty_db: DB,
    beacon_chain: BeaconChain,
    cli_args: CLIArgs,
    multi_beacon_node: MultiBeaconNode,
    remote_signer_url: str,
    thread_pool_executor: ThreadPoolExecutor,
    validators: list[ValidatorIndexPubkey],
    _mocked_remote_signer_endpoints: None,
) -> AsyncGenerator[Keymanager]:
    async with Keymanager(
        db=empty_db,
        beacon_chain=beacon_chain,
        multi_beacon_node=multi_beacon_node,
        cli_args=cli_args,
        thread_pool_executor=thread_pool_executor,
    ) as keymanager:
        yield keymanager


@pytest.fixture
def duty_cache(cli_args: CLIArgs) -> DutyCache:
    return DutyCache(data_dir=cli_args.data_dir)


@pytest.fixture
async def signature_provider(
    enable_keymanager_api: bool,
    cli_args: CLIArgs,
    keymanager: Keymanager,
    remote_signer_url: str,
    thread_pool_executor: ThreadPoolExecutor,
    validators: list[ValidatorIndexPubkey],
) -> AsyncGenerator[SignatureProvider]:
    if enable_keymanager_api:
        # import the default fixture validators into the Keymanager provider
        await keymanager.import_remote_keys(
            remote_keys=[
                SchemaKeymanagerAPI.RemoteKey(pubkey=v.pubkey, url=remote_signer_url)
                for v in validators
            ],
        )
        yield keymanager
    else:
        if cli_args.remote_signer_url is None:
            raise RuntimeError(
                "remote_signer_url is None despite disabled Keymanager API"
            )
        async with RemoteSigner(
            url=cli_args.remote_signer_url, thread_pool_executor=thread_pool_executor
        ) as remote_signer:
            yield remote_signer


@pytest.fixture
async def validator_status_tracker(
    multi_beacon_node: MultiBeaconNode,
    beacon_chain: BeaconChain,
    signature_provider: SignatureProvider,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
) -> ValidatorStatusTrackerService:
    validator_status_tracker = ValidatorStatusTrackerService(
        multi_beacon_node=multi_beacon_node,
        beacon_chain=beacon_chain,
        signature_provider=signature_provider,
        scheduler=scheduler,
        task_manager=task_manager,
    )
    await validator_status_tracker.initialize()
    return validator_status_tracker


@pytest.fixture
async def multi_beacon_node(
    cli_args: CLIArgs,
    _mocked_beacon_node_endpoints: None,
    spec: SpecFulu,
    scheduler: AsyncIOScheduler,
    task_manager: TaskManager,
    beacon_chain: BeaconChain,
) -> AsyncGenerator[MultiBeaconNode]:
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
def genesis(spec: SpecFulu) -> Genesis:
    # Fake genesis 1 hour ago
    return Genesis(
        genesis_time=int(time.time() - 3600),
        genesis_validators_root="0x9143aa7c615a7f7115e2b6aac319c03529df8242ae705fba9df39b79c59fa8b1",
        genesis_fork_version=spec.GENESIS_FORK_VERSION,
    )


@pytest.fixture
def beacon_chain(
    spec: SpecFulu, genesis: Genesis, task_manager: TaskManager
) -> BeaconChain:
    return BeaconChain(spec=spec, genesis=genesis, task_manager=task_manager)


@pytest.fixture
def _unregister_prometheus_metrics() -> Generator[None]:
    """
    Clears the prometheus registry metrics after a test is done running.
    """
    yield
    collectors = tuple(prometheus_client.REGISTRY._collector_to_names.keys())
    for collector in collectors:
        prometheus_client.REGISTRY.unregister(collector)
