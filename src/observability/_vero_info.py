import os

from prometheus_client import Gauge


def get_service_commit() -> str:
    return os.getenv("GIT_COMMIT", "---")


def get_service_name() -> str:
    return "io.serenita.vero"


def get_service_version() -> str:
    return os.getenv("GIT_TAG", "v0.0.0-dev")


_VERO_INFO = Gauge(
    "vero_info",
    "Information about the Vero build.",
    labelnames=["commit", "version"],
)
_VERO_INFO.labels(
    commit=get_service_commit(),
    version=get_service_version(),
).set(1)
