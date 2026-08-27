"""Add versioned Artifact Blob payloads and terminal Upload payload lifecycle."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0008_artifact_payloads_gc"
down_revision: str | None = "0007_artifact_blob_dedup"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "artifact_blobs",
        sa.Column(
            "payload_encoding", sa.Text(), nullable=False, server_default=sa.text("'identity'")
        ),
    )
    op.add_column("artifact_blobs", sa.Column("payload_size", sa.BigInteger(), nullable=True))
    op.add_column("artifact_blobs", sa.Column("payload_sha256", sa.CHAR(length=64), nullable=True))
    op.add_column("artifact_blobs", sa.Column("payload_object_key", sa.Text(), nullable=True))
    op.add_column(
        "artifact_blobs",
        sa.Column("payload_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "artifact_blobs",
        sa.Column(
            "payload_format_version",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'artifact-blob-payload-v1'"),
        ),
    )
    op.execute(
        sa.text(
            "UPDATE artifact_blobs SET payload_size = size, payload_sha256 = sha256, "
            "payload_object_key = object_key, "
            "payload_verified_at = CASE WHEN verification_status = 'verified' "
            "THEN verified_at ELSE NULL END"
        )
    )
    op.alter_column("artifact_blobs", "payload_size", nullable=False)
    op.alter_column("artifact_blobs", "payload_sha256", nullable=False)
    op.alter_column("artifact_blobs", "payload_object_key", nullable=False)
    op.create_check_constraint(
        "ck_artifact_blobs_payload_encoding",
        "artifact_blobs",
        "payload_encoding IN ('identity', 'zstd-v1')",
    )
    op.create_check_constraint(
        "ck_artifact_blobs_payload_size", "artifact_blobs", "payload_size > 0"
    )
    op.create_check_constraint(
        "ck_artifact_blobs_payload_sha256",
        "artifact_blobs",
        "payload_sha256 ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "ck_artifact_blobs_payload_format_version",
        "artifact_blobs",
        "payload_format_version = 'artifact-blob-payload-v1'",
    )

    op.create_table(
        "artifact_blob_payload_legacy_copies",
        sa.Column("artifact_blob_id", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column(
            "payload_encoding", sa.Text(), nullable=False, server_default=sa.text("'identity'")
        ),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("retained_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deletion_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("artifact_blob_id", name="pk_artifact_blob_payload_legacy_copies"),
        sa.ForeignKeyConstraint(
            ["artifact_blob_id"],
            ["artifact_blobs.id"],
            name="fk_artifact_blob_payload_legacy_blob_id",
        ),
        sa.CheckConstraint(
            "payload_encoding = 'identity'", name="ck_artifact_blob_payload_legacy_encoding"
        ),
        sa.CheckConstraint("size > 0", name="ck_artifact_blob_payload_legacy_size"),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="ck_artifact_blob_payload_legacy_sha256"
        ),
    )
    op.create_index(
        "ix_artifact_blob_payload_legacy_retention",
        "artifact_blob_payload_legacy_copies",
        ["deleted_at", "retained_until"],
    )

    op.create_table(
        "artifact_blob_payload_backfill_gaps",
        sa.Column("artifact_blob_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("artifact_blob_id", name="pk_artifact_blob_payload_backfill_gaps"),
        sa.ForeignKeyConstraint(
            ["artifact_blob_id"],
            ["artifact_blobs.id"],
            name="fk_artifact_blob_payload_backfill_gaps_blob_id",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_artifact_blob_payload_backfill_gaps_workspace_id",
        ),
        sa.CheckConstraint(
            "attempt_count > 0", name="ck_artifact_blob_payload_backfill_gaps_attempt_count"
        ),
    )
    op.create_index(
        "ix_artifact_blob_payload_backfill_gaps_unresolved",
        "artifact_blob_payload_backfill_gaps",
        ["resolved_at", "artifact_blob_id"],
    )

    op.add_column("uploads", sa.Column("payload_deleted_at", sa.DateTime(timezone=True)))
    op.add_column("uploads", sa.Column("payload_deletion_reason", sa.Text()))
    op.add_column(
        "uploads",
        sa.Column(
            "payload_deletion_attempts", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    op.add_column("uploads", sa.Column("payload_delete_claim_token", sa.Text()))
    op.add_column(
        "uploads", sa.Column("payload_delete_lease_expires_at", sa.DateTime(timezone=True))
    )
    op.add_column("uploads", sa.Column("payload_delete_last_error", sa.Text()))
    op.create_check_constraint(
        "ck_uploads_payload_deletion_attempts", "uploads", "payload_deletion_attempts >= 0"
    )
    op.create_index(
        "ix_uploads_payload_gc_eligibility",
        "uploads",
        ["verification_status", "payload_deleted_at", "completed_at"],
    )
    op.create_index(
        "ix_uploads_payload_gc_lease",
        "uploads",
        ["payload_delete_lease_expires_at", "id"],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM artifact_blobs "
            "WHERE payload_encoding <> 'identity' OR payload_object_key <> object_key) "
            "OR EXISTS (SELECT 1 FROM uploads WHERE payload_deleted_at IS NOT NULL) THEN "
            "RAISE EXCEPTION 'cannot downgrade after compressed payloads or Upload GC exist'; "
            "END IF; END $$"
        )
    )
    op.drop_index("ix_uploads_payload_gc_lease", table_name="uploads")
    op.drop_index("ix_uploads_payload_gc_eligibility", table_name="uploads")
    op.drop_constraint("ck_uploads_payload_deletion_attempts", "uploads", type_="check")
    op.drop_column("uploads", "payload_delete_last_error")
    op.drop_column("uploads", "payload_delete_lease_expires_at")
    op.drop_column("uploads", "payload_delete_claim_token")
    op.drop_column("uploads", "payload_deletion_attempts")
    op.drop_column("uploads", "payload_deletion_reason")
    op.drop_column("uploads", "payload_deleted_at")
    op.drop_index(
        "ix_artifact_blob_payload_legacy_retention",
        table_name="artifact_blob_payload_legacy_copies",
    )
    op.drop_index(
        "ix_artifact_blob_payload_backfill_gaps_unresolved",
        table_name="artifact_blob_payload_backfill_gaps",
    )
    op.drop_table("artifact_blob_payload_backfill_gaps")
    op.drop_table("artifact_blob_payload_legacy_copies")
    op.drop_constraint("ck_artifact_blobs_payload_format_version", "artifact_blobs", type_="check")
    op.drop_constraint("ck_artifact_blobs_payload_sha256", "artifact_blobs", type_="check")
    op.drop_constraint("ck_artifact_blobs_payload_size", "artifact_blobs", type_="check")
    op.drop_constraint("ck_artifact_blobs_payload_encoding", "artifact_blobs", type_="check")
    op.drop_column("artifact_blobs", "payload_format_version")
    op.drop_column("artifact_blobs", "payload_verified_at")
    op.drop_column("artifact_blobs", "payload_object_key")
    op.drop_column("artifact_blobs", "payload_sha256")
    op.drop_column("artifact_blobs", "payload_size")
    op.drop_column("artifact_blobs", "payload_encoding")
