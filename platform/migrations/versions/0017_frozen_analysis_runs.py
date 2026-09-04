"""Durable frozen analysis Run identity and task receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0017_frozen_analysis_runs"
down_revision = "0016_workspace_module_roles"
branch_labels = None
depends_on = None


TASK_TYPES = (
    "task_type IN ('verify_upload','ingest_artifact','publish_artifact_blob_pair',"
    "'reindex_symbols','analyze_occurrence','verify_symbol_import_pair',"
    "'dispatch_workspace_role','analyze_frozen_run')"
)


def upgrade() -> None:
    op.add_column("dump_blobs", sa.Column("capture_profile", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_dump_blobs_capture_profile",
        "dump_blobs",
        "capture_profile IS NULL OR capture_profile IN "
        "('light-crash','rich-crash','hang','full-memory')",
    )
    op.execute("ALTER TABLE analysis_runs ADD COLUMN demand_id TEXT NULL")
    op.execute("ALTER TABLE analysis_runs ADD COLUMN demand_generation BIGINT NULL")
    op.execute("ALTER TABLE analysis_runs ADD COLUMN retry_attempt INTEGER NULL")
    op.create_foreign_key(
        "fk_analysis_runs_demand_id",
        "analysis_runs",
        "auto_analysis_demands",
        ["demand_id"],
        ["id"],
    )
    op.create_check_constraint(
        "ck_analysis_runs_demand_attempt",
        "analysis_runs",
        "(demand_id IS NULL AND demand_generation IS NULL AND retry_attempt IS NULL) OR "
        "(demand_id IS NOT NULL AND demand_generation > 0 AND retry_attempt >= 0)",
    )
    op.create_unique_constraint(
        "uq_analysis_runs_demand_attempt",
        "analysis_runs",
        ["demand_id", "demand_generation", "retry_attempt"],
    )
    for table, constraint in (
        ("task_intents", "ck_task_intents_type"),
        ("task_executions", "ck_task_executions_type"),
    ):
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(constraint, table, TASK_TYPES)


def downgrade() -> None:
    retained = op.get_bind().execute(
        text(
            "SELECT EXISTS(SELECT 1 FROM analysis_runs WHERE demand_id IS NOT NULL) OR "
            "EXISTS(SELECT 1 FROM task_intents WHERE task_type = 'analyze_frozen_run') OR "
            "EXISTS(SELECT 1 FROM task_executions WHERE task_type = 'analyze_frozen_run')"
        )
    ).scalar_one()
    if retained:
        raise RuntimeError("Retained frozen Runs or tasks require the compatible schema")
    if op.get_bind().execute(
        text("SELECT EXISTS(SELECT 1 FROM dump_blobs WHERE capture_profile IS NOT NULL)")
    ).scalar_one():
        raise RuntimeError("Retained Dump capture profiles require the compatible schema")
    previous = (
        "task_type IN ('verify_upload','ingest_artifact','publish_artifact_blob_pair',"
        "'reindex_symbols','analyze_occurrence','verify_symbol_import_pair',"
        "'dispatch_workspace_role')"
    )
    for table, constraint in (
        ("task_intents", "ck_task_intents_type"),
        ("task_executions", "ck_task_executions_type"),
    ):
        op.drop_constraint(constraint, table, type_="check")
        op.create_check_constraint(constraint, table, previous)
    op.drop_constraint("uq_analysis_runs_demand_attempt", "analysis_runs", type_="unique")
    op.drop_constraint("ck_analysis_runs_demand_attempt", "analysis_runs", type_="check")
    op.drop_constraint("fk_analysis_runs_demand_id", "analysis_runs", type_="foreignkey")
    op.drop_column("analysis_runs", "retry_attempt")
    op.drop_column("analysis_runs", "demand_generation")
    op.drop_column("analysis_runs", "demand_id")
    op.drop_constraint("ck_dump_blobs_capture_profile", "dump_blobs", type_="check")
    op.drop_column("dump_blobs", "capture_profile")
