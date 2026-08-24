from __future__ import annotations

import os
from pathlib import Path

import pytest
from crashcap_api.config import Settings
from crashcap_api.ids import new_id, new_ulid
from crashcap_api.queueing import DramatiqTaskDispatcher
from redis import Redis


@pytest.mark.compose
def test_redis_message_survives_dispatcher_restart() -> None:
    redis_url = os.environ.get("CRASHCAP_TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("set CRASHCAP_TEST_REDIS_URL to an isolated disposable Redis database")

    settings = Settings.for_test(Path(".runtime/redis-gate")).model_copy(
        update={"queue_mode": "dramatiq", "redis_url": redis_url}
    )
    cleanup = Redis.from_url(redis_url)
    cleanup.flushdb()
    try:
        first = DramatiqTaskDispatcher(settings)
        message = {
            "schema_version": "1.0",
            "task_type": "verify_upload",
            "upload_id": new_id("upl"),
            "attempt_id": f"att_{new_ulid()}",
            "queue": "verify",
        }
        try:
            first.enqueue(message)
            assert first.broker.do_qsize("verify") == 1
        finally:
            first.broker.close()

        restarted = DramatiqTaskDispatcher(settings)
        consumer = restarted.broker.consume("verify", prefetch=1, timeout=1_000)
        try:
            assert restarted.broker.do_qsize("verify") == 1
            queued = next(consumer)
            assert queued.actor_name == "verify_upload"
            assert queued.args == (message,)
            consumer.ack(queued)
            assert restarted.broker.do_qsize("verify") == 0
        finally:
            consumer.close()
            restarted.broker.close()
    finally:
        cleanup.flushdb()
        cleanup.close()
