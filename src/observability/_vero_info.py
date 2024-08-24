import os


def get_service_commit():
    return os.getenv("GIT_COMMIT", "---")


def get_service_name():
    return "io.serenita.vero"


def get_service_version():
    return os.getenv("GIT_TAG", "v0.0.0")
