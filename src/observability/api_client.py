"""Helper that provides observability into API requests - request count and duration."""

import asyncio
import logging
from enum import Enum
from functools import partial
from types import SimpleNamespace
from typing import TypedDict, get_type_hints

import aiohttp
from prometheus_client import Counter, Histogram


class _RequestMetricLabelValues(TypedDict):
    service_type: str
    host: str
    method: str
    path: str
    status: str
    request_type: str


_REQUEST_DURATION = Histogram(
    "request_duration_seconds",
    "Request duration in seconds",
    labelnames=list(get_type_hints(_RequestMetricLabelValues).keys()),
)
_REQUESTS_COUNTER = Counter(
    "requests",
    "Number of requests",
    labelnames=list(get_type_hints(_RequestMetricLabelValues).keys()),
)
_TRANSMIT_BYTES = Counter(
    "transmit_bytes",
    "Total bytes transmitted",
    labelnames=["service_type", "host"],
)
_RECEIVE_BYTES = Counter(
    "receive_bytes",
    "Total bytes received",
    labelnames=["service_type", "host"],
)

_logger = logging.getLogger(__name__)


async def _on_request_start(
    _session: aiohttp.ClientSession,
    trace_config_ctx: SimpleNamespace,
    _params: aiohttp.TraceRequestStartParams,
) -> None:
    trace_config_ctx.start = asyncio.get_running_loop().time()


async def _on_request_chunk_sent(
    _session: aiohttp.ClientSession,
    trace_config_ctx: SimpleNamespace,
    params: aiohttp.TraceRequestChunkSentParams,
) -> None:
    _TRANSMIT_BYTES.labels(
        service_type=trace_config_ctx.service_type,
        host=trace_config_ctx.host,
    ).inc(len(params.chunk))


async def _on_response_chunk_received(
    _session: aiohttp.ClientSession,
    trace_config_ctx: SimpleNamespace,
    params: aiohttp.TraceResponseChunkReceivedParams,
) -> None:
    _RECEIVE_BYTES.labels(
        service_type=trace_config_ctx.service_type,
        host=trace_config_ctx.host,
    ).inc(len(params.chunk))


async def _on_request_end(
    _session: aiohttp.ClientSession,
    trace_config_ctx: SimpleNamespace,
    params: aiohttp.TraceRequestEndParams,
) -> None:
    path = params.url.path
    request_type = None

    # Allow overrides of the path used in the metric through
    # the trace_request_ctx. This is to avoid unique label values for
    # dynamic routes, e.g. "/eth/v1/validator/duties/proposer/123"
    if (
        hasattr(trace_config_ctx, "trace_request_ctx")
        and trace_config_ctx.trace_request_ctx is not None
    ):
        trace_request_ctx_dict: dict[str, str] = trace_config_ctx.trace_request_ctx
        if trace_request_ctx_dict is not None:
            path = trace_request_ctx_dict.get("path", path)
            request_type = trace_request_ctx_dict.get("request_type", request_type)

    _labels = _RequestMetricLabelValues(
        service_type=trace_config_ctx.service_type,
        host=trace_config_ctx.host,
        method=params.method,
        path=path,
        status=str(params.response.status),
        request_type=str(request_type),
    )

    elapsed = asyncio.get_running_loop().time() - trace_config_ctx.start
    _REQUEST_DURATION.labels(**_labels).observe(elapsed)
    _REQUESTS_COUNTER.labels(**_labels).inc()


class ServiceType(Enum):
    BEACON_NODE = "beacon_node"
    REMOTE_SIGNER = "remote_signer"


class RequestLatency(aiohttp.TraceConfig):
    def __init__(self, host: str, service_type: ServiceType):
        super().__init__(
            # While not correct from a typing point of view,
            # this is the most elegant way I found to inject
            # static data into the tracing context.
            trace_config_ctx_factory=partial(  # type: ignore[arg-type]
                lambda trace_request_ctx: SimpleNamespace(
                    trace_request_ctx=trace_request_ctx,
                    host=host,
                    service_type=service_type.value,
                ),
            ),
        )

        self.on_request_start.append(_on_request_start)
        self.on_request_end.append(_on_request_end)
        self.on_request_chunk_sent.append(_on_request_chunk_sent)
        self.on_response_chunk_received.append(_on_response_chunk_received)
