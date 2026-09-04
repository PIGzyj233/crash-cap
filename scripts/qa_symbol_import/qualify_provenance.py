"""Verify new Core raw provenance against the preserved pre-change 1.0 fixture."""

from __future__ import annotations

import copy
import hashlib
import json
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "target/qa-symbol-import"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    core = (
        ROOT
        / "target/debug"
        / ("dmp-core.exe" if platform.system() == "Windows" else "dmp-core")
    )
    dump = ROOT / "fixtures/p0-b01-null-read/generated/null-read.dmp"
    old_canonical_path = OUT / "baseline-canonical-1.0.json"
    old_raw_path = OUT / "baseline-raw/minidump.json"
    old_canonical_sha = sha(old_canonical_path)
    old_raw_sha = sha(old_raw_path)
    old = json.loads(old_canonical_path.read_text())
    old_raw = json.loads(old_raw_path.read_text())
    if any("unwind_method" in f for t in old_raw["threads"] for f in t["frames"]):
        raise RuntimeError(
            "pre-change raw baseline was replaced; preserve historical evidence before rerun"
        )
    prior = OUT / "provenance-qualification.json"
    failed_clock = OUT / "provenance-qualification-unfrozen-clock.json"
    if (
        prior.is_file()
        and not failed_clock.exists()
        and json.loads(prior.read_text())["status"] == "FAIL"
    ):
        failed_clock.write_bytes(prior.read_bytes())
    inspect = json.loads((OUT / "baseline-inspect.json").read_text())
    context = {
        "schema_version": "analysis-context-v1",
        "identity": {
            "workspace_id": old["workspace_id"],
            "occurrence_id": old["occurrence_id"],
            "analysis_id": old["analysis_id"],
        },
        "dump": old["dump"],
        "engine": old["engine"],
        "policy": {
            "symbol_inventory_version": 0,
            "source_bundle_policy_version": "source-bundle-v1.0",
        },
        "inspect": {
            "sha256": hashlib.sha256(
                json.dumps(inspect, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        },
        "inputs": {},
    }
    context_path = OUT / "provenance-frozen-context.json"
    context_path.write_text(json.dumps(context, indent=2))
    command = [
        str(core),
        "analyze",
        "--dump",
        str(dump),
        "--output",
        str(OUT / "provenance-canonical-1.0.json"),
        "--raw-dir",
        str(OUT / "provenance-raw"),
        "--analysis-context",
        str(context_path),
    ]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    canonical = json.loads((OUT / "provenance-canonical-1.0.json").read_text())
    raw = json.loads((OUT / "provenance-raw/minidump.json").read_text())
    stripped = copy.deepcopy(raw)
    methods = []
    for thread in stripped["threads"]:
        for frame in thread["frames"]:
            methods.append(frame.pop("unwind_method", None))
    checks = {
        "canonical_1_0_semantics_unchanged": canonical == old,
        "old_raw_semantics_unchanged": stripped == old_raw,
        "all_new_frames_have_native_provenance": bool(methods)
        and all(
            m
            in (
                "context",
                "call_frame_info",
                "cfi_scan",
                "frame_pointer",
                "scan",
                "prewalked",
                "unknown",
            )
            for m in methods
        ),
        "historical_raw_still_unmodified": sha(old_raw_path) == old_raw_sha
        and sha(old_canonical_path) == old_canonical_sha,
    }
    evidence = {
        "schema_version": "qai-unwind-provenance-v1",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "command": command,
        "core_binary_sha256": sha(core),
        "context_sha256": sha(context_path),
        "dump_sha256": sha(dump),
        "old_canonical_sha256": sha(old_canonical_path),
        "old_raw_sha256": sha(old_raw_path),
        "new_canonical_sha256": sha(OUT / "provenance-canonical-1.0.json"),
        "new_raw_sha256": sha(OUT / "provenance-raw/minidump.json"),
        "checks": checks,
        "native_methods": methods,
        "boundary": "local fixture; new raw provenance only; no historical Canonical rewrite and no Canonical 1.1 writer enabled",
    }
    (OUT / "provenance-qualification.json").write_text(
        json.dumps(evidence, indent=2) + "\n"
    )
    print(json.dumps({"status": evidence["status"], "checks": checks}))
    raise SystemExit(0 if evidence["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
