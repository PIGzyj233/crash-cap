#!/usr/bin/env python3
"""Verify DB-backed symbol source/cache outage behavior with a real MSVC DMP."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from verify_database_zstd_real_dmp import (
    FIXTURE_ROOT,
    INVENTORY,
    ROOT,
    SYMBOLICATOR_IMAGE,
    WORKSPACE_ID,
    VerificationFailure,
    canonical_digest,
    compose,
    core_command,
    docker_inspect,
    expected_semantics,
    match_input,
    normalized_canonical,
    parse_json_output,
    run,
    sanitized_quality,
    semantic_summary,
    sha256_file,
    source_requests,
    symbols_dir,
    target_business_functions,
)

DEFAULT_JSON = ROOT / "docs" / "evidence" / "pdb-storage-source-recovery-20260827.json"
DEFAULT_MD = ROOT / "docs" / "evidence" / "pdb-storage-source-recovery-20260827.md"
RUN_ROOT = ROOT / "target" / "pdb-storage-source-recovery"
MIGRATION_HEAD = "0009_delivery_v2_wire"


def write_match_input(output_dir: Path) -> None:
    (output_dir / "match-input.json").write_text(
        json.dumps(match_input(), indent=2) + "\n", encoding="utf-8"
    )


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def core_inspect(project: str, output_dir: Path, output_name: str) -> int:
    result = compose(
        project,
        "http",
        output_dir,
        "run",
        "--rm",
        "--no-deps",
        "core",
        "inspect",
        "--dump",
        "/fixture/generated/null-read.dmp",
        "--output",
        f"/evidence/{output_name}",
        check=False,
        timeout=120,
    )
    return result.returncode


def migration_revision(project: str, output_dir: Path) -> str:
    return compose(
        project,
        "http",
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


def inventory(project: str, output_dir: Path) -> dict[str, Any]:
    return parse_json_output(
        compose(
            project,
            "http",
            output_dir,
            "run",
            "--rm",
            "--no-deps",
            "seed",
            "inspect",
        )
    )


def down(project: str, output_dir: Path) -> None:
    compose(
        project,
        "http",
        output_dir,
        "down",
        "--volumes",
        "--remove-orphans",
        check=False,
        timeout=300,
    )


def symbolicator_cache_volume(project: str) -> str:
    result = run(
        [
            "docker",
            "volume",
            "ls",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            "label=com.docker.compose.volume=symbolicator-cache",
            "--format",
            "{{.Name}}",
        ]
    )
    names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(names) != 1:
        raise VerificationFailure(
            f"expected one exact Symbolicator cache volume for {project}, found {len(names)}"
        )
    return names[0]


def remove_exact_cache_volume(project: str, output_dir: Path) -> dict[str, Any]:
    compose(project, "http", output_dir, "stop", "gateway", "symbolicator")
    volume = symbolicator_cache_volume(project)
    labels = docker_inspect(volume, "{{json .Labels}}")
    parsed = json.loads(labels)
    if (
        not isinstance(parsed, dict)
        or parsed.get("com.docker.compose.project") != project
        or parsed.get("com.docker.compose.volume") != "symbolicator-cache"
    ):
        raise VerificationFailure("refusing to remove a cache volume without exact Compose labels")
    compose(project, "http", output_dir, "rm", "-f", "symbolicator")
    run(["docker", "volume", "rm", volume])
    return {"exact_labels_verified": True, "removed": True}


def schema_failures(value: Any) -> list[dict[str, str]] | None:
    if not isinstance(value, dict):
        return None
    schema = json.loads(
        (ROOT / "contracts" / "analysis-result-v1.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    return [
        {
            "path": "/" + "/".join(str(part) for part in error.absolute_path),
            "message": error.message,
        }
        for error in validator.iter_errors(value)
    ]


def analyze(
    project: str,
    output_dir: Path,
    core_digest: str,
    suffix: str,
    inspect_name: str,
) -> dict[str, Any]:
    logs_before = compose(
        project, "http", output_dir, "logs", "--no-color", "symbol-source"
    ).stdout
    requests_before = source_requests(logs_before)
    started = time.monotonic()
    result = core_command(
        project,
        "http",
        output_dir,
        core_digest,
        suffix=suffix,
        inspect_name=inspect_name,
    )
    seconds = time.monotonic() - started
    logs_after = compose(
        project, "http", output_dir, "logs", "--no-color", "symbol-source"
    ).stdout
    return {
        "returncode": result.returncode,
        "seconds": round(seconds, 6),
        "source_requests": source_requests(logs_after)[len(requests_before) :],
        "canonical": read_json(output_dir / f"canonical{suffix}.json"),
    }


def cached_source_outage(
    project: str, output_dir: Path, core_digest: str
) -> dict[str, Any]:
    down(project, output_dir)
    try:
        compose(
            project,
            "http",
            output_dir,
            "up",
            "-d",
            "--wait",
            "gateway",
            timeout=600,
        )
        state = inventory(project, output_dir)
        inspect_returncode = core_inspect(project, output_dir, "inspect-cached.json")
        baseline = analyze(
            project, output_dir, core_digest, "-cached-baseline", "inspect-cached.json"
        )
        cache_before = symbolicator_cache_volume(project)
        compose(project, "http", output_dir, "stop", "gateway", "symbolicator")
        compose(
            project,
            "http",
            output_dir,
            "up",
            "-d",
            "--wait",
            "gateway",
            timeout=600,
            seed_action="inspect",
        )
        cache_after = symbolicator_cache_volume(project)
        compose(project, "http", output_dir, "stop", "symbol-source")
        cached = analyze(
            project, output_dir, core_digest, "-cached-source-down", "inspect-cached.json"
        )
        return {
            "migration_revision": migration_revision(project, output_dir),
            "inventory": state,
            "inspect_returncode": inspect_returncode,
            "baseline": baseline,
            "after_restart_source_down": cached,
            "cache_volume_persisted_across_restart": cache_before == cache_after,
            "unified_mount_file_count": len(
                [path for path in symbols_dir("http", output_dir).rglob("*") if path.is_file()]
            ),
        }
    finally:
        down(project, output_dir)


def cold_outage_recovery(
    project: str, output_dir: Path, core_digest: str
) -> dict[str, Any]:
    down(project, output_dir)
    try:
        compose(
            project,
            "http",
            output_dir,
            "up",
            "-d",
            "--wait",
            "gateway",
            timeout=600,
        )
        state = inventory(project, output_dir)
        inspect_returncode = core_inspect(project, output_dir, "inspect-recovery.json")
        compose(project, "http", output_dir, "stop", "symbol-source")
        outage = analyze(
            project, output_dir, core_digest, "-cold-source-down", "inspect-recovery.json"
        )
        cache_reset = remove_exact_cache_volume(project, output_dir)
        compose(
            project,
            "http",
            output_dir,
            "up",
            "-d",
            "--wait",
            "gateway",
            timeout=600,
            seed_action="inspect",
        )
        recovered = analyze(
            project, output_dir, core_digest, "-source-recovered", "inspect-recovery.json"
        )
        return {
            "migration_revision": migration_revision(project, output_dir),
            "inventory": state,
            "inspect_returncode": inspect_returncode,
            "outage": outage,
            "cache_reset": cache_reset,
            "recovered": recovered,
            "unified_mount_file_count": len(
                [path for path in symbols_dir("http", output_dir).rglob("*") if path.is_file()]
            ),
        }
    finally:
        down(project, output_dir)


def blocking_warning(value: Any) -> bool:
    warnings = value.get("quality", {}).get("warnings", []) if isinstance(value, dict) else []
    return any(
        isinstance(warning, dict) and warning.get("code") == "symbolicator_failed"
        for warning in warnings
    )


def checks(cached: dict[str, Any], recovery: dict[str, Any]) -> list[dict[str, Any]]:
    baseline = cached["baseline"]["canonical"]
    cached_outage = cached["after_restart_source_down"]["canonical"]
    outage = recovery["outage"]["canonical"]
    recovered = recovery["recovered"]["canonical"]
    rows: list[tuple[str, bool, Any]] = [
        (
            "isolated source/cache projects reached migration head with zstd-only objects",
            cached["migration_revision"] == MIGRATION_HEAD
            and recovery["migration_revision"] == MIGRATION_HEAD
            and all(
                item["inventory"]["physical_objects_are_zstd_only"]
                and item["inventory"]["physical_object_count"] == 2
                for item in (cached, recovery)
            ),
            {
                "cached_revision": cached["migration_revision"],
                "recovery_revision": recovery["migration_revision"],
                "cached_objects": cached["inventory"]["physical_object_count"],
                "recovery_objects": recovery["inventory"]["physical_object_count"],
            },
        ),
        (
            "all emitted documents validate against Canonical v1",
            all(
                schema_failures(value) == []
                for value in (baseline, cached_outage, outage, recovered)
            ),
            {
                "baseline": schema_failures(baseline),
                "cached_source_down": schema_failures(cached_outage),
                "cold_source_down": schema_failures(outage),
                "source_recovered": schema_failures(recovered),
            },
        ),
        (
            "cold baseline parsed the expected crash without Unified fallback",
            cached["inspect_returncode"] == 0
            and cached["baseline"]["returncode"] == 0
            and cached["unified_mount_file_count"] == 0
            and isinstance(baseline, dict)
            and expected_semantics(baseline),
            {
                "inspect_returncode": cached["inspect_returncode"],
                "analyze_returncode": cached["baseline"]["returncode"],
                "unified_mount_file_count": cached["unified_mount_file_count"],
                "canonical_sha256": canonical_digest(baseline),
            },
        ),
        (
            "persisted cache survived Symbolicator restart and source outage",
            cached["cache_volume_persisted_across_restart"] is True
            and cached["after_restart_source_down"]["returncode"] == 0
            and not cached["after_restart_source_down"]["source_requests"]
            and isinstance(baseline, dict)
            and isinstance(cached_outage, dict)
            and normalized_canonical(baseline) == normalized_canonical(cached_outage),
            {
                "cache_volume_persisted": cached["cache_volume_persisted_across_restart"],
                "source_requests": cached["after_restart_source_down"]["source_requests"],
                "baseline_sha256": canonical_digest(baseline),
                "cached_source_down_sha256": canonical_digest(cached_outage),
            },
        ),
        (
            "empty-cache source outage failed closed without trusted business symbols",
            recovery["outage"]["returncode"] == 0
            and isinstance(outage, dict)
            and blocking_warning(outage)
            and not target_business_functions(outage)
            and isinstance(baseline, dict)
            and normalized_canonical(outage) != normalized_canonical(baseline),
            {
                "returncode": recovery["outage"]["returncode"],
                "business_functions": target_business_functions(outage)
                if isinstance(outage, dict)
                else [],
                "quality": sanitized_quality(outage.get("quality"))
                if isinstance(outage, dict)
                else None,
            },
        ),
        (
            "source recovery with a fresh cache restored the exact baseline Canonical",
            recovery["cache_reset"]["exact_labels_verified"] is True
            and recovery["cache_reset"]["removed"] is True
            and recovery["recovered"]["returncode"] == 0
            and isinstance(baseline, dict)
            and isinstance(recovered, dict)
            and normalized_canonical(baseline) == normalized_canonical(recovered),
            {
                "cache_reset": recovery["cache_reset"],
                "baseline_sha256": canonical_digest(baseline),
                "recovered_sha256": canonical_digest(recovered),
            },
        ),
        (
            "recovered run refetched DB-backed PE/PDB and retained crash semantics",
            any(
                request["status"] in {200, 206}
                and request["path"].endswith(("/debuginfo", "/executable"))
                for request in recovery["recovered"]["source_requests"]
            )
            and isinstance(recovered, dict)
            and expected_semantics(recovered),
            {
                "source_requests": recovery["recovered"]["source_requests"],
                "canonical_semantics": semantic_summary(recovered)
                if isinstance(recovered, dict)
                else None,
            },
        ),
    ]
    return [
        {"name": name, "status": "PASS" if passed else "FAIL", "evidence": evidence}
        for name, passed, evidence in rows
    ]


def public_analysis(value: dict[str, Any]) -> dict[str, Any]:
    canonical = value.get("canonical")
    return {
        "returncode": value.get("returncode"),
        "seconds": value.get("seconds"),
        "source_requests": value.get("source_requests"),
        "canonical_normalized_sha256": canonical_digest(canonical),
        "canonical_semantics": semantic_summary(canonical)
        if isinstance(canonical, dict)
        else None,
    }


def public_runs(cached: dict[str, Any], recovery: dict[str, Any]) -> dict[str, Any]:
    return {
        "cached_source_outage": {
            "migration_revision": cached["migration_revision"],
            "inventory": cached["inventory"],
            "inspect_returncode": cached["inspect_returncode"],
            "baseline": public_analysis(cached["baseline"]),
            "after_restart_source_down": public_analysis(
                cached["after_restart_source_down"]
            ),
            "cache_volume_persisted_across_restart": cached[
                "cache_volume_persisted_across_restart"
            ],
            "unified_mount_file_count": cached["unified_mount_file_count"],
        },
        "cold_outage_recovery": {
            "migration_revision": recovery["migration_revision"],
            "inventory": recovery["inventory"],
            "inspect_returncode": recovery["inspect_returncode"],
            "outage": public_analysis(recovery["outage"]),
            "cache_reset": recovery["cache_reset"],
            "recovered": public_analysis(recovery["recovered"]),
            "unified_mount_file_count": recovery["unified_mount_file_count"],
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    rows = [
        "# PDB storage source/cache recovery real-DMP evidence",
        "",
        f"Status: **{report['status']}**",
        "",
        (
            "This is an isolated local Docker Desktop pre-UAT using a real generated x64 MSVC "
            "minidump and DB-backed zstd-only PE/PDB objects."
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
            "## Identity evidence",
            "",
            f"- Baseline Canonical SHA-256: `{report['baseline_canonical_sha256']}`",
            f"- Cached source-down SHA-256: `{report['cached_source_down_sha256']}`",
            f"- Recovered Canonical SHA-256: `{report['recovered_canonical_sha256']}`",
            f"- Core image digest: `{report['core_image_digest']}`",
            f"- Symbolicator image: `{report['configured_symbolicator_image']}`",
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
    write_match_input(build_output)
    compose(
        "crash-cap-pdb-source-recovery-build",
        "http",
        build_output,
        "build",
        "migrations",
        "gateway",
        "core",
        timeout=1200,
    )
    core_digest = docker_inspect("crash-cap/dmp-core:pdb-storage-real-dmp-uat", "{{.Id}}")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", core_digest) is None:
        raise VerificationFailure(f"invalid Core image digest: {core_digest!r}")

    cached_output = run_root / "cached-source-outage"
    cached_output.mkdir()
    write_match_input(cached_output)
    recovery_output = run_root / "cold-outage-recovery"
    recovery_output.mkdir()
    write_match_input(recovery_output)
    cached = cached_source_outage(
        f"crash-cap-pdb-source-cached-{stamp.lower()}", cached_output, core_digest
    )
    recovery = cold_outage_recovery(
        f"crash-cap-pdb-source-recovery-{stamp.lower()}", recovery_output, core_digest
    )
    result_checks = checks(cached, recovery)
    report = {
        "schema_version": "pdb-storage-source-recovery-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": "PASS"
        if all(item["status"] == "PASS" for item in result_checks)
        else "FAIL",
        "scope": (
            "isolated local Docker Desktop; real generated x64 MSVC DMP/PE/PDB; "
            "not target-intranet or product-incident UAT"
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
        "run_root": str(run_root.relative_to(ROOT)).replace("\\", "/"),
        "checks": result_checks,
        "baseline_canonical_sha256": canonical_digest(cached["baseline"]["canonical"]),
        "cached_source_down_sha256": canonical_digest(
            cached["after_restart_source_down"]["canonical"]
        ),
        "recovered_canonical_sha256": canonical_digest(recovery["recovered"]["canonical"]),
        "runs": public_runs(cached, recovery),
        "not_proven": [
            "real lightstreamer or other product-incident DMP behavior",
            "target-intranet RustFS/S3, network, concurrency, restart, or p95 behavior",
            "cache disk-full, eviction race, multi-Build concurrency, or prolonged outage",
            "Unified/raw cleanup apply and rollback-window completion",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    markdown = args.markdown if args.markdown.is_absolute() else ROOT / args.markdown
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": result_checks}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
