import logging


def setup_logging(log_level: str) -> None:
    logging.logProcesses = False
    logging.logThreads = False
    logging.logMultiprocessing = False
    if hasattr(logging, "logAsyncioTasks"):
        logging.logAsyncioTasks = False

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s - %(name)-20s - %(levelname)-5s: %(message)s",
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root_logger.addHandler(stream_handler)
    root_logger.setLevel(log_level)
    if log_level != logging.getLevelName(logging.DEBUG):
        # apscheduler is quite verbose with default INFO logging
        logging.getLogger("apscheduler").setLevel(logging.WARNING)
