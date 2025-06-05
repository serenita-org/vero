import logging
from logging.handlers import QueueHandler, QueueListener
from pathlib import Path
from queue import Queue


def setup_logging(
    log_level: int,
    data_dir: Path,
) -> None:
    """
    Configure logging to use stdout and a rotating debug log file.
    Uses a background thread to handle logging without blocking the asyncio event loop.
    """
    logging.logProcesses = False
    logging.logThreads = False
    logging.logMultiprocessing = False
    if hasattr(logging, "logAsyncioTasks"):
        logging.logAsyncioTasks = False

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)-20s - %(levelname)-5s: %(message)s",
    )

    # StreamHandler - logs to stdout
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(log_level)

    # FileHandler - logs to a rotating log file at debug level
    #  This allows us to inspect debug level logs in case of issues
    debug_file_handler = logging.handlers.RotatingFileHandler(
        data_dir / "debug.log",
        maxBytes=5_000_000,
        backupCount=4,
    )
    debug_file_handler.setFormatter(formatter)
    debug_file_handler.setLevel(logging.DEBUG)

    # Use QueueHandler and QueueListener to process logs off of the main thread
    queue: Queue[logging.LogRecord] = Queue()
    root_logger.addHandler(QueueHandler(queue))
    listener = QueueListener(
        queue, stream_handler, debug_file_handler, respect_handler_level=True
    )
    listener.start()

    if log_level != logging.DEBUG:
        # apscheduler is quite verbose with default INFO logging
        logging.getLogger("apscheduler").setLevel(logging.WARNING)
