import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
)

from observability._vero_info import get_service_name, get_service_version


def setup_tracing() -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        return

    logging.getLogger("vero-init").info(
        f"Enabling tracing, exporting data to {endpoint}"
    )

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": get_service_name(),
                "service.version": get_service_version(),
            },
        ),
    )
    processor = BatchSpanProcessor(
        OTLPSpanExporter(endpoint=endpoint),
    )
    provider.add_span_processor(processor)

    # Sets the global default tracer provider
    trace.set_tracer_provider(provider)
