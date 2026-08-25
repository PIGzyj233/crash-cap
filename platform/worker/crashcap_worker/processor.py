from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from crashcap_api.build_publications import seal_content_build
from crashcap_api.canonical_semantics import (
    CanonicalSemanticError,
    bind_legacy_canonical,
    canonical_json_bytes,
    canonical_parity_differences,
    freeze_analysis_context,
    validate_canonical_semantics,
)
from crashcap_api.config import Settings
from crashcap_api.contracts import validate_contract
from crashcap_api.errors import ApiError
from crashcap_api.ids import new_id, new_ulid
from crashcap_api.metrics import (
    ARTIFACT_BLOB_CONFLICTS,
    ARTIFACT_BLOB_VERIFICATION_SECONDS,
    BUILD_PUBLICATION_REJECTIONS,
    BUILD_PUBLICATION_VERIFICATION_SECONDS,
    BUILD_PUBLICATIONS,
    CANONICAL_SHADOW_RESULTS,
    CANONICAL_VALIDATION_FAILURES,
    CANONICAL_WINNER_FINALIZES,
    GENERATION_ORPHAN_BYTES,
    GENERATION_ORPHAN_OBJECTS,
)
from crashcap_api.models import (
    AnalysisRun,
    AnalysisSummary,
    Artifact,
    ArtifactBlob,
    ArtifactBlobLegacyCopy,
    ArtifactBlobPair,
    Build,
    BuildArtifactExpectation,
    BuildModule,
    BuildPublication,
    CrashGroup,
    DumpBlob,
    GroupMembership,
    GroupMembershipHistory,
    Occurrence,
    Upload,
    Workspace,
    utcnow,
)
from crashcap_api.object_keys import (
    analysis_generation_key,
    analysis_generation_prefix,
    artifact_blob_key,
    dump_blob_key,
    raw_build_key,
)
from crashcap_api.queueing import TaskDispatcher
from crashcap_api.services.analysis import create_analysis_run
from crashcap_api.services.analysis_lifecycle import (
    fail_analysis,
    promote_current_analysis,
    transition_analysis,
)
from crashcap_api.services.artifact_blobs import (
    apply_pair_to_bindings,
    materialize_blob_across_builds,
    reconcile_build_blob_pairs,
)
from crashcap_api.services.common import operation_log, transition_upload
from crashcap_api.services.symbol_projection import update_symbol_health_for_promotion
from crashcap_api.services.uploads import release_artifact_blob_claim
from crashcap_api.storage import ObjectNotFoundError, ObjectStore, put_json, stream_sha256
from crashcap_api.task_handoff import (
    TaskClaim,
    claim_is_current,
    claim_task,
    finish_claim,
    heartbeat_claim,
    publish_after_commit,
    reindex_inventory_snapshot,
    stage_task_message,
)
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from .core_runner import CoreExecutionError, CoreExecutor, CoreOutput
from .source_bundle import (
    SourceBundleError,
    attach_source_context,
    inspect_source_bundle,
    stage_source_bundles,
)
from .symbols import SymbolIngestor

LOGGER = logging.getLogger(__name__)
BLOCKING_WARNING_PREFIXES = (
    "missing_",
    "pdb_mismatch",
    "pe_mismatch",
    "symbolicator_",
    "corrupt",
)


class WorkerProcessor:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker[Session],
        store: ObjectStore,
        dispatcher: TaskDispatcher,
        core: CoreExecutor | None = None,
        symbols: SymbolIngestor | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.store = store
        self.dispatcher = dispatcher
        self.core = core or CoreExecutor(settings)
        self.symbols = symbols or SymbolIngestor(settings)

    def verify_upload(self, message: dict[str, Any]) -> None:
        lease_seconds = self.settings.task_lease_seconds
        claim: TaskClaim | None = None
        try:
            with self.sessions() as session:
                claim = claim_task(
                    session,
                    message,
                    self.settings.schema_root,
                    receipt_mode=self.settings.task_receipt_mode,
                    lease_seconds=lease_seconds,
                )
                if not claim.acquired:
                    session.commit()
                    return
                upload = session.get(Upload, message["upload_id"])
                if upload is None:
                    finish_claim(session, claim, "dead")
                    session.commit()
                    LOGGER.warning(
                        "verification task references missing upload",
                        extra=_task_log_context(
                            message, claim, outcome="dead", reason="target_missing"
                        ),
                    )
                    return
                if upload.verification_status != "VERIFYING":
                    finish_claim(session, claim, "succeeded")
                    session.commit()
                    return
                object_key = upload.object_key
                session.commit()

            digest, size, prefix = stream_sha256(self.store, object_key)
            with self.sessions() as session:
                upload_snapshot = session.get(Upload, message["upload_id"])
                if upload_snapshot is None:
                    self._finish_non_analysis_claim(claim, "dead")
                    return
                rejection = _verify_payload(upload_snapshot, digest, size, prefix)
                if rejection is None:
                    rejection = _content_expectation_rejection(
                        session, upload_snapshot, digest, size
                    )
                file_kind = upload_snapshot.file_kind
                workspace_id = upload_snapshot.workspace_id
                build_id = upload_snapshot.build_id

            prepared_id: str | None = None
            prepared_key: str | None = None
            if rejection is None:
                if file_kind == "dmp":
                    prepared_id = new_id("blob")
                    prepared_key = dump_blob_key(workspace_id, prepared_id)
                else:
                    if build_id is None:
                        raise RuntimeError("artifact upload lost its Build")
                    prepared_key = raw_build_key(workspace_id, build_id, digest)
                self.store.copy(object_key, prepared_key)

            downstream: dict[str, Any] | None = None
            with self.sessions() as session:
                if not claim_is_current(session, claim, lock=True):
                    return
                upload = session.scalar(
                    select(Upload).where(Upload.id == message["upload_id"]).with_for_update()
                )
                if upload is None:
                    finish_claim(session, claim, "dead")
                    session.commit()
                    return
                if upload.verification_status != "VERIFYING":
                    finish_claim(session, claim, "succeeded")
                    session.commit()
                    return
                upload.verified_length = size
                upload.verified_sha256 = digest
                if rejection is not None:
                    transition_upload(upload, "REJECTED")
                    upload.rejection_reason = rejection
                    release_artifact_blob_claim(session, upload.id)
                    if upload.build_id is not None:
                        origins = session.scalars(
                            select(BuildPublication.origin).where(
                                BuildPublication.build_id == upload.build_id
                            )
                        ).all()
                        for origin in set(origins):
                            BUILD_PUBLICATION_REJECTIONS.labels(origin, rejection).inc()
                    operation_log(
                        session,
                        action="upload.verify",
                        target_type="upload",
                        target_id=upload.id,
                        workspace_id=upload.workspace_id,
                        request_id=message.get("request_id"),
                        result="rejected",
                        details={"reason": rejection},
                    )
                    finish_claim(session, claim, "succeeded")
                    session.commit()
                    return
                assert prepared_key is not None
                if upload.file_kind == "dmp":
                    assert prepared_id is not None
                    downstream = self._accept_dump(
                        session,
                        upload,
                        blob_id=prepared_id,
                        object_key=prepared_key,
                        request_id=message.get("request_id"),
                    )
                else:
                    downstream = self._accept_artifact(
                        session,
                        upload,
                        object_key=prepared_key,
                        request_id=message.get("request_id"),
                    )
                transition_upload(upload, "ACCEPTED")
                operation_log(
                    session,
                    action="upload.verify",
                    target_type="upload",
                    target_id=upload.id,
                    workspace_id=upload.workspace_id,
                    request_id=message.get("request_id"),
                    details={"sha256": digest, "verified_length": size},
                )
                if not finish_claim(session, claim, "succeeded"):
                    session.rollback()
                    return
                session.commit()
            if downstream is not None:
                with self.sessions() as session:
                    publish_after_commit(session, self.settings, self.dispatcher, downstream)
        except Exception:
            if claim is not None and claim.acquired:
                self._finish_non_analysis_claim(claim, "failed")
            raise

    def _accept_dump(
        self,
        session: Session,
        upload: Upload,
        *,
        blob_id: str,
        object_key: str,
        request_id: str | None,
    ) -> dict[str, Any] | None:
        assert upload.verified_sha256 is not None
        workspace = session.get(Workspace, upload.workspace_id)
        if workspace is None:
            raise RuntimeError("upload Workspace disappeared")
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            lock_key = f"{upload.workspace_id}:{upload.verified_sha256}"
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key}
            )
        blob = session.scalar(
            select(DumpBlob).where(
                DumpBlob.workspace_id == upload.workspace_id,
                DumpBlob.sha256 == upload.verified_sha256,
            )
        )
        if blob is None:
            blob = DumpBlob(
                id=blob_id,
                workspace_id=upload.workspace_id,
                sha256=upload.verified_sha256,
                size=upload.verified_length or upload.declared_length,
                object_key=object_key,
                dump_kind="user_minidump",
                verification_status="ACCEPTED",
                uploaded_at=upload.completed_at or utcnow(),
                expires_at=(upload.completed_at or utcnow())
                + timedelta(days=workspace.retention_days),
            )
            session.add(blob)
            session.flush()
        occurrence = session.scalar(select(Occurrence).where(Occurrence.dump_blob_id == blob.id))
        if occurrence is None:
            uploaded_at = upload.completed_at or utcnow()
            occurred_at = upload.reported_at or uploaded_at
            occurrence = Occurrence(
                id=new_id("occ"),
                workspace_id=upload.workspace_id,
                dump_blob_id=blob.id,
                reported_build_id=upload.reported_build_id,
                reported_at=upload.reported_at,
                uploaded_at=uploaded_at,
                occurred_at=occurred_at,
                time_source="reported" if upload.reported_at else "uploaded",
            )
            session.add(occurrence)
            session.flush()
        creation = create_analysis_run(
            session,
            self.settings,
            occurrence,
            reported_build_id=upload.reported_build_id,
            capture_profile=upload.capture_profile,
            request_id=request_id,
        )
        return creation.message

    def _accept_artifact(
        self,
        session: Session,
        upload: Upload,
        *,
        object_key: str,
        request_id: str | None,
    ) -> dict[str, Any] | None:
        assert upload.build_id is not None
        assert upload.verified_sha256 is not None
        existing = session.scalar(
            select(Artifact).where(
                Artifact.build_id == upload.build_id,
                Artifact.kind == upload.file_kind,
                Artifact.sha256 == upload.verified_sha256,
                Artifact.logical_name == upload.original_filename,
            )
        )
        if existing is not None:
            # Duplicate/retried transfers must never strand a delivery-v1
            # Workspace+SHA claim, regardless of whether the existing binding
            # predates Artifact Blobs.
            release_artifact_blob_claim(session, upload.id)
            return None
        artifact_id = new_id("art")
        build = session.get(Build, upload.build_id)
        if build is None:
            raise RuntimeError("artifact upload Build disappeared")
        if build.identity_mode == "content_v1":
            expectation = session.scalar(
                select(BuildArtifactExpectation).where(
                    BuildArtifactExpectation.build_id == upload.build_id,
                    BuildArtifactExpectation.kind == upload.file_kind,
                    BuildArtifactExpectation.normalized_name == upload.original_filename.casefold(),
                )
            )
            if expectation is None:
                raise RuntimeError("content Build upload has no Artifact expectation")
            module = session.get(BuildModule, expectation.module_id)
        else:
            module = _find_manifest_module(
                session, upload.build_id, upload.file_kind, upload.original_filename
            )
        artifact = Artifact(
            id=artifact_id,
            build_id=upload.build_id,
            module_id=module.id if module else None,
            kind=upload.file_kind,
            logical_name=upload.original_filename,
            sha256=upload.verified_sha256,
            size=upload.verified_length or upload.declared_length,
            object_key=object_key,
            verification_status="pending",
            materialization_source=(
                "upload" if self.settings.artifact_blob_dedup_mode != "off" else "legacy"
            ),
        )
        session.add(artifact)
        session.flush()
        blob_mode = self.settings.artifact_blob_dedup_mode != "off" and upload.file_kind in {
            "pe",
            "pdb",
        }
        message = {
            "schema_version": "1.1" if blob_mode else "1.0",
            "task_type": "ingest_artifact",
            "artifact_id": artifact.id,
            "attempt_id": f"att_{new_ulid()}",
            "queue": "ingest",
        }
        if blob_mode:
            message["upload_id"] = upload.id
        if request_id:
            message["request_id"] = request_id
        return stage_task_message(session, self.settings, message)

    def ingest_artifact(self, message: dict[str, Any]) -> None:
        lease_seconds = self.settings.task_lease_seconds
        claim: TaskClaim | None = None
        try:
            with self.sessions() as session:
                claim = claim_task(
                    session,
                    message,
                    self.settings.schema_root,
                    receipt_mode=self.settings.task_receipt_mode,
                    lease_seconds=lease_seconds,
                )
                if not claim.acquired:
                    session.commit()
                    return
                artifact = session.get(Artifact, message["artifact_id"])
                if artifact is None:
                    finish_claim(session, claim, "dead")
                    session.commit()
                    LOGGER.warning(
                        "ingest task references missing Artifact",
                        extra=_task_log_context(
                            message, claim, outcome="dead", reason="target_missing"
                        ),
                    )
                    return
                prior_status = artifact.verification_status
                snapshot = {
                    "id": artifact.id,
                    "kind": artifact.kind,
                    "logical_name": artifact.logical_name,
                    "object_key": artifact.object_key,
                    "sha256": artifact.sha256,
                }
                session.commit()

            if prior_status != "pending":
                if prior_status == "verified":
                    self._publish_verified_pair(str(snapshot["id"]))
                self._finish_non_analysis_claim(claim, "succeeded")
                return

            prepared: dict[str, Any]
            with tempfile.TemporaryDirectory(
                prefix=f"ingest-{snapshot['id']}-",
                dir=_existing_temp_root(self.settings.task_tmp_root),
            ) as raw_temp:
                local_path = Path(raw_temp) / str(snapshot["logical_name"])
                self.store.download_file(str(snapshot["object_key"]), local_path)
                if snapshot["kind"] == "source_bundle":
                    try:
                        metadata = inspect_source_bundle(local_path)
                        prepared = {"status": "verified", "metadata": metadata}
                    except SourceBundleError as error:
                        prepared = {
                            "status": "rejected_format",
                            "reason": str(error),
                        }
                else:
                    try:
                        identity = self.core.identify_artifact(local_path, str(snapshot["kind"]))
                    except CoreExecutionError as error:
                        prepared = {"status": "corrupted", "reason": error.code}
                    else:
                        if identity["sha256"].lower() != str(snapshot["sha256"]).lower():
                            prepared = {"status": "corrupted", "reason": "sha256_mismatch"}
                        elif snapshot["kind"] == "pdb" and identity.get("is_fastlink"):
                            prepared = {"status": "rejected_fastlink", "identity": identity}
                        else:
                            prepared = {"status": "verified", "identity": identity}

            if (
                snapshot["kind"] in {"pe", "pdb"}
                and self.settings.artifact_blob_dedup_mode != "off"
            ):
                self._ingest_artifact_blob(message, claim, snapshot, prepared)
                return

            if snapshot["kind"] in {"pe", "pdb"} and prepared["status"] == "verified":
                identity = cast(dict[str, Any], prepared["identity"])
                with self.sessions() as session:
                    if not claim_is_current(session, claim, lock=True):
                        return
                    artifact = session.scalar(
                        select(Artifact)
                        .where(Artifact.id == message["artifact_id"])
                        .with_for_update()
                    )
                    if artifact is None:
                        finish_claim(session, claim, "dead")
                        session.commit()
                        return
                    if artifact.verification_status == "pending":
                        # Identification is a durable, non-terminal checkpoint.
                        # It lets the second half of a concurrently ingested pair
                        # observe readiness without holding a row lock during
                        # object downloads or symsorter publication.
                        artifact.code_id = identity.get("code_id")
                        artifact.debug_id = identity.get("debug_id")
                    session.commit()
                prepared["status"] = self._publish_prepared_pair(str(snapshot["id"]))

            with self.sessions() as session:
                if not claim_is_current(session, claim, lock=True):
                    return
                artifact = session.scalar(
                    select(Artifact).where(Artifact.id == message["artifact_id"]).with_for_update()
                )
                if artifact is None:
                    finish_claim(session, claim, "dead")
                    session.commit()
                    return
                if artifact.verification_status != "pending":
                    finish_claim(session, claim, "succeeded")
                    session.commit()
                else:
                    build = session.get(Build, artifact.build_id)
                    module = (
                        session.get(BuildModule, artifact.module_id) if artifact.module_id else None
                    )
                    if build is None:
                        raise RuntimeError("artifact Build disappeared")
                    artifact.verification_status = str(prepared["status"])
                    if artifact.kind == "source_bundle":
                        artifact.ingest_metadata = cast(
                            dict[str, Any] | None,
                            prepared.get("metadata"),
                        )
                    else:
                        identity = cast(dict[str, Any], prepared.get("identity") or {})
                        artifact.code_id = identity.get("code_id")
                        artifact.debug_id = identity.get("debug_id")
                        if artifact.verification_status == "verified" and module is not None:
                            if artifact.kind == "pe":
                                module.code_id = artifact.code_id
                                module.debug_id = artifact.debug_id
                            elif artifact.kind == "pdb":
                                if (
                                    module.debug_id
                                    and artifact.debug_id
                                    and module.debug_id.lower() != artifact.debug_id.lower()
                                ):
                                    artifact.verification_status = "pdb_mismatch"
                                else:
                                    module.debug_id = artifact.debug_id
                    if (
                        artifact.verification_status == "verified"
                        and build.identity_mode != "content_v1"
                    ):
                        session.execute(
                            update(Workspace)
                            .where(Workspace.id == build.workspace_id)
                            .values(symbol_inventory_version=Workspace.symbol_inventory_version + 1)
                        )
                    action = (
                        "source_bundle.ingest"
                        if artifact.kind == "source_bundle"
                        else "artifact.ingest"
                    )
                    details: dict[str, Any] = {"kind": artifact.kind}
                    if prepared.get("reason"):
                        details["reason"] = prepared["reason"]
                    if artifact.ingest_metadata:
                        details.update(
                            source_entry_count=artifact.ingest_metadata.get("source_entry_count"),
                            policy_version=artifact.ingest_metadata.get("policy_version"),
                        )
                    operation_log(
                        session,
                        action=action,
                        target_type="artifact",
                        target_id=artifact.id,
                        workspace_id=build.workspace_id,
                        request_id=message.get("request_id"),
                        result=artifact.verification_status,
                        details=details,
                    )
                    if (
                        build.identity_mode == "content_v1"
                        and artifact.verification_status != "verified"
                    ):
                        origins = session.scalars(
                            select(BuildPublication.origin).where(
                                BuildPublication.build_id == build.id
                            )
                        ).all()
                        reason = str(prepared.get("reason") or artifact.verification_status)
                        for origin in set(origins):
                            BUILD_PUBLICATION_REJECTIONS.labels(origin, reason).inc()
                    sealed_build, newly_sealed = seal_content_build(session, build.id)
                    if newly_sealed and sealed_build is not None:
                        session.execute(
                            update(Workspace)
                            .where(Workspace.id == sealed_build.workspace_id)
                            .values(symbol_inventory_version=Workspace.symbol_inventory_version + 1)
                        )
                        publications = session.scalars(
                            select(BuildPublication).where(
                                BuildPublication.build_id == sealed_build.id
                            )
                        ).all()
                        now = datetime.now(UTC)
                        for publication in publications:
                            BUILD_PUBLICATIONS.labels(publication.origin, "ready").inc()
                            created_at = publication.created_at
                            if created_at.tzinfo is None:
                                created_at = created_at.replace(tzinfo=UTC)
                            elapsed = max(
                                0.0,
                                (now - created_at).total_seconds(),
                            )
                            BUILD_PUBLICATION_VERIFICATION_SECONDS.labels(
                                publication.origin
                            ).observe(elapsed)
                        operation_log(
                            session,
                            action="build.seal",
                            target_type="build",
                            target_id=sealed_build.id,
                            workspace_id=sealed_build.workspace_id,
                            request_id=message.get("request_id"),
                            result="ready",
                            details={
                                "fingerprint_version": sealed_build.fingerprint_version,
                                "publication_count": len(publications),
                            },
                        )
                    finish_claim(session, claim, "succeeded")
                    session.commit()
        except Exception:
            if claim is not None and claim.acquired:
                self._finish_non_analysis_claim(claim, "failed")
            raise

    def _ingest_artifact_blob(
        self,
        message: dict[str, Any],
        claim: TaskClaim,
        snapshot: dict[str, Any],
        prepared: dict[str, Any],
    ) -> None:
        if prepared["status"] != "verified":
            self._reject_artifact_blob_ingest(message, claim, prepared)
            return

        started = time.monotonic()
        with self.sessions() as session:
            artifact = session.get(Artifact, str(snapshot["id"]))
            build = session.get(Build, artifact.build_id) if artifact else None
            if artifact is None or build is None:
                self._finish_non_analysis_claim(claim, "dead")
                return
            workspace_id = build.workspace_id
        canonical_key = artifact_blob_key(workspace_id, str(snapshot["sha256"]))
        expected_size = 0
        try:
            expected_size = self.store.head(str(snapshot["object_key"])).size
            try:
                canonical_head = self.store.head(canonical_key)
            except ObjectNotFoundError:
                canonical_head = None
            if canonical_head is None or canonical_head.size != expected_size:
                self.store.copy(str(snapshot["object_key"]), canonical_key)
            digest, canonical_size, _prefix = stream_sha256(self.store, canonical_key)
            if digest != str(snapshot["sha256"]).lower() or canonical_size != expected_size:
                # A stale or corrupt canonical object is repaired only from the
                # just-verified transfer, then fully re-read before trust.
                self.store.copy(str(snapshot["object_key"]), canonical_key)
                digest, canonical_size, _prefix = stream_sha256(self.store, canonical_key)
            if digest != str(snapshot["sha256"]).lower() or canonical_size != expected_size:
                self._reject_artifact_blob_ingest(
                    message,
                    claim,
                    {"status": "corrupted", "reason": "canonical_copy_verification_failed"},
                )
                ARTIFACT_BLOB_VERIFICATION_SECONDS.labels(
                    str(snapshot["kind"]), "rejected"
                ).observe(time.monotonic() - started)
                return

            identity = cast(dict[str, Any], prepared["identity"])
            messages: list[dict[str, Any]] = []
            with self.sessions() as session:
                if not claim_is_current(session, claim, lock=True):
                    return
                artifact = session.scalar(
                    select(Artifact)
                    .where(Artifact.id == str(snapshot["id"]))
                    .with_for_update()
                )
                if artifact is None:
                    finish_claim(session, claim, "dead")
                    session.commit()
                    return
                build = session.get(Build, artifact.build_id)
                if build is None:
                    raise RuntimeError("Artifact Blob ingest Build disappeared")
                if session.bind is not None and session.bind.dialect.name == "postgresql":
                    session.execute(
                        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                        {"key": f"artifact-blob:{build.workspace_id}:{artifact.sha256}"},
                    )
                blob = session.scalar(
                    select(ArtifactBlob)
                    .where(
                        ArtifactBlob.workspace_id == build.workspace_id,
                        ArtifactBlob.sha256 == artifact.sha256,
                    )
                    .with_for_update()
                )
                conflict = _artifact_blob_identity_conflict(
                    blob,
                    kind=artifact.kind,
                    size=artifact.size,
                    identity=identity,
                )
                if conflict is not None:
                    artifact.verification_status = "rejected_format"
                    release_artifact_blob_claim(session, str(message.get("upload_id", "")))
                    ARTIFACT_BLOB_CONFLICTS.labels(conflict).inc()
                    operation_log(
                        session,
                        action="artifact_blob.verify",
                        target_type="artifact",
                        target_id=artifact.id,
                        workspace_id=build.workspace_id,
                        request_id=message.get("request_id"),
                        result="rejected",
                        details={"reason": conflict, "kind": artifact.kind},
                    )
                    finish_claim(session, claim, "succeeded")
                    session.commit()
                    ARTIFACT_BLOB_VERIFICATION_SECONDS.labels(
                        artifact.kind, "conflict"
                    ).observe(time.monotonic() - started)
                    return
                now = datetime.now(UTC)
                if blob is None:
                    blob = ArtifactBlob(
                        id=new_id("abl"),
                        workspace_id=build.workspace_id,
                        sha256=artifact.sha256.lower(),
                        kind=artifact.kind,
                        size=artifact.size,
                        object_key=canonical_key,
                        code_id=identity.get("code_id"),
                        debug_id=identity.get("debug_id"),
                        verification_status="verified",
                        verified_at=now,
                        updated_at=now,
                    )
                    session.add(blob)
                    session.flush()
                else:
                    blob.kind = artifact.kind
                    blob.size = artifact.size
                    blob.object_key = canonical_key
                    blob.code_id = identity.get("code_id")
                    blob.debug_id = identity.get("debug_id")
                    blob.verification_status = "verified"
                    blob.verification_reason = None
                    blob.verified_at = now
                    blob.updated_at = now
                old_object_key = artifact.object_key
                if old_object_key != canonical_key and session.get(
                    ArtifactBlobLegacyCopy, artifact.id
                ) is None:
                    session.add(
                        ArtifactBlobLegacyCopy(
                            artifact_id=artifact.id,
                            artifact_blob_id=blob.id,
                            object_key=old_object_key,
                        )
                    )
                artifact.artifact_blob_id = blob.id
                artifact.materialization_source = "upload"
                artifact.object_key = blob.object_key
                artifact.code_id = blob.code_id
                artifact.debug_id = blob.debug_id
                artifact.verification_status = "pending"
                if self.settings.artifact_blob_dedup_mode == "active":
                    messages.extend(
                        materialize_blob_across_builds(
                            session, self.settings, blob, source="blob_reuse"
                        )
                    )
                else:
                    messages.extend(reconcile_build_blob_pairs(session, self.settings, build))
                release_artifact_blob_claim(session, str(message.get("upload_id", "")))
                operation_log(
                    session,
                    action="artifact_blob.verify",
                    target_type="artifact_blob",
                    target_id=blob.id,
                    workspace_id=build.workspace_id,
                    request_id=message.get("request_id"),
                    result="verified",
                    details={"kind": blob.kind, "materialized_build_count": len(messages)},
                )
                if not finish_claim(session, claim, "succeeded"):
                    session.rollback()
                    return
                session.commit()
            for downstream in {
                str(item["attempt_id"]): item for item in messages
            }.values():
                with self.sessions() as session:
                    publish_after_commit(session, self.settings, self.dispatcher, downstream)
            ARTIFACT_BLOB_VERIFICATION_SECONDS.labels(
                str(snapshot["kind"]), "verified"
            ).observe(time.monotonic() - started)
        except Exception:
            ARTIFACT_BLOB_VERIFICATION_SECONDS.labels(
                str(snapshot["kind"]), "failed"
            ).observe(time.monotonic() - started)
            raise

    def _reject_artifact_blob_ingest(
        self,
        message: dict[str, Any],
        claim: TaskClaim,
        prepared: dict[str, Any],
    ) -> None:
        with self.sessions() as session:
            if not claim_is_current(session, claim, lock=True):
                return
            artifact = session.scalar(
                select(Artifact)
                .where(Artifact.id == str(message["artifact_id"]))
                .with_for_update()
            )
            if artifact is None:
                finish_claim(session, claim, "dead")
                session.commit()
                return
            build = session.get(Build, artifact.build_id)
            artifact.verification_status = str(prepared["status"])
            release_artifact_blob_claim(session, str(message.get("upload_id", "")))
            if build is not None:
                origins = session.scalars(
                    select(BuildPublication.origin).where(BuildPublication.build_id == build.id)
                ).all()
                reason = str(prepared.get("reason") or prepared["status"])
                for origin in set(origins):
                    BUILD_PUBLICATION_REJECTIONS.labels(origin, reason).inc()
                operation_log(
                    session,
                    action="artifact_blob.verify",
                    target_type="artifact",
                    target_id=artifact.id,
                    workspace_id=build.workspace_id,
                    request_id=message.get("request_id"),
                    result="rejected",
                    details={"reason": reason, "kind": artifact.kind},
                )
            finish_claim(session, claim, "succeeded")
            session.commit()

    def publish_artifact_blob_pair(self, message: dict[str, Any]) -> None:
        claim: TaskClaim | None = None
        try:
            with self.sessions() as session:
                claim = claim_task(
                    session,
                    message,
                    self.settings.schema_root,
                    receipt_mode=self.settings.task_receipt_mode,
                    lease_seconds=self.settings.task_lease_seconds,
                )
                if not claim.acquired:
                    session.commit()
                    return
                pair = session.get(ArtifactBlobPair, message["artifact_blob_pair_id"])
                if pair is None:
                    finish_claim(session, claim, "dead")
                    session.commit()
                    return
                pe_blob = session.get(ArtifactBlob, pair.pe_blob_id)
                pdb_blob = session.get(ArtifactBlob, pair.pdb_blob_id)
                if pe_blob is None or pdb_blob is None:
                    finish_claim(session, claim, "dead")
                    session.commit()
                    return
                prior_state = pair.state
                snapshot = {
                    "workspace_id": pair.workspace_id,
                    "pe_key": pe_blob.object_key,
                    "pdb_key": pdb_blob.object_key,
                    "pe_id": pe_blob.id,
                    "pdb_id": pdb_blob.id,
                    "debug_id": pe_blob.debug_id,
                    "pdb_debug_id": pdb_blob.debug_id,
                    "pe_status": pe_blob.verification_status,
                    "pdb_status": pdb_blob.verification_status,
                }
                session.commit()

            if prior_state == "pending":
                mismatch = (
                    snapshot["pe_status"] != "verified"
                    or snapshot["pdb_status"] != "verified"
                    or not snapshot["debug_id"]
                    or not snapshot["pdb_debug_id"]
                    or str(snapshot["debug_id"]).lower()
                    != str(snapshot["pdb_debug_id"]).lower()
                )
                if not mismatch:
                    with tempfile.TemporaryDirectory(
                        prefix=f"blob-pair-{message['artifact_blob_pair_id']}-",
                        dir=_existing_temp_root(self.settings.task_tmp_root),
                    ) as raw_temp:
                        root = Path(raw_temp)
                        pe_path, pdb_path = root / "module.pe", root / "module.pdb"
                        self.store.download_file(str(snapshot["pe_key"]), pe_path)
                        self.store.download_file(str(snapshot["pdb_key"]), pdb_path)
                        self.symbols.publish_pair(
                            str(snapshot["workspace_id"]),
                            pe_path,
                            pdb_path,
                            str(snapshot["debug_id"]),
                        )
                next_state = "rejected" if mismatch else "published"
            else:
                next_state = prior_state

            with self.sessions() as session:
                if not claim_is_current(session, claim, lock=True):
                    return
                pair = session.scalar(
                    select(ArtifactBlobPair)
                    .where(ArtifactBlobPair.id == message["artifact_blob_pair_id"])
                    .with_for_update()
                )
                if pair is None:
                    finish_claim(session, claim, "dead")
                    session.commit()
                    return
                if pair.state == "pending":
                    pair.state = next_state
                    pair.updated_at = datetime.now(UTC)
                    if next_state == "published":
                        pair.published_at = pair.updated_at
                        pair.rejection_reason = None
                    else:
                        pair.rejection_reason = "debug_id_mismatch"
                        ARTIFACT_BLOB_CONFLICTS.labels("pair_mismatch").inc()
                _affected, newly_sealed = apply_pair_to_bindings(session, pair)
                for build in newly_sealed:
                    publications = session.scalars(
                        select(BuildPublication).where(BuildPublication.build_id == build.id)
                    ).all()
                    now = datetime.now(UTC)
                    for publication in publications:
                        BUILD_PUBLICATIONS.labels(publication.origin, "ready").inc()
                        created_at = publication.created_at
                        if created_at.tzinfo is None:
                            created_at = created_at.replace(tzinfo=UTC)
                        BUILD_PUBLICATION_VERIFICATION_SECONDS.labels(
                            publication.origin
                        ).observe(max(0.0, (now - created_at).total_seconds()))
                    operation_log(
                        session,
                        action="build.seal",
                        target_type="build",
                        target_id=build.id,
                        workspace_id=build.workspace_id,
                        request_id=message.get("request_id"),
                        result="ready",
                        details={
                            "fingerprint_version": build.fingerprint_version,
                            "publication_count": len(publications),
                            "source": "artifact_blob_pair",
                        },
                    )
                operation_log(
                    session,
                    action="artifact_blob_pair.publish",
                    target_type="artifact_blob_pair",
                    target_id=pair.id,
                    workspace_id=pair.workspace_id,
                    request_id=message.get("request_id"),
                    result=pair.state,
                    details={"sealed_build_count": len(newly_sealed)},
                )
                finish_claim(session, claim, "succeeded")
                session.commit()
        except Exception:
            if claim is not None and claim.acquired:
                self._finish_non_analysis_claim(claim, "failed")
            raise

    def _publish_prepared_pair(self, artifact_id: str) -> str:
        with self.sessions() as session:
            artifact = session.get(Artifact, artifact_id)
            if artifact is None or artifact.module_id is None or artifact.debug_id is None:
                return "verified"
            counterpart = _counterpart(session, artifact)
            if (
                counterpart is None
                or counterpart.verification_status not in {"pending", "verified"}
                or counterpart.debug_id is None
            ):
                return "verified"
            if not _debug_ids_match(artifact, counterpart):
                return f"{artifact.kind}_mismatch"
            build = session.get(Build, artifact.build_id)
            if build is None:
                raise RuntimeError("prepared symbol pair references missing Build")
            pe = artifact if artifact.kind == "pe" else counterpart
            pdb = artifact if artifact.kind == "pdb" else counterpart
            workspace_id = build.workspace_id
            pe_key, pdb_key = pe.object_key, pdb.object_key
            pe_name, pdb_name = pe.logical_name, pdb.logical_name
            debug_id = artifact.debug_id
        with tempfile.TemporaryDirectory(
            prefix=f"prepare-publish-{artifact_id}-",
            dir=_existing_temp_root(self.settings.task_tmp_root),
        ) as raw_temp:
            root = Path(raw_temp)
            pe_path, pdb_path = root / pe_name, root / pdb_name
            self.store.download_file(pe_key, pe_path)
            self.store.download_file(pdb_key, pdb_path)
            self.symbols.publish_pair(workspace_id, pe_path, pdb_path, debug_id)
        return "verified"

    def _publish_verified_pair(self, artifact_id: str) -> None:
        with self.sessions() as session:
            artifact = session.get(Artifact, artifact_id)
            if (
                artifact is None
                or artifact.verification_status != "verified"
                or artifact.module_id is None
            ):
                return
            counterpart = _counterpart(session, artifact)
            if (
                counterpart is None
                or counterpart.verification_status != "verified"
                or not _debug_ids_match(artifact, counterpart)
            ):
                return
            build = session.get(Build, artifact.build_id)
            if build is None or artifact.debug_id is None:
                raise RuntimeError("verified symbol pair references incomplete Build state")
            pe = artifact if artifact.kind == "pe" else counterpart
            pdb = artifact if artifact.kind == "pdb" else counterpart
            workspace_id = build.workspace_id
            pe_key, pdb_key = pe.object_key, pdb.object_key
            pe_name, pdb_name = pe.logical_name, pdb.logical_name
            debug_id = artifact.debug_id
        with tempfile.TemporaryDirectory(
            prefix=f"publish-{artifact_id}-",
            dir=_existing_temp_root(self.settings.task_tmp_root),
        ) as raw_temp:
            root = Path(raw_temp)
            pe_path, pdb_path = root / pe_name, root / pdb_name
            self.store.download_file(pe_key, pe_path)
            self.store.download_file(pdb_key, pdb_path)
            self.symbols.publish_pair(workspace_id, pe_path, pdb_path, debug_id)

    def reindex_symbols(self, message: dict[str, Any]) -> None:
        lease_seconds = self.settings.task_lease_seconds
        claim: TaskClaim | None = None
        workspace_id = str(message["workspace_id"])
        try:
            with self.sessions() as session:
                claim = claim_task(
                    session,
                    message,
                    self.settings.schema_root,
                    receipt_mode=self.settings.task_receipt_mode,
                    lease_seconds=lease_seconds,
                )
                if not claim.acquired:
                    session.commit()
                    return
                workspace = session.get(Workspace, workspace_id)
                if workspace is None:
                    finish_claim(session, claim, "dead")
                    session.commit()
                    LOGGER.warning(
                        "reindex task references missing Workspace",
                        extra=_task_log_context(
                            message, claim, outcome="dead", reason="target_missing"
                        ),
                    )
                    return
                inventory_snapshot = reindex_inventory_snapshot(claim.logical_key)
                if (
                    inventory_snapshot is not None
                    and workspace.symbol_inventory_version != inventory_snapshot
                ):
                    operation_log(
                        session,
                        action="symbols.reindex",
                        target_type="workspace",
                        target_id=workspace_id,
                        workspace_id=workspace_id,
                        request_id=message.get("request_id"),
                        result="stale_noop",
                        details={
                            "intent_inventory_version": inventory_snapshot,
                            "current_inventory_version": workspace.symbol_inventory_version,
                        },
                    )
                    finish_claim(session, claim, "succeeded")
                    session.commit()
                    return
                build_filter = message.get("build_id")
                query = (
                    select(BuildModule, Build)
                    .join(Build, Build.id == BuildModule.build_id)
                    .where(Build.workspace_id == workspace_id)
                )
                if build_filter:
                    query = query.where(Build.id == build_filter)
                rows = session.execute(query).all()
                pairs: list[dict[str, str]] = []
                for module, _build in rows:
                    artifact_pair = session.scalars(
                        select(Artifact).where(
                            Artifact.module_id == module.id,
                            Artifact.verification_status == "verified",
                            Artifact.kind.in_(["pe", "pdb"]),
                        )
                    ).all()
                    pe = next((item for item in artifact_pair if item.kind == "pe"), None)
                    pdb = next((item for item in artifact_pair if item.kind == "pdb"), None)
                    if pe is None or pdb is None or not _debug_ids_match(pe, pdb):
                        continue
                    assert pe.debug_id is not None
                    pairs.append(
                        {
                            "pe_id": pe.id,
                            "pe_key": pe.object_key,
                            "pdb_id": pdb.id,
                            "pdb_key": pdb.object_key,
                            "debug_id": pe.debug_id,
                        }
                    )
                session.commit()

            with tempfile.TemporaryDirectory(
                prefix="reindex-", dir=_existing_temp_root(self.settings.task_tmp_root)
            ) as raw_temp:
                root = Path(raw_temp)
                for pair_snapshot in pairs:
                    pe_path = root / pair_snapshot["pe_id"]
                    pdb_path = root / pair_snapshot["pdb_id"]
                    self.store.download_file(pair_snapshot["pe_key"], pe_path)
                    self.store.download_file(pair_snapshot["pdb_key"], pdb_path)
                    self.symbols.publish_pair(
                        workspace_id,
                        pe_path,
                        pdb_path,
                        pair_snapshot["debug_id"],
                    )

            with self.sessions() as session:
                if not claim_is_current(session, claim, lock=True):
                    return
                workspace = session.scalar(
                    select(Workspace).where(Workspace.id == workspace_id).with_for_update()
                )
                if workspace is None:
                    finish_claim(session, claim, "dead")
                    session.commit()
                    return
                stale = (
                    inventory_snapshot is not None
                    and workspace.symbol_inventory_version != inventory_snapshot
                )
                operation_log(
                    session,
                    action="symbols.reindex",
                    target_type="workspace",
                    target_id=workspace_id,
                    workspace_id=workspace_id,
                    request_id=message.get("request_id"),
                    result="stale_after_work" if stale else "completed",
                    details={
                        "intent_inventory_version": inventory_snapshot,
                        "current_inventory_version": workspace.symbol_inventory_version,
                        "published_pair_count": len(pairs),
                    },
                )
                finish_claim(session, claim, "succeeded")
                session.commit()
        except Exception:
            if claim is not None and claim.acquired:
                self._finish_non_analysis_claim(claim, "failed")
            raise

    def _finish_non_analysis_claim(
        self,
        claim: TaskClaim,
        outcome: Literal["succeeded", "failed", "dead"],
    ) -> bool:
        with self.sessions() as session:
            if not claim_is_current(session, claim, lock=True):
                return False
            accepted = finish_claim(session, claim, outcome)
            if accepted:
                session.commit()
            else:
                session.rollback()
            return accepted

    def analyze_occurrence(self, message: dict[str, Any]) -> None:
        lease_seconds = max(
            self.settings.task_lease_seconds,
            self.settings.core_timeout_seconds + 300,
        )
        with self.sessions() as session:
            claim = claim_task(
                session,
                message,
                self.settings.schema_root,
                receipt_mode=self.settings.task_receipt_mode,
                lease_seconds=lease_seconds,
            )
            if not claim.acquired:
                session.commit()
                return
            run = session.get(AnalysisRun, message["run_id"])
            if run is None:
                finish_claim(session, claim, "dead")
                session.commit()
                LOGGER.warning(
                    "analysis task references missing Run",
                    extra=_task_log_context(
                        message, claim, outcome="dead", reason="target_missing"
                    ),
                )
                return
            from crashcap_api.analysis_states import TERMINAL_STATES

            if run.status in TERMINAL_STATES:
                finish_claim(session, claim, "succeeded")
                session.commit()
                return
            if run.status == "UPLOADED":
                transition_analysis(run, "VALIDATING")
            spec = dict(run.run_spec)
            session.commit()

        try:
            output = self._execute_analysis(message, spec, claim, lease_seconds)
            if output is None:
                return
            self._persist_analysis(message, output, claim)
        except CoreExecutionError as error:
            self._fail_run(message, claim, error.code, str(error))
        except CanonicalSemanticError as error:
            self._fail_run(message, claim, "CANONICAL_SEMANTIC_MISMATCH", str(error))
        except Exception as error:
            self._fail_run(message, claim, "PLATFORM_WORKER_FAILED", str(error))
            raise

    def _execute_analysis(
        self,
        message: dict[str, Any],
        spec: dict[str, Any],
        claim: TaskClaim,
        lease_seconds: int,
    ) -> CoreOutput | None:
        self.settings.task_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f"{spec['run_id']}-", dir=self.settings.task_tmp_root
        ) as raw_temp:
            task_dir = Path(raw_temp)
            self.store.download_file(spec["blob"]["object_key"], task_dir / "dump.dmp")

            with self.sessions() as session:
                run = session.get(AnalysisRun, spec["run_id"])
                inspect_key = run.inspect_object_key if run else None
            inspect: dict[str, Any]
            match: dict[str, Any] | None = None
            legacy_output: CoreOutput | None = None
            prepared_core = self._uses_prepared_core()
            if inspect_key:
                try:
                    self.store.download_file(inspect_key, task_dir / "inspect.json")
                    inspect = cast(
                        dict[str, Any],
                        json.loads((task_dir / "inspect.json").read_text(encoding="utf-8")),
                    )
                except Exception:
                    LOGGER.warning("analysis inspect checkpoint is unavailable; recomputing")
                    inspect_key = None
            if not inspect_key:
                if prepared_core:
                    inspect = self.core.inspect(task_dir, spec)
                else:
                    # Compatibility for existing Core test doubles and a
                    # rollback image that only exposes the legacy combined seam.
                    match = _materialize_match_spec(self.store, task_dir, spec)
                    (task_dir / "match.json").write_text(
                        json.dumps(match, indent=2, sort_keys=True), encoding="utf-8"
                    )
                    legacy_output = self.core.analyze(task_dir, spec)
                    inspect = legacy_output.inspect
                inspect_key = analysis_generation_key(
                    spec["workspace_id"],
                    spec["occurrence_id"],
                    spec["run_id"],
                    claim.attempt_id,
                    claim.generation,
                    "checkpoints/inspect.json",
                )
                put_json(self.store, inspect_key, inspect)
            if not self._record_inspect_checkpoint(
                message,
                claim,
                inspect,
                inspect_key,
                lease_seconds,
            ):
                return None
            with self.sessions() as session:
                frozen_run = session.get(AnalysisRun, spec["run_id"])
                if frozen_run is None or frozen_run.analysis_context is None:
                    raise RuntimeError("analysis context was not frozen after inspect")
                analysis_context = frozen_run.analysis_context
                assembly_mode = frozen_run.assembly_mode
            if assembly_mode in {"shadow", "core-final"}:
                try:
                    runtime_context = stage_source_bundles(
                        self.store,
                        analysis_context,
                        task_dir,
                    )
                except SourceBundleError as error:
                    runtime_context = json.loads(json.dumps(analysis_context))
                    runtime_inputs = cast(dict[str, Any], runtime_context["inputs"])
                    runtime_inputs["source_bundles"] = []
                    runtime_inputs["source_bundle_error"] = str(error)
                (task_dir / "analysis-context.json").write_bytes(
                    canonical_json_bytes(runtime_context)
                )
            if not self._begin_symbol_matching(claim, spec["run_id"], lease_seconds):
                return None
            if match is None:
                match = _materialize_match_spec(self.store, task_dir, spec)
                (task_dir / "match.json").write_text(
                    json.dumps(match, indent=2, sort_keys=True), encoding="utf-8"
                )
            match_key = analysis_generation_key(
                spec["workspace_id"],
                spec["occurrence_id"],
                spec["run_id"],
                claim.attempt_id,
                claim.generation,
                "checkpoints/match.json",
            )
            put_json(self.store, match_key, match)
            if not self._mark_analysis_queued(claim, spec["run_id"], lease_seconds):
                return None
            if not self._mark_analysis_running(claim, spec["run_id"], lease_seconds):
                return None
            output = (
                legacy_output
                if legacy_output is not None
                else self.core.analyze_prepared(task_dir, spec)
                if prepared_core
                else self.core.analyze(task_dir, spec)
            )
            canonical = output.canonical
            shadow_differences: tuple[str, ...] = ()
            if assembly_mode == "legacy":
                canonical = bind_legacy_canonical(canonical, analysis_context)
                _attach_source_context_compat(self.store, canonical, spec, task_dir)
            elif assembly_mode == "shadow":
                legacy_path = output.raw.get("raw/legacy-canonical.json")
                legacy_base = (
                    cast(
                        dict[str, Any],
                        json.loads(legacy_path.read_text(encoding="utf-8")),
                    )
                    if legacy_path is not None
                    else canonical
                )
                legacy = bind_legacy_canonical(legacy_base, analysis_context)
                _attach_source_context_compat(self.store, legacy, spec, task_dir)
                shadow_differences = tuple(canonical_parity_differences(legacy, canonical))
                CANONICAL_SHADOW_RESULTS.labels("mismatch" if shadow_differences else "match").inc()
                shadow_path = task_dir / "raw" / "core-final-shadow.json"
                shadow_path.parent.mkdir(parents=True, exist_ok=True)
                shadow_path.write_bytes(canonical_json_bytes(canonical))
                output.raw["raw/core-final-shadow.json"] = shadow_path
                canonical = legacy
            detached = Path(tempfile.mkdtemp(prefix=f"{spec['run_id']}-result-"))
            paths: dict[str, Path] = {}
            for name, source in output.raw.items():
                destination = detached / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                paths[name] = destination
            return CoreOutput(
                inspect=output.inspect,
                canonical=canonical,
                raw=paths,
                shadow_differences=shadow_differences,
            )

    def _uses_prepared_core(self) -> bool:
        return (
            isinstance(self.core, CoreExecutor)
            and type(self.core).analyze is CoreExecutor.analyze
            and "analyze" not in vars(self.core)
        )

    def _record_inspect_checkpoint(
        self,
        message: dict[str, Any],
        claim: TaskClaim,
        inspect: dict[str, Any],
        inspect_key: str,
        lease_seconds: int,
    ) -> bool:
        with self.sessions() as session:
            if not claim_is_current(session, claim, lock=True):
                return False
            run = session.scalar(
                select(AnalysisRun).where(AnalysisRun.id == message["run_id"]).with_for_update()
            )
            if run is None:
                return False
            occurrence = session.scalar(
                select(Occurrence).where(Occurrence.id == run.occurrence_id).with_for_update()
            )
            blob = session.get(DumpBlob, occurrence.dump_blob_id) if occurrence else None
            if occurrence is None or blob is None:
                raise RuntimeError("analysis Run references missing Occurrence or Blob")
            if run.status == "VALIDATING":
                _apply_dump_timestamp(occurrence, inspect)
                run.inspect_object_key = inspect_key
                run.analysis_context = freeze_analysis_context(
                    run,
                    occurrence,
                    blob,
                    inspect,
                    inspect_key,
                )
                transition_analysis(run, "INSPECTED")
                operation_log(
                    session,
                    action="analysis.inspect.complete",
                    target_type="analysis_run",
                    target_id=run.id,
                    workspace_id=occurrence.workspace_id,
                    request_id=message.get("request_id"),
                    details={"attempt_id": claim.attempt_id, "generation": claim.generation},
                )
            elif run.analysis_context is None:
                _apply_dump_timestamp(occurrence, inspect)
                run.inspect_object_key = inspect_key
                run.analysis_context = freeze_analysis_context(
                    run,
                    occurrence,
                    blob,
                    inspect,
                    inspect_key,
                )
            if not heartbeat_claim(session, claim, lease_seconds=lease_seconds):
                session.rollback()
                return False
            session.commit()
            return True

    def _begin_symbol_matching(
        self,
        claim: TaskClaim,
        run_id: str,
        lease_seconds: int,
    ) -> bool:
        with self.sessions() as session:
            if not claim_is_current(session, claim, lock=True):
                return False
            run = session.get(AnalysisRun, run_id)
            if run is None:
                return False
            if run.status in {"INSPECTED", "WAITING_FOR_SYMBOLS"}:
                transition_analysis(run, "MATCHING_SYMBOLS")
            if not heartbeat_claim(session, claim, lease_seconds=lease_seconds):
                session.rollback()
                return False
            session.commit()
            return True

    def _mark_analysis_queued(
        self,
        claim: TaskClaim,
        run_id: str,
        lease_seconds: int,
    ) -> bool:
        with self.sessions() as session:
            if not claim_is_current(session, claim, lock=True):
                return False
            run = session.get(AnalysisRun, run_id)
            if run is None:
                return False
            if run.status == "MATCHING_SYMBOLS":
                transition_analysis(run, "SYMBOLS_READY")
            if run.status == "SYMBOLS_READY":
                transition_analysis(run, "QUEUED")
            if not heartbeat_claim(session, claim, lease_seconds=lease_seconds):
                session.rollback()
                return False
            session.commit()
            return True

    def _mark_analysis_running(
        self,
        claim: TaskClaim,
        run_id: str,
        lease_seconds: int,
    ) -> bool:
        with self.sessions() as session:
            if not claim_is_current(session, claim, lock=True):
                return False
            run = session.get(AnalysisRun, run_id)
            if run is None:
                return False
            if run.status == "QUEUED":
                transition_analysis(run, "ANALYZING")
            if run.status not in {"ANALYZING", "NORMALIZING", "GROUPING"}:
                raise RuntimeError(f"analysis cannot execute from durable state {run.status}")
            if not heartbeat_claim(session, claim, lease_seconds=lease_seconds):
                session.rollback()
                return False
            session.commit()
            return True

    def _persist_analysis(
        self,
        message: dict[str, Any],
        output: CoreOutput,
        claim: TaskClaim,
    ) -> bool:
        try:
            with self.sessions() as session:
                run = session.get(AnalysisRun, message["run_id"])
                if run is None:
                    return False
                occurrence = session.get(Occurrence, run.occurrence_id)
                blob = session.get(DumpBlob, occurrence.dump_blob_id) if occurrence else None
                if occurrence is None or blob is None:
                    raise RuntimeError("analysis Run references missing Occurrence or Blob")
                canonical = output.canonical
                analysis_context = run.analysis_context
                if analysis_context is None:
                    raise RuntimeError("analysis Run has no immutable analysis context")
                workspace_id, occurrence_id, run_id = occurrence.workspace_id, occurrence.id, run.id
            try:
                validate_contract(
                    canonical,
                    self.settings.schema_root / "analysis-result-v1.schema.json",
                    "analysis result",
                )
            except ApiError:
                CANONICAL_VALIDATION_FAILURES.labels("schema").inc()
                raise
            try:
                validate_canonical_semantics(canonical, analysis_context)
            except CanonicalSemanticError:
                CANONICAL_VALIDATION_FAILURES.labels("semantic").inc()
                raise
            prefix = analysis_generation_prefix(
                workspace_id,
                occurrence_id,
                run_id,
                claim.attempt_id,
                claim.generation,
            )
            canonical_key = analysis_generation_key(
                workspace_id,
                occurrence_id,
                run_id,
                claim.attempt_id,
                claim.generation,
                "canonical.json",
            )
            put_json(self.store, canonical_key, canonical)
            written_objects: list[tuple[str, int]] = [
                ("canonical", len(canonical_json_bytes(canonical)))
            ]
            for name, path in output.raw.items():
                if name in {
                    "raw/minidump.json",
                    "raw/symbolicator.json",
                    "raw/inspect.json",
                    "raw/match.json",
                    "raw/legacy-canonical.json",
                    "raw/core-final-shadow.json",
                }:
                    self.store.put_file(
                        analysis_generation_key(
                            workspace_id,
                            occurrence_id,
                            run_id,
                            claim.attempt_id,
                            claim.generation,
                            name,
                        ),
                        path,
                        "application/json",
                    )
                    written_objects.append(("raw", path.stat().st_size))

            with self.sessions() as session:
                if not claim_is_current(session, claim, lock=True):
                    _record_generation_orphans(written_objects)
                    return False
                run = session.scalar(
                    select(AnalysisRun).where(AnalysisRun.id == run_id).with_for_update()
                )
                if run is None:
                    _record_generation_orphans(written_objects)
                    return False
                occurrence = session.scalar(
                    select(Occurrence).where(Occurrence.id == run.occurrence_id).with_for_update()
                )
                if occurrence is None:
                    raise RuntimeError("analysis Run references missing Occurrence")
                if run.status == "ANALYZING":
                    transition_analysis(run, "NORMALIZING")
                if run.status == "NORMALIZING":
                    transition_analysis(run, "GROUPING")
                if run.status != "GROUPING":
                    raise RuntimeError(f"analysis cannot finalize from durable state {run.status}")
                run.result_object_key = canonical_key
                run.raw_object_prefix = f"{prefix}/raw/"
                run.quality_score = float(canonical["quality"]["score"])
                resolution = canonical["build_resolution"]
                run.resolved_build_id = resolution.get("resolved_build_id")
                run.resolution_method = resolution["resolution_method"]
                run.resolution_evidence = resolution.get("evidence")
                _upsert_summary(session, run, canonical)
                status = "PARTIAL" if _is_partial(canonical) else "COMPLETE"
                transition_analysis(run, status)
                run.winner_attempt_id = claim.attempt_id
                run.winner_generation = claim.generation
                promotion = promote_current_analysis(session, occurrence, run)
                if promotion.promoted:
                    update_symbol_health_for_promotion(
                        session,
                        mode=self.settings.symbol_projection_mode,
                        occurrence=occurrence,
                        run=run,
                        canonical=canonical,
                    )
                    _update_group_projection(session, occurrence, run, canonical)
                operation_log(
                    session,
                    action="analysis.complete",
                    target_type="analysis_run",
                    target_id=run.id,
                    workspace_id=occurrence.workspace_id,
                    request_id=message.get("request_id"),
                    result=status,
                    details={
                        "quality_score": run.quality_score,
                        "attempt_id": claim.attempt_id,
                        "generation": claim.generation,
                        "current_promotion": promotion.reason,
                        "assembly_mode": run.assembly_mode,
                        "canonical_shadow_mismatch_count": len(output.shadow_differences),
                        "canonical_shadow_mismatch_paths": list(output.shadow_differences[:20]),
                    },
                )
                if not finish_claim(session, claim, "succeeded"):
                    session.rollback()
                    _record_generation_orphans(written_objects)
                    return False
                session.commit()
                CANONICAL_WINNER_FINALIZES.labels(
                    run.assembly_mode,
                    status,
                    promotion.reason,
                ).inc()
                return True
        finally:
            roots = {
                path.parents[1] if path.parent.name == "raw" else path.parent
                for path in output.raw.values()
            }
            for root in roots:
                shutil.rmtree(root, ignore_errors=True)

    def _fail_run(
        self,
        message: dict[str, Any],
        claim: TaskClaim,
        code: str,
        detail: str,
    ) -> bool:
        with self.sessions() as session:
            if not claim_is_current(session, claim, lock=True):
                return False
            run = session.scalar(
                select(AnalysisRun).where(AnalysisRun.id == message["run_id"]).with_for_update()
            )
            if run is None:
                finish_claim(session, claim, "dead")
                session.commit()
                return True
            target = fail_analysis(run, code)
            if target is None:
                finish_claim(session, claim, "succeeded")
                session.commit()
                return True
            run.error_code = code
            run.error_detail = detail[-2000:].replace("\x00", "")
            occurrence = session.get(Occurrence, run.occurrence_id)
            operation_log(
                session,
                action="analysis.fail",
                target_type="analysis_run",
                target_id=run.id,
                workspace_id=occurrence.workspace_id if occurrence else None,
                request_id=message.get("request_id"),
                result=target,
                details={
                    "error_code": code,
                    "attempt_id": claim.attempt_id,
                    "generation": claim.generation,
                },
            )
            if not finish_claim(session, claim, "failed"):
                session.rollback()
                return False
            session.commit()
            return True


def _verify_payload(upload: Upload, digest: str, size: int, prefix: bytes) -> str | None:
    if size != upload.declared_length:
        return "length_mismatch"
    if upload.client_sha256_hint and digest.lower() != upload.client_sha256_hint.lower():
        return "sha256_mismatch"
    if size == 0:
        return "empty_file"
    if upload.file_kind == "dmp" and not prefix.startswith(b"MDMP"):
        return "invalid_minidump_magic"
    if upload.file_kind == "pe":
        if not prefix.startswith(b"MZ") or len(prefix) < 0x40:
            return "invalid_pe_magic"
        offset = int.from_bytes(prefix[0x3C:0x40], "little")
        if offset + 4 > len(prefix) or prefix[offset : offset + 4] != b"PE\x00\x00":
            return "invalid_pe_signature"
    if upload.file_kind == "pdb" and not prefix.startswith(b"Microsoft C/C++ MSF 7.00"):
        return "invalid_pdb_format"
    if upload.file_kind == "source_bundle" and not prefix.startswith(b"PK"):
        return "invalid_zip_format"
    return None


def _artifact_blob_identity_conflict(
    blob: ArtifactBlob | None,
    *,
    kind: str,
    size: int,
    identity: dict[str, Any],
) -> str | None:
    if blob is None:
        return None
    if blob.kind != kind:
        return "kind"
    if blob.size != size:
        return "size"
    if (
        blob.code_id
        and identity.get("code_id")
        and blob.code_id.lower() != str(identity["code_id"]).lower()
    ):
        return "code_id"
    if (
        blob.debug_id
        and identity.get("debug_id")
        and blob.debug_id.lower() != str(identity["debug_id"]).lower()
    ):
        return "debug_id"
    return None


def _content_expectation_rejection(
    session: Session, upload: Upload, digest: str, size: int
) -> str | None:
    if upload.build_id is None or upload.file_kind not in {"pe", "pdb"}:
        return None
    build = session.get(Build, upload.build_id)
    if build is None or build.identity_mode != "content_v1":
        return None
    expectation = session.scalar(
        select(BuildArtifactExpectation).where(
            BuildArtifactExpectation.build_id == build.id,
            BuildArtifactExpectation.kind == upload.file_kind,
            BuildArtifactExpectation.normalized_name == upload.original_filename.casefold(),
        )
    )
    if expectation is None:
        return "unexpected_artifact"
    if expectation.size != size:
        return "expected_size_mismatch"
    if expectation.sha256.lower() != digest.lower():
        return "expected_sha256_mismatch"
    return None


def _find_manifest_module(
    session: Session, build_id: str, kind: str, filename: str
) -> BuildModule | None:
    column = BuildModule.code_file if kind == "pe" else BuildModule.debug_file
    return session.scalar(
        select(BuildModule).where(
            BuildModule.build_id == build_id, func.lower(column) == filename.lower()
        )
    )


def _counterpart(session: Session, artifact: Artifact) -> Artifact | None:
    if artifact.module_id is None or artifact.kind not in {"pe", "pdb"}:
        return None
    other_kind = "pdb" if artifact.kind == "pe" else "pe"
    return session.scalar(
        select(Artifact)
        .where(Artifact.module_id == artifact.module_id, Artifact.kind == other_kind)
        .order_by(Artifact.created_at.desc())
    )


def _debug_ids_match(first: Artifact, second: Artifact) -> bool:
    return bool(
        first.debug_id and second.debug_id and first.debug_id.lower() == second.debug_id.lower()
    )


def _materialize_match_spec(
    store: ObjectStore, task_dir: Path, spec: dict[str, Any]
) -> dict[str, Any]:
    artifact_dir = task_dir / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, dict[str, Any]] = {}
    for artifact in spec.get("artifacts", []):
        if artifact.get("kind") == "source_bundle":
            continue
        module_key = artifact.get("module_id") or artifact["artifact_id"]
        entry = grouped.setdefault(
            module_key,
            {
                "artifact_id": artifact["artifact_id"],
                "code_file": artifact.get("code_file"),
                "debug_file": artifact.get("debug_file"),
                "code_id": artifact.get("code_id"),
                "debug_id": artifact.get("debug_id"),
                "role": artifact.get("role"),
                "in_app": artifact.get("in_app", False),
                "build_id": artifact.get("build_id"),
            },
        )
        path = artifact_dir / artifact["artifact_id"]
        store.download_file(artifact["object_key"], path)
        relative = f"artifacts/{artifact['artifact_id']}"
        if artifact["kind"] == "pe":
            entry["pe_path"] = relative
            entry["code_id"] = artifact.get("code_id") or entry.get("code_id")
        elif artifact["kind"] == "pdb":
            entry["pdb_path"] = relative
            entry["debug_id"] = artifact.get("debug_id") or entry.get("debug_id")
    return {
        "workspace_id": spec["workspace_id"],
        "reported_build_id": spec.get("reported_build_id"),
        "modules": list(grouped.values()),
        "builds": [
            {"build_id": build["build_id"], "modules": build.get("modules", [])}
            for build in spec.get("builds", [])
        ],
    }


def _apply_dump_timestamp(occurrence: Occurrence, inspect: dict[str, Any]) -> None:
    """Apply the trusted Minidump header time unless a manual correction wins."""

    value = inspect.get("dump", {}).get("timestamp")
    if not isinstance(value, str):
        return
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)
    occurrence.dump_timestamp = timestamp
    if occurrence.time_source == "manual":
        return
    occurrence.occurred_at = timestamp
    occurrence.time_source = "dump"


def _attach_source_context_compat(
    store: ObjectStore,
    canonical: dict[str, Any],
    run_spec: dict[str, Any],
    task_dir: Path,
) -> None:
    """Legacy-only source enrichment retained for an explicit rollback window."""

    try:
        attach_source_context(store, canonical, run_spec, task_dir)
    except SourceBundleError as error:
        quality = cast(dict[str, Any], canonical.setdefault("quality", {}))
        warnings = cast(list[dict[str, Any]], quality.setdefault("warnings", []))
        warnings.append(
            {
                "code": "other",
                "message": f"Source context omitted: {error}",
                "module": None,
                "debug_id": None,
            }
        )


def _upsert_summary(session: Session, run: AnalysisRun, canonical: dict[str, Any]) -> None:
    crash = canonical["crash"]
    quality = canonical["quality"]
    crashing_thread = next(
        (thread for thread in canonical["threads"] if thread.get("is_crashing")), None
    )
    frames = (crashing_thread or {}).get("frames", [])[:15]
    top = next((frame for frame in frames if frame.get("in_app")), frames[0] if frames else {})
    build = session.get(Build, run.resolved_build_id) if run.resolved_build_id else None
    summary = session.get(AnalysisSummary, run.id) or AnalysisSummary(
        analysis_run_id=run.id,
        occurrence_id=run.occurrence_id,
        crash_type=crash["type"],
    )
    summary.resolved_build_id = run.resolved_build_id
    summary.version = build.version if build else None
    summary.exception_code = crash.get("exception_code")
    summary.exception_name = crash.get("exception_name")
    summary.access_type = crash.get("access_type")
    summary.crash_address = crash.get("address")
    summary.crashing_thread_id = crash.get("thread_id")
    summary.fault_module = crash.get("fault_module")
    summary.top_function = top.get("function")
    summary.top_source_file = top.get("file")
    summary.top_source_line = top.get("line")
    summary.symbol_coverage = quality.get("symbol_coverage")
    summary.unwind_reliability = quality.get("unwind_reliability")
    summary.artifact_completeness = quality.get("artifact_completeness")
    summary.exact_fingerprint = canonical["fingerprints"].get("exact")
    summary.family_fingerprint = None
    summary.crashing_frames = frames
    summary.crash_type = crash["type"]
    session.add(summary)


def _is_partial(canonical: dict[str, Any]) -> bool:
    if any(
        module.get("in_app") and module.get("status") != "matched"
        for module in canonical.get("modules", [])
    ):
        return True
    return any(
        str(warning.get("code", "")).startswith(BLOCKING_WARNING_PREFIXES)
        or str(warning.get("message", "")).startswith("Source context omitted:")
        for warning in canonical.get("quality", {}).get("warnings", [])
    )


def _record_generation_orphans(objects: list[tuple[str, int]]) -> None:
    for kind, size in objects:
        GENERATION_ORPHAN_OBJECTS.labels(kind).inc()
        GENERATION_ORPHAN_BYTES.labels(kind).inc(size)


def _task_log_context(
    message: dict[str, Any],
    claim: TaskClaim,
    *,
    outcome: str,
    reason: str,
) -> dict[str, Any]:
    target = (
        message.get("run_id")
        or message.get("upload_id")
        or message.get("artifact_id")
        or message.get("workspace_id")
        or "-"
    )
    return {
        "request_id": message.get("request_id") or "-",
        "attempt_id": claim.attempt_id,
        "task_type": claim.task_type,
        "queue": message.get("queue") or "-",
        "logical_target": claim.logical_key,
        "domain_identity": target,
        "claim_generation": claim.generation,
        "outcome": outcome,
        "reason": reason,
    }


def _update_group_projection(
    session: Session, occurrence: Occurrence, run: AnalysisRun, canonical: dict[str, Any]
) -> None:
    exact = canonical["fingerprints"].get("exact")
    current = session.get(GroupMembership, occurrence.id)
    previous_group_id = current.group_id if current else None
    if not exact:
        if current is not None:
            session.delete(current)
            session.add(
                GroupMembershipHistory(
                    occurrence_id=occurrence.id,
                    previous_group_id=previous_group_id,
                    group_id=None,
                    analysis_run_id=run.id,
                    action="unclassify",
                    similarity=1.0,
                    grouping_evidence_json={
                        "decision": "unclassified",
                        "algorithm": "exact-v1.0",
                        "grouping_version": run.grouping_version,
                    },
                )
            )
            session.flush()
            _refresh_group_count(session, previous_group_id)
        return
    group = session.scalar(
        select(CrashGroup).where(
            CrashGroup.workspace_id == occurrence.workspace_id,
            CrashGroup.group_type == "exact",
            CrashGroup.fingerprint == exact,
        )
    )
    summary = session.get(AnalysisSummary, run.id)
    if group is None:
        title = (
            " · ".join(
                part
                for part in [
                    summary.exception_name if summary else None,
                    summary.top_function if summary else None,
                ]
                if part
            )
            or "Exact crash"
        )
        group = CrashGroup(
            id=new_id("grp"),
            workspace_id=occurrence.workspace_id,
            group_type="exact",
            fingerprint=exact,
            representative_run_id=run.id,
            title=title,
            status="open",
            first_seen=occurrence.occurred_at,
            last_seen=occurrence.occurred_at,
            occurrence_count=0,
            first_build_id=run.resolved_build_id,
            last_build_id=run.resolved_build_id,
        )
        session.add(group)
        session.flush()
    else:
        group.last_seen = max(group.last_seen, occurrence.occurred_at)
        group.last_build_id = run.resolved_build_id
    evidence = {
        "decision": "auto_exact",
        "algorithm": "exact-v1.0",
        "grouping_version": run.grouping_version,
    }
    if current is None:
        current = GroupMembership(
            occurrence_id=occurrence.id,
            group_id=group.id,
            analysis_run_id=run.id,
            similarity=1.0,
            grouping_evidence_json=evidence,
        )
        session.add(current)
        action = "assign"
    else:
        action = "move" if current.group_id != group.id else "assign"
        current.group_id = group.id
        current.analysis_run_id = run.id
        current.grouping_evidence_json = evidence
        current.assigned_at = utcnow()
    session.add(
        GroupMembershipHistory(
            occurrence_id=occurrence.id,
            previous_group_id=previous_group_id,
            group_id=group.id,
            analysis_run_id=run.id,
            action=action,
            similarity=1.0,
            grouping_evidence_json=evidence,
        )
    )
    session.flush()
    _refresh_group_count(session, group.id)
    if previous_group_id and previous_group_id != group.id:
        _refresh_group_count(session, previous_group_id)


def _refresh_group_count(session: Session, group_id: str | None) -> None:
    if not group_id:
        return
    count = session.scalar(
        select(func.count())
        .select_from(GroupMembership)
        .where(GroupMembership.group_id == group_id)
    )
    group = session.get(CrashGroup, group_id)
    if group:
        group.occurrence_count = int(count or 0)


def _existing_temp_root(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    return str(path)
