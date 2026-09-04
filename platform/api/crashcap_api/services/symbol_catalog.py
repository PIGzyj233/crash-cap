"""Transactional global catalog. Byte validation and object I/O precede this layer.

Only trusted validators may construct admission evidence. This module does not
accept upload claims as verification, select a winner, or derive Workspace roles.
Callers own the transaction; exceptions require rollback. No function commits.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from ..frozen_inputs import digest, normalize_identity
from ..ids import new_ulid
from ..models import (
    ArtifactBlob,
    Build,
    CatalogChange,
    CatalogFile,
    CatalogFileLocation,
    CatalogIdentityMembership,
    CatalogPair,
    CatalogPairOrigin,
    CatalogPairReview,
    CatalogWatermark,
)


class CatalogError(ValueError):
    pass


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise CatalogError(reason)


def _hash(value: str) -> bool:
    return re.fullmatch(r"[0-9a-f]{64}", value) is not None


@dataclass(frozen=True)
class FileEvidence:
    kind: str
    raw_sha256: str
    raw_size: int
    code_id: str | None
    debug_id: str
    architecture: str
    validator_version: str
    verification_object_key: str
    verification_sha256: str

    @property
    def id(self) -> str:
        return digest(["catalog-file-v1", self.kind, self.raw_sha256])


@dataclass(frozen=True)
class LocationEvidence:
    object_key: str
    payload_encoding: str
    payload_sha256: str
    payload_size: int
    retention_basis: str
    artifact_blob_id: str | None
    verification_object_key: str
    verification_sha256: str


@dataclass(frozen=True)
class OriginEvidence:
    origin_type: str
    origin_key: str
    source_workspace_id: str | None
    build_id: str | None
    details: dict[str, Any]


def lock_catalog(session: Session) -> CatalogWatermark:
    # The singleton row is also initialized by migration. ON CONFLICT supports
    # empty SQLite unit databases without treating a sequence as commit order.
    session.execute(
        text(
            "INSERT INTO catalog_watermark (id, revision) VALUES (1, 0) ON CONFLICT (id) DO NOTHING"
        )
    )
    return session.scalars(
        select(CatalogWatermark)
        .where(CatalogWatermark.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def _emit(
    session: Session,
    watermark: CatalogWatermark,
    pair: CatalogPair,
    kind: str,
    affects: bool,
    details: dict[str, Any],
    review_id: str | None = None,
) -> None:
    watermark.revision += 1
    session.add(
        CatalogChange(
            revision=watermark.revision,
            pair_id=pair.id,
            code_id=pair.code_id,
            debug_id=pair.debug_id,
            architecture=pair.architecture,
            change_type=kind,
            affects_selection=affects,
            review_id=review_id,
            details=details,
        )
    )
    session.flush()


def _file(session: Session, evidence: FileEvidence) -> CatalogFile:
    require(
        evidence.kind in {"pe", "pdb"} and evidence.raw_size > 0 and _hash(evidence.raw_sha256),
        "invalid verified file shape",
    )
    require(
        bool(evidence.validator_version and evidence.verification_object_key)
        and _hash(evidence.verification_sha256),
        "file verification receipt missing",
    )
    identity = normalize_identity(
        {
            "code_id": evidence.code_id,
            "debug_id": evidence.debug_id,
            "architecture": evidence.architecture,
        }
    )
    require(
        identity["code_id"] == evidence.code_id and identity["debug_id"] == evidence.debug_id,
        "verified file identity is not normalized",
    )
    require(
        evidence.architecture in {"x86_64", "unknown"} and bool(evidence.debug_id),
        "unsupported file identity",
    )
    require(
        evidence.kind != "pe"
        or (evidence.architecture == "x86_64" and evidence.code_id is not None),
        "PE must be verified Windows x64",
    )
    existing = session.get(CatalogFile, evidence.id)
    if existing:
        require(
            all(
                getattr(existing, key) == getattr(evidence, key)
                for key in ("kind", "raw_sha256", "raw_size", "code_id", "debug_id", "architecture")
            ),
            "same raw file has contradictory identity evidence",
        )
        return existing
    result = CatalogFile(id=evidence.id, **asdict(evidence))
    session.add(result)
    session.flush()
    return result


def _location(
    session: Session, file: CatalogFile, evidence: LocationEvidence
) -> tuple[CatalogFileLocation, bool]:
    require(
        evidence.payload_encoding in {"identity", "zstd-v1"}
        and evidence.payload_size > 0
        and _hash(evidence.payload_sha256)
        and _hash(evidence.verification_sha256)
        and bool(evidence.verification_object_key),
        "invalid verified payload receipt",
    )
    if evidence.payload_encoding == "identity":
        require(
            (evidence.payload_sha256, evidence.payload_size) == (file.raw_sha256, file.raw_size),
            "identity payload differs from raw content",
        )
    existing = session.scalar(
        select(CatalogFileLocation).where(CatalogFileLocation.object_key == evidence.object_key)
    )
    if evidence.retention_basis == "canonical_blob":
        blob = session.scalar(
            select(ArtifactBlob)
            .where(ArtifactBlob.id == evidence.artifact_blob_id)
            .with_for_update()
        )
        require(
            blob is not None
            and (blob.kind, blob.sha256, blob.size) == (file.kind, file.raw_sha256, file.raw_size),
            "canonical Blob does not own the verified raw content",
        )
        assert blob is not None
        require(
            existing is not None
            or (
                blob.verification_status == "verified"
                and blob.payload_verified_at is not None
                and (
                    blob.kind,
                    blob.sha256,
                    blob.size,
                    blob.payload_object_key,
                    blob.payload_encoding,
                    blob.payload_sha256,
                    blob.payload_size,
                )
                == (
                    file.kind,
                    file.raw_sha256,
                    file.raw_size,
                    evidence.object_key,
                    evidence.payload_encoding,
                    evidence.payload_sha256,
                    evidence.payload_size,
                )
            ),
            "location is not the current verified canonical Blob payload",
        )
    else:
        require(
            evidence.retention_basis == "platform_owned"
            and evidence.artifact_blob_id is None
            and evidence.object_key.startswith(f"catalog/files/{file.id}/")
            and all(p not in {"", ".", ".."} for p in evidence.object_key.split("/")),
            "new catalog location must be retained platform-owned content",
        )
    if existing:
        require(
            existing.file_id == file.id
            and all(
                getattr(existing, key) == getattr(evidence, key)
                for key in (
                    "payload_encoding",
                    "payload_sha256",
                    "payload_size",
                    "retention_basis",
                    "artifact_blob_id",
                )
            ),
            "physical object key cannot be rebound to different content",
        )
        restored = existing.state != "available"
        if restored:
            existing.state = "available"
            existing.verification_object_key = evidence.verification_object_key
            existing.verification_sha256 = evidence.verification_sha256
        return existing, restored
    result = CatalogFileLocation(
        id=digest(["catalog-location-v1", file.id, evidence.object_key]),
        file_id=file.id,
        state="available",
        **asdict(evidence),
    )
    session.add(result)
    session.flush()
    return result, True


def admit_pair(
    session: Session,
    pe: FileEvidence,
    pdb: FileEvidence,
    locations: dict[str, tuple[LocationEvidence, ...]],
    origin: OriginEvidence,
) -> CatalogPair:
    require(
        pe.kind == "pe" and pdb.kind == "pdb" and pe.debug_id == pdb.debug_id,
        "admission requires one complete identity-consistent PE/PDB pair",
    )
    require(
        set(locations) == {"pe", "pdb"} and all(locations.values()),
        "both pair files need verified retained locations",
    )
    require(
        origin.origin_type in {"import_item", "build_artifacts", "publication"}
        and bool(origin.origin_key),
        "invalid origin",
    )
    if origin.build_id:
        build = session.get(Build, origin.build_id)
        require(
            build is not None and build.workspace_id == origin.source_workspace_id,
            "origin Build/Workspace mismatch",
        )
    watermark = lock_catalog(session)
    pe_file, pdb_file = _file(session, pe), _file(session, pdb)
    pair_id = digest(["pair-v1", pe.raw_sha256, pdb.raw_sha256])
    pair = session.get(CatalogPair, pair_id)
    created = pair is None
    if pair is None:
        pair = CatalogPair(
            id=pair_id,
            pe_file_id=pe_file.id,
            pdb_file_id=pdb_file.id,
            code_id=pe.code_id,
            debug_id=pe.debug_id,
            architecture="x86_64",
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
    affected = list(
        session.scalars(
            select(CatalogPair).where(
                or_(
                    CatalogPair.pe_file_id.in_([pe_file.id, pdb_file.id]),
                    CatalogPair.pdb_file_id.in_([pe_file.id, pdb_file.id]),
                )
            )
        )
    )
    before = {item.id: _usable(session, item) for item in affected}
    changed_locations = []
    changed_files = set()
    for file in (pe_file, pdb_file):
        for evidence in locations[file.kind]:
            location, changed = _location(session, file, evidence)
            if changed:
                changed_locations.append(location.id)
                changed_files.add(file.id)
    prior = session.scalar(
        select(CatalogPairOrigin).where(
            CatalogPairOrigin.pair_id == pair_id,
            CatalogPairOrigin.origin_type == origin.origin_type,
            CatalogPairOrigin.origin_key == origin.origin_key,
        )
    )
    if prior:
        require(
            prior.source_workspace_id == origin.source_workspace_id
            and prior.build_id == origin.build_id
            and prior.details == origin.details,
            "origin idempotency key has different evidence",
        )
    else:
        session.add(CatalogPairOrigin(id=f"cor_{new_ulid()}", pair_id=pair_id, **asdict(origin)))
    session.flush()
    if created or changed_locations or prior is None:
        _emit(
            session,
            watermark,
            pair,
            "pair_admitted" if created else "evidence_added",
            created or before[pair.id] != _usable(session, pair),
            {
                "location_ids": changed_locations,
                "origin_type": origin.origin_type,
                "origin_key": origin.origin_key,
            },
        )
    for item in affected:
        if item.id != pair.id and {item.pe_file_id, item.pdb_file_id} & changed_files:
            _emit(
                session,
                watermark,
                item,
                "location_evidence_added",
                before[item.id] != _usable(session, item),
                {"location_ids": changed_locations},
            )
    # Re-uploading a withdrawn pair never restores its qualification.
    return pair


def _usable(session: Session, pair: CatalogPair) -> bool:
    if pair.state != "active":
        return False
    available = set(
        session.scalars(
            select(CatalogFileLocation.file_id).where(
                CatalogFileLocation.file_id.in_([pair.pe_file_id, pair.pdb_file_id]),
                CatalogFileLocation.state == "available",
            )
        )
    )
    return {pair.pe_file_id, pair.pdb_file_id}.issubset(available)


def mark_location_unavailable(
    session: Session,
    location_id: str,
    *,
    evidence_object_key: str,
    evidence_sha256: str,
    reason: str,
) -> None:
    require(
        bool(evidence_object_key and reason) and _hash(evidence_sha256),
        "availability failure requires evidence",
    )
    watermark = lock_catalog(session)
    location = session.get(CatalogFileLocation, location_id, populate_existing=True)
    require(location is not None, "unknown location")
    assert location is not None
    if location.state == "unavailable":
        return
    pairs = list(
        session.scalars(
            select(CatalogPair).where(
                or_(
                    CatalogPair.pe_file_id == location.file_id,
                    CatalogPair.pdb_file_id == location.file_id,
                )
            )
        )
    )
    before = {pair.id: _usable(session, pair) for pair in pairs}
    location.state = "unavailable"
    session.flush()
    for pair in pairs:
        _emit(
            session,
            watermark,
            pair,
            "location_unavailable",
            before[pair.id] != _usable(session, pair),
            {
                "location_id": location_id,
                "reason": reason,
                "evidence_object_key": evidence_object_key,
                "evidence_sha256": evidence_sha256,
            },
        )


def review_pair(
    session: Session,
    pair_id: str,
    *,
    expected_version: int,
    state: str,
    reason: str,
    evidence_object_key: str,
    evidence_sha256: str,
    idempotency_key: str,
) -> CatalogPairReview:
    require(
        state in {"active", "withdrawn"}
        and bool(reason.strip())
        and bool(evidence_object_key)
        and _hash(evidence_sha256)
        and bool(idempotency_key),
        "review requires explicit evidence and idempotency",
    )
    request = digest(
        [pair_id, expected_version, state, reason, evidence_object_key, evidence_sha256]
    )
    watermark = lock_catalog(session)
    prior = session.scalar(
        select(CatalogPairReview).where(CatalogPairReview.idempotency_key == idempotency_key)
    )
    if prior:
        require(prior.request_sha256 == request, "review idempotency key has different request")
        return prior
    pair = session.get(CatalogPair, pair_id, populate_existing=True)
    require(
        pair is not None and pair.qualification_version == expected_version,
        "pair qualification version changed",
    )
    assert pair is not None
    changed = pair.state != state
    pair.state = state
    pair.qualification_version += 1
    review = CatalogPairReview(
        id=f"crv_{new_ulid()}",
        pair_id=pair.id,
        qualification_version=pair.qualification_version,
        state=state,
        reason=reason,
        idempotency_key=idempotency_key,
        request_sha256=request,
        evidence_object_key=evidence_object_key,
        evidence_sha256=evidence_sha256,
    )
    session.add(review)
    session.flush()
    _emit(
        session,
        watermark,
        pair,
        "qualification_reviewed",
        changed,
        {"qualification_version": pair.qualification_version},
        review.id,
    )
    return review


def protects_object(session: Session, object_key: str) -> bool:
    # Withdrawal and temporary unavailability never release retention references.
    return (
        session.scalar(
            select(CatalogFileLocation.id)
            .where(CatalogFileLocation.object_key == object_key)
            .limit(1)
        )
        is not None
    )


@dataclass(frozen=True)
class CandidatePage:
    revision: int
    pairs: tuple[dict[str, Any], ...]
    next_pair_id: str | None


def candidate_page(
    session: Session,
    identity: dict[str, Any],
    *,
    after: str | None = None,
    limit: int = 200,
    include_locations: bool = True,
) -> CandidatePage:
    require(1 <= limit <= 1000, "candidate page limit out of range")
    captured = normalize_identity(identity)
    require(
        captured["code_id"] is not None or captured["debug_id"] is not None,
        "no captured matching identity",
    )
    watermark = lock_catalog(session)
    bucket = []
    for key in ("code_id", "debug_id"):
        if captured[key] is not None:
            bucket.append(getattr(CatalogIdentityMembership, key) == captured[key])
    query = select(CatalogPair).join(CatalogIdentityMembership).where(or_(*bucket))
    for key in ("code_id", "debug_id", "architecture"):
        if captured[key] not in {None, "unknown"}:
            query = query.where(getattr(CatalogPair, key) == captured[key])
    if after:
        query = query.where(CatalogPair.id > after)
    rows = list(session.scalars(query.order_by(CatalogPair.id).limit(limit + 1)))
    results = []
    for pair in rows[:limit]:
        locations = (
            list(
                session.scalars(
                    select(CatalogFileLocation)
                    .where(CatalogFileLocation.file_id.in_([pair.pe_file_id, pair.pdb_file_id]))
                    .order_by(CatalogFileLocation.id)
                )
            )
            if include_locations
            else []
        )
        results.append(
            {
                "pair_id": pair.id,
                "state": pair.state,
                "qualification_version": pair.qualification_version,
                "identity": {
                    "code_id": pair.code_id,
                    "debug_id": pair.debug_id,
                    "architecture": pair.architecture,
                },
                "pe_file_id": pair.pe_file_id,
                "pdb_file_id": pair.pdb_file_id,
                "locations": [
                    {
                        "location_id": loc.id,
                        "file_id": loc.file_id,
                        "state": loc.state,
                        "object_key": loc.object_key,
                        "payload_encoding": loc.payload_encoding,
                        "payload_sha256": loc.payload_sha256,
                        "payload_size": loc.payload_size,
                    }
                    for loc in locations
                ],
            }
        )
    return CandidatePage(
        watermark.revision, tuple(results), rows[limit - 1].id if len(rows) > limit else None
    )
