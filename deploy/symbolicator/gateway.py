"""Internal policy gateway for Crash-Cap's Symbolicator deployment.

Symbolicator deliberately supports per-request symbol sources. Crash-Cap does not:
all sources are deployment-owned, either fixed in configuration or injected by this
gateway from validated Workspace/inventory scope. The gateway rejects request-owned
sources and scraping configuration before forwarding a small endpoint allowlist.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

MAX_BODY_BYTES = 16 * 1024 * 1024
SCOPE_RE = re.compile(r"^wsp_[A-Za-z0-9_-]{1,96}$")
REQUEST_ID_RE = re.compile(r"^/requests/[0-9a-fA-F-]{16,64}$")
MICROSOFT_SYMBOL_URL = "https://msdl.microsoft.com/download/symbols/"
MICROSOFT_SOURCE_ID = "crash-cap:microsoft"


def _module_symbol_identity(module: object) -> tuple[str, str] | None:
    """Return a stable PDB identity without trusting paths or letter casing."""
    if not isinstance(module, dict):
        return None
    debug_file = module.get("debug_file")
    debug_id = module.get("debug_id")
    if not isinstance(debug_file, str) or not isinstance(debug_id, str):
        return None
    debug_file = re.split(r"[\\/]", debug_file.strip())[-1].casefold()
    debug_id = "".join(
        character for character in debug_id.casefold() if character.isalnum()
    )
    if not debug_file or not debug_id:
        return None
    return debug_file, debug_id


def _literal_path_pattern(value: str) -> str:
    """Escape a module path for Symbolicator's case-insensitive glob filter."""
    escaped = {"*": "[*]", "?": "[?]", "[": "[[]", "]": "[]]"}
    return "".join(
        escaped.get(character, character) for character in value.replace("\\", "/")
    )


class PublicSymbolMissRegistry:
    """Append-only registry of exact public PDB identities confirmed missing."""

    def __init__(self, path: str, seed_path: str | None = None):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._known: set[tuple[str, str]] = set()
        if seed_path:
            self._load_path(Path(seed_path))
        self._load_path(self.path)

    def _load_path(self, path: Path) -> None:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return
        except OSError as error:
            print(
                f"public symbol miss registry load failed path={path}: {error}",
                flush=True,
            )
            return
        for line in lines:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if (
                not isinstance(entry, dict)
                or entry.get("source_id") != MICROSOFT_SOURCE_ID
            ):
                continue
            identity = _module_symbol_identity(entry)
            if identity is not None:
                self._known.add(identity)

    def contains(self, module: object) -> bool:
        identity = _module_symbol_identity(module)
        if identity is None:
            return False
        with self._lock:
            return identity in self._known

    def record_completed_response(self, payload: object) -> int:
        if not isinstance(payload, dict) or payload.get("status") not in (
            None,
            "completed",
        ):
            return 0
        modules = payload.get("modules")
        if not isinstance(modules, list):
            return 0

        candidates: dict[tuple[str, str], dict[str, str]] = {}
        for module in modules:
            if not isinstance(module, dict) or module.get("debug_status") != "missing":
                continue
            identity = _module_symbol_identity(module)
            if identity is None:
                continue
            candidates[identity] = {
                "debug_file": identity[0],
                "debug_id": identity[1],
                "source_id": MICROSOFT_SOURCE_ID,
            }
        if not candidates:
            return 0

        with self._lock:
            new_entries = [
                (identity, entry)
                for identity, entry in candidates.items()
                if identity not in self._known
            ]
            if not new_entries:
                return 0
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8", newline="\n") as registry:
                    for _identity, entry in new_entries:
                        registry.write(json.dumps(entry, separators=(",", ":")))
                        registry.write("\n")
                    registry.flush()
                    os.fsync(registry.fileno())
            except OSError as error:
                # The in-memory set still prevents duplicate work until restart;
                # persistence failure remains visible in container logs.
                print(f"public symbol miss registry append failed: {error}", flush=True)
            self._known.update(identity for identity, _entry in new_entries)
            return len(new_entries)


def _microsoft_path_patterns(
    payload: dict[str, object], registry: PublicSymbolMissRegistry
) -> list[str] | None:
    """Return allowed module paths, [] to omit Microsoft, or None to fail open."""
    modules = payload.get("modules")
    if not isinstance(modules, list) or not modules:
        return None

    eligible_modules = 0
    patterns: set[str] = set()
    for module in modules:
        if not isinstance(module, dict) or module.get("type") not in (None, "pe"):
            continue
        eligible_modules += 1
        if registry.contains(module):
            continue
        path = module.get("debug_file") or module.get("code_file")
        if not isinstance(path, str) or not path.strip():
            # An unfilterable unknown identity must retain access to Microsoft.
            return None
        patterns.add(_literal_path_pattern(path.strip()))

    if eligible_modules == 0:
        return None
    return sorted(patterns)


class GatewayServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        upstream: tuple[str, int],
        *,
        workspace_sources_enabled: bool = False,
        workspace_source_mode: str = "filesystem",
        workspace_symbol_source_url: str = "http://symbol-source:8081",
        symbols_root: str = "/symbols/workspaces",
        microsoft_symbols_enabled: bool = True,
        company_sdk_path: str | None = None,
        public_miss_registry_path: str | None = None,
        public_miss_seed_path: str | None = None,
    ):
        super().__init__(address, GatewayHandler)
        self.upstream = upstream
        self.workspace_sources_enabled = workspace_sources_enabled
        if workspace_source_mode not in {"filesystem", "http"}:
            raise ValueError("WORKSPACE_SOURCE_MODE must be filesystem or http")
        self.workspace_source_mode = workspace_source_mode
        self.workspace_symbol_source_url = workspace_symbol_source_url.rstrip("/")
        self.symbols_root = symbols_root.rstrip("/")
        self.microsoft_symbols_enabled = microsoft_symbols_enabled
        self.company_sdk_path = (
            company_sdk_path.rstrip("/") if company_sdk_path else None
        )
        self.public_miss_registry = (
            PublicSymbolMissRegistry(
                public_miss_registry_path,
                seed_path=public_miss_seed_path,
            )
            if public_miss_registry_path
            else None
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
            if (
                200 <= response.status < 300
                and self.server.workspace_sources_enabled
                and self.server.microsoft_symbols_enabled
                and self.server.public_miss_registry is not None
            ):
                try:
                    response_payload = json.loads(response_body)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    response_payload = None
                learned = self.server.public_miss_registry.record_completed_response(
                    response_payload
                )
                if learned:
                    print(
                        f"public_symbol_miss_learned count={learned}",
                        flush=True,
                    )
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
            workspace_source: dict[str, object] = {
                # The deployment-owned source ID changes whenever verified
                # symbols increment the inventory. This invalidates stale
                # negative entries without accepting a request-owned URL.
                "id": (
                    f"crash-cap:{scope}:inventory-{inventory}:"
                    f"{self.server.workspace_source_mode}-v1"
                ),
                "layout": {"type": "unified", "casing": "lowercase"},
                "filters": {"filetypes": ["pe", "pdb"]},
                "is_public": False,
            }
            if self.server.workspace_source_mode == "http":
                workspace_source.update(
                    {
                        "type": "http",
                        "url": (
                            f"{self.server.workspace_symbol_source_url}/v1/workspaces/"
                            f"{scope}/inventories/{inventory}/"
                        ),
                    }
                )
            else:
                workspace_source.update(
                    {
                        "type": "filesystem",
                        "path": f"{self.server.symbols_root}/{scope}",
                    }
                )
            sources: list[dict[str, object]] = [workspace_source]
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
                path_patterns = None
                if self.server.public_miss_registry is not None:
                    path_patterns = _microsoft_path_patterns(
                        payload, self.server.public_miss_registry
                    )
                # An empty pattern result means every eligible PDB identity was
                # already confirmed missing. Omitting the source prevents a
                # network request while private/inventory sources still run.
                if path_patterns != []:
                    filters: dict[str, object] = {
                        "filetypes": ["pe", "pdb", "portablepdb"]
                    }
                    if path_patterns is not None:
                        filters["path_patterns"] = path_patterns
                    sources.append(
                        {
                            # This ID is deployment-owned and intentionally stable
                            # across Workspace requests. Changing it cold-starts the
                            # public cache and therefore requires rollout evidence.
                            "id": MICROSOFT_SOURCE_ID,
                            "type": "http",
                            "url": MICROSOFT_SYMBOL_URL,
                            "layout": {"type": "symstore"},
                            "filters": filters,
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
        workspace_source_mode=os.environ.get("WORKSPACE_SOURCE_MODE", "filesystem"),
        workspace_symbol_source_url=os.environ.get(
            "WORKSPACE_SYMBOL_SOURCE_URL", "http://symbol-source:8081"
        ),
        symbols_root=os.environ.get("WORKSPACE_SYMBOLS_ROOT", "/symbols/workspaces"),
        microsoft_symbols_enabled=microsoft_symbols_enabled,
        company_sdk_path=os.environ.get("COMPANY_SDK_SYMBOL_PATH") or None,
        public_miss_registry_path=(
            os.environ.get("PUBLIC_SYMBOL_MISS_REGISTRY_PATH") or None
        ),
        public_miss_seed_path=(os.environ.get("PUBLIC_SYMBOL_MISS_SEED_PATH") or None),
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
