from __future__ import annotations

import copy
import hashlib
import os
from datetime import timedelta
from pathlib import Path

import pytest
from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.contracts import validate_contract, validate_task_message
from crashcap_api.errors import ApiError
from crashcap_api.models import (
    CatalogPair,
    CatalogPairOrigin,
    SymbolImport,
    SymbolImportAttempt,
    SymbolImportFile,
    SymbolImportItem,
    TaskExecution,
    TaskIntent,
    utcnow,
)
from crashcap_api.services.symbol_imports import complete_item
from crashcap_api.task_handoff import claim_task, heartbeat_claim, poison_task_delivery
from crashcap_worker.core_runner import CoreExecutionError
from crashcap_worker.outbox_relay import relay_once
from crashcap_worker.symbol_imports import recover_imports
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "target/debug" / ("dmp-core.exe" if os.name == "nt" else "dmp-core")
FIXTURE = ROOT / "fixtures/p0-b01-null-read/generated"
PAIR = "b7adb5332314fca1f7abad0666c426c5d04d7821046828271b92216a2dd13853"


def claim(kind, data):
    return {
        "name": "module." + kind,
        "raw_sha256": hashlib.sha256(data).hexdigest(),
        "raw_size": len(data),
    }


def request_for(pairs, key="one-import"):
    return {
        "idempotency_key": key,
        "source_label": "QA 独立导入",
        "pairs": [
            {"client_pair_id": str(index), "pe": claim("pe", pe), "pdb": claim("pdb", pdb)}
            for index, (pe, pdb) in enumerate(pairs)
        ],
    }


@pytest.fixture
def imports(tmp_path):
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "symbol_imports_enabled": True,
            "core_executor": "local",
            "core_command": str(CORE),
            "task_handoff_mode": "outbox",
            "task_receipt_mode": "strict",
        }
    )
    settings = Settings.model_validate(settings.model_dump())
    app = create_app(settings)
    with TestClient(app) as client:
        yield app, client, settings


def create_and_stage(imports, pairs, key="one-import"):
    app, client, settings = imports
    response = client.post("/api/v2/symbol-imports", json=request_for(pairs, key))
    assert response.status_code == 201, response.text
    batch = response.json()
    validate_contract(
        batch,
        settings.schema_root / "drafts/qa-symbol-import/symbol-import-result-v1.schema.json",
        "import result",
    )
    for item, (pe, pdb) in zip(batch["items"], pairs, strict=True):
        path = f"/api/v2/symbol-imports/{batch['import_id']}/items/{item['item_id']}"
        for kind, data in (("pe", pe), ("pdb", pdb)):
            response = client.put(path + "/files/" + kind, content=data)
            assert response.status_code == 200, response.text
        response = client.post(path + "/complete")
        assert response.status_code == 202, response.text
    assert not app.state.dispatcher.messages  # API committed only; relay owns publication.
    return batch


def drain(imports):
    app, _, settings = imports
    while relay_once(
        app.state.database.sessions, app.state.dispatcher, settings, owner_id="test-relay"
    ):
        pass
    app.state.dispatcher.drain()


def states(imports, batch):
    return imports[1].get("/api/v2/symbol-imports/" + batch["import_id"]).json()["items"]


def test_default_off_and_configuration_requires_real_core_strict_outbox(tmp_path):
    settings = Settings.for_test(tmp_path)
    with TestClient(create_app(settings)) as client:
        response = client.post("/api/v2/symbol-imports", json=request_for([(b"pe", b"pdb")]))
        assert response.status_code == 503
    for overrides in (
        {},
        {"core_executor": "local"},
        {"core_executor": "local", "task_handoff_mode": "outbox"},
    ):
        with pytest.raises(ValidationError):
            Settings.model_validate(
                {**settings.model_dump(), "symbol_imports_enabled": True, **overrides}
            )


def test_pair_staging_idempotency_and_immutable_binding(imports):
    app, client, _ = imports
    payload = request_for([(b"pe", b"pdb")])
    response = client.post("/api/v2/symbol-imports", json=payload)
    batch = response.json()
    assert response.status_code == 201
    same = client.post("/api/v2/symbol-imports", json=payload)
    assert same.status_code == 200 and same.json() == batch
    changed = copy.deepcopy(payload)
    changed["source_label"] = "different"
    assert client.post("/api/v2/symbol-imports", json=changed).status_code == 409
    item = batch["items"][0]
    path = f"/api/v2/symbol-imports/{batch['import_id']}/items/{item['item_id']}"
    assert client.put(path + "/files/pe", content=b"xx").status_code == 422
    assert client.put(path + "/files/pe", content=b"pe").status_code == 200
    assert client.post(path + "/complete").status_code == 409
    assert (
        client.put(
            path.replace(batch["import_id"], "wrong") + "/files/pdb", content=b"pdb"
        ).status_code
        == 404
    )
    assert client.put(path + "/files/pdb", content=b"pdb").status_code == 200
    assert client.post(path + "/complete").status_code == 202
    with app.state.database.sessions() as session:
        keys = {file.id: file.object_key for file in session.scalars(select(SymbolImportFile))}
    assert client.put(path + "/files/pe", content=b"pe").status_code == 200
    assert client.put(path + "/files/pdb", content=b"bad").status_code == 422
    assert client.post(path + "/complete").status_code == 202
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(TaskIntent)) == 1
        assert session.scalar(select(func.count()).select_from(SymbolImportAttempt)) == 1
        assert {
            file.id: file.object_key for file in session.scalars(select(SymbolImportFile))
        } == keys
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 0
    # Existing results remain readable after writes are disabled.
    app.state.settings.symbol_imports_enabled = False
    assert client.get("/api/v2/symbol-imports/" + batch["import_id"]).status_code == 200
    assert client.post(path + "/complete").status_code == 503


def test_duplicate_pair_ids_sizes_and_draft_consumers_rejected(imports):
    app, client, settings = imports
    body = request_for([(b"pe", b"pdb"), (b"pe", b"pdb")])
    body["pairs"][1]["client_pair_id"] = "0"
    assert client.post("/api/v2/symbol-imports", json=body).status_code == 422
    body["pairs"].pop()
    body["pairs"][0]["pdb"]["raw_size"] = 2**31 + 1
    assert client.post("/api/v2/symbol-imports", json=body).status_code == 413
    body["pairs"][0]["pdb"]["raw_size"] = 3
    body["pairs"][0]["pe"]["raw_size"] = 512 * 1024**2 + 1
    assert client.post("/api/v2/symbol-imports", json=body).status_code == 413
    frozen = {
        "schema_version": "1.2",
        "task_type": "analyze_frozen_run",
        "run_id": "r",
        "attempt_id": "a",
        "queue": "dump-small",
    }
    validate_task_message(frozen, settings.schema_root)
    with pytest.raises(ApiError, match="consumer is not implemented"):
        validate_task_message({**frozen, "task_type": "plan_analysis_demand"}, settings.schema_root)
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SymbolImport)) == 0


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("QAI_IMPORT_REAL"), reason="requires explicit real Core import qualification"
)
def test_real_core_mixed_batch_duplicate_delivery_and_cross_import_merge(imports):
    assert CORE.is_file(), "Real Core binary is required for the import qualification"
    pe = (FIXTURE / "null_read_target.exe").read_bytes()
    pdb = (FIXTURE / "null_read_target.pdb").read_bytes()
    app, _, _ = imports
    batch = create_and_stage(imports, [(pe, pdb), (pe, b"broken PDB")])
    with app.state.database.sessions() as session:
        messages = [dict(intent.message) for intent in session.scalars(select(TaskIntent))]
    drain(imports)
    result = states(imports, batch)
    assert [item["state"] for item in result] == ["available", "rejected"], result
    assert result[0]["pair_id"] == PAIR
    for message in messages * 2:
        app.state.processor.verify_symbol_import_pair(message)
    other = create_and_stage(imports, [(pe, pdb)], key="second-independent-import")
    drain(imports)
    assert states(imports, other)[0]["pair_id"] == PAIR
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 1
        origins = session.scalars(select(CatalogPairOrigin)).all()
        assert len(origins) == 2
        assert all(
            origin.source_workspace_id is None and origin.build_id is None for origin in origins
        )
        assert len(session.scalars(select(SymbolImportAttempt)).all()) == 3


def test_transient_failures_use_new_attempts_backoff_and_finite_budget(imports, monkeypatch):
    app, _, _ = imports
    batch = create_and_stage(imports, [(b"pe", b"pdb")])
    calls = []

    def failed(*_args):
        calls.append(1)
        raise CoreExecutionError("CORE_EXECUTION_TIMEOUT", "simulated timeout")

    monkeypatch.setattr("crashcap_worker.symbol_imports.prepare_catalog_pair", failed)
    drain(imports)
    for ordinal in (2, 3):
        with app.state.database.sessions() as session:
            attempt = session.scalar(
                select(SymbolImportAttempt).where(SymbolImportAttempt.ordinal == ordinal)
            )
            intent = session.get(TaskIntent, attempt.id)
            message = dict(intent.message)
        app.state.processor.verify_symbol_import_pair(message)  # Cannot skip due_at.
        assert len(calls) == ordinal - 1
        with app.state.database.sessions.begin() as session:
            session.get(TaskIntent, attempt.id).due_at = utcnow() - timedelta(seconds=1)
        drain(imports)
    assert states(imports, batch)[0]["state"] == "retry_exhausted"
    assert len(calls) == 3
    with app.state.database.sessions() as session:
        attempts = session.scalars(
            select(SymbolImportAttempt).order_by(SymbolImportAttempt.ordinal)
        ).all()
        assert [attempt.state for attempt in attempts] == ["failed", "failed", "exhausted"]
        assert len({attempt.id for attempt in attempts}) == 3
        messages = [dict(intent.message) for intent in session.scalars(select(TaskIntent))]
    for message in messages:
        app.state.processor.verify_symbol_import_pair(message)
    assert len(calls) == 3


def test_catalog_commit_is_fenced_after_lease_loss_and_recovery(imports, monkeypatch):
    app, _, settings = imports
    batch = create_and_stage(imports, [(b"pe", b"pdb")])
    stale = []

    def expire(*_args):
        with app.state.database.sessions.begin() as session:
            execution = session.scalars(select(TaskExecution)).one()
            execution.lease_until = utcnow() - timedelta(seconds=1)
            stale.append((execution.generation, execution.owner_id))
        assert recover_imports(app.state.database.sessions, settings) == 1
        # Result never reaches admission, even if the old worker finishes now.
        return object()

    monkeypatch.setattr("crashcap_worker.symbol_imports.prepare_catalog_pair", expire)
    drain(imports)
    assert states(imports, batch)[0]["state"] == "queued"
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 0
        assert session.scalar(select(func.count()).select_from(SymbolImportAttempt)) == 2
        old = session.scalar(select(SymbolImportAttempt).where(SymbolImportAttempt.ordinal == 1))
        assert old.state == "failed" and old.error_code == "IMPORT_EXECUTION_LEASE_LOST"


def test_lost_delivery_and_worker_crash_recovered_without_duplicate_admission(imports):
    app, _, settings = imports
    create_and_stage(imports, [(b"pe", b"pdb")])
    assert relay_once(app.state.database.sessions, app.state.dispatcher, settings, owner_id="relay")
    message = app.state.dispatcher.messages.popleft()  # Simulate Redis acknowledgement then loss.
    with app.state.database.sessions.begin() as session:
        session.get(TaskIntent, message["attempt_id"]).published_at = utcnow() - timedelta(hours=1)
    assert recover_imports(app.state.database.sessions, settings) == 1
    with app.state.database.sessions.begin() as session:
        owned = claim_task(session, message, settings.schema_root, receipt_mode="strict")
        item = session.get(SymbolImportItem, message["item_id"])
        attempt = session.get(SymbolImportAttempt, message["attempt_id"])
        item.state, attempt.state = "verifying", "running"
        session.get(TaskExecution, (owned.task_type, owned.logical_key)).lease_until = (
            utcnow() - timedelta(seconds=1)
        )
    assert recover_imports(app.state.database.sessions, settings) == 1
    with app.state.database.sessions.begin() as session:
        assert not heartbeat_claim(session, owned, lease_seconds=30)
        assert session.scalar(select(func.count()).select_from(SymbolImportAttempt)) == 2


def test_complete_transaction_rollback_leaves_no_outbox_intent(imports):
    app, client, settings = imports
    body = request_for([(b"pe", b"pdb")])
    batch = client.post("/api/v2/symbol-imports", json=body).json()
    item_id = batch["items"][0]["item_id"]
    path = f"/api/v2/symbol-imports/{batch['import_id']}/items/{item_id}"
    for kind, data in (("pe", b"pe"), ("pdb", b"pdb")):
        assert client.put(path + "/files/" + kind, content=data).status_code == 200
    with app.state.database.sessions() as session:
        complete_item(session, settings, batch["import_id"], item_id)
        session.rollback()
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(TaskIntent)) == 0
        assert session.get(SymbolImportItem, item_id).state == "staging"


def test_staged_bytes_changed_after_complete_never_reach_validator(imports, monkeypatch):
    app, _, _ = imports
    batch = create_and_stage(imports, [(b"pe", b"pdb")])
    with app.state.database.sessions() as session:
        file = session.scalar(select(SymbolImportFile).where(SymbolImportFile.kind == "pdb"))
        app.state.store.put_bytes(
            file.object_key, b"changed and larger", "application/octet-stream"
        )

    def forbidden(*_args):
        pytest.fail("Changed staging must never reach the real validator")

    monkeypatch.setattr("crashcap_worker.symbol_imports.prepare_catalog_pair", forbidden)
    drain(imports)
    result = states(imports, batch)[0]
    assert result["state"] == "queued" and result["error_code"] == "IMPORT_STAGING_CHANGED"
    assert result["pair_id"] is None


def test_upload_readback_and_chunked_size_are_verified_before_binding(imports, monkeypatch):
    app, client, _ = imports
    body = request_for([(b"pe", b"pdb")])
    batch = client.post("/api/v2/symbol-imports", json=body).json()
    item_id = batch["items"][0]["item_id"]
    path = f"/api/v2/symbol-imports/{batch['import_id']}/items/{item_id}"
    assert client.put(path + "/files/pe", content=iter([b"pe", b"extra"])).status_code == 422
    monkeypatch.setattr(app.state.store, "stream", lambda *_args: iter([b"xx"]))
    assert client.put(path + "/files/pe", content=b"pe").status_code == 503
    with app.state.database.sessions() as session:
        assert all(file.object_key is None for file in session.scalars(select(SymbolImportFile)))
        assert session.scalar(select(func.count()).select_from(TaskIntent)) == 0


def test_poisoned_delivery_is_terminal_and_does_not_strand_queued_item(imports):
    app, _, settings = imports
    batch = create_and_stage(imports, [(b"pe", b"pdb")])
    with app.state.database.sessions.begin() as session:
        message = dict(session.scalars(select(TaskIntent)).one().message)
        assert poison_task_delivery(session, message, "PERMANENT_VALIDATION")
    app.state.processor.verify_symbol_import_pair(message)
    assert recover_imports(app.state.database.sessions, settings) == 1
    result = states(imports, batch)[0]
    assert result["state"] == "rejected" and result["error_code"] == "IMPORT_TASK_DEAD"
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(SymbolImportAttempt)) == 1
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 0
