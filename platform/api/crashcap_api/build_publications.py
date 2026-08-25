from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings
from .contracts import validate_contract
from .errors import ApiError
from .models import (
    Artifact,
    Build,
    BuildArtifactExpectation,
    BuildModule,
    BuildPublication,
    Upload,
)
from .schemas import BuildPublicationCreate
from .services.uploads import FILE_LIMITS

FINGERPRINT_VERSION = "build-content-v1"


@dataclass(frozen=True)
class PreparedPublication:
    manifest: dict[str, Any]
    schema_version: str
    modules: tuple[dict[str, str], ...]
    artifacts: tuple[dict[str, Any], ...]
    content_fingerprint: str


def _normalize_json(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize_json(item) for item in value]
    if isinstance(value, dict):
        return {
            unicodedata.normalize("NFC", str(key)): _normalize_json(item)
            for key, item in value.items()
        }
    return value


def canonical_fingerprint(manifest: dict[str, Any], artifacts: list[dict[str, Any]]) -> str:
    normalized_artifacts = sorted(
        (
            {
                "kind": str(item["kind"]),
                "logical_name": unicodedata.normalize("NFC", str(item["logical_name"])),
                "size": int(item["size"]),
                "sha256": str(item["sha256"]).lower(),
            }
            for item in artifacts
        ),
        key=lambda item: (str(item["logical_name"]).casefold(), str(item["kind"])),
    )
    envelope = {
        "artifacts": normalized_artifacts,
        "fingerprint_version": FINGERPRINT_VERSION,
        "manifest": _normalize_json(manifest),
    }
    encoded = json.dumps(
        envelope,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def prepare_publication(body: BuildPublicationCreate, settings: Settings) -> PreparedPublication:
    payload = body.model_dump(mode="json")
    validate_contract(
        payload,
        settings.schema_root / "build-publication-v1.schema.json",
        "Build Publication",
    )
    manifest = _normalize_json(body.manifest)
    raw_version = manifest.get("schema_version")
    schema_version = raw_version if isinstance(raw_version, str) else ""
    schema_name = {
        "1.0": "build-manifest-v1.schema.json",
        "2.0": "build-manifest-v2.schema.json",
    }.get(schema_version)
    if schema_name is None:
        raise ApiError(
            "VALIDATION",
            "Build Publication manifest schema_version must be 1.0 or 2.0",
            status_code=422,
        )
    validate_contract(manifest, settings.schema_root / schema_name, "Build Manifest")
    if manifest["architecture"] != "x86_64":
        raise ApiError(
            "UNSUPPORTED_ARTIFACT_PROFILE",
            "Build Publications currently accept only Windows x64 artifacts",
            status_code=422,
        )
    if str(manifest.get("compiler", "")).casefold() != "msvc":
        raise ApiError(
            "UNSUPPORTED_ARTIFACT_PROFILE",
            "Build Publications currently require compiler=msvc",
            status_code=422,
        )
    if manifest.get("source_bundle") is not None:
        raise ApiError(
            "UNSUPPORTED_ARTIFACT_PROFILE",
            "source bundles remain an explicit legacy upload path in publication v1",
            status_code=422,
        )

    raw_modules = manifest["modules"]
    modules = tuple(
        {
            "code_file": str(item["code_file"]),
            "debug_file": str(item["debug_file"]),
            "role": str(item["role"]),
        }
        for item in raw_modules
    )
    invalid_module = next(
        (
            module
            for module in modules
            if not module["code_file"].casefold().endswith((".exe", ".dll"))
            or not module["debug_file"].casefold().endswith(".pdb")
        ),
        None,
    )
    if invalid_module is not None:
        raise ApiError(
            "UNSUPPORTED_ARTIFACT_PROFILE",
            "Build Publication modules must pair an EXE/DLL basename with a PDB basename",
            status_code=422,
            details={"code_file": invalid_module["code_file"]},
        )
    code_index = {module["code_file"].casefold(): module for module in modules}
    debug_names = [module["debug_file"].casefold() for module in modules]
    if len(code_index) != len(modules) or len(set(debug_names)) != len(modules):
        raise ApiError(
            "DUPLICATE_ARTIFACT_NAME",
            "Manifest PE and PDB basenames must each be unique within a Build",
            status_code=422,
        )

    artifacts = tuple(item.model_dump(mode="json") for item in body.artifacts)
    seen: set[tuple[str, str]] = set()
    expected_pairs: set[tuple[str, str]] = set()
    for artifact in artifacts:
        kind = str(artifact["kind"])
        logical_name = str(artifact["logical_name"])
        module_name = str(artifact["module_code_file"])
        module = code_index.get(module_name.casefold())
        if module is None:
            raise ApiError(
                "VALIDATION",
                "Artifact expectation references a module absent from the Manifest",
                status_code=422,
                details={"module_code_file": module_name},
            )
        required_name = module["code_file"] if kind == "pe" else module["debug_file"]
        if logical_name.casefold() != required_name.casefold():
            raise ApiError(
                "VALIDATION",
                "Artifact logical_name must exactly address its Manifest module and kind",
                status_code=422,
                details={"module_code_file": module_name, "kind": kind},
            )
        if int(artifact["size"]) > FILE_LIMITS[kind]:
            raise ApiError(
                "ARTIFACT_TOO_LARGE",
                f"{kind} exceeds the supported publication size limit",
                status_code=413,
                details={"logical_name": logical_name, "limit": FILE_LIMITS[kind]},
            )
        name_key = (kind, logical_name.casefold())
        pair_key = (module["code_file"].casefold(), kind)
        if name_key in seen or pair_key in expected_pairs:
            raise ApiError(
                "DUPLICATE_ARTIFACT_NAME",
                "Artifact inventory contains a duplicate module kind or basename",
                status_code=422,
                details={"logical_name": logical_name, "kind": kind},
            )
        seen.add(name_key)
        expected_pairs.add(pair_key)

    required_pairs = {
        (module["code_file"].casefold(), kind) for module in modules for kind in ("pe", "pdb")
    }
    if expected_pairs != required_pairs:
        missing = sorted(
            f"{module_name}:{kind}" for module_name, kind in required_pairs - expected_pairs
        )
        raise ApiError(
            "MISSING_EXPECTED_ARTIFACT",
            "Artifact inventory must contain exactly one PE and PDB for every module",
            status_code=422,
            details={"missing": missing},
        )
    return PreparedPublication(
        manifest=manifest,
        schema_version=schema_version,
        modules=modules,
        artifacts=artifacts,
        content_fingerprint=canonical_fingerprint(manifest, list(artifacts)),
    )


def publication_summary(row: BuildPublication) -> dict[str, Any]:
    return {
        "id": row.id,
        "workspace_id": row.workspace_id,
        "build_id": row.build_id,
        "origin": row.origin,
        "client_publication_id": row.client_publication_id,
        "client_version": row.client_version,
        "git_revision": row.git_revision,
        "git_worktree_state": row.git_worktree_state,
        "created_at": row.created_at.isoformat(),
        "last_seen_at": row.last_seen_at.isoformat(),
    }


def publication_status_view(
    session: Session,
    build: Build,
    publication: BuildPublication | None = None,
) -> dict[str, Any]:
    if (
        build.identity_mode != "content_v1"
        or build.fingerprint_version != FINGERPRINT_VERSION
        or not build.content_fingerprint
    ):
        raise ApiError(
            "LEGACY_BUILD",
            "Publication status is available only for content-identified Builds",
            status_code=409,
        )
    expectations = session.scalars(
        select(BuildArtifactExpectation)
        .where(BuildArtifactExpectation.build_id == build.id)
        .order_by(
            BuildArtifactExpectation.normalized_name,
            BuildArtifactExpectation.kind,
        )
    ).all()
    modules = {
        row.id: row
        for row in session.scalars(
            select(BuildModule).where(BuildModule.build_id == build.id)
        ).all()
    }
    artifacts = session.scalars(
        select(Artifact)
        .where(Artifact.build_id == build.id)
        .order_by(Artifact.created_at.desc(), Artifact.id.desc())
    ).all()
    uploads = session.scalars(
        select(Upload)
        .where(Upload.build_id == build.id)
        .order_by(Upload.uploaded_at.desc(), Upload.id.desc())
    ).all()
    rows: list[dict[str, Any]] = []
    for expected in expectations:
        matching_artifacts = [
            item
            for item in artifacts
            if item.kind == expected.kind
            and item.logical_name.casefold() == expected.normalized_name
        ]
        verified = next(
            (
                item
                for item in matching_artifacts
                if item.verification_status == "verified"
                and item.size == expected.size
                and item.sha256.lower() == expected.sha256.lower()
            ),
            None,
        )
        matching_uploads = [
            item
            for item in uploads
            if item.file_kind == expected.kind
            and item.original_filename.casefold() == expected.normalized_name
        ]
        active_upload = next(
            (
                item
                for item in matching_uploads
                if item.verification_status
                in {"INITIALIZED", "UPLOADING", "UPLOADED", "VERIFYING", "ACCEPTED"}
            ),
            None,
        )
        rejected_artifact = next(
            (
                item
                for item in matching_artifacts
                if item.verification_status not in {"pending", "verified"}
            ),
            None,
        )
        rejected_upload = next(
            (item for item in matching_uploads if item.verification_status == "REJECTED"), None
        )
        pending_artifact = next(
            (item for item in matching_artifacts if item.verification_status == "pending"), None
        )
        state = "missing"
        artifact_id: str | None = None
        upload_id: str | None = None
        rejection_reason: str | None = None
        artifact_blob_id: str | None = None
        delivery: str | None = None
        if verified is not None:
            state = "verified"
            artifact_id = verified.id
            artifact_blob_id = verified.artifact_blob_id
            delivery = _delivery_label(verified)
        elif rejected_artifact is not None and (
            active_upload is None
            or rejected_artifact.created_at >= active_upload.uploaded_at
        ):
            # ACCEPTED means byte verification finished; Artifact identity/pair
            # verification can still reject later. A newer terminal Artifact
            # therefore supersedes that transfer, while a genuinely newer retry
            # Upload remains visible as active.
            state = "rejected"
            artifact_id = rejected_artifact.id
            rejection_reason = rejected_artifact.verification_status
            artifact_blob_id = rejected_artifact.artifact_blob_id
            delivery = _delivery_label(rejected_artifact)
        elif active_upload is not None:
            upload_id = active_upload.id
            if active_upload.verification_status in {"INITIALIZED", "UPLOADING"}:
                state = "uploading"
            else:
                state = "verifying"
            if pending_artifact is not None:
                artifact_id = pending_artifact.id
                artifact_blob_id = pending_artifact.artifact_blob_id
                delivery = _delivery_label(pending_artifact)
        elif pending_artifact is not None:
            state = "verifying"
            artifact_id = pending_artifact.id
            artifact_blob_id = pending_artifact.artifact_blob_id
            delivery = _delivery_label(pending_artifact)
        elif rejected_artifact is not None:
            state = "rejected"
            artifact_id = rejected_artifact.id
            rejection_reason = rejected_artifact.verification_status
            artifact_blob_id = rejected_artifact.artifact_blob_id
            delivery = _delivery_label(rejected_artifact)
        elif rejected_upload is not None:
            state = "rejected"
            upload_id = rejected_upload.id
            rejection_reason = rejected_upload.rejection_reason or "upload_rejected"
        module = modules[expected.module_id]
        rows.append(
            {
                "module_id": expected.module_id,
                "module_code_file": module.code_file,
                "kind": expected.kind,
                "logical_name": expected.logical_name,
                "size": expected.size,
                "sha256": expected.sha256,
                "status": state,
                "artifact_id": artifact_id,
                "upload_id": upload_id,
                "rejection_reason": rejection_reason,
                "artifact_blob_id": artifact_blob_id,
                "delivery": delivery,
            }
        )

    states = {row["status"] for row in rows}
    ready = bool(rows) and states == {"verified"} and build.sealed_at is not None
    if ready:
        status = "ready"
    elif "verifying" in states or (states == {"verified"} and build.sealed_at is None):
        status = "verifying"
    elif "uploading" in states:
        status = "uploading"
    elif "rejected" in states:
        status = "rejected"
    else:
        status = "registered"
    publications = session.scalars(
        select(BuildPublication)
        .where(BuildPublication.build_id == build.id)
        .order_by(BuildPublication.created_at, BuildPublication.id)
    ).all()
    return {
        "publication": publication_summary(publication) if publication else None,
        "publications": [publication_summary(item) for item in publications],
        "build_id": build.id,
        "identity_mode": "content_v1",
        "fingerprint_version": FINGERPRINT_VERSION,
        "content_fingerprint": build.content_fingerprint,
        "status": status,
        "sealed_at": build.sealed_at.isoformat() if build.sealed_at else None,
        "expected_artifacts": rows,
        "missing_artifacts": [row for row in rows if row["status"] != "verified"],
        "rejected_artifacts": [row for row in rows if row["status"] == "rejected"],
        "ready": ready,
    }


def seal_content_build(session: Session, build_id: str) -> tuple[Build | None, bool]:
    # Crash-Cap sessions intentionally disable autoflush. The Artifact that may
    # complete this Build is updated in the same transaction, so make it visible
    # to the exact-inventory query before deciding whether sealing is legal.
    session.flush()
    build = session.scalar(select(Build).where(Build.id == build_id).with_for_update())
    if build is None or build.identity_mode != "content_v1":
        return build, False
    if build.sealed_at is not None:
        return build, False
    expectations = session.scalars(
        select(BuildArtifactExpectation).where(BuildArtifactExpectation.build_id == build.id)
    ).all()
    if not expectations:
        return build, False
    artifacts = session.scalars(
        select(Artifact).where(
            Artifact.build_id == build.id,
            Artifact.verification_status == "verified",
        )
    ).all()
    for expected in expectations:
        if not any(
            artifact.module_id == expected.module_id
            and artifact.kind == expected.kind
            and artifact.logical_name.casefold() == expected.normalized_name
            and artifact.size == expected.size
            and artifact.sha256.lower() == expected.sha256.lower()
            for artifact in artifacts
        ):
            return build, False
    build.sealed_at = datetime.now(UTC)
    return build, True


def _delivery_label(artifact: Artifact) -> str | None:
    if artifact.artifact_blob_id is None:
        return None
    return {
        "upload": "uploaded",
        "blob_reuse": "reused",
        "backfill": "backfilled",
    }.get(artifact.materialization_source)
