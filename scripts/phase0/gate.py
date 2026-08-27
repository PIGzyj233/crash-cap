#!/usr/bin/env python3
"""Evaluate the Phase 0 hard gate from current machine-readable evidence.

This command never turns missing or partial evidence into a pass. It also runs
the contract compatibility suite and validates every produced Canonical result
against the stable v1 schema before issuing GO.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JSON = ROOT / "docs" / "evidence" / "phase0-go-no-go.json"
DEFAULT_MD = ROOT / "docs" / "evidence" / "phase0-go-no-go.md"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")

EVIDENCE_PATHS = {
    "golden": ROOT / "docs" / "evidence" / "phase0-golden-results.json",
    "fixtures": ROOT / "docs" / "evidence" / "golden-fixtures.json",
    "rustfs": ROOT / "docs" / "evidence" / "rustfs-qualification.json",
    "calibration": ROOT / "docs" / "evidence" / "phase0-calibration.json",
    "core_oci": ROOT / "docs" / "evidence" / "core-oci.json",
    "symbolicator": ROOT / "docs" / "evidence" / "symbolicator-p0.json",
    "authorized_sample": ROOT / "docs" / "evidence" / "authorized-real-sample.json",
    "ci": ROOT / "docs" / "evidence" / "ci-phase0-verification.json",
    "toolchain": ROOT / "docs" / "evidence" / "toolchain.json",
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def run(command: list[str], timeout: int = 300) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        return {
            "command": command,
            "exit_code": completed.returncode,
            "stdout_tail": (completed.stdout or "")[-4000:],
            "stderr_tail": (completed.stderr or "")[-4000:],
        }
    except (OSError, subprocess.TimeoutExpired) as error:
        return {
            "command": command,
            "exit_code": None,
            "error": f"{type(error).__name__}: {error}",
        }


def check(
    check_id: str,
    title: str,
    passed: bool,
    observed: Any,
    evidence: list[str],
) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": title,
        "status": "PASS" if passed else "FAIL",
        "observed": observed,
        "evidence": evidence,
    }


def metric(golden: dict[str, Any], name: str) -> dict[str, Any]:
    value = (golden.get("metrics") or {}).get(name)
    return value if isinstance(value, dict) else {}


def recursive_schema_versions(value: Any) -> set[str]:
    versions: set[str] = set()
    if isinstance(value, dict):
        if "schema_version" in value and isinstance(value["schema_version"], dict):
            const = value["schema_version"].get("const")
            if isinstance(const, str):
                versions.add(const)
        for child in value.values():
            versions.update(recursive_schema_versions(child))
    elif isinstance(value, list):
        for child in value:
            versions.update(recursive_schema_versions(child))
    return versions


def contract_checks(golden: dict[str, Any]) -> dict[str, Any]:
    v0_names = [
        "analysis-result-v0.schema.json",
        "build-manifest-v0.schema.json",
        "task-message-v0.schema.json",
    ]
    v1_names = [
        "analysis-result-v1.schema.json",
        "build-manifest-v1.schema.json",
        "task-message-v1.schema.json",
    ]
    files: dict[str, Any] = {}
    metadata_ok = True
    for name in [*v0_names, *v1_names]:
        path = ROOT / "contracts" / name
        try:
            document = load(path)
            expected = "0.1" if "-v0." in name else "1.0"
            versions = sorted(recursive_schema_versions(document))
            stable_metadata = (
                document.get("$schema") == "https://json-schema.org/draft/2020-12/schema"
                and str(document.get("$id", "")).endswith(name)
                and versions == [expected]
            )
            files[name] = {
                "present": True,
                "schema_versions": versions,
                "id": document.get("$id"),
                "metadata_ok": stable_metadata,
            }
            metadata_ok = metadata_ok and stable_metadata
        except (OSError, ValueError, json.JSONDecodeError) as error:
            files[name] = {"present": False, "error": f"{type(error).__name__}: {error}"}
            metadata_ok = False

    suite = run(["cargo", "test", "-p", "crash-cap-schema-tests"], timeout=300)
    canonical_paths: list[str] = []
    canonical_versions: dict[str, Any] = {}
    for fixture in golden.get("fixtures", []):
        if not isinstance(fixture, dict):
            continue
        path_value = (fixture.get("paths") or {}).get("canonical")
        if not isinstance(path_value, str):
            continue
        path = Path(path_value)
        if not path.is_file():
            continue
        try:
            canonical = load(path)
            canonical_versions[str(fixture.get("fixture_id"))] = canonical.get("schema_version")
            canonical_paths.append(str(path))
        except (OSError, ValueError, json.JSONDecodeError) as error:
            canonical_versions[str(fixture.get("fixture_id"))] = f"ERROR: {error}"

    instance_validation = (
        run(
            [
                "cargo",
                "run",
                "--quiet",
                "-p",
                "crash-cap-schema-tests",
                "--bin",
                "validate-instance",
                "--",
                str(ROOT / "contracts" / "analysis-result-v1.schema.json"),
                *canonical_paths,
            ],
            timeout=300,
        )
        if canonical_paths
        else {"command": [], "exit_code": None, "error": "no Canonical results found"}
    )
    design = (ROOT / "docs" / "design.md").read_text(encoding="utf-8")
    api_v1_frozen = "stable API prefix: `/api/v1`" in design
    passed = (
        metadata_ok
        and suite.get("exit_code") == 0
        and instance_validation.get("exit_code") == 0
        and bool(canonical_paths)
        and all(value == "1.0" for value in canonical_versions.values())
        and api_v1_frozen
    )
    return {
        "status": "PASS" if passed else "FAIL",
        "files": files,
        "compatibility_suite": suite,
        "canonical_instance_validation": instance_validation,
        "canonical_versions": canonical_versions,
        "canonical_count": len(canonical_paths),
        "api_prefix": "/api/v1",
        "api_prefix_frozen_in_design": api_v1_frozen,
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Phase 0 Go/No-Go",
        "",
        f"Decision: **{report['decision']}**",
        f"Status: **{report['status']}**",
        f"Evaluated (UTC): `{report['evaluated_at_utc']}`",
        f"Core OCI digest: `{report.get('core_image_digest')}`",
        "",
        "| Gate | Result | Observed |",
        "| --- | --- | --- |",
    ]
    for item in report["gates"]:
        observed = json.dumps(item.get("observed"), ensure_ascii=False, separators=(",", ":"))
        if len(observed) > 220:
            observed = observed[:217] + "..."
        lines.append(f"| `{item['id']}` {item['title']} | **{item['status']}** | `{observed}` |")
    lines += [
        "",
        "## Supporting checks",
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
    for item in report["supporting_checks"]:
        lines.append(f"| `{item['id']}` {item['title']} | **{item['status']}** |")
    lines += [
        "",
        "## Evidence boundary",
        "",
        "- Verification was executed locally on Docker Desktop and the recorded Windows/MSVC toolchain.",
        "- No remote GitHub Actions run and no production deployment/network were executed by this report.",
        "- The authorized real-origin case is a pinned public upstream test artifact stored in a private local RustFS bucket; it is not a Crash-Cap production incident.",
        "- RustFS qualification is single-node local Docker evidence and does not prove distributed durability or production RPO/RTO.",
        "",
        f"Machine-readable evidence: `{report['output_json']}`",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    output_json = args.output_json if args.output_json.is_absolute() else ROOT / args.output_json
    output_md = args.output_md if args.output_md.is_absolute() else ROOT / args.output_md

    try:
        evidence = {name: load(path) for name, path in EVIDENCE_PATHS.items()}
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2

    golden = evidence["golden"]
    fixtures = evidence["fixtures"]
    rustfs = evidence["rustfs"]
    calibration = evidence["calibration"]
    core_oci = evidence["core_oci"]
    symbolicator = evidence["symbolicator"]
    authorized = evidence["authorized_sample"]
    ci = evidence["ci"]
    toolchain = evidence["toolchain"]

    core_digest = (core_oci.get("runtime") or {}).get("local_image_id")
    golden_digest = (golden.get("arguments") or {}).get("core_image_digest")
    calibration_digest = calibration.get("core_image_digest")

    m_exception = metric(golden, "valid_complete_matched_exception_code_accuracy")
    m_thread = metric(golden, "crashing_thread_accuracy")
    m_mismatch = metric(golden, "pdb_mismatch_detection_rate")
    m_top3 = metric(golden, "complete_symbol_sample_top3_business_frame_equivalence")
    m_silent = metric(golden, "silent_wrong_symbol_count")

    golden_all_pass = (
        golden.get("status") == "PASS"
        and (golden.get("counts") or {}).get("PASS") == 21
        and set((golden.get("counts") or {}).keys()) == {"PASS"}
    )
    contracts = contract_checks(golden)

    ci_checks = ci.get("checks") or []
    required_ci_ok = ci.get("required_ci_checks_passed") is True and not any(
        isinstance(item, dict) and item.get("status") == "FAIL" for item in ci_checks
    )
    required_tools = [
        item
        for item in toolchain.get("tools", [])
        if isinstance(item, dict) and item.get("required_for_phase0")
    ]
    toolchain_ok = bool(required_tools) and all(item.get("status") == "available" for item in required_tools)
    calibration_items = calibration.get("items") or {}
    calibration_ok = (
        calibration.get("overall_status") == "PASS"
        and all((calibration_items.get(name) or {}).get("status") == "PASS" for name in ["F03", "F04", "F05", "F06", "F07"])
        and ((calibration_items.get("F07") or {}).get("cache_boundary") or {}).get("cold_cache_proven") is True
        and "provisional" not in str((calibration_items.get("F04") or {}).get("decision", "")).lower()
        and "provisional" not in str((calibration_items.get("F06") or {}).get("decision", "")).lower()
    )
    core_oci_ok = (
        core_oci.get("status") == "PASS"
        and isinstance(core_digest, str)
        and DIGEST.fullmatch(core_digest) is not None
        and core_digest == golden_digest == calibration_digest
        and (core_oci.get("readonly_rootfs") or {}).get("status") == "PASS"
        and (core_oci.get("runtime") or {}).get("user") == "65532:65532"
    )
    symbolicator_ok = (
        symbolicator.get("healthcheck", {}).get("status") == 200
        and symbolicator.get("request_source_policy", {}).get("error_code") == "REQUEST_SOURCES_FORBIDDEN"
        and symbolicator.get("running_image_id") == "sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959"
    )
    authorized_ok = (
        authorized.get("classification") == "public-upstream-real-origin-test-artifact"
        and authorized.get("not_claimed_as") == "Crash-Cap production incident"
        and authorized.get("repository_binary_policy", {}).get("committed_binary") is False
        and authorized.get("private_storage", {}).get("anonymous_get_status") == 403
        and authorized.get("private_storage", {}).get("server_side_encryption") == "AES256"
        and authorized.get("source", {}).get("sha256") == authorized.get("private_storage", {}).get("stream_sha256")
    )
    supporting = [
        check("SUPPORT-CORE-OCI", "final Core image identity and sandbox", core_oci_ok, {"core": core_digest, "golden": golden_digest, "calibration": calibration_digest}, [str(EVIDENCE_PATHS["core_oci"]), str(EVIDENCE_PATHS["golden"]), str(EVIDENCE_PATHS["calibration"])]),
        check("SUPPORT-SYMBOLICATOR", "pinned loopback Symbolicator policy", symbolicator_ok, {"running_image_id": symbolicator.get("running_image_id"), "health": symbolicator.get("healthcheck")}, [str(EVIDENCE_PATHS["symbolicator"])]),
        check("SUPPORT-CALIBRATION", "F03-F07 frozen calibration", calibration_ok, {"overall": calibration.get("overall_status"), "cold_cache": ((calibration_items.get("F07") or {}).get("cache_boundary") or {}).get("cold_cache_proven")}, [str(EVIDENCE_PATHS["calibration"])]),
        check("SUPPORT-AUTHORIZED", "authorized real-origin sample boundary", authorized_ok, {"classification": authorized.get("classification"), "anonymous_get": authorized.get("private_storage", {}).get("anonymous_get_status")}, [str(EVIDENCE_PATHS["authorized_sample"])]),
        check("SUPPORT-CI", "local required CI checks", required_ci_ok, {"overall": ci.get("overall_status"), "remote_ci_executed": ci.get("remote_ci_executed")}, [str(EVIDENCE_PATHS["ci"])]),
        check("SUPPORT-TOOLCHAIN", "required Phase 0 toolchain", toolchain_ok, {"required_count": len(required_tools)}, [str(EVIDENCE_PATHS["toolchain"])]),
    ]

    fixture_count = fixtures.get("discovered_golden_count")
    fixture_ok = (
        golden_all_pass
        and isinstance(fixture_count, int)
        and 20 <= fixture_count <= 50
        and fixtures.get("expected_count") == fixture_count
        and fixtures.get("gaps") == []
        and authorized_ok
    )
    rustfs_cases = rustfs.get("cases") or []
    rustfs_candidate = rustfs.get("candidate") or {}
    rustfs_digest = rustfs_candidate.get("manifest_digest")
    rustfs_endpoint = rustfs_candidate.get("s3_endpoint")
    rustfs_tls = rustfs_candidate.get("tls_peer_verification")
    rustfs_e04 = next(
        (
            item
            for item in rustfs_cases
            if isinstance(item, dict) and item.get("case_id") == "P0-E04"
        ),
        {},
    )
    rustfs_e04_details = rustfs_e04.get("details") or {}
    rustfs_ok = (
        rustfs.get("qualification_status") == "QUALIFIED"
        and len(rustfs_cases) == 10
        and all(isinstance(item, dict) and item.get("status") == "PASS" for item in rustfs_cases)
        and isinstance(rustfs_digest, str)
        and DIGEST.fullmatch(rustfs_digest) is not None
        and isinstance(rustfs_endpoint, str)
        and rustfs_endpoint.startswith("https://")
        and rustfs_tls == "strict CA and SAN verification"
        and rustfs_e04_details.get("endpoint_scheme") == "https"
        and rustfs_e04_details.get("tls_peer_verification")
        == "strict CA and SAN verification"
        and re.fullmatch(r"[0-9a-f]{64}", str(rustfs_e04_details.get("ca_bundle_sha256")))
        is not None
    )

    gates = [
        check("GATE-P0-01", "exception code accuracy = 100%", m_exception.get("status") == "PASS" and m_exception.get("rate") == 1.0 and int(m_exception.get("denominator") or 0) > 0, m_exception, [str(EVIDENCE_PATHS["golden"])]),
        check("GATE-P0-02", "crashing thread accuracy = 100%", m_thread.get("status") == "PASS" and m_thread.get("rate") == 1.0 and int(m_thread.get("denominator") or 0) > 0, m_thread, [str(EVIDENCE_PATHS["golden"])]),
        check("GATE-P0-03", "PDB mismatch detection = 100%", m_mismatch.get("status") == "PASS" and m_mismatch.get("rate") == 1.0 and int(m_mismatch.get("denominator") or 0) > 0, m_mismatch, [str(EVIDENCE_PATHS["golden"])]),
        check("GATE-P0-04", "top-3 business-frame equivalence >= 95%", m_top3.get("status") == "PASS" and float(m_top3.get("rate") or 0.0) >= 0.95 and int(m_top3.get("denominator") or 0) == 11, m_top3, [str(EVIDENCE_PATHS["golden"])]),
        check("GATE-P0-05", "silent wrong symbols = 0", m_silent.get("status") == "PASS" and m_silent.get("count") == 0, m_silent, [str(EVIDENCE_PATHS["golden"])]),
        check("GATE-P0-06", "20-50 auditable Golden fixtures", fixture_ok, {"golden_status": golden.get("status"), "fixture_count": fixture_count, "counts": golden.get("counts")}, [str(EVIDENCE_PATHS["golden"]), str(EVIDENCE_PATHS["fixtures"]), str(EVIDENCE_PATHS["authorized_sample"])]),
        check("GATE-P0-07", "RustFS S3 qualification", rustfs_ok, {"status": rustfs.get("qualification_status"), "case_count": len(rustfs_cases), "digest": rustfs_digest, "endpoint": rustfs_endpoint, "tls_peer_verification": rustfs_tls}, [str(EVIDENCE_PATHS["rustfs"])]),
        check("GATE-P0-08", "stable v1 contracts and /api/v1", contracts.get("status") == "PASS", {"contract_status": contracts.get("status"), "canonical_count": contracts.get("canonical_count"), "api_prefix": contracts.get("api_prefix")}, [str(ROOT / "contracts"), str(ROOT / "docs" / "design.md")]),
    ]
    prerequisites_pass = all(item["status"] == "PASS" for item in [*gates, *supporting])
    decision = "GO" if prerequisites_pass else "NO-GO"
    gates.append(
        check(
            "GATE-P0-09",
            "recorded Go/No-Go decision",
            prerequisites_pass,
            {"decision": decision, "failed_prerequisites": [item["id"] for item in [*gates, *supporting] if item["status"] != "PASS"]},
            [str(DEFAULT_JSON), str(DEFAULT_MD)],
        )
    )
    overall = "PASS" if all(item["status"] == "PASS" for item in gates) else "FAIL"
    report = {
        "schema_version": "phase0-go-no-go-v1.0",
        "evaluated_at_utc": utc_now(),
        "status": overall,
        "decision": decision,
        "phase0_complete": overall == "PASS" and decision == "GO",
        "core_image_digest": core_digest,
        "symbolicator_image_digest": symbolicator.get("running_image_id"),
        "rustfs_image_digest": rustfs_digest,
        "gates": gates,
        "supporting_checks": supporting,
        "contracts": contracts,
        "evidence_paths": {name: str(path) for name, path in EVIDENCE_PATHS.items()},
        "remote_ci_executed": False,
        "boundaries": [
            "Local Docker Desktop and Windows/MSVC verification only; no production deployment proof.",
            "Remote GitHub Actions was not executed.",
            "Authorized real-origin sample is pinned public upstream testdata, not a Crash-Cap production incident.",
            "RustFS evidence is single-node local qualification, not distributed durability or production RPO/RTO.",
        ],
        "output_json": str(output_json),
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output_md.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"status": overall, "decision": decision, "json": str(output_json), "markdown": str(output_md)}, ensure_ascii=False, indent=2))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
