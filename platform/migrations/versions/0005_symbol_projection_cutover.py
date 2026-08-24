"""Add resumable Symbol Health projection cutover support."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0005_symbol_projection_cutover"
down_revision: str | None = "0004_symbol_health_projection"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The legacy NULLS NOT DISTINCT key merges every double-null module in a
    # Workspace.  The accepted projection identity intentionally splits those
    # rows by normalized filenames, so only the new workspace/identity key can
    # remain authoritative.
    op.drop_constraint(
        "uq_missing_symbols_workspace_debug_code", "missing_symbols", type_="unique"
    )
    op.create_index(
        "ix_missing_symbol_occurrences_workspace_symbol_occurrence",
        "missing_symbol_occurrences",
        ["workspace_id", "missing_symbol_id", "occurrence_id"],
    )

    op.create_table(
        "symbol_projection_states",
        sa.Column("occurrence_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("analysis_run_id", sa.Text(), nullable=False),
        sa.Column("identity_digest", sa.CHAR(length=64), nullable=False),
        sa.Column("missing_count", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "projected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("occurrence_id", name="pk_symbol_projection_states"),
        sa.ForeignKeyConstraint(
            ["occurrence_id", "workspace_id"],
            ["occurrences.id", "occurrences.workspace_id"],
            name="fk_symbol_projection_states_occurrence_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id", "occurrence_id"],
            ["analysis_runs.id", "analysis_runs.occurrence_id"],
            name="fk_symbol_projection_states_run_occurrence",
        ),
        sa.CheckConstraint(
            "missing_count >= 0", name="ck_symbol_projection_states_missing_count"
        ),
        sa.CheckConstraint(
            "source IN ('promotion', 'backfill')", name="ck_symbol_projection_states_source"
        ),
    )
    op.create_index(
        "ix_symbol_projection_states_workspace_run",
        "symbol_projection_states",
        ["workspace_id", "analysis_run_id"],
    )

    op.create_table(
        "symbol_projection_checkpoints",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("cursor_occurrence_id", sa.Text(), nullable=True),
        sa.Column("scanned_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("projected_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("gap_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("name", name="pk_symbol_projection_checkpoints"),
        sa.CheckConstraint(
            "scanned_count >= 0", name="ck_symbol_projection_checkpoints_scanned"
        ),
        sa.CheckConstraint(
            "projected_count >= 0", name="ck_symbol_projection_checkpoints_projected"
        ),
        sa.CheckConstraint("gap_count >= 0", name="ck_symbol_projection_checkpoints_gap"),
    )

    op.create_table(
        "symbol_projection_gaps",
        sa.Column("occurrence_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("analysis_run_id", sa.Text(), nullable=True),
        sa.Column("result_object_key", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("occurrence_id", name="pk_symbol_projection_gaps"),
        sa.ForeignKeyConstraint(
            ["occurrence_id", "workspace_id"],
            ["occurrences.id", "occurrences.workspace_id"],
            name="fk_symbol_projection_gaps_occurrence_workspace",
        ),
        sa.CheckConstraint("attempt_count > 0", name="ck_symbol_projection_gaps_attempt_count"),
    )
    op.create_index(
        "ix_symbol_projection_gaps_unresolved",
        "symbol_projection_gaps",
        ["resolved_at", "occurrence_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_symbol_projection_gaps_unresolved", table_name="symbol_projection_gaps")
    op.drop_table("symbol_projection_gaps")
    op.drop_table("symbol_projection_checkpoints")
    op.drop_index(
        "ix_symbol_projection_states_workspace_run", table_name="symbol_projection_states"
    )
    op.drop_table("symbol_projection_states")
    op.drop_index(
        "ix_missing_symbol_occurrences_workspace_symbol_occurrence",
        table_name="missing_symbol_occurrences",
    )
    # Downgrade is only safe before split identities have been materialized.
    # Production rollback uses compatible code/flags and never schema downgrade.
    op.execute(
        sa.text(
            "ALTER TABLE missing_symbols "
            "ADD CONSTRAINT uq_missing_symbols_workspace_debug_code "
            "UNIQUE NULLS NOT DISTINCT (workspace_id, debug_id, code_id)"
        )
    )
