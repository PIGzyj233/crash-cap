"""Durable historical catalog admission outcomes; no historical data migration."""

from alembic import op
from sqlalchemy import text

revision = "0014_catalog_backfill"
down_revision = "0013_symbol_imports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""CREATE TABLE symbol_catalog_backfill (
        id CHAR(64) PRIMARY KEY, locator JSONB NOT NULL, source_fingerprint CHAR(64) NOT NULL,
        outcome TEXT NOT NULL, pair_id CHAR(64) REFERENCES catalog_pairs(id), reason TEXT,
        attempt_count INTEGER NOT NULL, checked_at TIMESTAMPTZ NOT NULL,
        CONSTRAINT ck_symbol_catalog_backfill_outcome CHECK(outcome IN ('admitted','rejected','retryable')),
        CONSTRAINT ck_symbol_catalog_backfill_attempts CHECK(attempt_count > 0),
        CONSTRAINT ck_symbol_catalog_backfill_pair CHECK(outcome <> 'admitted' OR pair_id IS NOT NULL)
    )""")
    op.create_index("ix_symbol_catalog_backfill_gaps", "symbol_catalog_backfill", ["outcome", "id"])


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(text("SELECT EXISTS(SELECT 1 FROM symbol_catalog_backfill)"))
        .scalar_one()
    ):
        raise RuntimeError("Retained catalog backfill outcomes require the compatible schema")
    op.drop_table("symbol_catalog_backfill")
