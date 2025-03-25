import asyncio
import datetime
import functools
import logging
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from args import CLIArgs, log_cli_arg_values, parse_cli_args
from initialize import check_data_dir_permissions, run_services
from observability import get_service_commit, get_service_version, init_observability
from tasks import TaskManager

if TYPE_CHECKING:
    from services import ValidatorDutyService
from shutdown import shutdown_handler


async def main(cli_args: CLIArgs) -> None:
    logging.getLogger("vero-init").info(
        f"Starting vero {get_service_version()} (commit {get_service_commit()})",
    )
    check_data_dir_permissions(data_dir=Path(cli_args.data_dir))

    scheduler = AsyncIOScheduler(
        timezone=datetime.UTC,
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
    log_cli_arg_values(cli_args)
    asyncio.run(main(cli_args=cli_args))
