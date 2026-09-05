from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import Settings
from .contracts import validate_task_message
from .errors import ApiError
from .ids import new_ulid
from .metrics import (
    FENCED_STALE_WRITES,
    RELAY_BACKOFF_SECONDS,
    TASK_CLAIMS,
    TASK_HEARTBEATS,
    TASK_POISONED,
)
from .models import TaskExecution, TaskIntent, utcnow

ReceiptMode = Literal["strict"]


class TaskReceiptError(RuntimeError):
    """A permanent task-message or receipt error that must not be retried forever."""


@dataclass(frozen=True)
class TaskIdentity:
    task_type: str
    queue: str
    logical_key: str
    target_type: str
    target_id: str


@dataclass(frozen=True)
class TaskClaim:
    acquired: bool
    task_type: str
    logical_key: str
    attempt_id: str
    generation: int
    owner_id: str
    reason: str


@dataclass(frozen=True)
class RelayClaim:
    attempt_id: str
    generation: int
    owner_id: str
    message: dict[str, Any]


@dataclass(frozen=True)
class RedeliveryDecision:
    message: dict[str, Any]
    dispatch_state: str
    reopened: bool


def task_identity(
    message: dict[str, Any], *, logical_key_override: str | None = None
) -> TaskIdentity:
    task_type = str(message["task_type"])
    queue = str(message["queue"])
    if task_type == "verify_upload":
        target_type, target_id = "upload", str(message["upload_id"])
        logical_key = target_id
    elif task_type == "dispatch_workspace_role":
        target_type, target_id = "workspace", str(message["workspace_id"])
        logical_key = f"{target_id}:role:{message['role_version']}"
    elif task_type == "analyze_frozen_run":
        target_type, target_id = "analysis_run", str(message["run_id"])
        logical_key = target_id
    else:  # The contract validator normally rejects this first.
        raise TaskReceiptError(f"unsupported task type: {task_type}")
    return TaskIdentity(
        task_type,
        queue,
        logical_key_override or logical_key,
        target_type,
        target_id,
    )


def create_task_intent(
    session: Session,
    message: dict[str, Any],
    schema_root: Path,
    *,
    state: Literal["pending", "published"] = "pending",
    due_at: datetime | None = None,
    logical_key_override: str | None = None,
) -> TaskIntent:
    """Create one durable logical intent or return its semantically identical winner."""

    validate_task_message(message, schema_root)
    identity = task_identity(message, logical_key_override=logical_key_override)
    existing = session.scalar(
        select(TaskIntent).where(
            TaskIntent.task_type == identity.task_type,
            TaskIntent.logical_key == identity.logical_key,
        )
    )
    if existing is not None:
        _assert_compatible(existing, message, identity)
        return existing

    now = utcnow()
    row = TaskIntent(
        attempt_id=str(message["attempt_id"]),
        schema_version=str(message["schema_version"]),
        task_type=identity.task_type,
        queue=identity.queue,
        logical_key=identity.logical_key,
        target_type=identity.target_type,
        target_id=identity.target_id,
        message=dict(message),
        request_id=str(message["request_id"]) if message.get("request_id") else None,
        state=state,
        due_at=due_at or now,
        published_at=now if state == "published" else None,
    )
    if session.bind is not None and session.bind.dialect.name == "sqlite":
        # Python's sqlite legacy transaction mode does not BEGIN for the
        # preceding SELECT. Releasing a first SAVEPOINT would therefore commit
        # the row outside the caller's transaction and break atomic handoff.
        # SQLite is test-only here, so use the outer transaction directly.
        session.add(row)
        session.flush()
        return row
    try:
        with session.begin_nested():
            session.add(row)
            session.flush()
    except IntegrityError:
        existing = session.scalar(
            select(TaskIntent).where(
                TaskIntent.task_type == identity.task_type,
                TaskIntent.logical_key == identity.logical_key,
            )
        )
        if existing is None:
            raise
        _assert_compatible(existing, message, identity)
        return existing
    return row


def stage_task_message(
    session: Session,
    settings: Settings,
    message: dict[str, Any],
    *,
    logical_key_override: str | None = None,
) -> dict[str, Any]:
    """Validate and persist a task in the caller transaction."""

    validate_task_message(message, settings.schema_root)
    intent = create_task_intent(
        session,
        message,
        settings.schema_root,
        logical_key_override=logical_key_override,
    )
    # A logical replay must publish the durable winner's attempt, never the
    # losing caller-generated attempt ID.
    return dict(intent.message)


def claim_task(
    session: Session,
    message: dict[str, Any],
    schema_root: Path,
    *,
    receipt_mode: ReceiptMode = "strict",
    lease_seconds: int = 1500,
    owner_id: str | None = None,
    now: datetime | None = None,
) -> TaskClaim:
    """Acquire or reclaim execution ownership in a short database transaction."""

    validate_task_message(message, schema_root)
    identity = task_identity(message)
    claimed_at = now or utcnow()
    owner = owner_id or f"worker-{new_ulid()}"
    intent = session.scalar(
        select(TaskIntent)
        .where(TaskIntent.attempt_id == str(message["attempt_id"]))
        .with_for_update()
    )
    if intent is None:
        TASK_CLAIMS.labels(identity.task_type, "rejected_missing_receipt").inc()
        raise TaskReceiptError("task has no durable intent receipt")
        # Serialize execution creation/reclaim on the durable logical intent.
        intent = session.scalar(
            select(TaskIntent).where(TaskIntent.attempt_id == intent.attempt_id).with_for_update()
        )
        assert intent is not None
    identity = task_identity(message, logical_key_override=intent.logical_key)
    _assert_compatible(intent, message, identity)

    execution = session.get(
        TaskExecution,
        {"task_type": identity.task_type, "logical_key": identity.logical_key},
    )
    if execution is None:
        execution = TaskExecution(
            task_type=identity.task_type,
            logical_key=identity.logical_key,
            active_attempt_id=intent.attempt_id,
            generation=1,
            owner_id=owner,
            lease_until=claimed_at + timedelta(seconds=lease_seconds),
            outcome="running",
            updated_at=claimed_at,
        )
        session.add(execution)
        session.flush()
        TASK_CLAIMS.labels(identity.task_type, "first_claim").inc()
        return TaskClaim(
            True,
            identity.task_type,
            identity.logical_key,
            intent.attempt_id,
            1,
            owner,
            "first_claim",
        )

    lease_active = (
        execution.outcome == "running"
        and execution.lease_until is not None
        and _aware(execution.lease_until) > _aware(claimed_at)
    )
    if execution.outcome == "succeeded":
        return _rejected_claim(execution, owner, "already_succeeded")
    if lease_active:
        return _rejected_claim(execution, owner, "active_lease")

    execution.active_attempt_id = intent.attempt_id
    execution.generation += 1
    execution.owner_id = owner
    execution.lease_until = claimed_at + timedelta(seconds=lease_seconds)
    execution.outcome = "running"
    execution.updated_at = claimed_at
    session.flush()
    TASK_CLAIMS.labels(identity.task_type, "lease_reclaim").inc()
    return TaskClaim(
        True,
        identity.task_type,
        identity.logical_key,
        intent.attempt_id,
        execution.generation,
        owner,
        "lease_reclaim",
    )


def claim_relay_intent(
    session: Session,
    schema_root: Path,
    *,
    owner_id: str,
    lease_seconds: int = 30,
    now: datetime | None = None,
) -> RelayClaim | None:
    """Claim one due outbox row in a short transaction, poisoning invalid rows."""

    claimed_at = now or utcnow()
    candidates = session.scalars(
        select(TaskIntent)
        .where(
            or_(
                and_(TaskIntent.state == "pending", TaskIntent.due_at <= claimed_at),
                and_(
                    TaskIntent.state == "publishing",
                    or_(
                        TaskIntent.relay_lease_until.is_(None),
                        TaskIntent.relay_lease_until <= claimed_at,
                    ),
                ),
            )
        )
        .order_by(TaskIntent.due_at, TaskIntent.created_at, TaskIntent.attempt_id)
        .with_for_update(skip_locked=True)
        .limit(100)
    ).all()
    for intent in candidates:
        try:
            validate_task_message(intent.message, schema_root)
            identity = task_identity(intent.message, logical_key_override=intent.logical_key)
            _assert_compatible(intent, intent.message, identity)
            _assert_intent_envelope(intent)
        except (ApiError, KeyError, TaskReceiptError, TypeError, ValueError):
            intent.delivery_attempts += 1
            _poison_intent(intent, "PERMANENT_INVALID_TASK_MESSAGE", claimed_at)
            continue
        intent.state = "publishing"
        intent.relay_owner = owner_id
        intent.relay_generation += 1
        intent.relay_lease_until = claimed_at + timedelta(seconds=lease_seconds)
        intent.delivery_attempts += 1
        intent.last_error_code = None
        session.flush()
        return RelayClaim(
            attempt_id=intent.attempt_id,
            generation=intent.relay_generation,
            owner_id=owner_id,
            message=dict(intent.message),
        )
    return None


def acknowledge_relay_publish(
    session: Session,
    claim: RelayClaim,
    *,
    now: datetime | None = None,
) -> bool:
    intent = _locked_relay_intent(session, claim)
    if intent is None or not _relay_matches(intent, claim):
        return False
    intent.state = "published"
    intent.published_at = now or utcnow()
    intent.relay_owner = None
    intent.relay_lease_until = None
    intent.last_error_code = None
    return True


def reject_relay_publish(
    session: Session,
    claim: RelayClaim,
    error_code: str,
    *,
    permanent: bool,
    backoff_base_seconds: int = 1,
    backoff_max_seconds: int = 300,
    now: datetime | None = None,
) -> bool:
    intent = _locked_relay_intent(session, claim)
    if intent is None or not _relay_matches(intent, claim):
        return False
    rejected_at = now or utcnow()
    if permanent:
        _poison_intent(intent, error_code, rejected_at)
        return True
    exponent = min(max(intent.delivery_attempts - 1, 0), 16)
    delay = min(backoff_max_seconds, backoff_base_seconds * (2**exponent))
    RELAY_BACKOFF_SECONDS.labels(intent.task_type).observe(delay)
    intent.state = "pending"
    intent.due_at = rejected_at + timedelta(seconds=delay)
    intent.relay_owner = None
    intent.relay_lease_until = None
    intent.last_error_code = error_code[:200]
    return True


def request_task_redelivery(
    session: Session,
    message: dict[str, Any],
    schema_root: Path,
    *,
    now: datetime | None = None,
) -> RedeliveryDecision:
    """Return an existing live delivery or safely reopen its durable intent."""

    requested_at = now or utcnow()
    validate_task_message(message, schema_root)
    identity = task_identity(message)
    intent = session.scalar(
        select(TaskIntent)
        .where(
            TaskIntent.task_type == identity.task_type,
            TaskIntent.logical_key == identity.logical_key,
        )
        .with_for_update()
    )
    if intent is None:
        intent = create_task_intent(session, message, schema_root, due_at=requested_at)
        return RedeliveryDecision(dict(intent.message), "pending", True)

    execution = session.scalar(
        select(TaskExecution)
        .where(
            TaskExecution.task_type == intent.task_type,
            TaskExecution.logical_key == intent.logical_key,
        )
        .with_for_update()
    )
    if execution is not None:
        lease_active = (
            execution.outcome == "running"
            and execution.lease_until is not None
            and _aware(execution.lease_until) > _aware(requested_at)
        )
        if lease_active:
            return RedeliveryDecision(dict(intent.message), "active_lease", False)
        if execution.outcome == "succeeded":
            return RedeliveryDecision(dict(intent.message), "already_succeeded", False)
    if intent.state == "pending":
        return RedeliveryDecision(dict(intent.message), "pending", False)
    relay_active = (
        intent.state == "publishing"
        and intent.relay_lease_until is not None
        and _aware(intent.relay_lease_until) > _aware(requested_at)
    )
    if relay_active:
        return RedeliveryDecision(dict(intent.message), "publishing", False)

    intent.state = "pending"
    intent.due_at = requested_at
    intent.relay_owner = None
    intent.relay_lease_until = None
    intent.dead_at = None
    intent.last_error_code = None
    return RedeliveryDecision(dict(intent.message), "reopened", True)


def poison_task_delivery(
    session: Session,
    message: dict[str, Any],
    error_code: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Terminally quarantine a delivered message without attempting to parse it again."""

    attempt_id = message.get("attempt_id")
    if not isinstance(attempt_id, str):
        return False
    poisoned_at = now or utcnow()
    intent = session.scalar(
        select(TaskIntent).where(TaskIntent.attempt_id == attempt_id).with_for_update()
    )
    if intent is None:
        return False
    _poison_intent(intent, error_code, poisoned_at)
    execution = session.scalar(
        select(TaskExecution)
        .where(
            TaskExecution.task_type == intent.task_type,
            TaskExecution.logical_key == intent.logical_key,
        )
        .with_for_update()
    )
    if execution is not None and execution.active_attempt_id == attempt_id:
        execution.outcome = "dead"
        execution.lease_until = None
        execution.updated_at = poisoned_at
    return True


def heartbeat_claim(
    session: Session,
    claim: TaskClaim,
    *,
    lease_seconds: int,
    now: datetime | None = None,
) -> bool:
    execution = _locked_execution(session, claim)
    if execution is None or not _matches(execution, claim) or execution.outcome != "running":
        TASK_HEARTBEATS.labels(claim.task_type, "rejected_stale").inc()
        return False
    heartbeat_at = now or utcnow()
    execution.lease_until = heartbeat_at + timedelta(seconds=lease_seconds)
    execution.updated_at = heartbeat_at
    TASK_HEARTBEATS.labels(claim.task_type, "accepted").inc()
    return True


def claim_is_current(session: Session, claim: TaskClaim, *, lock: bool = False) -> bool:
    statement = select(TaskExecution).where(
        TaskExecution.task_type == claim.task_type,
        TaskExecution.logical_key == claim.logical_key,
    )
    if lock:
        statement = statement.with_for_update()
    execution = session.scalar(statement)
    current = (
        execution is not None and _matches(execution, claim) and execution.outcome == "running"
    )
    if not current:
        FENCED_STALE_WRITES.labels(claim.task_type, "claim_check").inc()
    return current


def finish_claim(
    session: Session,
    claim: TaskClaim,
    outcome: Literal["succeeded", "failed", "dead"],
    *,
    now: datetime | None = None,
) -> bool:
    execution = _locked_execution(session, claim)
    if execution is None or not _matches(execution, claim) or execution.outcome != "running":
        FENCED_STALE_WRITES.labels(claim.task_type, "finish").inc()
        return False
    execution.outcome = outcome
    execution.lease_until = None
    execution.updated_at = now or utcnow()
    return True


def _locked_execution(session: Session, claim: TaskClaim) -> TaskExecution | None:
    return session.scalar(
        select(TaskExecution)
        .where(
            TaskExecution.task_type == claim.task_type,
            TaskExecution.logical_key == claim.logical_key,
        )
        .with_for_update()
    )


def _locked_relay_intent(session: Session, claim: RelayClaim) -> TaskIntent | None:
    return session.scalar(
        select(TaskIntent).where(TaskIntent.attempt_id == claim.attempt_id).with_for_update()
    )


def _relay_matches(intent: TaskIntent, claim: RelayClaim) -> bool:
    return bool(
        intent.state == "publishing"
        and intent.relay_owner == claim.owner_id
        and intent.relay_generation == claim.generation
    )


def _matches(execution: TaskExecution | None, claim: TaskClaim) -> bool:
    return bool(
        execution is not None
        and execution.active_attempt_id == claim.attempt_id
        and execution.generation == claim.generation
        and execution.owner_id == claim.owner_id
    )


def _rejected_claim(execution: TaskExecution, owner_id: str, reason: str) -> TaskClaim:
    TASK_CLAIMS.labels(execution.task_type, reason).inc()
    return TaskClaim(
        False,
        execution.task_type,
        execution.logical_key,
        execution.active_attempt_id,
        execution.generation,
        owner_id,
        reason,
    )


def _assert_compatible(
    intent: TaskIntent,
    message: dict[str, Any],
    identity: TaskIdentity,
) -> None:
    if intent.queue != identity.queue or intent.target_type != identity.target_type:
        raise TaskReceiptError("task delivery conflicts with its durable routing intent")
    if intent.target_id != identity.target_id:
        raise TaskReceiptError("task delivery conflicts with its durable logical target")
    expected = _semantic_payload(intent.message)
    actual = _semantic_payload(message)
    if expected != actual:
        raise TaskReceiptError("task delivery payload conflicts with its durable intent")


def _assert_intent_envelope(intent: TaskIntent) -> None:
    if str(intent.message.get("attempt_id")) != intent.attempt_id:
        raise TaskReceiptError("task intent attempt envelope conflicts with its message")
    if str(intent.message.get("task_type")) != intent.task_type:
        raise TaskReceiptError("task intent type envelope conflicts with its message")
    if str(intent.message.get("queue")) != intent.queue:
        raise TaskReceiptError("task intent queue envelope conflicts with its message")


def _poison_intent(intent: TaskIntent, error_code: str, now: datetime) -> None:
    source = "relay" if intent.state in {"pending", "publishing"} else "delivery"
    TASK_POISONED.labels(intent.task_type, source).inc()
    intent.state = "dead"
    intent.dead_at = now
    intent.relay_owner = None
    intent.relay_lease_until = None
    intent.last_error_code = error_code[:200]


def _semantic_payload(message: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in message.items() if key not in {"attempt_id", "request_id"}}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
