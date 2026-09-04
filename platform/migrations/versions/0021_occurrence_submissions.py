"""Retain each upload's manual annotations without changing Occurrence identity."""

import sqlalchemy as sa
from alembic import op

revision = "0021_occurrence_submissions"
down_revision = "0020_frozen_grouping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "occurrence_submissions",
        sa.Column("upload_id", sa.Text(), sa.ForeignKey("uploads.id"), primary_key=True),
        sa.Column("occurrence_id", sa.Text(), sa.ForeignKey("occurrences.id")),
        sa.Column("label", sa.Text()),
        sa.Column("batch", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "(occurrence_id IS NULL AND verified_at IS NULL) OR "
            "(occurrence_id IS NOT NULL AND verified_at IS NOT NULL)",
            name="ck_occurrence_submissions_verified",
        ),
    )
    op.create_index(
        "ix_occurrence_submissions_history",
        "occurrence_submissions",
        ["occurrence_id", "upload_id"],
    )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT EXISTS (SELECT 1 FROM occurrence_submissions)")):
        raise RuntimeError("Retained submission history prevents downgrade")
    op.drop_table("occurrence_submissions")
