#!/usr/bin/env python3
"""Prove PostgreSQL plus zstd-only object backup/restore with a real MSVC DMP."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import tarfile
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
    semantic_summary,
    sha256_file,
    source_requests,
    symbols_dir,
)

DEFAULT_JSON = ROOT / "docs" / "evidence" / "pdb-storage-backup-restore-20260827.json"
DEFAULT_MD = ROOT / "docs" / "evidence" / "pdb-storage-backup-restore-20260827.md"
RUN_ROOT = ROOT / "target" / "pdb-storage-backup-restore"
MIGRATION_HEAD = "0009_delivery_v2_wire"


def migration_revision(project: str, mode: str, output_dir: Path) -> str:
    return compose(
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
        seed_action="inspect",
    ).stdout.strip()


def seed_json(
    project: str,
    mode: str,
    output_dir: Path,
    *args: str,
    check: bool = True,
) -> tuple[dict[str, Any] | None, int, str]:
    result = compose(
        project,
        mode,
        output_dir,
        "run",
        "--rm",
        "--no-deps",
        "seed",
        *args,
        check=check,
        seed_action="inspect",
    )
    parsed = parse_json_output(result) if result.returncode == 0 else None
    return parsed, result.returncode, (result.stderr or result.stdout)[-2000:]


def core_inspect(
    project: str, mode: str, output_dir: Path, output_name: str
) -> int:
    result = compose(
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
        f"/evidence/{output_name}",
        check=False,
        timeout=120,
        seed_action="inspect",
    )
    return result.returncode


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else None


def write_match_input(output_dir: Path) -> None:
    (output_dir / "match-input.json").write_text(
        json.dumps(match_input(), indent=2) + "\n", encoding="utf-8"
    )


def dump_database(project: str, mode: str, output_dir: Path) -> None:
    compose(
        project,
        mode,
        output_dir,
        "exec",
        "-T",
        "postgres",
        "pg_dump",
        "-U",
        "crashcap",
        "-d",
        "crashcap",
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--file=/evidence/postgres.dump",
        seed_action="inspect",
    )


def restore_database(project: str, mode: str, output_dir: Path) -> None:
    compose(
        project,
        mode,
        output_dir,
        "exec",
        "-T",
        "postgres",
        "pg_restore",
        "--exit-on-error",
        "--no-owner",
        "--no-acl",
        "-U",
        "crashcap",
        "-d",
        "crashcap",
        "/evidence/postgres.dump",
        seed_action="inspect",
    )


def down(project: str, mode: str, output_dir: Path) -> None:
    compose(
        project,
        mode,
        output_dir,
        "down",
        "--volumes",
        "--remove-orphans",
        check=False,
        timeout=300,
        seed_action="inspect",
    )


def backup_source(
    project: str, output_dir: Path, core_digest: str
) -> dict[str, Any]:
    mode = "filesystem"
    down(project, mode, output_dir)
    started = time.monotonic()
    try:
        compose(project, mode, output_dir, "up", "-d", "--wait", "gateway", timeout=600)
        startup_seconds = time.monotonic() - started
        inventory, _, _ = seed_json(project, mode, output_dir, "inspect")
        probe, _, _ = seed_json(project, mode, output_dir, "probe", "--kind", "pdb")
        inspect_returncode = core_inspect(
            project, mode, output_dir, "inspect-baseline.json"
        )
        core_started = time.monotonic()
        analyze = core_command(
            project,
            mode,
            output_dir,
            core_digest,
            suffix="-baseline",
            inspect_name="inspect-baseline.json",
        )
        core_seconds = time.monotonic() - core_started
        canonical = read_json(output_dir / "canonical-baseline.json")

        dump_database(project, mode, output_dir)
        backup, _, _ = seed_json(
            project,
            mode,
            output_dir,
            "backup",
            "--archive",
            "/evidence/blob-objects.tar",
        )
        dump_path = output_dir / "postgres.dump"
        archive_path = output_dir / "blob-objects.tar"
        if not dump_path.is_file() or not archive_path.is_file():
            raise VerificationFailure("backup media was not created on the host evidence mount")
        return {
            "startup_seconds": round(startup_seconds, 6),
            "migration_revision": migration_revision(project, mode, output_dir),
            "inventory": inventory,
            "direct_pdb_probe": probe,
            "inspect_returncode": inspect_returncode,
            "analyze_returncode": analyze.returncode,
            "core_seconds": round(core_seconds, 6),
            "canonical": canonical,
            "postgres_dump": {
                "format": "postgresql-custom",
                "size": dump_path.stat().st_size,
                "sha256": sha256_file(dump_path),
            },
            "object_backup": backup,
            "unified_mount_file_count": len(
                [path for path in symbols_dir(mode, output_dir).rglob("*") if path.is_file()]
            ),
        }
    finally:
        down(project, mode, output_dir)


def restored_target(
    project: str, output_dir: Path, core_digest: str
) -> dict[str, Any]:
    mode = "http"
    down(project, mode, output_dir)
    started = time.monotonic()
    try:
        compose(
            project,
            mode,
            output_dir,
            "up",
            "-d",
            "--wait",
            "postgres",
            timeout=300,
            seed_action="inspect",
        )
        restore_database(project, mode, output_dir)
        restore, _, _ = seed_json(
            project,
            mode,
            output_dir,
            "restore",
            "--archive",
            "/evidence/blob-objects.tar",
        )
        compose(
            project,
            mode,
            output_dir,
            "up",
            "-d",
            "--wait",
            "gateway",
            timeout=600,
            seed_action="inspect",
        )
        startup_seconds = time.monotonic() - started
        inventory, _, _ = seed_json(project, mode, output_dir, "inspect")
        probe, _, _ = seed_json(project, mode, output_dir, "probe", "--kind", "pdb")
        before_logs = compose(
            project,
            mode,
            output_dir,
            "logs",
            "--no-color",
            "symbol-source",
            seed_action="inspect",
        ).stdout
        before_requests = source_requests(before_logs)
        inspect_returncode = core_inspect(
            project, mode, output_dir, "inspect-restored.json"
        )
        core_started = time.monotonic()
        analyze = core_command(
            project,
            mode,
            output_dir,
            core_digest,
            suffix="-restored",
            inspect_name="inspect-restored.json",
        )
        core_seconds = time.monotonic() - core_started
        after_logs = compose(
            project,
            mode,
            output_dir,
            "logs",
            "--no-color",
            "symbol-source",
            seed_action="inspect",
        ).stdout
        requests = source_requests(after_logs)[len(before_requests) :]
        symbolicator_id = compose(
            project,
            mode,
            output_dir,
            "ps",
            "-q",
            "symbolicator",
            seed_action="inspect",
        ).stdout.strip()
        return {
            "startup_seconds": round(startup_seconds, 6),
            "migration_revision": migration_revision(project, mode, output_dir),
            "inventory": inventory,
            "direct_pdb_probe": probe,
            "object_restore": restore,
            "inspect_returncode": inspect_returncode,
            "analyze_returncode": analyze.returncode,
            "core_seconds": round(core_seconds, 6),
            "cold_source_requests": requests,
            "canonical": read_json(output_dir / "canonical-restored.json"),
            "unified_mount_file_count": len(
                [path for path in symbols_dir(mode, output_dir).rglob("*") if path.is_file()]
            ),
            "symbolicator_image_id": docker_inspect(symbolicator_id, "{{.Image}}"),
        }
    finally:
        down(project, mode, output_dir)


def corrupt_object_member(source: Path, destination: Path) -> dict[str, Any]:
    shutil.copyfile(source, destination)
    with tarfile.open(destination, "r:") as bundle:
        member = next(
            (
                item
                for item in bundle.getmembers()
                if item.isfile() and item.name.startswith("objects/") and item.size > 0
            ),
            None,
        )
        if member is None:
            raise VerificationFailure("object backup had no corruptible payload member")
        offset = member.offset_data + member.size // 2
        member_name = member.name.rsplit("/", 1)[-1]
    with destination.open("r+b") as handle:
        handle.seek(offset)
        original = handle.read(1)
        if len(original) != 1:
            raise VerificationFailure("could not read selected object backup byte")
        handle.seek(offset)
        handle.write(bytes([original[0] ^ 0x01]))
    return {
        "member_leaf": member_name,
        "size_preserved": destination.stat().st_size == source.stat().st_size,
        "source_sha256": sha256_file(source),
        "corrupt_sha256": sha256_file(destination),
    }


def corrupt_restore(project: str, output_dir: Path) -> dict[str, Any]:
    mode = "http"
    corrupt_path = output_dir / "blob-objects-corrupt.tar"
    injection = corrupt_object_member(output_dir / "blob-objects.tar", corrupt_path)
    down(project, mode, output_dir)
    try:
        compose(
            project,
            mode,
            output_dir,
            "up",
            "-d",
            "--wait",
            "postgres",
            timeout=300,
            seed_action="inspect",
        )
        restore_database(project, mode, output_dir)
        _restore, returncode, error_tail = seed_json(
            project,
            mode,
            output_dir,
            "restore",
            "--archive",
            "/evidence/blob-objects-corrupt.tar",
            check=False,
        )
        inventory, inspect_returncode, _ = seed_json(
            project, mode, output_dir, "inspect"
        )
        return {
            "injection": injection,
            "restore_returncode": returncode,
            "sha256_failure_reported": "failed SHA-256 verification" in error_tail,
            "inspect_returncode": inspect_returncode,
            "migration_revision": migration_revision(project, mode, output_dir),
            "inventory": inventory,
        }
    finally:
        down(project, mode, output_dir)


def schema_errors(documents: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    schema = json.loads(
        (ROOT / "contracts" / "analysis-result-v1.schema.json").read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    return {
        name: [
            {
                "path": "/" + "/".join(str(part) for part in error.absolute_path),
                "message": error.message,
            }
            for error in validator.iter_errors(document)
        ]
        for name, document in documents.items()
        if isinstance(document, dict)
    }


def make_checks(
    baseline: dict[str, Any], restored: dict[str, Any], corrupt: dict[str, Any]
) -> list[dict[str, Any]]:
    baseline_canonical = baseline["canonical"]
    restored_canonical = restored["canonical"]
    errors = schema_errors(
        {"baseline": baseline_canonical, "restored": restored_canonical}
    )
    baseline_inventory = baseline["inventory"]
    restored_inventory = restored["inventory"]
    corrupt_inventory = corrupt["inventory"]
    corrupt_blobs = corrupt_inventory.get("blobs", []) if corrupt_inventory else []
    checks: list[tuple[str, bool, Any]] = [
        (
            "source and restored PostgreSQL databases are at the delivery-v2 migration head",
            baseline["migration_revision"] == MIGRATION_HEAD
            and restored["migration_revision"] == MIGRATION_HEAD
            and corrupt["migration_revision"] == MIGRATION_HEAD,
            {
                "baseline": baseline["migration_revision"],
                "restored": restored["migration_revision"],
                "corrupt": corrupt["migration_revision"],
            },
        ),
        (
            "PostgreSQL custom dump and checksummed zstd-only object archive were created",
            baseline["postgres_dump"]["size"] > 0
            and re.fullmatch(r"[0-9a-f]{64}", baseline["postgres_dump"]["sha256"])
            is not None
            and baseline["object_backup"]["format"] == "artifact-blob-object-backup-v1"
            and baseline["object_backup"]["object_count"] == 2
            and baseline["object_backup"]["total_bytes"] > 0,
            {
                "postgres_dump": baseline["postgres_dump"],
                "object_backup": baseline["object_backup"],
            },
        ),
        (
            "fresh restore preserved all Artifact Blob database and object identities",
            baseline_inventory == restored_inventory
            and restored["object_restore"]["object_count"] == 2
            and restored_inventory["physical_object_count"] == 2
            and restored_inventory["physical_objects_are_zstd_only"] is True
            and all(
                blob["payload_present"]
                and blob["payload_observed_sha256"] == blob["payload_sha256"]
                and not blob["raw_object_present"]
                for blob in restored_inventory["blobs"]
            ),
            {
                "baseline_inventory": baseline_inventory,
                "restored_inventory": restored_inventory,
                "object_restore": restored["object_restore"],
            },
        ),
        (
            "restored DB-backed source returned the exact logical PDB bytes",
            restored["direct_pdb_probe"]["http_status"] == 200
            and restored["direct_pdb_probe"]["matches_logical_identity"] is True,
            restored["direct_pdb_probe"],
        ),
        (
            "baseline and restored real-DMP Core executions completed",
            baseline["inspect_returncode"] == 0
            and baseline["analyze_returncode"] == 0
            and restored["inspect_returncode"] == 0
            and restored["analyze_returncode"] == 0,
            {
                "baseline_inspect": baseline["inspect_returncode"],
                "baseline_analyze": baseline["analyze_returncode"],
                "restored_inspect": restored["inspect_returncode"],
                "restored_analyze": restored["analyze_returncode"],
            },
        ),
        (
            "baseline and restored outputs validate against Canonical v1",
            len(errors) == 2 and all(not value for value in errors.values()),
            errors,
        ),
        (
            "restored Canonical equals the pre-backup baseline except run timestamps",
            isinstance(baseline_canonical, dict)
            and isinstance(restored_canonical, dict)
            and normalized_canonical(baseline_canonical)
            == normalized_canonical(restored_canonical),
            {
                "baseline_normalized_sha256": canonical_digest(baseline_canonical),
                "restored_normalized_sha256": canonical_digest(restored_canonical),
            },
        ),
        (
            (
                "restored crash kept exception, crash thread, symbols, source lines, quality, "
                "and Exact"
            ),
            isinstance(restored_canonical, dict) and expected_semantics(restored_canonical),
            semantic_summary(restored_canonical)
            if isinstance(restored_canonical, dict)
            else None,
        ),
        (
            "restored cold run fetched DB-backed symbols with no Unified fallback",
            restored["unified_mount_file_count"] == 0
            and any(
                request["status"] in {200, 206}
                and request["path"].endswith(("/debuginfo", "/executable"))
                for request in restored["cold_source_requests"]
            ),
            {
                "unified_mount_file_count": restored["unified_mount_file_count"],
                "source_requests": restored["cold_source_requests"],
            },
        ),
        (
            "tampered object archive was rejected and left the fresh object store empty",
            corrupt["injection"]["size_preserved"] is True
            and corrupt["injection"]["source_sha256"]
            != corrupt["injection"]["corrupt_sha256"]
            and corrupt["restore_returncode"] != 0
            and corrupt["sha256_failure_reported"] is True
            and corrupt["inspect_returncode"] == 0
            and corrupt_inventory["physical_object_count"] == 0
            and all(not blob["payload_present"] for blob in corrupt_blobs),
            {
                "injection": corrupt["injection"],
                "restore_returncode": corrupt["restore_returncode"],
                "sha256_failure_reported": corrupt["sha256_failure_reported"],
                "physical_object_count": corrupt_inventory["physical_object_count"],
                "payload_present": [blob["payload_present"] for blob in corrupt_blobs],
            },
        ),
    ]
    return [
        {"name": name, "status": "PASS" if passed else "FAIL", "evidence": evidence}
        for name, passed, evidence in checks
    ]


def public_run(value: dict[str, Any]) -> dict[str, Any]:
    result = {key: child for key, child in value.items() if key != "canonical"}
    canonical = value.get("canonical")
    result["canonical_normalized_sha256"] = canonical_digest(canonical)
    result["canonical_semantics"] = (
        semantic_summary(canonical) if isinstance(canonical, dict) else None
    )
    return result


def render_markdown(report: dict[str, Any]) -> str:
    baseline = report["runs"]["baseline"]
    restored = report["runs"]["restored"]
    rows = [
        "# PDB storage backup/restore real-DMP evidence",
        "",
        f"Status: **{report['status']}**",
        "",
        (
            "This is an isolated local Docker Desktop pre-UAT. It restores a PostgreSQL "
            "custom dump and checksummed zstd-only object archive into fresh volumes, then "
            "reanalyzes the real generated x64 MSVC minidump."
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
            f"- PostgreSQL dump SHA-256: `{baseline['postgres_dump']['sha256']}`",
            f"- Object archive SHA-256: `{baseline['object_backup']['archive_sha256']}`",
            f"- Object count: {baseline['object_backup']['object_count']}",
            f"- Baseline Canonical SHA-256: `{baseline['canonical_normalized_sha256']}`",
            f"- Restored Canonical SHA-256: `{restored['canonical_normalized_sha256']}`",
            f"- Restored Unified file count: {restored['unified_mount_file_count']}",
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
    output_dir = run_root / "evidence"
    output_dir.mkdir()
    write_match_input(output_dir)

    build_started = time.monotonic()
    compose(
        "crash-cap-pdb-zstd-backup-build",
        "http",
        output_dir,
        "build",
        "migrations",
        "gateway",
        "core",
        timeout=1200,
        seed_action="inspect",
    )
    build_seconds = time.monotonic() - build_started
    core_digest = docker_inspect("crash-cap/dmp-core:pdb-storage-real-dmp-uat", "{{.Id}}")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", core_digest) is None:
        raise VerificationFailure(f"invalid Core image digest: {core_digest!r}")

    baseline = backup_source(
        f"crash-cap-pdb-zstd-backup-source-{stamp.lower()}", output_dir, core_digest
    )
    restored = restored_target(
        f"crash-cap-pdb-zstd-backup-restored-{stamp.lower()}", output_dir, core_digest
    )
    corrupt = corrupt_restore(
        f"crash-cap-pdb-zstd-backup-corrupt-{stamp.lower()}", output_dir
    )
    checks = make_checks(baseline, restored, corrupt)
    report = {
        "schema_version": "pdb-storage-backup-restore-v1",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL",
        "scope": (
            "isolated local Docker Desktop; fresh PostgreSQL and local object-store volumes; "
            "real generated x64 MSVC DMP/PE/PDB; not target-intranet UAT"
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
        "runs": {
            "baseline": public_run(baseline),
            "restored": public_run(restored),
            "corrupt_restore": corrupt,
        },
        "not_proven": [
            "real lightstreamer or other product-incident DMP equivalence",
            "target-intranet PostgreSQL, RustFS/S3, networking, concurrency, or performance",
            "target backup tooling, retention, encryption, operator signing, and disaster recovery",
            "Unified/raw/legacy cleanup apply and rollback-window completion",
        ],
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    markdown = args.markdown if args.markdown.is_absolute() else ROOT / args.markdown
    output.parent.mkdir(parents=True, exist_ok=True)
    markdown.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": report["status"], "checks": checks}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
