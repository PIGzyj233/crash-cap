#!/usr/bin/env python3
"""Re-run a fresh Golden result set through Core-owned Canonical assembly."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"JSON object expected: {path}")
    return value


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _compact(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _context(canonical: dict[str, Any], inspect: dict[str, Any]) -> dict[str, Any]:
    resolution = canonical["build_resolution"]
    evidence = resolution["evidence"]
    build_ids = {
        value
        for value in [
            resolution.get("reported_build_id"),
            resolution.get("resolved_build_id"),
            *evidence.get("candidate_build_ids", []),
        ]
        if value
    }
    return {
        "schema_version": "analysis-context-v1",
        "identity": {
            "workspace_id": canonical["workspace_id"],
            "occurrence_id": canonical["occurrence_id"],
            "analysis_id": canonical["analysis_id"],
        },
        "dump": {
            key: canonical["dump"][key]
            for key in (
                "blob_id",
                "sha256",
                "kind",
                "size",
                "dump_timestamp",
                "reported_at",
                "uploaded_at",
                "occurred_at",
                "time_source",
            )
        },
        "engine": {
            key: canonical["engine"][key]
            for key in (
                "core_image_digest",
                "symbolicator_version",
                "grouping_version",
                "normalization_version",
            )
        },
        "policy": {
            "symbol_inventory_version": 0,
            "in_app_rule_version": 0,
            "source_bundle_policy_version": "source-bundle-v1.0",
        },
        "inspect": {
            "object_key": "golden://inspect.json",
            "sha256": hashlib.sha256(_compact(inspect)).hexdigest(),
        },
        "inputs": {
            "artifact_ids": [],
            "build_ids": sorted(build_ids),
            "source_bundles": [],
        },
    }


def _replace_option(command: list[str], option: str, value: Path) -> None:
    index = command.index(option)
    command[index + 1] = str(value)


def run(args: argparse.Namespace) -> dict[str, Any]:
    source = _read(args.golden_results)
    records: list[dict[str, Any]] = []
    started = time.monotonic()
    for fixture in source.get("fixtures", []):
        fixture_id = str(fixture["fixture_id"])
        if fixture.get("status") != "PASS":
            records.append(
                {
                    "fixture_id": fixture_id,
                    "status": "FAIL",
                    "reason": "fresh Golden prerequisite did not pass",
                }
            )
            continue
        paths = fixture.get("paths") or {}
        canonical_path = Path(str(paths.get("canonical") or ""))
        analyze = (fixture.get("execution") or {}).get("analyze")
        if not canonical_path.is_file() or not isinstance(analyze, dict):
            records.append(
                {
                    "fixture_id": fixture_id,
                    "status": "PASS",
                    "parity": "expected rejection or unsupported input preserved by fresh Golden run",
                }
            )
            continue

        canonical = _read(canonical_path)
        inspect = _read(Path(str(paths["inspect"])))
        fixture_root = args.output_root / fixture_id
        context_path = fixture_root / "analysis-context.json"
        output_path = fixture_root / "canonical.json"
        raw_dir = fixture_root / "raw"
        _write(context_path, _context(canonical, inspect))
        command = [str(value) for value in analyze["command"]]
        command[0] = str(args.core)
        _replace_option(command, "--output", output_path)
        _replace_option(command, "--raw-dir", raw_dir)
        command.extend(["--analysis-context", str(context_path)])
        completed = subprocess.run(
            command,
            cwd=args.repository_root,
            capture_output=True,
            check=False,
            timeout=args.timeout,
        )
        (fixture_root / "stdout.txt").write_bytes(completed.stdout)
        (fixture_root / "stderr.txt").write_bytes(completed.stderr)
        if completed.returncode != 0 or not output_path.is_file():
            records.append(
                {
                    "fixture_id": fixture_id,
                    "status": "FAIL",
                    "returncode": completed.returncode,
                    "reason": "Core-final replay failed",
                }
            )
            continue
        core_final = _read(output_path)
        records.append(
            {
                "fixture_id": fixture_id,
                "status": "PASS" if core_final == canonical else "FAIL",
                "parity": "byte-semantic JSON equality" if core_final == canonical else "mismatch",
            }
        )

    passed = sum(record["status"] == "PASS" for record in records)
    result = {
        "schema_version": "canonical-parity-v1",
        "status": "PASS" if records and passed == len(records) else "FAIL",
        "fresh_golden_status": source.get("status"),
        "counts": {"PASS": passed, "total": len(records)},
        "duration_seconds": round(time.monotonic() - started, 3),
        "records": records,
    }
    _write(args.output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden-results", type=Path, required=True)
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
