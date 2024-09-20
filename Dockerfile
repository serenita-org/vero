ARG PYTHON_IMAGE_TAG="3.12-slim@sha256:105e9d85a67db1602e70fa2bbb49c1e66bae7e3bdcb6259344fe8ca116434f74"
ARG VENV_LOCATION="/opt/venv"

# Build image
FROM docker.io/library/python:${PYTHON_IMAGE_TAG} AS build

WORKDIR /build

RUN apt-get update && apt-get install --no-install-recommends -y git=1:2.39.5-0+deb12u1 && \
   apt-get clean && rm -rf /var/lib/apt/lists/*

ARG VENV_LOCATION
ENV PATH="$VENV_LOCATION/bin:$PATH"
RUN pip install --no-cache-dir uv==0.4.13 && uv venv ${VENV_LOCATION}
COPY requirements.txt .
RUN uv pip sync requirements.txt

# App image
FROM docker.io/library/python:${PYTHON_IMAGE_TAG}

ARG VENV_LOCATION
COPY --from=build $VENV_LOCATION $VENV_LOCATION
ENV PATH="$VENV_LOCATION/bin:$PATH"

WORKDIR /vero
RUN groupadd -g 1000 vero && \
    useradd --no-create-home --shell /bin/false -u 1000 -g vero vero && \
    chown -R vero:vero /vero

# Create directory for prometheus in multiprocess mode
RUN mkdir /tmp/multiprocessing && chown -R vero:vero /tmp/multiprocessing
ENV PROMETHEUS_MULTIPROC_DIR=/tmp/multiprocessing

COPY src .

EXPOSE 8000

ARG GIT_TAG
ARG GIT_COMMIT
ENV GIT_TAG=$GIT_TAG
ENV GIT_COMMIT=$GIT_COMMIT

USER vero
ENTRYPOINT ["python", "main.py"]
