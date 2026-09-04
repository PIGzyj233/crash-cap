from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from alembic import command
from crashcap_api.config import Settings
from crashcap_api.models import CatalogPair, CatalogPairOrigin, SymbolCatalogBackfill
from crashcap_api.services.catalog_backfill import backfill_catalog
from crashcap_api.storage import create_object_store
from crashcap_worker.core_runner import CoreExecutor
from sqlalchemy import func, inspect, select

from . import test_catalog_backfill as history_tests
from . import test_symbol_catalog_postgres as catalog_tests
from .test_symbol_imports import CORE, ROOT

pg = catalog_tests.pg
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL"
    ),
]


@pytest.fixture
def pg_history(pg, tmp_path):
    _, sessions, _ = pg
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "core_executor": "local",
            "core_command": str(CORE),
            "symbol_imports_enabled": True,
            "task_handoff_mode": "outbox",
            "task_receipt_mode": "strict",
        }
    )
    return sessions, create_object_store(settings), CoreExecutor(settings), tmp_path


def test_history_migration_roundtrip_and_evidence_preservation(pg, pg_history):
    engine, sessions, config = pg
    table = SymbolCatalogBackfill.__table__
    assert {column["name"] for column in inspect(engine).get_columns(table.name)} == set(
        table.columns.keys()
    )
    assert {index["name"] for index in inspect(engine).get_indexes(table.name)} == {
        index.name for index in table.indexes
    }
    command.downgrade(config, "0013_symbol_imports")
    assert table.name not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    history_tests.seed(pg_history, bad_pdb=True)
    history_tests.scan(pg_history, apply=True)
    with pytest.raises(RuntimeError, match="Retained catalog backfill outcomes"):
        command.downgrade(config, "0013_symbol_imports")
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(SymbolCatalogBackfill)) == 1


def test_real_history_raw_zstd_publication_and_restart_postgres(pg_history):
    history_tests.test_real_raw_zstd_publication_dry_run_restart_and_no_historical_rewrite(
        pg_history
    )
    sessions, _, _, _ = pg_history
    with sessions() as session:
        records = session.scalars(
            select(SymbolCatalogBackfill).order_by(SymbolCatalogBackfill.id)
        ).all()
        receipt = {
            "status": "PASS",
            "sources": [
                {
                    "locator": row.locator,
                    "outcome": row.outcome,
                    "pair_id": row.pair_id,
                    "attempt_count": row.attempt_count,
                }
                for row in records
            ],
            "old_rows_unchanged": True,
            "dry_run_no_db_or_store_writes": True,
            "boundary": (
                "real local Core, identity/zstd LocalObjectStore and disposable PostgreSQL; "
                "not target data/Redis/S3/browser proof"
            ),
        }
    (ROOT / "target/qa-symbol-import/history-real.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )


def test_postgres_concurrent_history_admission_is_one_pair_and_source(pg_history, monkeypatch):
    from crashcap_api.services import catalog_backfill

    history_tests.seed(pg_history)
    sessions, store, core, _ = pg_history
    original = catalog_backfill.prepare_catalog_pair
    barrier = threading.Barrier(2)

    def together(*args):
        prepared = original(*args)
        barrier.wait(timeout=30)
        return prepared

    monkeypatch.setattr(catalog_backfill, "prepare_catalog_pair", together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(backfill_catalog, sessions, store, core, apply=True)
        second = pool.submit(backfill_catalog, sessions, store, core, apply=True)
        results = [first.result(timeout=60), second.result(timeout=60)]
    assert all(result["cases"][0]["outcome"] == "admitted" for result in results)
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 1
        assert session.scalar(select(func.count()).select_from(CatalogPairOrigin)) == 1
        record = session.scalars(select(SymbolCatalogBackfill)).one()
        assert record.outcome == "admitted" and record.attempt_count == 2


def test_postgres_source_snapshot_fence(pg_history, monkeypatch):
    history_tests.test_source_change_during_io_rejects_stale_admission(pg_history, monkeypatch)
