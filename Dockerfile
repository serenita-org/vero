ARG PYTHON_IMAGE_TAG="3.14-slim-bookworm@sha256:404ca55875fc24a64f0a09e9ec7d405d725109aec04c9bf0991798fd45c7b898"
ARG UV_IMAGE_TAG="0.9.18@sha256:5713fa8217f92b80223bc83aac7db36ec80a84437dbc0d04bbc659cae030d8c9"

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

COPY --chown=vero:vero src .

EXPOSE 8000 8001

ARG GIT_TAG
ARG GIT_COMMIT
ENV GIT_TAG=$GIT_TAG
ENV GIT_COMMIT=$GIT_COMMIT

USER vero
ENTRYPOINT ["python", "main.py"]
