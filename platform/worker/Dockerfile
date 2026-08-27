# syntax=docker/dockerfile:1.7

# Keep the worker on the same reviewed Python/uv patch levels and manifest
# digests as the API.
ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc
ARG DOCKER_CLI_IMAGE=docker:29.6.1-cli@sha256:862099ada15c669000bef53aa4cb9d821262829f45b0dda2159ccb276443043b

FROM ${UV_IMAGE} AS uv
FROM ${DOCKER_CLI_IMAGE} AS docker_cli

FROM ${PYTHON_IMAGE} AS builder

WORKDIR /opt/crashcap
ENV UV_COMPILE_BYTECODE=1 \
    UV_HTTP_TIMEOUT=120 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/crashcap/.venv

COPY --from=uv /uv /uvx /usr/local/bin/
COPY platform/pyproject.toml platform/uv.lock platform/README.md ./
COPY platform/api ./api
COPY platform/worker ./worker
COPY platform/cli ./cli
COPY platform/migrations ./migrations

RUN --mount=type=cache,id=crashcap-uv-cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-editable --refresh-package crash-cap-platform

FROM ${PYTHON_IMAGE} AS runtime

COPY --from=docker_cli /usr/local/bin/docker /usr/local/bin/docker

RUN groupadd --gid 10001 crashcap \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin crashcap \
    && install -d -o 10001 -g 10001 -m 0750 /var/lib/crashcap/tasks /var/lib/crashcap/symbols \
    && install -d -o 10001 -g 10001 -m 0555 /opt/crashcap-ops

# Official Symbolicator 26.7.2 release asset. BuildKit verifies the upstream
# bytes before they can enter the worker image.
ADD --checksum=sha256:1ae9dff518bd76c57218c0af6e78906283040b91a3adb31fa1181becce68ea43 \
    https://github.com/getsentry/symbolicator/releases/download/26.7.2/symsorter-Linux-x86_64 \
    /usr/local/bin/symsorter
RUN chmod 0555 /usr/local/bin/symsorter

WORKDIR /opt/crashcap
ENV PATH=/opt/crashcap/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder --chown=10001:10001 /opt/crashcap/.venv /opt/crashcap/.venv
COPY --chown=10001:10001 contracts /opt/crashcap/contracts
COPY --chown=10001:10001 --chmod=0444 scripts/phase1/ops_storage_init.py /opt/crashcap-ops/ops_storage_init.py

USER 10001:10001
ENTRYPOINT ["crashcap-worker"]
