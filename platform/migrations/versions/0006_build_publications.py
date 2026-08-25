"""Add content-identified Builds and idempotent Build Publications."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006_build_publications"
down_revision: str | None = "0005_symbol_projection_cutover"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "builds",
        sa.Column(
            "identity_mode",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'legacy'"),
        ),
    )
    op.add_column("builds", sa.Column("fingerprint_version", sa.Text(), nullable=True))
    op.add_column("builds", sa.Column("content_fingerprint", sa.CHAR(length=64), nullable=True))
    op.add_column("builds", sa.Column("sealed_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_builds_identity_mode",
        "builds",
        "identity_mode IN ('legacy', 'content_v1')",
    )
    op.create_check_constraint(
        "ck_builds_content_identity",
        "builds",
        "(identity_mode = 'legacy' AND fingerprint_version IS NULL "
        "AND content_fingerprint IS NULL AND sealed_at IS NULL) OR "
        "(identity_mode = 'content_v1' AND fingerprint_version = 'build-content-v1' "
        "AND content_fingerprint IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_builds_content_fingerprint",
        "builds",
        "content_fingerprint IS NULL OR content_fingerprint ~ '^[0-9a-f]{64}$'",
    )
    op.create_unique_constraint(
        "uq_builds_workspace_content_fingerprint",
        "builds",
        ["workspace_id", "fingerprint_version", "content_fingerprint"],
    )
    op.create_unique_constraint(
        "uq_build_modules_build_id_id", "build_modules", ["build_id", "id"]
    )

    op.create_table(
        "build_publications",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("build_id", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("client_publication_id", sa.Text(), nullable=False),
        sa.Column("client_version", sa.Text(), nullable=False),
        sa.Column("git_revision", sa.Text(), nullable=True),
        sa.Column("git_worktree_state", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
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
        sa.PrimaryKeyConstraint("id", name="pk_build_publications"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], name="fk_build_publications_workspace_id"
        ),
        sa.ForeignKeyConstraint(
            ["build_id"], ["builds.id"], name="fk_build_publications_build_id"
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "origin",
            "client_publication_id",
            name="uq_build_publications_client_identity",
        ),
        sa.CheckConstraint(
            "origin IN ('local', 'ci')", name="ck_build_publications_origin"
        ),
        sa.CheckConstraint(
            "git_worktree_state IN ('clean', 'dirty', 'unknown')",
            name="ck_build_publications_git_state",
        ),
    )
    op.create_index(
        "ix_build_publications_build_created",
        "build_publications",
        ["build_id", sa.text("created_at DESC")],
    )
    op.create_index(
        "ix_build_publications_workspace_created",
        "build_publications",
        ["workspace_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "build_artifact_expectations",
        sa.Column("build_id", sa.Text(), nullable=False),
        sa.Column("module_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("logical_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.CHAR(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint(
            "build_id", "module_id", "kind", name="pk_build_artifact_expectations"
        ),
        sa.ForeignKeyConstraint(
            ["build_id"], ["builds.id"], name="fk_build_artifact_expectations_build_id"
        ),
        sa.ForeignKeyConstraint(
            ["build_id", "module_id"],
            ["build_modules.build_id", "build_modules.id"],
            name="fk_build_artifact_expectations_build_module",
        ),
        sa.UniqueConstraint(
            "build_id",
            "kind",
            "normalized_name",
            name="uq_build_artifact_expectations_logical_name",
        ),
        sa.CheckConstraint(
            "kind IN ('pe', 'pdb')", name="ck_build_artifact_expectations_kind"
        ),
        sa.CheckConstraint("size > 0", name="ck_build_artifact_expectations_size"),
        sa.CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'", name="ck_build_artifact_expectations_sha256"
        ),
    )

    op.add_column("uploads", sa.Column("rejection_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    # A content Build cannot be represented by the old mutable model. Operators
    # roll back compatible code/flags and retain this additive schema.
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM builds WHERE identity_mode = 'content_v1') THEN "
            "RAISE EXCEPTION 'cannot downgrade after content Builds exist'; "
            "END IF; END $$"
        )
    )
    op.drop_column("uploads", "rejection_reason")
    op.drop_table("build_artifact_expectations")
    op.drop_constraint("uq_build_modules_build_id_id", "build_modules", type_="unique")
    op.drop_index(
        "ix_build_publications_workspace_created", table_name="build_publications"
    )
    op.drop_index("ix_build_publications_build_created", table_name="build_publications")
    op.drop_table("build_publications")
    op.drop_constraint("uq_builds_workspace_content_fingerprint", "builds", type_="unique")
    op.drop_constraint("ck_builds_content_fingerprint", "builds", type_="check")
    op.drop_constraint("ck_builds_content_identity", "builds", type_="check")
    op.drop_constraint("ck_builds_identity_mode", "builds", type_="check")
    op.drop_column("builds", "sealed_at")
    op.drop_column("builds", "content_fingerprint")
    op.drop_column("builds", "fingerprint_version")
    op.drop_column("builds", "identity_mode")
