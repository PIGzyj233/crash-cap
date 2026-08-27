"""Add explicit wire identity for Artifact delivery v2 uploads."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_delivery_v2_wire"
down_revision: str | None = "0008_artifact_payloads_gc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "uploads",
        sa.Column("wire_encoding", sa.Text(), nullable=False, server_default=sa.text("'identity'")),
    )
    op.add_column("uploads", sa.Column("wire_declared_length", sa.BigInteger(), nullable=True))
    op.add_column("uploads", sa.Column("wire_sha256_hint", sa.CHAR(length=64), nullable=True))
    op.add_column("uploads", sa.Column("verified_wire_length", sa.BigInteger(), nullable=True))
    op.add_column("uploads", sa.Column("verified_wire_sha256", sa.CHAR(length=64), nullable=True))
    op.execute(
        sa.text(
            "UPDATE uploads SET wire_declared_length = declared_length, "
            "wire_sha256_hint = client_sha256_hint, verified_wire_length = verified_length, "
            "verified_wire_sha256 = verified_sha256"
        )
    )
    op.alter_column("uploads", "wire_declared_length", nullable=False)
    op.create_check_constraint(
        "ck_uploads_wire_encoding", "uploads", "wire_encoding IN ('identity', 'zstd-v1')"
    )
    op.create_check_constraint(
        "ck_uploads_wire_declared_length", "uploads", "wire_declared_length > 0"
    )
    op.create_check_constraint(
        "ck_uploads_wire_sha256_hint",
        "uploads",
        "wire_sha256_hint IS NULL OR wire_sha256_hint ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_uploads_verified_wire_length",
        "uploads",
        "verified_wire_length IS NULL OR verified_wire_length >= 0",
    )
    op.create_check_constraint(
        "ck_uploads_verified_wire_sha256",
        "uploads",
        "verified_wire_sha256 IS NULL OR verified_wire_sha256 ~ '^[0-9a-f]{64}$'",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM uploads WHERE wire_encoding <> 'identity') "
            "THEN RAISE EXCEPTION "
            "'cannot downgrade after artifact-delivery-v2 zstd uploads exist'; "
            "END IF; END $$"
        )
    )
    op.drop_constraint("ck_uploads_verified_wire_sha256", "uploads", type_="check")
    op.drop_constraint("ck_uploads_verified_wire_length", "uploads", type_="check")
    op.drop_constraint("ck_uploads_wire_sha256_hint", "uploads", type_="check")
    op.drop_constraint("ck_uploads_wire_declared_length", "uploads", type_="check")
    op.drop_constraint("ck_uploads_wire_encoding", "uploads", type_="check")
    op.drop_column("uploads", "verified_wire_sha256")
    op.drop_column("uploads", "verified_wire_length")
    op.drop_column("uploads", "wire_sha256_hint")
    op.drop_column("uploads", "wire_declared_length")
    op.drop_column("uploads", "wire_encoding")
