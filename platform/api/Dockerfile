# syntax=docker/dockerfile:1.7

# The patch-level tags and manifest digests are intentional: refresh them only
# with a reviewed dependency update.  The deployment Compose file pins the
# service image itself when it is promoted.
ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.11.29@sha256:eb2843a1e56fd9e30c7276ce1a52cba86e64c7b385f5e3279a0e08e02dd058fc

FROM ${UV_IMAGE} AS uv

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

# Install the locked production set into a self-contained, non-editable
# virtualenv.  The runtime stage therefore does not need a compiler or uv.
RUN --mount=type=cache,id=crashcap-uv-cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --no-editable --refresh-package crash-cap-platform

FROM ${PYTHON_IMAGE} AS runtime

RUN groupadd --gid 10001 crashcap \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin crashcap

WORKDIR /opt/crashcap
ENV PATH=/opt/crashcap/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

COPY --from=builder --chown=10001:10001 /opt/crashcap/.venv /opt/crashcap/.venv
COPY --from=builder --chown=10001:10001 /opt/crashcap/migrations /opt/crashcap/migrations
COPY --chown=10001:10001 contracts /opt/crashcap/contracts

USER 10001:10001
EXPOSE 8000

ENTRYPOINT ["crashcap-api"]
