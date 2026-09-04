"""Collect local compatibility evidence without claiming the full QAI-G2 gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "target/qa-symbol-import"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def junit(path):
    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    return {
        "tests": len(cases),
        "failed": sum(c.find("failure") is not None or c.find("error") is not None for c in cases),
        "skipped": sum(c.find("skipped") is not None for c in cases),
        "skip_reasons": sorted(
            {c.find("skipped").get("message", "") for c in cases if c.find("skipped") is not None}
        ),
    }


def main():
    python = junit(OUT / "compatibility-python.xml")
    focused = junit(OUT / "compatibility-focused.xml")
    frontend = json.loads((OUT / "compatibility-frontend.json").read_text(encoding="utf-8"))
    postgres = json.loads((OUT / "compatibility-postgres.json").read_text(encoding="utf-8"))
    checks = {
        "platform_regression_no_failures": python["tests"] > 0 and python["failed"] == 0,
        "focused_inputs_and_reader_no_skips": focused["tests"] > 0
        and focused["failed"] == focused["skipped"] == 0,
        "frontend_no_failures_or_pending": frontend["success"]
        and frontend["numTotalTests"] > 0
        and frontend["numFailedTests"] == frontend["numPendingTests"] == 0,
        "real_postgresql_roundtrip": postgres["status"] == "PASS"
        and postgres["owned_container_removed"]
        and not postgres["application_database_touched"],
        "postgres_evidence_matches_source": all(
            sha(ROOT / p) == digest for p, digest in postgres["hashes"].items()
        ),
        "old_canonical_contract_unchanged": (
            ROOT / "contracts/analysis-result-v1.schema.json"
        ).read_bytes()
        == subprocess.check_output(
            ["git", "show", "HEAD:contracts/analysis-result-v1.schema.json"], cwd=ROOT
        ),
    }
    paths = [
        OUT / name
        for name in (
            "compatibility-python.xml",
            "compatibility-focused.xml",
            "compatibility-frontend.json",
            "compatibility-postgres.json",
            "compatibility-postgres.xml",
            "compatibility-postgres.log",
        )
    ]
    build = ROOT / "platform/frontend/dist"
    assets = sorted(build.glob("assets/*"))
    checks["frontend_build_present"] = (build / "index.html").is_file() and bool(assets)
    changed = subprocess.check_output(
        ["git", "diff", "--name-only"], cwd=ROOT, text=True
    ).splitlines()
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True
    ).splitlines()
    report = {
        "schema_version": "qai-compatibility-progress-v1",
        "time_utc": datetime.now(UTC).isoformat(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "scope": "Local frozen-input and dual-reader preparation, including one real PostgreSQL migration roundtrip",
        "QAI-G1": "NOT_PROVEN",
        "QAI-G2": "NOT_PROVEN",
        "checks": checks,
        "platform_regression": python,
        "focused_regression": focused,
        "frontend": {
            k: frontend[k]
            for k in (
                "numTotalTests",
                "numPassedTests",
                "numFailedTests",
                "numPendingTests",
                "success",
            )
        },
        "postgres": {
            k: postgres[k] for k in ("postgres_version", "image_id", "owned_container_removed")
        },
        "evidence": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha(p)} for p in paths],
        "frontend_build": [
            {"path": p.relative_to(ROOT).as_posix(), "sha256": sha(p)}
            for p in [build / "index.html", *assets]
            if p.is_file()
        ],
        "workspace_files": [
            {"path": p, "sha256": sha(ROOT / p)}
            for p in sorted(set(changed + untracked))
            if (ROOT / p).is_file()
        ],
        "remaining": [
            "Native Core 1.1 output and complete old-Current continuity",
            "Freeze all protocols, including verified policy projection",
            "New Worker/task path, catalog/demand migrations and end-to-end semantic validation",
            "Pinned compatible deployment images, mixed-version restart and in-flight tasks",
            "Browser UAT, remote CI and target-environment rollout/rollback gates",
        ],
        "boundary": "The broad Python run retains explicit environment skips; the targeted PostgreSQL migration run covers only its one skipped test. SQLite and synthetic Canonical reader fixtures are not native 1.1 analysis or target deployment proof.",
    }
    (OUT / "compatibility-progress.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("status", "QAI-G1", "QAI-G2", "checks", "focused_regression", "frontend")
            }
        )
    )
    raise SystemExit(0 if all(checks.values()) else 1)


if __name__ == "__main__":
    main()
