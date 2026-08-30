"""Add read-path indexes for platform overview and Occurrence browsing."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager

import sqlalchemy as sa
from alembic import op

revision: str = "0010_occurrence_browse"
down_revision: str | None = "0009_delivery_v2_wire"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


@contextmanager
def _index_ddl_scope() -> Iterator[None]:
    if op.get_context().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            yield
        return
    yield


def _postgresql_options() -> dict[str, bool]:
    return {"postgresql_concurrently": True} if op.get_context().dialect.name == "postgresql" else {}


def upgrade() -> None:
    options = _postgresql_options()
    with _index_ddl_scope():
        op.create_index(
            "ix_occurrences_workspace_occurred_id",
            "occurrences",
            ["workspace_id", sa.text("occurred_at DESC"), sa.text("id DESC")],
            **options,
        )
        op.create_index(
            "ix_analysis_runs_occurrence_id_desc",
            "analysis_runs",
            ["occurrence_id", sa.text("id DESC")],
            **options,
        )
        op.create_index(
            "ix_uploads_workspace_dmp_status_uploaded",
            "uploads",
            [
                "workspace_id",
                "file_kind",
                "verification_status",
                sa.text("uploaded_at DESC"),
            ],
            **options,
        )


def downgrade() -> None:
    # Keep the rollback transactional.  A concurrent DROP commits outside
    # Alembic's surrounding transaction; if a lower revision's data guard then
    # rejects the rollback, the database can remain stamped at this revision
    # even though these indexes have already disappeared.
    op.drop_index(
        "ix_uploads_workspace_dmp_status_uploaded",
        table_name="uploads",
    )
    op.drop_index(
        "ix_analysis_runs_occurrence_id_desc",
        table_name="analysis_runs",
    )
    op.drop_index(
        "ix_occurrences_workspace_occurred_id",
        table_name="occurrences",
    )
