"""Fail-closed S0 evidence runner. Does not claim any S1-S8 product gate."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator
from protocol import normalize_identity
from test_protocol import manifest

ROOT = Path(__file__).resolve().parents[2]
DRAFT = ROOT / "contracts/drafts/qa-symbol-import"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--evidence-dir", type=Path, default=ROOT / "target/qa-symbol-import"
    )
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/qa-symbol-import/s0.json"
    )
    args = parser.parse_args()
    checks = []

    def check(name, passed, detail):
        checks.append(
            {"name": name, "status": "PASS" if passed else "FAIL", "detail": detail}
        )

    tests = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts/qa_symbol_import",
            "-p",
            "test_*.py",
            "-v",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    check("draft_protocol_vectors", tests.returncode == 0, tests.stderr)
    plan = json.loads((ROOT / "scripts/qa_symbol_import/cases.json").read_text())
    ids = [c["id"] for c in plan["cases"]]
    check(
        "all_required_cases_mapped",
        sorted(ids) == [f"QAI-C{i:02}" for i in range(1, 24)],
        {"count": len(ids)},
    )
    for case in plan["cases"]:
        check(
            case["id"] + "_plan",
            all(f in plan["fixtures"] for f in case["fixtures"])
            and all(case[k] for k in ("gates", "owner", "environment", "assertion")),
            {"fixtures": case["fixtures"], "execution_status": "NOT_RUN"},
        )
    for path in sorted((ROOT / "contracts").glob("*.schema.json")):
        old = subprocess.run(
            ["git", "show", "HEAD:" + path.relative_to(ROOT).as_posix()],
            cwd=ROOT,
            capture_output=True,
        )
        # Git worktree CRLF conversion is not a semantic edit; preserve published content.
        check(
            "frozen_" + path.name,
            old.returncode == 0
            and old.stdout.replace(b"\r\n", b"\n")
            == path.read_bytes().replace(b"\r\n", b"\n"),
            {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()},
        )
    inputs = {}
    for name in (
        "baseline.json",
        "local-compose-health.json",
        "legacy-inventory.json",
        "baseline-canonical-1.0.json",
    ):
        path = args.evidence_dir / name
        if not path.is_file():
            check("input_" + name, False, "not collected")
            continue
        inputs[name] = json.loads(path.read_text(encoding="utf-8"))
        check(
            "input_" + name,
            True,
            {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "path": str(path),
            },
        )
    if "baseline.json" in inputs:
        check(
            "core_fixture_baseline",
            inputs["baseline.json"]["status"] == "PASS",
            inputs["baseline.json"].get("scope"),
        )
    if "legacy-inventory.json" in inputs:
        legacy = inputs["legacy-inventory.json"]
        check("legacy_enumeration", legacy["enumeration_complete"], legacy["counts"])
    if "local-compose-health.json" in inputs:
        health = inputs["local-compose-health.json"]
        check(
            "health_baseline_recorded",
            health.get("object_store_checked") is True
            and "symbol_projection" in health,
            {
                "counts": health.get("counts"),
                "known_preexisting_differences": health.get("symbol_projection"),
                "receiver": "S2/S5/S7 must reconcile or explain before product gates; collection is not a zero-violation claim",
            },
        )
    if "baseline-canonical-1.0.json" in inputs:
        old = inputs["baseline-canonical-1.0.json"]
        old_schema = json.loads(
            (ROOT / "contracts/analysis-result-v1.schema.json").read_text()
        )
        new_schema = json.loads(
            (DRAFT / "analysis-result-v1.1.schema.json").read_text()
        )
        one = Draft202012Validator(old_schema)
        two = Draft202012Validator(new_schema)
        new = copy.deepcopy(old)
        new["schema_version"] = "1.1"
        new["symbol_resolution"] = {
            "selection_version": "pair-selection-v1",
            "resolution_evidence_fingerprint": "a" * 64,
            "manifest": {"object_key": "synthetic/manifest", "sha256": "b" * 64},
            "inspect_sha256": "c" * 64,
            "context_sha256": "d" * 64,
        }
        for index, module in enumerate(new["modules"]):
            selection = manifest([])["modules"][0]
            selection["module_index"] = index
            selection["identity"] = normalize_identity(
                {
                    "code_id": module.get("code_id"),
                    "debug_id": module.get("debug_id"),
                    "architecture": "x86_64",
                }
            )
            module.update(
                {"module_index": index, "selection": selection, "source_outcomes": []}
            )
        for thread in new["threads"]:
            for index, frame in enumerate(thread["frames"]):
                frame.update(
                    {
                        "module_index": None,
                        "unwind_method": "unknown",
                        "physical_frame_index": index,
                    }
                )
        check(
            "canonical_explicit_version_matrix",
            one.is_valid(old)
            and not two.is_valid(old)
            and two.is_valid(new)
            and not one.is_valid(new),
            {
                "new_sample": "synthetic schema exercise, NOT a reinterpreted historical Run or Core 1.1 output",
                "new_errors": [e.message for e in two.iter_errors(new)],
            },
        )
    report = {
        "schema_version": "qai-gate-evidence-v1",
        "gate": "QAI-G0",
        "status": "PASS" if all(c["status"] == "PASS" for c in checks) else "FAIL",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "environment": "local checkout + real local Compose read-only baseline; protocol drafts and synthetic vectors",
        "checks": checks,
        "reviewer": "Codex automated evidence check; human signoff not recorded",
        "later_gates": {
            f"QAI-G{i}": "NOT_PROVEN" if i == 1 else "NOT_RUN" for i in range(1, 9)
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "checks": len(checks),
                "output": str(args.output),
            }
        )
    )
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
