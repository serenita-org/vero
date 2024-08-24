from prometheus_client import Gauge

from ._logging import setup_logging
from ._metrics_shared import get_shared_metrics, ERROR_TYPE
from ._profiling import setup_profiling
from ._tracing import setup_tracing
from ._vero_info import get_service_commit, get_service_name, get_service_version

VERO_INFO = Gauge(
    "vero_info", "Information about the Vero build.", labelnames=["commit", "version"]
)


def init_observability(
    log_level: str,
):
    VERO_INFO.labels(
        commit=get_service_commit(),
        version=get_service_version(),
    ).set(1)

    setup_logging(log_level=log_level)
    setup_tracing()
    setup_profiling()


__all__ = [
    "init_observability",
    "get_shared_metrics",
    "get_service_name",
    "get_service_version",
    "ERROR_TYPE",
]
