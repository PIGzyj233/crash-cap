"""Content-addressed DMP bytes; Workspace retention references remain independent."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from ..storage import ObjectNotFoundError, ObjectStore, stream_sha256


def lock_dump_content(session: Session, sha256: str) -> None:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": "dump-content:" + sha256},
        )


def retain_dump_content(session: Session, store: ObjectStore, sha256: str, source: Path) -> str:
    # This per-content lock also fences expiry. Unrelated uploads remain independent.
    lock_dump_content(session, sha256)
    key = f"dump-blobs/{sha256}/original.dmp"
    try:
        actual_sha, size, _ = stream_sha256(store, key)
    except ObjectNotFoundError:
        store.put_file(key, source, "application/octet-stream")
        actual_sha, size, _ = stream_sha256(store, key)
    if actual_sha != sha256 or size != source.stat().st_size:
        raise RuntimeError("Retained DMP content differs from its verified identity")
    return key
