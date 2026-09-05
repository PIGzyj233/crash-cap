"""File content, destination bindings and consumer-specific pair availability."""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..frozen_inputs import digest
from ..ids import new_id
from ..models import (
    ArtifactEntry,
    CatalogChange,
    CatalogFile,
    CatalogIdentityMembership,
    CatalogPair,
    CatalogPairOrigin,
    Upload,
)
from .symbol_catalog import (
    FileEvidence,
    LocationEvidence,
    _emit,
    _file,
    _location,
    _usable,
    lock_catalog,
)


def file_visible(file_id: Any, workspace_id: Any) -> Any:
    """SQL EXISTS; both pair halves must cross this interface independently."""
    return (
        select(ArtifactEntry.id)
        .where(
            ArtifactEntry.file_id == file_id,
            or_(ArtifactEntry.workspace_id.is_(None), ArtifactEntry.workspace_id == workspace_id),
        )
        .exists()
    )


def pair_visible(workspace_id: Any) -> Any:
    return file_visible(CatalogPair.pe_file_id, workspace_id) & file_visible(
        CatalogPair.pdb_file_id, workspace_id
    )


def pair_is_visible(session: Session, pair_id: str, workspace_id: str | None) -> bool:
    return (
        session.scalar(
            select(CatalogPair.id).where(
                CatalogPair.id == pair_id,
                pair_visible(workspace_id),
            )
        )
        is not None
    )


def _scopes(session: Session, file_id: str) -> set[str | None]:
    return set(
        session.scalars(
            select(ArtifactEntry.workspace_id)
            .where(
                ArtifactEntry.file_id == file_id,
            )
            .distinct()
        )
    )


def availability(session: Session, file: CatalogFile, workspace_id: str | None) -> str:
    if not file.debug_id:
        return "no_debug_identity"
    pairs = list(
        session.scalars(
            select(CatalogPair).where(
                or_(CatalogPair.pe_file_id == file.id, CatalogPair.pdb_file_id == file.id),
                pair_visible(workspace_id),
                CatalogPair.state == "active",
            )
        )
    )
    if not pairs:
        return "waiting_for_pair"
    for pair in pairs:
        conflicts = list(
            session.scalars(
                select(CatalogPair.id)
                .where(
                    CatalogPair.code_id == pair.code_id,
                    CatalogPair.debug_id == pair.debug_id,
                    CatalogPair.architecture == pair.architecture,
                    CatalogPair.state == "active",
                    pair_visible(workspace_id),
                )
                .limit(2)
            )
        )
        if len(conflicts) > 1:
            return "identity_conflict"
    return (
        "symbols_available"
        if any(_usable(session, pair) for pair in pairs)
        else "storage_unavailable"
    )


def refresh_availability(session: Session, debug_id: str | None) -> None:
    if not debug_id:
        return
    session.flush()
    for entry, file in session.execute(
        select(ArtifactEntry, CatalogFile)
        .join(CatalogFile, CatalogFile.id == ArtifactEntry.file_id)
        .where(CatalogFile.debug_id == debug_id)
    ):
        entry.availability = availability(session, file, entry.workspace_id)


def accept_file(
    session: Session,
    upload: Upload,
    evidence: FileEvidence,
    location: LocationEvidence,
) -> ArtifactEntry:
    """Short catalog-fenced transaction; caller also fences the Upload task claim."""
    watermark = lock_catalog(session)
    prior = session.scalar(select(ArtifactEntry).where(ArtifactEntry.upload_id == upload.id))
    if prior is not None:
        return prior
    file = _file(session, evidence)
    existing_pairs = list(
        session.scalars(
            select(CatalogPair).where(
                or_(CatalogPair.pe_file_id == file.id, CatalogPair.pdb_file_id == file.id)
            )
        )
    )
    before = {pair.id: _usable(session, pair) for pair in existing_pairs}
    _, restored = _location(session, file, location)
    session.flush()
    if restored:
        for existing_pair in existing_pairs:
            _emit(
                session,
                watermark,
                existing_pair,
                "location_restored",
                before[existing_pair.id] != _usable(session, existing_pair),
                {"file_id": file.id},
            )
    old_scopes = _scopes(session, file.id)
    entry = ArtifactEntry(
        id=new_id("art"),
        file_id=file.id,
        workspace_id=upload.workspace_id,
        upload_id=upload.id,
        name=upload.original_filename,
        version=upload.version,
        kind=file.kind,
        source=upload.source,
        availability="waiting_for_pair",
    )
    session.add(entry)
    session.flush()
    if upload.workspace_id not in old_scopes:
        # Classification can change before a pair exists, including PE without RSDS.
        watermark.revision += 1
        session.add(
            CatalogChange(
                revision=watermark.revision,
                file_id=file.id,
                pair_id=None,
                code_id=file.code_id,
                debug_id=file.debug_id,
                architecture=file.architecture,
                change_type="file_scope_added",
                affects_selection=True,
                details={"workspace_id": upload.workspace_id, "file_id": file.id},
            )
        )
    if not file.debug_id:
        entry.availability = "no_debug_identity"
        return entry
    counterparts = session.scalars(
        select(CatalogFile)
        .where(
            CatalogFile.kind == ("pdb" if file.kind == "pe" else "pe"),
            CatalogFile.debug_id == file.debug_id,
        )
        .order_by(CatalogFile.id)
    )
    for other in counterparts:
        left_scopes, right_scopes = _scopes(session, file.id), _scopes(session, other.id)
        if (
            not left_scopes
            or not right_scopes
            or not (left_scopes & right_scopes or None in left_scopes or None in right_scopes)
        ):
            continue
        pe, pdb = (file, other) if file.kind == "pe" else (other, file)
        pair_id = digest(["pair-v1", pe.raw_sha256, pdb.raw_sha256])
        pair = session.get(CatalogPair, pair_id)
        created = pair is None
        if pair is None:
            pair = CatalogPair(
                id=pair_id,
                pe_file_id=pe.id,
                pdb_file_id=pdb.id,
                code_id=pe.code_id,
                debug_id=pe.debug_id,
                architecture=pe.architecture,
                state="active",
                qualification_version=1,
            )
            session.add(pair)
            session.flush()
            session.add(
                CatalogIdentityMembership(
                    pair_id=pair.id,
                    code_id=pair.code_id,
                    debug_id=pair.debug_id,
                    architecture=pair.architecture,
                )
            )
        session.add(
            CatalogPairOrigin(
                id=new_id("cor"),
                pair_id=pair.id,
                origin_type="upload",
                origin_key=upload.id,
                source_workspace_id=upload.workspace_id,
                details={"artifact_entry_id": entry.id, "version": upload.version},
            )
        )
        # A new local binding also changes the default role when public content
        # was already usable. Label-only reuploads do not cause reanalysis.
        if created:
            _emit(
                session,
                watermark,
                pair,
                "file_scope_added",
                True,
                {
                    "workspace_id": upload.workspace_id,
                    "file_id": file.id,
                },
            )
    session.flush()
    # Recompute the affected identity for each destination independently. A
    # public addition can expose a conflict without granting a local override.
    refresh_availability(session, file.debug_id)
    return entry
