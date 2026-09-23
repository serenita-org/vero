import logging
from typing import Literal, Unpack

import aiohttp
from aiohttp import ClientResponse, ClientTimeout
from aiohttp.client import _RequestOptions
from aiohttp.hdrs import ACCEPT, CONTENT_TYPE, USER_AGENT
from opentelemetry import trace
from yarl import URL

from observability import Metrics, get_service_name, get_service_version
from observability.api_client import RequestLatency, ServiceType
from providers._headers import ContentType

_MAX_OK_RESPONSE_BYTES = 64 * 2**20  # 64 MiB
_MAX_ERROR_RESPONSE_BYTES = 1 * 2**20  # 1 MiB


def raise_for_response_size(
    response: aiohttp.ClientResponse,
    max_bytes: int,
) -> None:
    if response.content_length is not None and response.content_length > max_bytes:
        raise ValueError(
            f"Response body too large for {response.request_info.url}: "
            f"{response.content_length} bytes exceeds limit of {max_bytes} bytes",
        )


class ApiClient:
    def __init__(
        self,
        base_url: URL | str,
        service_type: ServiceType,
        timeout: ClientTimeout,
        metrics: Metrics,
    ) -> None:
        self.logger = logging.getLogger(self.__class__.__name__)
        self.tracer = trace.get_tracer(self.__class__.__name__)
        self.metrics = metrics

        self.base_url = URL(base_url)
        # netloc without the user+password part to avoid
        # exposing credentials in telemetry / unexpectedly
        self.netloc = self.base_url.host_port_subcomponent
        if not self.netloc:
            raise ValueError(f"Failed to parse netloc from {self.base_url}")

        self.client_session = aiohttp.ClientSession(
            base_url=self.base_url,
            timeout=timeout,
            headers={
                ACCEPT: ContentType.JSON.value,
                CONTENT_TYPE: ContentType.JSON.value,
                USER_AGENT: f"{get_service_name()}/{get_service_version()}",
            },
            trace_configs=[
                RequestLatency(netloc=self.netloc, service_type=service_type),
            ],
        )

    @staticmethod
    async def _read_error_text(response: aiohttp.ClientResponse) -> str:
        raise_for_response_size(response, _MAX_ERROR_RESPONSE_BYTES)
        return await response.text()

    @staticmethod
    async def _read_response_bytes(response: aiohttp.ClientResponse) -> bytes:
        raise_for_response_size(response, _MAX_OK_RESPONSE_BYTES)
        return await response.read()

    @staticmethod
    async def _raise_for_status(response: aiohttp.ClientResponse) -> None:
        if response.ok:
            return

        resp_text = await ApiClient._read_error_text(response)
        msg = f"Received status code {response.status} for request to {response.request_info.url}\nFull response text: {resp_text}"
        raise ValueError(msg)

    async def make_request(
        self,
        method: Literal["GET", "POST"],
        endpoint: str,
        formatted_endpoint_string_params: dict[str, str | int] | None = None,
        **kwargs: Unpack[_RequestOptions],
    ) -> tuple[bytes, str | None, ClientResponse]:
        """Make an HTTP request to the server.

        Args:
            method: HTTP method (GET, POST)
            endpoint: API endpoint path
            formatted_endpoint_string_params : Optional dict for endpoint formatting
            **kwargs: Additional aiohttp request options

        Returns:
            Tuple of:
                - Response body as bytes
                - Content-Type header value (or None if not present)
                - Full aiohttp ClientResponse object
        """
        if formatted_endpoint_string_params is not None:
            kwargs["trace_request_ctx"] = dict(path=endpoint)
            endpoint = endpoint.format(**formatted_endpoint_string_params)

        if "raise_for_status" not in kwargs:
            kwargs["raise_for_status"] = self._raise_for_status

        # Intentionally setting full URL here
        # for testing reasons - we need
        # the full URL available there
        url = self.base_url.join(URL(endpoint))

        self.logger.debug(f"Making {method} request to {url}")
        async with self.client_session.request(
            method=method,
            url=url,
            **kwargs,
        ) as resp:
            # The naive `resp.content_type` approach defaults to
            # a content type of `application/octet-stream` if
            # no Content-Type header is present in the response.
            # Therefore we can only check its value it
            # it is defined in the response header
            content_type = resp.headers.get(CONTENT_TYPE)
            if content_type is not None:
                # Use aiohttp's parsed value only if a value was
                # present in the Content-Type response header
                # (aiohttp confusingly returns the `application/octet-stream`
                # value even if the header was not provided):
                # https://github.com/aio-libs/aiohttp/blob/2602b711710dfe20131ec74d0753db746e56808a/aiohttp/helpers.py#L762
                content_type = resp.content_type

                if content_type not in (
                    ContentType.JSON.value,
                    ContentType.OCTET_STREAM.value,
                ):
                    raise NotImplementedError(
                        f"Content type in response unsupported: {content_type}"
                    )

            return await ApiClient._read_response_bytes(resp), content_type, resp
