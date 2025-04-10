ARG PYTHON_IMAGE_TAG="3.12-slim-bookworm@sha256:123be5684f39d8476e64f47a5fddf38f5e9d839baff5c023c815ae5bdfae0df7"
ARG UV_IMAGE_TAG="0.6.13@sha256:0b6dc79013b689f3bc0cbf12807cb1c901beaafe80f2ee10a1d76aa3842afb92"

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

EXPOSE 8000

ARG GIT_TAG
ARG GIT_COMMIT
ENV GIT_TAG=$GIT_TAG
ENV GIT_COMMIT=$GIT_COMMIT

USER vero
ENTRYPOINT ["python", "main.py"]
