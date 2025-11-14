import asyncio
import datetime
import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs
from observability import get_service_commit, get_service_version
from spec import SpecAttestation, SpecBeaconBlock, SpecSyncCommittee
from spec.base import SpecFulu
from spec.configs import get_network_spec
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

        self.cli_args = cli_args
        self.spec = load_spec(cli_args=cli_args)

        self.shutdown_event = asyncio.Event()

        self.validator_duty_services: list[ValidatorDutyService] = []
        self.task_manager = TaskManager(shutdown_event=self.shutdown_event)

        self.scheduler = AsyncIOScheduler(
            timezone=datetime.UTC,
            job_defaults=dict(
                coalesce=True,  # default value
                max_instances=1,  # default value
                misfire_grace_time=None,  # default is 1 second
            ),
        )
        self.scheduler.start()
