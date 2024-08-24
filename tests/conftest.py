import asyncio
import random
from collections.abc import AsyncGenerator

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pydantic import HttpUrl

from args import CLIArgs
from observability import init_observability
from providers import MultiBeaconNode, BeaconChain, RemoteSigner
from schemas.validator import ValidatorIndexPubkey, ValidatorStatus, ACTIVE_STATUSES
from services import ValidatorStatusTrackerService

# A few more global fixtures defined separately
from tests.mock_api.base import *  # noqa: F403
from tests.mock_api.beacon_node import *  # noqa: F403
from tests.mock_api.remote_signer import *  # noqa: F403


@pytest.fixture
def beacon_node_urls_proposal(request) -> list[HttpUrl]:
    return getattr(request, "param", [])


@pytest.fixture
def cli_args(
    remote_signer_url: str,
    beacon_node_url: str,
    beacon_node_urls_proposal: list[HttpUrl],
) -> CLIArgs:
    kwargs = dict(
        remote_signer_url=remote_signer_url,
        beacon_node_urls=f"{beacon_node_url}",
        fee_recipient="0x0000000000000000000000000000000000000000",
        data_dir="/tmp/vero_tests",
        use_external_builder=False,
        builder_boost_factor=90,
        graffiti="pytest",
        gas_limit=30_000_000,
        metrics_address="localhost",
        metrics_port=8000,
        log_level="INFO",
    )

    if beacon_node_urls_proposal:
        kwargs["beacon_node_urls_proposal"] = ",".join(
            str(url) for url in beacon_node_urls_proposal
        )

    return CLIArgs(**kwargs)


@pytest.fixture(autouse=True, scope="session")
def _init_observability():
    init_observability(log_level="INFO")


@pytest.fixture(scope="session")
def validators() -> list[ValidatorIndexPubkey]:
    return [
        ValidatorIndexPubkey(
            index=0,
            pubkey="0x8c87f7a01e54215ac177fb706d78e9edf762f15f34ba81103094da450f1683ced257d4270fc030a9a803aaa060edf16a",
            status=ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=1,
            pubkey="0xa728ab62714bada6b46f11dc0262c70fe4c45bb4d167fb4d709a49ec14ead5d0da7d5a57175f1c6b3a89a40f42be7439",
            status=ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=2,
            pubkey="0x832b8286f5d6535fd941c6c4ed8b9b20d214fc6aa726ce4fba1c9dbb4f278132646304f550e557231b6932aa02cf08d3",
            status=ValidatorStatus.ACTIVE_ONGOING,
        ),
        ValidatorIndexPubkey(
            index=3,
            pubkey="0xb99d27eeea8c7f9201926801acae031a9aa558428a47d403cfeda91260087dc77cb7e97f213b552c179d60be5d8dd671",
            status=ValidatorStatus.PENDING_QUEUED,
        ),
        ValidatorIndexPubkey(
            index=4,
            pubkey="0xa3ad41f12e889eb1f4e9d23247a7d8fc665f7e7bcd76e1ca61a1c54fc31fb30dd6cf12992969ab0899f0514d2f2aa852",
            status=ValidatorStatus.ACTIVE_EXITING,
        ),
    ]


@pytest.fixture(scope="session")
def random_active_validator(
    validators: list[ValidatorIndexPubkey],
) -> ValidatorIndexPubkey:
    return random.choice([v for v in validators if v.status in ACTIVE_STATUSES])


@pytest.fixture
async def remote_signer(
    cli_args: CLIArgs, mocked_remote_signer_endpoints
) -> AsyncGenerator[RemoteSigner, None]:
    async with RemoteSigner(url=cli_args.remote_signer_url) as remote_signer:
        yield remote_signer


@pytest.fixture(scope="session")
def scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.start()
    return scheduler


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
    cli_args: CLIArgs, mocked_beacon_node_endpoints, scheduler
) -> AsyncGenerator[MultiBeaconNode, None]:
    async with MultiBeaconNode(
        beacon_node_urls=cli_args.beacon_node_urls,
        beacon_node_urls_proposal=cli_args.beacon_node_urls_proposal,
        scheduler=scheduler,
    ) as mbn:
        yield mbn


@pytest.fixture
async def beacon_chain(multi_beacon_node: MultiBeaconNode) -> BeaconChain:
    beacon_chain = BeaconChain(multi_beacon_node=multi_beacon_node)
    return beacon_chain


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()
