from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from crashcap_api.config import Settings
from crashcap_api.contracts import validate_contract
from crashcap_api.errors import ApiError
from crashcap_api.evidence_comparison import AnalysisEvidence
from crashcap_api.frozen_inputs import canonical_bytes
from crashcap_api.ids import new_id
from crashcap_api.metrics import (
    GENERATION_ORPHAN_BYTES,
    GENERATION_ORPHAN_OBJECTS,
)
from crashcap_api.models import (
    AnalysisDemand,
    AnalysisRun,
    AnalysisSummary,
    CurrentDecision,
    DumpBlob,
    Occurrence,
    Upload,
    Workspace,
    utcnow,
)
from crashcap_api.object_keys import (
    analysis_generation_prefix,
)
from crashcap_api.queueing import TaskDispatcher
from crashcap_api.services.analysis_demands import (
    ensure_demand,
    fanout_workspace_role_next,
    settle_demand_after_comparison,
    settle_demand_after_execution_failure,
)
from crashcap_api.services.analysis_lifecycle import (
    fail_analysis,
    transition_analysis,
)
from crashcap_api.services.analysis_scheduler import release_execution_slot_for_run
from crashcap_api.services.catalog_materials import materialize_catalog_file, select_material
from crashcap_api.services.common import operation_log, transition_upload
from crashcap_api.services.current_decisions import (
    MAX_EVIDENCE_JSON_BYTES,
    build_native_evidence,
    parse_evidence_json,
    promote_current_by_evidence,
)
from crashcap_api.services.current_projection import update_group_projection
from crashcap_api.services.symbol_projection import update_symbol_health_for_promotion
from crashcap_api.storage import ObjectNotFoundError, ObjectStore, stream_sha256
from crashcap_api.task_handoff import (
    TaskClaim,
    claim_is_current,
    claim_task,
    finish_claim,
    heartbeat_claim,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from .core_runner import CoreExecutionError, CoreExecutor
from .frozen_core import FrozenAssignment, FrozenCoreExecutor

LOGGER = logging.getLogger(__name__)
BLOCKING_WARNING_PREFIXES = (
    "missing_",
    "pdb_mismatch",
    "pe_mismatch",
    "symbolicator_",
    "system_symbol_failed",
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
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.store = store
        self.dispatcher = dispatcher
        self.core = core or CoreExecutor(settings)

    def dispatch_workspace_role(self, message: dict[str, Any]) -> None:
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
                session.commit()
            if not claim.acquired:
                return
            for _ in range(1000):
                with self.sessions.begin() as session:
                    page = fanout_workspace_role_next(
                        session, str(message["workspace_id"]), now=utcnow()
                    )
                if page.caught_up:
                    with self.sessions() as session:
                        if claim_is_current(session, claim, lock=True):
                            finish_claim(session, claim, "succeeded")
                            session.commit()
                        else:
                            session.rollback()
                    return
            raise RuntimeError("Workspace role fanout exceeded 200000 occurrences")
        except Exception:
            if claim is not None and claim.acquired:
                self._finish_non_analysis_claim(claim, "failed")
            raise

    def analyze_frozen_run(self, message: dict[str, Any]) -> None:
        """Execute only the immutable 1.1 Run named by a strict durable receipt."""
        if not self.settings.frozen_analysis_enabled:
            raise ApiError(
                "FROZEN_ANALYSIS_DISABLED",
                "Frozen analysis is disabled",
                status_code=503,
            )
        claim: TaskClaim | None = None
        task_dir: Path | None = None
        written: list[tuple[str, int]] = []
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
                run = session.scalar(
                    select(AnalysisRun).where(AnalysisRun.id == message["run_id"]).with_for_update()
                )
                if run is None:
                    finish_claim(session, claim, "dead")
                    session.commit()
                    return
                if run.schema_version != "2.0" or run.assembly_mode != "core-final":
                    raise ApiError(
                        "FROZEN_RUN_REQUIRED",
                        "Task does not reference a frozen Run",
                        status_code=409,
                    )
                if run.status in {"FAILED", "TIMEOUT"}:
                    # Recovery can settle a published Run before its first
                    # delivery reaches a Worker. Consume that late receipt
                    # without reopening the Run or spending its Demand budget.
                    finish_claim(session, claim, "dead")
                    session.commit()
                    return
                occurrence = session.get(Occurrence, run.occurrence_id)
                blob = session.get(DumpBlob, occurrence.dump_blob_id) if occurrence else None
                if occurrence is None or blob is None:
                    raise RuntimeError("frozen Run references missing Occurrence or Blob")
                if run.status == "QUEUED":
                    transition_analysis(run, "ANALYZING")
                elif run.status != "ANALYZING":
                    raise RuntimeError(f"frozen analysis cannot execute from {run.status}")
                if (
                    run.demand_id is not None
                    and run.demand_generation is not None
                    and run.retry_attempt is not None
                ):
                    demand = session.scalar(
                        select(AnalysisDemand)
                        .where(AnalysisDemand.id == run.demand_id)
                        .with_for_update()
                    )
                    if (
                        demand is not None
                        and demand.generation == run.demand_generation
                        and demand.retry_attempt == run.retry_attempt
                    ):
                        demand.state = "running"
                        demand.reason = "analysis_running"
                        demand.not_before = None
                        demand.updated_at = utcnow()
                spec = dict(run.run_spec)
                workspace_id, occurrence_id = occurrence.workspace_id, occurrence.id
                session.commit()

            self.settings.task_tmp_root.mkdir(parents=True, exist_ok=True)
            task_dir = Path(
                tempfile.mkdtemp(
                    prefix=f"{message['run_id']}-{claim.generation}-",
                    dir=self.settings.task_tmp_root,
                )
            )
            run_bytes = canonical_bytes(spec)
            (task_dir / "run.json").write_bytes(run_bytes)
            self.store.download_file(spec["dump"]["object_key"], task_dir / "dump.dmp")
            self.store.download_file(spec["inspect"]["object_key"], task_dir / "inspect.json")
            self.store.download_file(
                spec["resolution_manifest"]["object_key"],
                task_dir / "resolution-manifest.json",
            )
            manifest_bytes = (task_dir / "resolution-manifest.json").read_bytes()
            if hashlib.sha256(manifest_bytes).hexdigest() != spec["resolution_manifest"]["sha256"]:
                raise CoreExecutionError(
                    "INVALID_FROZEN_EVIDENCE", "manifest object digest mismatch"
                )
            manifest = json.loads(manifest_bytes)
            selected: dict[str, str] = {}
            for module in manifest["modules"]:
                pair_id = module["selected_pair_id"]
                if pair_id is None:
                    continue
                debug_id = module["identity"]["debug_id"]
                if not isinstance(debug_id, str) or (
                    pair_id in selected and selected[pair_id] != debug_id
                ):
                    raise CoreExecutionError(
                        "INVALID_FROZEN_EVIDENCE", "selected pair identity is inconsistent"
                    )
                selected[pair_id] = debug_id
            with self.sessions() as session:
                materials = {
                    pair_id: (
                        select_material(
                            session,
                            pair_id,
                            debug_id,
                            "pe",
                            max_locations=self.settings.catalog_source_max_locations,
                            workspace_id=workspace_id,
                        ),
                        select_material(
                            session,
                            pair_id,
                            debug_id,
                            "pdb",
                            max_locations=self.settings.catalog_source_max_locations,
                            workspace_id=workspace_id,
                        ),
                    )
                    for pair_id, debug_id in selected.items()
                }
            pair_paths: dict[str, tuple[Path, Path]] = {}
            for index, (pair_id, (pe, pdb)) in enumerate(sorted(materials.items())):
                root = task_dir / "pairs" / str(index)
                root.mkdir(parents=True)
                pe_path, pdb_path = root / "module.pe", root / "module.pdb"
                materialize_catalog_file(self.store, pe, pe_path)
                materialize_catalog_file(self.store, pdb, pdb_path)
                pair_paths[pair_id] = (pe_path, pdb_path)
            if not self._heartbeat_frozen_claim(claim):
                return
            prefix = analysis_generation_prefix(
                workspace_id,
                occurrence_id,
                message["run_id"],
                claim.attempt_id,
                claim.generation,
            )
            output = FrozenCoreExecutor(self.settings).execute(
                task_dir,
                FrozenAssignment(
                    message["run_id"],
                    occurrence_id,
                    workspace_id,
                    hashlib.sha256(run_bytes).hexdigest(),
                ),
                pair_paths,
                raw_object_prefix=prefix,
            )
            canonical_key = f"{prefix}/canonical.json"
            self.store.put_bytes(canonical_key, output.canonical_bytes, "application/json")
            written.append(("canonical", len(output.canonical_bytes)))
            for key, path in output.raw.items():
                self.store.put_file(key, path, "application/json")
                written.append(("raw", path.stat().st_size))
            canonical = output.canonical
            status = "PARTIAL" if _is_partial(canonical) else "COMPLETE"
            candidate_evidence = None
            candidate_run_for_evidence: AnalysisRun | None = None
            if self.settings.evidence_promotion_enabled:
                with self.sessions() as session:
                    candidate_run_for_evidence = session.get(AnalysisRun, message["run_id"])
                    if candidate_run_for_evidence is None:
                        raise RuntimeError("frozen Run disappeared before evidence projection")
                    session.expunge(candidate_run_for_evidence)
                candidate_evidence = build_native_evidence(
                    candidate_run_for_evidence,
                    canonical,
                    output.canonical_bytes,
                    parse_evidence_json(
                        (task_dir / "inspect.json").read_bytes(),
                        "candidate inspect",
                    ),
                    schema_root=self.settings.schema_root,
                    status=status,
                )
            for _comparison_attempt in range(8):
                try:
                    current_evidence = (
                        self._prepare_current_evidence(occurrence_id)
                        if self.settings.evidence_promotion_enabled
                        else None
                    )
                except ObjectNotFoundError as error:
                    raise CoreExecutionError(
                        "CURRENT_EVIDENCE_UNAVAILABLE",
                        "Current evidence object is missing; preserve Current and retry",
                    ) from error
                with self.sessions() as session:
                    if not claim_is_current(session, claim, lock=True):
                        _record_generation_orphans(written)
                        return
                    run = session.scalar(
                        select(AnalysisRun)
                        .where(AnalysisRun.id == message["run_id"])
                        .with_for_update()
                    )
                    if run is None or run.status != "ANALYZING":
                        _record_generation_orphans(written)
                        return
                    occurrence = session.scalar(
                        select(Occurrence)
                        .where(Occurrence.id == run.occurrence_id)
                        .with_for_update()
                    )
                    if occurrence is None:
                        raise RuntimeError("frozen Run Occurrence disappeared")
                    observed_current = current_evidence.run_id if current_evidence else None
                    if (
                        self.settings.evidence_promotion_enabled
                        and occurrence.current_run_id != observed_current
                    ):
                        session.rollback()
                        continue
                    transition_analysis(run, "NORMALIZING")
                    transition_analysis(run, "GROUPING")
                    run.result_object_key = canonical_key
                    run.raw_object_prefix = f"{prefix}/raw/"
                    run.quality_score = float(canonical["quality"]["score"])
                    _upsert_summary(session, run, canonical)
                    transition_analysis(run, status)
                    run.winner_attempt_id = claim.attempt_id
                    run.winner_generation = claim.generation
                    promotion_reason = "evidence_v1_disabled"
                    promoted = False
                    if candidate_evidence is not None:
                        # The promotion entry refreshes locked rows. Preserve this
                        # transaction's terminal Run and winner before that read;
                        # flush is not commit and projection/fencing failure still
                        # rolls every write back together.
                        session.flush()
                        promotion = promote_current_by_evidence(
                            session,
                            occurrence,
                            run,
                            candidate_evidence,
                            current_evidence,
                            execution_attempt_id=claim.attempt_id,
                            execution_generation=claim.generation,
                            schema_root=self.settings.schema_root,
                        )
                        promotion_reason = promotion.decision.reason
                        promoted = promotion.promoted
                        if promoted:
                            update_symbol_health_for_promotion(
                                session,
                                mode=self.settings.symbol_projection_mode,
                                occurrence=occurrence,
                                run=run,
                                canonical=canonical,
                            )
                            _update_group_projection(session, occurrence, run, canonical)
                    demand_state: str | None = None
                    retry_attempt: int | None = None
                    if run.demand_id is not None and run.demand_generation is not None:
                        demand = session.scalar(
                            select(AnalysisDemand)
                            .where(AnalysisDemand.id == run.demand_id)
                            .with_for_update()
                        )
                        if (
                            demand is not None
                            and demand.generation == run.demand_generation
                            and demand.retry_attempt == run.retry_attempt
                        ):
                            if candidate_evidence is None:
                                demand.state = "needs_review"
                                demand.reason = promotion_reason
                                demand.not_before = None
                                demand.updated_at = utcnow()
                            else:
                                blob = session.get(DumpBlob, occurrence.dump_blob_id)
                                if blob is None:
                                    raise RuntimeError("frozen Run Dump Blob disappeared")
                                settlement = settle_demand_after_comparison(
                                    demand,
                                    blob,
                                    promotion.decision,
                                    promoted=promoted,
                                    settings=self.settings,
                                    now=utcnow(),
                                )
                                retry_attempt = settlement.retry_attempt
                            demand_state = demand.state
                    operation_log(
                        session,
                        action="analysis.frozen.complete",
                        target_type="analysis_run",
                        target_id=run.id,
                        workspace_id=occurrence.workspace_id,
                        request_id=message.get("request_id"),
                        result=status,
                        details={
                            "attempt_id": claim.attempt_id,
                            "generation": claim.generation,
                            "current_promotion": promotion_reason,
                            "demand_state": demand_state,
                            "retry_attempt": retry_attempt,
                        },
                    )
                    release_execution_slot_for_run(session, run.id)
                    if not finish_claim(session, claim, "succeeded"):
                        session.rollback()
                        _record_generation_orphans(written)
                        return
                    session.commit()
                    return
            raise RuntimeError("Current changed during eight consecutive evidence comparisons")
        except Exception as error:
            if claim is not None and claim.acquired:
                code = (
                    error.code
                    if isinstance(error, CoreExecutionError)
                    else "FROZEN_ANALYSIS_FAILED"
                )
                self._fail_run(message, claim, code, str(error))
            raise
        finally:
            if task_dir is not None:
                shutil.rmtree(task_dir, ignore_errors=True)

    def _heartbeat_frozen_claim(self, claim: TaskClaim) -> bool:
        with self.sessions() as session:
            current = heartbeat_claim(
                session, claim, lease_seconds=self.settings.task_lease_seconds
            )
            session.commit() if current else session.rollback()
            return current

    def _prepare_current_evidence(self, occurrence_id: str) -> AnalysisEvidence | None:
        """Read and validate the observed Current outside the finalization transaction."""

        with self.sessions() as session:
            occurrence = session.get(Occurrence, occurrence_id)
            if occurrence is None or occurrence.current_run_id is None:
                return None
            run = session.get(AnalysisRun, occurrence.current_run_id)
            if run is None or run.result_object_key is None:
                raise RuntimeError("Current references a Run without a persisted result")
            prior_decision = session.get(CurrentDecision, run.id)
            expected_canonical_sha256 = (
                prior_decision.candidate_evidence.get("canonical_sha256")
                if prior_decision is not None
                else None
            )
            session.expunge(run)
        canonical_payload = self._read_evidence_object(run.result_object_key)
        if (
            run.schema_version != "2.0"
            or run.assembly_mode != "core-final"
            or expected_canonical_sha256 is None
        ):
            raise CoreExecutionError(
                "CURRENT_EVIDENCE_INVALID", "Current has no complete decision binding"
            )
        if (
            not isinstance(expected_canonical_sha256, str)
            or hashlib.sha256(canonical_payload).hexdigest() != expected_canonical_sha256
        ):
            raise CoreExecutionError(
                "CURRENT_EVIDENCE_INVALID",
                "Current Canonical object digest differs from its decision evidence",
            )
        canonical = parse_evidence_json(canonical_payload, "Current Canonical")
        validate_contract(
            canonical,
            self.settings.schema_root / "analysis-result-v2.0.schema.json",
            "Current analysis result",
        )
        inspect_spec = run.run_spec.get("inspect", {})
        inspect_key = inspect_spec.get("object_key")
        inspect_sha256 = inspect_spec.get("sha256")
        if not isinstance(inspect_key, str) or not isinstance(inspect_sha256, str):
            raise CoreExecutionError(
                "CURRENT_EVIDENCE_INVALID", "Current frozen Run has no inspect object binding"
            )
        inspect_payload = self._read_evidence_object(inspect_key)
        if hashlib.sha256(inspect_payload).hexdigest() != inspect_sha256:
            raise CoreExecutionError(
                "CURRENT_EVIDENCE_INVALID", "Current inspect object digest mismatch"
            )
        return build_native_evidence(
            run,
            canonical,
            canonical_payload,
            parse_evidence_json(inspect_payload, "Current inspect"),
            schema_root=self.settings.schema_root,
        )

    def _read_evidence_object(self, key: str) -> bytes:
        head = self.store.head(key)
        if head.size > MAX_EVIDENCE_JSON_BYTES:
            raise RuntimeError("evidence object exceeds the JSON size limit")
        payload = bytearray()
        for chunk in self.store.stream(key):
            payload.extend(chunk)
            if len(payload) > MAX_EVIDENCE_JSON_BYTES:
                raise RuntimeError("evidence object grew beyond the JSON size limit")
        if len(payload) != head.size:
            raise RuntimeError("evidence object size changed while reading")
        return bytes(payload)

    def verify_upload(self, message: dict[str, Any]) -> None:
        from crashcap_api.services.artifact_catalog import accept_file
        from crashcap_api.services.symbol_catalog import lock_catalog

        from .file_ingest import prepare_file
        from .leases import renewable_lease

        claim: TaskClaim | None = None
        try:
            with self.sessions.begin() as session:
                claim = claim_task(
                    session,
                    message,
                    self.settings.schema_root,
                    receipt_mode=self.settings.task_receipt_mode,
                    lease_seconds=self.settings.task_lease_seconds,
                )
                if not claim.acquired:
                    return
                upload = session.get(Upload, message["upload_id"])
                if upload is None or upload.verification_status != "VERIFYING":
                    finish_claim(session, claim, "succeeded" if upload else "dead")
                    return
                session.expunge(upload)
            self.settings.task_tmp_root.mkdir(parents=True, exist_ok=True)
            with (
                renewable_lease(self.sessions, self.settings, claim),
                tempfile.TemporaryDirectory(
                    prefix="file-verify-", dir=self.settings.task_tmp_root
                ) as temporary,
            ):
                directory = Path(temporary)
                sha, size, prefix = stream_sha256(self.store, upload.object_key)
                rejection = _verify_wire_payload(upload, sha, size) or _verify_payload(
                    upload, sha, size, prefix
                )
                prepared = None
                blob_id = new_id("blob")
                key = f"dump-blobs/{sha}/original.dmp"
                if rejection is None:
                    raw = directory / ("dump.dmp" if upload.file_kind == "dmp" else "file")
                    self.store.download_file(upload.object_key, raw)
                    # Parse precisely the bytes whose transport hash was verified.
                    if raw.stat().st_size != size or _file_sha256(raw) != sha:
                        rejection = "staged_content_mismatch"
                    else:
                        try:
                            if upload.file_kind == "dmp":
                                if self.settings.core_executor != "fake":
                                    inspected = self.core.inspect(directory, {})
                                    if inspected["process"]["architecture"] != "x86_64":
                                        rejection = "unsupported_architecture"
                                    if inspected["dump"]["kind"] != "user_minidump":
                                        rejection = "unsupported_dump"
                            else:
                                prepared = prepare_file(
                                    self.core, self.store, raw, upload.file_kind, sha, size
                                )
                        except CoreExecutionError as error:
                            if error.code in {
                                "FILE_IDENTITY_INVALID",
                                "ARTIFACT_IDENTIFY_FAILED",
                                "CORRUPT_DUMP",
                                "UNSUPPORTED_DUMP",
                                "INVALID_INPUT",
                            }:
                                rejection = error.code.lower()
                            else:
                                raise
                with self.sessions.begin() as session:
                    if rejection is None and upload.file_kind == "dmp":
                        from crashcap_api.services.dump_content import retain_dump_content

                        key = retain_dump_content(session, self.store, sha, directory / "dump.dmp")
                    # Use the same lock order as catalog planning and adoption.
                    lock_catalog(session)
                    if not claim_is_current(session, claim, lock=True):
                        return
                    current = session.scalar(
                        select(Upload).where(Upload.id == upload.id).with_for_update()
                    )
                    if current is None or current.verification_status != "VERIFYING":
                        finish_claim(session, claim, "succeeded")
                        return
                    current.verified_wire_length = current.verified_length = size
                    current.verified_wire_sha256 = current.verified_sha256 = sha
                    if rejection:
                        current.rejection_reason = rejection
                        transition_upload(current, "REJECTED")
                    else:
                        if current.file_kind == "dmp":
                            self._accept_dump(
                                session,
                                current,
                                blob_id=blob_id,
                                object_key=key,
                                request_id=message.get("request_id"),
                            )
                        else:
                            assert prepared is not None
                            accept_file(session, current, *prepared)
                        transition_upload(current, "ACCEPTED")
                    operation_log(
                        session,
                        action="upload.verify",
                        target_type="upload",
                        target_id=current.id,
                        workspace_id=current.workspace_id,
                        request_id=message.get("request_id"),
                        result="rejected" if rejection else "accepted",
                        details={"sha256": sha, "size": size, "reason": rejection},
                    )
                    if not finish_claim(session, claim, "succeeded"):
                        raise RuntimeError("Upload execution ownership was lost")
                # A durable verified result owns the content; staging is disposable.
                try:
                    self.store.delete(upload.object_key)
                    with self.sessions.begin() as session:
                        cleaned = session.get(Upload, upload.id)
                        if cleaned is not None:
                            cleaned.payload_deleted_at = utcnow()
                            cleaned.payload_deletion_reason = "verified_result_persisted"
                except Exception:
                    LOGGER.warning("Upload staging cleanup deferred upload_id=%s", upload.id)
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
                capture_profile=upload.capture_profile,
                verification_status="ACCEPTED",
                uploaded_at=upload.completed_at or utcnow(),
                expires_at=(upload.completed_at or utcnow())
                + timedelta(days=workspace.retention_days),
            )
            session.add(blob)
            session.flush()
        elif blob.deleted_at is not None or (
            blob.expires_at is not None and blob.expires_at.replace(tzinfo=UTC) <= utcnow()
        ):
            # An explicit re-upload restores retained bytes without creating a new occurrence.
            blob.object_key = object_key
            blob.deleted_at = None
            blob.expires_at = (upload.completed_at or utcnow()) + timedelta(
                days=workspace.retention_days
            )
        occurrence = session.scalar(select(Occurrence).where(Occurrence.dump_blob_id == blob.id))
        if occurrence is None:
            uploaded_at = upload.completed_at or utcnow()
            occurred_at = upload.reported_at or uploaded_at
            occurrence = Occurrence(
                id=new_id("occ"),
                workspace_id=upload.workspace_id,
                dump_blob_id=blob.id,
                version=upload.version,
                reported_at=upload.reported_at,
                uploaded_at=uploaded_at,
                occurred_at=occurred_at,
                time_source="reported" if upload.reported_at else "uploaded",
            )
            session.add(occurrence)
            session.flush()
        from crashcap_api.services.occurrence_submissions import record_verified_submission

        record_verified_submission(
            session,
            upload,
            occurrence,
            include_unannotated=self.settings.automatic_analysis_enabled,
        )
        ensure_demand(session, occurrence.id, now=utcnow())
        return None

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
                release_execution_slot_for_run(session, run.id)
                finish_claim(session, claim, "succeeded")
                session.commit()
                return True
            run.error_code = code
            run.error_detail = detail[-2000:].replace("\x00", "")
            release_execution_slot_for_run(session, run.id)
            if (
                run.demand_id is not None
                and run.demand_generation is not None
                and run.retry_attempt is not None
            ):
                demand = session.scalar(
                    select(AnalysisDemand)
                    .where(AnalysisDemand.id == run.demand_id)
                    .with_for_update()
                )
                occurrence = session.get(Occurrence, run.occurrence_id)
                blob = session.get(DumpBlob, occurrence.dump_blob_id) if occurrence else None
                if (
                    demand is not None
                    and blob is not None
                    and demand.generation == run.demand_generation
                    and demand.retry_attempt == run.retry_attempt
                ):
                    settle_demand_after_execution_failure(
                        demand,
                        blob,
                        cause=str(run.run_spec.get("reason", "initial")),
                        error_code=code,
                        retryable=_frozen_failure_retryable(code),
                        settings=self.settings,
                        now=utcnow(),
                    )
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


def _frozen_failure_retryable(code: str) -> bool:
    return code not in {
        "CORRUPT_DUMP",
        "FROZEN_RUN_REQUIRED",
        "INVALID_FROZEN_EVIDENCE",
        "UNSUPPORTED_DUMP",
    }


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
    return None


def _file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _verify_wire_payload(upload: Upload, digest: str, size: int) -> str | None:
    if upload.wire_encoding not in {"identity", "zstd-v1"}:
        return "unsupported_wire_encoding"
    if upload.wire_encoding == "zstd-v1" and upload.file_kind not in {"pe", "pdb"}:
        return "unsupported_wire_encoding"
    if size != upload.wire_declared_length:
        return "wire_length_mismatch"
    if (
        upload.wire_encoding == "zstd-v1"
        and upload.wire_sha256_hint
        and digest.lower() != upload.wire_sha256_hint.lower()
    ):
        return "wire_sha256_mismatch"
    return None


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


def _upsert_summary(session: Session, run: AnalysisRun, canonical: dict[str, Any]) -> None:
    crash = canonical["crash"]
    quality = canonical["quality"]
    crashing_thread = next(
        (thread for thread in canonical["threads"] if thread.get("is_crashing")), None
    )
    frames = (crashing_thread or {}).get("frames", [])[:15]
    top = next((frame for frame in frames if frame.get("in_app")), frames[0] if frames else {})
    summary = session.get(AnalysisSummary, run.id) or AnalysisSummary(
        analysis_run_id=run.id,
        occurrence_id=run.occurrence_id,
        crash_type=crash["type"],
    )
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
    update_group_projection(session, occurrence, run, canonical)


def _existing_temp_root(path: Path) -> str:
    path.mkdir(parents=True, exist_ok=True)
    return str(path)
