# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.12.11-slim-bookworm@sha256:519591d6871b7bc437060736b9f7456b8731f1499a57e22e6c285135ae657bf7
FROM ${PYTHON_IMAGE}

RUN groupadd --gid 10001 crashcap \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin crashcap

WORKDIR /opt/crashcap-ops
COPY --chmod=0555 scripts/phase1/ops_exporter.py /opt/crashcap-ops/ops_exporter.py
COPY --chmod=0555 scripts/phase1/ops_docker_proxy.py /opt/crashcap-ops/ops_docker_proxy.py

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    OPS_EXPORTER_PORT=9108

USER 10001:10001
EXPOSE 9108
ENTRYPOINT ["python", "/opt/crashcap-ops/ops_exporter.py"]
