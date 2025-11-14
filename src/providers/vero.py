import asyncio
import datetime
import logging
from typing import TYPE_CHECKING

import aiohttp
from aiohttp import ClientTimeout
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs
from observability import Metrics, get_service_commit, get_service_version
from providers import BeaconChain
from spec import SpecAttestation, SpecBeaconBlock, SpecSyncCommittee
from spec.base import Genesis, SpecFulu
from spec.configs import Network, get_genesis_for_network, get_network_spec
from tasks import TaskManager

if TYPE_CHECKING:
    from services import ValidatorDutyService


def load_spec(cli_args: CLIArgs) -> SpecFulu:
    spec = get_network_spec(
        network=cli_args.network,
        network_custom_config_path=cli_args.network_custom_config_path,
    )
    # Generate some of the SSZ classes dynamically
    SpecAttestation.initialize(spec=spec)
    SpecBeaconBlock.initialize(spec=spec)
    SpecSyncCommittee.initialize(spec=spec)

    return spec


class Vero:
    def __init__(self, cli_args: CLIArgs) -> None:
        logging.getLogger("vero-init").info(
            f"Starting vero {get_service_version()} (commit {get_service_commit()})",
        )
        self.shutdown_event = asyncio.Event()
        self.scheduler = AsyncIOScheduler(
            timezone=datetime.UTC,
            job_defaults=dict(
                coalesce=True,  # default value
                max_instances=1,  # default value
                misfire_grace_time=None,  # default is 1 second
            ),
        )

        self.cli_args = cli_args
        self.spec = load_spec(cli_args=cli_args)
        if cli_args.network == Network.CUSTOM:
            # get genesis from beacon node on-demand
            genesis = asyncio.run(self._get_genesis_for_custom_network())
        else:
            genesis = get_genesis_for_network(network=self.cli_args.network)

        self.metrics = Metrics(
            spec=self.spec,
            addr=cli_args.metrics_address,
            port=cli_args.metrics_port,
            multiprocess_mode=cli_args.metrics_multiprocess_mode,
        )

        self.task_manager = TaskManager(
            shutdown_event=self.shutdown_event, metrics=self.metrics
        )
        self.beacon_chain = BeaconChain(
            spec=self.spec,
            genesis=genesis,
            task_manager=self.task_manager,
        )

        self.validator_duty_services: list[ValidatorDutyService] = []

    async def _get_genesis_for_custom_network(self) -> Genesis:
        # For custom networks, Vero retrieves genesis data
        # on-demand from the first configured beacon node
        logger = logging.getLogger("vero-init")
        bn_url = self.cli_args.beacon_node_urls[0]
        logger.debug(f"Getting genesis for custom network from {bn_url}")
        try:
            async with (
                aiohttp.ClientSession(
                    base_url=bn_url,
                ) as session,
                session.get(
                    "/eth/v1/beacon/genesis",
                    timeout=ClientTimeout(total=10.0),
                    raise_for_status=True,
                ) as resp,
            ):
                return Genesis.from_obj((await resp.json())["data"])  # type: ignore[no-any-return]
        except Exception as e:
            logger.exception(f"Failed to fetch genesis for custom network: {e!r}")
            raise
