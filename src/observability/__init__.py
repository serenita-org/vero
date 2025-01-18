from ._logging import setup_logging
from ._metrics import setup_metrics
from ._metrics_shared import ErrorType, get_shared_metrics
from ._profiling import setup_profiling
from ._tracing import setup_tracing
from ._vero_info import get_service_commit, get_service_name, get_service_version


def init_observability(
    metrics_address: str,
    metrics_port: int,
    metrics_multiprocess_mode: bool,
    log_level: str,
) -> None:
    setup_logging(log_level=log_level)
    setup_metrics(
        addr=metrics_address,
        port=metrics_port,
        multiprocess_mode=metrics_multiprocess_mode,
    )
    setup_tracing()
    setup_profiling()


__all__ = [
    "ErrorType",
    "get_service_commit",
    "get_service_name",
    "get_service_version",
    "get_shared_metrics",
    "init_observability",
]
