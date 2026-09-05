"""Empty PostgreSQL baseline, with no reverse migration into deleted Build tables."""

import io
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from crashcap_api.models import Base

ROOT = Path(__file__).resolve().parents[1]


def config():
    value = Config(str(ROOT / "alembic.ini"))
    value.set_main_option("script_location", str(ROOT))
    value.set_main_option("sqlalchemy.url", "postgresql://unused@localhost/unused")
    return value


def test_one_empty_baseline_covers_every_model_and_no_build_tables():
    settings = config()
    revisions = list(ScriptDirectory.from_config(settings).walk_revisions())
    assert len(revisions) == 1 and revisions[0].revision == "0001_upload_v3"
    output = io.StringIO()
    settings.attributes["output_buffer"] = output
    command.upgrade(settings, "head", sql=True)
    sql = output.getvalue()
    for table in Base.metadata.tables:
        assert f"CREATE TABLE {table} (" in sql
    for obsolete in (
        "builds",
        "build_modules",
        "build_publications",
        "artifacts",
        "symbol_imports",
    ):
        assert f"CREATE TABLE {obsolete} (" not in sql
    assert "JSONB" in sql and "TIMESTAMP WITH TIME ZONE" in sql
    for history in (
        "result_reviews",
        "analysis_demand_restarts",
        "occurrence_version_audits",
        "catalog_files",
    ):
        assert history + "_immutable" in sql


def test_rollback_requires_whole_stack_restore():
    with pytest.raises(RuntimeError, match="[Rr]estore"):
        command.downgrade(config(), "0001_upload_v3:base", sql=True)
