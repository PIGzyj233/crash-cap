from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "symbolicator_gateway", ROOT / "deploy" / "symbolicator" / "gateway.py"
)
assert SPEC is not None and SPEC.loader is not None
GATEWAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GATEWAY)


class UpstreamHandler(BaseHTTPRequestHandler):
    calls: ClassVar[list[tuple[str, str, bytes]]] = []
    response_payload: ClassVar[dict] = {"status": "completed"}
    get_response_payload: ClassVar[dict | None] = None

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def do_GET(self) -> None:
        self.calls.append(("GET", self.path, b""))
        body = (
            b"ok"
            if self.get_response_payload is None
            else json.dumps(self.get_response_payload, separators=(",", ":")).encode()
        )
        self.send_response(200)
        if self.get_response_payload is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.calls.append(("POST", self.path, body))
        response = json.dumps(self.response_payload, separators=(",", ":")).encode()
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
            ("127.0.0.1", 0),
            ("127.0.0.1", cls.upstream.server_port),
            workspace_sources_enabled=True,
            company_sdk_path="/symbols/company-sdk",
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
        UpstreamHandler.response_payload = {"status": "completed"}
        UpstreamHandler.get_response_payload = None

    def post(self, payload: dict, query: str = "scope=wsp_test&inventory=3"):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.gateway.server_port}/symbolicate?{query}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return urllib.request.urlopen(request, timeout=2)

    def test_deployment_owned_sources_are_used(self) -> None:
        with self.post(
            {"platform": "native", "stacktraces": [], "modules": []}
        ) as response:
            self.assertEqual(response.status, 200)
        self.assertEqual(len(UpstreamHandler.calls), 1)
        self.assertEqual(UpstreamHandler.calls[0][1], "/symbolicate")
        forwarded = json.loads(UpstreamHandler.calls[0][2])
        self.assertEqual(
            forwarded["sources"][0]["path"], "/symbols/workspaces/wsp_test"
        )
        self.assertEqual(
            forwarded["sources"][0]["id"],
            "crash-cap:wsp_test:inventory-3:filesystem-v1",
        )
        self.assertEqual(forwarded["sources"][1]["id"], "crash-cap:company-sdk")
        self.assertEqual(forwarded["sources"][1]["path"], "/symbols/company-sdk")
        self.assertEqual(
            forwarded["sources"][2]["url"],
            "https://msdl.microsoft.com/download/symbols/",
        )

    def test_workspace_scope_selects_a_distinct_private_root(self) -> None:
        with self.post(
            {"platform": "native", "stacktraces": [], "modules": []},
            query="scope=wsp_other&inventory=9&timeout=5",
        ) as response:
            self.assertEqual(response.status, 200)
        method, target, body = UpstreamHandler.calls[0]
        self.assertEqual(method, "POST")
        self.assertEqual(target, "/symbolicate?timeout=5")
        forwarded = json.loads(body)
        self.assertEqual(
            forwarded["sources"][0]["path"], "/symbols/workspaces/wsp_other"
        )
        self.assertEqual(
            forwarded["sources"][0]["id"],
            "crash-cap:wsp_other:inventory-9:filesystem-v1",
        )

    def test_http_workspace_source_is_deployment_owned_and_inventory_scoped(
        self,
    ) -> None:
        prior_mode = self.gateway.workspace_source_mode
        try:
            self.gateway.workspace_source_mode = "http"
            with self.post(
                {"platform": "native", "stacktraces": [], "modules": []},
                query="scope=wsp_http&inventory=12",
            ) as response:
                self.assertEqual(response.status, 200)
        finally:
            self.gateway.workspace_source_mode = prior_mode
        forwarded = json.loads(UpstreamHandler.calls[-1][2])
        source = forwarded["sources"][0]
        self.assertEqual(source["type"], "http")
        self.assertEqual(source["id"], "crash-cap:wsp_http:inventory-12:http-v1")
        self.assertEqual(
            source["url"],
            "http://symbol-source:8081/v1/workspaces/wsp_http/inventories/12/",
        )

    def test_microsoft_source_identity_and_cache_scope_are_shared_across_workspaces(
        self,
    ) -> None:
        for scope in ("wsp_first", "wsp_second"):
            with self.post(
                {"platform": "native", "stacktraces": [], "modules": []},
                query=f"scope={scope}&inventory=7&timeout=5",
            ) as response:
                self.assertEqual(response.status, 200)

        self.assertEqual(len(UpstreamHandler.calls), 2)
        first_target = UpstreamHandler.calls[0][1]
        second_target = UpstreamHandler.calls[1][1]
        self.assertEqual(first_target, "/symbolicate?timeout=5")
        self.assertEqual(second_target, "/symbolicate?timeout=5")
        self.assertNotIn("scope=", first_target)
        self.assertNotIn("scope=", second_target)

        first = json.loads(UpstreamHandler.calls[0][2])
        second = json.loads(UpstreamHandler.calls[1][2])
        self.assertNotEqual(first["sources"][0]["id"], second["sources"][0]["id"])
        self.assertEqual(first["sources"][-1]["id"], "crash-cap:microsoft")
        self.assertEqual(second["sources"][-1]["id"], "crash-cap:microsoft")
        self.assertTrue(first["sources"][-1]["is_public"])
        self.assertTrue(second["sources"][-1]["is_public"])

    def test_exact_missing_identity_is_persisted_and_filtered(self) -> None:
        module = {
            "type": "pe",
            "code_file": "C:\\Windows\\System32\\nvencodeapi64.dll",
            "code_id": "68756A9B102000",
            "debug_file": "nvEncodeAPI64.pdb",
            "debug_id": "20fdb836-a38d-4847-8f34-329f34a1fe4f-1",
        }
        missing_module = {**module, "debug_status": "missing"}
        kernel_module = {
            "type": "pe",
            "code_file": "C:\\Windows\\System32\\kernel32.dll",
            "code_id": "1234",
            "debug_file": "kernel32.pdb",
            "debug_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-1",
        }
        prior_registry = self.gateway.public_miss_registry
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                registry_path = str(Path(temp_dir) / "public-misses.jsonl")
                self.gateway.public_miss_registry = GATEWAY.PublicSymbolMissRegistry(
                    registry_path
                )
                UpstreamHandler.response_payload = {
                    "status": "completed",
                    "modules": [missing_module],
                }

                with self.post(
                    {
                        "platform": "native",
                        "stacktraces": [],
                        "modules": [module],
                    }
                ):
                    pass
                first = json.loads(UpstreamHandler.calls[-1][2])
                self.assertEqual(first["sources"][-1]["id"], "crash-cap:microsoft")

                with self.post(
                    {
                        "platform": "native",
                        "stacktraces": [],
                        "modules": [module],
                    }
                ):
                    pass
                second = json.loads(UpstreamHandler.calls[-1][2])
                self.assertNotIn(
                    "crash-cap:microsoft",
                    [source["id"] for source in second["sources"]],
                )

                with self.post(
                    {
                        "platform": "native",
                        "stacktraces": [],
                        "modules": [module, kernel_module],
                    }
                ):
                    pass
                mixed = json.loads(UpstreamHandler.calls[-1][2])
                microsoft = mixed["sources"][-1]
                self.assertEqual(microsoft["id"], "crash-cap:microsoft")
                self.assertEqual(
                    microsoft["filters"]["path_patterns"], ["kernel32.pdb"]
                )

                replacement_identity = {
                    **module,
                    "debug_id": "ffffffff-1111-2222-3333-444444444444-1",
                }
                with self.post(
                    {
                        "platform": "native",
                        "stacktraces": [],
                        "modules": [replacement_identity],
                    }
                ):
                    pass
                new_identity = json.loads(UpstreamHandler.calls[-1][2])
                self.assertEqual(
                    new_identity["sources"][-1]["filters"]["path_patterns"],
                    ["nvEncodeAPI64.pdb"],
                )

                reloaded = GATEWAY.PublicSymbolMissRegistry(registry_path)
                self.assertTrue(reloaded.contains(module))
                self.assertFalse(reloaded.contains(replacement_identity))
        finally:
            self.gateway.public_miss_registry = prior_registry

    def test_deployment_seed_matches_only_the_confirmed_nvidia_identity(self) -> None:
        module = {
            "type": "pe",
            "code_file": "C:\\Windows\\System32\\nvencodeapi64.dll",
            "code_id": "68756A9B102000",
            "debug_file": (
                "C:\\dvs\\p4\\build\\sw\\rel\\gpu_drv\\r575\\r576_76\\drivers\\"
                "multimedia\\codecs\\EncodeAPI\\_out\\wddm2_amd64_release\\"
                "nvEncodeAPI64.pdb"
            ),
            "debug_id": "20fdb836a38d48478f34329f34a1fe4f1",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = GATEWAY.PublicSymbolMissRegistry(
                str(Path(temp_dir) / "public-misses.jsonl"),
                seed_path=str(
                    ROOT / "deploy" / "symbolicator" / "public-misses.seed.jsonl"
                ),
            )
            self.assertTrue(registry.contains(module))
            self.assertEqual(
                GATEWAY._microsoft_path_patterns({"modules": [module]}, registry), []
            )

            new_driver = {
                **module,
                "debug_id": "ffffffff1111222233334444444444441",
            }
            self.assertFalse(registry.contains(new_driver))
            self.assertEqual(
                GATEWAY._microsoft_path_patterns({"modules": [new_driver]}, registry),
                [module["debug_file"].replace("\\", "/")],
            )

    def test_transient_public_failure_is_not_registered(self) -> None:
        module = {
            "type": "pe",
            "code_file": "C:\\Windows\\System32\\example.dll",
            "code_id": "1234",
            "debug_file": "example.pdb",
            "debug_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-1",
        }
        prior_registry = self.gateway.public_miss_registry
        try:
            for debug_status in ("fetching_failed", "timeout", "malformed"):
                with self.subTest(debug_status=debug_status):
                    UpstreamHandler.calls.clear()
                    with tempfile.TemporaryDirectory() as temp_dir:
                        self.gateway.public_miss_registry = (
                            GATEWAY.PublicSymbolMissRegistry(
                                str(Path(temp_dir) / "public-misses.jsonl")
                            )
                        )
                        UpstreamHandler.response_payload = {
                            "status": "completed",
                            "modules": [{**module, "debug_status": debug_status}],
                        }
                        for _ in range(2):
                            with self.post(
                                {
                                    "platform": "native",
                                    "stacktraces": [],
                                    "modules": [module],
                                }
                            ):
                                pass
                        for _method, _target, body in UpstreamHandler.calls:
                            forwarded = json.loads(body)
                            self.assertEqual(
                                forwarded["sources"][-1]["id"],
                                "crash-cap:microsoft",
                            )
        finally:
            self.gateway.public_miss_registry = prior_registry

    def test_completed_poll_response_is_recorded(self) -> None:
        module = {
            "type": "pe",
            "code_file": "C:\\Windows\\System32\\poll.dll",
            "code_id": "1234",
            "debug_file": "poll.pdb",
            "debug_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee-1",
        }
        missing_module = {**module, "debug_status": "missing"}
        prior_registry = self.gateway.public_miss_registry
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                registry = GATEWAY.PublicSymbolMissRegistry(
                    str(Path(temp_dir) / "public-misses.jsonl")
                )
                self.gateway.public_miss_registry = registry
                UpstreamHandler.response_payload = {
                    "status": "pending",
                    "request_id": "0123456789abcdef",
                }
                with self.post(
                    {
                        "platform": "native",
                        "stacktraces": [],
                        "modules": [module],
                    }
                ):
                    pass
                self.assertFalse(registry.contains(module))

                UpstreamHandler.get_response_payload = {
                    "status": "completed",
                    "modules": [missing_module],
                }
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.gateway.server_port}/requests/0123456789abcdef",
                    timeout=2,
                ):
                    pass
                self.assertTrue(registry.contains(module))
        finally:
            self.gateway.public_miss_registry = prior_registry

    def test_inventory_version_is_required_and_bounded(self) -> None:
        for query in (
            "scope=wsp_test",
            "scope=wsp_test&inventory=-1",
            "scope=wsp_test&inventory=9223372036854775808",
        ):
            with self.subTest(query=query):
                request = urllib.request.Request(
                    f"http://127.0.0.1:{self.gateway.server_port}/symbolicate?{query}",
                    data=b"",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=2)
                with raised.exception as error_response:
                    self.assertEqual(error_response.code, 400)
                    error_response.read()
        self.assertEqual(UpstreamHandler.calls, [])

    def test_request_owned_source_is_rejected_before_upstream(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.post(
                {
                    "platform": "native",
                    "stacktraces": [],
                    "modules": [],
                    "sources": [
                        {"type": "http", "id": "evil", "url": "https://example.test"}
                    ],
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
