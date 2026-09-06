"""Consumer-scoped file browsing and Current-report symbol impact queries."""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..errors import ApiError
from ..models import ArtifactEntry, CatalogFile, CatalogPair, MissingSymbol, Occurrence
from ..models import MissingSymbolOccurrence as Impact
from .artifact_catalog import availability, pair_visible
from .symbol_catalog import _usable


def _cursor(value: str | None, context: list[Any]) -> Any:
    if value is None:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if data["scope"] != _scope(context):
            raise ValueError("scope")
        return data["position"]
    except (ValueError, KeyError, TypeError):
        raise ApiError(
            "INVALID_CURSOR", "Cursor does not match this view", status_code=422
        ) from None


def _scope(context: list[Any]) -> str:
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()


def _next(position: Any, context: list[Any]) -> str:
    data = json.dumps({"scope": _scope(context), "position": position}).encode()
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def visible_entries(workspace_id: str | None) -> Any:
    return or_(ArtifactEntry.workspace_id.is_(None), ArtifactEntry.workspace_id == workspace_id)


def issue_row(session: Session, workspace_id: str, issue_id: str) -> MissingSymbol:
    row = session.scalar(
        select(MissingSymbol).where(
            MissingSymbol.workspace_id == workspace_id,
            MissingSymbol.id == issue_id,
        )
    )
    if row is None:
        raise ApiError("NOT_FOUND", "Symbol issue was not found", status_code=404)
    return row


def _identity_condition(issue: MissingSymbol) -> Any:
    # A PDB carries Debug ID only. A PE must satisfy every captured identifier.
    # Filenames cannot prove that a candidate is the missing file.
    debug = func.lower(func.trim(CatalogFile.debug_id)) == (issue.debug_id or "").casefold()
    code = func.lower(func.trim(CatalogFile.code_id)) == (issue.code_id or "").casefold()
    if issue.debug_id and issue.code_id:
        return and_(debug, or_(CatalogFile.kind == "pdb", code))
    if issue.debug_id:
        return debug
    if issue.code_id:
        return and_(CatalogFile.kind == "pe", code)
    return CatalogFile.id.is_(None)


def artifact_view(
    session: Session,
    entry: ArtifactEntry,
    file: CatalogFile,
    consumer: str | None,
) -> dict[str, Any]:
    return {
        "id": entry.id,
        "file_id": file.id,
        "workspace_id": entry.workspace_id,
        "name": entry.name,
        "version": entry.version,
        "kind": entry.kind,
        "sha256": file.raw_sha256,
        "size": file.raw_size,
        "code_id": file.code_id,
        "debug_id": file.debug_id,
        "availability": availability(session, file, consumer),
        "source": entry.source,
        "created_at": entry.created_at.isoformat(),
    }


def artifact_page(
    session: Session,
    workspace_id: str | None,
    *,
    origin: str = "all",
    filename: str | None = None,
    version: str | None = None,
    kind: str | None = None,
    state: str | None = None,
    issue_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> dict[str, Any]:
    context = ["files", workspace_id, origin, filename, version, kind, state, issue_id]
    position = _cursor(cursor, context)
    if position is not None and not isinstance(position, str):
        raise ApiError("INVALID_CURSOR", "Invalid file cursor", status_code=422)
    statement = (
        select(ArtifactEntry, CatalogFile)
        .join(CatalogFile, CatalogFile.id == ArtifactEntry.file_id)
        .where(visible_entries(workspace_id))
    )
    if origin == "public":
        statement = statement.where(ArtifactEntry.workspace_id.is_(None))
    elif origin == "workspace":
        statement = statement.where(ArtifactEntry.workspace_id == workspace_id)
    if filename:
        statement = statement.where(
            func.lower(ArtifactEntry.name).contains(filename.casefold(), autoescape=True)
        )
    if version is not None:
        statement = statement.where(ArtifactEntry.version == version)
    if kind:
        statement = statement.where(CatalogFile.kind == kind)
    if issue_id and workspace_id:
        statement = statement.where(_identity_condition(issue_row(session, workspace_id, issue_id)))
    items: list[dict[str, Any]] = []
    # Availability is consumer-dependent. Filter before paginating rather than
    # filtering a page of owner-scoped cached statuses and dropping matches.
    while len(items) <= limit:
        chunk_query = statement.where(ArtifactEntry.id < position) if position else statement
        chunk = session.execute(chunk_query.order_by(ArtifactEntry.id.desc()).limit(200)).all()
        for entry, file in chunk:
            item = artifact_view(session, entry, file, workspace_id)
            if state is None or item["availability"] == state:
                items.append(item)
                if len(items) > limit:
                    break
        if len(chunk) < 200 or len(items) > limit:
            break
        position = chunk[-1][0].id
    return {
        "items": items[:limit],
        "next_cursor": _next(items[limit - 1]["id"], context) if len(items) > limit else None,
    }


def artifact_detail(session: Session, workspace_id: str | None, artifact_id: str) -> dict[str, Any]:
    found = session.execute(
        select(ArtifactEntry, CatalogFile)
        .join(CatalogFile, CatalogFile.id == ArtifactEntry.file_id)
        .where(visible_entries(workspace_id), ArtifactEntry.id == artifact_id)
    ).one_or_none()
    if found is None:
        raise ApiError("NOT_FOUND", "File was not found in this space", status_code=404)
    entry, file = found
    pairs = session.scalars(
        select(CatalogPair)
        .where(
            or_(CatalogPair.pe_file_id == file.id, CatalogPair.pdb_file_id == file.id),
            pair_visible(workspace_id),
        )
        .order_by(CatalogPair.id)
    ).all()
    result = []
    for pair in pairs:
        halves = session.execute(
            select(ArtifactEntry, CatalogFile)
            .join(CatalogFile, CatalogFile.id == ArtifactEntry.file_id)
            .where(
                visible_entries(workspace_id),
                CatalogFile.id.in_([pair.pe_file_id, pair.pdb_file_id]),
            )
            .order_by(ArtifactEntry.id.desc())
        ).all()
        result.append(
            {
                "id": pair.id,
                "state": pair.state,
                "pe": [
                    artifact_view(session, e, f, workspace_id) for e, f in halves if f.kind == "pe"
                ],
                "pdb": [
                    artifact_view(session, e, f, workspace_id) for e, f in halves if f.kind == "pdb"
                ],
            }
        )
    return {"artifact": artifact_view(session, entry, file, workspace_id), "pairs": result}


def _active_impacts(workspace_id: str) -> Any:
    return (
        select(Impact)
        .join(Occurrence, Occurrence.id == Impact.occurrence_id)
        .where(
            Impact.workspace_id == workspace_id,
            Occurrence.workspace_id == workspace_id,
            Impact.analysis_run_id == Occurrence.current_run_id,
        )
    )


def _issue_view(issue: MissingSymbol, counts: dict[str, int]) -> dict[str, Any]:
    return {
        "id": issue.id,
        "code_file": issue.code_file,
        "debug_file": issue.debug_file,
        "code_id": issue.code_id or None,
        "debug_id": issue.debug_id or None,
        "affected_occurrence_count": sum(counts.values()),
        "reasons": counts,
        "first_seen": issue.first_seen.isoformat(),
        "last_seen": issue.last_seen.isoformat(),
    }


def symbol_issues(
    session: Session,
    workspace_id: str,
    *,
    q: str | None = None,
    limit: int = 30,
    cursor: str | None = None,
) -> dict[str, Any]:
    active = _active_impacts(workspace_id).subquery()
    counts = (
        select(active.c.missing_symbol_id.label("id"), func.count().label("count"))
        .group_by(active.c.missing_symbol_id)
        .subquery()
    )
    statement = (
        select(MissingSymbol, counts.c.count)
        .join(counts, counts.c.id == MissingSymbol.id)
        .where(MissingSymbol.workspace_id == workspace_id)
    )
    if q:
        statement = statement.where(
            or_(
                func.lower(MissingSymbol.code_file).contains(q.casefold(), autoescape=True),
                func.lower(MissingSymbol.debug_file).contains(q.casefold(), autoescape=True),
            )
        )
    filtered = statement.subquery()
    total = session.scalar(select(func.count()).select_from(filtered)) or 0
    affected = (
        session.scalar(
            select(func.count(func.distinct(active.c.occurrence_id))).where(
                active.c.missing_symbol_id.in_(select(filtered.c.id))
            )
        )
        or 0
    )
    context = ["issues", workspace_id, q]
    position = _cursor(cursor, context)
    if position is not None:
        if (
            not isinstance(position, list)
            or len(position) != 2
            or not isinstance(position[0], int)
            or not isinstance(position[1], str)
        ):
            raise ApiError("INVALID_CURSOR", "Invalid issue cursor", status_code=422)
        statement = statement.where(
            or_(
                counts.c.count < position[0],
                and_(counts.c.count == position[0], MissingSymbol.id > position[1]),
            )
        )
    rows = session.execute(
        statement.order_by(counts.c.count.desc(), MissingSymbol.id).limit(limit + 1)
    ).all()
    ids = [row.id for row, count in rows[:limit]]
    reasons: dict[str, dict[str, int]] = {identity: {} for identity in ids}
    for identity, reason, count in session.execute(
        select(active.c.missing_symbol_id, active.c.reason, func.count())
        .where(active.c.missing_symbol_id.in_(ids))
        .group_by(active.c.missing_symbol_id, active.c.reason)
    ):
        reasons[identity][reason] = count
    return {
        "items": [_issue_view(row, reasons[row.id]) for row, count in rows[:limit]],
        "next_cursor": _next([rows[limit - 1][1], rows[limit - 1][0].id], context)
        if len(rows) > limit
        else None,
        "total": total,
        "affected_occurrence_count": affected,
        "analyzed_occurrence_count": session.scalar(
            select(func.count())
            .select_from(Occurrence)
            .where(Occurrence.workspace_id == workspace_id, Occurrence.current_run_id.is_not(None))
        )
        or 0,
    }


def symbol_issue_detail(
    session: Session,
    workspace_id: str,
    issue_id: str,
) -> dict[str, Any]:
    issue = issue_row(session, workspace_id, issue_id)
    candidates = select(CatalogPair).where(
        CatalogPair.state == "active",
        pair_visible(workspace_id),
    )
    if issue.code_id:
        candidates = candidates.where(func.lower(CatalogPair.code_id) == issue.code_id.casefold())
    if issue.debug_id:
        candidates = candidates.where(func.lower(CatalogPair.debug_id) == issue.debug_id.casefold())
    pairs = session.scalars(candidates.limit(2)).all() if issue.code_id or issue.debug_id else []
    state = (
        "identity_incomplete"
        if not issue.code_id and not issue.debug_id
        else "identity_conflict"
        if len(pairs) > 1
        else "waiting_for_pair"
        if not pairs
        else "symbols_available"
        if _usable(session, pairs[0])
        else "storage_unavailable"
    )
    active = _active_impacts(workspace_id).where(Impact.missing_symbol_id == issue_id).subquery()
    counts = {
        reason: count
        for reason, count in session.execute(
            select(active.c.reason, func.count()).group_by(active.c.reason)
        )
    }
    return {
        "availability": state,
        "issue": _issue_view(issue, counts),
        "files": artifact_page(
            session,
            workspace_id,
            issue_id=issue_id,
        ),
    }
