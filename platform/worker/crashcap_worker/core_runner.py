from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import AbstractContextManager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from crashcap_api.canonical_semantics import bind_legacy_canonical
from crashcap_api.config import Settings

from .source_bundle import SourceBundleError, attach_staged_source_context


class CoreExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, returncode: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.returncode = returncode


@dataclass(frozen=True)
class CoreOutput:
    inspect: dict[str, Any]
    canonical: dict[str, Any]
    raw: dict[str, Path]
    shadow_differences: tuple[str, ...] = ()


class CoreExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def identify_artifact(self, path: Path, kind: str) -> dict[str, Any]:
        if self.settings.core_executor == "fake":
            return _fake_identity(path, kind)
        with tempfile.TemporaryDirectory(prefix="crashcap-identify-") as raw_temp:
            task_dir = Path(raw_temp)
            artifact_path = task_dir / f"artifact.{kind}"
            shutil.copyfile(path, artifact_path)
            output = task_dir / "identity.json"
            _prepare_container_output(output)
            if self.settings.core_executor == "local":
                self._run_local(
                    [
                        "identify",
                        "--kind",
                        kind,
                        "--artifact",
                        str(artifact_path),
                        "--output",
                        str(output),
                    ]
                )
            else:
                with DockerVolumeWorkspace(self.settings, task_dir) as workspace:
                    workspace.run(
                        [
                            "identify",
                            "--kind",
                            kind,
                            "--artifact",
                            f"/work/{artifact_path.name}",
                            "--output",
                            "/work/identity.json",
                        ]
                    )
            return cast(dict[str, Any], json.loads(output.read_text(encoding="utf-8")))

    def analyze(self, task_dir: Path, run_spec: dict[str, Any]) -> CoreOutput:
        self.inspect(task_dir, run_spec)
        return self.analyze_prepared(task_dir, run_spec)

    def inspect(self, task_dir: Path, run_spec: dict[str, Any]) -> dict[str, Any]:
        """Produce deterministic Dump evidence before the final analysis stage."""

        dump = task_dir / "dump.dmp"
        inspect_path = task_dir / "inspect.json"
        _prepare_container_output(inspect_path)
        with suppress(OSError):
            task_dir.chmod(0o777)

        if self.settings.core_executor == "fake":
            inspect, _canonical = _fake_analysis(run_spec)
            inspect_path.write_text(json.dumps(inspect), encoding="utf-8")
        elif self.settings.core_executor == "local":
            self._run_local(["inspect", "--dump", str(dump), "--output", str(inspect_path)])
        else:
            with DockerVolumeWorkspace(self.settings, task_dir) as workspace:
                workspace.run(
                    ["inspect", "--dump", "/work/dump.dmp", "--output", "/work/inspect.json"]
                )
        return cast(dict[str, Any], json.loads(inspect_path.read_text(encoding="utf-8")))

    def analyze_prepared(self, task_dir: Path, run_spec: dict[str, Any]) -> CoreOutput:
        """Analyze using already persisted inspect and match checkpoints."""

        inspect_path = task_dir / "inspect.json"
        match_path = task_dir / "match.json"
        if not inspect_path.is_file() or not match_path.is_file():
            raise CoreExecutionError(
                "MISSING_ANALYSIS_CHECKPOINT",
                "prepared analysis requires inspect.json and match.json",
            )
        canonical_path = task_dir / "canonical.json"
        raw_dir = task_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        _prepare_container_output(canonical_path)
        try:
            raw_dir.chmod(0o777)
            task_dir.chmod(0o777)
        except OSError:
            pass

        if self.settings.core_executor == "fake":
            _inspect, canonical = _fake_analysis(run_spec)
            context_path = task_dir / "analysis-context.json"
            if context_path.is_file():
                (raw_dir / "legacy-canonical.json").write_text(
                    json.dumps(canonical, sort_keys=True),
                    encoding="utf-8",
                )
                runtime_context = cast(
                    dict[str, Any],
                    json.loads(context_path.read_text(encoding="utf-8")),
                )
                canonical = bind_legacy_canonical(canonical, runtime_context)
                try:
                    attach_staged_source_context(canonical, runtime_context, task_dir)
                except SourceBundleError as error:
                    canonical["quality"]["warnings"].append(
                        {
                            "code": "other",
                            "message": f"Source context omitted: {error}",
                            "module": None,
                            "debug_id": None,
                        }
                    )
            canonical_path.write_text(json.dumps(canonical), encoding="utf-8")
        elif self.settings.core_executor == "local":
            self._run_local(self._analyze_arguments(run_spec, task_dir, container=False))
        else:
            with DockerVolumeWorkspace(self.settings, task_dir) as workspace:
                workspace.run(self._analyze_arguments(run_spec, task_dir, container=True))

        inspect = cast(dict[str, Any], json.loads(inspect_path.read_text(encoding="utf-8")))
        canonical = cast(dict[str, Any], json.loads(canonical_path.read_text(encoding="utf-8")))
        raw = {
            name: path
            for name, path in {
                "raw/minidump.json": raw_dir / "minidump.json",
                "raw/symbolicator.json": raw_dir / "symbolicator.json",
                "raw/match.json": raw_dir / "match.json",
                "raw/inspect.json": inspect_path,
                "raw/legacy-canonical.json": raw_dir / "legacy-canonical.json",
            }.items()
            if path.is_file()
        }
        return CoreOutput(inspect=inspect, canonical=canonical, raw=raw)

    def _analyze_arguments(
        self, run_spec: dict[str, Any], task_dir: Path, *, container: bool
    ) -> list[str]:
        prefix = Path("/work") if container else task_dir
        arguments = [
            "analyze",
            "--dump",
            str(prefix / "dump.dmp"),
            "--inspect",
            str(prefix / "inspect.json"),
            "--match",
            str(prefix / "match.json"),
            "--symbolicator",
            self.settings.symbolicator_url,
            "--workspace-id",
            str(run_spec["workspace_id"]),
            "--symbol-inventory-version",
            str(run_spec["symbol_inventory_version"]),
            "--symbolicator-timeout",
            str(self.settings.symbolicator_timeout_seconds),
            "--core-image-digest",
            self.settings.core_image_digest,
            "--symbolicator-version",
            self.settings.symbolicator_version,
            "--output",
            str(prefix / "canonical.json"),
            "--raw-dir",
            str(prefix / "raw"),
        ]
        capture_profile = run_spec.get("capture_profile")
        if capture_profile:
            arguments.extend(["--capture-profile", str(capture_profile)])
        if (task_dir / "analysis-context.json").is_file():
            arguments.extend(
                [
                    "--analysis-context",
                    str(prefix / "analysis-context.json"),
                ]
            )
        return arguments

    def _run_local(self, arguments: list[str]) -> None:
        command = [self.settings.core_command, *arguments]
        _run(command, timeout=self.settings.core_timeout_seconds)


class DockerVolumeWorkspace(AbstractContextManager["DockerVolumeWorkspace"]):
    """Run Core from a named task volume; the analysis container has no host bind mount."""

    def __init__(self, settings: Settings, task_dir: Path) -> None:
        self.settings = settings
        self.task_dir = task_dir.resolve()
        suffix = re.sub(r"[^a-z0-9]", "", self.task_dir.name.lower())[-24:] or "task"
        self.volume = f"crashcap-task-{suffix}-{os.getpid()}"
        self.stage = f"{self.volume}-stage"
        self.extract = f"{self.volume}-extract"

    def __enter__(self) -> DockerVolumeWorkspace:
        _verify_core_image(self.settings)
        _run(
            ["docker", "volume", "create", self.volume],
            timeout=30,
            timeout_code="CORE_STAGE_TIMEOUT",
            timeout_message="Core workspace volume creation exceeded its deadline",
            failure_code="CORE_STAGE_FAILED",
        )
        try:
            _run(
                [
                    "docker",
                    "create",
                    "--name",
                    self.stage,
                    "--network",
                    "none",
                    "--mount",
                    f"type=volume,source={self.volume},target=/work",
                    self.settings.core_image,
                    "version",
                ],
                timeout=30,
                timeout_code="CORE_STAGE_TIMEOUT",
                timeout_message="Core staging container creation exceeded its deadline",
                failure_code="CORE_STAGE_FAILED",
            )
            stage_bytes = _tree_size_bytes(self.task_dir)
            _run(
                ["docker", "cp", f"{self.task_dir}{os.sep}.", f"{self.stage}:/work"],
                timeout=self.settings.core_stage_deadline(stage_bytes),
                timeout_code="CORE_STAGE_TIMEOUT",
                timeout_message=f"Core input staging exceeded its deadline for {stage_bytes} bytes",
                failure_code="CORE_STAGE_FAILED",
            )
        except Exception:
            # __exit__ is not called when __enter__ fails. Remove the task
            # volume here so a staging timeout cannot leak Docker resources.
            with suppress(CoreExecutionError):
                _run(
                    ["docker", "volume", "rm", "-f", self.volume],
                    timeout=30,
                    check=False,
                    timeout_code="CORE_STAGE_CLEANUP_TIMEOUT",
                    timeout_message="Core workspace volume cleanup exceeded its deadline",
                )
            raise
        finally:
            with suppress(CoreExecutionError):
                _run(
                    ["docker", "rm", "-f", self.stage],
                    timeout=30,
                    check=False,
                    timeout_code="CORE_STAGE_CLEANUP_TIMEOUT",
                    timeout_message="Core staging container cleanup exceeded its deadline",
                )
        return self

    def run(self, arguments: list[str]) -> None:
        command = [
            "docker",
            "run",
            "--rm",
            "--read-only",
            "--user",
            "65532:65532",
            "--network",
            self.settings.core_network,
            "--memory",
            self.settings.core_memory,
            "--cpus",
            str(self.settings.core_cpus),
            "--pids-limit",
            str(self.settings.core_pids_limit),
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--tmpfs",
            f"/tmp:rw,nosuid,nodev,noexec,size={self.settings.core_tmpfs_size}",  # noqa: S108
            "--mount",
            f"type=volume,source={self.volume},target=/work",
            self.settings.core_image,
            *arguments,
        ]
        _run(
            command,
            timeout=self.settings.core_timeout_seconds,
            timeout_code="CORE_EXECUTION_TIMEOUT",
            timeout_message="Core execution exceeded its fixed deadline",
        )

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            try:
                _run(
                    [
                        "docker",
                        "create",
                        "--name",
                        self.extract,
                        "--network",
                        "none",
                        "--mount",
                        f"type=volume,source={self.volume},target=/work",
                        self.settings.core_image,
                        "version",
                    ],
                    timeout=30,
                    timeout_code="CORE_STAGE_TIMEOUT",
                    timeout_message=(
                        "Core result extraction container creation exceeded its deadline"
                    ),
                    failure_code="CORE_STAGE_FAILED",
                )
                _run(
                    ["docker", "cp", f"{self.extract}:/work/.", str(self.task_dir)],
                    timeout=self.settings.core_stage_deadline(_tree_size_bytes(self.task_dir)),
                    check=exc is None,
                    timeout_code="CORE_STAGE_TIMEOUT",
                    timeout_message="Core result extraction exceeded its deadline",
                    failure_code="CORE_STAGE_FAILED",
                )
            except CoreExecutionError:
                if exc is None:
                    raise
        finally:
            with suppress(CoreExecutionError):
                _run(
                    ["docker", "rm", "-f", self.extract],
                    timeout=30,
                    check=False,
                    timeout_code="CORE_STAGE_CLEANUP_TIMEOUT",
                    timeout_message="Core extraction container cleanup exceeded its deadline",
                )
            with suppress(CoreExecutionError):
                _run(
                    ["docker", "volume", "rm", "-f", self.volume],
                    timeout=30,
                    check=False,
                    timeout_code="CORE_STAGE_CLEANUP_TIMEOUT",
                    timeout_message="Core workspace volume cleanup exceeded its deadline",
                )


def _run(
    command: list[str],
    *,
    timeout: int,
    check: bool = True,
    timeout_code: str = "CORE_EXECUTION_TIMEOUT",
    timeout_message: str = "Core execution exceeded its fixed deadline",
    failure_code: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(  # noqa: S603 - argv-only execution, never a shell
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise CoreExecutionError(timeout_code, timeout_message) from error
    if check and result.returncode != 0:
        stderr = result.stderr[-4000:].replace("\x00", "")
        structured = _structured_core_error(stderr)
        code = failure_code or (
            structured[0]
            if structured
            else (
                "OOM"
                if result.returncode in {137, -9}
                else "UNSUPPORTED_DUMP"
                if result.returncode == 2
                else "CORRUPT_DUMP"
                if result.returncode == 3
                else "CORE_FAILED"
            )
        )
        message = structured[1] if structured else f"Core exited {result.returncode}: {stderr}"
        raise CoreExecutionError(code, message, returncode=result.returncode)
    return result


def _tree_size_bytes(root: Path) -> int:
    total = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def _structured_core_error(stderr: str) -> tuple[str, str] | None:
    for line in reversed(stderr.splitlines()):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        error = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(error, dict):
            continue
        code = error.get("code")
        message = error.get("message")
        if isinstance(code, str) and isinstance(message, str):
            return code[:100], message[:2000]
    return None


def _verify_core_image(settings: Settings) -> None:
    result = _run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", settings.core_image],
        timeout=30,
    )
    actual = result.stdout.strip().lower()
    if actual != settings.core_image_digest:
        raise CoreExecutionError(
            "CORE_IMAGE_MISMATCH",
            "Configured Core image does not match the pinned image digest",
        )


def _prepare_container_output(path: Path) -> None:
    """Pre-create an output writable by the fixed non-root Core UID."""

    path.touch()
    # Windows ACLs do not always expose POSIX chmod semantics. Docker cp still
    # preserves a writable file for the Linux task volume.
    with suppress(OSError):
        path.chmod(0o666)


def _fake_identity(path: Path, kind: str) -> dict[str, Any]:
    payload = path.read_bytes()
    import hashlib

    digest = hashlib.sha256(payload).hexdigest()
    marker = re.search(rb"CRASHCAP_DEBUG_ID=([0-9a-fA-F]{33,40})", payload)
    debug_id = marker.group(1).decode().lower() if marker else f"{digest[:32]}1"
    if kind == "pe":
        if not payload.startswith(b"MZ"):
            raise CoreExecutionError("ARTIFACT_IDENTIFY_FAILED", "fake PE is missing MZ")
        return {
            "kind": "pe",
            "size": len(payload),
            "sha256": digest,
            "code_id": digest[:16].upper(),
            "debug_id": debug_id,
            "debug_file": None,
            "is_fastlink": False,
        }
    if not payload.startswith(b"Microsoft C/C++ MSF 7.00"):
        raise CoreExecutionError("ARTIFACT_IDENTIFY_FAILED", "fake PDB is missing MSF 7.0")
    return {
        "kind": "pdb",
        "size": len(payload),
        "sha256": digest,
        "code_id": None,
        "debug_id": debug_id,
        "debug_file": None,
        "is_fastlink": b"CRASHCAP_FASTLINK=1" in payload,
    }


def _fake_analysis(run_spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    blob = run_spec["blob"]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in run_spec.get("artifacts", []):
        key = str(item.get("module_id") or item["artifact_id"])
        grouped.setdefault(key, []).append(item)
    artifact_group = next(
        (
            items
            for items in grouped.values()
            if any(item.get("role") == "entrypoint" for item in items)
        ),
        [],
    )
    pe = next((item for item in artifact_group if item.get("kind") == "pe"), None)
    pdb = next((item for item in artifact_group if item.get("kind") == "pdb"), None)
    artifact = pe or pdb
    manifest_module = next(
        (
            module
            for build in run_spec.get("builds", [])
            for module in build.get("modules", [])
            if module.get("role") == "entrypoint"
        ),
        None,
    )
    code_file = (artifact or manifest_module or {}).get("code_file") or "app.exe"
    debug_file = (artifact or manifest_module or {}).get("debug_file") or "app.pdb"
    code_id = pe.get("code_id") if pe else None
    pe_debug_id = pe.get("debug_id") if pe else None
    pdb_debug_id = pdb.get("debug_id") if pdb else None
    debug_id = pe_debug_id or pdb_debug_id
    if pe and pdb and pe_debug_id and pdb_debug_id:
        module_status = "matched" if pe_debug_id.lower() == pdb_debug_id.lower() else "pdb_mismatch"
    elif pe:
        module_status = "missing_pdb"
    else:
        module_status = "missing_pe"
    matched = module_status == "matched"

    reported_build_id = run_spec.get("reported_build_id")
    candidates: list[str] = []
    for build in run_spec.get("builds", []):
        for candidate_module in build.get("modules", []):
            if candidate_module.get("role") != "entrypoint":
                continue
            comparisons = []
            if code_id:
                comparisons.append(candidate_module.get("code_id") == code_id)
            if debug_id:
                comparisons.append(candidate_module.get("debug_id") == debug_id)
            if comparisons and all(comparisons):
                candidates.append(str(build["build_id"]))
                break
    candidates = sorted(set(candidates))
    if reported_build_id:
        resolved_build_id = reported_build_id
        resolution_method = "reported"
        evidence_candidates = [reported_build_id]
    elif len(candidates) == 1:
        resolved_build_id = candidates[0]
        resolution_method = "auto_unique"
        evidence_candidates = candidates
    elif len(candidates) > 1:
        resolved_build_id = None
        resolution_method = "ambiguous"
        evidence_candidates = candidates
    else:
        resolved_build_id = None
        resolution_method = "unresolved"
        evidence_candidates = []

    warnings: list[dict[str, Any]] = []
    if not matched:
        warnings.append(
            {
                "code": module_status,
                "message": f"business module is {module_status}",
                "module": code_file,
                "debug_id": debug_id,
            }
        )
    if resolution_method in {"ambiguous", "unresolved"}:
        warnings.append(
            {
                "code": f"{resolution_method}_build",
                "message": f"Build resolution is {resolution_method}; no Version was guessed",
            }
        )
    capture_profile = run_spec.get("capture_profile")
    crash_type = "hang" if capture_profile == "hang" else "crash"
    role = str((artifact or manifest_module or {}).get("role") or "entrypoint")
    in_app = bool(
        (artifact or manifest_module or {}).get("in_app", role in {"entrypoint", "owned"})
    )
    frame = {
        "index": 0,
        "instruction_addr": "0x1000",
        "module": code_file,
        "module_debug_id": debug_id,
        "relative_addr": "0x10",
        "function": "crashcap::fake_crash" if matched else None,
        "function_raw": "crashcap::fake_crash" if matched else None,
        "function_normalized": "crashcap::fake_crash" if matched else None,
        "function_offset": 16 if matched else None,
        "file": "fake.cpp" if matched else None,
        "line": 42 if matched else None,
        "trust": "context" if pe else "scan",
        "in_app": in_app,
        "inline": False,
        "source_context": None,
    }
    module = {
        "code_file": code_file,
        "code_id": code_id,
        "debug_file": debug_file,
        "debug_id": debug_id,
        "image_base": "0x1000",
        "image_size": 4096,
        "role": role,
        "in_app": in_app,
        "artifact_ids": [item["artifact_id"] for item in artifact_group],
        "status": module_status,
    }
    inspect = {
        "schema_version": "0.1",
        "dump": {"kind": "user_minidump", "size": blob["size"]},
        "process": {"architecture": "x86_64", "os": "windows"},
        "exception": {"code": "0xC0000005"},
        "crash_thread_id": 1,
        "threads": [],
        "modules": [module],
    }
    now = datetime.now(UTC).isoformat()
    canonical = {
        "schema_version": "1.0",
        "workspace_id": run_spec["workspace_id"],
        "occurrence_id": run_spec["occurrence_id"],
        "analysis_id": run_spec["run_id"],
        "engine": {
            "core_version": "1.0.0-test",
            "core_image_digest": run_spec["core_image_digest"],
            "symbolicator_version": run_spec["symbolicator_version"],
            "grouping_version": run_spec["grouping_version"],
            "normalization_version": run_spec["normalization_version"],
        },
        "build_resolution": {
            "reported_build_id": reported_build_id,
            "resolved_build_id": resolved_build_id,
            "resolution_method": resolution_method,
            "evidence": {
                "candidate_build_ids": evidence_candidates,
                "matched_entrypoints": [frame["module"]] if artifact else [],
                "matched_owned_modules": [],
                "conflicting_modules": [],
                "note": None,
            },
        },
        "dump": {
            "blob_id": blob["id"],
            "sha256": blob["sha256"],
            "kind": "user_minidump",
            "size": blob["size"],
            "capture_profile": capture_profile,
            "dump_timestamp": None,
            "reported_at": None,
            "uploaded_at": now,
            "occurred_at": now,
            "time_source": "uploaded",
        },
        "process": {
            "pid": 1,
            "architecture": "x86_64",
            "os": "windows",
            "os_version": None,
            "uptime_seconds": None,
        },
        "crash": {
            "type": crash_type,
            "type_evidence": "reported_hang" if crash_type == "hang" else "exception_stream",
            "thread_id": 1,
            "exception_code": None if crash_type == "hang" else "0xC0000005",
            "exception_name": None if crash_type == "hang" else "EXCEPTION_ACCESS_VIOLATION",
            "access_type": None if crash_type == "hang" else "read",
            "address": None if crash_type == "hang" else "0x1000",
            "fault_module": frame["module"],
            "fault_module_debug_id": debug_id,
        },
        "threads": [{"id": 1, "name": None, "is_crashing": True, "frames": [frame]}],
        "modules": [module],
        "quality": {
            "score": 1.0 if matched else 0.5,
            "symbol_coverage": 1.0 if matched else 0.0,
            "unwind_reliability": 1.0 if matched else (0.35 if pe is None else 0.7),
            "artifact_completeness": 1.0 if matched else 0.5,
            "warnings": warnings,
        },
        "fingerprints": {
            "exact": hashlib.sha256(f"{debug_id}:crashcap::fake_crash".encode()).hexdigest()
            if matched and crash_type == "crash" and in_app
            else None,
            "family": None,
            "algorithm": "exact-v1.0",
        },
    }
    return inspect, canonical
