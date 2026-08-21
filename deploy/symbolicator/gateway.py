"""Internal policy gateway for Crash-Cap's Symbolicator deployment.

Symbolicator deliberately supports per-request symbol sources. Crash-Cap does not:
all sources are deployment-owned and configured in Symbolicator's config file. This
gateway rejects request-owned sources and scraping configuration before forwarding a
small allowlist of endpoints to the private Symbolicator container.
"""

from __future__ import annotations

import http.client
import json
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit


MAX_BODY_BYTES = 16 * 1024 * 1024
SCOPE_RE = re.compile(r"^wsp_[A-Za-z0-9_-]{1,96}$")
REQUEST_ID_RE = re.compile(r"^/requests/[0-9a-fA-F-]{16,64}$")


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], upstream: tuple[str, int]):
        super().__init__(address, GatewayHandler)
        self.upstream = upstream


class GatewayHandler(BaseHTTPRequestHandler):
    server: GatewayServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        # Do not log request bodies or query strings. The scope is operational
        # metadata, but keeping it out also makes accidental credential logging
        # impossible if the client violates the contract.
        print(f'{self.client_address[0]} - {fmt % args}', flush=True)

    def _json_error(self, status: HTTPStatus, code: str, message: str) -> None:
        body = json.dumps(
            {"error": {"code": code, "message": message, "details": {}}},
            separators=(",", ":"),
        ).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _proxy(self, method: str, target: str, body: bytes | None = None) -> None:
        connection = http.client.HTTPConnection(*self.server.upstream, timeout=310)
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Content-Length"] = str(len(body))
        try:
            connection.request(method, target, body=body, headers=headers)
            response = connection.getresponse()
            response_body = response.read()
            self.send_response(response.status)
            content_type = response.getheader("Content-Type")
            if content_type:
                self.send_header("Content-Type", content_type)
            retry_after = response.getheader("Retry-After")
            if retry_after:
                self.send_header("Retry-After", retry_after)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
        except (OSError, http.client.HTTPException):
            self._json_error(
                HTTPStatus.BAD_GATEWAY,
                "SYMBOLICATOR_UNAVAILABLE",
                "symbolication service is unavailable",
            )
        finally:
            connection.close()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlsplit(self.path)
        if parsed.path == "/healthcheck" and not parsed.query:
            self._proxy("GET", "/healthcheck")
            return
        if REQUEST_ID_RE.fullmatch(parsed.path) and not parsed.query:
            self._proxy("GET", parsed.path)
            return
        self._json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "endpoint not found")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlsplit(self.path)
        if parsed.path != "/symbolicate":
            self._json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "endpoint not found")
            return

        query = parse_qs(parsed.query, keep_blank_values=True)
        if set(query) - {"scope", "timeout"}:
            self._json_error(HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "unsupported query parameter")
            return
        scopes = query.get("scope", [])
        if len(scopes) != 1 or not SCOPE_RE.fullmatch(scopes[0]):
            self._json_error(
                HTTPStatus.BAD_REQUEST,
                "INVALID_SCOPE",
                "one workspace scope is required",
            )
            return
        if "timeout" in query:
            values = query["timeout"]
            if len(values) != 1 or not values[0].isdigit() or int(values[0]) > 300:
                self._json_error(HTTPStatus.BAD_REQUEST, "INVALID_TIMEOUT", "timeout must be 0..300")
                return

        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            self._json_error(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "UNSUPPORTED_MEDIA_TYPE",
                "application/json is required",
            )
            return
        try:
            content_length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > MAX_BODY_BYTES:
            self._json_error(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "BODY_TOO_LARGE",
                "request body exceeds the configured limit",
            )
            return

        body = self.rfile.read(content_length)
        try:
            payload = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._json_error(HTTPStatus.BAD_REQUEST, "INVALID_JSON", "request body is not valid JSON")
            return
        if not isinstance(payload, dict):
            self._json_error(HTTPStatus.BAD_REQUEST, "INVALID_REQUEST", "request body must be an object")
            return
        if "sources" in payload:
            self._json_error(
                HTTPStatus.BAD_REQUEST,
                "REQUEST_SOURCES_FORBIDDEN",
                "symbol sources are deployment-managed",
            )
            return
        if payload.get("scraping") not in (None, {}):
            self._json_error(
                HTTPStatus.BAD_REQUEST,
                "SCRAPING_FORBIDDEN",
                "request-owned scraping configuration is disabled",
            )
            return
        options = payload.get("options")
        if options is not None and not isinstance(options, dict):
            self._json_error(HTTPStatus.BAD_REQUEST, "INVALID_OPTIONS", "options must be an object")
            return
        if isinstance(options, dict) and options.get("apply_source_context") is True:
            self._json_error(
                HTTPStatus.BAD_REQUEST,
                "SOURCE_CONTEXT_FORBIDDEN",
                "source-context downloads are disabled in Phase 0",
            )
            return

        self._proxy("POST", self.path, body)


def main() -> None:
    bind_host = os.environ.get("GATEWAY_BIND", "0.0.0.0")
    bind_port = int(os.environ.get("GATEWAY_PORT", "3021"))
    upstream_host = os.environ.get("SYMBOLICATOR_HOST", "symbolicator")
    upstream_port = int(os.environ.get("SYMBOLICATOR_PORT", "3021"))
    server = GatewayServer((bind_host, bind_port), (upstream_host, upstream_port))
    server.serve_forever()


if __name__ == "__main__":
    main()
