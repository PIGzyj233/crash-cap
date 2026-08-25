from __future__ import annotations

from datetime import timedelta

import pytest
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import TaskExecution, TaskIntent, utcnow
from crashcap_api.task_handoff import (
    TaskReceiptError,
    claim_task,
    create_task_intent,
    finish_claim,
    heartbeat_claim,
    request_task_redelivery,
    stage_task_message,
)
from prometheus_client import generate_latest


def _message() -> dict[str, str]:
    return {
        "schema_version": "1.0",
        "task_type": "analyze_occurrence",
        "run_id": "run_handoff_test",
        "attempt_id": "att_handoff_test",
        "queue": "dump-small",
        "request_id": "req_handoff_test",
    }


def test_claim_reclaim_and_fencing_are_generation_scoped(tmp_path: object) -> None:
    settings = Settings.for_test(tmp_path)  # type: ignore[arg-type]
    database = Database(settings)
    now = utcnow()
    try:
        with database.sessions() as session:
            first = claim_task(
                session,
                _message(),
                settings.schema_root,
                owner_id="worker-a",
                now=now,
                lease_seconds=60,
            )
            session.commit()
        assert first.acquired is True
        assert first.generation == 1

        with database.sessions() as session:
            duplicate = claim_task(
                session,
                _message(),
                settings.schema_root,
                owner_id="worker-b",
                now=now + timedelta(seconds=10),
                lease_seconds=60,
            )
            session.commit()
        assert duplicate.acquired is False
        assert duplicate.reason == "active_lease"

        with database.sessions() as session:
            assert heartbeat_claim(
                session,
                first,
                lease_seconds=60,
                now=now + timedelta(seconds=20),
            )
            session.commit()

        with database.sessions() as session:
            second = claim_task(
                session,
                _message(),
                settings.schema_root,
                owner_id="worker-b",
                now=now + timedelta(seconds=81),
                lease_seconds=60,
            )
            session.commit()
        assert second.acquired is True
        assert second.generation == 2

        with database.sessions() as session:
            assert (
                heartbeat_claim(
                    session,
                    first,
                    lease_seconds=60,
                    now=now + timedelta(seconds=82),
                )
                is False
            )

        with database.sessions() as session:
            assert finish_claim(session, first, "succeeded") is False
            assert finish_claim(session, second, "succeeded") is True
            session.commit()

        with database.sessions() as session:
            terminal_duplicate = claim_task(
                session,
                _message(),
                settings.schema_root,
                owner_id="worker-c",
                now=now + timedelta(seconds=200),
                lease_seconds=60,
            )
            execution = session.get(
                TaskExecution,
                {"task_type": "analyze_occurrence", "logical_key": "run_handoff_test"},
            )
        assert terminal_duplicate.acquired is False
        assert terminal_duplicate.reason == "already_succeeded"
        assert execution is not None and execution.generation == 2
        metrics = generate_latest().decode("utf-8")
        assert (
            'crashcap_task_heartbeats_total{outcome="accepted",task_type="analyze_occurrence"}'
            in metrics
        )
        assert (
            'crashcap_task_heartbeats_total{outcome="rejected_stale",task_type="analyze_occurrence"}'
            in metrics
        )
    finally:
        database.dispose()


def test_strict_receipt_requires_a_preexisting_durable_intent(tmp_path: object) -> None:
    settings = Settings.for_test(tmp_path)  # type: ignore[arg-type]
    database = Database(settings)
    try:
        with (
            database.sessions() as session,
            pytest.raises(TaskReceiptError, match="no durable intent"),
        ):
            claim_task(
                session,
                _message(),
                settings.schema_root,
                receipt_mode="strict",
            )

        with database.sessions() as session:
            intent = create_task_intent(session, _message(), settings.schema_root)
            session.commit()
            attempt_id = intent.attempt_id
        with database.sessions() as session:
            claim = claim_task(
                session,
                _message(),
                settings.schema_root,
                receipt_mode="strict",
                owner_id="worker-strict",
            )
            session.commit()
        assert claim.acquired is True
        assert claim.attempt_id == attempt_id
    finally:
        database.dispose()


def test_logical_duplicate_reuses_intent_but_conflicting_route_is_poison(tmp_path: object) -> None:
    settings = Settings.for_test(tmp_path)  # type: ignore[arg-type]
    database = Database(settings)
    try:
        with database.sessions() as session:
            first = create_task_intent(session, _message(), settings.schema_root)
            replay = {**_message(), "attempt_id": "att_replayed", "request_id": "req_replayed"}
            second = create_task_intent(session, replay, settings.schema_root)
            session.commit()
            assert first.attempt_id == second.attempt_id
            assert session.query(TaskIntent).count() == 1

        invalid = {**_message(), "queue": "dump-large"}
        with (
            database.sessions() as session,
            pytest.raises(TaskReceiptError, match="durable routing intent"),
        ):
            create_task_intent(session, invalid, settings.schema_root)
    finally:
        database.dispose()


def test_staged_intent_rolls_back_with_its_business_transaction(tmp_path: object) -> None:
    settings = Settings.for_test(tmp_path).model_copy(  # type: ignore[arg-type]
        update={"task_handoff_mode": "outbox"}
    )
    database = Database(settings)
    try:
        with database.sessions() as session:
            stage_task_message(session, settings, _message())
            session.rollback()
        with database.sessions() as session:
            assert session.query(TaskIntent).count() == 0
    finally:
        database.dispose()


def test_retry_reuses_pending_or_active_attempt_and_reopens_only_after_lease(
    tmp_path: object,
) -> None:
    settings = Settings.for_test(tmp_path)  # type: ignore[arg-type]
    database = Database(settings)
    now = utcnow()
    try:
        with database.sessions() as session:
            intent = create_task_intent(session, _message(), settings.schema_root, due_at=now)
            pending = request_task_redelivery(
                session,
                {**_message(), "attempt_id": "att_retry_generated"},
                settings.schema_root,
                now=now,
            )
            session.commit()
        assert pending.message["attempt_id"] == intent.attempt_id
        assert pending.dispatch_state == "pending"
        assert pending.reopened is False

        with database.sessions() as session:
            claim = claim_task(
                session,
                _message(),
                settings.schema_root,
                owner_id="worker-live",
                lease_seconds=60,
                now=now,
            )
            session.commit()
        with database.sessions() as session:
            active = request_task_redelivery(
                session,
                {**_message(), "attempt_id": "att_retry_active"},
                settings.schema_root,
                now=now + timedelta(seconds=30),
            )
            session.commit()
        assert active.dispatch_state == "active_lease"
        assert active.message["attempt_id"] == claim.attempt_id

        with database.sessions() as session:
            intent = session.get(TaskIntent, claim.attempt_id)
            assert intent is not None
            intent.state = "published"
            expired = request_task_redelivery(
                session,
                {**_message(), "attempt_id": "att_retry_expired"},
                settings.schema_root,
                now=now + timedelta(seconds=61),
            )
            session.commit()
        assert expired.dispatch_state == "reopened"
        assert expired.reopened is True
        assert expired.message["attempt_id"] == claim.attempt_id
    finally:
        database.dispose()
