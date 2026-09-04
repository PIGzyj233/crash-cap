from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from crashcap_api.config import Settings
from crashcap_api.models import (
    Base,
    CatalogChange,
    CatalogPair,
    CatalogPairOrigin,
    CatalogWatermark,
)
from crashcap_api.services.symbol_catalog import admit_pair, candidate_page
from crashcap_api.storage import create_object_store
from crashcap_worker.catalog_validation import prepare_catalog_pair
from crashcap_worker.core_runner import CoreExecutionError, CoreExecutor
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from .test_symbol_catalog import origin, pair_evidence

ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned catalog PostgreSQL"
    ),
]


@pytest.fixture
def pg():
    url = os.environ["QAI_CATALOG_DATABASE_URL"]
    schema = "qai_catalog_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    config = Config(str(ROOT / "platform/migrations/alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "platform/migrations"))
    config.set_main_option(
        "sqlalchemy.url", scoped.render_as_string(hide_password=False).replace("%", "%%")
    )
    engine = create_engine(scoped)
    try:
        command.upgrade(config, "head")
        yield engine, sessionmaker(engine, expire_on_commit=False, autoflush=False), config
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_catalog_migration_matches_models_roundtrips_empty_and_refuses_data_loss(pg):
    engine, sessions, config = pg
    inspector = inspect(engine)
    tables = [t for t in Base.metadata.sorted_tables if t.name.startswith("catalog_")]
    assert len(tables) == 8
    for table in tables:
        assert {c["name"] for c in inspector.get_columns(table.name)} == set(table.columns.keys())
        assert {
            i["name"]
            for i in inspector.get_indexes(table.name)
            if not i.get("duplicates_constraint")
        } == {i.name for i in table.indexes}
    command.downgrade(config, "0011_canonical_dual_reader")
    assert "catalog_pairs" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    with sessions.begin() as session:
        pair_id = admit_pair(session, *pair_evidence(), origin()).id
    with pytest.raises(RuntimeError, match="Retained catalog evidence"):
        command.downgrade(config, "0011_canonical_dual_reader")
    with sessions() as session:
        assert session.get(CatalogPair, pair_id) is not None
        assert session.get(CatalogWatermark, 1).revision == 1
        assert (
            session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "0023_demand_restarts"
        )


@pytest.mark.parametrize("rollback_first", [False, True])
def test_watermark_serializes_commit_order_and_concurrent_same_pair(pg, rollback_first):
    engine, sessions, _ = pg
    ready, release, second_started = threading.Event(), threading.Event(), threading.Event()
    pids = {}

    def first():
        with sessions() as session:
            session.begin()
            admit_pair(session, *pair_evidence(), origin("first"))
            ready.set()
            assert release.wait(10), "coordinator did not release first transaction"
            session.rollback() if rollback_first else session.commit()

    def second():
        assert ready.wait(10)
        with sessions.begin() as session:
            pids["second"] = session.execute(text("SELECT pg_backend_pid()")).scalar_one()
            second_started.set()
            admit_pair(session, *pair_evidence(), origin("second"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(first), pool.submit(second)
        try:
            assert second_started.wait(10)
            deadline = time.monotonic() + 5
            with engine.connect() as connection:
                while True:
                    blocked = connection.execute(
                        text("SELECT cardinality(pg_blocking_pids(:pid))"), {"pid": pids["second"]}
                    ).scalar_one()
                    if blocked:
                        break
                    assert time.monotonic() < deadline, (
                        "second mutation did not take the catalog commit fence"
                    )
                    time.sleep(0.02)
        finally:
            release.set()
        a.result(timeout=10)
        b.result(timeout=10)
    with sessions() as session:
        revisions = list(
            session.scalars(select(CatalogChange.revision).order_by(CatalogChange.revision))
        )
        assert revisions == ([1] if rollback_first else [1, 2])
        assert session.get(CatalogWatermark, 1).revision == len(revisions)
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 1
        assert session.scalar(select(func.count()).select_from(CatalogPairOrigin)) == len(revisions)


def test_real_core_and_local_storage_admit_actual_complete_pair(pg, tmp_path):
    _, sessions, _ = pg
    output = ROOT / "target/qa-symbol-import" / ("catalog-real-" + uuid.uuid4().hex)
    output.mkdir()
    settings = Settings.for_test(output).model_copy(
        update={
            "core_executor": "local",
            "core_command": str(
                ROOT / "target/debug" / ("dmp-core.exe" if os.name == "nt" else "dmp-core")
            ),
        }
    )
    store = create_object_store(settings)
    fixture = ROOT / "fixtures/p0-b01-null-read/generated"
    bad_pdb = output / "bad.pdb"
    bad_pdb.write_bytes(b"invalid PDB format")
    with pytest.raises(CoreExecutionError):
        prepare_catalog_pair(
            CoreExecutor(settings), store, fixture / "null_read_target.exe", bad_pdb
        )
    assert not any(path.is_file() for path in settings.object_store_local_root.rglob("*"))
    prepared = prepare_catalog_pair(
        CoreExecutor(settings),
        store,
        fixture / "null_read_target.exe",
        fixture / "null_read_target.pdb",
    )
    with sessions.begin() as session:
        pair = admit_pair(
            session, prepared.pe, prepared.pdb, prepared.locations, origin("actual-fixture")
        )
        expected_pair = [
            "pair-v1",
            hashlib.sha256((fixture / "null_read_target.exe").read_bytes()).hexdigest(),
            hashlib.sha256((fixture / "null_read_target.pdb").read_bytes()).hexdigest(),
        ]
        assert pair.id == hashlib.sha256(
            json.dumps(expected_pair, separators=(",", ":")).encode()
        ).hexdigest()
        page = candidate_page(session, {"code_id": pair.code_id, "debug_id": pair.debug_id})
        assert len(page.pairs) == 1
    receipt = {
        "status": "PASS",
        "pair_id": pair.id,
        "validator": prepared.pe.validator_version,
        "pe_sha256": prepared.pe.raw_sha256,
        "pdb_sha256": prepared.pdb.raw_sha256,
        "verification_object_key": prepared.pe.verification_object_key,
        "verification_sha256": prepared.pe.verification_sha256,
        "retained_local_objects": str(settings.object_store_local_root),
        "boundary": (
            "actual Core identity and LocalObjectStore readback into disposable PostgreSQL; "
            "no import API/history/planner proof"
        ),
    }
    receipt_path = Path(
        os.getenv(
            "QAI_CATALOG_RECEIPT_OUTPUT",
            str(ROOT / "target/qa-symbol-import/catalog-real.json"),
        )
    )
    receipt_path.write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
