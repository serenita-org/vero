ARG PYTHON_IMAGE_TAG="3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b"
ARG UV_IMAGE_TAG="0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c"

# uv image
FROM ghcr.io/astral-sh/uv:${UV_IMAGE_TAG} AS uv-image

# Build image
FROM docker.io/library/python:${PYTHON_IMAGE_TAG} AS build

WORKDIR /vero

# Install native build tools needed by Rust crates with C/asm deps
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends build-essential git

# Install and compile dependencies
RUN --mount=from=uv-image,source=/uv,target=/usr/local/bin/uv \
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

COPY --chown=vero:vero src .

EXPOSE 8000 8001

ARG GIT_TAG
ARG GIT_COMMIT
ENV GIT_TAG=$GIT_TAG
ENV GIT_COMMIT=$GIT_COMMIT

USER vero
ENTRYPOINT ["python", "main.py"]
