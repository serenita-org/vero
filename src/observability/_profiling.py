import os

import pyroscope
from opentelemetry import trace
from pydantic import HttpUrl
from pyroscope.otel import PyroscopeSpanProcessor

from observability._vero_info import get_service_name


def setup_profiling() -> None:
    pyroscope_address = os.getenv("PYROSCOPE_SERVER_ADDRESS")
    if not pyroscope_address:
        return

    pyroscope_server_address = HttpUrl(pyroscope_address)

    tags = {
        key_value_pair.split("=")[0]: key_value_pair.split("=")[1]
        for key_value_pair in os.getenv("PYROSCOPE_TAGS", "").split(",")
        if "=" in key_value_pair
    }

    pyroscope.configure(
        application_name=get_service_name(),
        server_address=str(pyroscope_server_address),
        tags=tags,
    )

    tracer_provider = trace.get_tracer_provider()

    # Register the Pyroscope span processor to enable
    # Span Profiles - more here:
    # https://grafana.com/blog/2024/02/06/combining-tracing-and-profiling-for-enhanced-observability-introducing-span-profiles/
    tracer_provider.add_span_processor(PyroscopeSpanProcessor())
