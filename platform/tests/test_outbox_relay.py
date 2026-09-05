from __future__ import annotations

import ast
from datetime import UTC, timedelta
from pathlib import Path
from typing import Any

import pytest
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import TaskIntent, utcnow
from crashcap_api.queueing import MemoryTaskDispatcher
from crashcap_api.task_handoff import (
    acknowledge_relay_publish,
    claim_relay_intent,
    create_task_intent,
    reject_relay_publish,
    stage_task_message,
)
from crashcap_worker.outbox_relay import relay_once
from prometheus_client import generate_latest

ROOT = Path(__file__).resolve().parents[2]


def _settings(tmp_path: Path) -> Settings:
    return Settings.for_test(tmp_path).model_copy(
        update={
            "task_handoff_mode": "outbox",
            "task_receipt_mode": "strict",
            "relay_lease_seconds": 5,
            "relay_backoff_base_seconds": 1,
            "relay_backoff_max_seconds": 8,
        }
    )


def _message(attempt_id: str = "att_outbox_test") -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "task_type": "verify_upload",
        "upload_id": "upl_outbox_test",
        "attempt_id": attempt_id,
        "queue": "verify",
        "request_id": "req_outbox_test",
    }


def test_outbox_commit_survives_absent_publisher_and_relays_later(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings)
    dispatcher = MemoryTaskDispatcher(settings)
    try:
        with database.sessions() as session:
            staged = stage_task_message(session, settings, _message())
            session.commit()
        assert dispatcher.snapshot() == []

        assert relay_once(database.sessions, dispatcher, settings, owner_id="relay-a") is True
        assert dispatcher.snapshot() == [staged]
        with database.sessions() as session:
            intent = session.get(TaskIntent, staged["attempt_id"])
            assert intent is not None
            assert intent.state == "published"
            assert intent.delivery_attempts == 1
        metrics = generate_latest().decode("utf-8")
        assert (
            'crashcap_relay_deliveries_total{outcome="published",task_type="verify_upload"}'
            in metrics
        )
    finally:
        database.dispose()


def test_publish_then_crash_is_reclaimed_as_an_at_least_once_duplicate(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings)
    dispatcher = MemoryTaskDispatcher(settings)

    class SimulatedCrash(RuntimeError):
        pass

    def crash(_claim: object) -> None:
        raise SimulatedCrash("publish accepted; process died before ack")

    try:
        with database.sessions() as session:
            stage_task_message(session, settings, _message())
            session.commit()
        with pytest.raises(SimulatedCrash):
            relay_once(
                database.sessions,
                dispatcher,
                settings,
                owner_id="relay-dead",
                after_publish=crash,
            )
        assert len(dispatcher.snapshot()) == 1
        with database.sessions() as session:
            intent = session.get(TaskIntent, "att_outbox_test")
            assert intent is not None and intent.state == "publishing"
            intent.relay_lease_until = utcnow() - timedelta(seconds=1)
            session.commit()

        assert relay_once(database.sessions, dispatcher, settings, owner_id="relay-reclaim")
        assert len(dispatcher.snapshot()) == 2
        with database.sessions() as session:
            intent = session.get(TaskIntent, "att_outbox_test")
            assert intent is not None
            assert intent.state == "published"
            assert intent.relay_generation == 2
            assert intent.delivery_attempts == 2
    finally:
        database.dispose()


def test_transient_publish_failure_returns_to_pending_with_backoff(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings)
    try:
        with database.sessions() as session:
            stage_task_message(session, settings, _message())
            claim = claim_relay_intent(
                session,
                settings.schema_root,
                owner_id="relay-a",
                now=utcnow(),
                lease_seconds=5,
            )
            assert claim is not None
            session.commit()
        failed_at = utcnow()
        with database.sessions() as session:
            assert reject_relay_publish(
                session,
                claim,
                "TRANSIENT_CONNECTIONERROR",
                permanent=False,
                backoff_base_seconds=2,
                backoff_max_seconds=8,
                now=failed_at,
            )
            session.commit()
        with database.sessions() as session:
            intent = session.get(TaskIntent, claim.attempt_id)
            assert intent is not None
            assert intent.state == "pending"
            assert intent.last_error_code == "TRANSIENT_CONNECTIONERROR"
            due_at = (
                intent.due_at
                if intent.due_at.tzinfo is not None
                else intent.due_at.replace(tzinfo=UTC)
            )
            assert due_at >= failed_at + timedelta(seconds=2)
        metrics = generate_latest().decode("utf-8")
        assert 'crashcap_relay_backoff_seconds_count{task_type="verify_upload"}' in metrics
    finally:
        database.dispose()


def test_relay_generation_fences_late_ack(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings)
    now = utcnow()
    try:
        with database.sessions() as session:
            create_task_intent(session, _message(), settings.schema_root, due_at=now)
            first = claim_relay_intent(
                session,
                settings.schema_root,
                owner_id="relay-first",
                lease_seconds=5,
                now=now,
            )
            assert first is not None
            session.commit()
        with database.sessions() as session:
            second = claim_relay_intent(
                session,
                settings.schema_root,
                owner_id="relay-second",
                lease_seconds=5,
                now=now + timedelta(seconds=6),
            )
            assert second is not None
            session.commit()
        with database.sessions() as session:
            assert acknowledge_relay_publish(session, first) is False
            assert acknowledge_relay_publish(session, second) is True
            session.commit()
    finally:
        database.dispose()


def test_invalid_persisted_message_is_permanent_poison(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    database = Database(settings)
    try:
        with database.sessions() as session:
            session.add(
                TaskIntent(
                    attempt_id="att_poison",
                    schema_version="1.0",
                    task_type="verify_upload",
                    queue="verify",
                    logical_key="upl_poison",
                    target_type="upload",
                    target_id="upl_poison",
                    message={"schema_version": "9.9", "task_type": "unknown"},
                    state="pending",
                    due_at=utcnow(),
                )
            )
            session.commit()
        with database.sessions() as session:
            assert (
                claim_relay_intent(
                    session,
                    settings.schema_root,
                    owner_id="relay-poison",
                )
                is None
            )
            session.commit()
        with database.sessions() as session:
            intent = session.get(TaskIntent, "att_poison")
            assert intent is not None
            assert intent.state == "dead"
            assert intent.last_error_code == "PERMANENT_INVALID_TASK_MESSAGE"
        metrics = generate_latest().decode("utf-8")
        assert 'crashcap_task_poisoned_total{source="relay",task_type="verify_upload"}' in metrics
    finally:
        database.dispose()


def test_low_level_enqueue_call_is_confined_to_queue_adapter() -> None:
    production_roots = (ROOT / "platform" / "api", ROOT / "platform" / "worker")
    allowed = ROOT / "platform" / "api" / "crashcap_api" / "queueing.py"
    violations: list[str] = []
    for production_root in production_roots:
        for path in production_root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "enqueue"
                    and path != allowed
                ):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []
