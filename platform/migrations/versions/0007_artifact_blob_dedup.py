"""Add Workspace-scoped Artifact Blob deduplication."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0007_artifact_blob_dedup"
down_revision: str | None = "0006_build_publications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_task_intents_schema_version", "task_intents", type_="check")
    op.create_check_constraint(
        "ck_task_intents_schema_version",
        "task_intents",
        "schema_version IN ('1.0', '1.1')",
    )
    op.create_table(
        "artifact_blobs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("code_id", sa.Text(), nullable=True),
        sa.Column("debug_id", sa.Text(), nullable=True),
        sa.Column("verification_status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("verification_reason", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id", name="pk_artifact_blobs"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_artifact_blobs_workspace_id"),
        sa.UniqueConstraint("workspace_id", "sha256", name="uq_artifact_blobs_workspace_sha256"),
        sa.CheckConstraint("kind IN ('pe', 'pdb')", name="ck_artifact_blobs_kind"),
        sa.CheckConstraint("size > 0", name="ck_artifact_blobs_size"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_artifact_blobs_sha256"),
        sa.CheckConstraint(
            "verification_status IN ('pending', 'verified', 'rejected', 'missing')",
            name="ck_artifact_blobs_verification_status",
        ),
    )
    op.create_index("ix_artifact_blobs_code_id", "artifact_blobs", ["workspace_id", "code_id"])
    op.create_index("ix_artifact_blobs_debug_id", "artifact_blobs", ["workspace_id", "debug_id"])

    op.add_column("artifacts", sa.Column("artifact_blob_id", sa.Text(), nullable=True))
    op.add_column(
        "artifacts",
        sa.Column("materialization_source", sa.Text(), nullable=False, server_default=sa.text("'legacy'")),
    )
    op.create_foreign_key(
        "fk_artifacts_artifact_blob_id", "artifacts", "artifact_blobs", ["artifact_blob_id"], ["id"]
    )
    op.create_check_constraint(
        "ck_artifacts_materialization_source",
        "artifacts",
        "materialization_source IN ('upload', 'blob_reuse', 'backfill', 'legacy')",
    )
    op.create_index("ix_artifacts_artifact_blob_id", "artifacts", ["artifact_blob_id"])

    op.create_table(
        "artifact_blob_upload_claims",
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column("upload_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("workspace_id", "sha256", name="pk_artifact_blob_upload_claims"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_artifact_blob_upload_claims_workspace_id"
        ),
        sa.ForeignKeyConstraint(["upload_id"], ["uploads.id"], name="fk_artifact_blob_upload_claims_upload_id"),
        sa.UniqueConstraint("upload_id", name="uq_artifact_blob_upload_claims_upload"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_artifact_blob_upload_claims_sha256"),
        sa.CheckConstraint("kind IN ('pe', 'pdb')", name="ck_artifact_blob_upload_claims_kind"),
        sa.CheckConstraint("size > 0", name="ck_artifact_blob_upload_claims_size"),
    )

    op.create_table(
        "artifact_blob_pairs",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("pe_blob_id", sa.Text(), nullable=False),
        sa.Column("pdb_blob_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("id", name="pk_artifact_blob_pairs"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_artifact_blob_pairs_workspace_id"),
        sa.ForeignKeyConstraint(["pe_blob_id"], ["artifact_blobs.id"], name="fk_artifact_blob_pairs_pe_blob_id"),
        sa.ForeignKeyConstraint(["pdb_blob_id"], ["artifact_blobs.id"], name="fk_artifact_blob_pairs_pdb_blob_id"),
        sa.UniqueConstraint("workspace_id", "pe_blob_id", "pdb_blob_id", name="uq_artifact_blob_pairs_exact"),
        sa.CheckConstraint("state IN ('pending', 'published', 'rejected')", name="ck_artifact_blob_pairs_state"),
    )

    op.create_table(
        "artifact_blob_legacy_copies",
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("artifact_blob_id", sa.Text(), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("artifact_id", name="pk_artifact_blob_legacy_copies"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], name="fk_artifact_blob_legacy_copies_artifact_id"),
        sa.ForeignKeyConstraint(
            ["artifact_blob_id"], ["artifact_blobs.id"], name="fk_artifact_blob_legacy_copies_blob_id"
        ),
    )
    op.create_index(
        "ix_artifact_blob_legacy_copies_object_key",
        "artifact_blob_legacy_copies",
        ["object_key"],
    )

    op.create_table(
        "artifact_blob_backfill_gaps",
        sa.Column("artifact_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("artifact_id", name="pk_artifact_blob_backfill_gaps"),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], name="fk_artifact_blob_backfill_gaps_artifact_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_artifact_blob_backfill_gaps_workspace_id"
        ),
        sa.CheckConstraint("attempt_count > 0", name="ck_artifact_blob_backfill_gaps_attempt_count"),
    )
    op.create_index(
        "ix_artifact_blob_backfill_gaps_unresolved",
        "artifact_blob_backfill_gaps",
        ["resolved_at", "artifact_id"],
    )

    for table in ("task_intents", "task_executions"):
        op.drop_constraint(f"ck_{table}_type", table, type_="check")
        op.create_check_constraint(
            f"ck_{table}_type",
            table,
            "task_type IN ('verify_upload', 'ingest_artifact', "
            "'publish_artifact_blob_pair', 'reindex_symbols', 'analyze_occurrence')",
        )


def downgrade() -> None:
    # Sharing cannot be represented safely by the previous schema. Compatible
    # code rollback disables the feature and retains this additive schema.
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM artifacts WHERE artifact_blob_id IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM artifact_blobs) THEN "
            "RAISE EXCEPTION 'cannot downgrade after Artifact Blob data exists'; "
            "END IF; END $$"
        )
    )
    for table in ("task_intents", "task_executions"):
        op.drop_constraint(f"ck_{table}_type", table, type_="check")
        op.create_check_constraint(
            f"ck_{table}_type",
            table,
            "task_type IN ('verify_upload', 'ingest_artifact', 'reindex_symbols', 'analyze_occurrence')",
        )
    op.drop_constraint("ck_task_intents_schema_version", "task_intents", type_="check")
    op.create_check_constraint(
        "ck_task_intents_schema_version", "task_intents", "schema_version = '1.0'"
    )
    op.drop_index("ix_artifact_blob_backfill_gaps_unresolved", table_name="artifact_blob_backfill_gaps")
    op.drop_table("artifact_blob_backfill_gaps")
    op.drop_index(
        "ix_artifact_blob_legacy_copies_object_key",
        table_name="artifact_blob_legacy_copies",
    )
    op.drop_table("artifact_blob_legacy_copies")
    op.drop_table("artifact_blob_pairs")
    op.drop_table("artifact_blob_upload_claims")
    op.drop_index("ix_artifacts_artifact_blob_id", table_name="artifacts")
    op.drop_constraint("ck_artifacts_materialization_source", "artifacts", type_="check")
    op.drop_constraint("fk_artifacts_artifact_blob_id", "artifacts", type_="foreignkey")
    op.drop_column("artifacts", "materialization_source")
    op.drop_column("artifacts", "artifact_blob_id")
    op.drop_index("ix_artifact_blobs_debug_id", table_name="artifact_blobs")
    op.drop_index("ix_artifact_blobs_code_id", table_name="artifact_blobs")
    op.drop_table("artifact_blobs")
