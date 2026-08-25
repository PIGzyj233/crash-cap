from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class PublisherServerState:
    address: str = ""
    inventory: list[dict[str, Any]] = field(default_factory=list)
    publications: dict[tuple[str, str], str] = field(default_factory=dict)
    accepted: set[tuple[str, str]] = field(default_factory=set)
    uploads: dict[str, tuple[str, str]] = field(default_factory=dict)
    multipart_uploads: dict[str, int] = field(default_factory=dict)
    multipart_payloads: dict[str, dict[int, bytes]] = field(default_factory=dict)
    fail_first_pdb_part: bool = True
    pdb_failure_consumed: bool = False
    put_count: int = 0
    registration_count: int = 0

    def summary(self, body: dict[str, Any], publication_id: str) -> dict[str, Any]:
        return {
            "id": publication_id,
            "workspace_id": "wsp_native_e2e",
            "build_id": "bld_shared_content",
            "origin": body["origin"],
            "client_publication_id": body["client_publication_id"],
            "client_version": body["client_version"],
            "git_revision": body["git"]["revision"],
            "git_worktree_state": body["git"]["worktree_state"],
            "created_at": "2026-08-25T00:00:00+00:00",
            "last_seen_at": "2026-08-25T00:00:00+00:00",
        }

    def response(self, body: dict[str, Any], publication_id: str) -> dict[str, Any]:
        expectations = []
        for item in self.inventory:
            key = (item["kind"], item["logical_name"].casefold())
            verified = key in self.accepted
            expectations.append(
                {
                    "module_id": "mod_native_e2e",
                    "module_code_file": item["module_code_file"],
                    "kind": item["kind"],
                    "logical_name": item["logical_name"],
                    "size": item["size"],
                    "sha256": item["sha256"],
                    "status": "verified" if verified else "missing",
                    "artifact_id": f"art_{item['kind']}" if verified else None,
                    "upload_id": None,
                    "rejection_reason": None,
                }
            )
        ready = bool(expectations) and all(item["status"] == "verified" for item in expectations)
        summaries = [
            self.summary(
                {
                    **body,
                    "origin": origin,
                    "client_publication_id": client_id,
                },
                pub_id,
            )
            for (origin, client_id), pub_id in self.publications.items()
        ]
        return {
            "publication": self.summary(body, publication_id),
            "publications": summaries,
            "build_id": "bld_shared_content",
            "identity_mode": "content_v1",
            "fingerprint_version": "build-content-v1",
            "content_fingerprint": "f" * 64,
            "status": "ready" if ready else "registered",
            "sealed_at": "2026-08-25T00:01:00+00:00" if ready else None,
            "expected_artifacts": expectations,
            "missing_artifacts": [item for item in expectations if item["status"] != "verified"],
            "rejected_artifacts": [],
            "ready": ready,
        }


class PublisherHTTPServer(ThreadingHTTPServer):
    publisher_state: PublisherServerState


class PublisherHandler(BaseHTTPRequestHandler):
    server: PublisherHTTPServer

    def log_message(self, _format: str, *args: object) -> None:
        del args

    @property
    def state(self) -> PublisherServerState:
        return self.server.publisher_state

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length) or b"{}")

    def send_json(self, status: int, body: Any) -> None:
        payload = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/v1/workspaces":
            self.send_json(200, [{"id": "wsp_native_e2e", "name": "native-e2e"}])
            return
        if self.path == "/api/v1/artifact-producers":
            self.send_json(
                200,
                [
                    {
                        "producer": "msvc",
                        "status": "supported",
                        "publication_contracts": ["1.0"],
                        "minimum_client_version": "1.0.0",
                        "build_publications_enabled": True,
                    }
                ],
            )
            return
        if self.path.startswith("/api/v1/uploads/"):
            upload_id = self.path.rsplit("/", 1)[-1]
            status = (
                "ACCEPTED" if self.state.uploads[upload_id] in self.state.accepted else "REJECTED"
            )
            self.send_json(
                200,
                {
                    "upload_id": upload_id,
                    "status": status,
                    "verification_status": status,
                    "rejection_reason": None,
                },
            )
            return
        if self.path.startswith("/api/v1/build-publications/"):
            publication_id = self.path.rsplit("/", 1)[-1]
            key = next(
                key for key, value in self.state.publications.items() if value == publication_id
            )
            body = {
                "origin": key[0],
                "client_publication_id": key[1],
                "client_version": "crashcap/1.0.0",
                "git": {"revision": None, "worktree_state": "unknown"},
            }
            self.send_json(200, self.state.response(body, publication_id))
            return
        self.send_json(404, {"error": {"code": "NOT_FOUND", "message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/api/v1/workspaces/wsp_native_e2e/build-publications":
            body = self.read_json()
            self.state.registration_count += 1
            if not self.state.inventory:
                self.state.inventory = body["artifacts"]
            else:
                assert body["artifacts"] == self.state.inventory
            key = (body["origin"], body["client_publication_id"])
            publication_id = self.state.publications.setdefault(
                key, f"pub_{body['origin']}_native_e2e"
            )
            self.send_json(201, self.state.response(body, publication_id))
            return
        if self.path == "/api/v1/builds/bld_shared_content/artifacts/uploads:init":
            body = self.read_json()
            expected = next(
                item
                for item in self.state.inventory
                if item["kind"] == body["file_kind"]
                and item["logical_name"].casefold() == body["filename"].casefold()
            )
            assert body["size"] == expected["size"]
            assert body["sha256"] == expected["sha256"]
            upload_id = f"upl_{body['file_kind']}_{len(self.state.uploads)}"
            self.state.uploads[upload_id] = (body["file_kind"], body["filename"].casefold())
            multipart = None
            url = f"http://{self.state.address}/objects/{upload_id}"
            if body["file_kind"] == "pdb":
                part_size = max(1, (body["size"] + 1) // 2)
                part_count = (body["size"] + part_size - 1) // part_size
                self.state.multipart_uploads[upload_id] = part_size
                self.state.multipart_payloads[upload_id] = {}
                multipart = {
                    "upload_id": f"s3-{upload_id}",
                    "part_size": part_size,
                    "parts": [
                        {
                            "part_number": number,
                            "url": f"http://{self.state.address}/objects/{upload_id}/parts/{number}",
                        }
                        for number in range(1, part_count + 1)
                    ],
                }
                url = ""
            self.send_json(
                201,
                {
                    "upload_id": upload_id,
                    "method": "PUT",
                    "url": url,
                    "headers": {"Content-Type": "application/octet-stream"},
                    "expires_in": 900,
                    "multipart": multipart,
                },
            )
            return
        if self.path.startswith("/api/v1/uploads/") and self.path.endswith("/complete"):
            body = self.read_json()
            upload_id = self.path.split("/")[-2]
            kind, logical_name = self.state.uploads[upload_id]
            if upload_id in self.state.multipart_uploads:
                assert body["multipart_upload_id"] == f"s3-{upload_id}"
                part_numbers = [item["part_number"] for item in body["parts"]]
                assert part_numbers == list(range(1, len(part_numbers) + 1))
                payload = b"".join(
                    self.state.multipart_payloads[upload_id][number] for number in part_numbers
                )
                expected = next(
                    item
                    for item in self.state.inventory
                    if (item["kind"], item["logical_name"].casefold()) == (kind, logical_name)
                )
                assert len(payload) == expected["size"]
                assert hashlib.sha256(payload).hexdigest() == expected["sha256"]
            self.state.accepted.add((kind, logical_name))
            self.send_json(
                200,
                {
                    "upload_id": upload_id,
                    "status": "VERIFYING",
                    "verification_status": "VERIFYING",
                    "rejection_reason": None,
                },
            )
            return
        self.send_json(404, {"error": {"code": "NOT_FOUND", "message": "not found"}})

    def do_PUT(self) -> None:  # noqa: N802
        segments = self.path.strip("/").split("/")
        upload_id = segments[1]
        part_number = int(segments[3]) if len(segments) == 4 else None
        expected = next(
            item
            for item in self.state.inventory
            if (item["kind"], item["logical_name"].casefold()) == self.state.uploads[upload_id]
        )
        remaining = int(self.headers["Content-Length"])
        digest = hashlib.sha256()
        payload = bytearray()
        total = 0
        while remaining:
            chunk = self.rfile.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            digest.update(chunk)
            if part_number is not None:
                payload.extend(chunk)
            total += len(chunk)
            remaining -= len(chunk)
        if part_number is not None:
            part_size = self.state.multipart_uploads[upload_id]
            offset = (part_number - 1) * part_size
            assert total == min(part_size, expected["size"] - offset)
            if (
                expected["kind"] == "pdb"
                and self.state.fail_first_pdb_part
                and not self.state.pdb_failure_consumed
            ):
                self.state.pdb_failure_consumed = True
                self.send_response(403)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.state.multipart_payloads[upload_id][part_number] = bytes(payload)
        else:
            assert total == expected["size"]
            assert digest.hexdigest() == expected["sha256"]
        self.state.put_count += 1
        self.send_response(200)
        self.send_header("ETag", f'"{upload_id}"')
        self.send_header("Content-Length", "0")
        self.end_headers()


def _publisher_binary() -> Path:
    if os.name == "nt":
        return ROOT / "tools" / "crashcap" / "windows-x86_64" / "crashcap.exe"
    return ROOT / "tools" / "crashcap" / "linux-x86_64" / "crashcap"


def test_checked_in_native_cli_publishes_replays_and_keeps_receipt_safe(tmp_path: Path) -> None:
    fixture_root = ROOT / "fixtures" / ".build" / "golden"
    code_fixture = fixture_root / "golden_target_release.exe"
    debug_fixture = fixture_root / "golden_target_release.pdb"
    if not code_fixture.is_file() or not debug_fixture.is_file():
        pytest.skip("build the Phase 0 native fixtures before the native publisher E2E gate")

    output = tmp_path / "out"
    output.mkdir()
    shutil.copy2(code_fixture, output / code_fixture.name)
    shutil.copy2(debug_fixture, output / debug_fixture.name)
    for arguments in (
        ["git", "init", "--quiet"],
        ["git", "config", "user.email", "native-e2e@crash-cap.invalid"],
        ["git", "config", "user.name", "Crash-Cap Native E2E"],
        ["git", "add", "out"],
        ["git", "commit", "--quiet", "-m", "native fixtures"],
    ):
        completed = subprocess.run(  # noqa: S603,S607 - isolated disposable Git repository
            arguments,
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
    config = tmp_path / "crashcap.toml"
    state = PublisherServerState()
    server = PublisherHTTPServer(("127.0.0.1", 0), PublisherHandler)
    state.address = f"127.0.0.1:{server.server_port}"
    server.publisher_state = state
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    receipt = tmp_path / "crashcap-publication.json"

    initialized = subprocess.run(  # noqa: S603 - runs the checked-in native gate binary
        [
            str(_publisher_binary()),
            "--api-url",
            f"http://{state.address}/api/v1",
            "--config",
            str(config),
            "--json",
            "init",
            "--workspace",
            "native-e2e",
            "--artifact-root",
            "out",
            "--profile",
            "release",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert initialized.returncode == 0, initialized.stderr
    assert json.loads(initialized.stdout)["module_count"] == 1
    assert config.is_file()

    def publish(
        origin: str, *, succeeds: bool = True
    ) -> dict[str, Any] | subprocess.CompletedProcess[str]:
        completed = subprocess.run(  # noqa: S603 - runs the checked-in native gate binary
            [
                str(_publisher_binary()),
                "--api-url",
                f"http://{state.address}/api/v1",
                "--config",
                str(config),
                "--json",
                "publish",
                "--profile",
                "release",
                "--origin",
                origin,
                "--wait-seconds",
                "10",
                "--receipt",
                str(receipt),
            ],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
        )
        if succeeds:
            assert completed.returncode == 0, completed.stderr
            return json.loads(completed.stdout)
        assert completed.returncode == 2
        assert "object upload part 1 failed (403)" in completed.stderr
        return completed

    try:
        publish("local", succeeds=False)
        assert len([key for key in state.publications if key[0] == "local"]) == 1
        first = publish("local")
        first_put_count = state.put_count
        replay = publish("local")
        ci = publish("ci")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert first["ready"] is replay["ready"] is ci["ready"] is True
    assert first["build_id"] == replay["build_id"] == ci["build_id"]
    assert first["publication"]["id"] == replay["publication"]["id"]
    assert first["publication"]["id"] != ci["publication"]["id"]
    assert first_put_count == 3  # one PE plus two successful PDB parts after interruption
    assert state.put_count == first_put_count
    assert state.registration_count == 4
    assert len([key for key in state.publications if key[0] == "local"]) == 1

    receipt_text = receipt.read_text(encoding="utf-8")
    receipt_payload = json.loads(receipt_text)
    assert receipt_payload["git"]["worktree_state"] == "dirty"
    assert receipt_payload["warnings"] == ["git_worktree_dirty"]
    assert str(tmp_path) not in receipt_text
    assert "http://" not in receipt_text
    assert "presigned" not in receipt_text.casefold()
    assert "credential" not in receipt_text.casefold()
