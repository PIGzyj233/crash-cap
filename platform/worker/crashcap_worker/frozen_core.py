"""Worker process adapter for sealed Runs; no matching, assembly or promotion here.

The caller owns the private task directory and supplies assignment fields from
the immutable platform record. Staging downloads and durable task fencing are
separate orchestration responsibilities. Never derive the assignment from Run JSON.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from crashcap_api.config import Settings
from crashcap_api.contracts import load_validator
from crashcap_api.frozen_inputs import FrozenInputError, verify_frozen_run

from .core_runner import CoreExecutionError, DockerVolumeWorkspace, _run

MAX_JSON_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class FrozenAssignment:
    run_id: str
    occurrence_id: str
    workspace_id: str
    object_sha256: str


@dataclass(frozen=True)
class FrozenCoreOutput:
    canonical: dict[str, Any]
    canonical_bytes: bytes
    canonical_path: Path
    # Full object keys, not display names. Upload these files without re-encoding.
    raw: dict[str, Path]
    raw_sha256: dict[str, str]


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise CoreExecutionError("INVALID_FROZEN_EVIDENCE", reason)


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json(path: Path) -> tuple[dict[str, Any], bytes]:
    _require(path.is_file() and path.stat().st_size <= MAX_JSON_BYTES, "JSON is not a bounded file")
    with path.open("rb") as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    _require(len(data) <= MAX_JSON_BYTES, "JSON grew beyond its limit")

    def unique(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            _require(key not in value, "JSON has duplicate object keys")
            value[key] = item
        return value

    def constant(_value: str) -> None:
        raise ValueError("non-finite JSON number")

    try:
        value = json.loads(data, object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, UnicodeError) as error:
        raise CoreExecutionError("INVALID_FROZEN_EVIDENCE", "Invalid JSON input/output") from error
    _require(isinstance(value, dict), "JSON must be an object")
    return cast(dict[str, Any], value), data


def _contained_file(root: Path, path: Path) -> Path:
    resolved = path.resolve(strict=True)
    _require(
        resolved.is_relative_to(root) and resolved.is_file(), "staged file escapes task directory"
    )
    return resolved


class FrozenCoreExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def execute(
        self,
        task_dir: Path,
        assignment: FrozenAssignment,
        pairs: dict[str, tuple[Path, Path]],
        *,
        raw_object_prefix: str,
    ) -> FrozenCoreOutput:
        try:
            return self._execute(
                task_dir,
                assignment,
                pairs,
                raw_object_prefix=raw_object_prefix,
            )
        except OSError as error:
            raise CoreExecutionError("FROZEN_STAGE_IO_FAILED", str(error)) from error
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            raise CoreExecutionError("INVALID_FROZEN_EVIDENCE", str(error)) from error

    def _execute(
        self,
        task_dir: Path,
        assignment: FrozenAssignment,
        pairs: dict[str, tuple[Path, Path]],
        *,
        raw_object_prefix: str,
    ) -> FrozenCoreOutput:
        settings = self.settings
        if not settings.frozen_core_enabled:
            raise CoreExecutionError("FROZEN_WRITER_DISABLED", "Frozen Core execution is disabled")
        _require(
            settings.core_executor in {"local", "docker"}, "Frozen execution cannot use fake Core"
        )
        _require(
            settings.frozen_symbolicator_url is not None
            and settings.frozen_pair_source_root is not None
            and settings.frozen_symbolicator_image_digest is not None,
            "Frozen engine/source configuration is incomplete",
        )
        _require(
            re.fullmatch(r"[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*", raw_object_prefix) is not None
            and len(raw_object_prefix) <= 900
            and all(part not in {".", ".."} for part in raw_object_prefix.split("/")),
            "Invalid raw object prefix",
        )
        root = task_dir.resolve(strict=True)
        _require(root.is_dir(), "Task directory does not exist")
        paths = {
            name: _contained_file(root, root / name)
            for name in ("run.json", "resolution-manifest.json", "inspect.json", "dump.dmp")
        }
        run, run_bytes = _json(paths["run.json"])
        _require(
            hashlib.sha256(run_bytes).hexdigest() == assignment.object_sha256,
            "Run object differs from independently assigned digest",
        )
        _require(
            (
                run.get("run_id"),
                run.get("occurrence_id"),
                run.get("context", {}).get("workspace_id"),
            )
            == (assignment.run_id, assignment.occurrence_id, assignment.workspace_id),
            "Run execution identity differs from assignment",
        )
        _, manifest_bytes = _json(paths["resolution-manifest.json"])
        _, inspect_bytes = _json(paths["inspect.json"])
        try:
            manifest, inspect = verify_frozen_run(
                run,
                manifest_bytes=manifest_bytes,
                inspect_bytes=inspect_bytes,
                observed_dump_sha256=_sha(paths["dump.dmp"]),
                observed_dump_size=paths["dump.dmp"].stat().st_size,
                schema_root=settings.schema_root / "drafts/qa-symbol-import",
            )
        except FrozenInputError as error:
            raise CoreExecutionError("INVALID_FROZEN_EVIDENCE", str(error)) from error
        pins = {
            "core_image_digest": settings.core_image_digest,
            "symbolicator_image_digest": settings.frozen_symbolicator_image_digest,
            "symbolicator_version": settings.symbolicator_version,
        }
        _require(
            all(run["context"][key] == value for key, value in pins.items()),
            "Run engines differ from deployment pins",
        )
        selected = {
            module["selected_pair_id"]
            for module in manifest["modules"]
            if module["selected_pair_id"]
        }
        _require(set(pairs) == selected, "Staged pair set differs from frozen selection")
        container = settings.core_executor == "docker"
        prefix = PurePosixPath("/work") if container else root
        staged: dict[str, dict[str, str]] = {}
        for pair, (pe, pdb) in pairs.items():
            staged[pair] = {}
            for kind, path in (("pe", pe), ("pdb", pdb)):
                resolved = _contained_file(root, path)
                staged[pair][kind] = (prefix / resolved.relative_to(root).as_posix()).as_posix()
        descriptor = {
            "schema_version": "frozen-execution-v1",
            "assignment": asdict(assignment),
            "engines": pins,
            "pairs": staged,
        }
        descriptor_bytes = json.dumps(
            descriptor, ensure_ascii=False, separators=(",", ":")
        ).encode()
        output_parent = root / "results"
        output_dir = output_parent / "frozen-output"
        _require(
            not output_dir.exists(), "Frozen output directory already exists; use a new attempt"
        )
        with (root / "execution.json").open("xb") as stream:
            stream.write(descriptor_bytes)
        output_parent.mkdir()
        args = [
            "analyze-frozen",
            "--dump",
            str(prefix / "dump.dmp"),
            "--run",
            str(prefix / "run.json"),
            "--resolution-manifest",
            str(prefix / "resolution-manifest.json"),
            "--inspect",
            str(prefix / "inspect.json"),
            "--execution",
            str(prefix / "execution.json"),
            "--symbolicator",
            str(settings.frozen_symbolicator_url),
            "--pair-source-root",
            str(settings.frozen_pair_source_root).rstrip("/") + "/" + assignment.workspace_id,
            "--symbolicator-timeout",
            str(settings.symbolicator_timeout_seconds),
            "--output-dir",
            str(prefix / "results/frozen-output"),
            "--raw-object-prefix",
            raw_object_prefix,
        ]
        if settings.frozen_allow_local_core_sentinel:
            _require(
                settings.environment != "production" and not container,
                "Local sentinel is forbidden here",
            )
            args.append("--allow-local-core-sentinel")
        if container:
            # DockerVolumeWorkspace sets Linux ownership of the output parent
            # explicitly. Host chmod cannot do that on Windows.
            for path in [
                *paths.values(),
                root / "execution.json",
                *(p for pair in pairs.values() for p in pair),
            ]:
                path.chmod(0o644)
                for parent in path.resolve().parents:
                    if parent == root:
                        break
                    parent.chmod(0o755)
            with DockerVolumeWorkspace(
                settings, root, writable_directories=("results",)
            ) as workspace:
                workspace.run(args)
        else:
            _run([settings.core_command, *args], timeout=settings.core_timeout_seconds)
        return self._validate_output(
            output_dir,
            raw_object_prefix,
            run,
            manifest,
            inspect,
            {
                "run.json": run_bytes,
                "resolution-manifest.json": manifest_bytes,
                "inspect.json": inspect_bytes,
                "execution.json": descriptor_bytes,
            },
        )

    def _validate_output(
        self,
        output: Path,
        prefix: str,
        run: dict[str, Any],
        manifest: dict[str, Any],
        inspect: dict[str, Any],
        input_bytes: dict[str, bytes],
    ) -> FrozenCoreOutput:
        _require(
            not (output / "failure.json").exists(), "Core returned success with a failure receipt"
        )
        canonical_path = _contained_file(output.resolve(), output / "canonical.json")
        canonical, encoded = _json(canonical_path)
        validator = load_validator(
            str((self.settings.schema_root / "analysis-result-v2.0.schema.json").resolve())
        )
        _require(not list(validator.iter_errors(canonical)), "Canonical 1.1 schema mismatch")
        _require(
            (canonical["analysis_id"], canonical["occurrence_id"], canonical["workspace_id"])
            == (run["run_id"], run["occurrence_id"], run["context"]["workspace_id"]),
            "Canonical assignment mismatch",
        )
        _require(
            canonical["dump"] == run["result_facts"]["dump"],
            "Canonical changed immutable dump facts",
        )
        expected_resolution = {
            "selection_version": run["context"]["selection_version"],
            "resolution_evidence_fingerprint": run["resolution_evidence_fingerprint"],
            "selection": run["resolution_manifest"],
            "inspect_sha256": run["inspect"]["sha256"],
            "context_sha256": run["context_sha256"],
        }
        _require(
            canonical["symbol_resolution"] == expected_resolution,
            "Canonical changed frozen resolution",
        )
        _require(
            all(
                canonical["engine"][key] == run["context"][key]
                for key in (
                    "core_image_digest",
                    "symbolicator_version",
                    "normalization_version",
                    "grouping_version",
                )
            ),
            "Canonical engine differs from frozen context",
        )
        modules = canonical["modules"]
        roles = run["policy_snapshots"]["role_policy"]["modules"]
        _require(len(modules) == len(manifest["modules"]), "Canonical module count changed")
        for index, (module, selection, role, captured) in enumerate(
            zip(modules, manifest["modules"], roles, inspect["modules"], strict=True)
        ):
            _require(
                module["module_index"] == index and module["selection"] == selection,
                "Canonical changed selected pair evidence",
            )
            _require(
                (module["role"], module["in_app"]) == (role["role"], role["in_app"]),
                "Canonical changed Workspace roles",
            )
            _require(
                all(
                    module[key] == captured[key]
                    for key in (
                        "code_file",
                        "code_id",
                        "debug_file",
                        "debug_id",
                        "image_base",
                        "image_size",
                    )
                ),
                "Canonical changed captured module identity/range",
            )
        raw: dict[str, Path] = {}
        hashes: dict[str, str] = {}
        raw_dir = output / "raw"
        _require(
            not output.is_symlink() and not raw_dir.is_symlink(),
            "Output directories must not be symlinks",
        )
        for path in raw_dir.iterdir():
            _require(path.is_file() and not path.is_symlink(), "Invalid raw evidence entry")
            resolved = _contained_file(output.resolve(), path)
            key = f"{prefix}/raw/{path.name}"
            raw[key], hashes[key] = resolved, _sha(resolved)
        for name, expected in input_bytes.items():
            _require(
                hashes.get(f"{prefix}/raw/{name}") == hashlib.sha256(expected).hexdigest(),
                "Core raw input copy differs from staged input",
            )
        for module in modules:
            for outcome in module["source_outcomes"]:
                reference = outcome["diagnostic_ref"]
                if reference is not None:
                    _require(
                        hashes.get(reference["object_key"]) == reference["sha256"],
                        "Diagnostic reference is absent, foreign or has wrong bytes",
                    )
        return FrozenCoreOutput(canonical, encoded, canonical_path, raw, hashes)
