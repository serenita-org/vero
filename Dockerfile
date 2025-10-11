ARG PYTHON_IMAGE_TAG="3.14-slim-trixie@sha256:5cfac249393fa6c7ebacaf0027a1e127026745e603908b226baa784c52b9d99b"
ARG UV_IMAGE_TAG="0.9.2@sha256:6dbd7c42a9088083fa79e41431a579196a189bcee3ae68ba904ac2bf77765867"

# uv image
FROM ghcr.io/astral-sh/uv:${UV_IMAGE_TAG} AS uv-image

# Build image
FROM docker.io/library/python:${PYTHON_IMAGE_TAG} AS build

WORKDIR /vero

# Install and compile dependencies
RUN --mount=from=uv-image,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --compile-bytecode --no-install-project

# App image
FROM docker.io/library/python:${PYTHON_IMAGE_TAG}

# Place executables in the environment at the front of the path
ENV PATH="/vero/.venv/bin:$PATH"

WORKDIR /vero
RUN groupadd -g 1000 vero && \
    useradd --no-create-home --shell /bin/false -u 1000 -g vero vero && \
    chown -R vero:vero /vero
COPY --from=build --chown=vero:vero /vero/.venv /vero/.venv

# Create directory for prometheus in multiprocess mode
RUN mkdir /tmp/multiprocessing && chown -R vero:vero /tmp/multiprocessing
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/multiprocessing

COPY --chown=vero:vero src .

EXPOSE 8000 8001

ARG GIT_TAG
ARG GIT_COMMIT
ENV GIT_TAG=$GIT_TAG
ENV GIT_COMMIT=$GIT_COMMIT

USER vero
ENTRYPOINT ["python", "main.py"]
