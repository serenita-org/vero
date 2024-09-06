import logging
import asyncio
import signal
from pathlib import Path
from types import FrameType


from args import parse_cli_args, CLIArgs
from initialize import check_data_dir_permissions, run_services
from observability import init_observability, get_service_version, get_service_commit


def prep_datadir(data_dir: Path) -> None:
    # Write to placeholder file
    # so datadir is not empty.
    # The data dir is not necessary at the
    # moment but will be used soon for
    # another laying of slashing protection
    # and caching.
    with open(data_dir / "vero_placeholder.yml", "w") as f:
        f.write("placeholder")


async def main(cli_args: CLIArgs) -> None:
    logging.getLogger("vero-init").info(
        f"Starting vero {get_service_version()} (commit {get_service_commit()})"
    )
    check_data_dir_permissions(cli_args=cli_args)
    prep_datadir(data_dir=cli_args.data_dir)
    await run_services(cli_args=cli_args)


def sigterm_handler(signum: int, frame: FrameType | None):
    print("Received SIGTERM. Exiting.")
    exit(0)


if __name__ == "__main__":
    cli_args = parse_cli_args()
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
