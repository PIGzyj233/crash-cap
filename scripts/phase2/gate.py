from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_JSON = ROOT / "docs" / "evidence" / "phase2-gate.json"
OUTPUT_MD = ROOT / "docs" / "evidence" / "phase2-gate.md"
NATIVE_PUBLISHER = (
    ROOT / "tools" / "crashcap" / "windows-x86_64" / "crashcap.exe"
    if os.name == "nt"
    else ROOT / "tools" / "crashcap" / "linux-x86_64" / "crashcap"
)


STEPS: list[tuple[str, list[str], Path]] = [
    ("markdown-links", [sys.executable, "scripts/ci/check_markdown_links.py"], ROOT),
    ("rust-format", ["cargo", "fmt", "--check"], ROOT),
    (
        "rust-clippy",
        [
            "cargo",
            "clippy",
            "--workspace",
            "--all-targets",
            "--locked",
            "--",
            "-D",
            "warnings",
        ],
        ROOT,
    ),
    ("rust-tests-and-contracts", ["cargo", "test", "--workspace", "--locked"], ROOT),
    ("schema-matrix", [sys.executable, "scripts/schema/validate.py"], ROOT),
    ("python-lint", ["uv", "run", "ruff", "check", "."], ROOT / "platform"),
    (
        "pdb-storage-verifier-lint",
        [
            "uv",
            "run",
            "ruff",
            "check",
            "--config",
            "pyproject.toml",
            "../scripts/symbolicator/seed_database_zstd_source.py",
            "../scripts/symbolicator/verify_database_zstd_real_dmp.py",
            "../scripts/symbolicator/verify_database_zstd_backup_restore.py",
            "../scripts/symbolicator/verify_database_zstd_source_recovery.py",
        ],
        ROOT / "platform",
    ),
    (
        "ops-backup-shell-syntax",
        ["bash", "-n", "scripts/phase1/ops_backup_restore.sh"],
        ROOT,
    ),
    (
        "deploy-linux-shell-syntax",
        ["bash", "-n", "scripts/phase1/deploy_linux.sh"],
        ROOT,
    ),
    (
        "python-types",
        ["uv", "run", "mypy", "api", "worker", "cli"],
        ROOT / "platform",
    ),
    ("platform-tests", ["uv", "run", "pytest", "-q"], ROOT / "platform"),
    ("publisher-cli-contract", [str(NATIVE_PUBLISHER), "--help"], ROOT),
    ("frontend-openapi", ["pnpm", "openapi:check"], ROOT / "platform" / "frontend"),
    ("frontend-tests", ["pnpm", "test", "--", "--run"], ROOT / "platform" / "frontend"),
    ("frontend-types", ["pnpm", "lint"], ROOT / "platform" / "frontend"),
    ("frontend-build", ["pnpm", "build"], ROOT / "platform" / "frontend"),
]


def _run(name: str, command: list[str], cwd: Path) -> dict[str, Any]:
    started = time.perf_counter()
    resolved_command = command.copy()
    executable = shutil.which(resolved_command[0])
    if executable is None:
        return {
            "name": name,
            "command": command,
            "cwd": str(cwd),
            "status": "FAIL",
            "returncode": 127,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "output_tail": f"executable not found on PATH: {command[0]}",
        }
    resolved_command[0] = executable
    completed = subprocess.run(  # noqa: S603 - commands are a repository-owned fixed gate matrix
        resolved_command,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    return {
        "name": name,
        "command": command,
        "cwd": str(cwd),
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "returncode": completed.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "output_tail": "\n".join(output.splitlines()[-40:]),
    }


def _markdown(report: dict[str, Any]) -> str:
    integrations = report["integration_services"]
    postgresql_status = (
        "executed" if integrations["postgresql"] else "skipped (CRASH_CAP_TEST_DATABASE_URL unset)"
    )
    redis_status = (
        "executed" if integrations["redis"] else "skipped (CRASHCAP_TEST_REDIS_URL unset)"
    )
    lines = [
        "# Phase 2 Gate Evidence",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Decision: **{report['decision']}**",
        f"- Passed: `{report['passed_steps']}/{report['total_steps']}`",
        (
            "- Scope: local source, contract, PostgreSQL migration, Redis queue persistence, "
            "platform, CLI, and frontend verification; this is not proof that an external "
            "intranet deployment or remote CI runner executed the workflow."
        ),
        (
            f"- Integration services: PostgreSQL `{postgresql_status}`; Redis `{redis_status}`."
        ),
        "",
        "| Step | Result | Seconds | Command |",
        "| --- | --- | ---: | --- |",
    ]
    for step in report["steps"]:
        command = " ".join(step["command"]).replace("|", "\\|")
        lines.append(
            f"| `{step['name']}` | {step['status']} | {step['duration_seconds']} | `{command}` |"
        )
    lines.extend(
        [
            "",
            "## Gate assertions",
            "",
            (
                "- MSVC is the only producer marked `supported`; clang-cl and Crashpad remain "
                "`experimental` until producer-specific fixtures pass the frozen Golden metrics."
            ),
            (
                "- Content Build registration is unique by `(workspace_id, fingerprint_version, "
                "content_fingerprint)`; local and CI Publications can point to the same Build."
            ),
            (
                "- Publication readiness requires every declared PE/PDB to match its expected "
                "size/SHA-256 and pass identity validation; Ready atomically seals the Build."
            ),
            (
                "- Workspace-scoped Artifact Blobs reuse only server-verified PE/PDB bytes; "
                "every Build retains its exact expectations, and pair mismatch does not poison "
                "an individually valid Blob."
            ),
            (
                "- PostgreSQL/RustFS backup refuses an existing target, hashes every mirrored "
                "file with relative paths, and verifies the complete manifest before restore; "
                "crash-analysis equivalence remains a separate required Gate."
            ),
            (
                "- Source bundle ingest rejects traversal, symlinks, encryption, nested "
                "archives, oversized input, and excessive compression ratio before source is "
                "consumed."
            ),
            (
                "- Symbol upload can target an affected Build/module, batch reprocess preserves "
                "old Runs and Occurrence count, and progress is available by SSE with polling "
                "fallback."
            ),
            (
                "- Workspace in-app rules are versioned in Run Spec; rule changes create new "
                "Runs and cannot override the system-module deny floor."
            ),
            (
                "- Existing Build Manifest v1 and Canonical v1 readers remain covered by the "
                "compatibility suite."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    results = []
    for name, command, cwd in STEPS:
        result = _run(name, command, cwd)
        results.append(result)
        print(f"[{result['status']}] {name} ({result['duration_seconds']}s)")
        if result["status"] == "FAIL":
            print(result["output_tail"], file=sys.stderr)
    passed = sum(step["status"] == "PASS" for step in results)
    report = {
        "schema_version": "1.0",
        "phase": "Phase 2",
        "generated_at": datetime.now(UTC).isoformat(),
        "decision": "PASS / GO" if passed == len(results) else "FAIL / NO-GO",
        "passed_steps": passed,
        "total_steps": len(results),
        "integration_services": {
            "postgresql": bool(os.environ.get("CRASH_CAP_TEST_DATABASE_URL")),
            "redis": bool(os.environ.get("CRASHCAP_TEST_REDIS_URL")),
        },
        "steps": results,
    }
    OUTPUT_JSON.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    OUTPUT_MD.write_text(_markdown(report), encoding="utf-8")
    print(f"evidence_json={OUTPUT_JSON}")
    print(f"evidence_markdown={OUTPUT_MD}")
    print(f"decision={report['decision']}")
    return 0 if report["decision"] == "PASS / GO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
