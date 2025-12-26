from typing import TYPE_CHECKING

from ._logging import setup_logging
from ._metrics import ErrorType, Metrics
from ._profiling import setup_profiling

# from ._tracing import setup_tracing
from ._vero_info import get_service_commit, get_service_name, get_service_version

if TYPE_CHECKING:
    from pathlib import Path


def init_observability(
    log_level: int,
    data_dir: Path,
) -> None:
    setup_logging(
        log_level=log_level,
        data_dir=data_dir,
    )
    # TODO re-enable once grpc adds support for free-threading
    #    setup_tracing()
    setup_profiling()


__all__ = [
    "ErrorType",
    "Metrics",
    "get_service_commit",
    "get_service_name",
    "get_service_version",
    "init_observability",
]
