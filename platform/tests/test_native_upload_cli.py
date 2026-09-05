"""Native CLI HTTP contract tests. The server double does not validate PE/PDB bytes."""

import hashlib
import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLI = (
    ROOT
    / "tools/crashcap"
    / ("windows-x86_64/crashcap.exe" if os.name == "nt" else "linux-x86_64/crashcap")
)


@pytest.fixture
def endpoint():
    uploads = {}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, value):
            body = json.dumps(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            requests.append(("GET", self.path))
            if self.path == "/api/v3/workspaces":
                return self.reply(200, [{"id": "wsp_exact", "name": "exact-name"}])
            uid = self.path.rsplit("/", 1)[-1]
            row = uploads[uid]
            self.reply(
                200,
                {
                    "upload_id": uid,
                    "status": "REJECTED" if row["filename"] == "bad.dll" else "ACCEPTED",
                    "verification_status": "REJECTED"
                    if row["filename"] == "bad.dll"
                    else "ACCEPTED",
                    "workspace_id": row["workspace_id"],
                    "availability": "waiting_for_pair",
                    "artifact_entry_id": "art_" + uid,
                    "version_conflict": False,
                    "rejection_reason": "invalid_format" if row["filename"] == "bad.dll" else None,
                },
            )

        def do_POST(self):
            requests.append(("POST", self.path))
            data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            if self.path == "/api/v3/uploads:init":
                uid = f"upl_{len(uploads)}"
                uploads[uid] = data
                return self.reply(
                    201,
                    {
                        "upload_id": uid,
                        "method": "PUT",
                        "url": f"http://127.0.0.1:{self.server.server_port}/object/{uid}?token=secret-signed-url",
                        "headers": {},
                        "expires_in": 900,
                    },
                )
            uid = self.path.rsplit("/", 1)[-1].split(":")[0]
            self.reply(
                200,
                {
                    "upload_id": uid,
                    "status": "VERIFYING",
                    "verification_status": "VERIFYING",
                    "version_conflict": False,
                },
            )

        def do_PUT(self):
            uid = self.path.split("?")[0].rsplit("/", 1)[-1]
            data = self.rfile.read(int(self.headers["Content-Length"]))
            assert hashlib.sha256(data).hexdigest() == uploads[uid]["sha256"]
            assert len(data) == uploads[uid]["size"]
            self.reply(200, {})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/api/v3", uploads, requests
    finally:
        print("CLI API requests:", requests)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def invoke(tmp_path, url, *args):
    if not CLI.is_file():
        pytest.skip("build the native release first")
    return subprocess.run(  # noqa: S603 - invokes the repository's native CLI against an owned server
        [
            str(CLI),
            "upload",
            *map(str, args),
            "--api-url",
            url,
            "--json",
            "--receipt",
            str(tmp_path / "receipt.json"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )


def test_recursive_batch_preserves_successes_and_errors_and_replays(tmp_path, endpoint):
    url, uploads, _requests = endpoint
    (tmp_path / "nested").mkdir()
    (tmp_path / "alone.pdb").write_bytes(b"stub PDB payload")
    (tmp_path / "nested/bad.dll").write_bytes(b"bad DLL payload")
    (tmp_path / "ignored.txt").write_text("ignored")
    result = invoke(
        tmp_path, url, tmp_path, "--workspace", "exact-name", "--build-version", "sdk-1"
    )
    assert result.returncode != 0, result.stdout
    receipt = json.loads((tmp_path / "receipt.json").read_text())
    assert receipt["succeeded"] == receipt["failed"] == 1
    assert receipt["target"] == {"workspace_id": "wsp_exact", "public": False}
    assert receipt["version"] == "sdk-1"
    assert len(uploads) == 2 and all(row["version"] == "sdk-1" for row in uploads.values())
    assert any(row.get("ok") for row in receipt["files"])
    assert all(row.get("links", {}).get("upload", "").startswith(url) for row in receipt["files"])
    assert "secret-signed-url" not in json.dumps(receipt)
    assert "build_id" not in json.dumps(receipt) and "sealed" not in json.dumps(receipt)
    again = invoke(tmp_path, url, tmp_path / "alone.pdb", "--public")
    assert again.returncode == 0, again.stderr
    assert json.loads(again.stdout)["succeeded"] == 1


def test_public_dump_preflight_and_unknown_workspace_upload_nothing(tmp_path, endpoint):
    url, uploads, requests = endpoint
    dmp = tmp_path / "crash.dmp"
    dmp.write_bytes(b"MDMP")
    pdb = tmp_path / "alone.pdb"
    pdb.write_bytes(b"PDB")
    result = invoke(tmp_path, url, dmp, pdb, "--public")
    assert result.returncode != 0 and not requests
    result = invoke(tmp_path, url, pdb, "--workspace", "exact")
    assert result.returncode != 0 and not uploads
    assert "not found" in (result.stderr + result.stdout)
