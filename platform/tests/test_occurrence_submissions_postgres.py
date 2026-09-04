import os

import pytest
from alembic import command
from crashcap_api.models import OccurrenceSubmission
from sqlalchemy import inspect, select

from . import test_symbol_catalog_postgres as catalog_tests
from . import test_upload_analysis_demand as upload_tests

pg = catalog_tests.pg
pytestmark = pytest.mark.skipif(
    not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL lane"
)


def test_submission_migration_and_verified_api_history(pg, tmp_path):
    engine, sessions, config = pg
    assert {c["name"] for c in inspect(engine).get_columns("occurrence_submissions")} == set(
        OccurrenceSubmission.__table__.columns.keys()
    )
    command.downgrade(config, "0020_frozen_grouping")
    assert "occurrence_submissions" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    upload_tests.test_accepted_duplicate_dump_uses_one_demand_when_automatic_enabled(
        tmp_path, True, database_url=engine.url.render_as_string(hide_password=False)
    )
    with pytest.raises(RuntimeError, match="Retained submission history"):
        command.downgrade(config, "0020_frozen_grouping")
    with sessions() as session:
        assert len(list(session.scalars(select(OccurrenceSubmission)))) == 3
