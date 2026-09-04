import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from crashcap_api.models import ResultReview


def test_result_review_migration_retains_history_and_matches_model():
    path = Path(__file__).resolve().parents[1] / "migrations/versions" / "0022_result_reviews.py"
    spec = importlib.util.spec_from_file_location("result_review_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    try:
        # Parent FK behavior still requires owned PostgreSQL qualification.
        with (
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
        ):
            migration.upgrade()
            columns = sa.inspect(connection).get_columns("result_reviews")
            assert {item["name"] for item in columns} == set(ResultReview.__table__.columns.keys())
            migration.downgrade()
            migration.upgrade()
            table = sa.Table(
                "result_reviews", sa.MetaData(), autoload_with=connection, resolve_fks=False
            )
            row = {
                "id": "review_1",
                "occurrence_id": "occ_1",
                "current_run_id": "run_old",
                "candidate_run_id": "run_new",
                "idempotency_key": "one",
                "request_sha256": "a" * 64,
                "request": {},
                "audit_object_key": "reviews/one.json",
                "audit_sha256": "b" * 64,
                "cause": "engine_upgrade",
                "decision": "promote",
                "reason": "reviewed_transition",
                "current_evidence": {},
                "candidate_evidence": {},
                "differences": [],
            }
            connection.execute(table.insert().values(**row))
            for changes in (
                {"id": "review_2"},
                {"id": "review_2", "idempotency_key": "two", "candidate_run_id": "run_old"},
                {"id": "review_2", "idempotency_key": "two", "cause": "force"},
            ):
                with pytest.raises(sa.exc.IntegrityError):
                    connection.execute(table.insert().values(**{**row, **changes}))
            with pytest.raises(RuntimeError, match="Retained result review history"):
                migration.downgrade()
            assert connection.scalar(sa.select(sa.func.count()).select_from(table)) == 1
    finally:
        engine.dispose()
