from __future__ import annotations

import json
import logging
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from crashcap_api.config import Settings
from crashcap_api.contracts import validate_contract
from crashcap_api.ids import new_id, new_ulid
from crashcap_api.models import (
    CURRENT_ELIGIBLE_STATUSES,
    AnalysisRun,
    AnalysisSummary,
    Artifact,
    Build,
    BuildModule,
    CrashGroup,
    DumpBlob,
    GroupMembership,
    GroupMembershipHistory,
    MissingSymbol,
    Occurrence,
    Upload,
    Workspace,
    utcnow,
)
from crashcap_api.object_keys import analysis_key, analysis_prefix, dump_blob_key, raw_build_key
from crashcap_api.queueing import TaskDispatcher
from crashcap_api.services.analysis import create_analysis_run
from crashcap_api.services.common import (
    active_missing_occurrences,
    missing_symbol_key,
    operation_log,
    transition_analysis,
    transition_upload,
)
from crashcap_api.storage import ObjectStore, put_json, stream_sha256
from sqlalchemy import func, insert, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from .core_runner import CoreExecutionError, CoreExecutor, CoreOutput
from .source_bundle import SourceBundleError, attach_source_context, inspect_source_bundle
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
        with self.sessions() as session:
            upload = session.get(Upload, message["upload_id"])
            if upload is None:
                LOGGER.warning("verification task references missing upload")
                return
            if upload.verification_status != "VERIFYING":
                return
            try:
                digest, size, prefix = stream_sha256(self.store, upload.object_key)
                rejection = _verify_payload(upload, digest, size, prefix)
                upload.verified_length = size
                upload.verified_sha256 = digest
                if rejection is not None:
                    transition_upload(upload, "REJECTED")
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
                    session.commit()
                    return
                if upload.file_kind == "dmp":
                    run_message = self._accept_dump(session, upload)
                    ingest_message = None
                else:
                    run_message = None
                    ingest_message = self._accept_artifact(session, upload)
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
                session.commit()
            except Exception:
                session.rollback()
                raise
        if ingest_message is not None:
            self.dispatcher.enqueue(ingest_message)
        if run_message is not None:
            self.dispatcher.enqueue(run_message)

    def _accept_dump(self, session: Session, upload: Upload) -> dict[str, Any] | None:
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
            blob_id = new_id("blob")
            final_key = dump_blob_key(upload.workspace_id, blob_id)
            self.store.copy(upload.object_key, final_key)
            blob = DumpBlob(
                id=blob_id,
                workspace_id=upload.workspace_id,
                sha256=upload.verified_sha256,
                size=upload.verified_length or upload.declared_length,
                object_key=final_key,
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
        )
        return creation.message

    def _accept_artifact(self, session: Session, upload: Upload) -> dict[str, Any] | None:
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
            return None
        artifact_id = new_id("art")
        final_key = raw_build_key(upload.workspace_id, upload.build_id, upload.verified_sha256)
        self.store.copy(upload.object_key, final_key)
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
            object_key=final_key,
            verification_status="pending",
        )
        session.add(artifact)
        session.flush()
        return {
            "schema_version": "1.0",
            "task_type": "ingest_artifact",
            "artifact_id": artifact.id,
            "attempt_id": f"att_{new_ulid()}",
            "queue": "ingest",
        }

    def ingest_artifact(self, message: dict[str, Any]) -> None:
        with self.sessions() as session:
            # A delivery may be retried or arrive concurrently. Lock the
            # durable artifact row before testing `pending`; only one worker
            # may publish and increment the Workspace inventory version.
            artifact = session.scalar(
                select(Artifact).where(Artifact.id == message["artifact_id"]).with_for_update()
            )
            if artifact is None or artifact.verification_status != "pending":
                return
            build = session.get(Build, artifact.build_id)
            module = session.get(BuildModule, artifact.module_id) if artifact.module_id else None
            if build is None:
                raise RuntimeError("artifact Build disappeared")
            with tempfile.TemporaryDirectory(
                prefix=f"ingest-{artifact.id}-",
                dir=_existing_temp_root(self.settings.task_tmp_root),
            ) as raw_temp:
                local_path = Path(raw_temp) / artifact.logical_name
                self.store.download_file(artifact.object_key, local_path)
                if artifact.kind == "source_bundle":
                    try:
                        artifact.ingest_metadata = inspect_source_bundle(local_path)
                    except SourceBundleError as error:
                        artifact.verification_status = "rejected_format"
                        operation_log(
                            session,
                            action="source_bundle.ingest",
                            target_type="artifact",
                            target_id=artifact.id,
                            workspace_id=build.workspace_id,
                            request_id=message.get("request_id"),
                            result="rejected_format",
                            details={"reason": str(error)},
                        )
                        session.commit()
                        return
                    artifact.verification_status = "verified"
                    session.execute(
                        update(Workspace)
                        .where(Workspace.id == build.workspace_id)
                        .values(symbol_inventory_version=Workspace.symbol_inventory_version + 1)
                    )
                    operation_log(
                        session,
                        action="source_bundle.ingest",
                        target_type="artifact",
                        target_id=artifact.id,
                        workspace_id=build.workspace_id,
                        request_id=message.get("request_id"),
                        result="verified",
                        details={
                            "source_entry_count": artifact.ingest_metadata["source_entry_count"],
                            "policy_version": artifact.ingest_metadata["policy_version"],
                        },
                    )
                    session.commit()
                    return
                try:
                    identity = self.core.identify_artifact(local_path, artifact.kind)
                except CoreExecutionError as error:
                    artifact.verification_status = "corrupted"
                    operation_log(
                        session,
                        action="artifact.ingest",
                        target_type="artifact",
                        target_id=artifact.id,
                        workspace_id=build.workspace_id,
                        request_id=message.get("request_id"),
                        result="rejected",
                        details={"reason": error.code},
                    )
                    session.commit()
                    return
                if identity["sha256"].lower() != artifact.sha256.lower():
                    artifact.verification_status = "corrupted"
                    session.commit()
                    return
                if artifact.kind == "pdb" and identity.get("is_fastlink"):
                    artifact.verification_status = "rejected_fastlink"
                    session.commit()
                    return
                artifact.code_id = identity.get("code_id")
                artifact.debug_id = identity.get("debug_id")
                artifact.verification_status = "verified"
                if module is not None:
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
                session.flush()
                counterpart = _counterpart(session, artifact)
                pair_verified = (
                    counterpart is not None
                    and artifact.verification_status == "verified"
                    and counterpart.verification_status == "verified"
                )
                if pair_verified:
                    assert counterpart is not None
                    if not _debug_ids_match(artifact, counterpart):
                        artifact.verification_status = f"{artifact.kind}_mismatch"
                if pair_verified and artifact.verification_status == "verified":
                    assert counterpart is not None
                    assert artifact.debug_id is not None
                    pe = artifact if artifact.kind == "pe" else counterpart
                    pdb = artifact if artifact.kind == "pdb" else counterpart
                    pe_path = Path(raw_temp) / pe.logical_name
                    pdb_path = Path(raw_temp) / pdb.logical_name
                    if pe.id != artifact.id:
                        self.store.download_file(pe.object_key, pe_path)
                    if pdb.id != artifact.id:
                        self.store.download_file(pdb.object_key, pdb_path)
                    self.symbols.publish_pair(
                        build.workspace_id,
                        pe_path,
                        pdb_path,
                        artifact.debug_id,
                    )
                if artifact.verification_status == "verified":
                    session.execute(
                        update(Workspace)
                        .where(Workspace.id == build.workspace_id)
                        .values(symbol_inventory_version=Workspace.symbol_inventory_version + 1)
                    )
                operation_log(
                    session,
                    action="artifact.ingest",
                    target_type="artifact",
                    target_id=artifact.id,
                    workspace_id=build.workspace_id,
                    request_id=message.get("request_id"),
                    result=artifact.verification_status,
                    details={"kind": artifact.kind},
                )
                session.commit()

    def reindex_symbols(self, message: dict[str, Any]) -> None:
        with self.sessions() as session:
            workspace_id = message["workspace_id"]
            build_filter = message.get("build_id")
            query = (
                select(BuildModule, Build)
                .join(Build, Build.id == BuildModule.build_id)
                .where(Build.workspace_id == workspace_id)
            )
            if build_filter:
                query = query.where(Build.id == build_filter)
            rows = session.execute(query).all()
            with tempfile.TemporaryDirectory(
                prefix="reindex-", dir=_existing_temp_root(self.settings.task_tmp_root)
            ) as raw_temp:
                root = Path(raw_temp)
                for module, _build in rows:
                    pair = session.scalars(
                        select(Artifact).where(
                            Artifact.module_id == module.id,
                            Artifact.verification_status == "verified",
                            Artifact.kind.in_(["pe", "pdb"]),
                        )
                    ).all()
                    pe = next((item for item in pair if item.kind == "pe"), None)
                    pdb = next((item for item in pair if item.kind == "pdb"), None)
                    if pe is None or pdb is None or not _debug_ids_match(pe, pdb):
                        continue
                    pe_path, pdb_path = root / pe.id, root / pdb.id
                    self.store.download_file(pe.object_key, pe_path)
                    self.store.download_file(pdb.object_key, pdb_path)
                    assert pe.debug_id is not None
                    self.symbols.publish_pair(workspace_id, pe_path, pdb_path, pe.debug_id)
            operation_log(
                session,
                action="symbols.reindex",
                target_type="workspace",
                target_id=workspace_id,
                workspace_id=workspace_id,
                request_id=message.get("request_id"),
            )
            session.commit()

    def analyze_occurrence(self, message: dict[str, Any]) -> None:
        with self.sessions() as session:
            run = session.get(AnalysisRun, message["run_id"])
            if run is None or run.status in CURRENT_ELIGIBLE_STATUSES | {
                "FAILED",
                "REJECTED",
                "CANCELLED",
                "TIMEOUT",
                "OOM",
            }:
                return
            if run.status == "UPLOADED":
                transition_analysis(run, "VALIDATING")
            run.started_at = utcnow()
            session.commit()
            spec = dict(run.run_spec)

        try:
            output = self._execute_analysis(spec)
            self._persist_analysis(message, output)
        except CoreExecutionError as error:
            self._fail_run(message, error.code, str(error))
        except Exception as error:
            self._fail_run(message, "PLATFORM_WORKER_FAILED", str(error))
            raise

    def _execute_analysis(self, spec: dict[str, Any]) -> CoreOutput:
        self.settings.task_tmp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix=f"{spec['run_id']}-", dir=self.settings.task_tmp_root
        ) as raw_temp:
            task_dir = Path(raw_temp)
            self.store.download_file(spec["blob"]["object_key"], task_dir / "dump.dmp")
            match = _materialize_match_spec(self.store, task_dir, spec)
            (task_dir / "match.json").write_text(
                json.dumps(match, indent=2, sort_keys=True), encoding="utf-8"
            )
            output = self.core.analyze(task_dir, spec)
            attach_source_context(self.store, output.canonical, spec, task_dir)
            detached = Path(tempfile.mkdtemp(prefix=f"{spec['run_id']}-result-"))
            paths: dict[str, Path] = {}
            for name, source in output.raw.items():
                destination = detached / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                paths[name] = destination
            return CoreOutput(
                inspect=output.inspect,
                canonical=output.canonical,
                raw=paths,
            )

    def _persist_analysis(self, message: dict[str, Any], output: CoreOutput) -> None:
        try:
            with self.sessions() as session:
                run = session.get(AnalysisRun, message["run_id"])
                if run is None:
                    return
                occurrence = session.get(Occurrence, run.occurrence_id)
                blob = session.get(DumpBlob, occurrence.dump_blob_id) if occurrence else None
                if occurrence is None or blob is None:
                    raise RuntimeError("analysis Run references missing Occurrence or Blob")
                _advance_to_analyzing(run)
                _apply_dump_timestamp(occurrence, output.inspect)
                canonical = _bind_platform_identity(output.canonical, run, occurrence, blob)
                transition_analysis(run, "NORMALIZING")
                validate_contract(
                    canonical,
                    self.settings.schema_root / "analysis-result-v1.schema.json",
                    "analysis result",
                )
                transition_analysis(run, "GROUPING")
                prefix = analysis_prefix(occurrence.workspace_id, occurrence.id, run.id)
                canonical_key = analysis_key(
                    occurrence.workspace_id, occurrence.id, run.id, "canonical.json"
                )
                put_json(self.store, canonical_key, canonical)
                for name, path in output.raw.items():
                    if name in {
                        "raw/minidump.json",
                        "raw/symbolicator.json",
                        "raw/inspect.json",
                        "raw/match.json",
                    }:
                        self.store.put_file(
                            analysis_key(occurrence.workspace_id, occurrence.id, run.id, name),
                            path,
                            "application/json",
                        )
                run.result_object_key = canonical_key
                run.raw_object_prefix = f"{prefix}/raw/"
                run.quality_score = float(canonical["quality"]["score"])
                resolution = canonical["build_resolution"]
                run.resolved_build_id = resolution.get("resolved_build_id")
                run.resolution_method = resolution["resolution_method"]
                run.resolution_evidence = resolution.get("evidence")
                _upsert_summary(session, run, canonical)
                _update_missing_symbols(session, occurrence.workspace_id, occurrence.id, canonical)
                status = "PARTIAL" if _is_partial(canonical) else "COMPLETE"
                transition_analysis(run, status)
                run.finished_at = utcnow()
                occurrence.current_run_id = run.id
                _update_group_projection(session, occurrence, run, canonical)
                operation_log(
                    session,
                    action="analysis.complete",
                    target_type="analysis_run",
                    target_id=run.id,
                    workspace_id=occurrence.workspace_id,
                    request_id=message.get("request_id"),
                    result=status,
                    details={"quality_score": run.quality_score},
                )
                session.commit()
        finally:
            roots = {
                path.parents[1] if path.parent.name == "raw" else path.parent
                for path in output.raw.values()
            }
            for root in roots:
                shutil.rmtree(root, ignore_errors=True)

    def _fail_run(self, message: dict[str, Any], code: str, detail: str) -> None:
        with self.sessions() as session:
            run = session.get(AnalysisRun, message["run_id"])
            if run is None:
                return
            target = (
                "TIMEOUT"
                if code == "TIMEOUT"
                else "OOM"
                if code == "OOM"
                else "REJECTED"
                if code in {"UNSUPPORTED_DUMP", "CORRUPT_DUMP"}
                else "FAILED"
            )
            if target in _allowed_targets(run.status):
                transition_analysis(run, target)
            else:
                run.status = target
            run.finished_at = utcnow()
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
                details={"error_code": code},
            )
            session.commit()


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


def _advance_to_analyzing(run: AnalysisRun) -> None:
    for state in ["INSPECTED", "MATCHING_SYMBOLS", "SYMBOLS_READY", "QUEUED", "ANALYZING"]:
        if state in _allowed_targets(run.status):
            transition_analysis(run, state)


def _allowed_targets(status: str) -> set[str]:
    from crashcap_api.services.common import ANALYSIS_TRANSITIONS

    return ANALYSIS_TRANSITIONS.get(status, set())


def _bind_platform_identity(
    canonical: dict[str, Any], run: AnalysisRun, occurrence: Occurrence, blob: DumpBlob
) -> dict[str, Any]:
    result = cast(dict[str, Any], json.loads(json.dumps(canonical)))
    result["schema_version"] = "1.0"
    result["workspace_id"] = occurrence.workspace_id
    result["occurrence_id"] = occurrence.id
    result["analysis_id"] = run.id
    result["dump"].update(
        {
            "blob_id": blob.id,
            "sha256": blob.sha256,
            "size": blob.size,
            "dump_timestamp": occurrence.dump_timestamp.isoformat()
            if occurrence.dump_timestamp
            else None,
            "reported_at": occurrence.reported_at.isoformat() if occurrence.reported_at else None,
            "uploaded_at": occurrence.uploaded_at.isoformat(),
            "occurred_at": occurrence.occurred_at.isoformat(),
            "time_source": occurrence.time_source,
        }
    )
    result["engine"].update(
        {
            "core_image_digest": run.core_image_digest,
            "symbolicator_version": run.symbolicator_version,
            "grouping_version": run.grouping_version,
            "normalization_version": run.normalization_version,
        }
    )
    return result


def _apply_dump_timestamp(occurrence: Occurrence, inspect: dict[str, Any]) -> None:
    """Apply the trusted Minidump header time unless a manual correction wins."""

    if occurrence.time_source == "manual":
        return
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
    occurrence.occurred_at = timestamp
    occurrence.time_source = "dump"


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
        for warning in canonical.get("quality", {}).get("warnings", [])
    )


def _update_missing_symbols(
    session: Session, workspace_id: str, occurrence_id: str, canonical: dict[str, Any]
) -> None:
    missing_statuses = {"missing_pe", "missing_pdb", "pdb_mismatch", "pe_mismatch"}
    current = {
        missing_symbol_key(module): module
        for module in canonical.get("modules", [])
        if module.get("status") in missing_statuses
    }
    rows = session.execute(
        select(MissingSymbol.__table__).where(MissingSymbol.workspace_id == workspace_id)
    ).mappings()
    row_by_key = {
        missing_symbol_key(
            {
                "code_id": row["code_id"],
                "debug_id": row["debug_id"],
            }
        ): dict(row)
        for row in rows
    }
    activity = active_missing_occurrences(session, workspace_id)
    previous = {key for key, occurrences in activity.items() if occurrence_id in occurrences}

    for key, module in current.items():
        row = row_by_key.get(key)
        if row is None:
            row = {
                "workspace_id": workspace_id,
                "code_file": module.get("code_file"),
                "code_id": module.get("code_id"),
                "debug_file": module.get("debug_file"),
                "debug_id": module.get("debug_id"),
                "first_seen": utcnow(),
                "last_seen": utcnow(),
                "affected_occurrence_count": 0,
                "status": "open",
            }
            session.execute(
                insert(MissingSymbol),
                [row],
            )
            row_by_key[key] = row
        row["last_seen"] = utcnow()
        row["code_file"] = module.get("code_file")
        row["debug_file"] = module.get("debug_file")
        occurrences = activity.setdefault(key, set())
        if occurrence_id not in occurrences:
            occurrences.add(occurrence_id)
            operation_log(
                session,
                action="missing_symbol.observe",
                target_type="missing_symbol",
                target_id=key,
                workspace_id=workspace_id,
                details={"occurrence_id": occurrence_id, "reason": module.get("status")},
            )

    for key in previous - set(current):
        activity.setdefault(key, set()).discard(occurrence_id)
        operation_log(
            session,
            action="missing_symbol.clear",
            target_type="missing_symbol",
            target_id=key,
            workspace_id=workspace_id,
            details={"occurrence_id": occurrence_id},
        )

    for key, row in row_by_key.items():
        count = len(activity.get(key, set()))
        values: dict[str, Any] = {
            "affected_occurrence_count": count,
            "status": "open" if count else "resolved",
        }
        if key in current:
            values.update(
                last_seen=row["last_seen"],
                code_file=row["code_file"],
                debug_file=row["debug_file"],
            )
        session.execute(
            update(MissingSymbol)
            .where(
                MissingSymbol.workspace_id == workspace_id,
                MissingSymbol.debug_id.is_not_distinct_from(row["debug_id"]),
                MissingSymbol.code_id.is_not_distinct_from(row["code_id"]),
            )
            .values(**values)
        )


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
