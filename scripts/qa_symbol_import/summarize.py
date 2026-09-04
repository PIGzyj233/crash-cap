"""Export compact, hash-linked QAI evidence for review; raw responses remain in target."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "target/qa-symbol-import"
OUT = ROOT / "docs/evidence/qa-symbol-import"


def main():
    names = [
        "s0.json",
        "baseline.json",
        "local-compose-health.json",
        "legacy-inventory.json",
        "source-qualification.json",
        "source-qualification-backlog1024.json",
        "source-qualification-bounded.json",
    ]
    inputs = {}
    refs = []
    for name in names:
        path = RAW / name
        content = path.read_bytes()
        inputs[name] = json.loads(content)
        refs.append(
            {
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
        )
    baseline = inputs["baseline.json"]
    legacy = inputs["legacy-inventory.json"]
    report = {
        "schema_version": "qai-execution-summary-v1",
        "head": baseline["head"],
        "workspace_changes": baseline["workspace_files"],
        "raw_evidence": refs,
        "gates": {
            "QAI-G0": inputs["s0.json"]["status"],
            "QAI-G1": "NOT_PROVEN",
            **{f"QAI-G{i}": "NOT_RUN" for i in range(2, 9)},
        },
        "s0": {
            "checks": len(inputs["s0.json"]["checks"]),
            "failed_checks": [
                c for c in inputs["s0.json"]["checks"] if c["status"] != "PASS"
            ],
        },
        "local_health": inputs["local-compose-health.json"],
        "legacy": {
            "counts": legacy["counts"],
            "enumeration_complete": legacy["enumeration_complete"],
            "run_status_counts": dict(Counter(r["status"] for r in legacy["runs"])),
            "canonical_available": sum(
                r["canonical"]["status"] == "present" for r in legacy["runs"]
            ),
            "canonical_unwind_provenance_present": sum(
                r.get("canonical_unwind_methods_present", False) for r in legacy["runs"]
            ),
            "raw_frame_keys": sorted(
                {
                    k
                    for r in legacy["runs"]
                    for o in r["raw_objects"]
                    for k in o.get("frame_keys", [])
                }
            ),
            "continuity_status": "NOT_PROVEN; raw trust mapping or explicit version-transition recomputation not yet qualified",
        },
        "source_experiments": [],
    }
    for name in names[4:]:
        result = inputs[name]
        report["source_experiments"].append(
            {
                "evidence": name,
                "status": result["status"],
                "time_utc": result["time_utc"],
                "image": result["image"],
                "running_image_id": result.get("running_image_id"),
                "version": result.get("version"),
                "cases": [
                    {
                        "id": c["id"],
                        "status": c["status"],
                        "seconds": c["detail"].get("seconds"),
                        "requests": c["detail"].get(
                            "requests", len(c["detail"].get("events", []))
                        ),
                        "download_error_count": len(
                            c["detail"].get("download_errors", [])
                        ),
                    }
                    for c in result["cases"]
                ],
                "boundary": result["environment"],
            }
        )
    report["reviewer"] = "Codex automatic checks; no human or target signoff"
    report["not_proven"] = [
        "S1 source strategy freeze and multi-module/public/unwind exclusion",
        "historical Current continuity and actual new Core Canonical 1.1",
        "catalog/API/Worker/browser functionality",
        "remote CI",
        "target migration, UAT, observation and rollback",
    ]
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "execution-summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(str(OUT / "execution-summary.json"))


if __name__ == "__main__":
    main()
