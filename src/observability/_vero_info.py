import os


def get_service_commit() -> str:
    return os.getenv("GIT_COMMIT", "---")


def get_service_name() -> str:
    return "io.serenita.vero"


def get_service_version() -> str:
    return os.getenv("GIT_TAG", "v0.0.0-dev")
