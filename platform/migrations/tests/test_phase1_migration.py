"""Executable, database-independent checks for the initial Alembic revision.

The default test path renders PostgreSQL SQL in Alembic offline mode.  This
keeps the migration gate useful in CI without requiring a service container;
an integration test can additionally be run by setting
``CRASH_CAP_TEST_DATABASE_URL`` to a PostgreSQL 15+ URL.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

MIGRATIONS = Path(__file__).resolve().parents[1]
CONFIG_PATH = MIGRATIONS / "alembic.ini"

EXPECTED_TABLES = {
    "workspaces",
    "builds",
    "build_modules",
    "artifacts",
    "dump_blobs",
    "occurrences",
    "analysis_runs",
    "analysis_summaries",
    "crash_groups",
    "group_memberships",
    "group_membership_history",
    "missing_symbols",
    "uploads",
    "operation_logs",
}
FORBIDDEN_TABLES = {"users", "roles", "tenants", "memberships"}


def _config(output: io.StringIO | None = None) -> Config:
    config = Config(str(CONFIG_PATH))
    config.set_main_option(
        "sqlalchemy.url",
        os.environ.get(
            "CRASH_CAP_TEST_DATABASE_URL",
            "postgresql+psycopg://postgres:postgres@localhost:5432/crashcap",
        ),
    )
    if output is not None:
        config.attributes["output_buffer"] = output
    return config


def _render_upgrade() -> str:
    output = io.StringIO()
    command.upgrade(_config(output), "head", sql=True)
    return output.getvalue()


def _render_downgrade() -> str:
    output = io.StringIO()
    command.downgrade(_config(output), "0001_phase1_initial:base", sql=True)
    return output.getvalue()


def test_phase1_upgrade_renders_all_tables_and_postgres_types() -> None:
    sql = _render_upgrade()
    normalized = sql.lower()

    for table in EXPECTED_TABLES:
        assert f"create table {table}" in normalized
    for table in FORBIDDEN_TABLES:
        assert f"create table {table}" not in normalized

    assert "jsonb" in normalized
    assert "timestamp with time zone" in normalized
    assert "unique nulls not distinct (workspace_id, debug_id, code_id)" in normalized


def test_phase1_upgrade_renders_documented_constraints_and_indexes() -> None:
    sql = _render_upgrade().lower()
    required = {
        "uq_workspaces_name",
        "fk_builds_workspace_id",
        "fk_build_modules_build_id",
        "fk_artifacts_build_id",
        "fk_artifacts_module_id",
        "uq_dump_blobs_workspace_sha256",
        "uq_occurrences_dump_blob_id",
        "uq_analysis_runs_idempotency_key",
        "uq_crash_groups_workspace_type_fingerprint",
        "pk_group_memberships",
        "fk_group_membership_history_occurrence_id",
        "ck_group_membership_history_action",
        "ix_group_membership_history_occurrence_recorded",
        "uq_missing_symbols_workspace_debug_code",
        "ix_builds_workspace_created_at",
        "ix_artifacts_debug_id",
        "ix_artifacts_code_id",
        "ix_artifacts_sha256",
        "ix_analysis_summaries_exact_fingerprint",
        "ix_analysis_summaries_exception_fault_module",
    }
    for name in required:
        assert name in sql, name

    assert "unique (workspace_id, version)" not in sql
    assert "ck_uploads_verification_status" in sql
    assert "ck_analysis_runs_status" in sql
    assert "ck_artifacts_verification_status" in sql


def test_phase1_downgrade_renders_in_dependency_order() -> None:
    sql = _render_downgrade().lower()
    assert "drop table operation_logs" in sql
    assert "drop table workspaces" in sql
    assert sql.index("drop table operation_logs") < sql.index("drop table workspaces")
    assert "drop constraint fk_occurrences_current_run_id" in sql


@pytest.mark.integration
def test_phase1_can_upgrade_and_downgrade_postgresql() -> None:
    """Exercise PostgreSQL DDL when an explicit test database is provided."""

    url = os.environ.get("CRASH_CAP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set CRASH_CAP_TEST_DATABASE_URL for PostgreSQL integration testing")

    engine = create_engine(url)
    try:
        command.upgrade(_config(), "head")
        names = set(inspect(engine).get_table_names())
        assert names >= EXPECTED_TABLES

        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO workspaces (id, name) VALUES (:id, :name)"),
                {"id": "wsp_test", "name": "migration-test"},
            )
            connection.execute(
                text("INSERT INTO missing_symbols (workspace_id) VALUES (:workspace_id)"),
                {"workspace_id": "wsp_test"},
            )
            with pytest.raises(IntegrityError):
                connection.execute(
                    text("INSERT INTO missing_symbols (workspace_id) VALUES (:workspace_id)"),
                    {"workspace_id": "wsp_test"},
                )

        command.downgrade(_config(), "base")
        assert not (set(inspect(engine).get_table_names()) & EXPECTED_TABLES)
    finally:
        engine.dispose()
