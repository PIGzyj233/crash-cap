from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import ANALYSIS_STATUSES, UPLOAD_STATUSES, AnalysisRun, OperationLog, Upload
from ..redaction import sanitize_details


def require_row[T](session: Session, model: type[T], identifier: object, label: str) -> T:
    row = session.get(model, identifier)
    if row is None:
        raise ApiError("NOT_FOUND", f"{label} was not found", status_code=404)
    return row


UPLOAD_TRANSITIONS = {
    "INITIALIZED": {"UPLOADING", "UPLOADED"},
    "UPLOADING": {"UPLOADED"},
    "UPLOADED": {"VERIFYING"},
    "VERIFYING": {"ACCEPTED", "QUARANTINED", "REJECTED"},
    "ACCEPTED": set(),
    "QUARANTINED": set(),
    "REJECTED": set(),
}

ANALYSIS_TRANSITIONS = {
    "UPLOADED": {"VALIDATING", "CANCELLED"},
    "VALIDATING": {"INSPECTED", "REJECTED", "FAILED", "TIMEOUT", "OOM", "CANCELLED"},
    "INSPECTED": {"MATCHING_SYMBOLS", "CANCELLED"},
    "MATCHING_SYMBOLS": {"SYMBOLS_READY", "WAITING_FOR_SYMBOLS", "FAILED", "CANCELLED"},
    "WAITING_FOR_SYMBOLS": {"MATCHING_SYMBOLS", "CANCELLED"},
    "SYMBOLS_READY": {"QUEUED", "CANCELLED"},
    "QUEUED": {"ANALYZING", "CANCELLED"},
    "ANALYZING": {"NORMALIZING", "FAILED", "TIMEOUT", "OOM", "CANCELLED"},
    "NORMALIZING": {"GROUPING", "FAILED", "CANCELLED"},
    "GROUPING": {"COMPLETE", "PARTIAL", "FAILED", "CANCELLED"},
    "COMPLETE": set(),
    "PARTIAL": set(),
    "FAILED": set(),
    "REJECTED": set(),
    "CANCELLED": set(),
    "TIMEOUT": set(),
    "OOM": set(),
}


def transition_upload(upload: Upload, target: str) -> None:
    if upload.verification_status not in UPLOAD_STATUSES or target not in UPLOAD_STATUSES:
        raise ValueError("unknown upload state")
    if target not in UPLOAD_TRANSITIONS[upload.verification_status]:
        raise ApiError(
            "CONFLICT",
            "illegal upload state transition",
            status_code=409,
            details={"from": upload.verification_status, "to": target},
        )
    upload.verification_status = target


def transition_analysis(run: AnalysisRun, target: str) -> None:
    if run.status not in ANALYSIS_STATUSES or target not in ANALYSIS_STATUSES:
        raise ValueError("unknown analysis state")
    if target not in ANALYSIS_TRANSITIONS[run.status]:
        raise ApiError(
            "CONFLICT",
            "illegal analysis state transition",
            status_code=409,
            details={"from": run.status, "to": target},
        )
    run.status = target


def operation_log(
    session: Session,
    *,
    action: str,
    target_type: str | None,
    target_id: str | None,
    workspace_id: str | None,
    request: Request | None = None,
    request_id: str | None = None,
    result: str = "success",
    details: dict[str, Any] | None = None,
) -> OperationLog:
    if request is not None:
        source_ip = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        request_id = getattr(request.state, "request_id", request_id)
    else:
        source_ip = None
        user_agent = None
    safe_details = _sanitize_details(details or {})
    row = OperationLog(
        workspace_id=workspace_id,
        actor="anonymous",
        request_id=request_id,
        source_ip=source_ip,
        user_agent=user_agent,
        action=action,
        target_type=target_type,
        target_id=target_id,
        result=result,
        details=safe_details,
    )
    session.add(row)
    return row


def _sanitize_details(details: dict[str, Any]) -> dict[str, Any]:
    return sanitize_details(details)


def assert_no_delete_routes(routes: Iterable[object]) -> None:
    violations: list[str] = []
    for route in routes:
        methods: set[str] = set(getattr(route, "methods", set()) or set())
        if "DELETE" in methods:
            violations.append(getattr(route, "path", "<unknown>"))
    if violations:
        raise RuntimeError(f"Phase 1 must not expose DELETE routes: {violations}")


def latest_run(session: Session, occurrence_id: str) -> AnalysisRun | None:
    return session.scalars(
        select(AnalysisRun)
        .where(AnalysisRun.occurrence_id == occurrence_id)
        .order_by(AnalysisRun.id.desc())
        .limit(1)
    ).first()


def missing_symbol_key(module: dict[str, Any]) -> str:
    # Keep the activity-log identity aligned with the database's authoritative
    # NULL-safe unique key. Filenames are descriptive and can change as better
    # artifacts arrive; debug/code identities define one missing-symbol row.
    identity = {
        "code_id": module.get("code_id"),
        "debug_id": module.get("debug_id"),
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"ms_{digest}"


def active_missing_occurrences(
    session: Session, workspace_id: str, target_id: str | None = None
) -> dict[str, set[str]]:
    query = select(OperationLog).where(
        OperationLog.workspace_id == workspace_id,
        OperationLog.action.in_(["missing_symbol.observe", "missing_symbol.clear"]),
    )
    if target_id is not None:
        query = query.where(OperationLog.target_id == target_id)
    activity: dict[str, set[str]] = {}
    for row in session.scalars(query.order_by(OperationLog.id)):
        details = row.details or {}
        occurrence_id = details.get("occurrence_id")
        if not isinstance(occurrence_id, str) or not row.target_id:
            continue
        occurrences = activity.setdefault(row.target_id, set())
        if row.action == "missing_symbol.observe":
            occurrences.add(occurrence_id)
        else:
            occurrences.discard(occurrence_id)
    return activity
