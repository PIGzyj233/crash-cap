from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import pytest
from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.models import Upload
from fastapi import FastAPI
from fastapi.testclient import TestClient


@dataclass
class Phase1Harness:
    client: TestClient
    app: FastAPI
    settings: Settings

    def create_workspace(self, name: str) -> dict[str, Any]:
        response = self.client.post(
            "/api/v3/workspaces",
            json={"name": name, "display_name": name.replace("-", " ").title()},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def initialize_dump(
        self,
        workspace_id: str,
        payload: bytes,
        *,
        capture_profile: str = "rich-crash",
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "filename": "crash.dmp",
            "size": len(payload),
            "file_kind": "dmp",
            "workspace_id": workspace_id,
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        initialized = self.client.post("/api/v3/uploads:init", json=body)
        assert initialized.status_code == 201, initialized.text
        upload = initialized.json()
        self._seed_upload(upload["upload_id"], payload)
        completed = self.client.post(f"/api/v3/uploads/{upload['upload_id']}:complete", json={})
        assert completed.status_code == 200, completed.text
        return upload

    def upload_dump(
        self,
        workspace_id: str,
        payload: bytes,
        *,
        capture_profile: str = "rich-crash",
    ) -> dict[str, Any]:
        upload = self.initialize_dump(
            workspace_id,
            payload,
            capture_profile=capture_profile,
        )
        self.drain()
        terminal = self.client.get(f"/api/v3/uploads/{upload['upload_id']}")
        assert terminal.status_code == 200, terminal.text
        assert terminal.json()["verification_status"] == "ACCEPTED"
        return terminal.json()

    def drain(self) -> int:
        from crashcap_worker.outbox_relay import relay_once

        while relay_once(
            self.app.state.database.sessions,
            self.app.state.dispatcher,
            self.settings,
            owner_id="test-relay",
        ):
            pass
        return int(self.app.state.dispatcher.drain())

    def _seed_upload(self, upload_id: str, payload: bytes) -> None:
        with self.app.state.database.sessions() as session:
            row = session.get(Upload, upload_id)
            assert row is not None
            key = row.object_key
        self.app.state.store.put_bytes(key, payload, "application/octet-stream")


@pytest.fixture
def harness(tmp_path: Any) -> Phase1Harness:
    settings = Settings.for_test(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        yield Phase1Harness(client=client, app=app, settings=settings)


def pe_bytes(debug_id: str) -> bytes:
    payload = bytearray(768)
    payload[0:2] = b"MZ"
    payload[0x3C:0x40] = (0x80).to_bytes(4, "little")
    payload[0x80:0x84] = b"PE\x00\x00"
    payload.extend(f"CRASHCAP_DEBUG_ID={debug_id}".encode())
    return bytes(payload)


def pdb_bytes(debug_id: str, *, fastlink: bool = False) -> bytes:
    marker = f"CRASHCAP_DEBUG_ID={debug_id}".encode()
    suffix = b"CRASHCAP_FASTLINK=1" if fastlink else b""
    return b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\x00\x00\x00" + marker + suffix


def dump_bytes(seed: int) -> bytes:
    return b"MDMP" + seed.to_bytes(8, "little") + bytes([seed % 251]) * 1012
