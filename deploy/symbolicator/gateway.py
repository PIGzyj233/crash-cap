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
MICROSOFT_SYMBOL_URL = "https://msdl.microsoft.com/download/symbols/"


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        upstream: tuple[str, int],
        *,
        workspace_sources_enabled: bool = False,
        symbols_root: str = "/symbols/workspaces",
        microsoft_symbols_enabled: bool = True,
        company_sdk_path: str | None = None,
    ):
        super().__init__(address, GatewayHandler)
        self.upstream = upstream
        self.workspace_sources_enabled = workspace_sources_enabled
        self.symbols_root = symbols_root.rstrip("/")
        self.microsoft_symbols_enabled = microsoft_symbols_enabled
        self.company_sdk_path = (
            company_sdk_path.rstrip("/") if company_sdk_path else None
        )


class GatewayHandler(BaseHTTPRequestHandler):
    server: GatewayServer
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        # Do not log request bodies or query strings. The scope is operational
        # metadata, but keeping it out also makes accidental credential logging
        # impossible if the client violates the contract.
        print(f"{self.client_address[0]} - {fmt % args}", flush=True)

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

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/healthcheck" and not parsed.query:
            self._proxy("GET", "/healthcheck")
            return
        if REQUEST_ID_RE.fullmatch(parsed.path) and not parsed.query:
            self._proxy("GET", parsed.path)
            return
        self._json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "endpoint not found")

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path != "/symbolicate":
            self._json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "endpoint not found")
            return

        query = parse_qs(parsed.query, keep_blank_values=True)
        if set(query) - {"scope", "inventory", "timeout"}:
            self._json_error(
                HTTPStatus.BAD_REQUEST, "INVALID_QUERY", "unsupported query parameter"
            )
            return
        scopes = query.get("scope", [])
        if len(scopes) != 1 or not SCOPE_RE.fullmatch(scopes[0]):
            self._json_error(
                HTTPStatus.BAD_REQUEST,
                "INVALID_SCOPE",
                "one workspace scope is required",
            )
            return
        inventories = query.get("inventory", [])
        if (
            len(inventories) != 1
            or not inventories[0].isdigit()
            or len(inventories[0]) > 19
            or int(inventories[0]) > 9_223_372_036_854_775_807
        ):
            self._json_error(
                HTTPStatus.BAD_REQUEST,
                "INVALID_INVENTORY",
                "one uint63 symbol inventory version is required",
            )
            return
        if "timeout" in query:
            values = query["timeout"]
            if len(values) != 1 or not values[0].isdigit() or int(values[0]) > 300:
                self._json_error(
                    HTTPStatus.BAD_REQUEST, "INVALID_TIMEOUT", "timeout must be 0..300"
                )
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
            self._json_error(
                HTTPStatus.BAD_REQUEST, "INVALID_JSON", "request body is not valid JSON"
            )
            return
        if not isinstance(payload, dict):
            self._json_error(
                HTTPStatus.BAD_REQUEST,
                "INVALID_REQUEST",
                "request body must be an object",
            )
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
            self._json_error(
                HTTPStatus.BAD_REQUEST, "INVALID_OPTIONS", "options must be an object"
            )
            return
        if isinstance(options, dict) and options.get("apply_source_context") is True:
            self._json_error(
                HTTPStatus.BAD_REQUEST,
                "SOURCE_CONTEXT_FORBIDDEN",
                "source-context downloads are disabled in Phase 0",
            )
            return

        # Deliberately do not forward the caller's Workspace scope. Private
        # source identities already include Workspace + inventory, while the
        # stable Microsoft source ID must remain in Symbolicator's global cache
        # namespace so one approved download is reusable by every Workspace.
        upstream_target = "/symbolicate"
        timeout = query.get("timeout")
        if timeout:
            upstream_target = f"{upstream_target}?timeout={timeout[0]}"
        if self.server.workspace_sources_enabled:
            scope = scopes[0]
            inventory = inventories[0]
            sources: list[dict[str, object]] = [
                {
                    # The filesystem path remains Workspace-scoped while the
                    # deployment-owned source ID changes whenever verified
                    # symbols increment the inventory. This invalidates stale
                    # negative debug-file cache entries without accepting a
                    # request-owned URL or source definition.
                    "id": f"crash-cap:{scope}:inventory-{inventory}",
                    "type": "filesystem",
                    "path": f"{self.server.symbols_root}/{scope}",
                    "layout": {"type": "unified", "casing": "lowercase"},
                    "filters": {"filetypes": ["pe", "pdb"]},
                    "is_public": False,
                }
            ]
            if self.server.company_sdk_path:
                sources.append(
                    {
                        "id": "crash-cap:company-sdk",
                        "type": "filesystem",
                        "path": self.server.company_sdk_path,
                        "layout": {"type": "unified", "casing": "lowercase"},
                        "filters": {"filetypes": ["pe", "pdb"]},
                        "is_public": False,
                    }
                )
            if self.server.microsoft_symbols_enabled:
                sources.append(
                    {
                        # This ID is deployment-owned and intentionally stable
                        # across Workspace requests. Changing it cold-starts the
                        # public cache and therefore requires rollout evidence.
                        "id": "crash-cap:microsoft",
                        "type": "http",
                        "url": MICROSOFT_SYMBOL_URL,
                        "layout": {"type": "symstore"},
                        "filters": {"filetypes": ["pe", "pdb", "portablepdb"]},
                        "is_public": True,
                    }
                )
            payload["sources"] = sources
            body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        self._proxy("POST", upstream_target, body)


def main() -> None:
    bind_host = os.environ.get("GATEWAY_BIND", "0.0.0.0")
    bind_port = int(os.environ.get("GATEWAY_PORT", "3021"))
    upstream_host = os.environ.get("SYMBOLICATOR_HOST", "symbolicator")
    upstream_port = int(os.environ.get("SYMBOLICATOR_PORT", "3021"))
    workspace_sources_enabled = os.environ.get(
        "WORKSPACE_SOURCES_ENABLED", "false"
    ).lower() in {
        "1",
        "true",
        "yes",
    }
    microsoft_symbols_enabled = os.environ.get(
        "MICROSOFT_SYMBOLS_ENABLED", "true"
    ).lower() in {
        "1",
        "true",
        "yes",
    }
    server = GatewayServer(
        (bind_host, bind_port),
        (upstream_host, upstream_port),
        workspace_sources_enabled=workspace_sources_enabled,
        symbols_root=os.environ.get("WORKSPACE_SYMBOLS_ROOT", "/symbols/workspaces"),
        microsoft_symbols_enabled=microsoft_symbols_enabled,
        company_sdk_path=os.environ.get("COMPANY_SDK_SYMBOL_PATH") or None,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
