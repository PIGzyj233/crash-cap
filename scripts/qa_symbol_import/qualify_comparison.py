"""Run asserted comparator vectors and bind the receipt to their exact inputs/code."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "target/qa-symbol-import"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    vectors_path = OUT / "comparison-vectors.json"
    junit_path = OUT / "comparison-tests.xml"
    log_path = OUT / "comparison-tests.log"
    env = dict(os.environ, QAI_COMPARISON_VECTORS_OUTPUT=str(vectors_path))
    command = [
        "uv",
        "run",
        "pytest",
        "-q",
        "tests/test_evidence_comparison.py",
        f"--junitxml={junit_path}",
    ]
    result = subprocess.run(command, cwd=ROOT / "platform", env=env, capture_output=True, text=True)
    log_path.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Comparator qualification failed; see {log_path}")
    vectors = json.loads(vectors_path.read_text(encoding="utf-8"))
    suites = ET.parse(junit_path).getroot()
    tests = suites.findall(".//testcase")
    files = [
        ROOT / "platform/api/crashcap_api/evidence_comparison.py",
        ROOT / "platform/tests/test_evidence_comparison.py",
        ROOT / "contracts/drafts/qa-symbol-import/comparison-evidence-v1.schema.json",
        ROOT / "contracts/drafts/qa-symbol-import/comparison-decision-v1.schema.json",
        vectors_path,
        junit_path,
        log_path,
        Path(__file__),
    ]
    report = {
        "schema_version": "qai-comparison-qualification-v1",
        "time_utc": datetime.now(UTC).isoformat(),
        "status": "PASS",
        "command": command,
        "tests": len(tests),
        "skipped": len(suites.findall(".//skipped")),
        "vectors": len(vectors),
        "decisions": dict(Counter(v["decision"]["reason"] for v in vectors)),
        "hashes": {
            str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
        },
        "boundary": (
            "Local asserted synthetic evidence-v1 vectors, each validated against both JSON schemas. "
            "Audit authorizations are test data only. No real review granted, no Current changed. "
            "Production evidence projection, lock/fencing and atomic projections remain S5 work."
        ),
    }
    if report["skipped"] or not tests or not vectors:
        raise RuntimeError("Qualification must run nonempty vectors with zero skips")
    (OUT / "comparison-qualification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps({k: report[k] for k in ("status", "tests", "skipped", "vectors", "decisions")})
    )


if __name__ == "__main__":
    main()
