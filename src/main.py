import asyncio
import logging
import signal
import sys
from pathlib import Path
from types import FrameType

from args import CLIArgs, parse_cli_args
from initialize import check_data_dir_permissions, run_services
from observability import get_service_commit, get_service_version, init_observability


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
    await run_services(cli_args=cli_args)


def sigterm_handler(_signum: int, _frame: FrameType | None) -> None:
    logging.getLogger().info("Received SIGTERM. Exiting.")
    sys.exit(0)


if __name__ == "__main__":
    cli_args = parse_cli_args(args=sys.argv[1:])
    init_observability(
        metrics_address=cli_args.metrics_address,
        metrics_port=cli_args.metrics_port,
        metrics_multiprocess_mode=cli_args.metrics_multiprocess_mode,
        log_level=cli_args.log_level,
    )

    signal.signal(signal.SIGTERM, sigterm_handler)

    # Execution will block here until Ctrl+C (Ctrl+Break on Windows) is pressed.
    try:
        asyncio.run(main(cli_args=cli_args))
    except (KeyboardInterrupt, SystemExit):
        logger = logging.getLogger("vero-shutdown")
        logger.info("Shutting down...")
