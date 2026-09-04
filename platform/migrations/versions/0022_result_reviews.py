"""Append explicit reviews without overwriting the initial Current decision."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0022_result_reviews"
down_revision = "0021_occurrence_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    json_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "result_reviews",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("occurrence_id", sa.Text(), sa.ForeignKey("occurrences.id"), nullable=False),
        sa.Column("current_run_id", sa.Text(), sa.ForeignKey("analysis_runs.id"), nullable=False),
        sa.Column(
            "candidate_run_id",
            sa.Text(),
            sa.ForeignKey("current_decisions.candidate_run_id"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("request_sha256", sa.CHAR(64), nullable=False),
        sa.Column("request", json_type, nullable=False),
        sa.Column("audit_object_key", sa.Text(), nullable=False),
        sa.Column("audit_sha256", sa.CHAR(64), nullable=False),
        sa.Column("cause", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("current_evidence", json_type, nullable=False),
        sa.Column("candidate_evidence", json_type, nullable=False),
        sa.Column("differences", json_type, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("occurrence_id", "idempotency_key", name="uq_result_reviews_request"),
        sa.CheckConstraint("current_run_id <> candidate_run_id", name="ck_result_reviews_distinct"),
        sa.CheckConstraint(
            "cause IN ('engine_upgrade','role_change','evidence_correction')",
            name="ck_result_reviews_cause",
        ),
        sa.CheckConstraint(
            "decision IN ('promote','retain','incomparable','correct')",
            name="ck_result_reviews_decision",
        ),
    )
    op.create_index(
        "ix_result_reviews_history", "result_reviews", ["occurrence_id", "created_at", "id"]
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION reject_result_review_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN
                RAISE EXCEPTION 'result review history is immutable';
            END $$
        """)
        op.execute("""
            CREATE TRIGGER result_reviews_immutable BEFORE UPDATE OR DELETE ON result_reviews
            FOR EACH ROW EXECUTE FUNCTION reject_result_review_mutation()
        """)


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM result_reviews)")):
        raise RuntimeError("Retained result review history prevents downgrade")
    op.drop_table("result_reviews")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION reject_result_review_mutation()")
