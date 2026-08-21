#!/usr/bin/env python3
"""Run a fixture through inspect -> official unwind -> symbolication -> canonical.

The runner compares only fields declared by the fixture's expected contract and
prints path-specific differences. It writes generated match input and engine
outputs under ``target/golden``; fixture source files are never modified.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def core_command(explicit: str | None) -> list[str]:
    if explicit:
        return [explicit]
    candidates = [ROOT / "target" / "debug" / "dmp-core.exe", ROOT / "target" / "release" / "dmp-core.exe"]
    for candidate in candidates:
        if candidate.exists():
            return [str(candidate)]
    return ["cargo", "run", "-q", "-p", "dmp-core", "--"]


def run(command: list[str]) -> None:
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    if process.returncode:
        raise RuntimeError(
            f"command failed ({process.returncode}): {' '.join(command)}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )


def rel_or_abs(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def make_match_input(fixture: Path, manifest: dict) -> dict:
    target = manifest["target"]
    build_id = manifest.get("build_id", f"bld_{manifest.get('fixture_id', 'golden')}")
    pe = rel_or_abs(fixture, target["path"])
    pdb = rel_or_abs(fixture, target["pdb"])
    module = {
        "artifact_id": f"art_{manifest.get('fixture_id', 'golden')}_target",
        "code_file": Path(target["path"]).name,
        "debug_file": Path(target["pdb"]).name,
        "pe_path": str(pe),
        "pdb_path": str(pdb),
        "code_id": target["code_id"],
        "debug_id": target["debug_id"],
        "role": "entrypoint",
        "in_app": True,
        "build_id": build_id,
    }
    return {
        "workspace_id": "wsp_p0test",
        "modules": [module],
        "builds": [{"build_id": build_id, "modules": [{"code_id": target["code_id"], "debug_id": target["debug_id"], "role": "entrypoint"}]}],
    }


def normalize_hex(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return f"0x{int(value, 16):x}"
    except ValueError:
        return value.lower()


def compare(expected: dict, inspect: dict, canonical: dict, manifest: dict) -> list[dict]:
    differences: list[dict] = []

    def check(path: str, actual: object, wanted: object) -> None:
        if actual != wanted:
            differences.append({"path": path, "expected": wanted, "actual": actual})

    dump = expected.get("dump", {})
    check("dump.magic_ascii", inspect.get("dump", {}).get("signature"), dump.get("magic_ascii"))
    check("dump.kind", inspect.get("dump", {}).get("kind"), dump.get("kind"))
    check("dump.architecture", inspect.get("process", {}).get("architecture"), dump.get("architecture"))

    exception = expected.get("exception", {})
    actual_exception = inspect.get("exception") or {}
    if "code" in exception:
        check("exception.code", str(actual_exception.get("code", "")).upper(), str(exception["code"]).upper())
    for field in ("name", "access_type"):
        if field in exception:
            check(f"exception.{field}", actual_exception.get(field), exception[field])
    if "fault_address" in exception:
        check("exception.fault_address", normalize_hex(actual_exception.get("fault_address")), normalize_hex(exception["fault_address"]))

    if expected.get("crashing_thread", {}).get("must_be_nonzero"):
        thread_id = canonical.get("crash", {}).get("thread_id")
        if not isinstance(thread_id, int) or thread_id == 0:
            differences.append({"path": "crashing_thread.thread_id", "expected": "nonzero", "actual": thread_id})

    expected_frames = expected.get("business_frames", [])
    actual_frames = []
    for thread in canonical.get("threads", []):
        if thread.get("is_crashing"):
            actual_frames.extend(thread.get("frames", []))
    actual_names = {frame.get("function_normalized") for frame in actual_frames}
    for name in expected_frames:
        if name not in actual_names:
            differences.append({"path": "business_frames", "expected": name, "actual": sorted(actual_names)})

    target = manifest.get("target", {})
    target_module = next((module for module in canonical.get("modules", []) if module.get("code_id", "").lower() == str(target.get("code_id", "")).lower()), None)
    if target_module is None:
        differences.append({"path": "module_ids", "expected": target.get("code_id"), "actual": None})
    else:
        check("module_ids.code_id", target_module.get("code_id", "").upper(), str(target.get("code_id", "")).upper())
        check("module_ids.debug_id", target_module.get("debug_id", "").lower(), str(target.get("debug_id", "")).lower())
    return differences


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=Path("fixtures/p0-b01-null-read"))
    parser.add_argument("--core", help="path to a dmp-core executable")
    parser.add_argument("--symbolicator", default=os.environ.get("SYMBOLICATOR_URL"))
    parser.add_argument("--symbolicator-version", default="26.7.2")
    parser.add_argument("--core-image-digest")
    args = parser.parse_args()

    fixture = args.fixture if args.fixture.is_absolute() else ROOT / args.fixture
    manifest = read_json(fixture / "generated" / "manifest.json")
    expected_doc = read_json(fixture / "expected.json")
    dump = rel_or_abs(fixture, manifest["dump"]["path"])
    output_dir = ROOT / "target" / "golden" / manifest.get("fixture_id", fixture.name)
    output_dir.mkdir(parents=True, exist_ok=True)
    match_path = output_dir / "match-input.json"
    match_path.write_text(json.dumps(make_match_input(fixture, manifest), indent=2) + "\n", encoding="utf-8")
    inspect_path = output_dir / "inspect.json"
    canonical_path = output_dir / "canonical.json"
    raw_dir = output_dir / "raw"
    core = core_command(args.core)
    run(core + ["inspect", "--dump", str(dump), "--output", str(inspect_path)])
    analyze = core + ["analyze", "--dump", str(dump), "--inspect", str(inspect_path), "--match", str(match_path), "--workspace-id", "wsp_p0test", "--symbolicator-version", args.symbolicator_version, "--output", str(canonical_path), "--raw-dir", str(raw_dir)]
    if args.symbolicator:
        analyze += ["--symbolicator", args.symbolicator]
    if args.core_image_digest:
        analyze += ["--core-image-digest", args.core_image_digest]
    run(analyze)

    inspect = read_json(inspect_path)
    canonical = read_json(canonical_path)
    differences = compare(expected_doc["expected"], inspect, canonical, manifest)
    summary = {"ok": not differences, "fixture_id": manifest.get("fixture_id"), "differences": differences, "inspect": str(inspect_path), "canonical": str(canonical_path), "raw_dir": str(raw_dir), "commands": {"inspect": core + ["inspect"], "analyze": analyze}}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if not differences else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, KeyError, json.JSONDecodeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2)
