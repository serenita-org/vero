import logging
from collections.abc import Awaitable, Callable

import msgspec
from aiohttp import hdrs, web

from providers.keymanager import PubkeyNotFound
from schemas.keymanager_api import ErrorResponse


@web.middleware
async def bearer_authentication(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    auth_header_value = request.headers.get(hdrs.AUTHORIZATION)
    if not auth_header_value:
        return web.json_response(
            status=401,
            body=msgspec.json.encode(
                ErrorResponse(message="No value provided for Authorization header")
            ),
        )

    if auth_header_value != f"Bearer {request.app['bearer_token']}":
        return web.json_response(
            status=403,
            body=msgspec.json.encode(
                ErrorResponse(message="Invalid value provided for Authorization header")
            ),
        )

    return await handler(request)


@web.middleware
async def exception_handler(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """
    Transforms any exception the app may raise into a JSON response
    to comply with the Keymanager API specification.
    """
    try:
        return await handler(request)
    except web.HTTPException:
        raise
    except msgspec.ValidationError as e:
        status_code = 400
        msg = repr(e)
    except PubkeyNotFound as e:
        status_code = 500
        msg = repr(e)
    except Exception as e:
        status_code = 500
        msg = repr(e)
        logger = logging.getLogger("api.keymanager.middlewares.exception_handler")
        logger.error(
            f"Exception occurred while handling request to {request.url}: {msg}",
            exc_info=logger.isEnabledFor(logging.DEBUG),
        )

    return web.json_response(
        status=status_code, body=msgspec.json.encode(ErrorResponse(message=msg))
    )
