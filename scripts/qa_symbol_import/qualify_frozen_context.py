"""Cross-check native full Run artifacts with the platform's independent reader.

Run from platform with `uv run python ../scripts/qa_symbol_import/qualify_frozen_context.py`
after qualify_native_sources.py has completed its owned live qualification.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from crashcap_api.frozen_inputs import verify_frozen_run

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "target/qa-symbol-import"
FROZEN = OUT / "frozen-context"
LIVE = OUT / "native-source"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "frozen-context-progress.json").write_text(
        json.dumps({"status": "RUNNING", "recorded_at": datetime.now(UTC).isoformat()}),
        encoding="utf-8",
    )
    run = read(FROZEN / "run.json")
    dump = ROOT / "fixtures/p0-b01-null-read/generated/null-read.dmp"
    manifest, _ = verify_frozen_run(
        run,
        manifest_bytes=(FROZEN / "manifest.json").read_bytes(),
        inspect_bytes=(FROZEN / "inspect.json").read_bytes(),
        observed_dump_sha256=sha(dump),
        observed_dump_size=dump.stat().st_size,
        schema_root=ROOT / "contracts/drafts/qa-symbol-import",
    )
    native = read(FROZEN / "qualification.json")
    live = read(LIVE / "progress.json")
    canonical = read(LIVE / "canonical.json")
    roles = run["policy_snapshots"]["role_policy"]["modules"]
    checks = {
        "native_full_run_and_negative_cases_pass": native["status"] == "PASS"
        and all(case["status"] == "PASS" for case in native["cases"]),
        "independent_platform_verifier_pass": True,
        "run_object_seal": native["run_sha256"] == sha(FROZEN / "run.json"),
        "live_run_is_same_full_run": live["native"]["run_sha256"] == native["run_sha256"],
        "live_source_pass_and_cleanup": live["status"] == "PASS"
        and live["owned_container_and_volume_removed"],
        "canonical_bytes_seal": live["native"]["canonical"]["sha256"]
        == sha(LIVE / "canonical.json"),
        "canonical_assignment": (
            canonical["analysis_id"],
            canonical["occurrence_id"],
            canonical["workspace_id"],
        )
        == (run["run_id"], run["occurrence_id"], run["context"]["workspace_id"]),
        "canonical_facts_from_run": canonical["dump"] == run["result_facts"]["dump"],
        "canonical_context_from_run": canonical["symbol_resolution"]["context_sha256"]
        == run["context_sha256"],
        "canonical_fingerprint_from_run": canonical["symbol_resolution"][
            "resolution_evidence_fingerprint"
        ]
        == run["resolution_evidence_fingerprint"],
        "canonical_selection_from_manifest": [m["selection"] for m in canonical["modules"]]
        == manifest["modules"],
        "canonical_roles_from_workspace_policy": [
            (m["module_index"], m["role"], m["in_app"]) for m in canonical["modules"]
        ]
        == [(m["module_index"], m["role"], m["in_app"]) for m in roles],
        "Build_from_frozen_local_snapshot": canonical["build_resolution"]["resolved_build_id"]
        == "bld_fixture",
        "real_fault_function_line": any(
            "trigger_null_read" in (frame["function"] or "") and frame["line"] == 76
            for thread in canonical["threads"]
            for frame in thread["frames"]
        ),
    }
    paths = [
        Path(__file__).resolve(),
        ROOT / "platform/api/crashcap_api/frozen_inputs.py",
        ROOT / "platform/tests/test_frozen_inputs.py",
        ROOT / "core/src/frozen_context.rs",
        ROOT / "core/tests/frozen_context.rs",
        ROOT / "core/tests/frozen_source_native.rs",
        ROOT / "contracts/drafts/qa-symbol-import/analysis-run-v2.schema.json",
        ROOT / "contracts/drafts/qa-symbol-import/analysis-context-v2.schema.json",
        ROOT / "contracts/drafts/qa-symbol-import/resolution-manifest-v1.schema.json",
        FROZEN / "run.json",
        FROZEN / "inspect.json",
        FROZEN / "manifest.json",
        FROZEN / "qualification.json",
        LIVE / "progress.json",
        LIVE / "canonical.json",
        LIVE / "prepare.log",
        LIVE / "live.log",
        OUT / "frozen-context-python.xml",
    ]
    result = {
        "schema_version": "qai-frozen-context-progress-v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "scope": (
            "full Run/policy/assignment validation, real pair staging, live source and Core result"
        ),
        "not_proven": [
            "production planner",
            "catalog admission",
            "source bundle enrichment",
            "Worker activation",
            "old Current transition",
            "deployment",
        ],
        "files": {p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
    }
    (OUT / "frozen-context-progress.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"status": result["status"], "checks": len(checks)}))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        failure = {
            "schema_version": "qai-frozen-context-progress-v1",
            "status": "FAIL",
            "recorded_at": datetime.now(UTC).isoformat(),
            "error": f"{type(error).__name__}: {error}",
        }
        (OUT / "frozen-context-progress.json").write_text(
            json.dumps(failure, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(failure))
        raise SystemExit(1) from error
