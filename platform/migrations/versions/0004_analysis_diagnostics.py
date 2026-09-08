"""Persist execution stages and retained failure evidence."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0004_analysis_diagnostics"
down_revision = "0003_missing_symbol_identity"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("analysis_runs", sa.Column("progress", JSONB(), nullable=True))
    op.add_column("analysis_runs", sa.Column("diagnostics", JSONB(), nullable=True))


def downgrade():
    raise RuntimeError("Restore a database backup to roll back retained execution diagnostics")
