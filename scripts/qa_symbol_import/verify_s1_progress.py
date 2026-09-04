"""Record S1 sub-gate evidence without claiming the unfinished whole G1 passed."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from partitioned_source import collect_partition

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "target/qa-symbol-import"


def main():
    checks = []
    commands = [
        ["cargo", "fmt", "--all", "--check"],
        ["cargo", "test", "-p", "dmp-core", "--locked"],
        [
            "cargo",
            "test",
            "-p",
            "dmp-core",
            "--locked",
            "--test",
            "frozen_unwind",
            "--",
            "--ignored",
        ],
        ["cargo", "build", "-p", "dmp-core", "--locked"],
        [sys.executable, "scripts/qa_symbol_import/qualify_provenance.py"],
        [sys.executable, "scripts/qa_symbol_import/qualify_comparison.py"],
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
    ]
    for index, command in enumerate(commands):
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
        log = OUT / f"s1-command-{index}.txt"
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        checks.append(
            {
                "command": command,
                "exit_code": result.returncode,
                "log": log.relative_to(ROOT).as_posix(),
                "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            }
        )
        print(json.dumps({"command": command, "exit_code": result.returncode}), flush=True)
        if result.returncode:
            break
    names = [
        "source-qualification-partitioned.json",
        "source-qualification-diagnostics.json",
        "legacy-qualification.json",
        "frozen-unwind.json",
        "provenance-qualification.json",
        "legacy-locations.json",
        "comparison-qualification.json",
    ]
    inputs = {}
    refs = []
    for name in names:
        path = OUT / name
        data = path.read_bytes()
        inputs[name] = json.loads(data)
        refs.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(data).hexdigest(),
                "bytes": len(data),
            }
        )
    partition = inputs[names[0]]
    inspect = json.loads((OUT / "baseline-inspect.json").read_text())
    pc = int(inspect["exception"]["address"], 0)
    for index, pair in enumerate(partition["partition_pairs"]):
        expected_pc = hex(pc + index * 0x1000000)
        job = {
            "key": pair["pair_id"],
            "frame_refs": [(0, index, index)],
            "request": {"stacktraces": [{"frames": [{"instruction_addr": expected_pc}]}]},
        }
        collect_partition(job, partition["raw_results"][f"partition_{index}"])
    legacy = inputs[names[2]]
    comparison = inputs["comparison-qualification.json"]
    comparison_hashes_valid = all(
        hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
        for path, digest in comparison["hashes"].items()
    )
    locations = inputs["legacy-locations.json"]
    locations_script_current = (
        locations["script_sha256"]
        == hashlib.sha256(
            (ROOT / "scripts/qa_symbol_import/qualify_legacy_locations.py").read_bytes()
        ).hexdigest()
    )
    source_checks = [
        {"id": c["id"], "status": c["status"], "detail": c["detail"]}
        for c in partition["cases"]
        if c["id"].startswith(("partition_", "all_partitioned", "blocked_"))
    ]
    control = partition["raw_results"]["whole_request_two_sources_control"]["stacktraces"][0][
        "frames"
    ]
    changed = subprocess.check_output(
        ["git", "diff", "--name-only"], cwd=ROOT, text=True
    ).splitlines()
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard"], cwd=ROOT, text=True
    ).splitlines()
    current_files = [
        {"path": p, "sha256": hashlib.sha256((ROOT / p).read_bytes()).hexdigest()}
        for p in sorted(set(changed + untracked))
        if (ROOT / p).is_file()
    ]
    passed = (
        len(checks) == len(commands)
        and all(c["exit_code"] == 0 for c in checks)
        and all(value["status"] == "PASS" for value in inputs.values())
        and len(partition["partition_pairs"]) == 200
        and comparison_hashes_valid
        and locations_script_current
        and comparison["skipped"] == 0
    )
    report = {
        "schema_version": "qai-s1-progress-v1",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "workspace_files": current_files,
        "status": "PASS" if passed else "FAIL",
        "scope": "S1 source/diagnostics/provenance plus local legacy availability and pure comparison; not whole G1",
        "QAI-G1": "NOT_PROVEN",
        "subtasks": {
            "QAI-1.1": "PASS" if passed else "FAIL",
            "QAI-1.2": "PASS" if passed else "FAIL",
            "QAI-1.3": "NOT_PROVEN",
            "QAI-1.4": "NOT_PROVEN",
        },
        "commands": checks,
        "evidence": refs,
        "source_checks": source_checks,
        "whole_request_control_functions": [f.get("function") for f in control],
        "partition_physical_pc_checks": len(partition["partition_pairs"]),
        "legacy_summary": legacy["qualification_summary"],
        "comparison_summary": {
            k: comparison[k] for k in ("tests", "vectors", "skipped", "decisions")
        },
        "legacy_locations_summary": {
            "counts": locations["counts"],
            "verified_blob_payloads": sum(
                b["status"] == "verified_bytes" for b in locations["blobs"]
            ),
            "not_global_pair_admission": True,
        },
        "current_routes": [
            {
                "run_id": r["run_id"],
                "occurrence_id": r["occurrence_id"],
                "qualification": r["legacy_qualification"],
            }
            for r in legacy["runs"]
            if r["is_current"]
        ],
        "remaining": [
            "Historical context/pair evidence projection into candidate comparison, without rewriting old records",
            "Explicit new-version Current continuity with creation-order and correction rules",
            "Freeze all machine contracts; local pure comparator vectors now qualified",
            "S2-S8 production compatibility, catalog, demand, Current, browser, CI and target gates",
        ],
    }
    (OUT / "s1-progress.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "QAI-G1": report["QAI-G1"],
                "subtasks": report["subtasks"],
            }
        )
    )
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
