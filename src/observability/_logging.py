import logging
from logging.handlers import QueueHandler, QueueListener
from queue import Queue
from types import TracebackType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

type _SysExcInfoType = (
    tuple[type[BaseException], BaseException, TracebackType | None]
    | tuple[None, None, None]
)


class ConditionalExcInfoFormatter(logging.Formatter):
    def __init__(self, fmt: str, include_exc_info: bool) -> None:
        super().__init__(fmt)
        self.include_exc_info = include_exc_info

    def formatException(self, ei: _SysExcInfoType) -> str:  # noqa: N802
        # Suppresses verbose exception logging output
        # unless include_exc_info is True.
        if not self.include_exc_info:
            return ""
        return super().formatException(ei)


def setup_logging(
    log_level: int,
    data_dir: Path,
) -> None:
    """
    Configure logging to use stdout and a rotating debug log file.
    Uses a background thread to handle logging to file without blocking
    the asyncio event loop.
    """
    logging.logProcesses = False
    logging.logThreads = False
    if hasattr(logging, "logAsyncioTasks"):
        logging.logAsyncioTasks = False

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()
    log_format = "%(asctime)s - %(name)-20s - %(levelname)-5s: %(message)s"

    # StreamHandler - logs to stdout on the main thread.
    # (Not using the QueueHandler for this one because it doesn't allow for conditional
    # exception logging)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(
        ConditionalExcInfoFormatter(
            log_format, include_exc_info=log_level <= logging.DEBUG
        )
    )
    stream_handler.setLevel(log_level)
    root_logger.addHandler(stream_handler)

    # FileHandler - logs to a rotating log file at debug level
    #  This allows us to inspect debug level logs in case of issues
    debug_file_handler = logging.handlers.RotatingFileHandler(
        data_dir / "debug.log",
        maxBytes=5_000_000,
        backupCount=4,
    )
    debug_file_handler.setLevel(logging.DEBUG)

    # Use QueueHandler and QueueListener to process logs off of the main thread
    queue: Queue[logging.LogRecord] = Queue()
    queue_handler = QueueHandler(queue)
    queue_handler.setFormatter(logging.Formatter(log_format))
    root_logger.addHandler(queue_handler)
    listener = QueueListener(queue, debug_file_handler)
    listener.start()

    if log_level != logging.DEBUG:
        # apscheduler is quite verbose with default INFO logging
        logging.getLogger("apscheduler").setLevel(logging.WARNING)
