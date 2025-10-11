from typing import TYPE_CHECKING

from ._logging import setup_logging
from ._metrics import setup_metrics
from ._metrics_shared import ERRORS_METRIC, ErrorType
from ._profiling import setup_profiling
from ._tracing import setup_tracing
from ._vero_info import get_service_commit, get_service_name, get_service_version

if TYPE_CHECKING:
    from pathlib import Path


def init_observability(
    metrics_address: str,
    metrics_port: int,
    metrics_multiprocess_mode: bool,
    log_level: int,
    data_dir: Path,
) -> None:
    setup_logging(
        log_level=log_level,
        data_dir=data_dir,
    )
    setup_metrics(
        addr=metrics_address,
        port=metrics_port,
        multiprocess_mode=metrics_multiprocess_mode,
    )
    setup_tracing()
    setup_profiling()


__all__ = [
    "ERRORS_METRIC",
    "ErrorType",
    "get_service_commit",
    "get_service_name",
    "get_service_version",
    "init_observability",
]
