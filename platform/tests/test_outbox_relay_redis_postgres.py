from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import TaskIntent, utcnow
from crashcap_api.queueing import DramatiqTaskDispatcher
from crashcap_api.task_handoff import stage_task_message
from crashcap_worker.outbox_relay import relay_once
from redis import Redis

ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "platform" / "migrations"


def _config(url: str) -> Config:
    config = Config(str(MIGRATIONS / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@pytest.mark.integration
def test_postgres_commit_survives_real_redis_outage_and_recovers() -> None:
    database_url = os.environ.get("CRASH_CAP_TEST_DATABASE_URL")
    redis_url = os.environ.get("CRASH_CAP_TEST_REDIS_URL")
    redis_container = os.environ.get("CRASH_CAP_TEST_REDIS_CONTAINER")
    if not database_url or not redis_url or not redis_container:
        pytest.skip(
            "set CRASH_CAP_TEST_DATABASE_URL, CRASH_CAP_TEST_REDIS_URL and "
            "CRASH_CAP_TEST_REDIS_CONTAINER for the outage gate"
        )

    settings = Settings.for_test(ROOT / ".runtime" / "g3-integration", database_url).model_copy(
        update={
            "create_schema": False,
            "queue_mode": "dramatiq",
            "redis_url": redis_url,
            "task_handoff_mode": "outbox",
            "task_receipt_mode": "strict",
            "relay_lease_seconds": 5,
            "relay_backoff_base_seconds": 1,
            "relay_backoff_max_seconds": 2,
        }
    )
    config = _config(database_url)
    command.upgrade(config, "head")
    database = Database(settings)
    dispatcher = DramatiqTaskDispatcher(settings)
    message = {
        "schema_version": "1.0",
        "task_type": "verify_upload",
        "upload_id": "upl_real_redis_outage",
        "attempt_id": "att_real_redis_outage",
        "queue": "verify",
    }
    redis_was_stopped = False
    try:
        Redis.from_url(redis_url).flushdb()
        with database.sessions() as session:
            stage_task_message(session, settings, message)
            session.commit()

        subprocess.run(  # noqa: S603, S607 - exact disposable container supplied by operator
            ["docker", "stop", redis_container],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        redis_was_stopped = True
        assert relay_once(database.sessions, dispatcher, settings, owner_id="relay-outage")
        with database.sessions() as session:
            intent = session.get(TaskIntent, message["attempt_id"])
            assert intent is not None
            assert intent.state == "pending"
            assert intent.last_error_code is not None
            assert intent.last_error_code.startswith("TRANSIENT_")

        subprocess.run(  # noqa: S603, S607 - exact disposable container supplied by operator
            ["docker", "start", redis_container],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        redis_was_stopped = False
        client = Redis.from_url(redis_url)
        for _ in range(50):
            try:
                if client.ping():
                    break
            except Exception:
                time.sleep(0.1)
        else:
            raise AssertionError("disposable Redis did not recover")

        with database.sessions() as session:
            intent = session.get(TaskIntent, message["attempt_id"])
            assert intent is not None
            intent.due_at = utcnow()
            session.commit()
        assert relay_once(database.sessions, dispatcher, settings, owner_id="relay-recovered")
        with database.sessions() as session:
            intent = session.get(TaskIntent, message["attempt_id"])
            assert intent is not None
            assert intent.state == "published"
            assert intent.delivery_attempts == 2
        queue_keys = list(client.scan_iter(match="dramatiq:*"))
        assert any(
            client.type(key) == b"list" and int(client.llen(key)) > 0 for key in queue_keys
        )
    finally:
        if redis_was_stopped:
            subprocess.run(  # noqa: S603, S607 - restore exact disposable test container
                ["docker", "start", redis_container],  # noqa: S607
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        database.dispose()
        command.downgrade(config, "base")
