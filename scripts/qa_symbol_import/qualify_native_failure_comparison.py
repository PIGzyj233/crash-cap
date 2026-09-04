"""Compare unmodified native fault reports after the isolated source qualifier."""

import hashlib
import json
from pathlib import Path

from crashcap_api.contracts import validate_contract
from crashcap_api.evidence_comparison import compare_evidence
from crashcap_api.models import AnalysisRun
from crashcap_api.services.current_decisions import build_native_evidence

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "target/qa-symbol-import"
OUT = BASE / "native-source"


def main():
    receipt_bytes = (OUT / "progress.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    if receipt["status"] != "PASS":
        raise ValueError("native source qualification did not pass")
    for name, expected in receipt["files"].items():
        path = (ROOT / name).resolve()
        if (
            not path.is_relative_to(ROOT)
            or hashlib.sha256(path.read_bytes()).hexdigest() != expected
        ):
            raise ValueError(f"native qualification file changed: {name}")
    inspect_bytes = (BASE / "frozen-context/inspect.json").read_bytes()
    inspection = json.loads(inspect_bytes)
    inputs = {
        "target/qa-symbol-import/frozen-context/inspect.json": hashlib.sha256(inspect_bytes).hexdigest()
    }
    for path in (
        Path(__file__).resolve(),
        ROOT / "platform/api/crashcap_api/evidence_comparison.py",
        ROOT / "platform/api/crashcap_api/services/current_decisions.py",
    ):
        inputs[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()

    def project(report_path, run_path):
        raw, run_bytes = report_path.read_bytes(), run_path.read_bytes()
        canonical, spec = json.loads(raw), json.loads(run_bytes)
        if hashlib.sha256(inspect_bytes).hexdigest() != spec["inspect"]["sha256"]:
            raise ValueError("inspect differs from frozen Run")
        validate_contract(
            canonical,
            ROOT / "contracts/analysis-result-v1.1.schema.json",
            "native report",
        )
        run = AnalysisRun(
            id=spec["run_id"],
            occurrence_id=spec["occurrence_id"],
            schema_version="1.1",
            assembly_mode="core-final",
            status="PARTIAL",
            run_spec=spec,
        )
        for path, payload in ((report_path, raw), (run_path, run_bytes)):
            inputs[path.relative_to(ROOT).as_posix()] = hashlib.sha256(
                payload
            ).hexdigest()
        return build_native_evidence(
            run, canonical, raw, inspection, schema_root=ROOT / "contracts"
        )

    current = project(OUT / "canonical.json", BASE / "frozen-context/run.json")
    cases = []
    for mode, expected in (
        ("native-missing", ("retain", "permanent_loss", False)),
        ("native-unavailable", ("retain", "business_transient_loss", True)),
    ):
        candidate = project(OUT / f"{mode}-canonical.json", OUT / f"{mode}-run.json")
        decision = compare_evidence(current, candidate)
        if (decision.decision, decision.reason, decision.retry) != expected:
            raise ValueError(f"unexpected {mode} decision: {decision.as_dict()}")
        cases.append(
            {
                "mode": mode,
                "candidate": candidate.as_dict(),
                "decision": decision.as_dict(),
            }
        )
    result = {
        "status": "PASS",
        "scope": "Actual Core reports to product evidence projector and comparator; isolated Run envelopes, no persisted Current transition",
        "source_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
        "inputs": inputs,
        "current": current.as_dict(),
        "cases": cases,
    }
    (BASE / "native-failure-comparison.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": "PASS", "cases": len(cases)}))


if __name__ == "__main__":
    main()
