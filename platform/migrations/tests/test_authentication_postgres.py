"""Migrate real anonymous rows, then verify attribution and immutable history on PostgreSQL."""

import os
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.skipif(
    not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL"
)


def test_backfill_preserves_history_and_prevents_attribution_changes():
    root = Path(__file__).resolve().parents[1]
    url = os.environ["QAI_CATALOG_DATABASE_URL"]
    schema = "auth_migration_" + uuid.uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = make_url(url).update_query_dict({"options": f"-csearch_path={schema}"})
    engine = create_engine(scoped)
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root))
    config.set_main_option(
        "sqlalchemy.url", scoped.render_as_string(hide_password=False).replace("%", "%%")
    )
    try:
        command.upgrade(config, "0001_upload_v3")
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO uploads (id,object_key,original_filename,declared_length,"
                    "wire_declared_length,file_kind,source) "
                    "VALUES ('upl_old','old/object','a.dll',12,12,'pe','cli')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO operation_logs (action,actor) "
                    "VALUES ('upload.initialize','anonymous')"
                )
            )
            connection.execute(text("INSERT INTO workspaces (id,name) VALUES ('wsp_old','old')"))
            connection.execute(
                text(
                    "INSERT INTO dump_blobs (id,workspace_id,sha256,size,object_key) "
                    "VALUES ('blob_old','wsp_old',:sha,12,'old/dmp')"
                ),
                {"sha": "a" * 64},
            )
            connection.execute(
                text(
                    "INSERT INTO occurrences (id,workspace_id,dump_blob_id,uploaded_at,"
                    "occurred_at,time_source) "
                    "VALUES ('occ_old','wsp_old','blob_old',"
                    "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'uploaded')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO occurrence_version_audits "
                    "(id,occurrence_id,old_version,new_version,source) "
                    "VALUES ('ova_old','occ_old','1','2','manual')"
                )
            )
        command.upgrade(config, "head")
        with engine.connect() as connection:
            upload = connection.execute(
                text("SELECT uploaded_by_user_id,uploaded_by_name,source FROM uploads")
            ).one()
            assert upload == ("usr_legacy", "历史未知用户", "cli")
            audit = connection.execute(
                text("SELECT old_version,new_version,actor_user_id FROM occurrence_version_audits")
            ).one()
            assert audit == ("1", "2", "usr_legacy")
            assert connection.scalar(text("SELECT auth_method FROM operation_logs")) == "legacy"
            assert connection.scalar(text("SELECT count(*) FROM users")) == 3
        with (
            pytest.raises(DBAPIError, match="attribution is immutable"),
            engine.begin() as connection,
        ):
            connection.execute(text("UPDATE uploads SET uploaded_by_user_id='usr_ci'"))
        with pytest.raises(DBAPIError, match="immutable history"), engine.begin() as connection:
            connection.execute(text("UPDATE occurrence_version_audits SET new_version='3'"))
        with engine.begin() as connection:
            connection.execute(text("UPDATE uploads SET verification_status='REJECTED'"))
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()
