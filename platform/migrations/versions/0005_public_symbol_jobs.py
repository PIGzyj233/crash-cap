"""Independent durable Windows public PDB cache jobs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005_public_symbol_jobs"
down_revision = "0004_analysis_diagnostics"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "public_symbol_jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("occurrence_id", sa.Text(), nullable=False),
        sa.Column("source_run_id", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("items", JSONB(), nullable=False),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("requested_by_user_id", sa.Text(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["occurrence_id", "workspace_id"], ["occurrences.id", "occurrences.workspace_id"]
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id", "occurrence_id"], ["analysis_runs.id", "analysis_runs.occurrence_id"]
        ),
        sa.UniqueConstraint(
            "occurrence_id", "idempotency_key", name="uq_public_symbol_jobs_request"
        ),
        sa.CheckConstraint(
            "status IN ('queued','running','completed','failed')",
            name="ck_public_symbol_jobs_status",
        ),
    )
    op.create_index(
        "ix_public_symbol_jobs_occurrence", "public_symbol_jobs", ["occurrence_id", "created_at"]
    )
    op.create_table(
        "public_symbol_requests",
        sa.Column("occurrence_id", sa.Text(), sa.ForeignKey("occurrences.id"), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("job_id", sa.Text(), sa.ForeignKey("public_symbol_jobs.id"), nullable=False),
    )
    for table in ("task_intents", "task_executions"):
        op.drop_constraint(f"ck_{table}_type", table, type_="check")
        op.create_check_constraint(
            f"ck_{table}_type",
            table,
            "task_type IN ('verify_upload','dispatch_workspace_role',"
            "'analyze_frozen_run','fetch_public_symbols')",
        )
    op.drop_constraint("ck_task_intents_queue", "task_intents", type_="check")
    op.create_check_constraint(
        "ck_task_intents_queue",
        "task_intents",
        "queue IN ('verify','ingest','dump-small','dump-large','public-symbols')",
    )


def downgrade():
    raise RuntimeError("Restore a database backup to roll back public symbol jobs")
