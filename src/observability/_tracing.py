import os

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
)
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

from observability._vero_info import get_service_version, get_service_name


def setup_tracing() -> None:
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return None

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": get_service_name(),
                "service.version": get_service_version(),
            }
        )
    )
    processor = BatchSpanProcessor(
        OTLPSpanExporter(endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    )
    provider.add_span_processor(processor)

    # Sets the global default tracer provider
    trace.set_tracer_provider(provider)
