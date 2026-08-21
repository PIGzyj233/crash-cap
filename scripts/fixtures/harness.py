#!/usr/bin/env python3
"""Validate Phase 0 Golden fixture metadata and local evidence.

Only built-in execution kinds are accepted. The harness never evaluates a
manifest command or launches a fixture-provided executable.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


HARNESS_SCHEMA = "fixture-harness-v0.2"
GOLDEN_CATEGORIES = {"P0-D03", "P0-D04", "P0-D05", "P0-D06", "P0-D07"}
REQUIRED_FIXTURE_KEYS = {
    "schema_version", "fixture_id", "golden", "category", "source", "platform",
    "scenario", "build", "capture", "artifacts", "execution", "expected_file",
    "binary_policy",
}
REQUIRED_EXPECTED_KEYS = {"schema_version", "fixture_id", "expected", "allowed_differences", "verification"}
REQUIRED_EXPECTED_EVIDENCE_KEYS = {
    "dump", "exception", "crashing_thread", "business_frames", "module_ids",
    "artifact_treatment", "warnings", "reference_boundary",
}
FORBIDDEN_BINARY_SUFFIXES = {
    ".dmp", ".exe", ".dll", ".pdb", ".obj", ".ilk", ".lib", ".exp", ".bin",
}


def load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"cannot read JSON: {exc}"
    if not isinstance(value, dict):
        return None, "top-level JSON value must be an object"
    return value, None


def normalize_hex(value: Any) -> str:
    return str(value or "").replace("0x", "").replace("0X", "").upper()


def verifier_result(value: dict[str, Any]) -> dict[str, Any]:
    result = value.get("result")
    if isinstance(result, dict):
        return result
    # P0-B01 predates the generic verifier and stores its result at top level.
    result = dict(value)
    if "ok" in result and "valid_dump" not in result:
        result["valid_dump"] = bool(result.get("ok"))
    if "has_exception" not in result:
        result["has_exception"] = isinstance(result.get("exception"), dict)
    return result


def check_binary_policy(directory: Path, manifest: dict[str, Any], errors: list[str], warnings: list[str]) -> None:
    generated = directory / "generated"
    binaries_found: list[str] = []
    if generated.exists():
        for path in generated.rglob("*"):
            if path.is_file() and path.suffix.lower() in FORBIDDEN_BINARY_SUFFIXES:
                binaries_found.append(path.relative_to(directory).as_posix())
    if binaries_found:
        warnings.append(
            "local generated binaries present (expected; must remain ignored): "
            + ", ".join(sorted(binaries_found))
        )
    if manifest.get("binary_policy") == "no_binary" and binaries_found:
        errors.append("metadata-only fixture unexpectedly contains binary artifacts")


def check_golden_runtime(
    directory: Path,
    manifest: dict[str, Any],
    expected: dict[str, Any],
    errors: list[str],
    warnings: list[str],
) -> tuple[bool, str]:
    execution = manifest.get("execution", {})
    if not isinstance(execution, dict):
        errors.append("execution must be an object")
        return False, "invalid_execution"
    kind = execution.get("kind")
    if kind not in {
        "windows-independent-minidump",
        "windows-derived-artifact",
        "private-object-authorized-minidump",
    }:
        errors.append(f"unsupported Golden built-in execution kind: {kind!r}")
        return False, "unsupported_execution"

    generated = directory / "generated"
    manifest_path = generated / "manifest.json"
    validation_path = generated / "validation.json"
    verifier_path = generated / "verifier-result.json"
    for path in (manifest_path, validation_path, verifier_path):
        if not path.is_file():
            errors.append(f"missing generated evidence: {path.relative_to(directory).as_posix()}")
    if errors:
        return False, "not_generated"

    generated_manifest, manifest_error = load_json(manifest_path)
    validation, validation_error = load_json(validation_path)
    verifier, verifier_error = load_json(verifier_path)
    if manifest_error:
        errors.append(f"generated/manifest.json: {manifest_error}")
    if validation_error:
        errors.append(f"generated/validation.json: {validation_error}")
    if verifier_error:
        errors.append(f"generated/verifier-result.json: {verifier_error}")
    if not generated_manifest or generated_manifest.get("fixture_id") != manifest.get("fixture_id"):
        errors.append("generated manifest fixture_id does not match fixture.json")
    if not validation or validation.get("status") not in {"verified_local", "preserved_existing_verified"}:
        errors.append("generated validation does not report verified_local")
    if not verifier:
        return False, "invalid_verifier"

    result = verifier_result(verifier)
    expected_dump = expected.get("dump", {})
    expected_exception = expected.get("exception")
    if expected_dump.get("valid_dump") is not None and result.get("valid_dump") is not None:
        if bool(expected_dump["valid_dump"]) != bool(result.get("valid_dump")):
            errors.append(f"valid_dump={result.get('valid_dump')!r}, expected {expected_dump['valid_dump']!r}")
    if expected_dump.get("has_exception") is not None and result.get("has_exception") is not None:
        if bool(expected_dump["has_exception"]) != bool(result.get("has_exception")):
            errors.append(f"has_exception={result.get('has_exception')!r}, expected {expected_dump['has_exception']!r}")
    if expected_exception is not None and result.get("exception"):
        actual_code = normalize_hex(result["exception"].get("code"))
        expected_code = normalize_hex(expected_exception.get("code"))
        if actual_code != expected_code:
            errors.append(f"exception code {actual_code!r} does not match expected {expected_code!r}")
    if expected_exception is not None and not result.get("exception"):
        errors.append("expected exception object is absent from generated verifier result")
    if expected_exception is None and result.get("has_exception") is True:
        errors.append("expected no exception stream but generated verifier reports one")

    target_architecture = (generated_manifest.get("target") or {}).get("architecture")
    expected_architecture = expected_dump.get("architecture")
    if expected_architecture == "x86" and target_architecture != "x86":
        errors.append(f"target PE architecture={target_architecture!r}, expected x86")
    if expected_architecture == "x86_64" and target_architecture not in {"x86_64", None}:
        errors.append(f"target PE architecture={target_architecture!r}, expected x86_64")

    artifact_treatment = expected.get("artifact_treatment")
    artifacts = (validation or {}).get("artifacts", {})
    if artifact_treatment == "missing_pdb" and artifacts.get("pdb_present") is True:
        errors.append("missing_pdb fixture unexpectedly has a PDB")
    if artifact_treatment == "missing_pe" and artifacts.get("pe_present") is True:
        errors.append("missing_pe fixture unexpectedly has a PE")
    if artifact_treatment in {"corrupt_dump", "truncated_dump"} and result.get("valid_dump") is True:
        errors.append(f"{artifact_treatment} fixture was accepted as valid")
    if kind == "private-object-authorized-minidump":
        source = manifest.get("source", {})
        if source.get("authorization") in {None, "", "not_applicable"}:
            errors.append("authorized real-origin fixture lacks an auditable authorization")
        private_storage = (validation or {}).get("private_storage", {})
        if not str(private_storage.get("uri", "")).startswith("s3://"):
            errors.append("authorized real-origin fixture lacks its private object URI")
        if private_storage.get("anonymous_get_status") not in {401, 403, 404}:
            errors.append("authorized real-origin object was not proven private")
        if private_storage.get("server_side_encryption") != "AES256":
            errors.append("authorized real-origin object lacks the expected SSE-S3 evidence")

    reference_file = manifest.get("reference_file")
    if reference_file:
        reference_path = directory / str(reference_file)
        if not reference_path.is_file():
            errors.append(f"fixture missing reference boundary/debugger summary: {reference_file}")
    return not errors, "verified_local"


def check_fixture(directory: Path, *, metadata_only: bool = False) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    manifest_path = directory / "fixture.json"
    manifest, error = load_json(manifest_path)
    if error or manifest is None:
        return {"fixture_id": directory.name, "status": "FAIL", "discovered": False, "executed": False, "errors": [error or "missing fixture.json"], "warnings": []}
    missing = sorted(REQUIRED_FIXTURE_KEYS - manifest.keys())
    if missing:
        errors.append("fixture.json missing keys: " + ", ".join(missing))
    fixture_id = manifest.get("fixture_id", directory.name)
    if fixture_id != directory.name:
        errors.append(f"fixture_id {fixture_id!r} does not match directory {directory.name!r}")
    source = manifest.get("source")
    if not isinstance(source, dict) or not source.get("authorization"):
        errors.append("source.authorization is required")
    expected_path = directory / str(manifest.get("expected_file", "expected.json"))
    expected, expected_error = load_json(expected_path)
    if expected_error or expected is None:
        errors.append(expected_error or f"missing {expected_path.name}")
    else:
        missing_expected = sorted(REQUIRED_EXPECTED_KEYS - expected.keys())
        if missing_expected:
            errors.append("expected.json missing keys: " + ", ".join(missing_expected))
        if expected.get("fixture_id") != fixture_id:
            errors.append("expected.json fixture_id does not match fixture.json")

    golden = manifest.get("golden") is True
    if not golden:
        execution = manifest.get("execution", {})
        kind = execution.get("kind") if isinstance(execution, dict) else None
        check_binary_policy(directory, manifest, errors, warnings)
        if kind == "metadata-only":
            return {"fixture_id": fixture_id, "status": "PASS" if not errors else "FAIL", "discovered": True, "executed": True, "execution_status": "metadata_only", "golden": False, "manifest": str(manifest_path.relative_to(directory.parent.parent)).replace(os.sep, "/"), "errors": errors, "warnings": warnings}
        errors.append("non-Golden fixture must use metadata-only built-in execution")
        return {"fixture_id": fixture_id, "status": "FAIL", "discovered": True, "executed": False, "golden": False, "errors": errors, "warnings": warnings}

    if manifest.get("category") not in GOLDEN_CATEGORIES:
        errors.append(f"Golden fixture has unsupported category: {manifest.get('category')!r}")
    expected_object = expected.get("expected", {}) if isinstance(expected, dict) else {}
    missing_evidence = sorted(REQUIRED_EXPECTED_EVIDENCE_KEYS - expected_object.keys())
    if missing_evidence:
        errors.append("expected.expected missing keys: " + ", ".join(missing_evidence))
    check_binary_policy(directory, manifest, errors, warnings)
    if metadata_only:
        reference_file = manifest.get("reference_file")
        if reference_file and not (directory / str(reference_file)).is_file():
            errors.append(f"fixture missing reference boundary/debugger summary: {reference_file}")
        return {
            "fixture_id": fixture_id,
            "status": "FAIL" if errors else "PASS",
            "discovered": True,
            "executed": False,
            "golden": True,
            "category": manifest.get("category"),
            "source_kind": source.get("kind") if isinstance(source, dict) else None,
            "source_authorization": source.get("authorization") if isinstance(source, dict) else None,
            "execution_status": "metadata_validated",
            "manifest": str(manifest_path.relative_to(directory.parent.parent)).replace(os.sep, "/"),
            "errors": errors,
            "warnings": warnings,
        }
    executed, execution_status = check_golden_runtime(directory, manifest, expected_object, errors, warnings)
    status = "FAIL" if errors else ("PASS" if executed else "SKIP")
    return {
        "fixture_id": fixture_id,
        "status": status,
        "discovered": True,
        "executed": executed,
        "golden": True,
        "category": manifest.get("category"),
        "source_kind": source.get("kind") if isinstance(source, dict) else None,
        "source_authorization": source.get("authorization") if isinstance(source, dict) else None,
        "execution_status": execution_status,
        "manifest": str(manifest_path.relative_to(directory.parent.parent)).replace(os.sep, "/"),
        "errors": errors,
        "warnings": warnings,
    }


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_coverage(path: Path, results: list[dict[str, Any]], expected_count: int) -> None:
    golden = [item for item in results if item.get("golden")]
    categories: dict[str, list[str]] = {}
    for item in golden:
        categories.setdefault(str(item.get("category")), []).append(str(item["fixture_id"]))
    gaps = []
    if len(golden) != expected_count:
        gaps.append(f"expected {expected_count} Golden fixtures, discovered {len(golden)}")
    if any(item.get("status") != "PASS" for item in golden):
        gaps.append("one or more Golden fixtures failed metadata/runtime evidence validation")
    authorized = [
        item
        for item in golden
        if item.get("category") == "P0-D07"
        and item.get("status") == "PASS"
        and item.get("source_authorization") not in {None, "", "not_applicable"}
    ]
    if not authorized:
        gaps.append("P0-D07: no authorized real-origin sample passed the fixture and private-storage checks")
    authorized_record = (
        {
            "status": "present",
            "fixture_ids": [str(item["fixture_id"]) for item in authorized],
            "classification": "public-upstream-real-origin-test-artifact",
            "production_incident_claimed": False,
        }
        if authorized
        else {"status": "gap", "reason": "No authorized real-origin sample passed validation."}
    )
    record = {
        "schema_version": "golden-fixture-coverage-v0.1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "expected_count": expected_count,
        "discovered_golden_count": len(golden),
        "categories": categories,
        "fixtures": results,
        "gaps": gaps,
        "real_authorized_sample": authorized_record,
    }
    write_text(path, json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    md_lines = [
        "# Golden fixture coverage", "", f"- Expected Golden count: **{expected_count}**",
        f"- Discovered Golden count: **{len(golden)}**",
        (
            f"- P0-D07 authorized real-origin sample: **PASS** ({len(authorized)}; public upstream test artifact, not production)"
            if authorized
            else "- P0-D07 authorized real-origin sample: **GAP**"
        ),
        "",
        "| Category | Count | Fixtures |", "| --- | ---: | --- |",
    ]
    for category in sorted(categories):
        ids = categories[category]
        md_lines.append(f"| {category} | {len(ids)} | {', '.join(ids)} |")
    md_lines.extend(["", "## Boundaries", ""])
    md_lines.extend(f"- {gap}" for gap in gaps)
    write_text(path.with_suffix(".md"), "\n".join(md_lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=Path("fixtures"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--coverage-output", type=Path)
    parser.add_argument("--expected-golden-count", type=int, default=21)
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="validate reviewable fixture metadata without claiming generated runtime evidence",
    )
    parser.add_argument(
        "--exclude-fixture",
        action="append",
        default=[],
        help="exclude one fixture id from this explicitly scoped lane; repeatable",
    )
    args = parser.parse_args()
    root = args.fixtures.resolve()
    if not root.is_dir():
        parser.error(f"fixture directory does not exist: {root}")
    results = [
        check_fixture(directory, metadata_only=args.metadata_only)
        for directory in sorted(path for path in root.iterdir() if path.is_dir())
        if not directory.name.startswith("_")
        and directory.name not in set(args.exclude_fixture)
        and (directory / "fixture.json").exists()
    ]
    golden_count = sum(item.get("golden") is True for item in results)
    summary = {
        "schema_version": HARNESS_SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fixture_root": str(root),
        "fixtures": results,
        "totals": {
            "discovered": len(results), "golden": golden_count,
            "executed": sum(bool(item.get("executed")) for item in results),
            "passed": sum(item.get("status") == "PASS" for item in results),
            "failed": sum(item.get("status") == "FAIL" for item in results),
            "skipped": sum(item.get("status") == "SKIP" for item in results),
        },
    }
    encoded = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    sys.stdout.write(encoded)
    if args.output:
        output = args.output if args.output.is_absolute() else Path.cwd() / args.output
        write_text(output, encoded)
    if args.coverage_output:
        coverage = args.coverage_output if args.coverage_output.is_absolute() else Path.cwd() / args.coverage_output
        write_coverage(coverage, results, args.expected_golden_count)
    return 1 if summary["totals"]["failed"] or golden_count != args.expected_golden_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
