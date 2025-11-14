import asyncio
import functools
import signal
import sys
from pathlib import Path

from args import log_cli_arg_values, parse_cli_args
from initialize import check_data_dir_permissions, run_services
from observability import init_observability
from providers import Vero
from shutdown import shutdown_handler


async def main(vero: Vero) -> None:
    loop = asyncio.get_running_loop()
    signals = (signal.SIGINT, signal.SIGTERM)
    for s in signals:
        loop.add_signal_handler(
            s,
            functools.partial(
                shutdown_handler,
                s,
                vero,
            ),
        )

    await run_services(vero=vero)


if __name__ == "__main__":
    cli_args = parse_cli_args(args=sys.argv[1:])
    check_data_dir_permissions(data_dir=Path(cli_args.data_dir))
    init_observability(
        metrics_address=cli_args.metrics_address,
        metrics_port=cli_args.metrics_port,
        metrics_multiprocess_mode=cli_args.metrics_multiprocess_mode,
        log_level=cli_args.log_level,
        data_dir=Path(cli_args.data_dir),
    )
    log_cli_arg_values(cli_args)
    asyncio.run(main(vero=Vero(cli_args=cli_args)))
