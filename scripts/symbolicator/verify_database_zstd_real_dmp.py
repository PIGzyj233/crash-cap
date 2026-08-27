#!/usr/bin/env python3
"""Compare a real MSVC DMP through filesystem and DB-backed zstd sources."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "deploy" / "compose" / "pdb-storage-real-dmp-uat.yml"
FIXTURE_ROOT = ROOT / "fixtures" / "p0-b01-null-read"
DEFAULT_JSON = ROOT / "docs" / "evidence" / "pdb-storage-real-dmp-equivalence-20260827.json"
DEFAULT_MD = ROOT / "docs" / "evidence" / "pdb-storage-real-dmp-equivalence-20260827.md"
RUN_ROOT = ROOT / "target" / "pdb-storage-real-dmp-uat"
WORKSPACE_ID = "wsp_01M0VEVHHMTZH6GQB6KTF07XTK"
INVENTORY = 1
SYMBOLICATOR_IMAGE = (
    "ghcr.io/getsentry/symbolicator@"
    "sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959"
)
SOURCE_PATH_RE = re.compile(r'"(?:GET|HEAD) (/v1/workspaces/[^ ]+) HTTP/[0-9.]+" (\d+)')


class VerificationFailure(RuntimeError):
    pass


def run(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
    timeout: int = 900,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.run(  # noqa: S603 - args are constructed from fixed verifier commands
        args,
        cwd=ROOT,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    if check and process.returncode != 0:
        raise VerificationFailure(
            f"command failed ({process.returncode}): {' '.join(args)}\n"
            f"stdout:\n{process.stdout[-4000:]}\nstderr:\n{process.stderr[-4000:]}"
        )
    return process


def compose_command(project: str, *args: str) -> list[str]:
    return ["docker", "compose", "-p", project, "-f", str(COMPOSE_FILE), *args]


def compose(
    project: str,
    mode: str,
    output_dir: Path,
    *args: str,
    check: bool = True,
    timeout: int = 900,
    seed_action: str = "seed",
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["CRASHCAP_UAT_SOURCE_MODE"] = mode
    environment["CRASHCAP_UAT_OUTPUT_DIR"] = str(output_dir.resolve())
    environment["CRASHCAP_UAT_SEED_ACTION"] = seed_action
    source_dir = symbols_dir(mode, output_dir)
    source_dir.mkdir(parents=True, exist_ok=True)
    environment["CRASHCAP_UAT_SYMBOLS_DIR"] = str(source_dir.resolve())
    return run(
        compose_command(project, *args),
        env=environment,
        check=check,
        timeout=timeout,
    )


def symbols_dir(mode: str, output_dir: Path) -> Path:
    if mode == "filesystem":
        return ROOT / "deploy" / "symbolicator" / "symbols" / "p0-test"
    return output_dir / "empty-unified"


def docker_inspect(identifier: str, template: str) -> str:
    return run(["docker", "inspect", "--format", template, identifier]).stdout.strip()


def parse_json_output(process: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    value = json.loads(process.stdout)
    if not isinstance(value, dict):
        raise VerificationFailure("expected a JSON object from isolated helper")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def match_input() -> dict[str, Any]:
    metadata = json.loads(
        (FIXTURE_ROOT / "generated" / "pe-metadata.json").read_text(encoding="utf-8")
    )
    return {
        "workspace_id": WORKSPACE_ID,
        "modules": [
            {
                "artifact_id": "art_real_dmp_target",
                "code_file": "null_read_target.exe",
                "debug_file": "null_read_target.pdb",
                "pe_path": "/fixture/generated/null_read_target.exe",
                "pdb_path": "/fixture/generated/null_read_target.pdb",
                "code_id": metadata["code_id"],
                "debug_id": metadata["debug_id"],
                "role": "entrypoint",
                "in_app": True,
                "build_id": "bld_real_dmp_uat",
            }
        ],
        "builds": [
            {
                "build_id": "bld_real_dmp_uat",
                "modules": [
                    {
                        "code_id": metadata["code_id"],
                        "debug_id": metadata["debug_id"],
                        "role": "entrypoint",
                        "code_file": "null_read_target.exe",
                    }
                ],
            }
        ],
    }


def source_requests(logs: str) -> list[dict[str, Any]]:
    return [
        {"path": match.group(1), "status": int(match.group(2))}
        for match in SOURCE_PATH_RE.finditer(logs)
    ]


def source_ids(value: Any) -> list[str]:
    found: set[str] = set()

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "source" and isinstance(child, str):
                    found.add(child)
                else:
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return sorted(found)


def normalized_canonical(value: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(value)
    dump = normalized.get("dump")
    if isinstance(dump, dict):
        dump.pop("uploaded_at", None)
        dump.pop("occurred_at", None)
    return normalized


def crashing_frames(value: dict[str, Any]) -> list[dict[str, Any]]:
    threads = value.get("threads", [])
    if not isinstance(threads, list):
        return []
    thread = next(
        (item for item in threads if isinstance(item, dict) and item.get("is_crashing")),
        None,
    )
    frames = thread.get("frames", []) if isinstance(thread, dict) else []
    return [frame for frame in frames if isinstance(frame, dict)]


def semantic_summary(value: dict[str, Any]) -> dict[str, Any]:
    crash = value.get("crash", {})
    frames = crashing_frames(value)
    quality = sanitized_quality(value.get("quality"))
    build_resolution = copy.deepcopy(value.get("build_resolution"))
    if isinstance(build_resolution, dict):
        evidence = build_resolution.get("evidence")
        if isinstance(evidence, dict):
            for key in ("matched_entrypoints", "matched_owned_modules", "conflicting_modules"):
                paths = evidence.get(key)
                if isinstance(paths, list):
                    evidence[key] = [basename_any(item) for item in paths]
    return {
        "crash": {
            "type": crash.get("type"),
            "thread_id": crash.get("thread_id"),
            "exception_code": crash.get("exception_code"),
            "exception_name": crash.get("exception_name"),
            "access_type": crash.get("access_type"),
            "address": crash.get("address"),
            "fault_module_debug_id": crash.get("fault_module_debug_id"),
        },
        "crashing_frames": [
            {
                key: frame.get(key)
                for key in (
                    "index",
                    "instruction_addr",
                    "module_debug_id",
                    "relative_addr",
                    "function",
                    "function_raw",
                    "function_normalized",
                    "file",
                    "line",
                    "trust",
                    "in_app",
                    "inline",
                )
            }
            for frame in frames
        ],
        "quality": quality,
        "build_resolution": build_resolution,
        "fingerprints": value.get("fingerprints"),
    }


def basename_any(value: Any) -> str:
    return str(value).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]


def sanitized_quality(value: Any) -> Any:
    quality = copy.deepcopy(value)
    if not isinstance(quality, dict):
        return quality
    warnings = quality.get("warnings")
    if isinstance(warnings, list):
        for warning in warnings:
            if isinstance(warning, dict) and warning.get("module"):
                warning["module"] = basename_any(warning["module"])
    return quality


def target_business_functions(value: dict[str, Any]) -> list[str]:
    return [
        str(frame["function"])
        for frame in crashing_frames(value)
        if frame.get("in_app") and frame.get("function")
    ]


def core_command(
    project: str,
    mode: str,
    output_dir: Path,
    core_digest: str,
    *,
    suffix: str = "",
    inspect_name: str = "inspect.json",
) -> subprocess.CompletedProcess[str]:
    output_name = f"canonical{suffix}.json"
    raw_name = f"raw{suffix}"
    return compose(
        project,
        mode,
        output_dir,
        "run",
        "--rm",
        "--no-deps",
        "core",
        "analyze",
        "--dump",
        "/fixture/generated/null-read.dmp",
        "--inspect",
        f"/evidence/{inspect_name}",
        "--match",
        "/evidence/match-input.json",
        "--symbolicator",
        "http://gateway:3021",
        "--workspace-id",
        WORKSPACE_ID,
        "--symbol-inventory-version",
        str(INVENTORY),
        "--symbolicator-timeout",
        "60",
        "--core-image-digest",
        core_digest,
        "--symbolicator-version",
        "26.7.2",
        "--output",
        f"/evidence/{output_name}",
        "--raw-dir",
        f"/evidence/{raw_name}",
        check=False,
        timeout=300,
    )


def run_mode(
    name: str,
    mode: str,
    run_root: Path,
    core_digest: str,
    *,
    corrupt_pdb: bool = False,
    hot_repeat: bool = False,
) -> dict[str, Any]:
    project = f"crash-cap-pdb-zstd-uat-{name}"
    output_dir = run_root / name
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "match-input.json").write_text(
        json.dumps(match_input(), indent=2) + "\n", encoding="utf-8"
    )
    compose(project, mode, output_dir, "down", "--volumes", "--remove-orphans", check=False)
    started = time.monotonic()
    try:
        compose(project, mode, output_dir, "up", "-d", "--wait", "gateway", timeout=600)
        startup_seconds = time.monotonic() - started
        migration = compose(
            project,
            mode,
            output_dir,
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "crashcap",
            "-d",
            "crashcap",
            "-Atc",
            "select version_num from alembic_version",
        ).stdout.strip()
        inventory_before = parse_json_output(
            compose(
                project,
                mode,
                output_dir,
                "run",
                "--rm",
                "--no-deps",
                "seed",
                "inspect",
            )
        )
        corruption = None
        if corrupt_pdb:
            corruption = parse_json_output(
                compose(
                    project,
                    mode,
                    output_dir,
                    "run",
                    "--rm",
                    "--no-deps",
                    "seed",
                    "corrupt",
                    "--kind",
                    "pdb",
                )
            )
        inventory_after = parse_json_output(
            compose(
                project,
                mode,
                output_dir,
                "run",
                "--rm",
                "--no-deps",
                "seed",
                "inspect",
            )
        )
        probe = None
        if mode == "http":
            probe = parse_json_output(
                compose(
                    project,
                    mode,
                    output_dir,
                    "run",
                    "--rm",
                    "--no-deps",
                    "seed",
                    "probe",
                    "--kind",
                    "pdb",
                )
            )
        before_logs = compose(
            project, mode, output_dir, "logs", "--no-color", "symbol-source"
        ).stdout
        before_requests = source_requests(before_logs)
        inspect_run = compose(
            project,
            mode,
            output_dir,
            "run",
            "--rm",
            "--no-deps",
            "core",
            "inspect",
            "--dump",
            "/fixture/generated/null-read.dmp",
            "--output",
            "/evidence/inspect.json",
            check=False,
            timeout=120,
        )
        core_started = time.monotonic()
        analyze_run = core_command(project, mode, output_dir, core_digest)
        cold_seconds = time.monotonic() - core_started
        after_cold_logs = compose(
            project, mode, output_dir, "logs", "--no-color", "symbol-source"
        ).stdout
        cold_requests = source_requests(after_cold_logs)[len(before_requests) :]
        canonical_path = output_dir / "canonical.json"
        canonical = (
            json.loads(canonical_path.read_text(encoding="utf-8"))
            if canonical_path.is_file()
            else None
        )
        raw_path = output_dir / "raw" / "symbolicator.json"
        raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.is_file() else None

        hot: dict[str, Any] | None = None
        if hot_repeat:
            hot_started = time.monotonic()
            hot_run = core_command(project, mode, output_dir, core_digest, suffix="-hot")
            hot_seconds = time.monotonic() - hot_started
            hot_logs = compose(
                project, mode, output_dir, "logs", "--no-color", "symbol-source"
            ).stdout
            after_hot_requests = source_requests(hot_logs)[len(source_requests(after_cold_logs)) :]
            hot_path = output_dir / "canonical-hot.json"
            hot_canonical = (
                json.loads(hot_path.read_text(encoding="utf-8")) if hot_path.is_file() else None
            )
            hot = {
                "returncode": hot_run.returncode,
                "seconds": round(hot_seconds, 6),
                "additional_source_requests": after_hot_requests,
                "canonical": hot_canonical,
            }

        symbolicator_id = compose(
            project, mode, output_dir, "ps", "-q", "symbolicator"
        ).stdout.strip()
        source_id = compose(project, mode, output_dir, "ps", "-q", "symbol-source").stdout.strip()
        symbolicator_version = compose(
            project,
            mode,
            output_dir,
            "exec",
            "-T",
            "symbolicator",
            "/bin/symbolicator",
            "--version",
        ).stdout.strip().splitlines()
        unified_files = [
            path for path in symbols_dir(mode, output_dir).rglob("*") if path.is_file()
        ]
        return {
            "mode": mode,
            "project": project,
            "startup_seconds": round(startup_seconds, 6),
            "migration_revision": migration,
            "symbolicator_version": symbolicator_version,
            "symbolicator_image_id": docker_inspect(symbolicator_id, "{{.Image}}"),
            "symbol_source_image_id": docker_inspect(source_id, "{{.Image}}"),
            "unified_mount_file_count": len(unified_files),
            "inventory_before": inventory_before,
            "corruption": corruption,
            "inventory_after": inventory_after,
            "direct_pdb_probe": probe,
            "inspect_returncode": inspect_run.returncode,
            "analyze_returncode": analyze_run.returncode,
            "analyze_error_tail": (analyze_run.stderr or analyze_run.stdout)[-2000:],
            "cold_seconds": round(cold_seconds, 6),
            "cold_source_requests": cold_requests,
            "raw_symbol_source_ids": source_ids(raw),
            "canonical": canonical,
            "hot": hot,
        }
    finally:
        compose(
            project,
            mode,
            output_dir,
            "down",
            "--volumes",
            "--remove-orphans",
            check=False,
            timeout=300,
        )


def check_report(modes: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    legacy = modes["legacy"]
    zstd = modes["zstd"]
    corrupt = modes["corrupt"]
    legacy_canonical = legacy["canonical"]
    zstd_canonical = zstd["canonical"]
    corrupt_canonical = corrupt["canonical"]
    hot_canonical = zstd.get("hot", {}).get("canonical")
    checks: list[tuple[str, bool, Any]] = []

    checks.append(
        (
            "isolated migrations reached delivery-v2 head",
            all(item["migration_revision"] == "0009_delivery_v2_wire" for item in modes.values()),
            {name: item["migration_revision"] for name, item in modes.items()},
        )
    )
    checks.append(
        (
            "Artifact objects are zstd-only and HTTP runs have no Unified raw fallback",
            all(
                item["inventory_before"]["physical_objects_are_zstd_only"]
                and item["inventory_before"]["physical_object_count"] == 2
                and all(
                    not blob["raw_object_present"]
                    for blob in item["inventory_before"]["blobs"]
                )
                for item in modes.values()
            )
            and legacy["unified_mount_file_count"] > 0
            and zstd["unified_mount_file_count"] == 0
            and corrupt["unified_mount_file_count"] == 0,
            {
                "artifact_blobs": {
                    name: item["inventory_before"] for name, item in modes.items()
                },
                "unified_mount_file_count": {
                    name: item["unified_mount_file_count"] for name, item in modes.items()
                },
            },
        )
    )
    checks.append(
        (
            "legacy and intact zstd Core executions completed",
            legacy["inspect_returncode"] == 0
            and legacy["analyze_returncode"] == 0
            and zstd["inspect_returncode"] == 0
            and zstd["analyze_returncode"] == 0,
            {
                "legacy": legacy["analyze_returncode"],
                "zstd": zstd["analyze_returncode"],
            },
        )
    )
    schema = json.loads(
        (ROOT / "contracts" / "analysis-result-v1.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    canonical_documents = {
        "legacy": legacy_canonical,
        "zstd": zstd_canonical,
        "zstd_hot": hot_canonical,
        "corrupt": corrupt_canonical,
    }
    schema_failures = {
        name: [
            {
                "path": "/" + "/".join(str(part) for part in error.absolute_path),
                "message": error.message,
            }
            for error in validator.iter_errors(document)
        ]
        for name, document in canonical_documents.items()
        if isinstance(document, dict)
    }
    checks.append(
        (
            "all real Core outputs validate against Canonical v1",
            len(schema_failures) == len(canonical_documents)
            and all(not failures for failures in schema_failures.values()),
            schema_failures,
        )
    )
    checks.append(
        (
            "database-backed zstd source returned the exact logical PDB bytes",
            zstd["direct_pdb_probe"]["http_status"] == 200
            and zstd["direct_pdb_probe"]["matches_logical_identity"] is True,
            zstd["direct_pdb_probe"],
        )
    )
    canonical_equal = isinstance(legacy_canonical, dict) and isinstance(zstd_canonical, dict)
    if canonical_equal:
        canonical_equal = normalized_canonical(legacy_canonical) == normalized_canonical(
            zstd_canonical
        )
    checks.append(
        (
            "legacy filesystem and zstd HTTP Canonical are equal except run timestamps",
            canonical_equal,
            {
                "legacy_normalized_sha256": canonical_digest(legacy_canonical),
                "zstd_normalized_sha256": canonical_digest(zstd_canonical),
            },
        )
    )
    checks.append(
        (
            (
                "expected exception, crash thread, business functions, source lines, quality, "
                "and Exact exist"
            ),
            isinstance(zstd_canonical, dict) and expected_semantics(zstd_canonical),
            semantic_summary(zstd_canonical) if isinstance(zstd_canonical, dict) else None,
        )
    )
    checks.append(
        (
            "cold HTTP run fetched DB-backed debuginfo",
            any(
                request["path"].endswith("/debuginfo") and request["status"] in {200, 206}
                for request in zstd["cold_source_requests"]
            ),
            {
                "requests": zstd["cold_source_requests"],
                "sources": zstd["raw_symbol_source_ids"],
            },
        )
    )
    hot_equal = isinstance(zstd_canonical, dict) and isinstance(hot_canonical, dict)
    if hot_equal:
        hot_equal = normalized_canonical(zstd_canonical) == normalized_canonical(hot_canonical)
    checks.append(
        (
            "hot HTTP run preserved Canonical and did not refetch the source",
            zstd.get("hot", {}).get("returncode") == 0
            and hot_equal
            and not zstd.get("hot", {}).get("additional_source_requests"),
            {
                "additional_source_requests": zstd.get("hot", {}).get(
                    "additional_source_requests"
                ),
                "hot_normalized_sha256": canonical_digest(hot_canonical),
            },
        )
    )
    corrupted_blob = next(
        blob for blob in corrupt["inventory_after"]["blobs"] if blob["kind"] == "pdb"
    )
    probe_error = corrupt["direct_pdb_probe"].get("error", {})
    error_payload = probe_error.get("error", {}) if isinstance(probe_error, dict) else {}
    checks.append(
        (
            "same-size single-bit zstd corruption was detected before raw bytes were served",
            corrupt["corruption"]["size_preserved"] is True
            and corrupted_blob["payload_observed_sha256"] != corrupted_blob["payload_sha256"]
            and corrupt["direct_pdb_probe"]["http_status"] == 503
            and error_payload.get("code") == "SYMBOL_PAYLOAD_UNAVAILABLE"
            and error_payload.get("message") == "payload_sha256_mismatch",
            {
                "corruption": corrupt["corruption"],
                "probe": corrupt["direct_pdb_probe"],
            },
        )
    )
    corrupt_functions = (
        target_business_functions(corrupt_canonical)
        if isinstance(corrupt_canonical, dict)
        else []
    )
    corrupt_differs = not isinstance(corrupt_canonical, dict) or not isinstance(
        legacy_canonical, dict
    )
    if not corrupt_differs:
        corrupt_differs = normalized_canonical(corrupt_canonical) != normalized_canonical(
            legacy_canonical
        )
    corrupt_warnings = (
        corrupt_canonical.get("quality", {}).get("warnings", [])
        if isinstance(corrupt_canonical, dict)
        else []
    )
    checks.append(
        (
            "corrupt payload did not produce silently trusted business symbols",
            "crashcap::trigger_null_read()" not in corrupt_functions
            and "wmain(int, wchar_t**)" not in corrupt_functions
            and corrupt_differs
            and sum(
                request["status"] == 503 for request in corrupt["cold_source_requests"]
            )
            >= 2
            and any(
                warning.get("code") == "symbolicator_failed"
                for warning in corrupt_warnings
                if isinstance(warning, dict)
            ),
            {
                "core_returncode": corrupt["analyze_returncode"],
                "business_functions": corrupt_functions,
                "source_requests": corrupt["cold_source_requests"],
                "quality": (
                    sanitized_quality(corrupt_canonical.get("quality"))
                    if isinstance(corrupt_canonical, dict)
                    else None
                ),
            },
        )
    )
    return [
        {"name": name, "status": "PASS" if passed else "FAIL", "evidence": evidence}
        for name, passed, evidence in checks
    ]


def canonical_digest(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    payload = json.dumps(
        normalized_canonical(value), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def public_modes(modes: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    projected: dict[str, dict[str, Any]] = {}
    for name, item in modes.items():
        hot = item.get("hot")
        projected[name] = {
            key: item.get(key)
            for key in (
                "mode",
                "project",
                "startup_seconds",
                "migration_revision",
                "symbolicator_version",
                "symbolicator_image_id",
                "symbol_source_image_id",
                "unified_mount_file_count",
                "inventory_before",
                "corruption",
                "inventory_after",
                "direct_pdb_probe",
                "inspect_returncode",
                "analyze_returncode",
                "cold_seconds",
                "cold_source_requests",
                "raw_symbol_source_ids",
            )
        }
        projected[name]["canonical_normalized_sha256"] = canonical_digest(item.get("canonical"))
        projected[name]["canonical_semantics"] = (
            semantic_summary(item["canonical"])
            if isinstance(item.get("canonical"), dict)
            else None
        )
        if isinstance(hot, dict):
            projected[name]["hot"] = {
                "returncode": hot.get("returncode"),
                "seconds": hot.get("seconds"),
                "additional_source_requests": hot.get("additional_source_requests"),
                "canonical_normalized_sha256": canonical_digest(hot.get("canonical")),
            }
        else:
            projected[name]["hot"] = None
    return projected


def expected_semantics(value: dict[str, Any]) -> bool:
    crash = value.get("crash", {})
    frames = crashing_frames(value)
    functions = [frame.get("function_normalized") for frame in frames if frame.get("in_app")]
    source_rows = {
        (frame.get("function_normalized"), frame.get("file"), frame.get("line"))
        for frame in frames
        if frame.get("in_app")
    }
    quality = value.get("quality", {})
    fingerprints = value.get("fingerprints", {})
    return (
        crash.get("type") == "crash"
        and crash.get("thread_id") == 11480
        and crash.get("exception_code") == "0xC0000005"
        and crash.get("access_type") == "read"
        and functions[:2] == ["crashcap::trigger_null_read", "wmain"]
        and ("crashcap::trigger_null_read", "null_read_target.cpp", 76) in source_rows
        and ("wmain", "null_read_target.cpp", 105) in source_rows
        and quality.get("score") == 1.0
        and quality.get("symbol_coverage") == 1.0
        and isinstance(fingerprints.get("exact"), str)
        and len(fingerprints["exact"]) == 64
    )


def render_markdown(report: dict[str, Any]) -> str:
    modes = report["modes"]
    zstd = modes["zstd"]
    corrupt = modes["corrupt"]
    rows = [
        "# PDB storage real-DMP equivalence evidence",
        "",
        f"Status: **{report['status']}**",
        "",
        (
            "This is an isolated local Docker Desktop pre-UAT using a real generated x64 MSVC "
            "minidump, PE, and PDB. It is not a lightstreamer/product incident or "
            "target-intranet UAT."
        ),
        "",
        "## Checks",
        "",
        "| Check | Status |",
        "| --- | --- |",
    ]
    rows.extend(f"| {item['name']} | {item['status']} |" for item in report["checks"])
    rows.extend(
        [
            "",
            "## Runtime evidence",
            "",
            "| Path | Cold seconds | Source requests | Canonical SHA-256 |",
            "| --- | ---: | ---: | --- |",
        ]
    )
    for name in ("legacy", "zstd", "corrupt"):
        item = modes[name]
        rows.append(
            f"| {name} | {item['cold_seconds']:.6f} | "
            f"{len(item['cold_source_requests'])} | "
            f"{item['canonical_normalized_sha256'] or 'none'} |"
        )
    rows.extend(
        [
            "",
            (
                f"- zstd direct PDB probe: HTTP {zstd['direct_pdb_probe']['http_status']}, "
                f"identity match={zstd['direct_pdb_probe']['matches_logical_identity']}"
            ),
            f"- corrupt direct PDB probe: HTTP {corrupt['direct_pdb_probe']['http_status']}",
            (
                "- hot zstd additional source requests: "
                f"{len(zstd['hot']['additional_source_requests'])}"
            ),
            f"- PostgreSQL migration: `{zstd['migration_revision']}`",
            f"- Symbolicator image: `{report['configured_symbolicator_image']}`",
            f"- Core image digest: `{report['core_image_digest']}`",
            "",
            "## Evidence boundary",
            "",
        ]
    )
    rows.extend(f"- NOT_PROVEN: {item}" for item in report["not_proven"])
    return "\n".join(rows) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_root = RUN_ROOT / stamp
    run_root.mkdir(parents=True, exist_ok=False)
    build_output = run_root / "build"
    build_output.mkdir()
    build_started = time.monotonic()
    compose(
        "crash-cap-pdb-zstd-uat-build",
        "http",
        build_output,
        "build",
        "migrations",
        "gateway",
        "core",
        timeout=1200,
    )
    build_seconds = time.monotonic() - build_started
    core_digest = docker_inspect("crash-cap/dmp-core:pdb-storage-real-dmp-uat", "{{.Id}}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", core_digest):
        raise VerificationFailure(f"invalid Core image digest: {core_digest!r}")

    modes = {
        "legacy": run_mode("legacy", "filesystem", run_root, core_digest),
        "zstd": run_mode(
            "zstd", "http", run_root, core_digest, hot_repeat=True
        ),
        "corrupt": run_mode(
            "corrupt", "http", run_root, core_digest, corrupt_pdb=True
        ),
    }
    checks = check_report(modes)
    report = {
        "schema_version": "pdb-storage-real-dmp-equivalence-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL",
        "scope": (
            "isolated local Docker Desktop; real generated x64 MSVC DMP/PE/PDB; "
            "not a product incident or target-intranet UAT"
        ),
        "fixture": {
            "id": "p0-b01-null-read",
            "dump_sha256": sha256_file(FIXTURE_ROOT / "generated" / "null-read.dmp"),
            "pe_sha256": sha256_file(
                FIXTURE_ROOT / "generated" / "null_read_target.exe"
            ),
            "pdb_sha256": sha256_file(
                FIXTURE_ROOT / "generated" / "null_read_target.pdb"
            ),
        },
        "workspace_id": WORKSPACE_ID,
        "inventory": INVENTORY,
        "core_image_digest": core_digest,
        "configured_symbolicator_image": SYMBOLICATOR_IMAGE,
        "build_seconds": round(build_seconds, 6),
        "run_root": str(run_root.relative_to(ROOT)).replace("\\", "/"),
        "checks": checks,
        "modes": public_modes(modes),
        "not_proven": [
            "real lightstreamer or other product-incident DMP equivalence",
            "target-intranet PostgreSQL, RustFS/S3, networking, concurrency, or performance",
            "backup restore from target PostgreSQL plus zstd-only RustFS",
            "Unified/raw/legacy cleanup apply and rollback-window completion",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    markdown = args.markdown if args.markdown.is_absolute() else ROOT / args.markdown
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": checks}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
