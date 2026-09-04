"""Retain idempotent manual demand restart receipts."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0023_demand_restarts"
down_revision = "0022_result_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "analysis_demand_restarts",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "demand_id", sa.Text(), sa.ForeignKey("auto_analysis_demands.id"), nullable=False
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.CHAR(64), nullable=False),
        sa.Column("request", json_type, nullable=False),
        sa.Column("response", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "demand_id", "idempotency_key", name="uq_analysis_demand_restart_request"
        ),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION reject_demand_restart_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'demand restart history is immutable';
            END $$
        """)
        op.execute("""
            CREATE TRIGGER demand_restarts_immutable
            BEFORE UPDATE OR DELETE ON analysis_demand_restarts
            FOR EACH ROW EXECUTE FUNCTION reject_demand_restart_mutation()
        """)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM analysis_demand_restarts)")):
        raise RuntimeError("Retained demand restart history prevents downgrade")
    op.drop_table("analysis_demand_restarts")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION reject_demand_restart_mutation()")
