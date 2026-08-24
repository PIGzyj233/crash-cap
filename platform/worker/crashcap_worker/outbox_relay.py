from __future__ import annotations

import logging
from collections.abc import Callable

from crashcap_api.config import Settings
from crashcap_api.errors import ApiError
from crashcap_api.metrics import RELAY_DELIVERIES
from crashcap_api.queueing import TaskDispatcher, publish_task
from crashcap_api.task_handoff import (
    RelayClaim,
    TaskReceiptError,
    acknowledge_relay_publish,
    claim_relay_intent,
    reject_relay_publish,
)
from sqlalchemy.orm import Session, sessionmaker

LOGGER = logging.getLogger(__name__)


def relay_once(
    sessions: sessionmaker[Session],
    dispatcher: TaskDispatcher,
    settings: Settings,
    *,
    owner_id: str,
    after_publish: Callable[[RelayClaim], None] | None = None,
) -> bool:
    """Relay one durable intent; return whether a due row was handled."""

    with sessions() as session:
        claim = claim_relay_intent(
            session,
            settings.schema_root,
            owner_id=owner_id,
            lease_seconds=settings.relay_lease_seconds,
        )
        session.commit()
    if claim is None:
        return False

    try:
        publish_task(dispatcher, claim.message)
    except Exception as error:
        permanent = _is_permanent_publish_error(error)
        with sessions() as session:
            accepted = reject_relay_publish(
                session,
                claim,
                _error_code(error),
                permanent=permanent,
                backoff_base_seconds=settings.relay_backoff_base_seconds,
                backoff_max_seconds=settings.relay_backoff_max_seconds,
            )
            session.commit()
        task_type = str(claim.message.get("task_type", "unknown"))
        RELAY_DELIVERIES.labels(
            task_type, "permanent_error" if permanent else "transient_error"
        ).inc()
        LOGGER.warning(
            "outbox publish failed attempt_id=%s generation=%d permanent=%s fenced=%s error=%s",
            claim.attempt_id,
            claim.generation,
            permanent,
            accepted,
            type(error).__name__,
            extra={
                "attempt_id": claim.attempt_id,
                "task_type": task_type,
                "queue": claim.message.get("queue"),
                "claim_generation": claim.generation,
                "outcome": "permanent_error" if permanent else "transient_error",
            },
        )
        return True

    # This explicit seam models a process death after Redis accepted the task
    # but before PostgreSQL recorded the acknowledgement. A raised exception is
    # deliberately not caught: the publishing lease later permits a duplicate.
    if after_publish is not None:
        after_publish(claim)

    with sessions() as session:
        accepted = acknowledge_relay_publish(session, claim)
        session.commit()
    task_type = str(claim.message.get("task_type", "unknown"))
    RELAY_DELIVERIES.labels(task_type, "published" if accepted else "fenced_ack").inc()
    if not accepted:
        LOGGER.warning(
            "outbox publish acknowledgement lost fencing race attempt_id=%s generation=%d",
            claim.attempt_id,
            claim.generation,
            extra={
                "attempt_id": claim.attempt_id,
                "task_type": task_type,
                "queue": claim.message.get("queue"),
                "claim_generation": claim.generation,
                "outcome": "fenced_ack",
            },
        )
    return True


def _is_permanent_publish_error(error: Exception) -> bool:
    return isinstance(error, (ApiError, KeyError, TaskReceiptError, TypeError, ValueError))


def _error_code(error: Exception) -> str:
    prefix = "PERMANENT" if _is_permanent_publish_error(error) else "TRANSIENT"
    return f"{prefix}_{type(error).__name__.upper()}"[:200]
