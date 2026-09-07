"""The acceptance runner uses a cookie session and revokes its ephemeral CLI token."""

import importlib.util
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "acceptance_auth", ROOT / "scripts/upload_v3/authentication.py"
)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def endpoint():
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append((self.path, dict(self.headers), json.loads(body) if body else None))
            status = 200
            if self.path.endswith("/auth/login"):
                value = {"user": {"must_change_password": False}, "csrf_token": "test-csrf"}
            elif self.path.endswith("/me/tokens"):
                value = {"id": "tok_test", "token": "test-cli-credential"}
            else:
                status, value = 204, None
            self.send_response(status)
            if self.path.endswith("/auth/login"):
                self.send_header("Set-Cookie", "crashcap_session=test-session; HttpOnly; Path=/api")
            self.end_headers()
            if value:
                self.wfile.write(json.dumps(value).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/api/v3", calls
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


@pytest.mark.parametrize("failed", [False, True])
def test_acceptance_cleans_up_credentials_on_success_and_failure(endpoint, monkeypatch, failed):
    base, calls = endpoint
    monkeypatch.setattr(module.getpass, "getpass", lambda _: "fixture-password")
    try:
        with module.authenticated_api(base, "http://frontend.test", "alice") as (api, token):
            assert token == "test-cli-credential"  # noqa: S105 - test-only credential
            api("/workspaces", {"name": "acceptance"})
            if failed:
                raise RuntimeError("test run failed")
    except RuntimeError:
        assert failed
    assert [path for path, _, _ in calls] == [
        "/api/v3/auth/login",
        "/api/v3/me/tokens",
        "/api/v3/workspaces",
        "/api/v3/me/tokens/tok_test:revoke",
        "/api/v3/auth/logout",
    ]
    for _, headers, _ in calls[1:]:
        normalized = {name.lower(): value for name, value in headers.items()}
        assert normalized["cookie"] == "crashcap_session=test-session"
        assert normalized["origin"] == "http://frontend.test"
        assert normalized["x-csrf-token"] == "test-csrf"
        assert "authorization" not in normalized


def test_acceptance_does_not_forward_login_to_a_redirect():
    assert (
        module.NoRedirect().redirect_request(None, None, 307, "redirect", {}, "http://other.test")
        is None
    )
