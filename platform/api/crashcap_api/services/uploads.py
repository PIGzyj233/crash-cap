from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import Settings
from ..errors import ApiError
from ..ids import new_id, new_ulid
from ..models import ArtifactEntry, Upload, Workspace
from ..object_keys import upload_key
from ..queueing import TaskDispatcher
from ..storage import ObjectNotFoundError, ObjectStore
from ..task_handoff import stage_task_message
from .common import operation_log, transition_upload

FILE_LIMITS = {
    "dmp": 256 * 1024 * 1024,
    "pe": 512 * 1024 * 1024,
    "pdb": 2 * 1024 * 1024 * 1024,
}


def create_upload_record(
    session: Session,
    *,
    workspace_id: str | None,
    file_kind: str,
    filename: str,
    size: int,
    sha256_hint: str | None,
    capture_profile: str | None,
    reported_at: datetime | None,
    request: Request,
    wire_encoding: str = "identity",
    wire_size: int | None = None,
    wire_sha256: str | None = None,
    version: str | None = None,
    source: str = "api",
) -> Upload:
    workspace = session.get(Workspace, workspace_id) if workspace_id is not None else None
    if workspace_id is not None and workspace is None:
        raise ApiError("NOT_FOUND", "Workspace was not found", status_code=404)
    if workspace_id is None and file_kind == "dmp":
        raise ApiError("PUBLIC_DMP_NOT_ALLOWED", "DMP uploads require a Workspace", status_code=422)
    if capture_profile == "full-memory":
        raise ApiError(
            "UNSUPPORTED_DUMP",
            "full-memory dumps are not accepted by the anonymous Phase 1 platform",
            status_code=422,
        )
    limit = FILE_LIMITS[file_kind]
    if size > limit:
        code = "DUMP_TOO_LARGE" if file_kind == "dmp" else "VALIDATION"
        raise ApiError(code, f"{file_kind} exceeds the Phase 1 size limit", status_code=413)
    resolved_wire_size = size if wire_size is None else wire_size
    resolved_wire_sha256 = sha256_hint if wire_sha256 is None else wire_sha256
    if wire_encoding not in {"identity", "zstd-v1"}:
        raise ApiError("VALIDATION", "unsupported Artifact wire encoding", status_code=422)
    if resolved_wire_size <= 0 or resolved_wire_size > limit + 1024 * 1024:
        raise ApiError(
            "VALIDATION", "Artifact wire size exceeds its bounded limit", status_code=413
        )
    if wire_encoding == "identity" and (
        resolved_wire_size != size
        or (sha256_hint is not None and resolved_wire_sha256 != sha256_hint)
    ):
        raise ApiError(
            "VALIDATION", "identity wire declaration must match logical content", status_code=422
        )

    upload_id = new_id("upl")
    key = upload_key(workspace_id, upload_id)
    upload = Upload(
        id=upload_id,
        workspace_id=workspace_id,
        object_key=key,
        original_filename=filename,
        declared_length=size,
        client_sha256_hint=sha256_hint.lower() if sha256_hint else None,
        wire_encoding=wire_encoding,
        wire_declared_length=resolved_wire_size,
        wire_sha256_hint=resolved_wire_sha256.lower() if resolved_wire_sha256 else None,
        source_ip=request.client.host if request.client else None,
        file_kind=file_kind,
        version=version,
        source=source,
        verification_status="INITIALIZED",
        capture_profile=capture_profile,
        reported_at=reported_at,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    session.add(upload)
    operation_log(
        session,
        action="upload.initialize",
        target_type="upload",
        target_id=upload.id,
        workspace_id=workspace_id,
        request=request,
        details={
            "file_kind": file_kind,
            "declared_length": size,
            "wire_encoding": wire_encoding,
            "wire_declared_length": resolved_wire_size,
        },
    )
    session.flush()
    return upload


def presigned_upload_response(store: ObjectStore, upload: Upload) -> dict[str, Any]:
    presigned = store.presign_put(
        upload.object_key, upload.wire_declared_length, "application/octet-stream"
    )
    response: dict[str, Any] = {
        "upload_id": upload.id,
        "method": presigned.method,
        "url": presigned.url,
        "headers": presigned.headers,
        "expires_in": presigned.expires_in,
    }
    if presigned.multipart_upload_id:
        multipart: dict[str, Any] = {
            "upload_id": presigned.multipart_upload_id,
            "parts": list(presigned.parts),
        }
        if presigned.part_size is not None:
            multipart["part_size"] = presigned.part_size
        response["multipart"] = multipart
    return response


def initialize_upload(
    session: Session,
    store: ObjectStore,
    *,
    workspace_id: str | None,
    file_kind: str,
    filename: str,
    size: int,
    sha256_hint: str | None,
    capture_profile: str | None,
    reported_at: datetime | None,
    request: Request,
    wire_encoding: str = "identity",
    wire_size: int | None = None,
    wire_sha256: str | None = None,
    version: str | None = None,
    source: str = "api",
) -> tuple[Upload, dict[str, Any]]:
    upload = create_upload_record(
        session,
        workspace_id=workspace_id,
        file_kind=file_kind,
        filename=filename,
        size=size,
        sha256_hint=sha256_hint,
        capture_profile=capture_profile,
        reported_at=reported_at,
        request=request,
        wire_encoding=wire_encoding,
        wire_size=wire_size,
        wire_sha256=wire_sha256,
        version=version,
        source=source,
    )
    session.commit()
    return upload, presigned_upload_response(store, upload)


def complete_upload(
    session: Session,
    store: ObjectStore,
    dispatcher: TaskDispatcher,
    settings: Settings,
    *,
    upload_id: str,
    multipart_upload_id: str | None,
    parts: list[dict[str, Any]],
    request: Request,
) -> dict[str, Any]:
    upload = session.get(Upload, upload_id)
    if upload is None:
        raise ApiError("NOT_FOUND", "Upload was not found", status_code=404)
    if upload.verification_status in {"ACCEPTED", "REJECTED", "QUARANTINED", "VERIFYING"}:
        return upload_completion_view(session, upload)
    if multipart_upload_id:
        if not parts:
            raise ApiError("VALIDATION", "multipart completion requires parts", status_code=422)
        store.complete_multipart(upload.object_key, multipart_upload_id, parts)
    try:
        head = store.head(upload.object_key)
    except ObjectNotFoundError as error:
        raise ApiError("CONFLICT", "uploaded object is not present", status_code=409) from error
    if head.size != upload.wire_declared_length:
        length_reason = (
            "length_mismatch" if upload.wire_encoding == "identity" else "wire_length_mismatch"
        )
        upload.verified_wire_length = head.size
        transition_upload(upload, "UPLOADED")
        transition_upload(upload, "VERIFYING")
        transition_upload(upload, "REJECTED")
        upload.rejection_reason = length_reason
        operation_log(
            session,
            action="upload.complete",
            target_type="upload",
            target_id=upload.id,
            workspace_id=upload.workspace_id,
            request=request,
            result="rejected",
            details={"reason": length_reason, "verified_wire_length": head.size},
        )
        session.commit()
        raise ApiError(
            "VALIDATION",
            "uploaded Content-Length differs from the declared size",
            status_code=422,
        )
    transition_upload(upload, "UPLOADED")
    transition_upload(upload, "VERIFYING")
    upload.completed_at = datetime.now(UTC)
    operation_log(
        session,
        action="upload.complete",
        target_type="upload",
        target_id=upload.id,
        workspace_id=upload.workspace_id,
        request=request,
        details={"verified_wire_length": head.size, "wire_encoding": upload.wire_encoding},
    )
    message = {
        "schema_version": "1.0",
        "task_type": "verify_upload",
        "upload_id": upload.id,
        "attempt_id": f"att_{new_ulid()}",
        "queue": "verify",
        "request_id": getattr(request.state, "request_id", ""),
    }
    message = stage_task_message(session, settings, message)
    session.commit()
    return upload_completion_view(session, upload)


def upload_completion_view(session: Session, upload: Upload) -> dict[str, Any]:
    result: dict[str, Any] = {
        "upload_id": upload.id,
        "status": upload.verification_status,
        "verification_status": upload.verification_status,
        "workspace_id": upload.workspace_id,
        "version": upload.version,
    }
    if upload.verified_sha256:
        result["sha256"] = upload.verified_sha256
        duplicate_uploads = session.scalar(
            select(func.count())
            .select_from(Upload)
            .where(
                Upload.workspace_id == upload.workspace_id,
                Upload.file_kind == upload.file_kind,
                Upload.verified_sha256 == upload.verified_sha256,
                Upload.verification_status == "ACCEPTED",
            )
        )
        result["duplicate"] = int(duplicate_uploads or 0) > 1
    if upload.rejection_reason:
        result["rejection_reason"] = upload.rejection_reason
    entry = session.scalar(select(ArtifactEntry).where(ArtifactEntry.upload_id == upload.id))
    if entry is not None:
        result["artifact_entry_id"] = entry.id
        from ..models import CatalogFile
        from .artifact_catalog import availability

        file = session.get(CatalogFile, entry.file_id)
        result["availability"] = (
            availability(session, file, entry.workspace_id) if file else "validating"
        )
    # IDs are recovered from authoritative verified content, not stored client hints.
    if upload.file_kind == "dmp" and upload.verified_sha256:
        from ..models import DumpBlob, Occurrence

        blob = (
            session.query(DumpBlob)
            .filter_by(workspace_id=upload.workspace_id, sha256=upload.verified_sha256)
            .one_or_none()
        )
        if blob:
            occurrence = session.query(Occurrence).filter_by(dump_blob_id=blob.id).one_or_none()
            result.update(
                {
                    "blob_id": blob.id,
                    "occurrence_id": occurrence.id if occurrence else None,
                    "current_version": occurrence.version if occurrence else None,
                    "version_conflict": bool(
                        occurrence
                        and upload.version is not None
                        and occurrence.version != upload.version
                    ),
                }
            )
    return result
