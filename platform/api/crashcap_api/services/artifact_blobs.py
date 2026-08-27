from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..build_publications import seal_content_build
from ..config import Settings
from ..errors import ApiError
from ..ids import new_id, new_ulid
from ..metrics import (
    ARTIFACT_BLOB_BYTES,
    ARTIFACT_BLOB_CLAIM_TAKEOVERS,
    ARTIFACT_BLOB_CONFLICTS,
    ARTIFACT_BLOB_DELIVERIES,
)
from ..models import (
    Artifact,
    ArtifactBlob,
    ArtifactBlobPair,
    ArtifactBlobUploadClaim,
    Build,
    BuildArtifactExpectation,
    BuildModule,
    Workspace,
)
from ..queueing import TaskDispatcher
from ..storage import ObjectStore
from ..task_handoff import publish_after_commit, stage_task_message
from .artifact_payloads import payload_head_valid, payload_object_key
from .uploads import create_upload_record, presigned_upload_response


def delivery_label(source: str, *, blob_backed: bool) -> str | None:
    if not blob_backed:
        return None
    return {
        "upload": "uploaded",
        "blob_reuse": "reused",
        "backfill": "backfilled",
    }.get(source)


def initialize_artifact_delivery(
    session: Session,
    store: ObjectStore,
    dispatcher: TaskDispatcher,
    settings: Settings,
    *,
    build: Build,
    file_kind: str,
    filename: str,
    size: int,
    sha256: str,
    request: Request,
    wire_encoding: str = "identity",
    wire_size: int | None = None,
    wire_sha256: str | None = None,
) -> dict[str, Any]:
    if settings.artifact_blob_dedup_mode != "active":
        raise ApiError(
            "ARTIFACT_DELIVERY_DISABLED",
            "artifact-delivery-v1 is not active in this environment",
            status_code=404,
        )
    expectation = require_exact_expectation(
        session,
        build,
        file_kind=file_kind,
        filename=filename,
        size=size,
        sha256=sha256,
    )
    _lock_workspace_sha(session, build.workspace_id, sha256)
    now = datetime.now(UTC)
    blob = session.scalar(
        select(ArtifactBlob)
        .where(
            ArtifactBlob.workspace_id == build.workspace_id,
            ArtifactBlob.sha256 == sha256,
        )
        .with_for_update()
    )
    if blob is not None:
        _assert_blob_shape(blob, file_kind, size)
        if blob.verification_status == "verified" and _canonical_object_valid(store, blob):
            artifact = materialize_blob_binding(
                session, build, expectation, blob, source="blob_reuse"
            )
            messages = reconcile_build_blob_pairs(session, settings, build)
            session.commit()
            for message in messages:
                publish_after_commit(session, settings, dispatcher, message)
            ARTIFACT_BLOB_DELIVERIES.labels("active", "reused").inc()
            # Bytes are disposition/request counters, just like upload-init
            # bytes. A waiter that retries after another process materializes
            # the binding still made a real decision to skip this transfer.
            ARTIFACT_BLOB_BYTES.labels("skipped").inc(size)
            return {
                "disposition": "reused",
                "artifact_blob_id": blob.id,
                "artifact_id": artifact.id,
                "delivery": "reused",
            }
        if blob.verification_status == "verified":
            blob.verification_status = "missing"
            blob.verification_reason = "canonical_object_missing_or_wrong_size"
            blob.updated_at = now

    if build.sealed_at is not None:
        # Preserve the canonical-object health observation even though the
        # immutable Build cannot enter a replacement-transfer workflow.
        session.commit()
        raise ApiError(
            "BUILD_SEALED",
            "a sealed content Build cannot start a replacement Artifact transfer; "
            "repair or backfill the canonical Blob",
            status_code=409,
        )

    claim = session.scalar(
        select(ArtifactBlobUploadClaim)
        .where(
            ArtifactBlobUploadClaim.workspace_id == build.workspace_id,
            ArtifactBlobUploadClaim.sha256 == sha256,
        )
        .with_for_update()
    )
    if claim is not None:
        if claim.kind != file_kind or claim.size != size:
            ARTIFACT_BLOB_CONFLICTS.labels("claim_shape").inc()
            raise ApiError(
                "ARTIFACT_BLOB_CONFLICT",
                "the active transfer claim has conflicting immutable metadata",
                status_code=409,
            )
        if _aware(claim.lease_expires_at) > now:
            session.commit()
            ARTIFACT_BLOB_DELIVERIES.labels("active", "wait").inc()
            return {
                "disposition": "wait",
                "retry_after_seconds": min(
                    5, max(1, int((_aware(claim.lease_expires_at) - now).total_seconds()))
                ),
                "lease_expires_at": _aware(claim.lease_expires_at).isoformat(),
            }
        session.delete(claim)
        session.flush()
        ARTIFACT_BLOB_CLAIM_TAKEOVERS.inc()

    upload = create_upload_record(
        session,
        workspace_id=build.workspace_id,
        build_id=build.id,
        file_kind=file_kind,
        filename=filename,
        size=size,
        sha256_hint=sha256,
        capture_profile=None,
        reported_build_id=None,
        reported_at=None,
        request=request,
        wire_encoding=wire_encoding,
        wire_size=wire_size,
        wire_sha256=wire_sha256,
    )
    session.add(
        ArtifactBlobUploadClaim(
            workspace_id=build.workspace_id,
            sha256=sha256,
            upload_id=upload.id,
            kind=file_kind,
            size=size,
            lease_expires_at=now + timedelta(seconds=settings.artifact_blob_claim_lease_seconds),
        )
    )
    session.commit()
    response = presigned_upload_response(store, upload)
    response["disposition"] = "upload"
    if wire_size is not None:
        response["wire_encoding"] = wire_encoding
        response["wire_size"] = wire_size
    ARTIFACT_BLOB_DELIVERIES.labels("active", "upload").inc()
    ARTIFACT_BLOB_BYTES.labels("uploaded").inc(size)
    return response


def bind_verified_blobs(
    session: Session,
    store: ObjectStore,
    settings: Settings,
    build: Build,
) -> list[dict[str, Any]]:
    if settings.artifact_blob_dedup_mode != "active" or build.identity_mode != "content_v1":
        return []
    expectations = session.scalars(
        select(BuildArtifactExpectation).where(BuildArtifactExpectation.build_id == build.id)
    ).all()
    for expectation in expectations:
        blob = session.scalar(
            select(ArtifactBlob).where(
                ArtifactBlob.workspace_id == build.workspace_id,
                ArtifactBlob.sha256 == expectation.sha256,
                ArtifactBlob.kind == expectation.kind,
                ArtifactBlob.size == expectation.size,
                ArtifactBlob.verification_status == "verified",
            )
        )
        if blob is None:
            continue
        if not _canonical_object_valid(store, blob):
            blob.verification_status = "missing"
            blob.verification_reason = "canonical_object_missing_or_wrong_size"
            blob.updated_at = datetime.now(UTC)
            continue
        prior = _exact_artifact(session, build.id, expectation)
        newly_blob_backed = prior is None or prior.artifact_blob_id is None
        materialize_blob_binding(session, build, expectation, blob, source="blob_reuse")
        if newly_blob_backed:
            ARTIFACT_BLOB_DELIVERIES.labels("active", "reused").inc()
            ARTIFACT_BLOB_BYTES.labels("skipped").inc(expectation.size)
    return reconcile_build_blob_pairs(session, settings, build)


def materialize_blob_across_builds(
    session: Session,
    settings: Settings,
    blob: ArtifactBlob,
    *,
    source: str,
) -> list[dict[str, Any]]:
    rows = session.execute(
        select(BuildArtifactExpectation, Build)
        .join(Build, Build.id == BuildArtifactExpectation.build_id)
        .where(
            Build.workspace_id == blob.workspace_id,
            Build.identity_mode == "content_v1",
            Build.sealed_at.is_(None),
            BuildArtifactExpectation.sha256 == blob.sha256,
            BuildArtifactExpectation.kind == blob.kind,
            BuildArtifactExpectation.size == blob.size,
        )
    ).all()
    builds: dict[str, Build] = {}
    for expectation, build in rows:
        materialize_blob_binding(session, build, expectation, blob, source=source)
        builds[build.id] = build
    messages: list[dict[str, Any]] = []
    for build in builds.values():
        messages.extend(reconcile_build_blob_pairs(session, settings, build))
    return messages


def materialize_blob_binding(
    session: Session,
    build: Build,
    expectation: BuildArtifactExpectation,
    blob: ArtifactBlob,
    *,
    source: str,
) -> Artifact:
    if build.sealed_at is not None:
        existing = _exact_artifact(session, build.id, expectation)
        if existing is None:
            raise ApiError(
                "BUILD_SEALED",
                "a sealed content Build cannot gain an Artifact binding",
                status_code=409,
            )
        return existing
    existing = _exact_artifact(session, build.id, expectation)
    if existing is None:
        existing = Artifact(
            id=new_id("art"),
            build_id=build.id,
            module_id=expectation.module_id,
            kind=expectation.kind,
            logical_name=expectation.logical_name,
            sha256=blob.sha256,
            size=blob.size,
            object_key=payload_object_key(blob),
            artifact_blob_id=blob.id,
            materialization_source=source,
            code_id=blob.code_id,
            debug_id=blob.debug_id,
            verification_status="pending",
        )
        session.add(existing)
        session.flush()
    elif existing.artifact_blob_id is None:
        existing.artifact_blob_id = blob.id
        existing.materialization_source = source
        existing.object_key = payload_object_key(blob)
        existing.code_id = blob.code_id
        existing.debug_id = blob.debug_id
    elif existing.artifact_blob_id != blob.id:
        ARTIFACT_BLOB_CONFLICTS.labels("artifact_binding").inc()
        raise ApiError(
            "ARTIFACT_BLOB_CONFLICT",
            "an exact Build Artifact is already bound to a different Blob",
            status_code=409,
        )
    return existing


def reconcile_build_blob_pairs(
    session: Session, settings: Settings, build: Build
) -> list[dict[str, Any]]:
    if build.identity_mode != "content_v1":
        return []
    # Sessions deliberately disable autoflush. Blob bindings created in this
    # transaction must be visible to the exact PE/PDB pairing query.
    session.flush()
    messages: list[dict[str, Any]] = []
    modules = session.scalars(select(BuildModule).where(BuildModule.build_id == build.id)).all()
    for module in modules:
        artifacts = session.scalars(
            select(Artifact)
            .where(
                Artifact.build_id == build.id,
                Artifact.module_id == module.id,
                Artifact.kind.in_(["pe", "pdb"]),
                Artifact.artifact_blob_id.is_not(None),
            )
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
        ).all()
        pe = next((row for row in artifacts if row.kind == "pe"), None)
        pdb = next((row for row in artifacts if row.kind == "pdb"), None)
        if pe is None or pdb is None:
            continue
        pair = session.scalar(
            select(ArtifactBlobPair).where(
                ArtifactBlobPair.workspace_id == build.workspace_id,
                ArtifactBlobPair.pe_blob_id == pe.artifact_blob_id,
                ArtifactBlobPair.pdb_blob_id == pdb.artifact_blob_id,
            )
        )
        if pair is None:
            pair = ArtifactBlobPair(
                id=new_id("abp"),
                workspace_id=build.workspace_id,
                pe_blob_id=str(pe.artifact_blob_id),
                pdb_blob_id=str(pdb.artifact_blob_id),
                state="pending",
            )
            session.add(pair)
            session.flush()
        if pair.state == "published":
            _apply_published_pair(module, pe, pdb)
        elif pair.state == "rejected":
            pe.verification_status = "pe_mismatch"
            pdb.verification_status = "pdb_mismatch"
        else:
            message = {
                "schema_version": "1.1",
                "task_type": "publish_artifact_blob_pair",
                "artifact_blob_pair_id": pair.id,
                "attempt_id": f"att_{new_ulid()}",
                "queue": "ingest",
            }
            messages.append(stage_task_message(session, settings, message))
    _seal_and_increment(session, build)
    # A Build can reference the same pair only once per module, but multiple
    # modules/builds may discover it in one transaction. Publish each intent once.
    return list({str(message["attempt_id"]): message for message in messages}.values())


def apply_pair_to_bindings(
    session: Session, pair: ArtifactBlobPair
) -> tuple[list[Build], list[Build]]:
    pe_rows = session.scalars(
        select(Artifact).where(Artifact.artifact_blob_id == pair.pe_blob_id, Artifact.kind == "pe")
    ).all()
    builds: dict[str, Build] = {}
    for pe in pe_rows:
        pdb = session.scalar(
            select(Artifact).where(
                Artifact.build_id == pe.build_id,
                Artifact.module_id == pe.module_id,
                Artifact.kind == "pdb",
                Artifact.artifact_blob_id == pair.pdb_blob_id,
            )
        )
        if pdb is None or pe.module_id is None:
            continue
        build = session.get(Build, pe.build_id)
        module = session.get(BuildModule, pe.module_id)
        if build is None or module is None or build.sealed_at is not None:
            continue
        if pair.state == "published":
            _apply_published_pair(module, pe, pdb)
        elif pair.state == "rejected":
            pe.verification_status = "pe_mismatch"
            pdb.verification_status = "pdb_mismatch"
        builds[build.id] = build
    newly_sealed: list[Build] = []
    for build in builds.values():
        if _seal_and_increment(session, build):
            newly_sealed.append(build)
    return list(builds.values()), newly_sealed


def require_exact_expectation(
    session: Session,
    build: Build,
    *,
    file_kind: str,
    filename: str,
    size: int,
    sha256: str,
) -> BuildArtifactExpectation:
    if build.identity_mode != "content_v1":
        raise ApiError(
            "LEGACY_BUILD",
            "artifact-delivery-v1 is available only for content Builds",
            status_code=409,
        )
    expectation = session.scalar(
        select(BuildArtifactExpectation).where(
            BuildArtifactExpectation.build_id == build.id,
            BuildArtifactExpectation.kind == file_kind,
            BuildArtifactExpectation.normalized_name == filename.casefold(),
        )
    )
    if expectation is None:
        raise ApiError(
            "UNEXPECTED_ARTIFACT",
            "Artifact is absent from the Build expectation inventory",
            status_code=422,
        )
    conflicts = []
    if expectation.size != size:
        conflicts.append("size")
    if expectation.sha256 != sha256:
        conflicts.append("sha256")
    if conflicts:
        raise ApiError(
            "ARTIFACT_CONTENT_MISMATCH",
            "Artifact delivery declaration differs from the expected content",
            status_code=422,
            details={"conflicting_fields": conflicts},
        )
    return expectation


def _exact_artifact(
    session: Session, build_id: str, expectation: BuildArtifactExpectation
) -> Artifact | None:
    return session.scalar(
        select(Artifact)
        .where(
            Artifact.build_id == build_id,
            Artifact.module_id == expectation.module_id,
            Artifact.kind == expectation.kind,
            Artifact.sha256 == expectation.sha256,
            Artifact.size == expectation.size,
            Artifact.logical_name == expectation.logical_name,
        )
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    )


def _apply_published_pair(module: BuildModule, pe: Artifact, pdb: Artifact) -> None:
    pe.verification_status = "verified"
    pdb.verification_status = "verified"
    module.code_id = pe.code_id
    module.debug_id = pe.debug_id or pdb.debug_id


def _seal_and_increment(session: Session, build: Build) -> bool:
    sealed, newly_sealed = seal_content_build(session, build.id)
    if not newly_sealed or sealed is None:
        return False
    workspace = session.scalar(
        select(Workspace).where(Workspace.id == sealed.workspace_id).with_for_update()
    )
    if workspace is None:
        raise RuntimeError("sealed Build Workspace disappeared")
    workspace.symbol_inventory_version += 1
    return True


def _assert_blob_shape(blob: ArtifactBlob, kind: str, size: int) -> None:
    if blob.kind == kind and blob.size == size:
        return
    ARTIFACT_BLOB_CONFLICTS.labels("blob_shape").inc()
    raise ApiError(
        "ARTIFACT_BLOB_CONFLICT",
        "Workspace+SHA is already bound to conflicting Blob metadata",
        status_code=409,
        details={"conflicting_fields": ["kind" if blob.kind != kind else "size"]},
    )


def _canonical_object_valid(store: ObjectStore, blob: ArtifactBlob) -> bool:
    return payload_head_valid(store, blob)


def _lock_workspace_sha(session: Session, workspace_id: str, sha256: str) -> None:
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"artifact-blob:{workspace_id}:{sha256}"},
        )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
