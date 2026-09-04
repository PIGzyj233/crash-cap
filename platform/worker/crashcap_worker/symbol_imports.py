"""Durable per-pair verification with finite retries and fenced catalog admission."""

from __future__ import annotations

import hashlib
import logging
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from crashcap_api.config import Settings
from crashcap_api.contracts import validate_task_message
from crashcap_api.models import (
    SymbolImport,
    SymbolImportAttempt,
    SymbolImportFile,
    SymbolImportItem,
    TaskExecution,
    TaskIntent,
    utcnow,
)
from crashcap_api.services.symbol_catalog import OriginEvidence, admit_pair
from crashcap_api.services.symbol_imports import schedule_attempt
from crashcap_api.storage import ObjectStore
from crashcap_api.task_handoff import (
    TaskClaim,
    TaskReceiptError,
    claim_is_current,
    claim_task,
    finish_claim,
    heartbeat_claim,
)
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, sessionmaker

from .catalog_validation import prepare_catalog_pair
from .core_runner import CoreExecutionError, CoreExecutor

LOGGER = logging.getLogger(__name__)
TASK = "verify_symbol_import_pair"
PERMANENT_CODES = frozenset(
    {
        "ARTIFACT_IDENTIFY_FAILED",
        "ARTIFACT_TOO_LARGE",
        "UNSUPPORTED_ARTIFACT_KIND",
        "CATALOG_PAIR_INVALID",
        "CATALOG_FILE_LIMIT",
    }
)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def live_claim(session: Session, claim: TaskClaim) -> bool:
    # Global order: intent -> execution -> item -> attempt -> catalog watermark.
    session.scalar(
        select(TaskIntent).where(TaskIntent.attempt_id == claim.attempt_id).with_for_update()
    )
    if not claim_is_current(session, claim, lock=True):
        return False
    execution = session.get(TaskExecution, (claim.task_type, claim.logical_key))
    assert execution is not None
    return execution.lease_until is not None and aware(execution.lease_until) > utcnow()


def locked_attempt(
    session: Session, attempt_id: str, item_id: str
) -> tuple[SymbolImportItem, SymbolImportAttempt]:
    item = session.scalars(
        select(SymbolImportItem).where(SymbolImportItem.id == item_id).with_for_update()
    ).one()
    attempt = session.scalars(
        select(SymbolImportAttempt)
        .where(SymbolImportAttempt.id == attempt_id, SymbolImportAttempt.item_id == item_id)
        .with_for_update()
    ).one()
    return item, attempt


def fail_attempt(
    session: Session,
    settings: Settings,
    item: SymbolImportItem,
    attempt: SymbolImportAttempt,
    code: str,
    *,
    permanent: bool = False,
) -> None:
    attempt.error_code = item.error_code = code[:200]
    attempt.finished_at = utcnow()
    if permanent:
        attempt.state = item.state = "rejected"
    elif item.attempt_count >= settings.symbol_import_max_attempts:
        attempt.state, item.state = "exhausted", "retry_exhausted"
    else:
        attempt.state = "failed"
        schedule_attempt(
            session,
            settings,
            item,
            due_at=utcnow()
            + timedelta(
                seconds=min(3600, settings.symbol_import_retry_seconds * 2 ** (attempt.ordinal - 1))
            ),
        )


@contextmanager
def renewable_lease(
    sessions: sessionmaker[Session], settings: Settings, claim: TaskClaim
) -> Iterator[None]:
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(min(30, settings.task_lease_seconds / 3)):
            try:
                with sessions.begin() as session:
                    if not live_claim(session, claim):
                        return
                    heartbeat_claim(session, claim, lease_seconds=settings.task_lease_seconds)
            except Exception:
                LOGGER.exception("Symbol import heartbeat failed attempt_id=%s", claim.attempt_id)
                return  # Final transaction will reject expiry or a newer owner.

    thread = threading.Thread(target=renew, name="symbol-import-lease", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)


def materialize(store: ObjectStore, file: SymbolImportFile, destination: Path) -> None:
    if file.object_key is None:
        raise CoreExecutionError("IMPORT_STAGING_MISSING", "Import has no verified upload")
    sha, total = hashlib.sha256(), 0
    with destination.open("xb") as output:
        for block in store.stream(file.object_key):
            total += len(block)
            if total > file.raw_size:
                raise CoreExecutionError("IMPORT_STAGING_CHANGED", "Staged file exceeds claim")
            sha.update(block)
            output.write(block)
    if total != file.raw_size or sha.hexdigest() != file.raw_sha256:
        raise CoreExecutionError("IMPORT_STAGING_CHANGED", "Staged file differs from upload claim")


def verify_pair(
    settings: Settings,
    sessions: sessionmaker[Session],
    store: ObjectStore,
    core: CoreExecutor,
    message: dict[str, Any],
) -> None:
    if not settings.symbol_imports_enabled:
        return
    validate_task_message(message, settings.schema_root)
    if message.get("task_type") != TASK:
        raise TaskReceiptError("Symbol import consumer received a different task type")
    with sessions.begin() as session:
        # Duplicate broker delivery cannot bypass retry backoff or a terminal attempt.
        intent = session.scalar(
            select(TaskIntent)
            .where(TaskIntent.attempt_id == message["attempt_id"])
            .with_for_update()
        )
        if intent is not None and (intent.state == "dead" or aware(intent.due_at) > utcnow()):
            return
        claim = claim_task(
            session,
            message,
            settings.schema_root,
            receipt_mode="strict",
            lease_seconds=settings.task_lease_seconds,
        )
        if not claim.acquired:
            return
        item, attempt = locked_attempt(session, claim.attempt_id, str(message["item_id"]))
        if attempt.state not in {"queued", "running"} or item.attempt_count != attempt.ordinal:
            finish_claim(session, claim, "succeeded")
            return
        if attempt.state == "running":
            # A crashed execution consumes this retry attempt. Reclaim fencing
            # closes it and allocates the next attempt, never retries forever.
            fail_attempt(session, settings, item, attempt, "IMPORT_EXECUTION_LEASE_LOST")
            finish_claim(session, claim, "failed")
            return
        item.state, attempt.state, attempt.started_at = "verifying", "running", utcnow()
        files = {
            file.kind: file
            for file in session.scalars(
                select(SymbolImportFile).where(SymbolImportFile.item_id == item.id)
            )
        }
        batch = session.get(SymbolImport, item.import_id)
        assert batch is not None
        origin = OriginEvidence(
            "import_item",
            item.id,
            None,
            None,
            {
                "import_id": item.import_id,
                "client_pair_id": item.client_pair_id,
                "source_label": batch.source_label,
                "files": {
                    kind: {
                        "name": file.name,
                        "raw_sha256": file.raw_sha256,
                        "raw_size": file.raw_size,
                    }
                    for kind, file in files.items()
                },
            },
        )
    try:
        with (
            renewable_lease(sessions, settings, claim),
            tempfile.TemporaryDirectory(prefix="crashcap-import-verify-") as temporary,
        ):
            paths = {kind: Path(temporary) / kind for kind in ("pe", "pdb")}
            for kind, path in paths.items():
                materialize(store, files[kind], path)
            prepared = prepare_catalog_pair(core, store, paths["pe"], paths["pdb"])
        with sessions.begin() as session:
            if not live_claim(session, claim):
                return
            item, attempt = locked_attempt(session, claim.attempt_id, str(message["item_id"]))
            if attempt.state != "running" or item.attempt_count != attempt.ordinal:
                return
            pair = admit_pair(session, prepared.pe, prepared.pdb, prepared.locations, origin)
            if not live_claim(session, claim):
                # A wait for the catalog watermark may outlast this lease. Roll
                # back admission as well as item/task updates in that case.
                raise CoreExecutionError(
                    "IMPORT_EXECUTION_LEASE_LOST", "Lease expired at admission"
                )
            item.pair_id, item.state, item.error_code = pair.id, "available", None
            attempt.state, attempt.finished_at = "succeeded", utcnow()
            finish_claim(session, claim, "succeeded")
    except Exception as error:
        code = (
            error.code
            if isinstance(error, CoreExecutionError)
            else "IMPORT_" + type(error).__name__.upper()
        )
        with sessions.begin() as session:
            if not live_claim(session, claim):
                return
            item, attempt = locked_attempt(session, claim.attempt_id, str(message["item_id"]))
            if attempt.state == "running" and item.attempt_count == attempt.ordinal:
                fail_attempt(
                    session, settings, item, attempt, code, permanent=code in PERMANENT_CODES
                )
                finish_claim(session, claim, "dead" if code in PERMANENT_CODES else "failed")
        LOGGER.warning(
            "Symbol import verification failed attempt_id=%s code=%s", claim.attempt_id, code
        )


def recover_imports(sessions: sessionmaker[Session], settings: Settings, *, limit: int = 20) -> int:
    """Bounded durable recovery of dead workers and acknowledged-but-lost deliveries."""
    if not settings.symbol_imports_enabled:
        return 0
    if not 1 <= limit <= 200:
        raise ValueError("Import recovery page limit must be between 1 and 200")
    now = utcnow()
    with sessions() as session:
        ids = session.scalars(
            select(SymbolImportAttempt.id)
            .join(TaskIntent, TaskIntent.attempt_id == SymbolImportAttempt.id)
            .outerjoin(TaskExecution, TaskExecution.active_attempt_id == SymbolImportAttempt.id)
            .where(
                SymbolImportAttempt.state.in_(["queued", "running"]),
                or_(
                    TaskIntent.state == "dead",
                    and_(TaskExecution.outcome == "running", TaskExecution.lease_until <= now),
                    and_(
                        TaskExecution.active_attempt_id.is_(None),
                        TaskIntent.state == "published",
                        TaskIntent.published_at
                        <= now - timedelta(seconds=settings.task_lease_seconds),
                    ),
                ),
            )
            .order_by(SymbolImportAttempt.created_at)
            .limit(limit)
        ).all()
    recovered = 0
    for attempt_id in ids:
        with sessions.begin() as session:
            intent = session.scalars(
                select(TaskIntent).where(TaskIntent.attempt_id == attempt_id).with_for_update()
            ).one()
            execution = session.scalar(
                select(TaskExecution)
                .where(TaskExecution.active_attempt_id == attempt_id)
                .with_for_update()
            )
            item, attempt = locked_attempt(session, attempt_id, intent.target_id)
            if attempt.state not in {"queued", "running"} or item.attempt_count != attempt.ordinal:
                continue
            if intent.state == "dead":
                if execution is not None:
                    execution.outcome, execution.lease_until = "dead", None
                fail_attempt(session, settings, item, attempt, "IMPORT_TASK_DEAD", permanent=True)
            elif execution is None:
                if (
                    intent.state != "published"
                    or intent.published_at is None
                    or aware(intent.published_at)
                    > now - timedelta(seconds=settings.task_lease_seconds)
                ):
                    continue
                intent.state, intent.due_at = "pending", now
            elif (
                execution.outcome == "running"
                and execution.lease_until is not None
                and aware(execution.lease_until) <= now
            ):
                # Marking outcome failed fences the old owner, even before a new
                # attempt is claimed; heartbeat cannot resurrect the old lease.
                execution.outcome, execution.lease_until, execution.updated_at = "failed", None, now
                fail_attempt(session, settings, item, attempt, "IMPORT_EXECUTION_LEASE_LOST")
            else:
                continue
            recovered += 1
    return recovered
