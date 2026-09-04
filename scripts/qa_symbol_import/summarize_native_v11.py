"""Bind the explicit native Core lanes to their actual output and source bytes.

This summarizes existing successful runs, never activates a writer, and does
not turn a fixture context into an analysis-context-v2 / Worker qualification.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from protocol import digest, evidence_fingerprint, raw_hash, validate_manifest

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "target/qa-symbol-import"
NATIVE = OUT / "native-v11"


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def main() -> None:
    lanes = {}
    for name, expected_passed, expected_ignored in (("unit", 71, 2), ("native", 2, 0)):
        path = OUT / f"core-v11-{name}.log"
        log = path.read_text(encoding="utf-8", errors="replace")
        results = re.findall(r"test result: ok\. (\d+) passed; (\d+) failed; (\d+) ignored", log)
        if not results or "test result: FAILED" in log or "error:" in log:
            raise RuntimeError(f"{name} lane is not successful")
        counts = [sum(int(result[i]) for result in results) for i in range(3)]
        if counts != [expected_passed, 0, expected_ignored]:
            raise RuntimeError(f"unexpected {name} counts: {counts}")
        lanes[name] = dict(zip(("passed", "failed", "ignored"), counts, strict=True))
    native = read(NATIVE / "qualification.json")
    canonical = read(NATIVE / "canonical.json")
    raw = read(NATIVE / "raw-selected.json")
    manifest = read(NATIVE / "manifest.json")
    validate_manifest(manifest)
    resolution = canonical["symbol_resolution"]
    checks = {
        "native_lane_pass": native["status"] == "PASS",
        "core_output_v11": canonical["schema_version"] == "1.1",
        "canonical_object_digest": native["canonical"]["sha256"]
        == file_hash(NATIVE / "canonical.json"),
        "manifest_object_digest": resolution["manifest"]["sha256"]
        == file_hash(NATIVE / "manifest.json"),
        "inspect_object_digest": resolution["inspect_sha256"] == file_hash(NATIVE / "inspect.json"),
        "relevant_fingerprint_cross_language": resolution["resolution_evidence_fingerprint"]
        == evidence_fingerprint(manifest),
        "fixture_context_digest_cross_language": resolution["context_sha256"]
        == digest(read(NATIVE / "context.json")),
        "exact_algorithm_versioned": canonical["fingerprints"]["algorithm"] == "exact-v1.1",
        "grouping_versioned": canonical["engine"]["grouping_version"] == "group-v1.1",
        "module_selections_preserved": [m["selection"] for m in canonical["modules"]]
        == manifest["modules"],
        "native_methods_preserved": all(
            f["unwind_method"] == r["frames"][f["physical_frame_index"]]["unwind_method"]
            and int(f["instruction_addr"], 16)
            == r["frames"][f["physical_frame_index"]]["instruction"]
            for t, r in zip(canonical["threads"], raw["threads"], strict=True)
            for f in t["frames"]
        ),
        "no_private_raw_function_leak": all(
            f["function"] is None and f["file"] is None and f["line"] is None
            for t in canonical["threads"]
            for f in t["frames"]
        ),
    }
    legacy = read(OUT / "provenance-qualification.json")
    checks["old_canonical_and_raw_regression"] = legacy["status"] == "PASS"
    for field in ("dump_sha256", "pe_sha256", "pdb_sha256", "pair_id"):
        raw_hash(native[field])
    paths = [
        ROOT / "core/src/canonical.rs",
        ROOT / "core/src/canonical_v11.rs",
        ROOT / "core/src/canonical_v11_tests.rs",
        ROOT / "core/src/unwind.rs",
        ROOT / "core/src/lib.rs",
        ROOT / "core/tests/canonical_v11.rs",
        ROOT / "core/tests/frozen_unwind.rs",
        ROOT / "contracts/analysis-result-v1.schema.json",
        ROOT / "contracts/analysis-result-v1.1.schema.json",
        Path(__file__).resolve(),
        OUT / "core-v11-unit.log",
        OUT / "core-v11-native.log",
        OUT / "core-v11-build.log",
        OUT / "core-v11-legacy.log",
        OUT / "provenance-qualification.json",
        *sorted(NATIVE.glob("*.json")),
    ]
    result = {
        "schema_version": "qai-native-v11-progress-v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "scope": (
            "Core library assembler, native PE unwind, synthetic symbol provenance controls "
            "and old 1.0 regression"
        ),
        "not_proven": [
            "complete Run/context-v2 validation in Core",
            "native partition source requests",
            "public source fallback",
            "Worker integration",
            "old Current transition",
            "QAI-G1",
            "QAI-G4",
            "deployment",
        ],
        "lanes": lanes,
        "checks": checks,
        "fixture": native,
        "files": {str(p.relative_to(ROOT)).replace("\\", "/"): file_hash(p) for p in paths},
    }
    (OUT / "native-v11-progress.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": result["status"], "checks": len(checks), "lanes": lanes}))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
