"""Workspace-independent imports. Caller owns each short database transaction."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..config import Settings
from ..contracts import validate_contract
from ..errors import ApiError
from ..frozen_inputs import digest
from ..ids import new_ulid
from ..models import SymbolImport, SymbolImportAttempt, SymbolImportFile, SymbolImportItem, utcnow
from ..task_handoff import create_task_intent


def require_enabled(settings: Settings) -> None:
    if not settings.symbol_imports_enabled:
        raise ApiError(
            "QUALIFICATION_PENDING", "Symbol import writes are disabled", status_code=503
        )


def create_import(
    session: Session, settings: Settings, payload: dict[str, Any]
) -> tuple[SymbolImport, bool]:
    validate_contract(
        payload,
        settings.schema_root / "drafts/qa-symbol-import/symbol-import-request-v1.schema.json",
        "symbol import",
    )
    client_ids = [pair["client_pair_id"] for pair in payload["pairs"]]
    if len(set(client_ids)) != len(client_ids):
        raise ApiError(
            "VALIDATION", "client_pair_id must be unique within one import", status_code=422
        )
    for pair in payload["pairs"]:
        for kind, limit in (("pe", 512 * 1024**2), ("pdb", 2 * 1024**3)):
            if pair[kind]["raw_size"] > limit:
                raise ApiError(
                    "FILE_TOO_LARGE", f"{kind} exceeds the supported limit", status_code=413
                )
    request_sha = digest(payload)
    proposed_id = "imp_" + new_ulid()
    insert = sqlite_insert if session.get_bind().dialect.name == "sqlite" else pg_insert
    session.execute(
        insert(SymbolImport)
        .values(
            id=proposed_id,
            idempotency_key=payload["idempotency_key"],
            request_sha256=request_sha,
            source_label=payload["source_label"],
            created_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
    )
    batch = session.scalar(
        select(SymbolImport).where(SymbolImport.idempotency_key == payload["idempotency_key"])
    )
    assert batch is not None
    if batch.request_sha256 != request_sha:
        raise ApiError(
            "IDEMPOTENCY_CONFLICT",
            "Idempotency key is bound to a different import",
            status_code=409,
        )
    created = batch.id == proposed_id
    if created:
        for position, pair in enumerate(payload["pairs"]):
            item = SymbolImportItem(
                id="imi_" + new_ulid(),
                import_id=batch.id,
                client_pair_id=pair["client_pair_id"],
                position=position,
            )
            session.add(item)
            session.flush()
            for kind in ("pe", "pdb"):
                session.add(
                    SymbolImportFile(
                        id="imf_" + new_ulid(), item_id=item.id, kind=kind, **pair[kind]
                    )
                )
        session.flush()
    return batch, created


def import_result(session: Session, import_id: str) -> dict[str, Any]:
    if session.get(SymbolImport, import_id) is None:
        raise ApiError("NOT_FOUND", "Symbol import does not exist", status_code=404)
    items = session.scalars(
        select(SymbolImportItem)
        .where(SymbolImportItem.import_id == import_id)
        .order_by(SymbolImportItem.position)
    ).all()
    files = session.scalars(
        select(SymbolImportFile)
        .join(SymbolImportItem)
        .where(SymbolImportItem.import_id == import_id)
    ).all()
    by_item = {(file.item_id, file.kind): file.id for file in files}
    return {
        "import_id": import_id,
        "items": [
            {
                "item_id": item.id,
                "client_pair_id": item.client_pair_id,
                "state": item.state,
                "pair_id": item.pair_id,
                "error_code": item.error_code,
                "pe_upload_id": by_item[item.id, "pe"],
                "pdb_upload_id": by_item[item.id, "pdb"],
            }
            for item in items
        ],
    }


def get_item(
    session: Session, import_id: str, item_id: str, *, lock: bool = False
) -> SymbolImportItem:
    statement = select(SymbolImportItem).where(
        SymbolImportItem.id == item_id, SymbolImportItem.import_id == import_id
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    item = session.scalar(statement)
    if item is None:
        raise ApiError(
            "NOT_FOUND", "Symbol import item does not exist in this batch", status_code=404
        )
    return item


def schedule_attempt(
    session: Session, settings: Settings, item: SymbolImportItem, *, due_at: datetime | None = None
) -> SymbolImportAttempt:
    """Called with the item locked; attempt budget differs from execution generation."""
    if item.attempt_count >= settings.symbol_import_max_attempts:
        raise ValueError("symbol import attempt budget exhausted")
    attempt_id = "iva_" + new_ulid()
    create_task_intent(
        session,
        {
            "schema_version": "1.2",
            "task_type": "verify_symbol_import_pair",
            "queue": "ingest",
            "item_id": item.id,
            "attempt_id": attempt_id,
        },
        settings.schema_root,
        due_at=due_at,
    )
    item.attempt_count += 1
    item.state = "queued"
    attempt = SymbolImportAttempt(id=attempt_id, item_id=item.id, ordinal=item.attempt_count)
    session.add(attempt)
    session.flush()
    return attempt


def complete_item(session: Session, settings: Settings, import_id: str, item_id: str) -> None:
    item = get_item(session, import_id, item_id, lock=True)
    if item.state != "staging":
        return
    files = session.scalars(
        select(SymbolImportFile).where(SymbolImportFile.item_id == item.id)
    ).all()
    if {file.kind for file in files if file.object_key is not None} != {"pe", "pdb"}:
        raise ApiError(
            "PAIR_INCOMPLETE", "Both declared files must finish uploading", status_code=409
        )
    schedule_attempt(session, settings, item)
