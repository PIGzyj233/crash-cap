from __future__ import annotations

import hashlib
import os
import threading
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from crashcap_api.ids import new_id
from crashcap_api.models import AnalysisRun, DumpBlob, Occurrence, Workspace, utcnow
from crashcap_api.services.analysis_lifecycle import PromotionDecision, promote_current_analysis
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "platform" / "migrations"


def _config(url: str) -> Config:
    config = Config(str(MIGRATIONS / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _run(occurrence_id: str, status: str) -> AnalysisRun:
    run_id = new_id("run")
    return AnalysisRun(
        id=run_id,
        occurrence_id=occurrence_id,
        run_spec={"run_id": run_id},
        resolution_method="unresolved",
        core_version="test",
        core_image_digest="sha256:" + "0" * 64,
        symbolicator_version="test",
        symbol_inventory_version=0,
        idempotency_key=hashlib.sha256(run_id.encode()).hexdigest(),
        status=status,
    )


@pytest.mark.integration
def test_postgres_occurrence_lock_prevents_late_current_analysis_rollback() -> None:
    url = os.environ.get("CRASH_CAP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set CRASH_CAP_TEST_DATABASE_URL for PostgreSQL lifecycle testing")

    config = _config(url)
    engine = create_engine(url, pool_pre_ping=True)
    sessions = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
    try:
        command.upgrade(config, "head")
        with sessions() as session:
            workspace = Workspace(id=new_id("wsp"), name="postgres-promotion")
            session.add(workspace)
            session.flush()
            blob = DumpBlob(
                id=new_id("blob"),
                workspace_id=workspace.id,
                sha256="4" * 64,
                size=1,
                object_key="dump-blobs/postgres/original.dmp",
                verification_status="ACCEPTED",
            )
            session.add(blob)
            session.flush()
            occurrence = Occurrence(
                id=new_id("occ"),
                workspace_id=workspace.id,
                dump_blob_id=blob.id,
                uploaded_at=utcnow(),
                occurred_at=utcnow(),
                time_source="uploaded",
            )
            session.add(occurrence)
            session.flush()
            older = _run(occurrence.id, "COMPLETE")
            newer = _run(occurrence.id, "PARTIAL")
            session.add_all([older, newer])
            session.commit()

        newer_locked = threading.Event()
        decisions: list[PromotionDecision] = []
        failures: list[Exception] = []
        result_lock = threading.Lock()

        def promote(run_id: str, *, signal: bool) -> None:
            try:
                with sessions() as session:
                    locked = session.scalar(
                        select(Occurrence)
                        .where(Occurrence.id == occurrence.id)
                        .with_for_update()
                    )
                    candidate = session.get(AnalysisRun, run_id)
                    assert locked is not None and candidate is not None
                    if signal:
                        newer_locked.set()
                        time.sleep(0.2)
                    decision = promote_current_analysis(session, locked, candidate)
                    session.commit()
                with result_lock:
                    decisions.append(decision)
            except Exception as error:
                with result_lock:
                    failures.append(error)

        newer_thread = threading.Thread(target=promote, args=(newer.id,), kwargs={"signal": True})
        newer_thread.start()
        assert newer_locked.wait(timeout=10)
        older_thread = threading.Thread(target=promote, args=(older.id,), kwargs={"signal": False})
        older_thread.start()
        newer_thread.join(timeout=15)
        older_thread.join(timeout=15)
        assert not newer_thread.is_alive() and not older_thread.is_alive()
        assert failures == []
        assert {decision.reason for decision in decisions} == {
            "first_success",
            "older_than_current",
        }

        with sessions() as session:
            stored = session.get(Occurrence, occurrence.id)
            assert stored is not None and stored.current_run_id == newer.id
    finally:
        command.downgrade(config, "base")
        engine.dispose()
