import os

import pytest
from alembic import command
from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.models import OccurrenceSubmission
from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from . import test_symbol_catalog_postgres as catalog_tests
from .test_upload_v3 import CORE, DMP, space, upload

pg = catalog_tests.pg
pytestmark = pytest.mark.skipif(
    not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL lane"
)


def test_submission_migration_and_verified_api_history(pg, tmp_path):
    engine, sessions, config = pg
    assert {c["name"] for c in inspect(engine).get_columns("occurrence_submissions")} == set(
        OccurrenceSubmission.__table__.columns.keys()
    )
    settings = Settings.for_test(
        tmp_path, engine.url.render_as_string(hide_password=False)
    ).model_copy(update={"core_executor": "local", "core_command": str(CORE)})
    app = create_app(settings)
    with TestClient(app) as client:
        workspace = space(client, "submission-postgres")
        first = upload((app, client), DMP, workspace)
        second = upload((app, client), DMP, workspace, "v1")
        third = upload((app, client), DMP, workspace, "v2")
        assert first["occurrence_id"] == second["occurrence_id"] == third["occurrence_id"]
        assert third["version_conflict"] is True
    with pytest.raises(RuntimeError, match="Restore"):
        command.downgrade(config, "base")
    with sessions() as session:
        assert len(list(session.scalars(select(OccurrenceSubmission)))) == 3
