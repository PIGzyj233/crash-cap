from __future__ import annotations

from pathlib import Path

from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import AnalysisRun, Occurrence, OperationLog, TaskIntent, Upload, Workspace
from crashcap_api.task_reconciliation import reconcile_task_intents


def _settings(tmp_path: Path) -> Settings:
    return Settings.for_test(tmp_path).model_copy(update={"task_handoff_mode": "outbox"})


def _seed_verifying_uploads(database: Database) -> None:
    with database.sessions() as session:
        session.add(
            Workspace(
                id="wsp_reconcile",
                name="reconcile",
                display_name="Reconcile",
                retention_days=30,
            )
        )
        session.flush()
        for suffix in ("a", "b"):
            session.add(
                Upload(
                    id=f"upl_reconcile_{suffix}",
                    workspace_id="wsp_reconcile",
                    object_key=f"workspaces/wsp_reconcile/uploads/{suffix}",
                    original_filename=f"{suffix}.dmp",
                    declared_length=4,
                    file_kind="dmp",
                    verification_status="VERIFYING",
                )
            )
        session.commit()


def test_reconciliation_is_dry_run_by_default_and_resumable(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings)
    try:
        _seed_verifying_uploads(database)
        with database.sessions() as session:
            first = reconcile_task_intents(session, settings, limit=1)
            session.rollback()
        assert first["mode"] == "dry-run"
        assert first["selected_count"] == 1
        assert first["next_cursor"] is not None

        with database.sessions() as session:
            second = reconcile_task_intents(
                session,
                settings,
                after=str(first["next_cursor"]),
                limit=10,
            )
            assert session.query(TaskIntent).count() == 0
            assert session.query(OperationLog).count() == 0
        assert second["selected_count"] == 1
        assert second["items"][0]["target_id"] != first["items"][0]["target_id"]
    finally:
        database.dispose()


def test_reconciliation_apply_creates_only_intent_and_audit_rows(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings)
    try:
        _seed_verifying_uploads(database)
        with database.sessions() as session:
            before = {
                "occurrences": session.query(Occurrence).count(),
                "runs": session.query(AnalysisRun).count(),
            }
            report = reconcile_task_intents(session, settings, limit=10, apply=True)
            session.commit()
        assert report["created_count"] == 2
        with database.sessions() as session:
            assert session.query(TaskIntent).count() == 2
            assert session.query(OperationLog).filter_by(action="task.reconcile").count() == 2
            assert session.query(Occurrence).count() == before["occurrences"]
            assert session.query(AnalysisRun).count() == before["runs"]

            replay = reconcile_task_intents(session, settings, limit=10)
            assert replay["selected_count"] == 0
    finally:
        database.dispose()
