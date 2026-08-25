from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import UPLOAD_STATUSES, AnalysisRun, OperationLog, Upload
from ..redaction import sanitize_details
from .analysis_lifecycle import transition_analysis as transition_analysis


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
