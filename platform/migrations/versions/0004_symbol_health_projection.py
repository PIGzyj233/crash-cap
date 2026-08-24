"""Add durable Current Analysis based Symbol Health projection tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004_symbol_health_projection"
down_revision: str | None = "0003_durable_task_handoff"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("missing_symbols", sa.Column("id", sa.Text(), nullable=True))
    op.add_column("missing_symbols", sa.Column("identity_key", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_missing_symbols_id", "missing_symbols", ["id"])
    op.create_unique_constraint(
        "uq_missing_symbols_workspace_identity",
        "missing_symbols",
        ["workspace_id", "identity_key"],
    )
    op.create_unique_constraint(
        "uq_missing_symbols_id_workspace", "missing_symbols", ["id", "workspace_id"]
    )
    op.create_unique_constraint(
        "uq_occurrences_id_workspace", "occurrences", ["id", "workspace_id"]
    )

    op.create_table(
        "missing_symbol_occurrences",
        sa.Column("missing_symbol_id", sa.Text(), nullable=False),
        sa.Column("occurrence_id", sa.Text(), nullable=False),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("analysis_run_id", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("code_file", sa.Text(), nullable=True),
        sa.Column("debug_file", sa.Text(), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["missing_symbol_id", "workspace_id"],
            ["missing_symbols.id", "missing_symbols.workspace_id"],
            name="fk_missing_symbol_occurrences_symbol_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["occurrence_id", "workspace_id"],
            ["occurrences.id", "occurrences.workspace_id"],
            name="fk_missing_symbol_occurrences_occurrence_workspace",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_run_id", "occurrence_id"],
            ["analysis_runs.id", "analysis_runs.occurrence_id"],
            name="fk_missing_symbol_occurrences_run_occurrence",
        ),
        sa.PrimaryKeyConstraint(
            "missing_symbol_id", "occurrence_id", name="pk_missing_symbol_occurrences"
        ),
        sa.CheckConstraint(
            "reason IN ('missing_pe', 'missing_pdb', 'pdb_mismatch', 'pe_mismatch')",
            name="ck_missing_symbol_occurrences_reason",
        ),
    )
    op.create_index(
        "ix_missing_symbol_occurrences_workspace",
        "missing_symbol_occurrences",
        ["workspace_id"],
    )
    op.create_index(
        "ix_missing_symbol_occurrences_occurrence",
        "missing_symbol_occurrences",
        ["occurrence_id"],
    )
    op.create_index(
        "ix_missing_symbol_occurrences_run",
        "missing_symbol_occurrences",
        ["analysis_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_missing_symbol_occurrences_run", table_name="missing_symbol_occurrences")
    op.drop_index(
        "ix_missing_symbol_occurrences_occurrence", table_name="missing_symbol_occurrences"
    )
    op.drop_index(
        "ix_missing_symbol_occurrences_workspace", table_name="missing_symbol_occurrences"
    )
    op.drop_table("missing_symbol_occurrences")
    op.drop_constraint("uq_occurrences_id_workspace", "occurrences", type_="unique")
    op.drop_constraint("uq_missing_symbols_id_workspace", "missing_symbols", type_="unique")
    op.drop_constraint("uq_missing_symbols_workspace_identity", "missing_symbols", type_="unique")
    op.drop_constraint("uq_missing_symbols_id", "missing_symbols", type_="unique")
    op.drop_column("missing_symbols", "identity_key")
    op.drop_column("missing_symbols", "id")
