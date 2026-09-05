from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from contextlib import AbstractContextManager, suppress
from pathlib import Path
from typing import Any, cast

from crashcap_api.config import Settings


class CoreExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, returncode: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.returncode = returncode


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

    def inspect(self, task_dir: Path, run_spec: dict[str, Any]) -> dict[str, Any]:
        """Produce deterministic Dump evidence before the final analysis stage."""

        dump = task_dir / "dump.dmp"
        inspect_path = task_dir / "inspect.json"
        _prepare_container_output(inspect_path)
        with suppress(OSError):
            task_dir.chmod(0o777)

        if self.settings.core_executor == "fake":
            inspect = {
                "schema_version": "0.1",
                "dump": {"kind": "user_minidump", "size": run_spec.get("blob", {}).get("size", 32)},
                "process": {"architecture": "x86_64", "os": "windows"},
                "exception": {"code": "0xC0000005"},
                "crash_thread_id": 1,
                "threads": [],
                "modules": [],
            }
            inspect_path.write_text(json.dumps(inspect), encoding="utf-8")
        elif self.settings.core_executor == "local":
            self._run_local(["inspect", "--dump", str(dump), "--output", str(inspect_path)])
        else:
            with DockerVolumeWorkspace(self.settings, task_dir) as workspace:
                workspace.run(
                    ["inspect", "--dump", "/work/dump.dmp", "--output", "/work/inspect.json"]
                )
        return cast(dict[str, Any], json.loads(inspect_path.read_text(encoding="utf-8")))

    def _run_local(self, arguments: list[str]) -> None:
        command = [self.settings.core_command, *arguments]
        _run(command, timeout=self.settings.core_timeout_seconds)


class DockerVolumeWorkspace(AbstractContextManager["DockerVolumeWorkspace"]):
    """Run Core from a named task volume; the analysis container has no host bind mount."""

    def __init__(
        self, settings: Settings, task_dir: Path, *, writable_directories: tuple[str, ...] = ()
    ) -> None:
        self.settings = settings
        self.task_dir = task_dir.resolve()
        suffix = re.sub(r"[^a-z0-9]", "", self.task_dir.name.lower())[-24:] or "task"
        self.volume = f"crashcap-task-{suffix}-{os.getpid()}"
        self.stage = f"{self.volume}-stage"
        self.extract = f"{self.volume}-extract"
        self.writable_directories = writable_directories
        if any(
            re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) is None for name in writable_directories
        ):
            raise CoreExecutionError("CORE_STAGE_FAILED", "Invalid writable directory name")

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
            if self.writable_directories:
                self._prepare_writable_directories()
        except Exception:
            # __exit__ is not called when __enter__ fails. Remove the task
            # container before its mounted volume; Docker cannot remove an
            # in-use volume even with -f.
            with suppress(CoreExecutionError):
                _run(
                    ["docker", "rm", "-f", self.stage],
                    timeout=30,
                    check=False,
                    timeout_code="CORE_STAGE_CLEANUP_TIMEOUT",
                    timeout_message="Core staging container cleanup exceeded its deadline",
                )
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

    def _prepare_writable_directories(self) -> None:
        # Windows host chmod does not encode Unix ownership/mode in docker cp.
        # Apply explicit directory metadata through Docker's archive input; the
        # runtime still runs as UID 65532, with no shell or root execution.
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w") as output:
            for name in self.writable_directories:
                entry = tarfile.TarInfo(name)
                entry.type = tarfile.DIRTYPE
                entry.mode = 0o700
                entry.uid = entry.gid = 65532
                output.addfile(entry)
        try:
            result = subprocess.run(  # noqa: S603 - fixed Docker argv and generated metadata only
                ["docker", "cp", "-a", "-", f"{self.stage}:/work"],  # noqa: S607
                input=archive.getvalue(),
                capture_output=True,
                timeout=30,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise CoreExecutionError(
                "CORE_STAGE_TIMEOUT", "Output directory metadata staging timed out"
            ) from error
        if result.returncode:
            raise CoreExecutionError(
                "CORE_STAGE_FAILED",
                "Output directory metadata staging failed",
                returncode=result.returncode,
            )

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
