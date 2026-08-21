#!/usr/bin/env python3
"""Minimal read-only Docker Engine API proxy for the Phase 1 metrics sidecar.

Only container listing and one-shot container stats are exposed.  The proxy
rejects every write method and every other Docker endpoint before touching the
socket.  It never logs request paths, response bodies or container metadata.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import socket
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

CONTAINER_ID = re.compile(r"^/containers/([0-9a-fA-F]{12,64})/stats$")
ALLOWED_SERVICES = {
    "postgres",
    "redis",
    "rustfs",
    "symbolicator",
    "symbolicator-gateway",
    "api",
    "worker",
    "worker-verify",
    "worker-ingest",
    "worker-dump-large",
    "retention",
    "frontend",
}


def filter_containers(
    containers: object,
    *,
    project: str,
    services: set[str] = ALLOWED_SERVICES,
) -> list[dict[str, Any]]:
    if not isinstance(containers, list):
        return []
    result: list[dict[str, Any]] = []
    for container in containers:
        if not isinstance(container, dict):
            continue
        container_id = container.get("Id")
        labels = container.get("Labels")
        if not isinstance(container_id, str) or not re.fullmatch(
            r"[0-9a-fA-F]{12,64}", container_id
        ):
            continue
        if not isinstance(labels, dict):
            continue
        if labels.get("com.docker.compose.project") != project:
            continue
        if labels.get("com.docker.compose.service") not in services:
            continue
        result.append(container)
    return result


def allowed_container_id(requested: str, containers: list[dict[str, Any]]) -> bool:
    return any(container.get("Id") == requested for container in containers)


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float) -> None:
        super().__init__("localhost", timeout=timeout)
        self.socket_path = socket_path

    def connect(self) -> None:
        unix_family = socket.__dict__.get("AF_UNIX")
        if not isinstance(unix_family, int):
            raise OSError("Unix sockets are unavailable on this platform")
        sock = socket.socket(unix_family, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.socket_path)
        self.sock = sock


class ProxyServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        socket_path: str,
        timeout: float,
        project: str,
    ) -> None:
        super().__init__(address, ProxyHandler)
        self.socket_path = socket_path
        self.docker_timeout = timeout
        self.project = project


class ProxyHandler(BaseHTTPRequestHandler):
    server: ProxyServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/healthz" and not parsed.query:
            self._write(HTTPStatus.OK, b"ok\n")
            return
        if parsed.path == "/containers/json":
            query = parse_qs(parsed.query, keep_blank_values=True)
            if set(query) - {"all"}:
                self._write_error(HTTPStatus.BAD_REQUEST)
                return
            self._proxy_list()
            return
        match = CONTAINER_ID.fullmatch(parsed.path)
        if match:
            query = parse_qs(parsed.query, keep_blank_values=True)
            if query != {"stream": ["false"]}:
                self._write_error(HTTPStatus.BAD_REQUEST)
                return
            allowed = self._allowed_containers()
            if allowed is None or not allowed_container_id(match.group(1), allowed):
                self._write_error(HTTPStatus.FORBIDDEN)
                return
            self._proxy_get(f"/containers/{match.group(1)}/stats?stream=false")
            return
        self._write_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        self._write_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_PUT(self) -> None:
        self._write_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_PATCH(self) -> None:
        self._write_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def do_DELETE(self) -> None:
        self._write_error(HTTPStatus.METHOD_NOT_ALLOWED)

    def _allowed_containers(self) -> list[dict[str, Any]] | None:
        body, status = self._docker_get("/containers/json?all=1")
        if status != HTTPStatus.OK:
            return None
        try:
            return filter_containers(
                json.loads(body.decode("utf-8")), project=self.server.project
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None

    def _proxy_list(self) -> None:
        body, status = self._docker_get("/containers/json?all=1")
        if status != HTTPStatus.OK:
            self._write_error(HTTPStatus.BAD_GATEWAY)
            return
        try:
            filtered = filter_containers(
                json.loads(body.decode("utf-8")), project=self.server.project
            )
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_error(HTTPStatus.BAD_GATEWAY)
            return
        self._write(
            HTTPStatus.OK, json.dumps(filtered, separators=(",", ":")).encode("utf-8")
        )

    def _docker_get(self, path: str) -> tuple[bytes, int]:
        connection = UnixHTTPConnection(
            self.server.socket_path, self.server.docker_timeout
        )
        try:
            connection.request("GET", path, headers={"Accept": "application/json"})
            response = connection.getresponse()
            return response.read(16 * 1024 * 1024), response.status
        except (OSError, http.client.HTTPException):
            return b"", 0
        finally:
            connection.close()

    def _proxy_get(self, path: str) -> None:
        connection = UnixHTTPConnection(
            self.server.socket_path, self.server.docker_timeout
        )
        try:
            connection.request("GET", path, headers={"Accept": "application/json"})
            response = connection.getresponse()
            body = response.read(16 * 1024 * 1024)
            content_type = response.getheader("Content-Type") or "application/json"
            self.send_response(response.status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except (OSError, http.client.HTTPException):
            self._write_error(HTTPStatus.BAD_GATEWAY)
        finally:
            connection.close()

    def _write_error(self, status: HTTPStatus) -> None:
        self._write(
            status, json.dumps({"error": "docker api unavailable"}).encode("utf-8")
        )

    def _write(self, status: HTTPStatus, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    host = os.environ.get("OPS_DOCKER_PROXY_BIND", "0.0.0.0")
    port = int(os.environ.get("OPS_DOCKER_PROXY_PORT", "2375"))
    socket_path = os.environ.get("OPS_DOCKER_PROXY_SOCKET", "/var/run/docker.sock")
    timeout = float(os.environ.get("OPS_DOCKER_PROXY_TIMEOUT_SECONDS", "2"))
    project = os.environ.get("OPS_DOCKER_PROXY_PROJECT", "crash-cap-phase1")
    ProxyServer((host, port), socket_path, timeout, project).serve_forever()


if __name__ == "__main__":
    main()
