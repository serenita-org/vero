"""
Helper that provides observability into API requests - request count and duration.
"""

import asyncio
import logging
from enum import Enum
from types import SimpleNamespace

import aiohttp
from prometheus_client import Counter, Histogram

_REQUEST_DURATION = Histogram(
    "request_duration_seconds",
    "Request duration in seconds",
    labelnames=["service_type", "host", "method", "path", "status", "request_type"],
)
_REQUESTS_COUNTER = Counter(
    "requests",
    "Number of requests",
    labelnames=["service_type", "host", "method", "path", "status", "request_type"],
)

_logger = logging.getLogger(__name__)


async def _on_request_start(
    session: aiohttp.ClientSession,
    trace_config_ctx: SimpleNamespace,
    params: aiohttp.TraceRequestStartParams,
):
    trace_config_ctx.start = asyncio.get_event_loop().time()


async def _on_request_end(
    session: aiohttp.ClientSession,
    trace_config_ctx: SimpleNamespace,
    params: aiohttp.TraceRequestEndParams,
):
    # Allow overrides of the path used in the metric through
    # the trace_request_ctx. This is to avoid unique label values for
    # dynamic routes, e.g. "/eth/v1/validator/duties/proposer/123"
    try:
        path = trace_config_ctx.trace_request_ctx.path
    except AttributeError:
        path = params.url.path

    _labels = dict(
        service_type=trace_config_ctx.service_type,
        host=trace_config_ctx.host,
        method=params.method,
        path=path,
        status=params.response.status,
        request_type=getattr(trace_config_ctx.trace_request_ctx, "request_type", None),
    )

    elapsed = asyncio.get_event_loop().time() - trace_config_ctx.start
    _REQUEST_DURATION.labels(**_labels).observe(elapsed)
    _REQUESTS_COUNTER.labels(**_labels).inc()


class ServiceType(Enum):
    BEACON_NODE = "beacon_node"
    REMOTE_SIGNER = "remote_signer"


class RequestLatency(aiohttp.TraceConfig):
    def _trace_config_ctx_factory(
        self, trace_request_ctx: SimpleNamespace | None
    ) -> SimpleNamespace:
        return SimpleNamespace(
            host=self.host,
            service_type=self.service_type.value,
            trace_request_ctx=trace_request_ctx,
        )

    def __init__(self, host: str, service_type: ServiceType):
        super().__init__(trace_config_ctx_factory=self._trace_config_ctx_factory)

        self.host = host
        self.service_type = service_type

        self.on_request_start.append(_on_request_start)
        self.on_request_end.append(_on_request_end)
