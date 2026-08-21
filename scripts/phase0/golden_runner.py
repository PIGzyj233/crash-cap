#!/usr/bin/env python3
"""Execute the Phase 0 golden corpus and publish auditable evidence.

The runner deliberately treats fixture metadata as a contract, not as an
analysis result.  Every fixture with a dump is sent through the real
``dmp-core`` executable; missing generated artifacts, missing fixtures, and
unavailable Symbolicator evidence are represented as ``SKIP``/``INCOMPLETE``
and never as a passing analysis.  Outputs are written below ``target`` and the
two requested evidence files; fixture source directories are read-only from
this program's point of view.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = ROOT / "fixtures" / "index.json"
DEFAULT_OUTPUT_ROOT = ROOT / "target" / "phase0-golden"
DEFAULT_JSON = ROOT / "docs" / "evidence" / "phase0-golden-results.json"
DEFAULT_MD = ROOT / "docs" / "evidence" / "phase0-golden-results.md"
SHA256_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class RunnerFailure(RuntimeError):
    """A per-fixture failure that should be recorded, not abort the corpus."""


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def path_from_arg(value: str | Path, base: Path = ROOT) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base / path


def safe_fixture_output(output_root: Path, fixture_name: str) -> Path:
    """Return one direct output child and reject traversal or symlink escapes."""

    output_root_resolved = output_root.resolve()
    fixture_output = (output_root_resolved / fixture_name).resolve()
    if fixture_output.parent != output_root_resolved:
        raise RunnerFailure(
            f"fixture output must be one direct child of {output_root_resolved}: {fixture_output}"
        )
    return fixture_output


def resolve_fixture_ref(value: Any, fixture_dir: Path) -> Path | None:
    """Resolve a generated artifact reference without trusting stale metadata.

    Older metadata records absolute paths from another checkout.  A relative
    manifest path is authoritative; an absent absolute path is tried by
    basename below only when the fixture actually contains that file.
    """

    if value is None or not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    candidate = Path(raw)
    if candidate.is_file():
        return candidate
    if not candidate.is_absolute():
        local = fixture_dir / candidate
        return local
    # A stale absolute path may still identify a generated file by name.  Do
    # not substitute a different file unless it is present in this fixture.
    local_by_name = fixture_dir / candidate.name
    if local_by_name.is_file():
        return local_by_name
    generated_by_name = fixture_dir / "generated" / candidate.name
    if generated_by_name.is_file():
        return generated_by_name
    return candidate


def relative_or_absolute(value: Any, fixture_dir: Path) -> Path | None:
    if value is None:
        return None
    return resolve_fixture_ref(value, fixture_dir)


def normalize_hex(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return f"0x{value:x}"
    if not isinstance(value, str):
        return None
    text = value.strip()
    try:
        return f"0x{int(text, 16):x}"
    except ValueError:
        return text.lower()


def normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    return str(value).strip().lower()


def module_basename(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\\", "/").rstrip("/")
    return text.rsplit("/", 1)[-1].lower() if text else None


def normalize_symbol(value: Any) -> str | None:
    if value is None or not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    # Canonical output already normalizes signatures.  This also makes the
    # runner tolerant of a raw Symbolicator function in a fixture comparison.
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\([^()]*\)$", "", text).strip()
    return text


def parse_error(stdout: str, stderr: str) -> dict[str, Any]:
    """Extract dmp-core's structured error without echoing a whole response."""

    for stream in (stderr, stdout):
        for line in reversed(stream.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) and isinstance(value.get("error"), dict):
                error = value["error"]
                return {
                    "code": error.get("code"),
                    "message": error.get("message"),
                    "details": error.get("details", {}),
                }
    text = (stderr or stdout).strip()
    return {"code": None, "message": text[-1000:] if text else None, "details": {}}


def core_command(explicit: str | None) -> list[str]:
    if explicit:
        # A path is the documented form.  Accept a command line for local
        # development as a convenience, while keeping subprocess shell=False.
        parts = shlex.split(explicit, posix=False)
        return parts or [explicit]
    for candidate in (
        ROOT / "target" / "release" / "dmp-core.exe",
        ROOT / "target" / "debug" / "dmp-core.exe",
        ROOT / "target" / "release" / "dmp-core",
        ROOT / "target" / "debug" / "dmp-core",
    ):
        if candidate.is_file():
            return [str(candidate)]
    return ["cargo", "run", "-q", "-p", "dmp-core", "--"]


def run_command(
    command: list[str],
    output_dir: Path,
    name: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run a real core command and persist stdout/stderr for audit."""

    started = dt.datetime.now(dt.timezone.utc)
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        timed_out = False
        returncode = completed.returncode
    except subprocess.TimeoutExpired as error:
        stdout = error.stdout or ""
        stderr = error.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        timed_out = True
        returncode = None
    ended = dt.datetime.now(dt.timezone.utc)
    stdout_path = output_dir / f"{name}.stdout.txt"
    stderr_path = output_dir / f"{name}.stderr.txt"
    write_text(stdout_path, stdout)
    write_text(stderr_path, stderr)
    result: dict[str, Any] = {
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_seconds": round((ended - started).total_seconds(), 3),
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }
    if returncode != 0 or timed_out:
        result["error"] = parse_error(stdout, stderr)
    return result


def load_manifest_and_metadata(
    fixture_dir: Path,
    fixture_doc: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    artifacts = fixture_doc.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    manifest_ref = artifacts.get("generated_manifest") or "generated/manifest.json"
    manifest_path = resolve_fixture_ref(manifest_ref, fixture_dir)
    manifest: dict[str, Any] | None = None
    notes: list[str] = []
    if manifest_path and manifest_path.is_file():
        try:
            manifest = read_json(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            notes.append(f"manifest_unreadable:{type(error).__name__}")
    elif manifest_path:
        notes.append("manifest_missing")

    metadata: dict[str, Any] = {}
    # Base metadata describes the dump's build for mismatch fixtures.  The
    # ordinary PE metadata is a fallback for fixtures without a manifest.
    for name in ("base-pe-metadata.json", "pe-metadata.json"):
        path = fixture_dir / "generated" / name
        if path.is_file():
            try:
                value = read_json(path)
                if not metadata:
                    metadata = value
                else:
                    for key in ("code_id", "debug_id", "architecture"):
                        metadata.setdefault(key, value.get(key))
            except (OSError, ValueError, json.JSONDecodeError) as error:
                notes.append(f"{name}_unreadable:{type(error).__name__}")
    return manifest, metadata, notes


def build_artifact_spec(
    fixture_dir: Path,
    fixture_doc: dict[str, Any],
    expected: dict[str, Any],
    manifest: dict[str, Any] | None,
    metadata: dict[str, Any],
    workspace_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    artifacts = fixture_doc.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    target = manifest.get("target", {}) if isinstance(manifest, dict) else {}
    if not isinstance(target, dict):
        target = {}

    def first_value(*values: Any) -> Any:
        for value in values:
            if value is not None:
                return value
        return None

    # Manifest target paths intentionally retain null for missing PE/PDB.
    pe_ref = target.get("path") if "path" in target else artifacts.get("target_pe")
    pdb_ref = target.get("pdb") if "pdb" in target else artifacts.get("target_pdb")
    pe_path = relative_or_absolute(pe_ref, fixture_dir)
    pdb_path = relative_or_absolute(pdb_ref, fixture_dir)
    code_id = first_value(target.get("code_id"), metadata.get("code_id"))
    debug_id = first_value(target.get("debug_id"), metadata.get("debug_id"))
    target_arch = first_value(target.get("architecture"), metadata.get("architecture"))
    expected_module_ids = expected.get("module_ids")
    if isinstance(expected_module_ids, dict):
        # The contract requires these IDs but does not duplicate their values.
        # Never invent them; metadata/manifest are the only accepted evidence.
        pass

    treatment = str(expected.get("artifact_treatment") or "unknown")
    if not code_id and not debug_id:
        return None, {
            "pe_path": str(pe_path) if pe_path else None,
            "pdb_path": str(pdb_path) if pdb_path else None,
            "code_id": None,
            "debug_id": None,
            "architecture": target_arch,
            "treatment": treatment,
            "reason": "missing_artifact_identity",
        }

    code_file = Path(str(pe_ref)).name if pe_ref else "target.exe"
    debug_file = Path(str(pdb_ref)).name if pdb_ref else "target.pdb"
    build_id = f"bld_{fixture_doc.get('fixture_id', fixture_dir.name)}"
    module = {
        "artifact_id": f"art_{fixture_doc.get('fixture_id', fixture_dir.name)}_target",
        "code_file": code_file,
        "debug_file": debug_file,
        "pe_path": str(pe_path) if pe_path else None,
        "pdb_path": str(pdb_path) if pdb_path else None,
        "code_id": code_id,
        "debug_id": debug_id,
        "role": "entrypoint",
        "in_app": True,
        "build_id": build_id,
    }
    match_input = {
        "workspace_id": workspace_id,
        "modules": [module],
        "builds": [
            {
                "build_id": build_id,
                "modules": [
                    {
                        "code_id": code_id,
                        "debug_id": debug_id,
                        "role": "entrypoint",
                        "code_file": code_file,
                    }
                ],
            }
        ],
    }
    details = {
        "pe_path": str(pe_path) if pe_path else None,
        "pdb_path": str(pdb_path) if pdb_path else None,
        "code_id": code_id,
        "debug_id": debug_id,
        "architecture": target_arch,
        "treatment": treatment,
        "pe_exists": bool(pe_path and pe_path.is_file()),
        "pdb_exists": bool(pdb_path and pdb_path.is_file()),
    }
    return match_input, details


def resolve_dump_path(
    fixture_dir: Path,
    fixture_doc: dict[str, Any],
    manifest: dict[str, Any] | None,
) -> Path | None:
    artifacts = fixture_doc.get("artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}
    dump = manifest.get("dump", {}) if isinstance(manifest, dict) else {}
    if not isinstance(dump, dict):
        dump = {}
    ref = dump.get("path") if "path" in dump else artifacts.get("dump")
    return resolve_fixture_ref(ref, fixture_dir)


def expected_treatment(expected_doc: dict[str, Any]) -> str:
    value = expected_doc.get("expected", {}).get("artifact_treatment")
    return str(value or "unknown")


def expected_dump(expected_doc: dict[str, Any]) -> dict[str, Any]:
    value = expected_doc.get("expected", {}).get("dump", {})
    return value if isinstance(value, dict) else {}


def expected_exception(expected_doc: dict[str, Any]) -> dict[str, Any] | None:
    value = expected_doc.get("expected", {}).get("exception")
    return value if isinstance(value, dict) else None


def expected_frames(expected_doc: dict[str, Any]) -> list[str]:
    value = expected_doc.get("expected", {}).get("business_frames", [])
    return [str(item) for item in value] if isinstance(value, list) else []


def cdb_reference_frames(reference_path: Path | None) -> tuple[list[str], list[str]]:
    """Read stable and inline symbol names from an optional CDB summary.

    The checked-in v0 summaries only require a small stable business-frame
    set.  Some release summaries additionally provide an ``inline_frames`` or
    ``inline_business_frames`` section; those names are compared against the
    canonical inline records when present, without making older summaries
    invent an expectation.
    """

    if reference_path is None or not reference_path.is_file():
        return [], []
    try:
        lines = reference_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], []
    section: str | None = None
    business: list[str] = []
    inline: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        lower = line.lower()
        if lower in {"business_frames:", "business_frame:", "resolved_business_frames:"}:
            section = "business"
            continue
        if lower in {"inline_frames:", "inline_business_frames:", "resolved_inline_frames:"}:
            section = "inline"
            continue
        if not raw_line.startswith((" ", "\t")) and line.endswith(":"):
            section = None
            continue
        match = re.match(r"^-\s+(?:resolved|inline_resolved):\s*(.+?)\s*$", line)
        if not match or section is None:
            continue
        target = inline if section == "inline" else business
        name = match.group(1)
        if name not in target:
            target.append(name)
    return business, inline


def find_target_module(
    canonical: dict[str, Any] | None,
    artifact_details: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(canonical, dict):
        return None
    modules = canonical.get("modules", [])
    if not isinstance(modules, list):
        return None
    target_code = normalize_id(artifact_details.get("code_id"))
    target_debug = normalize_id(artifact_details.get("debug_id"))
    for module in modules:
        if not isinstance(module, dict):
            continue
        if target_code and normalize_id(module.get("code_id")) == target_code:
            return module
        if target_debug and normalize_id(module.get("debug_id")) == target_debug:
            return module
    for module in modules:
        if isinstance(module, dict) and module.get("role") == "entrypoint":
            return module
    return None


def warning_codes(canonical: dict[str, Any] | None) -> set[str]:
    if not isinstance(canonical, dict):
        return set()
    quality = canonical.get("quality", {})
    warnings = quality.get("warnings", []) if isinstance(quality, dict) else []
    return {
        str(item.get("code"))
        for item in warnings
        if isinstance(item, dict) and item.get("code")
    }


def warning_messages(canonical: dict[str, Any] | None) -> list[str]:
    if not isinstance(canonical, dict):
        return []
    quality = canonical.get("quality", {})
    warnings = quality.get("warnings", []) if isinstance(quality, dict) else []
    return [
        str(item.get("message", ""))
        for item in warnings
        if isinstance(item, dict)
    ]


def crashing_frames(canonical: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(canonical, dict):
        return []
    threads = canonical.get("threads", [])
    if not isinstance(threads, list):
        return []
    for thread in threads:
        if isinstance(thread, dict) and thread.get("is_crashing"):
            frames = thread.get("frames", [])
            return [frame for frame in frames if isinstance(frame, dict)]
    return []


def symbolicator_completed(raw_dir: Path) -> bool:
    path = raw_dir / "symbolicator.json"
    if not path.is_file():
        return False
    try:
        raw = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    response = raw.get("final_response")
    return isinstance(response, dict) and response.get("status") == "completed"


def symbolicator_target_symbols_available(raw_dir: Path, artifact_details: dict[str, Any]) -> bool:
    """Return true only when the target module was actually symbolized.

    A gateway can complete a request while reporting ``debug_status: missing``
    for one or more modules.  That is a real, useful outcome, but it is not a
    failed golden comparison and it must not inflate the top-three denominator.
    """

    path = raw_dir / "symbolicator.json"
    if not path.is_file():
        return False
    try:
        raw = read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    response = raw.get("final_response")
    if not isinstance(response, dict) or response.get("status") != "completed":
        return False
    target_code = normalize_id(artifact_details.get("code_id"))
    target_debug = normalize_id(artifact_details.get("debug_id"))
    modules = response.get("modules", [])
    if not isinstance(modules, list):
        return False
    for module in modules:
        if not isinstance(module, dict):
            continue
        if target_code and normalize_id(module.get("code_id")) != target_code:
            if not target_debug or normalize_id(module.get("debug_id")) != target_debug:
                continue
        features = module.get("features", {})
        return module.get("debug_status") == "found" and isinstance(features, dict) and features.get("has_symbols") is True
    return False


def compare_result(
    expected_doc: dict[str, Any],
    inspect: dict[str, Any] | None,
    canonical: dict[str, Any] | None,
    rejection: dict[str, Any] | None,
    artifact_details: dict[str, Any],
    raw_dir: Path,
    symbolicator_requested: bool,
    reference_path: Path | None = None,
) -> dict[str, Any]:
    expected = expected_doc.get("expected", {})
    if not isinstance(expected, dict):
        expected = {}
    treatment = str(expected.get("artifact_treatment") or "unknown")
    fields: list[dict[str, Any]] = []
    not_evaluated: list[dict[str, Any]] = []
    not_applicable: list[dict[str, Any]] = []
    reference_business_frames, reference_inline_frames = cdb_reference_frames(reference_path)

    def check(path: str, actual: Any, wanted: Any, *, normalize: str | None = None) -> None:
        left = actual
        right = wanted
        if normalize == "hex":
            left = normalize_hex(actual)
            right = normalize_hex(wanted)
        elif normalize == "id":
            left = normalize_id(actual)
            right = normalize_id(wanted)
        if left != right:
            fields.append({"path": path, "expected": wanted, "actual": actual})

    if rejection is not None:
        wanted = expected_dump(expected_doc)
        actual_code = rejection.get("code")
        acceptable = False
        if treatment == "corrupt_dump":
            acceptable = actual_code == "UNSUPPORTED_DUMP"
        elif treatment == "truncated_dump":
            acceptable = actual_code == "CORRUPT_DUMP"
        elif treatment == "non_x64":
            acceptable = actual_code in {"UNSUPPORTED_DUMP", "UNSUPPORTED_ARCHITECTURE"}
        if not acceptable:
            fields.append(
                {
                    "path": "rejection.code",
                    "expected": treatment,
                    "actual": actual_code,
                }
            )
        return {
            "field_differences": fields,
            "not_evaluated": not_evaluated,
            "not_applicable": not_applicable,
            "warnings": [],
            "target_module": None,
            "target_status": None,
            "symbolicator_completed": False,
            "reference_business_frames": reference_business_frames,
            "reference_inline_frames": reference_inline_frames,
            "acceptable_rejection": acceptable,
        }

    if inspect is None:
        fields.append({"path": "inspect", "expected": "successful inspect", "actual": None})
    else:
        dump = expected_dump(expected_doc)
        actual_dump = inspect.get("dump", {})
        actual_process = inspect.get("process", {})
        if isinstance(dump, dict):
            if "magic_ascii" in dump:
                check("dump.magic_ascii", actual_dump.get("signature"), dump["magic_ascii"])
            if dump.get("kind") not in (None, "rejected_input"):
                check("dump.kind", actual_dump.get("kind"), dump.get("kind"))
            # A non-x64 target may carry an AMD64 collector SystemInfo stream;
            # dmp-core now rejects proven WOW64 module sets before emitting an
            # inspect report, so this check is only for older/synthetic cases
            # that reach the comparison path.
            if dump.get("architecture") and treatment != "non_x64":
                check("dump.architecture", actual_process.get("architecture"), dump.get("architecture"))
            if "has_exception" in dump:
                check(
                    "dump.has_exception",
                    bool(inspect.get("exception")),
                    bool(dump.get("has_exception")),
                )

        wanted_exception = expected_exception(expected_doc)
        actual_exception = inspect.get("exception")
        if wanted_exception is None:
            if actual_exception is not None:
                fields.append({"path": "exception", "expected": None, "actual": actual_exception})
        else:
            if not isinstance(actual_exception, dict):
                fields.append({"path": "exception", "expected": wanted_exception, "actual": None})
            else:
                for name in ("code", "name", "access_type"):
                    if name in wanted_exception:
                        check(f"exception.{name}", actual_exception.get(name), wanted_exception[name], normalize="hex" if name == "code" else None)
                if "fault_address" in wanted_exception:
                    check(
                        "exception.fault_address",
                        actual_exception.get("fault_address"),
                        wanted_exception["fault_address"],
                        normalize="hex",
                    )

    target_module = find_target_module(canonical, artifact_details)
    target_status = target_module.get("status") if target_module else None
    actual_warnings = warning_codes(canonical)
    messages = warning_messages(canonical)
    symbols_available = symbolicator_target_symbols_available(raw_dir, artifact_details)
    if canonical is None:
        fields.append({"path": "canonical", "expected": "analysis result", "actual": None})
    else:
        crash = canonical.get("crash", {})
        if not isinstance(crash, dict):
            crash = {}
        if wanted_exception is not None:
            for name, canonical_name in (
                ("code", "exception_code"),
                ("name", "exception_name"),
                ("access_type", "access_type"),
            ):
                if name in wanted_exception:
                    check(
                        f"crash.{canonical_name}",
                        crash.get(canonical_name),
                        wanted_exception[name],
                        normalize="hex" if name == "code" else None,
                    )
        if wanted_exception is None:
            expected_type = "hang" if treatment == "explicit_hang" else "unknown"
            check("crash.type", crash.get("type"), expected_type)
        crashing = expected.get("crashing_thread")
        if isinstance(crashing, dict) and crashing.get("must_be_nonzero"):
            thread_id = crash.get("thread_id")
            if not isinstance(thread_id, int) or thread_id == 0:
                fields.append({"path": "crashing_thread.thread_id", "expected": "nonzero", "actual": thread_id})
            if "expected_id" in crashing:
                check("crashing_thread.thread_id", thread_id, crashing["expected_id"])

        if treatment == "non_x64":
            target_arch = str(artifact_details.get("architecture") or "").lower()
            if target_arch not in {"x86", "i386", "i686"}:
                fields.append({"path": "target.architecture", "expected": "x86", "actual": artifact_details.get("architecture")})

        wanted_status = {
            "complete": "matched",
            "missing_pdb": "missing_pdb",
            "wrong_pdb": "pdb_mismatch",
            "missing_pe": "missing_pe",
            "pe_mismatch": "pe_mismatch",
        }.get(treatment)
        if wanted_status:
            if target_module is None:
                fields.append({"path": "artifact_treatment", "expected": wanted_status, "actual": None})
            elif target_status != wanted_status:
                fields.append({"path": "artifact_treatment", "expected": wanted_status, "actual": target_status})

        wanted_frames = expected_frames(expected_doc)
        actual_inline_names: list[str] = []
        if wanted_frames:
            frames = crashing_frames(canonical)
            actual_names = [normalize_symbol(frame.get("function_normalized") or frame.get("function")) for frame in frames]
            actual_names = [name for name in actual_names if name]
            actual_inline_names = [
                name
                for frame in frames
                if frame.get("inline")
                for name in [normalize_symbol(frame.get("function_normalized") or frame.get("function"))]
                if name
            ]
            if treatment in {"missing_pdb", "wrong_pdb"}:
                # These treatments intentionally make target business symbols
                # ineligible. Keep the expected frame list as an explicit
                # non-applicability marker even if the gateway happened to
                # return a symbol response from another published build.
                not_applicable.append(
                    {
                        "path": "business_frames",
                        "reason": "not_applicable_due_to_expected_artifact_treatment",
                    }
                )
            elif not symbolicator_requested:
                not_evaluated.append({"path": "business_frames", "reason": "symbolicator_not_requested"})
            elif not symbolicator_completed(raw_dir):
                not_evaluated.append({"path": "business_frames", "reason": "symbolicator_not_completed"})
            elif not symbols_available:
                not_evaluated.append({"path": "business_frames", "reason": "target_symbols_unavailable"})
            else:
                missing = [name for name in wanted_frames if normalize_symbol(name) not in actual_names]
                if missing:
                    fields.append({"path": "business_frames", "expected": wanted_frames, "actual": actual_names, "missing": missing})

            if reference_inline_frames:
                if treatment in {"missing_pdb", "wrong_pdb"}:
                    not_applicable.append(
                        {
                            "path": "cdb_inline_business_frames",
                            "reason": "not_applicable_due_to_expected_artifact_treatment",
                        }
                    )
                elif not symbolicator_requested or not symbolicator_completed(raw_dir) or not symbols_available:
                    not_evaluated.append(
                        {
                            "path": "cdb_inline_business_frames",
                            "reason": "target_symbols_unavailable",
                        }
                    )
                else:
                    missing_inline = [
                        name
                        for name in reference_inline_frames
                        if normalize_symbol(name) not in actual_inline_names
                    ]
                    if missing_inline:
                        fields.append(
                            {
                                "path": "cdb_inline_business_frames",
                                "expected": reference_inline_frames,
                                "actual": actual_inline_names,
                                "missing": missing_inline,
                            }
                        )

    warning_requirements: list[dict[str, Any]] = []
    for warning in expected.get("warnings", []) if isinstance(expected.get("warnings"), list) else []:
        value = str(warning)
        satisfied = False
        if value in actual_warnings:
            satisfied = True
        elif value == "pdb_mismatch" and target_status == "pe_mismatch":
            # Artifact matching intentionally stops at PE identity mismatch;
            # the PDB secondary mismatch is therefore not observable without
            # weakening the exact-PE rule.  The primary rejection is recorded.
            satisfied = True
        elif value == "no_exception_stream" and inspect is not None and inspect.get("exception") is None:
            satisfied = True
        elif value == "declared_hang" and isinstance(canonical, dict) and canonical.get("crash", {}).get("type") == "hang":
            satisfied = True
        elif value == "unknown_no_exception" and isinstance(canonical, dict) and canonical.get("crash", {}).get("type") == "unknown":
            satisfied = True
        elif value == "missing_pe_unwind" and any("unwind" in message.lower() for message in messages):
            satisfied = True
        elif value == "unsupported_architecture" and str(artifact_details.get("architecture", "")).lower() in {"x86", "i386", "i686"}:
            satisfied = True
        elif value in {"corrupt_dump", "truncated_dump"} and rejection is not None:
            satisfied = True
        # Human prose in expected warnings is explanatory evidence, not an
        # engine warning code.  It must not make a valid run fail.
        elif " " in value and value not in {"no_exception_stream"}:
            satisfied = True
        requirement = {"warning": value, "satisfied": satisfied}
        warning_requirements.append(requirement)
        if not satisfied:
            not_evaluated.append({"path": "quality.warnings", "warning": value, "reason": "warning_not_observed"})

    return {
        "field_differences": fields,
        "not_evaluated": not_evaluated,
        "not_applicable": not_applicable,
        "warnings": warning_requirements,
        "target_module": target_module,
        "target_status": target_status,
        "symbolicator_completed": symbolicator_completed(raw_dir),
        "symbolicator_symbols_available": symbols_available,
        "reference_business_frames": reference_business_frames,
        "reference_inline_frames": reference_inline_frames,
        "actual_inline_business_frames": actual_inline_names if canonical is not None else [],
        "acceptable_rejection": False,
    }


def metric_observation(
    treatment: str,
    expected_doc: dict[str, Any],
    inspect: dict[str, Any] | None,
    canonical: dict[str, Any] | None,
    comparison: dict[str, Any],
    artifact_details: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    """Return per-fixture observations consumed by the corpus metrics."""

    expected_exception_doc = expected_exception(expected_doc)
    expected_code = normalize_hex(expected_exception_doc.get("code")) if expected_exception_doc else None
    actual_code = None
    actual_thread = None
    if isinstance(canonical, dict):
        crash = canonical.get("crash", {})
        if isinstance(crash, dict):
            actual_code = normalize_hex(crash.get("exception_code"))
            actual_thread = crash.get("thread_id")
    inspect_thread = None
    if isinstance(inspect, dict) and isinstance(inspect.get("exception"), dict):
        inspect_thread = inspect["exception"].get("thread_id")
    target_module = comparison.get("target_module")
    target_status = comparison.get("target_status")
    # Exception/thread metrics intentionally do not depend on Symbolicator
    # availability or informational frame differences.  They measure the
    # valid dump + exact artifact match path, which is still proven when a
    # completed gateway response says target symbols are missing.
    complete_eligible = (
        treatment == "complete"
        and inspect is not None
        and canonical is not None
        and target_status == "matched"
    )
    mismatch_expected = treatment in {"wrong_pdb", "pe_mismatch"}
    mismatch_detected = mismatch_expected and (
        target_status in {"pdb_mismatch", "pe_mismatch"}
        or "pdb_mismatch" in warning_codes(canonical)
        or "pe_mismatch" in warning_codes(canonical)
    )
    frames = crashing_frames(canonical)
    wrong_symbols = 0
    if mismatch_expected and target_status in {"pdb_mismatch", "pe_mismatch", "missing_pe"}:
        target_debug = normalize_id(artifact_details.get("debug_id"))
        target_basename = module_basename(target_module.get("code_file")) if target_module else None
        for frame in frames:
            frame_module = normalize_id(frame.get("module_debug_id"))
            has_symbol = bool(frame.get("function") or frame.get("file") or frame.get("line"))
            same_target_module = bool(
                (target_debug and frame_module == target_debug)
                or (target_basename and module_basename(frame.get("module")) == target_basename)
            )
            if frame.get("in_app") and has_symbol and same_target_module:
                wrong_symbols += 1

    return {
        "complete_match_eligible": complete_eligible,
        "exception_code_correct": complete_eligible and actual_code == expected_code,
        "crashing_thread_eligible": complete_eligible and isinstance(inspect_thread, int) and inspect_thread != 0,
        "crashing_thread_correct": complete_eligible and isinstance(inspect_thread, int) and actual_thread == inspect_thread,
        "pdb_mismatch_eligible": mismatch_expected and status in {"PASS", "INCOMPLETE", "FAIL"},
        "pdb_mismatch_detected": mismatch_detected,
        "top3_eligible": treatment == "complete" and canonical is not None and target_status == "matched" and comparison.get("symbolicator_symbols_available", False),
        "top3_correct": treatment == "complete" and canonical is not None and target_status == "matched" and comparison.get("symbolicator_symbols_available", False) and not any(
            item.get("path") == "business_frames" for item in comparison.get("field_differences", [])
        ),
        "silent_wrong_symbol_count": wrong_symbols,
    }


def run_fixture(
    fixture_name: str,
    fixtures_root: Path,
    output_root: Path,
    core: list[str],
    args: argparse.Namespace,
) -> dict[str, Any]:
    fixture_dir = fixtures_root / fixture_name
    fixture_output = safe_fixture_output(output_root, fixture_name)
    if fixture_output.exists():
        shutil.rmtree(fixture_output)
    fixture_output.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "fixture_id": fixture_name,
        "fixture_dir": str(fixture_dir),
        "output_dir": str(fixture_output),
        "status": "SKIP",
        "category": None,
        "treatment": None,
        "skip_reason": None,
        "paths": {},
        "comparison": {},
        "metrics": {},
    }

    fixture_path = fixture_dir / "fixture.json"
    expected_path = fixture_dir / "expected.json"
    if not fixture_path.is_file() or not expected_path.is_file():
        result["skip_reason"] = "fixture_contract_missing"
        result["paths"]["fixture"] = str(fixture_path)
        result["paths"]["expected"] = str(expected_path)
        return result
    try:
        fixture_doc = read_json(fixture_path)
        expected_doc = read_json(expected_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        result["status"] = "FAIL"
        result["skip_reason"] = f"fixture_contract_unreadable:{type(error).__name__}"
        return result

    write_json(fixture_output / "expected.json", expected_doc)
    result["paths"]["fixture"] = str(fixture_path)
    result["paths"]["expected"] = str(fixture_output / "expected.json")
    result["category"] = fixture_doc.get("category")
    result["treatment"] = expected_treatment(expected_doc)

    manifest, metadata, metadata_notes = load_manifest_and_metadata(fixture_dir, fixture_doc)
    dump_path = resolve_dump_path(fixture_dir, fixture_doc, manifest)
    match_input, artifact_details = build_artifact_spec(
        fixture_dir,
        fixture_doc,
        expected_doc.get("expected", {}),
        manifest,
        metadata,
        args.workspace_id,
    )
    result["artifact_details"] = artifact_details
    result["metadata_notes"] = metadata_notes
    result["paths"]["dump"] = str(dump_path) if dump_path else None
    if manifest is not None:
        write_json(fixture_output / "manifest.json", manifest)
        result["paths"]["manifest"] = str(fixture_output / "manifest.json")
    if match_input is not None:
        match_path = fixture_output / "match-input.json"
        write_json(match_path, match_input)
        result["paths"]["match_input"] = str(match_path)
    raw_dir = fixture_output / "raw"
    result["paths"]["raw_dir"] = str(raw_dir)
    if dump_path is None or not dump_path.is_file():
        result["skip_reason"] = "dump_missing"
        write_json(fixture_output / "diff.json", {"status": "SKIP", "reason": result["skip_reason"]})
        result["paths"]["diff"] = str(fixture_output / "diff.json")
        return result

    treatment = result["treatment"]
    invalid_dump = treatment in {"corrupt_dump", "truncated_dump"}
    # Complete/non-x64 samples need actual generated PE/PDB evidence.  The
    # deliberate D05 missing-* cases are handled by a null artifact field and
    # must continue to real matching instead.
    required_artifact_missing = False
    if treatment in {"complete", "non_x64", "explicit_hang", "unknown_no_exception"}:
        required_artifact_missing = not artifact_details.get("pe_exists", False) or not artifact_details.get("pdb_exists", False)
    if match_input is None and not invalid_dump and treatment != "authorized_real_no_local_artifacts":
        required_artifact_missing = True

    inspect_path = fixture_output / "inspect.json"
    inspect_command = core + ["inspect", "--dump", str(dump_path), "--output", str(inspect_path)]
    inspect_run = run_command(inspect_command, fixture_output, "inspect", args.timeout_seconds)
    result["execution"] = {"inspect": inspect_run}
    result["paths"]["inspect"] = str(inspect_path)
    inspect_doc: dict[str, Any] | None = None
    rejection: dict[str, Any] | None = None
    if inspect_run.get("returncode") == 0 and inspect_path.is_file():
        try:
            inspect_doc = read_json(inspect_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            result["status"] = "FAIL"
            result["skip_reason"] = f"inspect_output_unreadable:{type(error).__name__}"
    elif inspect_run.get("returncode") != 0 or inspect_run.get("timed_out"):
        rejection = inspect_run.get("error") or {"code": None, "message": "inspect failed"}
        write_json(raw_dir / "inspect-error.json", rejection)
        result["paths"]["inspect_error"] = str(raw_dir / "inspect-error.json")

    # Invalid inputs are meaningful real executions even though there is no
    # canonical output.  Do not invoke analyze after a rejected inspect.
    if rejection is not None:
        comparison = compare_result(
            expected_doc,
            None,
            None,
            rejection,
            artifact_details,
            raw_dir,
            bool(args.symbolicator),
            reference_path=fixture_dir / "reference" / "cdb-summary.txt",
        )
        result["comparison"] = comparison
        result["actual"] = {"rejection": rejection}
        result["status"] = "PASS" if comparison.get("acceptable_rejection") else "FAIL"
        diff = {
            "field_differences": comparison.get("field_differences", []),
            "not_evaluated": comparison.get("not_evaluated", []),
            "warnings": comparison.get("warnings", []),
        }
        write_json(fixture_output / "diff.json", diff)
        result["paths"]["diff"] = str(fixture_output / "diff.json")
        result["metrics"] = metric_observation(
            treatment,
            expected_doc,
            None,
            None,
            comparison,
            artifact_details,
            result["status"],
        )
        return result

    if inspect_doc is None:
        result["status"] = "FAIL"
        result["skip_reason"] = "inspect_failed_without_structured_rejection"
        return result

    if required_artifact_missing:
        # Keep the real inspect evidence, but do not pretend a canonical
        # artifact/symbol verdict exists without the generated artifact.
        result["status"] = "SKIP"
        result["skip_reason"] = "required_generated_artifact_missing"
        write_json(fixture_output / "diff.json", {"status": "SKIP", "reason": result["skip_reason"]})
        result["paths"]["diff"] = str(fixture_output / "diff.json")
        result["actual"] = {"inspect": inspect_doc}
        return result

    canonical_path = fixture_output / "canonical.json"
    analyze_command = core + [
        "analyze",
        "--dump",
        str(dump_path),
        "--inspect",
        str(inspect_path),
        "--workspace-id",
        args.workspace_id,
        "--symbolicator-version",
        args.symbolicator_version,
        "--core-image-digest",
        args.core_image_digest,
        "--output",
        str(canonical_path),
        "--raw-dir",
        str(raw_dir),
    ]
    if match_input is not None:
        analyze_command[4:4] = ["--match", str(fixture_output / "match-input.json")]
    if args.symbolicator:
        analyze_command += ["--symbolicator", args.symbolicator]
    if treatment == "explicit_hang":
        analyze_command += ["--capture-profile", "hang"]
    analyze_run = run_command(analyze_command, fixture_output, "analyze", args.timeout_seconds)
    result["execution"]["analyze"] = analyze_run
    result["paths"]["canonical"] = str(canonical_path)
    canonical_doc: dict[str, Any] | None = None
    if canonical_path.is_file():
        try:
            canonical_doc = read_json(canonical_path)
        except (OSError, ValueError, json.JSONDecodeError):
            canonical_doc = None
    if raw_dir.is_dir() and (raw_dir / "match.json").is_file():
        result["paths"]["match_report"] = str(raw_dir / "match.json")
    result["actual"] = {"inspect": inspect_doc, "canonical": canonical_doc}

    if analyze_run.get("returncode") != 0 or analyze_run.get("timed_out"):
        error = analyze_run.get("error") or {"code": None, "message": "analyze failed"}
        write_json(raw_dir / "analyze-error.json", error)
        result["paths"]["analyze_error"] = str(raw_dir / "analyze-error.json")
        if treatment == "non_x64" and error.get("code") in {"UNSUPPORTED_DUMP", "UNSUPPORTED_ARCHITECTURE"}:
            result["status"] = "PASS"
            result["skip_reason"] = "unsupported_non_x64_boundary"
        else:
            result["status"] = "FAIL"
            result["skip_reason"] = "analyze_failed"
        comparison = compare_result(
            expected_doc,
            inspect_doc,
            canonical_doc,
            None,
            artifact_details,
            raw_dir,
            bool(args.symbolicator),
            reference_path=fixture_dir / "reference" / "cdb-summary.txt",
        )
        comparison["analysis_error"] = error
        result["comparison"] = comparison
        write_json(fixture_output / "diff.json", comparison)
        result["paths"]["diff"] = str(fixture_output / "diff.json")
        result["metrics"] = metric_observation(
            treatment,
            expected_doc,
            inspect_doc,
            canonical_doc,
            comparison,
            artifact_details,
            result["status"],
        )
        return result

    comparison = compare_result(
        expected_doc,
        inspect_doc,
        canonical_doc,
        None,
        artifact_details,
        raw_dir,
        bool(args.symbolicator),
        reference_path=fixture_dir / "reference" / "cdb-summary.txt",
    )
    result["comparison"] = comparison
    fields = comparison.get("field_differences", [])
    not_evaluated = comparison.get("not_evaluated", [])
    if fields:
        result["status"] = "FAIL"
    elif not_evaluated:
        result["status"] = "INCOMPLETE"
        result["skip_reason"] = "evidence_not_evaluable"
    else:
        result["status"] = "PASS"
    write_json(fixture_output / "diff.json", comparison)
    result["paths"]["diff"] = str(fixture_output / "diff.json")
    result["metrics"] = metric_observation(
        treatment,
        expected_doc,
        inspect_doc,
        canonical_doc,
        comparison,
        artifact_details,
        result["status"],
    )
    return result


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def make_metric(
    name: str,
    observations: list[dict[str, Any]],
    eligible_key: str,
    correct_key: str,
    fixture_results: list[dict[str, Any]],
) -> dict[str, Any]:
    eligible_ids: list[str] = []
    skipped_ids: list[str] = []
    numerator = 0
    if eligible_key in {"complete_match_eligible", "crashing_thread_eligible", "top3_eligible"}:
        in_scope = {"complete"}
    elif eligible_key == "pdb_mismatch_eligible":
        in_scope = {"wrong_pdb", "pe_mismatch"}
    else:
        in_scope = set()
    for result, observation in zip(fixture_results, observations):
        if observation.get(eligible_key):
            eligible_ids.append(result["fixture_id"])
            if observation.get(correct_key):
                numerator += 1
        elif result.get("treatment") in in_scope and result.get("status") in {"SKIP", "INCOMPLETE"}:
            skipped_ids.append(result["fixture_id"])
    denominator = len(eligible_ids)
    return {
        "name": name,
        "numerator": numerator,
        "denominator": denominator,
        "rate": ratio(numerator, denominator),
        "status": "PASS" if denominator and numerator == denominator else ("FAIL" if denominator else "NO_VALID_SAMPLES"),
        "eligible_fixture_ids": eligible_ids,
        "skipped_fixture_ids": skipped_ids,
    }


def aggregate_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [result.get("metrics", {}) for result in results]
    exception = make_metric(
        "valid_complete_matched_exception_code_accuracy",
        observations,
        "complete_match_eligible",
        "exception_code_correct",
        results,
    )
    thread = make_metric(
        "crashing_thread_accuracy",
        observations,
        "crashing_thread_eligible",
        "crashing_thread_correct",
        results,
    )
    pdb = make_metric(
        "pdb_mismatch_detection_rate",
        observations,
        "pdb_mismatch_eligible",
        "pdb_mismatch_detected",
        results,
    )
    top3 = make_metric(
        "complete_symbol_sample_top3_business_frame_equivalence",
        observations,
        "top3_eligible",
        "top3_correct",
        results,
    )
    silent_wrong_symbols = sum(
        int(observation.get("silent_wrong_symbol_count", 0)) for observation in observations
    )
    return {
        exception["name"]: exception,
        thread["name"]: thread,
        pdb["name"]: pdb,
        top3["name"]: top3,
        "silent_wrong_symbol_count": {
            "count": silent_wrong_symbols,
            "status": "PASS" if silent_wrong_symbols == 0 else "FAIL",
            "scope": "wrong_pdb and pe_mismatch target frames with symbols despite non-matched artifact status",
        },
    }


def render_markdown(
    evidence: dict[str, Any],
    output_json: Path,
    output_md: Path,
) -> str:
    counts = evidence["counts"]
    lines = [
        "# Phase 0 Golden Runner Results",
        "",
        f"Status: **{evidence['status']}**  ",
        f"Generated: `{evidence['generated_at_utc']}`  ",
        f"Fixture index: `{evidence['fixture_index']}`  ",
        f"Core image digest supplied: `{evidence['arguments']['core_image_digest']}`  ",
        f"Symbolicator: `{evidence['arguments'].get('symbolicator') or 'not requested'}`; version `{evidence['arguments']['symbolicator_version']}`",
        "",
        "This report is execution evidence. `SKIP` and `INCOMPLETE` are not passing analyses; they are excluded from rate denominators.",
        "",
        "## Counts",
        "",
        f"`{json.dumps(counts, ensure_ascii=False)}`",
        "",
        "## Metrics",
        "",
        "| Metric | Numerator | Denominator | Rate | Status |",
        "|---|---:|---:|---:|---|",
    ]
    for name, metric in evidence["metrics"].items():
        if name == "silent_wrong_symbol_count":
            lines.append(f"| {name} | {metric['count']} | — | — | {metric['status']} |")
        else:
            rate = "—" if metric["rate"] is None else f"{metric['rate']:.4f}"
            lines.append(f"| {name} | {metric['numerator']} | {metric['denominator']} | {rate} | {metric['status']} |")
    lines.extend(
        [
            "",
            "## Fixture execution",
            "",
            "| Fixture | Category | Treatment | Status | Diff / skip reason |",
            "|---|---|---|---|---|",
        ]
    )
    for result in evidence["fixtures"]:
        reason = result.get("skip_reason") or ""
        diff_count = len(result.get("comparison", {}).get("field_differences", []))
        if diff_count:
            reason = f"{diff_count} field difference(s); {reason}".strip()
        lines.append(
            f"| `{result['fixture_id']}` | {result.get('category') or '—'} | {result.get('treatment') or '—'} | **{result['status']}** | {reason or '—'} |"
        )
    lines.extend(
        [
            "",
            "Each fixture directory under `target/phase0-golden` contains the copied `expected.json`, real `inspect.json` when inspect succeeded, `raw/` engine outputs, `canonical.json` when analyze produced one, and `diff.json`.",
            "",
            "## Limitations",
            "",
            "- Placeholder and non-golden entries from `fixtures/index.json` are excluded.",
            "- Missing generated binaries or dumps are recorded as `SKIP`; fixture metadata alone never contributes to a metric.",
            "- A top-three symbol equivalence rate requires a completed Symbolicator response. Without `--symbolicator`, those samples remain `INCOMPLETE`.",
            "- WOW64/x86 rejection is proven from the SysWOW64 ntdll plus WOW64 runtime module set when an AMD64 collector SystemInfo stream is present.",
            "- The runner does not claim production authorization for the synthetic fixture corpus.",
            "",
            f"Machine-readable evidence: `{output_json}`",
            f"This report: `{output_md}`",
        ]
    )
    return "\n".join(lines) + "\n"


def discover_fixtures(index_path: Path) -> tuple[Path, list[str], set[str], dict[str, Any]]:
    index = read_json(index_path)
    fixture_root_ref = index.get("fixture_directory", "fixtures")
    fixture_root = path_from_arg(fixture_root_ref, index_path.parent.parent if index_path.parent.name == "fixtures" else ROOT)
    entries = index.get("fixtures", [])
    names: list[str] = []
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, str):
                names.append(entry)
            elif isinstance(entry, dict) and isinstance(entry.get("fixture_id"), str):
                names.append(entry["fixture_id"])
    golden = index.get("golden", {})
    excluded = set(golden.get("exclude_from_golden", [])) if isinstance(golden, dict) else set()
    # Keep the index as the source of truth while de-duplicating concurrent
    # fixture-agent edits.
    names = list(dict.fromkeys(names))
    return fixture_root, names, excluded, index


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures-index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--fixture", action="append", help="limit a local run; repeatable")
    parser.add_argument("--core", help="path to dmp-core executable")
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MD)
    parser.add_argument("--symbolicator", default=os.environ.get("SYMBOLICATOR_URL"))
    parser.add_argument(
        "--version",
        "--symbolicator-version",
        dest="symbolicator_version",
        default=os.environ.get("SYMBOLICATOR_VERSION", "unknown"),
    )
    parser.add_argument("--workspace-id", default="wsp_p0test")
    parser.add_argument("--core-image-digest", required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=180, dest="timeout_seconds")
    args = parser.parse_args(argv)
    if not SHA256_DIGEST.fullmatch(args.core_image_digest):
        parser.error("--core-image-digest must match sha256:<64 lowercase hex chars> and must be supplied")
    if args.workers < 1:
        parser.error("--workers must be >= 1")
    if args.timeout_seconds < 1:
        parser.error("--timeout must be >= 1")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    index_path = path_from_arg(args.fixtures_index)
    output_root = path_from_arg(args.output_root)
    output_json = path_from_arg(args.output_json)
    output_md = path_from_arg(args.output_md)
    fixtures_root, names, excluded, index = discover_fixtures(index_path)
    requested = set(args.fixture or [])
    selected = [name for name in names if name not in excluded and (not requested or name in requested)]
    unknown_requested = sorted(requested - set(selected))
    core = core_command(args.core)

    results: list[dict[str, Any]] = []
    if unknown_requested:
        for name in unknown_requested:
            results.append(
                {
                    "fixture_id": name,
                    "status": "SKIP",
                    "skip_reason": "not_in_index_or_excluded",
                    "category": None,
                    "treatment": None,
                    "paths": {},
                    "comparison": {},
                    "metrics": {},
                }
            )

    def execute(name: str) -> dict[str, Any]:
        try:
            return run_fixture(name, fixtures_root, output_root, core, args)
        except Exception as error:  # noqa: BLE001 - preserve a per-fixture audit record
            try:
                fixture_output = safe_fixture_output(output_root, name)
            except RunnerFailure:
                fixture_output = None
            traceback_path = fixture_output / "runner-traceback.txt" if fixture_output else None
            if traceback_path is not None:
                fixture_output.mkdir(parents=True, exist_ok=True)
                write_text(traceback_path, traceback.format_exc())
            return {
                "fixture_id": name,
                "status": "FAIL",
                "skip_reason": f"runner_exception:{type(error).__name__}",
                "error": str(error),
                "category": None,
                "treatment": None,
                "paths": {"runner_traceback": str(traceback_path)} if traceback_path else {},
                "comparison": {},
                "metrics": {},
            }

    if args.workers == 1:
        results.extend(execute(name) for name in selected)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(execute, name): name for name in selected}
            unordered = [future.result() for future in concurrent.futures.as_completed(futures)]
            results.extend(sorted(unordered, key=lambda item: item.get("fixture_id", "")))

    # A deterministic index order makes evidence diffs useful even with
    # parallel execution.
    order = {name: index for index, name in enumerate(selected)}
    results.sort(key=lambda item: order.get(item.get("fixture_id", ""), len(order)))
    metrics = aggregate_metrics(results)
    counts: dict[str, int] = {}
    for result in results:
        status = str(result.get("status", "FAIL"))
        counts[status] = counts.get(status, 0) + 1
    required_metric_names = [
        "valid_complete_matched_exception_code_accuracy",
        "crashing_thread_accuracy",
        "pdb_mismatch_detection_rate",
        "complete_symbol_sample_top3_business_frame_equivalence",
    ]
    metric_complete = all(metrics[name].get("status") == "PASS" for name in required_metric_names)
    status = "PASS" if counts.get("FAIL", 0) == 0 and metric_complete and counts.get("INCOMPLETE", 0) == 0 and counts.get("SKIP", 0) == 0 else "INCOMPLETE"
    if counts.get("FAIL", 0):
        status = "FAIL"
    evidence = {
        "schema_version": "phase0-golden-results-v0.1",
        "status": status,
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fixture_index": str(index_path),
        "fixture_root": str(fixtures_root),
        "excluded_fixture_ids": sorted(excluded),
        "arguments": {
            "core": core,
            "core_image_digest": args.core_image_digest,
            "symbolicator": args.symbolicator,
            "symbolicator_version": args.symbolicator_version,
            "workspace_id": args.workspace_id,
            "workers": args.workers,
            "timeout_seconds": args.timeout_seconds,
        },
        "counts": counts,
        "metrics": metrics,
        "fixtures": results,
        "limitations": [
            "SKIP and INCOMPLETE fixtures are excluded from metric denominators.",
            "No fixture metadata is used as an analysis pass without a real dmp-core command.",
            "Symbolication metrics require a completed Symbolicator response.",
        ],
    }
    write_json(output_json, evidence)
    write_text(output_md, render_markdown(evidence, output_json, output_md))
    print(json.dumps({"status": status, "counts": counts, "metrics": metrics, "output_json": str(output_json), "output_md": str(output_md)}, indent=2, ensure_ascii=False))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
