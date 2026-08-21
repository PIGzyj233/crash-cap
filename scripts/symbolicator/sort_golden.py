#!/usr/bin/env python3
"""Sort every complete Golden PE/PDB pair into Symbolicator Unified layout.

The fixture manifests are the discovery source, but artifact treatment is
checked against ``expected.json`` before anything is published.  Only a
fixture whose expected treatment is ``complete`` may invoke the pinned
symsorter.  In particular, missing/wrong PE or PDB treatments are recorded as
not published and are never silently substituted with another fixture's
artifact.

The output directory is intentionally the ignored Phase 0 workspace at
``deploy/symbolicator/symbols/p0-test``.  The symsorter release is imported
from the existing pinned downloader so the version, URL and SHA-256 remain a
single fixed contract.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "fixtures"
DEFAULT_OUTPUT = ROOT / "deploy" / "symbolicator" / "symbols" / "p0-test"
DEFAULT_EVIDENCE = ROOT / "docs" / "evidence" / "symsorter-golden.json"
sys.path.insert(0, str(ROOT))

# Keep the pinned binary contract in one place.  fetch_and_sort.py contains
# the download/hash implementation and does not execute its CLI on import.
from scripts.fixtures.extract_pe_metadata import parse_pe  # noqa: E402
from scripts.symbolicator.symsorter.fetch_and_sort import (  # noqa: E402
    ASSET_NAME,
    DOWNLOAD_URL,
    EXPECTED_SHA256,
    VERSION,
    download_pinned,
    run_tool,
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path).replace("\\", "/")


def normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text.upper() if text else None


def normalize_treatment(expected: dict[str, Any]) -> str:
    value = expected.get("expected", {}).get("artifact_treatment")
    return str(value or "unknown")


def resolve_fixture_path(fixture_dir: Path, value: Any) -> Path | None:
    """Resolve a manifest artifact without falling back to another fixture.

    All generated manifests are relative to their fixture directory.  An
    absolute path is accepted only if it still exists at that exact path; a
    stale path is rejected rather than guessed by basename.
    """

    if value is None or not isinstance(value, str) or not value.strip():
        return None
    candidate = Path(value)
    return candidate if candidate.is_absolute() else fixture_dir / candidate


def unified_prefix(output: Path, debug_id: str) -> Path:
    if len(debug_id) <= 2:
        raise ValueError(f"debug_id is too short for Unified layout: {debug_id!r}")
    if any(character not in "0123456789ABCDEF" for character in debug_id):
        raise ValueError(f"debug_id is not hexadecimal: {debug_id!r}")
    prefix = output / debug_id[:2].lower() / debug_id[2:].lower()
    output_resolved = output.resolve()
    prefix_resolved = prefix.resolve()
    if os.path.commonpath((str(output_resolved), str(prefix_resolved))) != str(output_resolved):
        raise ValueError(f"debug_id path escaped output root: {debug_id!r}")
    return prefix


def validate_layout(output: Path, code_id: str, debug_id: str) -> dict[str, Any]:
    prefix = unified_prefix(output, debug_id)
    required = {
        "executable": prefix / "executable",
        "executable_meta": prefix / "executable.meta",
        "debuginfo": prefix / "debuginfo",
        "debuginfo_meta": prefix / "debuginfo.meta",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    executable_identity: dict[str, Any] | None = None
    parse_error: str | None = None
    if not missing:
        try:
            executable_identity = parse_pe(required["executable"])
        except (OSError, ValueError, struct.error) as error:
            parse_error = f"{type(error).__name__}: {error}"
    actual_code = normalize_id((executable_identity or {}).get("code_id"))
    actual_debug = normalize_id((executable_identity or {}).get("debug_id"))
    identity_matches = actual_code == code_id and actual_debug == debug_id
    return {
        "prefix": prefix.relative_to(output).as_posix(),
        "files": {name: path.relative_to(output).as_posix() for name, path in required.items()},
        "missing": missing,
        "executable_identity": executable_identity,
        "executable_parse_error": parse_error,
        "code_id": code_id,
        "debug_id": debug_id,
        "executable_identity_matches": identity_matches,
        "ready_for_symbolicator": not missing and parse_error is None and identity_matches,
    }


def fixture_query_boundary(expected: dict[str, Any]) -> dict[str, Any]:
    evidence = expected.get("expected", {})
    frames = evidence.get("business_frames", []) if isinstance(evidence, dict) else []
    first = frames[0] if isinstance(frames, list) and frames else None
    return {
        "status": "deferred_to_batch_runner",
        "runner": "scripts/phase0/golden_runner.py",
        "first_expected_business_frame": first,
        "reason": (
            "sort_golden publishes symbols and verifies Unified layout only; "
            "the batch runner must resolve the first business-frame address "
            "from each dump and submit the actual Symbolicator query."
        ),
    }


def discover_fixture(fixture_dir: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "fixture_id": fixture_dir.name,
        "fixture": rel(fixture_dir / "fixture.json"),
        "manifest": rel(fixture_dir / "generated" / "manifest.json"),
    }
    try:
        fixture = read_json(fixture_dir / "fixture.json")
        expected = read_json(fixture_dir / "expected.json")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        record.update({"status": "rejected_metadata", "reason": f"{type(error).__name__}: {error}"})
        return record

    manifest_path = fixture_dir / "generated" / "manifest.json"
    generated: dict[str, Any] | None = None
    if manifest_path.is_file():
        try:
            generated = read_json(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            record["generated_manifest_error"] = f"{type(error).__name__}: {error}"

    expected_treatment = normalize_treatment(expected)
    generated_dump = generated.get("dump", {}) if isinstance(generated, dict) else {}
    generated_treatment = generated_dump.get("treatment") if isinstance(generated_dump, dict) else None
    record.update(
        {
            "category": fixture.get("category"),
            "golden": fixture.get("golden") is True,
            "expected_artifact_treatment": expected_treatment,
            "generated_artifact_treatment": generated_treatment,
            "query": fixture_query_boundary(expected),
        }
    )

    # expected.json is authoritative for the treatment contract.  The old
    # P0-B01 generated manifest predates dump.treatment, so a missing generated
    # treatment is explicitly recorded as a legacy metadata boundary.
    if expected_treatment != "complete":
        record.update(
            {
                "status": "not_published",
                "publish": False,
                "reason": "artifact_treatment is not complete",
            }
        )
        if generated_treatment == "complete":
            record["reason"] = "expected artifact_treatment is not complete; generated metadata disagrees"
        return record
    if generated is None:
        record.update(
            {
                "status": "rejected_missing_manifest",
                "publish": False,
                "reason": "complete fixture has no readable generated/manifest.json",
            }
        )
        return record
    if generated.get("fixture_id") != fixture.get("fixture_id"):
        record.update(
            {
                "status": "rejected_manifest_identity",
                "publish": False,
                "reason": "generated manifest fixture_id does not match fixture.json",
            }
        )
        return record
    if generated_treatment not in (None, "complete"):
        record.update(
            {
                "status": "rejected_treatment_mismatch",
                "publish": False,
                "reason": "expected complete but generated manifest treatment is not complete",
            }
        )
        return record
    target = generated.get("target", {})
    if not isinstance(target, dict):
        target = {}
    pe = resolve_fixture_path(fixture_dir, target.get("path"))
    pdb = resolve_fixture_path(fixture_dir, target.get("pdb"))
    code_id = normalize_id(target.get("code_id"))
    debug_id = normalize_id(target.get("debug_id"))
    errors: list[str] = []
    if pe is None or not pe.is_file():
        errors.append("matching PE is missing")
    if pdb is None or not pdb.is_file():
        errors.append("matching PDB is missing")
    if not code_id:
        errors.append("manifest target.code_id is missing")
    if not debug_id:
        errors.append("manifest target.debug_id is missing")

    actual_pe: dict[str, Any] | None = None
    if pe is not None and pe.is_file():
        try:
            actual_pe = parse_pe(pe)
        except (OSError, ValueError, struct.error) as error:
            errors.append(f"PE metadata parse failed: {type(error).__name__}: {error}")
    if actual_pe is not None:
        if code_id and normalize_id(actual_pe.get("code_id")) != code_id:
            errors.append(
                f"code_id mismatch: manifest={code_id}, PE={normalize_id(actual_pe.get('code_id'))}"
            )
        if debug_id and normalize_id(actual_pe.get("debug_id")) != debug_id:
            errors.append(
                f"debug_id mismatch: manifest={debug_id}, PE={normalize_id(actual_pe.get('debug_id'))}"
            )
    if pdb is not None and pdb.is_file() and pdb.stat().st_size == 0:
        errors.append("matching PDB is empty")

    record.update(
        {
            "publish": not errors,
            "pe": rel(pe) if pe else None,
            "pdb": rel(pdb) if pdb else None,
            "code_id": code_id,
            "debug_id": debug_id,
            "pe_metadata": actual_pe,
            "artifact_sha256": {
                "pe": sha256_file(pe) if pe and pe.is_file() else None,
                "pdb": sha256_file(pdb) if pdb and pdb.is_file() else None,
            },
        }
    )
    if errors:
        record.update({"status": "rejected_artifact_validation", "reason": "; ".join(errors), "errors": errors})
    else:
        record["status"] = "ready_to_sort"
    return record


def sha256_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_markdown(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = evidence["summary"]
    lines = [
        "# Golden Symbolicator symsorter evidence",
        "",
        f"- symsorter: **{evidence['version']}** ({evidence['asset']})",
        f"- expected SHA-256: `{evidence['expected_sha256']}`",
        f"- observed SHA-256: `{evidence['observed_sha256']}`",
        f"- complete fixtures discovered: **{summary['complete_discovered']}**",
        f"- complete fixtures sorted: **{summary['sorted']}**",
        f"- complete fixture failures: **{summary['failed']}**",
        f"- non-complete fixtures not published: **{summary['not_published']}**",
        "",
        "| Fixture | Code ID | Debug ID | symsorter | Unified layout | Query boundary |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in evidence["fixtures"]:
        if item.get("expected_artifact_treatment") != "complete":
            continue
        layout = item.get("layout", {})
        lines.append(
            "| {fixture_id} | `{code_id}` | `{debug_id}` | `{sort_status}` | `{layout_status}` | delegated |".format(
                fixture_id=item.get("fixture_id"),
                code_id=item.get("code_id") or "-",
                debug_id=item.get("debug_id") or "-",
                sort_status=item.get("sort_status", item.get("status", "-")),
                layout_status="ready" if layout.get("ready_for_symbolicator") else "not-ready",
            )
        )
    lines.extend(["", "## Not published", ""])
    not_published = [item for item in evidence["fixtures"] if item.get("expected_artifact_treatment") != "complete"]
    if not_published:
        for item in not_published:
            lines.append(
                f"- `{item.get('fixture_id')}`: `{item.get('expected_artifact_treatment')}`; {item.get('reason', 'not published')}"
            )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Query boundary",
            "",
            "The sort evidence proves only the pinned PE/PDB was accepted and placed in Unified layout.",
            "Several debug fixtures intentionally share one compiler-produced PE/PDB identity; after the first write, symsorter reports a duplicate-file warning and the script validates the existing same-ID layout rather than treating Sorted 0 as a new artifact.",
            "For every complete fixture, the first expected business-frame symbol is recorded in JSON and the actual address query is delegated to `scripts/phase0/golden_runner.py`.",
            "",
            "## Reproduction",
            "",
            "```text",
            "PYTHONDONTWRITEBYTECODE=1 python scripts/symbolicator/sort_golden.py --clean",
            "```",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=FIXTURE_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--clean", action="store_true", help="remove only selected debug-id prefixes before sorting")
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--only", nargs="*", help="optional fixture IDs; default is all discovered fixtures")
    args = parser.parse_args()

    fixtures_root = args.fixtures if args.fixtures.is_absolute() else ROOT / args.fixtures
    output = args.output if args.output.is_absolute() else ROOT / args.output
    evidence_path = args.evidence if args.evidence.is_absolute() else ROOT / args.evidence
    if not fixtures_root.is_dir():
        raise SystemExit(f"fixture root does not exist: {fixtures_root}")
    output.mkdir(parents=True, exist_ok=True)

    tool, expected_hash, observed_hash = download_pinned(force=args.force_download)
    discovered = [
        discover_fixture(path)
        for path in sorted(fixtures_root.iterdir())
        if path.is_dir() and not path.name.startswith("_") and (path / "fixture.json").is_file()
    ]
    if args.only:
        requested = set(args.only)
        discovered = [item for item in discovered if item.get("fixture_id") in requested]
    complete_discovered = sum(item.get("expected_artifact_treatment") == "complete" for item in discovered)
    if complete_discovered == 0:
        raise SystemExit("no complete fixture found")

    cleaned: set[str] = set()
    for item in discovered:
        if item.get("status") != "ready_to_sort":
            continue
        code_id = item["code_id"]
        debug_id = item["debug_id"]
        prefix = unified_prefix(output, debug_id)
        if args.clean and debug_id not in cleaned and prefix.is_dir():
            shutil.rmtree(prefix)
        cleaned.add(debug_id)

        pe = ROOT / item["pe"] if not Path(item["pe"]).is_absolute() else Path(item["pe"])
        pdb = ROOT / item["pdb"] if not Path(item["pdb"]).is_absolute() else Path(item["pdb"])
        sort_args = ["--output", str(output), str(pe), str(pdb)]
        result = run_tool(tool, *sort_args, check=False)
        item["command"] = [str(tool), *sort_args]
        item["returncode"] = result.returncode
        item["stdout"] = result.stdout
        item["stderr"] = result.stderr
        duplicate_warning = "duplicate debug files" in result.stderr.lower()
        item["sort_status"] = (
            "sorted_existing_duplicate"
            if result.returncode == 0 and duplicate_warning
            else ("sorted" if result.returncode == 0 else "symsorter_failed")
        )
        item["duplicate_identity_warning"] = duplicate_warning
        if result.returncode == 0:
            item["layout"] = validate_layout(output, code_id, debug_id)
            if item["layout"]["ready_for_symbolicator"]:
                item["status"] = "sorted_verified"
            else:
                item["status"] = "layout_validation_failed"
        else:
            item["layout"] = {"ready_for_symbolicator": False}

    failed = sum(
        item.get("expected_artifact_treatment") == "complete"
        and item.get("status") != "sorted_verified"
        for item in discovered
    )
    not_published = sum(item.get("expected_artifact_treatment") != "complete" for item in discovered)
    evidence: dict[str, Any] = {
        "schema_version": "symsorter-golden-evidence-v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
        "asset": ASSET_NAME,
        "download_url": DOWNLOAD_URL,
        "expected_sha256": expected_hash,
        "observed_sha256": observed_hash,
        "tool_path": rel(tool),
        "output_root": rel(output),
        "clean_selected_debug_ids": args.clean,
        "summary": {
            "discovered": len(discovered),
            "complete_discovered": complete_discovered,
            "sorted": complete_discovered - failed,
            "failed": failed,
            "not_published": not_published,
        },
        "fixtures": discovered,
        "query_boundary": {
            "status": "deferred_to_batch_runner",
            "runner": "scripts/phase0/golden_runner.py",
            "scope": "every complete fixture has query.first_expected_business_frame in its record",
        },
    }
    write_json(evidence_path, evidence)
    write_markdown(evidence_path.with_suffix(".md"), evidence)
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    return 0 if failed == 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
