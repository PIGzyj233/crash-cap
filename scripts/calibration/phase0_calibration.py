#!/usr/bin/env python3
"""Run the Phase 0 F03--F07 calibration probes.

The probes are intentionally read-only with respect to fixtures and the
existing Phase 0 runners.  Temporary match files, restored-artifact copies,
mock Symbolicator responses, and command output are created below the system
temporary directory.  Only the two explicit evidence files are written.

This is calibration evidence, not a replacement Golden runner. A controlled
cold-cache measurement is opt-in: the tool verifies the exact disposable
Phase 0 Docker volume labels before deleting and recreating that cache.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON = ROOT / "docs" / "evidence" / "phase0-calibration.json"
DEFAULT_MARKDOWN = ROOT / "docs" / "evidence" / "phase0-calibration.md"

P0_B01 = ROOT / "fixtures" / "p0-b01-null-read"
MISSING_PE = ROOT / "fixtures" / "p0-d05-missing-pe"
GOLDEN_PE = ROOT / "fixtures" / ".build" / "golden" / "golden_target_debug.exe"
MISSING_PE_PDB = MISSING_PE / "generated" / "target.pdb"
MISSING_PE_DUMP = MISSING_PE / "generated" / "dump.dmp"
CDB = ROOT / "scripts" / "symbolicator" / ".tools" / "windbg" / "x64-package" / "unpacked" / "amd64" / "cdb.exe"
CDB_COMMANDS = ROOT / "scripts" / "symbolicator" / "windbg" / "cdb-p0-b01.commands"
SYMBOLICATOR_URL = "http://127.0.0.1:3021"
SYMBOLICATOR_VOLUME = "crash-cap-symbolicator-p0_symbolicator-cache"
SYMBOLICATOR_PROJECT = "crash-cap-symbolicator-p0"
SYMBOLICATOR_COMPOSE = ROOT / "deploy" / "compose" / "symbolicator.yml"

NTDLL = {
    "code_id": "BA65E4A2266000",
    "debug_file": "ntdll.pdb",
    "debug_id": "1806222313d4104266a4820b86925e3b1",
    "image_addr": "0x7ffc8ad00000",
    "image_size": 2514944,
    "instruction_addr": "0x7ffc8adaad6a",
}
KERNELBASE = {
    "code_id": "CA32CD543FE000",
    "debug_file": "kernelbase.pdb",
    "debug_id": "d218ba2f1c9b5e12cc7223574b1b66981",
    "image_addr": "0x7ffc87f20000",
    "image_size": 4186112,
    "instruction_addr": "0x7ffc87f2ad00",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def command_text(argv: list[str]) -> str:
    return shlex.join(argv)


def tail(value: str, limit: int = 2400) -> str:
    value = value.strip()
    return value if len(value) <= limit else "..." + value[-limit:]


def run_command(
    argv: list[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 180,
    keep_full: bool = False,
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        result = {
            "command": command_text(argv),
            "exit_code": completed.returncode,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "stdout_tail": tail(completed.stdout),
            "stderr_tail": tail(completed.stderr),
        }
        if keep_full:
            result["_stdout_full"] = completed.stdout
            result["_stderr_full"] = completed.stderr
        return result
    except subprocess.TimeoutExpired as error:
        return {
            "command": command_text(argv),
            "exit_code": None,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "stdout_tail": tail(str(error.stdout or "")),
            "stderr_tail": tail(str(error.stderr or "")),
            "timed_out": True,
        }
    except OSError as error:
        return {
            "command": command_text(argv),
            "exit_code": 127,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            "stdout_tail": "",
            "stderr_tail": f"{type(error).__name__}: {error}",
        }


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text, 16) if text.lower().startswith("0x") else int(text, 16)
        except ValueError:
            return None
    return None


def basename(value: str | None) -> str:
    if not value:
        return ""
    return re.split(r"[\\/]", value)[-1].lower()


def core_executable() -> Path | None:
    for candidate in (ROOT / "target" / "release" / "dmp-core.exe", ROOT / "target" / "debug" / "dmp-core.exe"):
        if candidate.is_file():
            return candidate
    return None


def metadata_for(directory: Path) -> dict[str, Any]:
    for filename in ("base-pe-metadata.json", "pe-metadata.json"):
        candidate = directory / "generated" / filename
        if candidate.is_file():
            return read_json(candidate)
    raise FileNotFoundError(f"no PE metadata under {directory / 'generated'}")


def make_match_input(
    *,
    metadata: dict[str, Any],
    pe_path: Path | None,
    pdb_path: Path | None,
    workspace_id: str,
    build_id: str,
) -> dict[str, Any]:
    module = {
        "artifact_id": f"art_{build_id}_target",
        "code_file": "golden_target_debug.exe",
        "debug_file": "golden_target_debug.pdb",
        "pe_path": str(pe_path) if pe_path else None,
        "pdb_path": str(pdb_path) if pdb_path else None,
        "code_id": metadata["code_id"],
        "debug_id": metadata["debug_id"],
        "role": "entrypoint",
        "in_app": True,
        "build_id": build_id,
    }
    return {
        "workspace_id": workspace_id,
        "modules": [module],
        "builds": [
            {
                "build_id": build_id,
                "modules": [
                    {
                        "code_id": metadata["code_id"],
                        "debug_id": metadata["debug_id"],
                        "role": "entrypoint",
                    }
                ],
            }
        ],
    }


def run_analysis(
    *,
    temp_root: Path,
    core: Path,
    dump: Path,
    metadata: dict[str, Any],
    pe_path: Path | None,
    pdb_path: Path | None,
    label: str,
    core_image_digest: str,
    symbolicator: str | None = None,
    workspace_id: str = "wsp_p0calibration",
) -> dict[str, Any]:
    match_path = temp_root / f"{label}-match.json"
    output_path = temp_root / f"{label}.json"
    raw_path = temp_root / f"{label}-raw"
    match_path.write_text(
        json.dumps(
            make_match_input(
                metadata=metadata,
                pe_path=pe_path,
                pdb_path=pdb_path,
                workspace_id=workspace_id,
                build_id=f"bld_{label}",
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    command = [
        str(core),
        "analyze",
        "--dump",
        str(dump),
        "--match",
        str(match_path),
        "--workspace-id",
        workspace_id,
        "--core-image-digest",
        core_image_digest,
        "--output",
        str(output_path),
        "--raw-dir",
        str(raw_path),
    ]
    if symbolicator:
        command.extend(["--symbolicator", symbolicator])
    command_result = run_command(command, timeout=240)
    parsed = None
    if output_path.is_file():
        try:
            parsed = read_json(output_path)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            parsed = None
    return {"label": label, "command": command_result, "canonical": parsed}


def frame_summary(canonical: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(canonical, dict):
        return {"frame_count": 0, "in_app_count": 0, "named_in_app": [], "trust_histogram": {}, "quality": None}
    threads = canonical.get("threads") or []
    frames = threads[0].get("frames", []) if threads and isinstance(threads[0], dict) else []
    app_frames = [frame for frame in frames if frame.get("in_app")]
    named = [frame.get("function_normalized") or frame.get("function") for frame in app_frames]
    return {
        "frame_count": len(frames),
        "in_app_count": len(app_frames),
        "named_in_app": [value for value in named if value],
        "trust_histogram": dict(Counter(frame.get("trust", "unknown") for frame in frames)),
        "scan_in_app_count": sum(frame.get("in_app") and frame.get("trust") == "scan" for frame in frames),
        "quality": canonical.get("quality"),
        "warning_codes": [warning.get("code") for warning in (canonical.get("quality", {}).get("warnings", []))],
    }


def run_cdb(temp_root: Path, dump: Path) -> dict[str, Any]:
    if not CDB.is_file() or not CDB_COMMANDS.is_file() or not GOLDEN_PE.is_file() or not MISSING_PE_PDB.is_file():
        return {
            "status": "SKIP",
            "reason": "portable CDB, restored PE, matching PDB, or command file unavailable",
        }
    symbols = temp_root / "cdb-symbols"
    symbols.mkdir(parents=True, exist_ok=True)
    shutil.copy2(GOLDEN_PE, symbols / "golden_target_debug.exe")
    shutil.copy2(MISSING_PE_PDB, symbols / "golden_target_debug.pdb")
    result = run_command(
        [
            str(CDB),
            "-z",
            str(dump),
            "-y",
            str(symbols),
            "-lines",
            "-cf",
            str(CDB_COMMANDS),
        ],
        cwd=CDB.parent,
        timeout=180,
        keep_full=True,
    )
    text = result.pop("_stdout_full", "")
    result.pop("_stderr_full", None)
    # Parse the full CDB output, but preserve only names and a bounded output
    # tail in the evidence so machine-specific paths do not bloat the report.
    matches = re.findall(r"golden_target_debug!([^+\s\[]+)", text)
    business: list[str] = []
    for name in matches:
        if name in {"invoke_main", "__scrt_common_main_seh"} or name.startswith("__"):
            continue
        if name not in business:
            business.append(name)
    return {
        "status": "PASS" if result.get("exit_code") == 0 else "FAIL",
        "command": result,
        "business_functions": business,
        "boundary": "CDB uses restored PE/PDB copies in a temporary symbol directory; OS symbols remain WRONG_SYMBOLS in this local run.",
    }


def calibrate_f03(temp_root: Path, core: Path | None, core_image_digest: str) -> dict[str, Any]:
    if core is None:
        return {"status": "SKIP", "reason": "dmp-core release/debug executable is unavailable"}
    if not MISSING_PE_DUMP.is_file() or not GOLDEN_PE.is_file() or not MISSING_PE_PDB.is_file():
        return {"status": "SKIP", "reason": "same-dump restored-PE inputs are unavailable"}
    metadata = metadata_for(MISSING_PE)
    restored = run_analysis(
        temp_root=temp_root,
        core=core,
        dump=MISSING_PE_DUMP,
        metadata=metadata,
        pe_path=GOLDEN_PE,
        pdb_path=MISSING_PE_PDB,
        label="f03-restored-pe",
        core_image_digest=core_image_digest,
    )
    missing = run_analysis(
        temp_root=temp_root,
        core=core,
        dump=MISSING_PE_DUMP,
        metadata=metadata,
        pe_path=None,
        pdb_path=MISSING_PE_PDB,
        label="f03-missing-pe",
        core_image_digest=core_image_digest,
    )
    cdb = run_cdb(temp_root, MISSING_PE_DUMP)
    restored_summary = frame_summary(restored.get("canonical"))
    missing_summary = frame_summary(missing.get("canonical"))
    cdb_business = cdb.get("business_functions", [])
    missing_named = set(missing_summary.get("named_in_app", []))
    lost = [name for name in cdb_business if name not in missing_named]
    restored_quality = (restored_summary.get("quality") or {}).get("score")
    missing_quality = (missing_summary.get("quality") or {}).get("score")
    quality_delta = None
    quality_drop_ratio = None
    if isinstance(restored_quality, (int, float)) and isinstance(missing_quality, (int, float)):
        quality_delta = missing_quality - restored_quality
        quality_drop_ratio = (restored_quality - missing_quality) / restored_quality if restored_quality else None
    prerequisites = (
        restored["command"].get("exit_code") == 0
        and missing["command"].get("exit_code") == 0
        and cdb.get("status") == "PASS"
        and "missing_pe_unwind" in missing_summary.get("warning_codes", [])
    )
    return {
        "status": "PASS" if prerequisites else "FAIL",
        "decision": "retain missing_pe and missing_pe_unwind as PARTIAL evidence; do not fail the valid dump, do not construct Exact",
        "inputs": {
            "dump": str(MISSING_PE_DUMP),
            "restored_pe": str(GOLDEN_PE),
            "matching_pdb": str(MISSING_PE_PDB),
            "same_dump_for_both_runs": True,
        },
        "cdb": cdb,
        "restored_pe": {"command": restored["command"], "summary": restored_summary},
        "missing_pe": {"command": missing["command"], "summary": missing_summary},
        "comparison": {
            "cdb_business_frame_count": len(cdb_business),
            "cdb_business_functions": cdb_business,
            "missing_pe_business_functions_recovered": sorted(missing_named),
            "business_frames_lost_vs_cdb": lost,
            "business_frame_loss_count": len(lost),
            "business_frame_loss_rate": (len(lost) / len(cdb_business)) if cdb_business else None,
            "restored_frame_count": restored_summary["frame_count"],
            "missing_pe_frame_count": missing_summary["frame_count"],
            "restored_in_app_count": restored_summary["in_app_count"],
            "missing_pe_in_app_count": missing_summary["in_app_count"],
            "missing_pe_scan_in_app_count": missing_summary["scan_in_app_count"],
            "quality_score_delta_missing_minus_restored": quality_delta,
            "quality_drop_ratio": quality_drop_ratio,
        },
        "boundary": "CDB was run with temporary restored artifacts on the exact missing-PE dump; this is synthetic local MSVC evidence, not a production dump.",
    }


def model_quality(frames: list[dict[str, Any]], modules: list[dict[str, Any]]) -> dict[str, Any]:
    app_frames = [frame for frame in frames if frame.get("in_app") and frame.get("module")]
    symbolized = sum(bool(frame.get("function") or frame.get("file") or frame.get("line")) for frame in app_frames)
    warnings: list[str] = []
    if app_frames:
        symbol_coverage = symbolized / len(app_frames)
    else:
        symbol_coverage = 0.0
        warnings.append("symbol_coverage denominator is zero")
    if frames:
        trust_values = {"context": 1.0, "cfi": 1.0, "frame_pointer": 0.75, "scan": 0.20}
        unwind = sum(trust_values.get(frame.get("trust"), 0.0) for frame in frames) / len(frames)
    else:
        unwind = 0.0
        warnings.append("unwind_reliability denominator is zero")
    if any(frame.get("trust") == "scan" for frame in frames):
        warnings.append("scan_frames")
    app_modules = [module for module in modules if module.get("in_app")]
    matched = sum(module.get("status") == "matched" for module in app_modules)
    if app_modules:
        completeness = matched / len(app_modules)
    else:
        completeness = 0.0
        warnings.append("artifact_completeness denominator is zero")
    return {
        "symbol_coverage": symbol_coverage,
        "unwind_reliability": unwind,
        "artifact_completeness": completeness,
        "score": 0.45 * symbol_coverage + 0.35 * unwind + 0.20 * completeness,
        "warnings": warnings,
    }


def calibrate_f04() -> dict[str, Any]:
    app_matched = {"module": "app.exe", "in_app": True, "status": "matched"}
    system_pending = {"module": "ntdll.dll", "in_app": False, "status": "system_symbol_pending"}
    cases = {
        "many_system_cfi": {
            "frames": [{"module": "app.exe", "in_app": True, "trust": "context", "function": "app::crash"}]
            + [{"module": "ntdll.dll", "in_app": False, "trust": "cfi"} for _ in range(128)],
            "modules": [app_matched, system_pending],
            "expected": {"symbol_coverage": 1.0, "unwind_reliability": 1.0, "artifact_completeness": 1.0},
        },
        "many_system_scan": {
            "frames": [{"module": "app.exe", "in_app": True, "trust": "context", "function": "app::crash"}]
            + [{"module": "ntdll.dll", "in_app": False, "trust": "scan"} for _ in range(128)],
            "modules": [app_matched, system_pending],
            "expected": {"symbol_coverage": 1.0, "artifact_completeness": 1.0},
        },
        "no_in_app_system_only": {
            "frames": [{"module": "ntdll.dll", "in_app": False, "trust": "cfi"} for _ in range(16)],
            "modules": [system_pending],
            "expected": {"symbol_coverage": 0.0, "unwind_reliability": 1.0, "artifact_completeness": 0.0, "score": 0.35},
        },
        "all_denominators_zero": {
            "frames": [],
            "modules": [],
            "expected": {"symbol_coverage": 0.0, "unwind_reliability": 0.0, "artifact_completeness": 0.0, "score": 0.0},
        },
    }
    evaluated: dict[str, Any] = {}
    all_match = True
    for name, case in cases.items():
        observed = model_quality(case["frames"], case["modules"])
        expected = case["expected"]
        matches = all(math.isclose(observed[key], value, rel_tol=1e-12, abs_tol=1e-12) for key, value in expected.items())
        all_match = all_match and matches
        evaluated[name] = {
            "frame_count": len(case["frames"]),
            "observed": observed,
            "expected_subset": expected,
            "matches_contract": matches,
        }
    actual_p0b01 = None
    canonical = ROOT / "target" / "phase0-golden" / "p0-b01-null-read" / "canonical.json"
    if canonical.is_file():
        value = read_json(canonical)
        actual_p0b01 = {"quality": value.get("quality"), "source": str(canonical)}
    return {
        "status": "PASS" if all_match and actual_p0b01 is not None else "FAIL",
        "decision": "freeze 0.45/0.35/0.20 for stable v1 based on the Golden gate and deterministic denominator boundary matrices; keep denominator warnings visible",
        "weights": {"symbol_coverage": 0.45, "unwind_reliability": 0.35, "artifact_completeness": 0.20},
        "cases": evaluated,
        "actual_complete_p0_b01": actual_p0b01,
        "boundary": "The many-system-frame cases are deterministic contract probes, not a claim about production frame distributions. System-only evidence scores 0.35 because unwind is strong while app/artifact denominators are zero; warnings are mandatory.",
    }


def validate_alignment(unwind_frames: list[dict[str, Any]], response_frames: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = 0
    rejected: list[dict[str, Any]] = []
    mappings: list[dict[str, Any]] = []
    for position, response in enumerate(response_frames):
        index = response.get("original_index", position)
        index = int(index) if isinstance(index, (int, float)) or str(index).isdigit() else -1
        requested = unwind_frames[index] if 0 <= index < len(unwind_frames) else None
        response_address = parse_int(response.get("instruction_addr"))
        requested_address = parse_int(requested.get("instruction")) if requested else None
        requested_module = ((requested or {}).get("module") or {}).get("code_file")
        response_module = response.get("package") or response.get("module") or response.get("code_file")
        address_ok = (
            response_address is not None
            and requested_address is not None
            and (response_address == requested_address or response_address + 1 == requested_address)
        )
        module_ok = not response_module or basename(response_module) == basename(requested_module)
        valid = requested is not None and address_ok and module_ok
        mapping = {
            "response_position": position,
            "original_index": index,
            "response_address": response_address,
            "requested_address": requested_address,
            "response_module": basename(response_module),
            "requested_module": basename(requested_module),
            "address_delta": abs(response_address - requested_address) if response_address is not None and requested_address is not None else None,
            "address_ok": address_ok,
            "module_ok": module_ok,
            "accepted": valid,
        }
        mappings.append(mapping)
        if valid:
            accepted += 1
        else:
            rejected.append(mapping)
    return {"accepted": accepted, "rejected": len(rejected), "rejected_mappings": rejected, "mappings": mappings}


def mock_core_symbolication(
    *,
    temp_root: Path,
    core: Path,
    core_image_digest: str,
    wrong_index: bool,
) -> dict[str, Any]:
    raw_unwind_path = ROOT / "target" / "phase0-golden" / "p0-b01-null-read" / "raw" / "minidump.json"
    raw_symbol_path = ROOT / "target" / "phase0-golden" / "p0-b01-null-read" / "raw" / "symbolicator.json"
    if not raw_unwind_path.is_file() or not raw_symbol_path.is_file():
        return {"status": "SKIP", "reason": "p0-b01 raw unwind/Symbolicator evidence unavailable"}
    unwind = read_json(raw_unwind_path)
    original = read_json(raw_symbol_path)["final_response"]["stacktraces"][0]["frames"]
    response_frames: list[dict[str, Any]] = []
    for position, source in enumerate(original[:2]):
        frame = copy.deepcopy(source)
        frame["function"] = f"calibration::physical_{position}"
        frame["filename"] = "calibration.cpp"
        frame["lineno"] = 100 + position
        if wrong_index and position == 0:
            frame["original_index"] = 1
        response_frames.append(frame)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            body = json.dumps({"status": "completed", "stacktraces": [{"frames": response_frames}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: Any) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        metadata = metadata_for(P0_B01)
        dump = P0_B01 / "generated" / "null-read.dmp"
        pe = P0_B01 / "generated" / "null_read_target.exe"
        pdb = P0_B01 / "generated" / "null_read_target.pdb"
        result = run_analysis(
            temp_root=temp_root,
            core=core,
            dump=dump,
            metadata=metadata,
            pe_path=pe,
            pdb_path=pdb,
            label="f05-mock-wrong" if wrong_index else "f05-mock-correct",
            core_image_digest=core_image_digest,
            symbolicator=f"http://127.0.0.1:{server.server_address[1]}",
        )
        canonical = result.get("canonical") or {}
        frames = (canonical.get("threads") or [{}])[0].get("frames", [])
        tagged = [
            {"index": frame.get("index"), "function": frame.get("function"), "instruction_addr": frame.get("instruction_addr")}
            for frame in frames
            if isinstance(frame.get("function"), str) and frame["function"].startswith("calibration::")
        ]
        expected_functions = {f"calibration::physical_{index}": index for index in range(2)}
        wrong_fill = 0
        missing_tag = 0
        for function, expected_index in expected_functions.items():
            matching = [frame for frame in frames if frame.get("function") == function]
            if not matching:
                # A provenance-rejected response is intentionally absent from
                # Canonical.  Absence is not a wrong physical-frame fill; only
                # an accepted symbol attached to another physical index is.
                missing_tag += 1
            elif any(frame.get("index") != expected_index for frame in matching):
                wrong_fill += 1
        return {
            "status": "PASS" if result["command"].get("exit_code") == 0 else "FAIL",
            "wrong_index_injected": wrong_index,
            "command": result["command"],
            "tagged_canonical_frames": tagged,
            "wrong_physical_frame_fills": wrong_fill,
            "provenance_rejected_symbol_count": missing_tag,
            "quality_warning_codes": [
                warning.get("code")
                for warning in (canonical.get("quality", {}).get("warnings", []) or [])
                if isinstance(warning, dict)
            ],
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def calibrate_f05(temp_root: Path, core: Path | None, core_image_digest: str) -> dict[str, Any]:
    raw_unwind_path = ROOT / "target" / "phase0-golden" / "p0-b01-null-read" / "raw" / "minidump.json"
    raw_symbol_path = ROOT / "target" / "phase0-golden" / "p0-b01-null-read" / "raw" / "symbolicator.json"
    if core is None or not raw_unwind_path.is_file() or not raw_symbol_path.is_file():
        return {"status": "SKIP", "reason": "Core or p0-b01 raw evidence unavailable"}
    unwind = read_json(raw_unwind_path)
    raw_symbol = read_json(raw_symbol_path)
    unwind_frames = unwind["threads"][0]["frames"]
    response_frames = raw_symbol["final_response"]["stacktraces"][0]["frames"]
    actual = validate_alignment(unwind_frames, response_frames)
    mutated = copy.deepcopy(response_frames)
    if mutated:
        mutated[0]["original_index"] = 1
    mutation_check = validate_alignment(unwind_frames, mutated)
    correct_mock = mock_core_symbolication(
        temp_root=temp_root,
        core=core,
        core_image_digest=core_image_digest,
        wrong_index=False,
    )
    wrong_mock = mock_core_symbolication(
        temp_root=temp_root,
        core=core,
        core_image_digest=core_image_digest,
        wrong_index=True,
    )
    core_wrong_fills = wrong_mock.get("wrong_physical_frame_fills", 0)
    prerequisites = (
        actual["rejected"] == 0
        and actual["accepted"] == len(response_frames)
        and mutation_check["rejected"] >= 1
        and correct_mock.get("status") == "PASS"
        and wrong_mock.get("status") == "PASS"
    )
    # Exercise the current Core implementation as well as the independent
    # alignment model so a regression cannot hide behind the calibration code.
    status = "PASS" if prerequisites and core_wrong_fills == 0 else "FAIL"
    return {
        "status": status,
        "decision": "Accept symbol merge only when original_index, address, and module provenance are consistent; rejected mappings remain counted quality warnings and never fill another physical frame",
        "raw_sources": {"unwind": str(raw_unwind_path), "symbolicator": str(raw_symbol_path)},
        "actual_raw_alignment": actual,
        "mutated_alignment_validator": {
            "mutation": "first response frame original_index changed from 0 to 1 while address/module remained unchanged",
            "rejected_mappings": mutation_check["rejected"],
            "accepted_mappings": mutation_check["accepted"],
            "validator_rejects_wrong_physical_mapping": mutation_check["rejected"] >= 1,
        },
        "core_mock_probe": {
            "correct": correct_mock,
            "wrong_original_index": wrong_mock,
            "wrong_physical_frame_fills": core_wrong_fills,
            "required_zero": True,
        },
        "boundary": "The real p0-b01 response uses original_index and has one observed return-address adjustment where response_addr=request_addr-1. Both the validator and Core accept only exact equality or that direction. The mock verifies the current Core behavior, not merely a Python-side validator.",
    }


def exact_fingerprint(workspace: str, exception_code: str, access_type: str, fault_debug_id: str, function: str, relative: int) -> str:
    bucket = relative & ~0xF
    payload = f"{workspace}\n{exception_code}\n{access_type}\n{fault_debug_id}\n{fault_debug_id}\n{function}\n0x{bucket:x}"
    return hashlib.sha256(payload.encode()).hexdigest()


def calibrate_f06() -> dict[str, Any]:
    same_bucket = [0x1320, 0x1321, 0x132F]
    cross_bucket = [0x1320, 0x1330]
    same_hashes = [exact_fingerprint("wsp_p0calibration", "0xC0000005", "read", "DBG", "app::crash", value) for value in same_bucket]
    cross_hashes = [exact_fingerprint("wsp_p0calibration", "0xC0000005", "read", "DBG", "app::crash", value) for value in cross_bucket]
    repeat_hash = exact_fingerprint("wsp_p0calibration", "0xC0000005", "read", "DBG", "app::crash", 0x1327)
    repeat_hash_again = exact_fingerprint("wsp_p0calibration", "0xC0000005", "read", "DBG", "app::crash", 0x1327)
    generated = [exact_fingerprint("wsp_p0calibration", "0xC0000005", "read", "DBG", "app::crash", 0x1000 + index * 0x10) for index in range(2048)]
    collision_count = len(generated) - len(set(generated))
    canonical_path = ROOT / "target" / "phase0-golden" / "p0-b01-null-read" / "canonical.json"
    actual = None
    if canonical_path.is_file():
        value = read_json(canonical_path)
        actual = {"algorithm": value.get("fingerprints", {}).get("algorithm"), "exact_present": bool(value.get("fingerprints", {}).get("exact"))}
    same_ok = len(set(same_hashes)) == 1
    cross_ok = cross_hashes[0] != cross_hashes[1]
    deterministic_ok = repeat_hash == repeat_hash_again
    return {
        "status": (
            "PASS"
            if same_ok
            and cross_ok
            and deterministic_ok
            and collision_count == 0
            and actual == {"algorithm": "exact-v1.0", "exact_present": True}
            else "FAIL"
        ),
        "decision": "freeze exact-v1.0 with a 16-byte relative-address bucket for stable v1; do not infer zero theoretical or semantic collisions from this sample",
        "bucket_mask": "relative_addr & ~0xF",
        "same_bucket": {"relative_addresses": [hex(value) for value in same_bucket], "same_hash": same_ok, "hash": same_hashes[0]},
        "cross_bucket": {"relative_addresses": [hex(value) for value in cross_bucket], "different_hash": cross_ok, "hashes": cross_hashes},
        "deterministic_repeat": deterministic_ok,
        "generated_cross_bucket_count": len(generated),
        "observed_sha256_collision_count": collision_count,
        "actual_p0_b01": actual,
        "boundary": "Same-bucket addresses intentionally coalesce; adjacent buckets intentionally split. This is a deterministic calibration matrix, not a proof against semantic collisions from identical normalized functions across unrelated code paths.",
    }


def http_json(url: str, payload: dict[str, Any], timeout: int = 320) -> dict[str, Any]:
    started = time.perf_counter()
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
        parsed = json.loads(raw) if raw else None
        return {"status": status, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "json": parsed, "error": None}
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            parsed = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            parsed = None
        return {"status": error.code, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "json": parsed, "error": None}
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        return {"status": None, "duration_ms": round((time.perf_counter() - started) * 1000, 2), "json": None, "error": f"{type(error).__name__}: {error}"}


def public_payload(module: dict[str, Any]) -> dict[str, Any]:
    return {
        "platform": "native",
        "modules": [
            {
                "arch": "x86_64",
                "code_id": module["code_id"],
                "debug_file": module["debug_file"],
                "debug_id": module["debug_id"],
                "image_addr": module["image_addr"],
                "image_size": module["image_size"],
                "type": "pe",
            }
        ],
        "stacktraces": [{"frames": [{"instruction_addr": module["instruction_addr"]}]}],
    }


def summarize_public_response(result: dict[str, Any]) -> dict[str, Any]:
    value = result.get("json") if isinstance(result.get("json"), dict) else {}
    module = (value.get("modules") or [{}])[0]
    frame = ((value.get("stacktraces") or [{}])[0].get("frames") or [{}])[0]
    debug_status = module.get("debug_status")
    frame_status = frame.get("status")
    if result.get("status") == 200 and value.get("status") == "completed" and debug_status == "found" and frame_status == "symbolicated":
        classification = "success"
    elif result.get("status") == 200 and debug_status in {"missing", "unused"}:
        classification = "public_symbol_not_found"
    elif result.get("error"):
        classification = "network_failure"
    else:
        classification = "symbolicator_error"
    return {
        "http_status": result.get("status"),
        "duration_ms": result.get("duration_ms"),
        "symbolicator_status": value.get("status"),
        "debug_status": debug_status,
        "frame_status": frame_status,
        "function": frame.get("function"),
        "classification": classification,
        "error": result.get("error"),
    }


def wait_for_symbolicator_health(symbolicator_url: str, timeout_seconds: int = 90) -> dict[str, Any]:
    started = time.perf_counter()
    attempts = 0
    last_error: str | None = None
    while time.perf_counter() - started < timeout_seconds:
        attempts += 1
        try:
            with urllib.request.urlopen(f"{symbolicator_url}/healthcheck", timeout=5) as response:
                body = response.read().decode("utf-8", errors="replace")
                if response.status == 200 and body.strip() == "ok":
                    return {
                        "status": "PASS",
                        "attempts": attempts,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        "http_status": response.status,
                        "body": body.strip(),
                    }
                last_error = f"HTTP {response.status}: {body[:200]}"
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = f"{type(error).__name__}: {error}"
        time.sleep(1)
    return {
        "status": "FAIL",
        "attempts": attempts,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "error": last_error or "health timeout",
    }


def reset_symbolicator_cache(symbolicator_url: str, enabled: bool) -> dict[str, Any]:
    """Reset only the reviewed disposable Phase 0 Symbolicator cache volume."""

    if not enabled:
        return {
            "status": "NOT_REQUESTED",
            "volume": SYMBOLICATOR_VOLUME,
            "reason": "Pass --reset-symbolicator-cache to collect controlled cold/hot evidence.",
        }

    inspect_before = run_command(
        ["docker", "volume", "inspect", SYMBOLICATOR_VOLUME, "--format", "{{json .}}"],
        timeout=30,
        keep_full=True,
    )
    raw_before = inspect_before.pop("_stdout_full", "").strip()
    inspect_before.pop("_stderr_full", None)
    try:
        before = json.loads(raw_before)
    except json.JSONDecodeError:
        before = None
    labels = before.get("Labels", {}) if isinstance(before, dict) else {}
    expected_labels = {
        "com.docker.compose.project": SYMBOLICATOR_PROJECT,
        "com.docker.compose.volume": "symbolicator-cache",
    }
    label_check = inspect_before.get("exit_code") == 0 and all(labels.get(key) == value for key, value in expected_labels.items())
    if not label_check:
        return {
            "status": "FAIL",
            "volume": SYMBOLICATOR_VOLUME,
            "expected_labels": expected_labels,
            "actual_labels": labels,
            "inspect_before": inspect_before,
            "reason": "Refused cache deletion because the exact volume labels were not verified.",
        }

    compose = [
        "docker",
        "compose",
        "-p",
        SYMBOLICATOR_PROJECT,
        "-f",
        str(SYMBOLICATOR_COMPOSE),
    ]
    down = run_command([*compose, "down"], timeout=120)
    remove = (
        run_command(["docker", "volume", "rm", SYMBOLICATOR_VOLUME], timeout=30)
        if down.get("exit_code") == 0
        else {"command": "not run", "exit_code": None, "reason": "compose down failed"}
    )
    up = (
        run_command([*compose, "up", "-d", "--build"], timeout=240)
        if remove.get("exit_code") == 0
        else {"command": "not run", "exit_code": None, "reason": "volume removal failed"}
    )
    health = (
        wait_for_symbolicator_health(symbolicator_url)
        if up.get("exit_code") == 0
        else {"status": "FAIL", "reason": "compose up failed"}
    )
    inspect_after = run_command(
        ["docker", "volume", "inspect", SYMBOLICATOR_VOLUME, "--format", "{{json .}}"],
        timeout=30,
        keep_full=True,
    )
    raw_after = inspect_after.pop("_stdout_full", "").strip()
    inspect_after.pop("_stderr_full", None)
    try:
        after = json.loads(raw_after)
    except json.JSONDecodeError:
        after = None
    after_labels = after.get("Labels", {}) if isinstance(after, dict) else {}
    recreated = (
        inspect_after.get("exit_code") == 0
        and all(after_labels.get(key) == value for key, value in expected_labels.items())
        and before.get("CreatedAt") != after.get("CreatedAt")
        if isinstance(before, dict) and isinstance(after, dict)
        else False
    )
    passed = (
        down.get("exit_code") == 0
        and remove.get("exit_code") == 0
        and up.get("exit_code") == 0
        and health.get("status") == "PASS"
        and recreated
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "volume": SYMBOLICATOR_VOLUME,
        "expected_labels": expected_labels,
        "actual_labels_before": labels,
        "actual_labels_after": after_labels,
        "created_at_before": before.get("CreatedAt") if isinstance(before, dict) else None,
        "created_at_after": after.get("CreatedAt") if isinstance(after, dict) else None,
        "recreated": recreated,
        "inspect_before": inspect_before,
        "compose_down": down,
        "volume_remove": remove,
        "compose_up": up,
        "health": health,
        "inspect_after": inspect_after,
    }


def calibrate_f07(
    temp_root: Path,
    core: Path | None,
    core_image_digest: str,
    symbolicator_url: str,
    cache_reset: dict[str, Any],
) -> dict[str, Any]:
    config_path = ROOT / "deploy" / "symbolicator" / "config.yml"
    config_text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    microsoft_urls = re.findall(r"^\s*url:\s*(https?://\S+)", config_text, flags=re.MULTILINE)
    volume = run_command(["docker", "volume", "inspect", SYMBOLICATOR_VOLUME], timeout=30)
    measurements: list[dict[str, Any]] = []
    if core is None:
        core_probe: dict[str, Any] = {"status": "SKIP", "reason": "Core executable unavailable"}
    else:
        core_probe = {}
    for module_name, module in (("ntdll", NTDLL), ("kernelbase", KERNELBASE)):
        for repeat in range(3):
            result = http_json(
                f"{symbolicator_url}/symbolicate?scope=wsp_p0calibration"
                "&inventory=0&timeout=300",
                public_payload(module),
            )
            summary = summarize_public_response(result)
            measurements.append(
                {
                    "module": module_name,
                    "temperature_label": (
                        "controlled-cold-first-query"
                        if repeat == 0 and cache_reset.get("status") == "PASS"
                        else "first-observed-cache-state-unknown"
                        if repeat == 0
                        else "hot-repeat-observed"
                    ),
                    "repeat": repeat + 1,
                    **summary,
                }
            )
    policy_payload = public_payload(NTDLL)
    policy_payload["sources"] = [{"id": "request-owned", "type": "http", "url": "https://example.invalid/symbols/"}]
    policy = http_json(
        f"{symbolicator_url}/symbolicate?scope=wsp_p0calibration&inventory=0&timeout=30",
        policy_payload,
    )
    policy_json = policy.get("json") if isinstance(policy.get("json"), dict) else {}
    policy_probe = {
        "http_status": policy.get("status"),
        "error_code": ((policy_json.get("error") or {}).get("code") if isinstance(policy_json, dict) else None),
        "request_owned_sources_rejected": policy.get("status") == 400 and ((policy_json.get("error") or {}).get("code") == "REQUEST_SOURCES_FORBIDDEN"),
    }
    network = http_json(
        "http://127.0.0.1:39999/symbolicate?scope=wsp_p0calibration"
        "&inventory=0&timeout=1",
        public_payload(NTDLL),
        timeout=3,
    )
    network_probe = {
        "http_status": network.get("status"),
        "error": network.get("error"),
        "classification": "network_failure" if network.get("error") else "unexpectedly_reachable",
        "mapped_to_business_pdb_mismatch": False,
    }
    if core is not None:
        metadata = metadata_for(P0_B01)
        dump = P0_B01 / "generated" / "null-read.dmp"
        pe = P0_B01 / "generated" / "null_read_target.exe"
        pdb = P0_B01 / "generated" / "null_read_target.pdb"
        unavailable = run_analysis(
            temp_root=temp_root,
            core=core,
            dump=dump,
            metadata=metadata,
            pe_path=pe,
            pdb_path=pdb,
            label="f07-network-unavailable",
            core_image_digest=core_image_digest,
            symbolicator="http://127.0.0.1:39999",
        )
        canonical = unavailable.get("canonical") or {}
        modules = canonical.get("modules") or []
        warnings = canonical.get("quality", {}).get("warnings", [])
        warning_codes = [warning.get("code") for warning in warnings]
        core_probe = {
            "status": "PASS" if unavailable["command"].get("exit_code") == 0 and "pdb_mismatch" not in warning_codes and any(module.get("status") == "matched" for module in modules) else "FAIL",
            "command": unavailable["command"],
            "module_statuses": [module.get("status") for module in modules],
            "warning_codes": warning_codes,
            "network_failure_not_pdb_mismatch": "pdb_mismatch" not in warning_codes,
        }
    valid_measurements = [item for item in measurements if item["classification"] in {"success", "public_symbol_not_found"}]
    network_failures = [item for item in measurements if item["classification"] == "network_failure"]
    successes = [item for item in measurements if item["classification"] == "success"]
    failure_rate = len(network_failures) / len(measurements) if measurements else None
    successful_probe = bool(successes)
    status = (
        "PASS"
        if microsoft_urls
        and successful_probe
        and not network_failures
        and policy_probe["request_owned_sources_rejected"]
        and network_probe["mapped_to_business_pdb_mismatch"] is False
        and core_probe.get("status") in {"PASS", "SKIP"}
        and cache_reset.get("status") == "PASS"
        else "FAIL"
    )
    return {
        "status": status,
        "decision": "retain Microsoft source as deployment-owned allowlisted egress; keep cache temperature and source attribution explicit, and classify network failures as unavailable rather than business PDB mismatch",
        "configured_sources": {"config": str(config_path), "microsoft_urls": microsoft_urls, "microsoft_source_present": bool(microsoft_urls)},
        "cache_boundary": {
            "volume": SYMBOLICATOR_VOLUME,
            "volume_inspect": volume,
            "cache_cleared_by_tool": cache_reset.get("status") == "PASS",
            "cold_cache_proven": cache_reset.get("status") == "PASS",
            "reset_evidence": cache_reset,
            "reason": (
                "The exact disposable Phase 0 cache volume was label-checked, removed, recreated, and the gateway became healthy before the first public query."
                if cache_reset.get("status") == "PASS"
                else "No successful controlled cache reset was recorded; first-observed timings may be warm."
            ),
        },
        "measurements": measurements,
        "aggregate": {
            "total_valid_public_queries": len(valid_measurements),
            "success_count": len(successes),
            "network_failure_count": len(network_failures),
            "observed_network_failure_rate": failure_rate,
            "public_not_found_count": sum(item["classification"] == "public_symbol_not_found" for item in measurements),
            "successful_query_latency_ms": [item["duration_ms"] for item in successes],
        },
        "allowlist_probe": policy_probe,
        "network_failure_probe": network_probe,
        "core_network_failure_probe": core_probe,
        "boundary": "A controlled empty Docker cache establishes cold-start state for each module's first query; Symbolicator responses still do not expose per-byte source attribution. This is local Docker egress evidence, not production-network evidence.",
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 0 F03–F07 calibration evidence",
        "",
        f"- Overall: **{report['overall_status']}**",
        f"- Checked (UTC): `{report['checked_at_utc']}`",
        f"- Core executable: `{report.get('core_executable') or 'unavailable'}`",
        f"- Core OCI image digest: `{report.get('core_image_digest')}`",
        "- Remote CI: **not executed**",
        "",
        "| Item | Status | Phase 0 decision |",
        "| --- | --- | --- |",
    ]
    for item in ("F03", "F04", "F05", "F06", "F07"):
        value = report["items"].get(item, {})
        lines.append(f"| `{item}` | **{value.get('status', 'SKIP')}** | {value.get('decision', value.get('reason', '-'))} |")
    f03 = report["items"].get("F03", {})
    if f03.get("comparison"):
        comparison = f03["comparison"]
        lines += [
            "",
            "## F03 missing-PE measurement",
            "",
            f"- Exact same dump with restored PE/PDB versus `pe_path=null`; CDB business frames: `{comparison.get('cdb_business_functions')}`.",
            f"- Missing-PE business-frame loss versus CDB: `{comparison.get('business_frame_loss_count')}/{comparison.get('cdb_business_frame_count')}` (`{comparison.get('business_frame_loss_rate')}`).",
            f"- Trust: restored `{f03.get('restored_pe', {}).get('summary', {}).get('trust_histogram')}`, missing-PE `{f03.get('missing_pe', {}).get('summary', {}).get('trust_histogram')}`.",
            f"- Quality: restored `{f03.get('restored_pe', {}).get('summary', {}).get('quality', {}).get('score')}`, missing-PE `{f03.get('missing_pe', {}).get('summary', {}).get('quality', {}).get('score')}`.",
        ]
    f05 = report["items"].get("F05", {})
    if f05.get("core_mock_probe"):
        lines += [
            "",
            "## F05 alignment result",
            "",
            f"- Real raw mappings accepted: `{f05.get('actual_raw_alignment', {}).get('accepted')}`; rejected: `{f05.get('actual_raw_alignment', {}).get('rejected')}`.",
            f"- Validator rejects mutated wrong physical mapping: `{f05.get('mutated_alignment_validator', {}).get('validator_rejects_wrong_physical_mapping')}`.",
            f"- Current Core wrong-index mock fills: `{f05.get('core_mock_probe', {}).get('wrong_physical_frame_fills')}`; required: `0`.",
        ]
    f07 = report["items"].get("F07", {})
    if f07.get("aggregate"):
        aggregate = f07["aggregate"]
        lines += [
            "",
            "## F07 Microsoft symbols",
            "",
            f"- Valid public queries: `{aggregate.get('total_valid_public_queries')}`, successes: `{aggregate.get('success_count')}`, observed network failure rate: `{aggregate.get('observed_network_failure_rate')}`.",
            f"- Successful latencies (ms): `{aggregate.get('successful_query_latency_ms')}`.",
            f"- Cold cache proven: **{f07.get('cache_boundary', {}).get('cold_cache_proven')}**.",
            f"- Request-owned source rejection: `{f07.get('allowlist_probe', {}).get('error_code')}`.",
        ]
    lines += [
        "",
        "## Reproduce",
        "",
        "```text",
        f"python scripts/calibration/phase0_calibration.py --core-image-digest {report.get('core_image_digest')} --reset-symbolicator-cache",
        "```",
        "",
        "The JSON evidence contains command tails, raw mapping summaries, temporary restored-artifact boundaries, and per-probe machine-readable data.",
        "",
        "## Evidence boundary",
        "",
        "Fixtures, the Phase 0 Golden runner, the roadmap, and contracts were not modified by this tool. "
        "The samples are local synthetic MSVC outputs. The exact disposable Symbolicator test cache was reset only when explicitly requested; "
        "no remote CI or production egress proof is claimed.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--symbolicator", default=SYMBOLICATOR_URL)
    parser.add_argument("--core-image-digest", required=True, help="audited sha256 OCI image ID embedded in every calibration Canonical result")
    parser.add_argument(
        "--reset-symbolicator-cache",
        action="store_true",
        help=f"label-check and recreate only {SYMBOLICATOR_VOLUME} before F07 cold/hot probes",
    )
    args = parser.parse_args()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", args.core_image_digest):
        parser.error("--core-image-digest must be sha256:<64 lowercase hex characters>")
    output_json = args.output_json if args.output_json.is_absolute() else ROOT / args.output_json
    output_markdown = args.output_markdown if args.output_markdown.is_absolute() else ROOT / args.output_markdown
    core = core_executable()
    with tempfile.TemporaryDirectory(prefix="crash-cap-phase0-calibration-") as name:
        temp_root = Path(name)
        items = {
            "F03": calibrate_f03(temp_root, core, args.core_image_digest),
            "F04": calibrate_f04(),
            "F05": calibrate_f05(temp_root, core, args.core_image_digest),
            "F06": calibrate_f06(),
        }
        cache_reset = reset_symbolicator_cache(args.symbolicator, args.reset_symbolicator_cache)
        items["F07"] = calibrate_f07(
            temp_root,
            core,
            args.core_image_digest,
            args.symbolicator,
            cache_reset,
        )
    statuses = [item.get("status") for item in items.values()]
    overall = "FAIL" if "FAIL" in statuses else ("PARTIAL" if "SKIP" in statuses else "PASS")
    report = {
        "schema_version": "phase0-calibration-evidence-v0.1",
        "checked_at_utc": utc_now(),
        "overall_status": overall,
        "core_executable": str(core) if core else None,
        "core_image_digest": args.core_image_digest,
        "symbolicator_endpoint": args.symbolicator,
        "items": items,
        "remote_ci_executed": False,
        "modified_paths": [],
        "notes": [
            "F03 uses one exact dump with a temporary restored PE/PDB copy and a separate missing-PE run.",
            "F04 exercises the current 0.45/0.35/0.20 formula and denominator warnings without changing Core.",
            "F05 intentionally includes a wrong-original_index mock to test the actual Core merge behavior.",
            "F07 is a hard pass only when the exact disposable Symbolicator cache volume was label-checked, removed, recreated, and healthy before its first public query.",
        ],
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output_markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"overall_status": overall, "json": str(output_json), "markdown": str(output_markdown)}, indent=2))
    return 0 if overall in {"PASS", "PARTIAL"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
