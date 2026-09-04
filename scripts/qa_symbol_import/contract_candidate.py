"""Capture/check local contract bytes without claiming protocol qualification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def inventory() -> dict[str, str]:
    paths = list((ROOT / "contracts/drafts/qa-symbol-import").glob("*.schema.json"))
    paths.extend(ROOT / path for path in (
        "contracts/analysis-result-v1.schema.json",
        "contracts/analysis-result-v1.1.schema.json",
        "platform/api/crashcap_api/evidence_comparison.py",
        "platform/tests/test_evidence_comparison.py",
        "scripts/qa_symbol_import/build_drafts.py",
        "scripts/qa_symbol_import/protocol.py",
        "scripts/qa_symbol_import/test_protocol.py",
        "scripts/qa_symbol_import/test_legacy_continuity.py",
        "scripts/qa_symbol_import/test_source_diagnostics.py",
        "scripts/qa_symbol_import/test_partitioned_source.py",
    ))
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(paths)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    actual = inventory()
    if args.check:
        expected = json.loads(args.manifest.read_text(encoding="utf-8"))
        if expected.get("schema_version") != "qai-contract-candidate-v1":
            parser.error("unsupported manifest version")
        recorded = expected.get("files")
        if not isinstance(recorded, dict):
            parser.error("manifest files must be an object")
        changed = sorted(key for key in set(actual) | set(recorded)
                         if actual.get(key) != recorded.get(key))
        if changed:
            print(json.dumps({"status": "DRIFT", "files": changed}, indent=2))
            raise SystemExit(1)
        print(json.dumps({"status": "MATCH", "files": len(actual),
                          "protocol_frozen": False}))
        return
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    with args.manifest.open("x", encoding="utf-8") as stream:
        json.dump({"schema_version": "qai-contract-candidate-v1", "protocol_frozen": False,
                   "scope": "byte inventory only; not qualification or release approval",
                   "files": actual}, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"manifest": str(args.manifest), "files": len(actual)}))


if __name__ == "__main__":
    main()
