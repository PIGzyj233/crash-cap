from __future__ import annotations

import importlib.util
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "symbolicator_gateway", ROOT / "deploy" / "symbolicator" / "gateway.py"
)
assert SPEC is not None and SPEC.loader is not None
GATEWAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATEWAY)


class UpstreamHandler(BaseHTTPRequestHandler):
    calls: list[tuple[str, str, bytes]] = []

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_GET(self) -> None:  # noqa: N802
        self.calls.append(("GET", self.path, b""))
        body = b"ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.calls.append(("POST", self.path, body))
        response = b'{"status":"completed"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)


class GatewayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        cls.gateway = GATEWAY.GatewayServer(
            ("127.0.0.1", 0), ("127.0.0.1", cls.upstream.server_port)
        )
        cls.threads = [
            threading.Thread(target=cls.upstream.serve_forever, daemon=True),
            threading.Thread(target=cls.gateway.serve_forever, daemon=True),
        ]
        for thread in cls.threads:
            thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.gateway.shutdown()
        cls.upstream.shutdown()
        cls.gateway.server_close()
        cls.upstream.server_close()

    def setUp(self) -> None:
        UpstreamHandler.calls.clear()

    def post(self, payload: dict, query: str = "scope=wsp_test"):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.gateway.server_port}/symbolicate?{query}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urllib.request.urlopen(request, timeout=2)

    def test_deployment_owned_sources_are_used(self) -> None:
        with self.post({"platform": "native", "stacktraces": [], "modules": []}) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(len(UpstreamHandler.calls), 1)
        forwarded = json.loads(UpstreamHandler.calls[0][2])
        self.assertNotIn("sources", forwarded)

    def test_request_owned_source_is_rejected_before_upstream(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post(
                {
                    "platform": "native",
                    "stacktraces": [],
                    "modules": [],
                    "sources": [{"type": "http", "id": "evil", "url": "https://example.test"}],
                }
            )
        with raised.exception as error_response:
            self.assertEqual(error_response.code, 400)
            error = json.loads(error_response.read())
        self.assertEqual(error["error"]["code"], "REQUEST_SOURCES_FORBIDDEN")
        self.assertEqual(UpstreamHandler.calls, [])

    def test_workspace_scope_is_required(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post({"platform": "native"}, query="")
        with raised.exception as error_response:
            self.assertEqual(error_response.code, 400)
            error_response.read()
        self.assertEqual(UpstreamHandler.calls, [])

    def test_source_context_and_scraping_are_rejected(self) -> None:
        for payload in (
            {"options": {"apply_source_context": True}},
            {"scraping": {"enabled": True, "allowed_origins": ["*"]}},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    self.post(payload)
                with raised.exception as error_response:
                    error_response.read()
        self.assertEqual(UpstreamHandler.calls, [])


if __name__ == "__main__":
    unittest.main()
