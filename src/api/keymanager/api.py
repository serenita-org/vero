import asyncio
import logging
import os
import stat
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from args import CLIArgs

from .fee_recipient_endpoints import routes as fee_recipient_routes
from .gas_limit_endpoints import routes as gas_limit_routes
from .graffiti_endpoints import routes as graffiti_routes
from .middlewares import bearer_authentication, exception_handler, path_param_validation
from .remote_key_manager_endpoints import routes as remote_key_manager_routes
from .voluntary_exit_endpoints import routes as voluntary_exit_routes

if TYPE_CHECKING:
    from providers import Keymanager


def _ensure_bearer_token_file_permissions(fp: Path) -> None:
    permissions = stat.S_IMODE(fp.stat().st_mode)
    if permissions != 0o600:
        raise PermissionError(
            f"Bearer token file {fp} must have permissions set to 0o600",
        )


def _read_bearer_token_value(fp: Path) -> str:
    _ensure_bearer_token_file_permissions(fp)
    with Path.open(fp) as f:
        return f.read().strip()


def _write_bearer_token_value(fp: Path, value: str) -> None:
    fd = os.open(
        fp,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
    )
    with os.fdopen(fd, "w") as f:
        f.write(value)

    fp.chmod(0o600)


def _get_bearer_token_value(cli_args: CLIArgs) -> str:
    fp = cli_args.keymanager_api_token_file_path
    try:
        return _read_bearer_token_value(fp)
    except FileNotFoundError:
        # If it doesn't exist, generate a value and store it in the file.
        bearer_token_value = os.urandom(32).hex()
        _write_bearer_token_value(fp=fp, value=bearer_token_value)

    return bearer_token_value


def _create_app(keymanager: "Keymanager", cli_args: CLIArgs) -> web.Application:
    app = web.Application(
        middlewares=[exception_handler, path_param_validation, bearer_authentication]
    )

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
        logger.exception(
            f"Unexpected error occurred - exiting... {e!r}",
        )
        sys.exit(1)
