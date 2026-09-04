"""Persist evidence-v1 Current decisions without rewriting historical Runs."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "0018_current_decisions"
down_revision = "0017_frozen_analysis_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "current_decisions",
        sa.Column(
            "candidate_run_id",
            sa.Text(),
            sa.ForeignKey("analysis_runs.id"),
            primary_key=True,
        ),
        sa.Column(
            "occurrence_id", sa.Text(), sa.ForeignKey("occurrences.id"), nullable=False
        ),
        sa.Column(
            "observed_current_run_id",
            sa.Text(),
            sa.ForeignKey("analysis_runs.id"),
            nullable=True,
        ),
        sa.Column("rule_version", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("retry_recommended", sa.Boolean(), nullable=False),
        sa.Column("differences", postgresql.JSONB(), nullable=False),
        sa.Column("current_evidence", postgresql.JSONB(), nullable=True),
        sa.Column("candidate_evidence", postgresql.JSONB(), nullable=False),
        sa.Column("audit_id", sa.Text(), nullable=True),
        sa.Column("audit_sha256", sa.CHAR(64), nullable=True),
        sa.Column(
            "execution_attempt_id",
            sa.Text(),
            sa.ForeignKey("task_intents.attempt_id"),
            nullable=False,
        ),
        sa.Column("execution_generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "rule_version = 'evidence-v1'", name="ck_current_decisions_rule"
        ),
        sa.CheckConstraint(
            "decision IN ('promote','retain','incomparable','correct')",
            name="ck_current_decisions_decision",
        ),
        sa.CheckConstraint(
            "execution_generation > 0", name="ck_current_decisions_generation"
        ),
        sa.UniqueConstraint(
            "candidate_run_id",
            "observed_current_run_id",
            "rule_version",
            name="uq_current_decisions_observation",
        ),
    )
    op.create_index(
        "ix_current_decisions_occurrence_created",
        "current_decisions",
        ["occurrence_id", "created_at"],
    )


def downgrade() -> None:
    if op.get_bind().execute(
        text("SELECT EXISTS(SELECT 1 FROM current_decisions)")
    ).scalar_one():
        raise RuntimeError("Retained evidence-v1 decisions require the compatible schema")
    op.drop_index(
        "ix_current_decisions_occurrence_created", table_name="current_decisions"
    )
    op.drop_table("current_decisions")
