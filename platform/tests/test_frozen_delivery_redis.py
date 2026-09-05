"""Real Redis delivery loss and late delivery against owned PostgreSQL."""

import json
import os
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import timedelta

import pytest
from crashcap_api.models import (
    AnalysisDemand,
    AnalysisExecutionSlot,
    AnalysisRun,
    TaskExecution,
    TaskIntent,
)
from crashcap_api.queueing import DramatiqTaskDispatcher
from crashcap_api.services.analysis_recovery import recover_expired_frozen_runs
from crashcap_api.services.analysis_scheduler import bind_execution_slot, claim_execution_slots
from crashcap_api.services.frozen_runs import adopt_frozen_run
from crashcap_worker.outbox_relay import relay_once
from redis import Redis
from redis.exceptions import ConnectionError
from sqlalchemy import select

from . import test_frozen_run_adoption as adoption_tests
from .test_analysis_demands import NOW
from .test_frozen_run_adoption import prepare

frozen = adoption_tests.frozen
pg = adoption_tests.pg

pytestmark = pytest.mark.skipif(
    not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL lane"
)


def docker(*args):
    return subprocess.run(  # noqa: S603 - fixed test commands and owned container IDs
        ["docker", *args],  # noqa: S607 - Docker CLI on the validation host
        check=True,
        capture_output=True,
        text=True,
        timeout=30,  # noqa: S607
    ).stdout.strip()


@pytest.fixture
def owned_redis():
    token = uuid.uuid4().hex
    image = json.loads(docker("image", "inspect", "redis:7.4.5-bookworm"))[0]["Id"]
    container = docker(
        "run",
        "--pull=never",
        "-d",
        "--name",
        "qai-delivery-" + token,
        "--label",
        "crashcap.qai.delivery=" + token,
        "--label",
        "crashcap.qai.delivery.run=" + os.environ.get("QAI_DELIVERY_RUN_TOKEN", token),
        "-p",
        "127.0.0.1::6379",
        image,
        "redis-server",
        "--save",
        "",
        "--appendonly",
        "no",
    )
    client = None
    try:
        address = docker("port", container, "6379/tcp")
        assert address.startswith("127.0.0.1:")
        url = "redis://" + address + "/0"
        client = Redis.from_url(url)
        for _ in range(50):
            try:
                if client.ping():
                    break
            except ConnectionError:
                pass
            time.sleep(0.1)
        else:
            raise AssertionError("owned Redis did not become ready")
        yield url, client
    finally:
        if client is not None:
            client.close()
        assert (
            docker(
                "inspect", container, "--format", '{{index .Config.Labels "crashcap.qai.delivery"}}'
            )
            == token
        )
        docker("rm", "-f", "-v", container)


def consume_in_fresh_process(settings, sessions, queue, *, timeout_seconds=15):
    with sessions() as session:
        url = session.get_bind().url.render_as_string(hide_password=False)
    configuration = settings.model_copy(
        update={"database_url": url, "create_schema": False}
    ).model_dump(mode="json")
    code = """
import json, os, sys
p = json.load(sys.stdin)
for key in list(os.environ):
    if key.startswith('CRASHCAP_'):
        del os.environ[key]
for key, value in p['settings'].items():
    if value is not None:
        os.environ['CRASHCAP_' + key.upper()] = (
            json.dumps(value) if isinstance(value, (dict, list, bool)) else str(value)
        )
from crashcap_worker.broker import configure_broker
broker = configure_broker()
from crashcap_worker import tasks
from dramatiq import Worker
worker = Worker(broker, queues={p['queue']}, worker_threads=1)
try:
    worker.start()
    broker.join(p['queue'], timeout=p['timeout_seconds'] * 1000)
    worker.join()
finally:
    worker.stop(timeout=5000)
    broker.close()
print('drained')
"""
    result = subprocess.run(  # noqa: S603 - fixed code; configuration passed only through stdin
        [sys.executable, "-c", code],
        input=json.dumps(
            {"settings": configuration, "queue": queue, "timeout_seconds": timeout_seconds}
        ),
        text=True,
        capture_output=True,
        timeout=timeout_seconds + 15,
        check=False,
    )
    assert result.returncode == 0, result.stderr.replace(url, "<database>")
    assert result.stdout.strip() == "drained"


@contextmanager
def resident_planner_process(settings, sessions, log_path):
    """Run the production resident entry point against this test's isolated schema."""
    with sessions() as session:
        url = session.get_bind().url.render_as_string(hide_password=False)
    configuration = settings.model_copy(
        update={"database_url": url, "create_schema": False}
    ).model_dump(mode="json")
    code = """
import json, os, sys
p = json.load(sys.stdin)
for key in list(os.environ):
    if key.startswith('CRASHCAP_'):
        del os.environ[key]
for key, value in p.items():
    if value is not None:
        os.environ['CRASHCAP_' + key.upper()] = (
            json.dumps(value) if isinstance(value, (dict, list, bool)) else str(value)
        )
from crashcap_worker.automatic_main import run
run()
"""
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(  # noqa: S603 - fixed entry point with isolated settings on stdin
            [sys.executable, "-c", code],
            stdin=subprocess.PIPE,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            process.stdin.write(json.dumps(configuration))
            process.stdin.close()
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=15)


@pytest.mark.parametrize("budget,expected", [(1, "retry_exhausted"), (3, "retry_wait")])
def test_real_frozen_delivery_loss_and_late_message(frozen, owned_redis, budget, expected):
    settings, sessions = frozen
    url, client = owned_redis
    settings = settings.model_copy(
        update={
            "automatic_analysis_enabled": True,
            "evidence_promotion_enabled": True,
            "analysis_max_attempts": budget,
            "automatic_analysis_delivery_timeout_seconds": 30,
            "queue_mode": "dramatiq",
            "redis_url": url,
        }
    )
    demand_id, prepared = prepare(sessions, valid_ids=True)
    with sessions.begin() as session:
        slot = claim_execution_slots(session, settings, owner_id="delivery-test", now=NOW)[0]
        created = adopt_frozen_run(session, settings, demand_id, prepared, now=NOW)
        bind_execution_slot(session, slot, created.run.id, now=NOW)
        message = dict(created.intent.message)
    dispatcher = DramatiqTaskDispatcher(settings)
    try:
        assert relay_once(sessions, dispatcher, settings, owner_id="real-redis-relay")
        consumer = dispatcher.broker.consume(message["queue"], timeout=1000)
        try:
            delivered = next(consumer)
            assert delivered is not None
            assert delivered.args == (message,)
        finally:
            consumer.close()
        # Remove the real queued delivery. Keep the decoded payload to model a
        # delayed duplicate after the recovery transaction has committed.
        client.flushdb()
        assert client.dbsize() == 0
        with sessions.begin() as session:
            intent = session.get(TaskIntent, message["attempt_id"])
            assert intent.state == "published"
            expired = intent.published_at + timedelta(seconds=31)
            assert recover_expired_frozen_runs(session, settings, now=expired) == 1
            recovered_attempt = session.get(AnalysisDemand, demand_id).retry_attempt
        dispatcher.enqueue(delivered.args[0])
        dispatcher.enqueue(delivered.args[0])
        consume_in_fresh_process(settings, sessions, message["queue"])
        with sessions.begin() as session:
            execution = session.scalar(
                select(TaskExecution).where(
                    TaskExecution.logical_key == message["run_id"],
                    TaskExecution.task_type == "analyze_frozen_run",
                )
            )
            assert execution.outcome == "dead"
            run = session.get(AnalysisRun, message["run_id"])
            assert run.status == "FAILED"
            assert run.error_code == "FROZEN_DELIVERY_UNCLAIMED_TIMEOUT"
            assert run.result_object_key is None
            assert run.winner_attempt_id is None
            assert session.get(AnalysisDemand, demand_id).state == expected
            assert session.get(AnalysisDemand, demand_id).retry_attempt == recovered_attempt
            assert session.get(AnalysisExecutionSlot, demand_id) is None
            assert recover_expired_frozen_runs(session, settings, now=expired) == 0
    finally:
        dispatcher.broker.close()
