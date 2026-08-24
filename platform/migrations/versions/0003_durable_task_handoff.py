"""Add durable task intent and execution ownership metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0003_durable_task_handoff"
down_revision: str | None = "0002_phase2_build_symbols"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_intents",
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("schema_version", sa.Text(), server_default=sa.text("'1.0'"), nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("queue", sa.Text(), nullable=False),
        sa.Column("logical_key", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("message", postgresql.JSONB(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), server_default=sa.text("'pending'"), nullable=False),
        sa.Column(
            "due_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("relay_owner", sa.Text(), nullable=True),
        sa.Column("relay_generation", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("relay_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dead_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("attempt_id", name="pk_task_intents"),
        sa.UniqueConstraint("task_type", "logical_key", name="uq_task_intents_type_logical_key"),
        sa.CheckConstraint("schema_version = '1.0'", name="ck_task_intents_schema_version"),
        sa.CheckConstraint(
            "task_type IN ('verify_upload', 'ingest_artifact', 'reindex_symbols', "
            "'analyze_occurrence')",
            name="ck_task_intents_type",
        ),
        sa.CheckConstraint(
            "queue IN ('verify', 'ingest', 'dump-small', 'dump-large')",
            name="ck_task_intents_queue",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'publishing', 'published', 'dead')",
            name="ck_task_intents_state",
        ),
        sa.CheckConstraint("relay_generation >= 0", name="ck_task_intents_relay_generation"),
        sa.CheckConstraint("delivery_attempts >= 0", name="ck_task_intents_delivery_attempts"),
    )
    op.create_index("ix_task_intents_due", "task_intents", ["state", "due_at"])
    op.create_index(
        "ix_task_intents_relay_lease", "task_intents", ["state", "relay_lease_until"]
    )
    op.create_index(
        "ix_task_intents_target",
        "task_intents",
        ["task_type", "target_type", "target_id"],
    )

    op.create_table(
        "task_executions",
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("logical_key", sa.Text(), nullable=False),
        sa.Column("active_attempt_id", sa.Text(), nullable=False),
        sa.Column("generation", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.Text(), server_default=sa.text("'idle'"), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["active_attempt_id"],
            ["task_intents.attempt_id"],
            name="fk_task_executions_active_attempt_id",
        ),
        sa.PrimaryKeyConstraint("task_type", "logical_key", name="pk_task_executions"),
        sa.CheckConstraint(
            "task_type IN ('verify_upload', 'ingest_artifact', 'reindex_symbols', "
            "'analyze_occurrence')",
            name="ck_task_executions_type",
        ),
        sa.CheckConstraint("generation >= 0", name="ck_task_executions_generation"),
        sa.CheckConstraint(
            "outcome IN ('idle', 'running', 'succeeded', 'failed', 'dead')",
            name="ck_task_executions_outcome",
        ),
    )
    op.create_index(
        "ix_task_executions_lease", "task_executions", ["outcome", "lease_until"]
    )

    op.add_column("analysis_runs", sa.Column("inspect_object_key", sa.Text(), nullable=True))
    op.add_column("analysis_runs", sa.Column("analysis_context", postgresql.JSONB(), nullable=True))
    op.add_column(
        "analysis_runs",
        sa.Column("assembly_mode", sa.Text(), server_default=sa.text("'legacy'"), nullable=False),
    )
    op.add_column("analysis_runs", sa.Column("winner_attempt_id", sa.Text(), nullable=True))
    op.add_column("analysis_runs", sa.Column("winner_generation", sa.BigInteger(), nullable=True))
    op.create_check_constraint(
        "ck_analysis_runs_assembly_mode",
        "analysis_runs",
        "assembly_mode IN ('legacy', 'shadow', 'core-final')",
    )
    op.create_check_constraint(
        "ck_analysis_runs_winner_generation",
        "analysis_runs",
        "winner_generation IS NULL OR winner_generation > 0",
    )
    op.create_unique_constraint(
        "uq_analysis_runs_id_occurrence", "analysis_runs", ["id", "occurrence_id"]
    )
    op.create_foreign_key(
        "fk_analysis_runs_winner_attempt_id",
        "analysis_runs",
        "task_intents",
        ["winner_attempt_id"],
        ["attempt_id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_analysis_runs_winner_attempt_id", "analysis_runs", type_="foreignkey")
    op.drop_constraint("uq_analysis_runs_id_occurrence", "analysis_runs", type_="unique")
    op.drop_constraint("ck_analysis_runs_winner_generation", "analysis_runs", type_="check")
    op.drop_constraint("ck_analysis_runs_assembly_mode", "analysis_runs", type_="check")
    op.drop_column("analysis_runs", "winner_generation")
    op.drop_column("analysis_runs", "winner_attempt_id")
    op.drop_column("analysis_runs", "assembly_mode")
    op.drop_column("analysis_runs", "analysis_context")
    op.drop_column("analysis_runs", "inspect_object_key")
    op.drop_index("ix_task_executions_lease", table_name="task_executions")
    op.drop_table("task_executions")
    op.drop_index("ix_task_intents_target", table_name="task_intents")
    op.drop_index("ix_task_intents_relay_lease", table_name="task_intents")
    op.drop_index("ix_task_intents_due", table_name="task_intents")
    op.drop_table("task_intents")
