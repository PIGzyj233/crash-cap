"""Allow native Canonical 1.1 grouping on frozen Runs."""

import sqlalchemy as sa
from alembic import op

revision = "0020_frozen_grouping"
down_revision = "0019_analysis_scheduler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_analysis_runs_grouping_version", "analysis_runs", type_="check")
    op.create_check_constraint(
        "ck_analysis_runs_grouping_version",
        "analysis_runs",
        "grouping_version = 'group-v1.0' OR "
        "(schema_version = '1.1' AND grouping_version = 'group-v1.1')",
    )


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM analysis_runs WHERE grouping_version = 'group-v1.1')")
    ):
        raise RuntimeError("Retained Canonical 1.1 grouping prevents downgrade")
    op.drop_constraint("ck_analysis_runs_grouping_version", "analysis_runs", type_="check")
    op.create_check_constraint(
        "ck_analysis_runs_grouping_version", "analysis_runs", "grouping_version = 'group-v1.0'"
    )
