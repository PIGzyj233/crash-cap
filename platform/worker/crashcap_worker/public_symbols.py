"""Fetch exact Windows PDBs into the engine's persistent download cache.

Only GET /proxy is used. This module never creates analysis work, publishes
catalog symbols, changes Current, or invalidates any cache.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import re
import shutil
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote, urlsplit

from crashcap_api.config import Settings
from crashcap_api.models import AnalysisRun, CurrentDecision, PublicSymbolJob, utcnow
from crashcap_api.services.common import operation_log
from crashcap_api.storage import ObjectStore
from crashcap_api.task_handoff import TaskClaim, claim_is_current, claim_task, finish_claim
from sqlalchemy.orm import Session, sessionmaker

from .core_runner import CoreExecutionError, CoreExecutor

if TYPE_CHECKING:
    from .processor import WorkerProcessor


def pdb_identity(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.replace("-", "").lower()
    if re.fullmatch(r"[0-9a-f]{33,40}", raw) is None:
        return None
    return raw[:32] + format(int(raw[32:], 16), "x")


def targets(
    inspect: dict[str, Any], manifest: dict[str, Any], canonical: dict[str, Any] | None, limit: int
) -> list[dict[str, Any]]:
    captured, selections = inspect["modules"], manifest["modules"]
    if len(captured) != len(selections):
        raise ValueError("frozen module cardinality differs")
    ready = {
        module["module_index"]
        for module in (canonical or {}).get("modules", [])
        if any(
            outcome.get("stage") in {"symbolicate", "download_pdb"}
            and outcome.get("outcome") == "found"
            for outcome in module.get("source_outcomes", [])
        )
    }
    result: list[dict[str, Any]] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for index, (module, selection) in enumerate(zip(captured, selections, strict=True)):
        if selection["module_index"] != index:
            raise ValueError("frozen module index differs")
        identity = selection["identity"]
        if (
            pdb_identity(module.get("debug_id")) != pdb_identity(identity.get("debug_id"))
            or str(module.get("code_id") or "").lower()
            != str(identity.get("code_id") or "").lower()
        ):
            raise ValueError("frozen module identity differs")
        filename = PureWindowsPath(str(module.get("debug_file") or "")).name.lower()
        debug_id = pdb_identity(module.get("debug_id"))
        skipped = (
            "private_selection"
            if selection["state"] != "none"
            else "already_available"
            if index in ready
            else "debug_identity_unavailable"
            if not debug_id or not re.fullmatch(r"[a-z0-9_.+ -]+\.pdb", filename)
            else "target_limit"
            if len(seen) >= limit
            else None
        )
        item: dict[str, Any] = {
            "module_indexes": [index],
            "code_file": module.get("code_file"),
            "debug_file": filename or None,
            "debug_id": debug_id,
            "status": "skipped" if skipped else "pending",
            "reason": skipped,
        }
        if skipped:
            result.append(item)
        else:
            assert debug_id is not None
            if (filename, debug_id) in seen:
                seen[(filename, debug_id)]["module_indexes"].append(index)
            else:
                seen[(filename, debug_id)] = item
                result.append(item)
    return result


def download_pdb(
    settings: Settings, item: dict[str, Any], destination: Path, deadline: float
) -> dict[str, Any]:
    """Bound connect, headers and each read by one per-file wall-clock deadline."""
    endpoint = urlsplit(settings.frozen_symbolicator_url)
    if (
        endpoint.scheme not in {"http", "https"}
        or not endpoint.hostname
        or endpoint.username
        or endpoint.query
    ):
        raise ValueError("invalid managed Symbolicator endpoint")
    name, debug_id = str(item["debug_file"]), str(item["debug_id"])
    path = (
        endpoint.path.rstrip("/")
        + "/proxy/"
        + "/".join(map(quote, (name, debug_id[:32] + debug_id[32:].upper(), name)))
    )
    deadline = min(deadline, time.monotonic() + settings.public_symbol_file_timeout_seconds)
    connection_type = (
        http.client.HTTPSConnection if endpoint.scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_type(
        endpoint.hostname, endpoint.port, timeout=max(0.01, deadline - time.monotonic())
    )
    started = time.monotonic()
    try:
        connection.connect()
        sock = connection.sock
        assert sock is not None
        sock.settimeout(max(0.01, deadline - time.monotonic()))
        connection.request("GET", path, headers={"Accept": "application/octet-stream"})
        sock.settimeout(max(0.01, deadline - time.monotonic()))
        response = connection.getresponse()
        if response.status == 404:
            return {
                "status": "not_found",
                "reason": "microsoft_symbol_not_found",
                "http_status": 404,
            }
        if response.status != 200:
            return {
                "status": "failed",
                "reason": "public_symbol_http_error",
                "http_status": response.status,
            }
        maximum = 2 * 1024**3
        declared = response.getheader("Content-Length")
        if declared is not None and (not declared.isdigit() or not 0 < int(declared) <= maximum):
            return {"status": "failed", "reason": "public_symbol_size_invalid"}
        size, sha = 0, hashlib.sha256()
        with destination.open("xb") as output:
            while True:
                if response.isclosed():
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("public symbol deadline exceeded")
                sock.settimeout(remaining)
                block = response.read1(1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > maximum:
                    return {"status": "failed", "reason": "public_symbol_size_invalid"}
                sha.update(block)
                output.write(block)
        if not size or (declared is not None and size != int(declared)):
            return {"status": "failed", "reason": "public_symbol_size_invalid"}
        return {
            "status": "downloaded",
            "reason": "awaiting_identity_check",
            "sha256": sha.hexdigest(),
            "size": size,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
        }
    finally:
        connection.close()


def _json_reference(store: ObjectStore, reference: dict[str, Any]) -> dict[str, Any]:
    payload = bytearray()
    for block in store.stream(reference["object_key"]):
        payload.extend(block)
        if len(payload) > 32 * 1024 * 1024:
            raise ValueError("frozen JSON object too large")
    if hashlib.sha256(payload).hexdigest() != reference["sha256"]:
        raise ValueError("frozen JSON object hash mismatch")
    return cast(dict[str, Any], json.loads(payload))


def run_public_symbol_job(processor: WorkerProcessor, message: dict[str, Any]) -> None:
    settings, sessions, store = processor.settings, processor.sessions, processor.store
    with sessions.begin() as session:
        claim = claim_task(
            session, message, settings.schema_root, lease_seconds=settings.task_lease_seconds
        )
        if not claim.acquired:
            return
        job = session.get(PublicSymbolJob, message["job_id"])
        if job is None or job.status in {"completed", "failed"}:
            finish_claim(session, claim, "succeeded")
            return
        job.status = "running"
        job.started_at = job.started_at or utcnow()
        started_at = (
            job.started_at.replace(tzinfo=UTC) if job.started_at.tzinfo is None else job.started_at
        )
        run = session.get(AnalysisRun, job.source_run_id)
        spec = dict(run.run_spec) if run else {}
        decision = session.get(CurrentDecision, job.source_run_id)
        result_ref = (
            {
                "object_key": run.result_object_key,
                "sha256": decision.candidate_evidence["canonical_sha256"],
            }
            if run and run.result_object_key and decision
            else None
        )
        items = list(job.items)
    remaining = (
        settings.public_symbol_job_budget_seconds - (datetime.now(UTC) - started_at).total_seconds()
    )
    deadline = time.monotonic() + max(0, remaining)
    try:
        if not items:
            inspect = _json_reference(store, spec["inspect"])
            manifest = _json_reference(store, spec["resolution_manifest"])
            canonical = _json_reference(store, result_ref) if result_ref else None
            items = targets(inspect, manifest, canonical, settings.public_symbol_max_modules)
        for item in items:
            if item["status"] not in {"pending", "fetching"}:
                continue
            if time.monotonic() >= deadline:
                item.update(status="failed", reason="public_symbol_job_budget_exhausted")
                continue
            item.update(status="fetching", reason=None)
            if not _save_job(sessions, claim, message["job_id"], items):
                return
            settings.task_tmp_root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(
                prefix="public-symbol-", dir=settings.task_tmp_root
            ) as temporary:
                path = Path(temporary) / "symbol.pdb"
                try:
                    if shutil.disk_usage(temporary).free < 2 * 1024**3 + 64 * 1024**2:
                        raise OSError("public symbol disk capacity insufficient")
                    result = download_pdb(settings, item, path, deadline)
                    if result["status"] == "downloaded":
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError("identity budget exhausted")
                        identity = CoreExecutor(
                            settings.model_copy(
                                update={"core_timeout_seconds": max(1, min(60, int(remaining)))}
                            )
                        ).identify_artifact(path, "pdb")
                        result["identity"] = identity
                        if (
                            identity.get("kind") != "pdb"
                            or pdb_identity(identity.get("debug_id")) != item["debug_id"]
                        ):
                            result.update(
                                status="identity_mismatch", reason="public_pdb_identity_mismatch"
                            )
                        else:
                            result.update(reason="pdb_identity_verified")
                    item.update(result)
                except (
                    TimeoutError,
                    OSError,
                    http.client.HTTPException,
                    CoreExecutionError,
                ) as error:
                    item.update(
                        status="failed",
                        reason="public_symbol_timeout"
                        if isinstance(error, TimeoutError)
                        else "public_symbol_fetch_or_validation_failed",
                        error_type=type(error).__name__,
                    )
            if not _save_job(sessions, claim, message["job_id"], items):
                return
        _save_job(sessions, claim, message["job_id"], items, terminal="completed")
    except Exception as error:
        _save_job(
            sessions,
            claim,
            message["job_id"],
            items,
            terminal="failed",
            error_code="PUBLIC_SYMBOL_EVIDENCE_INVALID"
            if isinstance(error, (ValueError, KeyError))
            else "PUBLIC_SYMBOL_JOB_FAILED",
        )


def _save_job(
    sessions: sessionmaker[Session],
    claim: TaskClaim,
    job_id: str,
    items: list[dict[str, Any]],
    *,
    terminal: str | None = None,
    error_code: str | None = None,
) -> bool:
    with sessions.begin() as session:
        if not claim_is_current(session, claim, lock=True):
            return False
        job = session.get(PublicSymbolJob, job_id)
        if job is None:
            return False
        # JSON values must be replaced, including their nested dictionaries.
        job.items = json.loads(json.dumps(items))
        if terminal:
            job.status, job.finished_at, job.error_code = terminal, utcnow(), error_code
            operation_log(
                session,
                action="public_symbols.complete",
                target_type="public_symbol_job",
                target_id=job_id,
                workspace_id=job.workspace_id,
                result=terminal,
                details={
                    "cache_only": True,
                    "source_run_id": job.source_run_id,
                    "downloaded": sum(i["status"] == "downloaded" for i in items),
                },
            )
            finish_claim(session, claim, "succeeded")
        return True
