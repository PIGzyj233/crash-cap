from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.models import Base, CatalogPair, SymbolImport, SymbolImportAttempt, TaskIntent
from crashcap_api.services.symbol_imports import complete_item, create_import
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from . import test_symbol_catalog_postgres as catalog_tests
from . import test_symbol_imports as imports_tests

pg = catalog_tests.pg

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL"
    ),
]


@pytest.fixture
def pg_imports(pg, tmp_path):
    engine, _, _ = pg
    settings = Settings.for_test(
        tmp_path, engine.url.render_as_string(hide_password=False)
    ).model_copy(
        update={
            "symbol_imports_enabled": True,
            "core_executor": "local",
            "core_command": str(imports_tests.CORE),
            "task_handoff_mode": "outbox",
            "task_receipt_mode": "strict",
        }
    )
    settings = Settings.model_validate(settings.model_dump())
    app = create_app(settings)
    with TestClient(app) as client:
        yield app, client, settings


def test_import_schema_roundtrip_and_retained_records_refuse_downgrade(pg, pg_imports):
    engine, sessions, config = pg
    tables = [
        table for table in Base.metadata.sorted_tables if table.name.startswith("symbol_import")
    ]
    assert len(tables) == 4
    for table in tables:
        assert {column["name"] for column in inspect(engine).get_columns(table.name)} == set(
            table.columns.keys()
        )
        assert {
            index["name"]
            for index in inspect(engine).get_indexes(table.name)
            if not index.get("duplicates_constraint")
        } == {index.name for index in table.indexes}
    command.downgrade(config, "0012_global_symbol_catalog")
    assert not set(table.name for table in tables).intersection(inspect(engine).get_table_names())
    command.upgrade(config, "head")
    batch = imports_tests.create_and_stage(pg_imports, [(b"pe", b"pdb")])
    with pytest.raises(RuntimeError, match="Retained symbol import records"):
        command.downgrade(config, "0012_global_symbol_catalog")
    with sessions() as session:
        assert session.get(SymbolImport, batch["import_id"]) is not None
        assert session.scalar(select(func.count()).select_from(SymbolImportAttempt)) == 1


def test_postgres_concurrent_same_key_and_complete_are_one_logical_task(pg, pg_imports):
    _, sessions, _ = pg
    _, client, settings = pg_imports
    payload = imports_tests.request_for([(b"pe", b"pdb")])
    barrier = threading.Barrier(2)

    def create():
        barrier.wait(timeout=5)
        with sessions.begin() as session:
            batch, created = create_import(session, settings, payload)
            return batch.id, created

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(create), pool.submit(create)
        results = [first.result(timeout=10), second.result(timeout=10)]
    assert results[0][0] == results[1][0] and sorted(row[1] for row in results) == [False, True]
    batch = client.get("/api/v2/symbol-imports/" + results[0][0]).json()
    item_id = batch["items"][0]["item_id"]
    path = f"/api/v2/symbol-imports/{batch['import_id']}/items/{item_id}"
    for kind, data in (("pe", b"pe"), ("pdb", b"pdb")):
        assert client.put(path + "/files/" + kind, content=data).status_code == 200
    barrier = threading.Barrier(2)

    def complete():
        barrier.wait(timeout=5)
        with sessions.begin() as session:
            complete_item(session, settings, batch["import_id"], item_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(complete), pool.submit(complete)
        first.result(timeout=10)
        second.result(timeout=10)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SymbolImport)) == 1
        assert session.scalar(select(func.count()).select_from(TaskIntent)) == 1
        assert session.scalar(select(func.count()).select_from(SymbolImportAttempt)) == 1


def test_real_api_pair_validation_merge_and_per_item_failure_postgres(pg_imports):
    imports_tests.test_real_core_mixed_batch_duplicate_delivery_and_cross_import_merge(pg_imports)
    app, _, _ = pg_imports
    with app.state.database.sessions() as session:
        pair = session.scalars(select(CatalogPair)).one()
        attempts = session.scalars(
            select(SymbolImportAttempt).order_by(SymbolImportAttempt.created_at)
        ).all()
        receipt = {
            "status": "PASS",
            "pair_id": pair.id,
            "attempt_states": [attempt.state for attempt in attempts],
            "boundary": (
                "HTTP TestClient + actual local Core + LocalObjectStore + disposable PostgreSQL; "
                "no browser/S3/Redis/target deployment proof"
            ),
        }
    (imports_tests.ROOT / "target/qa-symbol-import/import-real.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )


def test_postgres_commit_fence_after_worker_lease_loss(pg_imports, monkeypatch):
    imports_tests.test_catalog_commit_is_fenced_after_lease_loss_and_recovery(
        pg_imports, monkeypatch
    )


def test_postgres_finite_retry_attempts_and_outbox_rollback(pg_imports, monkeypatch):
    imports_tests.test_transient_failures_use_new_attempts_backoff_and_finite_budget(
        pg_imports, monkeypatch
    )


def test_concurrent_delivery_executes_real_validator_once(pg, pg_imports, monkeypatch):
    from crashcap_worker.catalog_validation import prepare_catalog_pair

    _, sessions, _ = pg
    app, _, _ = pg_imports
    pe = (imports_tests.FIXTURE / "null_read_target.exe").read_bytes()
    pdb = (imports_tests.FIXTURE / "null_read_target.pdb").read_bytes()
    batch = imports_tests.create_and_stage(pg_imports, [(pe, pdb)])
    with sessions() as session:
        message = dict(session.scalars(select(TaskIntent)).one().message)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow(*args):
        calls.append(1)
        entered.set()
        assert release.wait(timeout=10)
        return prepare_catalog_pair(*args)

    monkeypatch.setattr("crashcap_worker.symbol_imports.prepare_catalog_pair", slow)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(app.state.processor.verify_symbol_import_pair, message)
        try:
            assert entered.wait(timeout=10)
            second = pool.submit(app.state.processor.verify_symbol_import_pair, message)
            second.result(timeout=5)
            assert len(calls) == 1
        finally:
            release.set()
        first.result(timeout=60)
    assert imports_tests.states(pg_imports, batch)[0]["pair_id"] == imports_tests.PAIR
    assert len(calls) == 1
