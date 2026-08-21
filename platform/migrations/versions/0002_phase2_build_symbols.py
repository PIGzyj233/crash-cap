"""Add Phase 2 producer, source-bundle, and in-app rule metadata."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002_phase2_build_symbols"
down_revision: Union[str, None] = "0001_phase1_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workspaces",
        sa.Column(
            "in_app_rules",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{\"include_modules\":[],\"exclude_modules\":[]}'::jsonb"),
        ),
    )
    op.add_column(
        "workspaces",
        sa.Column("in_app_rule_version", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )
    op.create_check_constraint(
        "ck_workspaces_in_app_rule_version", "workspaces", "in_app_rule_version >= 0"
    )
    op.add_column("builds", sa.Column("producer", sa.Text(), nullable=True))
    op.add_column("builds", sa.Column("producer_build_id", sa.Text(), nullable=True))
    op.add_column("builds", sa.Column("manifest_schema_version", sa.Text(), nullable=True))
    op.add_column("builds", sa.Column("source_bundle_config", postgresql.JSONB(), nullable=True))
    op.create_check_constraint(
        "ck_builds_producer",
        "builds",
        "producer IS NULL OR producer IN ('msvc', 'clang-cl', 'crashpad')",
    )
    op.create_unique_constraint(
        "uq_builds_workspace_producer_id",
        "builds",
        ["workspace_id", "producer", "producer_build_id"],
    )
    op.add_column("artifacts", sa.Column("ingest_metadata", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("artifacts", "ingest_metadata")
    op.drop_constraint("uq_builds_workspace_producer_id", "builds", type_="unique")
    op.drop_constraint("ck_builds_producer", "builds", type_="check")
    op.drop_column("builds", "source_bundle_config")
    op.drop_column("builds", "manifest_schema_version")
    op.drop_column("builds", "producer_build_id")
    op.drop_column("builds", "producer")
    op.drop_constraint("ck_workspaces_in_app_rule_version", "workspaces", type_="check")
    op.drop_column("workspaces", "in_app_rule_version")
    op.drop_column("workspaces", "in_app_rules")
