from __future__ import annotations

import os
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from crashcap_api.models import TaskExecution, TaskIntent, utcnow
from crashcap_api.task_handoff import (
    RelayClaim,
    TaskClaim,
    acknowledge_relay_publish,
    claim_relay_intent,
    claim_task,
    create_task_intent,
    finish_claim,
)
from sqlalchemy.orm import Session, sessionmaker

from .test_symbol_catalog_postgres import pg as postgres_fixture

ROOT = Path(__file__).resolve().parents[2]
pg = postgres_fixture
pytestmark = pytest.mark.skipif(
    not os.getenv("QAI_CATALOG_DATABASE_URL"), reason="requires owned PostgreSQL"
)


@pytest.mark.integration
def test_postgres_serializes_concurrent_claim_and_reclaim(pg) -> None:
    _, sessions, _ = pg
    message = {
        "schema_version": "1.2",
        "task_type": "analyze_frozen_run",
        "run_id": "run_postgres_claim",
        "attempt_id": "att_postgres_claim",
        "queue": "dump-small",
    }
    with sessions() as session:
        create_task_intent(session, message, ROOT / "contracts")
        session.commit()

    first_round = _concurrent_claims(sessions, message, "first")
    winners = [claim for claim in first_round if claim.acquired]
    assert len(winners) == 1
    assert winners[0].generation == 1
    assert {claim.reason for claim in first_round if not claim.acquired} == {"active_lease"}

    with sessions() as session:
        execution = session.get(
            TaskExecution,
            {"task_type": "analyze_frozen_run", "logical_key": "run_postgres_claim"},
        )
        assert execution is not None
        execution.lease_until = None
        session.commit()

    second_round = _concurrent_claims(sessions, message, "second")
    reclaimed = [claim for claim in second_round if claim.acquired]
    assert len(reclaimed) == 1
    assert reclaimed[0].generation == 2
    assert {claim.reason for claim in second_round if not claim.acquired} == {"active_lease"}

    with sessions() as session:
        assert finish_claim(session, winners[0], "succeeded") is False
        assert finish_claim(session, reclaimed[0], "succeeded") is True
        session.commit()


@pytest.mark.integration
def test_postgres_skip_locked_relay_claim_and_ack_fencing(pg) -> None:
    _, sessions, _ = pg
    message = {
        "schema_version": "1.0",
        "task_type": "verify_upload",
        "upload_id": "upl_postgres_relay",
        "attempt_id": "att_postgres_relay",
        "queue": "verify",
    }
    now = utcnow()
    with sessions() as session:
        create_task_intent(session, message, ROOT / "contracts", due_at=now)
        session.commit()

    first_round = _concurrent_relay_claims(sessions, "first", now)
    first = [claim for claim in first_round if claim is not None]
    assert len(first) == 1
    assert first[0].generation == 1

    with sessions() as session:
        intent = session.get(TaskIntent, "att_postgres_relay")
        assert intent is not None
        intent.relay_lease_until = now - timedelta(seconds=1)
        session.commit()
    second_round = _concurrent_relay_claims(
        sessions,
        "second",
        now + timedelta(seconds=1),
    )
    second = [claim for claim in second_round if claim is not None]
    assert len(second) == 1
    assert second[0].generation == 2

    with sessions() as session:
        assert acknowledge_relay_publish(session, first[0]) is False
        assert acknowledge_relay_publish(session, second[0]) is True
        session.commit()


def _concurrent_claims(
    sessions: sessionmaker[Session],
    message: dict[str, str],
    round_name: str,
) -> list[TaskClaim]:
    barrier = threading.Barrier(3)
    claims: list[TaskClaim] = []
    failures: list[Exception] = []
    lock = threading.Lock()

    def run(worker: str) -> None:
        try:
            with sessions() as session:
                barrier.wait(timeout=10)
                claim = claim_task(
                    session,
                    message,
                    ROOT / "contracts",
                    receipt_mode="strict",
                    owner_id=f"{round_name}-{worker}",
                    lease_seconds=60,
                )
                session.commit()
            with lock:
                claims.append(claim)
        except Exception as error:
            with lock:
                failures.append(error)

    threads = [threading.Thread(target=run, args=(str(index),)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=10)
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert failures == []
    assert len(claims) == 2
    return claims


def _concurrent_relay_claims(
    sessions: sessionmaker[Session],
    round_name: str,
    now: datetime,
) -> list[RelayClaim | None]:
    barrier = threading.Barrier(3)
    claims: list[RelayClaim | None] = []
    failures: list[Exception] = []
    lock = threading.Lock()

    def run(worker: str) -> None:
        try:
            with sessions() as session:
                barrier.wait(timeout=10)
                claim = claim_relay_intent(
                    session,
                    ROOT / "contracts",
                    owner_id=f"relay-{round_name}-{worker}",
                    lease_seconds=30,
                    now=now,
                )
                session.commit()
            with lock:
                claims.append(claim)
        except Exception as error:
            with lock:
                failures.append(error)

    threads = [threading.Thread(target=run, args=(str(index),)) for index in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait(timeout=10)
    for thread in threads:
        thread.join(timeout=15)
        assert not thread.is_alive()
    assert failures == []
    assert len(claims) == 2
    return claims
