"""Missing modules may have only a PE identity or only a PDB identity."""

from alembic import op

revision = "0003_missing_symbol_identity"
down_revision = "0002_user_auth"
branch_labels = None
depends_on = None


def upgrade():
    # References use the existing id/workspace unique keys, not the erroneous
    # composite primary key. Preserve rows, associations and workspace scope.
    op.drop_constraint("missing_symbols_pkey", "missing_symbols", type_="primary")
    op.create_primary_key("missing_symbols_pkey", "missing_symbols", ["id"])
    op.alter_column("missing_symbols", "code_id", nullable=True)
    op.alter_column("missing_symbols", "debug_id", nullable=True)


def downgrade():
    raise RuntimeError("Restore a database backup to roll back nullable module identities")
