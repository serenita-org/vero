import os
from pathlib import Path

from prometheus_client import REGISTRY, multiprocess, start_http_server


def setup_metrics(addr: str, port: int, multiprocess_mode: bool = False) -> None:
    if multiprocess_mode:
        # Wipe files in multiprocessing dir from previous run
        #  See https://prometheus.github.io/client_python/multiprocess/
        _multiprocessing_data_dir = os.getenv("PROMETHEUS_MULTIPROC_DIR")
        if _multiprocessing_data_dir is None:
            raise ValueError("PROMETHEUS_MULTIPROC_DIR environment variable is not set")

        _multiprocessing_data_path = Path(_multiprocessing_data_dir)
        if not _multiprocessing_data_path.is_dir():
            raise ValueError(
                f"PROMETHEUS_MULTIPROC_DIR {_multiprocessing_data_path} does not exist",
            )

        for file in _multiprocessing_data_path.iterdir():
            Path.unlink(_multiprocessing_data_dir / file)

        multiprocess.MultiProcessCollector(REGISTRY)  # type: ignore[no-untyped-call]

    start_http_server(addr=addr, port=port)
