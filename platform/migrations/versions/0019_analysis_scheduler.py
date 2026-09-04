"""Add durable fair automatic-analysis capacity slots."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text

revision = "0019_analysis_scheduler"
down_revision = "0018_current_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analysis_scheduler_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("last_workspace_id", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("id = 1", name="ck_analysis_scheduler_state_singleton"),
    )
    op.execute("INSERT INTO analysis_scheduler_state (id) VALUES (1)")
    op.create_table(
        "analysis_execution_slots",
        sa.Column(
            "demand_id",
            sa.Text(),
            sa.ForeignKey("auto_analysis_demands.id"),
            primary_key=True,
        ),
        sa.Column("workspace_id", sa.Text(), sa.ForeignKey("workspaces.id"), nullable=False),
        sa.Column("claim_token", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_id", sa.Text(), sa.ForeignKey("analysis_runs.id"), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("claim_token", name="uq_analysis_execution_slots_claim"),
        sa.UniqueConstraint("run_id", name="uq_analysis_execution_slots_run"),
        sa.CheckConstraint(
            "state IN ('planning','executing')", name="ck_analysis_execution_slots_state"
        ),
        sa.CheckConstraint(
            "(state = 'planning' AND run_id IS NULL) OR "
            "(state = 'executing' AND run_id IS NOT NULL)",
            name="ck_analysis_execution_slots_binding",
        ),
    )
    op.create_index(
        "ix_analysis_execution_slots_lease",
        "analysis_execution_slots",
        ["state", "lease_until"],
    )


def downgrade() -> None:
    if op.get_bind().execute(
        text("SELECT EXISTS(SELECT 1 FROM analysis_execution_slots)")
    ).scalar_one():
        raise RuntimeError("Retained automatic-analysis slots require the compatible schema")
    op.drop_table("analysis_execution_slots")
    op.drop_table("analysis_scheduler_state")
