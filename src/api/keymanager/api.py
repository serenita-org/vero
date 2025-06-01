import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from args import CLIArgs

from .fee_recipient_endpoints import routes as fee_recipient_routes
from .gas_limit_endpoints import routes as gas_limit_routes
from .graffiti_endpoints import routes as graffiti_routes
from .middlewares import bearer_authentication, exception_handler
from .remote_key_manager_endpoints import routes as remote_key_manager_routes
from .voluntary_exit_endpoints import routes as voluntary_exit_routes

if TYPE_CHECKING:
    from providers import Keymanager


def _get_bearer_token_value(cli_args: CLIArgs) -> str:
    # Check if the filepath exists - if it does, read the token value from it
    fp = cli_args.keymanager_api_token_file_path
    if fp.exists():
        with Path.open(fp) as f:
            return f.read().strip()

    # If it doesn't, generate a value and store it in the file.
    bearer_token_value = os.urandom(32).hex()[2:]
    with Path.open(fp, "w") as f:
        f.write(bearer_token_value)

    return bearer_token_value


def _create_app(keymanager: "Keymanager", cli_args: CLIArgs) -> web.Application:
    app = web.Application(middlewares=[exception_handler, bearer_authentication])

    app["bearer_token"] = _get_bearer_token_value(cli_args=cli_args)
    app["keymanager"] = keymanager

    app.add_routes(fee_recipient_routes)
    app.add_routes(gas_limit_routes)
    app.add_routes(graffiti_routes)
    app.add_routes(remote_key_manager_routes)
    app.add_routes(voluntary_exit_routes)

    return app


async def start_server(keymanager: "Keymanager", cli_args: CLIArgs) -> None:
    app = _create_app(keymanager=keymanager, cli_args=cli_args)
    logger = logging.getLogger("api.keymanager.api")
    try:
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(
            runner,
            host=cli_args.keymanager_api_address,
            port=cli_args.keymanager_api_port,
        )
        logger.info(
            f"Starting Keymanager API on {cli_args.keymanager_api_address}:{cli_args.keymanager_api_port}"
        )
        await site.start()

        # run forever by 1 hour intervals,
        while True:  # noqa: ASYNC110
            await asyncio.sleep(3600)

    except asyncio.CancelledError:
        logger.debug("Shutting down")
        await app.shutdown()
        await app.cleanup()

    except Exception as e:
        logger.error(
            f"Unexpected error occurred - exiting... {e!r}",
            exc_info=logger.isEnabledFor(logging.DEBUG),
        )
        sys.exit(1)
