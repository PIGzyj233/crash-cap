#!/usr/bin/env python3
"""Query the running Phase 0 Symbolicator with the generated fixture.

The request uses the minidump verifier's actual fault module base and
exception address, so the frame is sent as a relative address instead of
guessing an ASLR base. The PE/PDB IDs come from the PE's CodeView metadata.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "http://127.0.0.1:3021"
DEFAULT_MANIFEST = ROOT / "fixtures" / "p0-b01-null-read" / "generated" / "manifest.json"
DEFAULT_VERIFIER = ROOT / "fixtures" / "p0-b01-null-read" / "generated" / "verifier-result.json"
DEFAULT_METADATA = ROOT / "fixtures" / "p0-b01-null-read" / "generated" / "pe-metadata.json"
DEFAULT_EVIDENCE = ROOT / "docs" / "evidence" / "symbolicator-p0-b01-query.json"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def post(base_url: str, payload: dict[str, Any], scope: str) -> tuple[int, bytes]:
    url = f"{base_url.rstrip('/')}/symbolicate?scope={scope}&inventory=0&timeout=30"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def check_response(response: dict[str, Any], debug_id: str) -> dict[str, Any]:
    failures: list[str] = []
    if response.get("status") != "completed":
        failures.append(f"status={response.get('status')!r}, expected 'completed'")
    stacktraces = response.get("stacktraces")
    frames = stacktraces[0].get("frames", []) if isinstance(stacktraces, list) and stacktraces else []
    if not frames:
        failures.append("response has no symbolicated frame")
    functions = [str(frame.get("function", "")) for frame in frames if isinstance(frame, dict)]
    if not any("crashcap::trigger_null_read" in function for function in functions):
        failures.append(f"expected crashcap::trigger_null_read in functions, got {functions!r}")

    modules = response.get("modules")
    module = modules[0] if isinstance(modules, list) and modules else {}
    if module.get("debug_status") != "found":
        failures.append(f"module debug_status={module.get('debug_status')!r}, expected 'found'")
    if str(module.get("debug_id", "")).replace("-", "").lower() != debug_id.lower():
        failures.append(f"response debug_id={module.get('debug_id')!r} does not match {debug_id!r}")
    candidates = module.get("candidates", []) if isinstance(module, dict) else []
    p0_candidates = [candidate for candidate in candidates if candidate.get("source") == "crash-cap:p0-test"]
    if not any(candidate.get("download", {}).get("status") == "ok" for candidate in p0_candidates):
        failures.append("no successful crash-cap:p0-test symbol download candidate")
    return {
        "passed": not failures,
        "failures": failures,
        "frame_functions": functions,
        "module_debug_status": module.get("debug_status"),
        "p0_test_candidates": p0_candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--scope", default="wsp_p0test")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--verifier", type=Path, default=DEFAULT_VERIFIER)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--output", type=Path, default=DEFAULT_EVIDENCE)
    args = parser.parse_args()

    manifest = load(args.manifest)
    verifier = load(args.verifier)
    metadata = load(args.metadata)
    exception_address = int(str(verifier["exception_address"]), 16)
    runtime_image_base = int(str(verifier["fault_module"]["image_base"]), 16)
    relative_address = exception_address - runtime_image_base
    if relative_address < 0:
        raise ValueError("exception address precedes the verifier's fault module base")

    debug_id = str(metadata["debug_id"])
    code_id = str(metadata["code_id"])
    payload: dict[str, Any] = {
        "platform": "native",
        "modules": [
            {
                "type": "pe",
                "debug_id": debug_id,
                "code_id": code_id,
                "debug_file": "null_read_target.exe",
                "image_addr": str(metadata["image_base"]).lower(),
                "image_size": int(str(metadata["size_of_image"]), 16),
            }
        ],
        "stacktraces": [
            {
                "frames": [
                    {
                        "instruction_addr": f"0x{relative_address:x}",
                        "addr_mode": "rel:0",
                    }
                ]
            }
        ],
        "options": {"dif_candidates": True, "apply_source_context": False},
    }
    evidence: dict[str, Any] = {
        "schema_version": "symbolicator-query-evidence-v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "scope": args.scope,
        "symbolicator_expected_version": "26.7.2",
        "fixture_manifest": str(args.manifest),
        "fixture_ids": {"code_id": code_id, "debug_id": debug_id},
        "address_derivation": {
            "exception_address": f"0x{exception_address:016X}",
            "runtime_image_base": f"0x{runtime_image_base:016X}",
            "relative_address": f"0x{relative_address:X}",
        },
        "request": payload,
    }
    try:
        status, body = post(args.base_url, payload, args.scope)
        evidence["http_status"] = status
        evidence["response"] = json.loads(body)
        if status != 200:
            evidence["validation"] = {"passed": False, "failures": [f"HTTP {status}"]}
        else:
            evidence["validation"] = check_response(evidence["response"], debug_id)
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError) as error:
        evidence["validation"] = {"passed": False, "failures": [str(error)]}

    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))
    return 0 if evidence["validation"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
