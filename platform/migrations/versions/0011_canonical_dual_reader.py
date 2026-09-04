"""Permit immutable Canonical 1.1 metadata; keep all writer defaults at 1.0."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_canonical_dual_reader"
down_revision: str | None = "0010_occurrence_browse"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _constraint(expression: str) -> None:
    with op.batch_alter_table("analysis_runs") as batch:
        batch.drop_constraint("ck_analysis_runs_schema_version", type_="check")
        batch.create_check_constraint("ck_analysis_runs_schema_version", expression)


def upgrade() -> None:
    _constraint("schema_version IN ('1.0', '1.1')")


def downgrade() -> None:
    # Never rewrite, delete or relabel historical results to fit an old reader.
    exists = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM analysis_runs WHERE schema_version <> '1.0' LIMIT 1"))
        .first()
    )
    if exists is not None:
        raise RuntimeError("Canonical 1.1 results exist; retain a compatible reader and schema")
    _constraint("schema_version = '1.0'")
