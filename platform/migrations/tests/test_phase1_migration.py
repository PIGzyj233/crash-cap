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
from alembic.script import ScriptDirectory
from crashcap_api.models import Base
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

MIGRATIONS = Path(__file__).resolve().parents[1]
CONFIG_PATH = MIGRATIONS / "alembic.ini"

EXPECTED_TABLES = {
    "workspaces",
    "builds",
    "build_modules",
    "artifacts",
    "artifact_blobs",
    "artifact_blob_upload_claims",
    "artifact_blob_pairs",
    "artifact_blob_legacy_copies",
    "artifact_blob_backfill_gaps",
    "artifact_blob_payload_legacy_copies",
    "artifact_blob_payload_backfill_gaps",
    "build_publications",
    "build_artifact_expectations",
    "dump_blobs",
    "occurrences",
    "analysis_runs",
    "analysis_summaries",
    "crash_groups",
    "group_memberships",
    "group_membership_history",
    "missing_symbols",
    "missing_symbol_occurrences",
    "symbol_projection_states",
    "symbol_projection_checkpoints",
    "symbol_projection_gaps",
    "task_intents",
    "task_executions",
    "uploads",
    "operation_logs",
    "workspace_module_roles",
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


def _render_phase2_downgrade() -> str:
    output = io.StringIO()
    command.downgrade(_config(output), "0002_phase2_build_symbols:0001_phase1_initial", sql=True)
    return output.getvalue()


def _render_architecture_downgrade() -> str:
    output = io.StringIO()
    command.downgrade(
        _config(output),
        "0005_symbol_projection_cutover:0002_phase2_build_symbols",
        sql=True,
    )
    return output.getvalue()


def test_revision_identifiers_fit_default_alembic_version_column() -> None:
    scripts = ScriptDirectory.from_config(_config())
    revisions = [revision.revision for revision in scripts.walk_revisions()]

    assert len(revisions) == len(set(revisions))
    assert all(len(revision) <= 32 for revision in revisions)


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
        "ix_occurrences_workspace_occurred_id",
        "ix_analysis_runs_occurrence_id_desc",
        "ix_uploads_workspace_dmp_status_uploaded",
    }
    for name in required:
        assert name in sql, name

    assert "unique (workspace_id, version)" not in sql
    assert "ck_uploads_verification_status" in sql
    assert "ck_analysis_runs_status" in sql
    assert "ck_artifacts_verification_status" in sql
    assert "create index concurrently ix_occurrences_workspace_occurred_id" in sql


def test_occurrence_browse_indexes_have_sqlite_equivalents() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        expected = {
            "occurrences": "ix_occurrences_workspace_occurred_id",
            "analysis_runs": "ix_analysis_runs_occurrence_id_desc",
            "uploads": "ix_uploads_workspace_dmp_status_uploaded",
        }
        for table_name, index_name in expected.items():
            assert index_name in {item["name"] for item in inspect(engine).get_indexes(table_name)}
    finally:
        engine.dispose()


def test_phase1_downgrade_renders_in_dependency_order() -> None:
    sql = _render_downgrade().lower()
    assert "drop table operation_logs" in sql
    assert "drop table workspaces" in sql
    assert sql.index("drop table operation_logs") < sql.index("drop table workspaces")
    assert "drop constraint fk_occurrences_current_run_id" in sql


def test_phase2_upgrade_and_downgrade_render_producer_source_and_in_app_ddl() -> None:
    upgrade = _render_upgrade().lower()
    for fragment in {
        "add column in_app_rules jsonb",
        "add column in_app_rule_version bigint",
        "ck_workspaces_in_app_rule_version",
        "add column producer text",
        "add column producer_build_id text",
        "add column manifest_schema_version text",
        "add column source_bundle_config jsonb",
        "ck_builds_producer",
        "uq_builds_workspace_producer_id",
        "add column ingest_metadata jsonb",
    }:
        assert fragment in upgrade, fragment

    downgrade = _render_phase2_downgrade().lower()
    for fragment in {
        "drop column ingest_metadata",
        "drop constraint uq_builds_workspace_producer_id",
        "drop constraint ck_builds_producer",
        "drop column source_bundle_config",
        "drop column manifest_schema_version",
        "drop column producer_build_id",
        "drop column producer",
        "drop constraint ck_workspaces_in_app_rule_version",
        "drop column in_app_rule_version",
        "drop column in_app_rules",
    }:
        assert fragment in downgrade, fragment


def test_architecture_upgrade_renders_additive_handoff_and_projection_ddl() -> None:
    upgrade = _render_upgrade().lower()
    for fragment in {
        "create table task_intents",
        "create table task_executions",
        "create table missing_symbol_occurrences",
        "ix_task_intents_due",
        "ix_task_intents_relay_lease",
        "ix_task_intents_target",
        "ix_task_executions_lease",
        "uq_task_intents_type_logical_key",
        "fk_task_executions_active_attempt_id",
        "add column inspect_object_key text",
        "add column analysis_context jsonb",
        "add column assembly_mode text",
        "add column winner_attempt_id text",
        "add column winner_generation bigint",
        "fk_analysis_runs_winner_attempt_id",
        "uq_analysis_runs_id_occurrence",
        "add column id text",
        "add column identity_key text",
        "uq_missing_symbols_workspace_identity",
        "fk_missing_symbol_occurrences_symbol_workspace",
        "fk_missing_symbol_occurrences_occurrence_workspace",
        "fk_missing_symbol_occurrences_run_occurrence",
        "create table symbol_projection_states",
        "create table symbol_projection_checkpoints",
        "create table symbol_projection_gaps",
        "ix_missing_symbol_occurrences_workspace_symbol_occurrence",
        "ix_symbol_projection_states_workspace_run",
        "ix_symbol_projection_gaps_unresolved",
        "drop constraint uq_missing_symbols_workspace_debug_code",
    }:
        assert fragment in upgrade, fragment


def test_local_publication_upgrade_is_additive_and_content_identified() -> None:
    upgrade = _render_upgrade().lower()
    for fragment in {
        "add column identity_mode text",
        "add column fingerprint_version text",
        "add column content_fingerprint char(64)",
        "add column sealed_at timestamp with time zone",
        "create table build_publications",
        "create table build_artifact_expectations",
        "uq_builds_workspace_content_fingerprint",
        "uq_build_publications_client_identity",
        "uq_build_artifact_expectations_logical_name",
        "uq_build_modules_build_id_id",
        "fk_build_artifact_expectations_build_module",
        "ck_builds_content_identity",
        "ck_builds_content_fingerprint",
        "ck_build_artifact_expectations_sha256",
        "add column rejection_reason text",
    }:
        assert fragment in upgrade, fragment


def test_artifact_blob_upgrade_is_additive_workspace_scoped_and_fenced() -> None:
    upgrade = _render_upgrade().lower()
    for fragment in {
        "create table artifact_blobs",
        "create table artifact_blob_upload_claims",
        "create table artifact_blob_pairs",
        "create table artifact_blob_legacy_copies",
        "create table artifact_blob_backfill_gaps",
        "uq_artifact_blobs_workspace_sha256",
        "uq_artifact_blob_upload_claims_upload",
        "uq_artifact_blob_pairs_exact",
        "add column artifact_blob_id text",
        "add column materialization_source text",
        "fk_artifacts_artifact_blob_id",
        "ck_artifacts_materialization_source",
        "publish_artifact_blob_pair",
        "schema_version in ('1.0', '1.1')",
    }:
        assert fragment in upgrade, fragment
    assert "artifact-blobs/{workspace_id}" not in upgrade


def test_artifact_payload_upgrade_is_additive_versioned_and_gc_fenced() -> None:
    upgrade = _render_upgrade().lower()
    for fragment in {
        "add column payload_encoding text",
        "add column payload_size bigint",
        "add column payload_sha256 char(64)",
        "add column payload_object_key text",
        "add column payload_verified_at timestamp with time zone",
        "add column payload_format_version text",
        "create table artifact_blob_payload_legacy_copies",
        "create table artifact_blob_payload_backfill_gaps",
        "ck_artifact_blobs_payload_encoding",
        "ck_artifact_blobs_payload_format_version",
        "add column payload_deleted_at timestamp with time zone",
        "add column payload_deletion_reason text",
        "add column payload_deletion_attempts integer",
        "add column payload_delete_claim_token text",
        "add column payload_delete_lease_expires_at timestamp with time zone",
        "ix_uploads_payload_gc_eligibility",
        "ix_uploads_payload_gc_lease",
    }:
        assert fragment in upgrade, fragment


def test_architecture_downgrade_removes_only_new_additive_schema() -> None:
    downgrade = _render_architecture_downgrade().lower()
    for fragment in {
        "drop table missing_symbol_occurrences",
        "drop table symbol_projection_states",
        "drop table symbol_projection_checkpoints",
        "drop table symbol_projection_gaps",
        "drop constraint uq_occurrences_id_workspace",
        "drop column identity_key",
        "drop column id",
        "drop constraint fk_analysis_runs_winner_attempt_id",
        "drop column winner_generation",
        "drop column winner_attempt_id",
        "drop column assembly_mode",
        "drop column analysis_context",
        "drop column inspect_object_key",
        "drop table task_executions",
        "drop table task_intents",
    }:
        assert fragment in downgrade, fragment
    assert "drop table analysis_runs" not in downgrade
    assert downgrade.index("drop table missing_symbol_occurrences") < downgrade.index(
        "drop column identity_key"
    )
    assert downgrade.index("drop constraint fk_analysis_runs_winner_attempt_id") < downgrade.index(
        "drop table task_intents"
    )


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
        assert "result_reviews" in names
        assert "uq_result_reviews_request" in {
            constraint["name"]
            for constraint in inspect(engine).get_unique_constraints("result_reviews")
        }
        assert {
            "ck_result_reviews_distinct",
            "ck_result_reviews_cause",
            "ck_result_reviews_decision",
        } <= {
            constraint["name"]
            for constraint in inspect(engine).get_check_constraints("result_reviews")
        }
        with engine.connect() as connection:
            assert connection.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM pg_trigger "
                    "WHERE tgrelid = 'result_reviews'::regclass "
                    "AND tgname = 'result_reviews_immutable' AND NOT tgisinternal)"
                )
            )
        assert {
            "in_app_rules",
            "in_app_rule_version",
        } <= {column["name"] for column in inspect(engine).get_columns("workspaces")}
        assert {
            "producer",
            "producer_build_id",
            "manifest_schema_version",
            "source_bundle_config",
            "identity_mode",
            "fingerprint_version",
            "content_fingerprint",
            "sealed_at",
        } <= {column["name"] for column in inspect(engine).get_columns("builds")}
        assert "rejection_reason" in {
            column["name"] for column in inspect(engine).get_columns("uploads")
        }
        assert "ingest_metadata" in {
            column["name"] for column in inspect(engine).get_columns("artifacts")
        }
        assert {"artifact_blob_id", "materialization_source"} <= {
            column["name"] for column in inspect(engine).get_columns("artifacts")
        }
        assert {
            "payload_encoding",
            "payload_size",
            "payload_sha256",
            "payload_object_key",
            "payload_verified_at",
            "payload_format_version",
        } <= {column["name"] for column in inspect(engine).get_columns("artifact_blobs")}
        assert {
            "payload_deleted_at",
            "payload_deletion_reason",
            "payload_deletion_attempts",
            "payload_delete_claim_token",
            "payload_delete_lease_expires_at",
            "payload_delete_last_error",
        } <= {column["name"] for column in inspect(engine).get_columns("uploads")}
        artifact_blob_unique = {
            constraint["name"]
            for constraint in inspect(engine).get_unique_constraints("artifact_blobs")
        }
        assert "uq_artifact_blobs_workspace_sha256" in artifact_blob_unique
        assert {
            "inspect_object_key",
            "analysis_context",
            "assembly_mode",
            "winner_attempt_id",
            "winner_generation",
        } <= {column["name"] for column in inspect(engine).get_columns("analysis_runs")}
        assert {"id", "identity_key"} <= {
            column["name"] for column in inspect(engine).get_columns("missing_symbols")
        }
        task_intent_indexes = {
            index["name"] for index in inspect(engine).get_indexes("task_intents")
        }
        assert {
            "ix_task_intents_due",
            "ix_task_intents_relay_lease",
            "ix_task_intents_target",
        } <= task_intent_indexes
        relation_foreign_keys = {
            foreign_key["name"]: tuple(foreign_key["constrained_columns"])
            for foreign_key in inspect(engine).get_foreign_keys("missing_symbol_occurrences")
        }
        assert relation_foreign_keys["fk_missing_symbol_occurrences_symbol_workspace"] == (
            "missing_symbol_id",
            "workspace_id",
        )
        assert relation_foreign_keys["fk_missing_symbol_occurrences_occurrence_workspace"] == (
            "occurrence_id",
            "workspace_id",
        )
        assert relation_foreign_keys["fk_missing_symbol_occurrences_run_occurrence"] == (
            "analysis_run_id",
            "occurrence_id",
        )

        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO workspaces (id, name) VALUES (:id, :name)"),
                {"id": "wsp_test", "name": "migration-test"},
            )
            connection.execute(
                text("INSERT INTO missing_symbols (workspace_id) VALUES (:workspace_id)"),
                {"workspace_id": "wsp_test"},
            )
        # Revision 0005 intentionally permits multiple legacy double-null rows;
        # the authoritative workspace/identity key separates normalized files.
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO missing_symbols (workspace_id) VALUES (:workspace_id)"),
                {"workspace_id": "wsp_test"},
            )
            connection.execute(
                text(
                    "INSERT INTO missing_symbols "
                    "(id, workspace_id, identity_key, code_file) "
                    "VALUES ('missing_identity', 'wsp_test', 'identity:test', 'app.exe')"
                )
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO missing_symbols "
                    "(id, workspace_id, identity_key, code_file) "
                    "VALUES ('missing_identity_duplicate', 'wsp_test', "
                    "'identity:test', 'other.exe')"
                )
            )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO task_intents "
                    "(attempt_id, task_type, queue, logical_key, target_type, target_id, message) "
                    "VALUES (:attempt_id, :task_type, :queue, :logical_key, :target_type, "
                    ":target_id, CAST(:message AS jsonb))"
                ),
                {
                    "attempt_id": "attempt_test_1",
                    "task_type": "verify_upload",
                    "queue": "verify",
                    "logical_key": "upload:test",
                    "target_type": "upload",
                    "target_id": "upload_test",
                    "message": "{}",
                },
            )
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO task_intents "
                    "(attempt_id, task_type, queue, logical_key, target_type, target_id, message) "
                    "VALUES ('attempt_test_2', 'verify_upload', 'verify', 'upload:test', "
                    "'upload', 'upload_test', '{}'::jsonb)"
                )
            )

        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO workspaces (id, name) VALUES ('wsp_other', 'migration-other')")
            )
            connection.execute(
                text(
                    "INSERT INTO dump_blobs (id, workspace_id, sha256, size, object_key) "
                    "VALUES ('blob_test', 'wsp_test', :sha256, 1, 'dumps/test.dmp')"
                ),
                {"sha256": "1" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO occurrences "
                    "(id, workspace_id, dump_blob_id, uploaded_at, occurred_at, time_source) "
                    "VALUES ('occ_test', 'wsp_test', 'blob_test', CURRENT_TIMESTAMP, "
                    "CURRENT_TIMESTAMP, 'uploaded')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO analysis_runs "
                    "(id, occurrence_id, run_spec, resolution_method, core_version, "
                    "core_image_digest, symbolicator_version, symbol_inventory_version, "
                    "idempotency_key, status) VALUES ('run_test', 'occ_test', '{}'::jsonb, "
                    "'unresolved', 'test', :digest, 'test', 0, :idempotency_key, 'COMPLETE')"
                ),
                {"digest": f"sha256:{'2' * 64}", "idempotency_key": "3" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO missing_symbols "
                    "(id, workspace_id, identity_key, debug_id) "
                    "VALUES ('missing_other', 'wsp_other', 'debug:other', 'DEBUGOTHER')"
                )
            )
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO analysis_runs "
                    "(id, occurrence_id, run_spec, resolution_method, core_version, "
                    "core_image_digest, symbolicator_version, symbol_inventory_version, "
                    "idempotency_key, status, schema_version) VALUES "
                    "('run_canonical_11', 'occ_test', '{}'::jsonb, 'unresolved', 'test', "
                    ":digest, 'test', 0, :key, 'PARTIAL', '1.1')"
                ),
                {"digest": f"sha256:{'2' * 64}", "key": "5" * 64},
            )
        with pytest.raises(RuntimeError, match="retain a compatible reader"):
            command.downgrade(_config(), "0010_occurrence_browse")
        with engine.begin() as connection:
            assert (
                connection.execute(
                    text("SELECT schema_version FROM analysis_runs WHERE id='run_canonical_11'")
                ).scalar_one()
                == "1.1"
            )
            assert (
                connection.execute(
                    text("SELECT schema_version FROM analysis_runs WHERE id='run_test'")
                ).scalar_one()
                == "1.0"
            )
            connection.execute(text("DELETE FROM analysis_runs WHERE id='run_canonical_11'"))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO missing_symbol_occurrences "
                    "(missing_symbol_id, occurrence_id, workspace_id, analysis_run_id, reason) "
                    "VALUES ('missing_other', 'occ_test', 'wsp_other', 'run_test', 'missing_pdb')"
                )
            )

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO artifact_blobs "
                    "(id, workspace_id, sha256, kind, size, object_key, verification_status, "
                    "payload_encoding, payload_size, payload_sha256, payload_object_key, "
                    "payload_verified_at) VALUES "
                    "('abl_zstd_guard', 'wsp_test', :sha256, 'pdb', 1, 'raw/guard.pdb', "
                    "'verified', 'zstd-v1', 1, :sha256, 'compressed/guard.pdb.zst', "
                    "CURRENT_TIMESTAMP)"
                ),
                {"sha256": "4" * 64},
            )
        with pytest.raises(SQLAlchemyError, match="cannot downgrade after compressed payloads"):
            command.downgrade(_config(), "0007_artifact_blob_dedup")
        assert "payload_encoding" in {
            column["name"] for column in inspect(engine).get_columns("artifact_blobs")
        }
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM artifact_blobs WHERE id = 'abl_zstd_guard'"))
        # Depending on Alembic's per-revision transaction boundary, 0009 may
        # already have stepped back before 0008 rejects. Restore head before
        # exercising the normal empty-data downgrade.
        command.upgrade(_config(), "head")

        # The production rollback contract is compatible-code + feature flags,
        # not schema downgrade after split identities exist.  Remove only this
        # test's deliberately incompatible rows so an empty-schema Alembic
        # roundtrip can still verify dependency ordering.
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM missing_symbols WHERE workspace_id IN ('wsp_test', 'wsp_other')")
            )
        command.downgrade(_config(), "base")
        assert not (set(inspect(engine).get_table_names()) & EXPECTED_TABLES)
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT to_regclass('result_reviews')")) is None
            assert (
                connection.scalar(text("SELECT to_regprocedure('reject_result_review_mutation()')"))
                is None
            )
    finally:
        engine.dispose()
