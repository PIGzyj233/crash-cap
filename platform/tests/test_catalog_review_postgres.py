import os
from pathlib import Path
from uuid import uuid4

import pytest
from crashcap_api.app import create_app
from crashcap_api.config import Settings
from fastapi.testclient import TestClient

from . import test_catalog_review_api as cases
from . import test_symbol_catalog_postgres as catalog_tests
from .catalog_fixtures import admit_pair, origin, pair_evidence

pg = catalog_tests.pg
pytestmark = pytest.mark.skipif(
    not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL lane"
)


@pytest.mark.parametrize("case", ["replay", "readback", "enabled"])
def test_catalog_review_api_on_postgres(pg, tmp_path, monkeypatch, case):
    engine, _, _ = pg
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "database_url": engine.url.render_as_string(hide_password=False),
            "create_schema": False,
            "catalog_reviews_enabled": True,
        }
    )
    app = create_app(settings)
    try:
        with app.state.database.sessions.begin() as session:
            pe, pdb, locations = pair_evidence()
            pair_id = admit_pair(session, pe, pdb, locations, origin()).id
        with TestClient(app) as client:
            context = (app, client, pair_id)
            if case == "replay":
                cases.test_review_replay_conflict_history_and_integrity(context)
            elif case == "readback":
                cases.test_bad_evidence_readback_does_not_change_catalog(context, monkeypatch)
            else:
                cases.test_review_default_enabled_and_blank_evidence_rejected(tmp_path, context)
    finally:
        app.state.database.dispose()


@pytest.mark.parametrize("case", ["replay", "read_recovery"])
def test_catalog_review_evidence_on_postgres_and_s3(pg, tmp_path, monkeypatch, case):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "scripts/upload_v3"))
    from owned_browser_storage import owned_storage

    engine, _, _ = pg
    output = root / "target/qa-symbol-import/review-storage" / uuid4().hex
    with owned_storage(output) as (overrides, _, _):
        settings = Settings.model_validate(
            {
                **Settings.for_test(tmp_path).model_dump(),
                **overrides,
                "database_url": engine.url.render_as_string(hide_password=False),
                "create_schema": False,
                "catalog_reviews_enabled": True,
            }
        )
        app = create_app(settings)
        try:
            with app.state.database.sessions.begin() as session:
                pe, pdb, locations = pair_evidence()
                pair_id = admit_pair(session, pe, pdb, locations, origin()).id
            with TestClient(app) as client:
                context = (app, client, pair_id)
                if case == "replay":
                    cases.test_review_replay_conflict_history_and_integrity(context)
                else:
                    cases.test_review_read_interruption_never_returns_partial_evidence(
                        context, monkeypatch
                    )
        finally:
            app.state.database.dispose()
