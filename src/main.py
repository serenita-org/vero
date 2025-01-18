import asyncio
import functools
import logging
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs, parse_cli_args
from initialize import check_data_dir_permissions, run_services
from observability import get_service_commit, get_service_version, init_observability
from tasks import TaskManager

if TYPE_CHECKING:
    from services import ValidatorDutyService
from shutdown import shutdown_handler


def prep_datadir(data_dir: Path) -> None:
    # Write to placeholder file
    # so datadir is not empty.
    # The data dir is not necessary at the
    # moment but will be used soon for
    # another laying of slashing protection
    # and caching.
    with Path.open(data_dir / "vero_placeholder.yml", "w") as f:
        f.write("placeholder")


async def main(cli_args: CLIArgs) -> None:
    logging.getLogger("vero-init").info(
        f"Starting vero {get_service_version()} (commit {get_service_commit()})",
    )
    check_data_dir_permissions(data_dir=Path(cli_args.data_dir))
    prep_datadir(data_dir=Path(cli_args.data_dir))

    scheduler = AsyncIOScheduler(
        timezone=pytz.UTC,
        job_defaults=dict(
            coalesce=True,  # default value
            max_instances=1,  # default value
            misfire_grace_time=None,  # default is 1 second
        ),
    )
    scheduler.start()

    validator_duty_services: list[ValidatorDutyService] = []

    shutdown_event = asyncio.Event()
    task_manager = TaskManager(shutdown_event=shutdown_event)

    loop = asyncio.get_running_loop()
    signals = (signal.SIGINT, signal.SIGTERM)
    for s in signals:
        loop.add_signal_handler(
            s,
            functools.partial(
                shutdown_handler,
                s,
                validator_duty_services,
                shutdown_event,
                task_manager,
            ),
        )

    await run_services(
        cli_args=cli_args,
        task_manager=task_manager,
        scheduler=scheduler,
        validator_duty_services=validator_duty_services,
        shutdown_event=shutdown_event,
    )


if __name__ == "__main__":
    cli_args = parse_cli_args(args=sys.argv[1:])
    init_observability(
        metrics_address=cli_args.metrics_address,
        metrics_port=cli_args.metrics_port,
        metrics_multiprocess_mode=cli_args.metrics_multiprocess_mode,
        log_level=cli_args.log_level,
    )
    asyncio.run(main(cli_args=cli_args))
