#!/usr/bin/env python3
"""Validate and render a Phase 1 target UAT record.

This tool is a recorder/checker, not an automated acceptance authority.  It
never invents a tester, target, environment, evidence reference, or signature.
Without a completed answer file the result is ``NOT_PROVEN``.  A PASS requires
all sixteen Phase 1 gates to have explicit PASS answers with evidence, a named
developer or operations tester, target/environment metadata, and a traceable
attestation reference.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

OK_STATUS = "PASS"
ERROR_STATUS = "FAIL"
UNPROVEN_STATUS = "NOT_PROVEN"
GATE_IDS = tuple(f"GATE-P1-{number:02d}" for number in range(1, 17))
PLACEHOLDER_VALUES = {
    "",
    "todo",
    "tbd",
    "fill-me",
    "replace-me",
    "your-name",
    "your-target",
    "your-environment",
}


def _non_placeholder(value: Any) -> bool:
    return isinstance(value, str) and value.strip().lower() not in PLACEHOLDER_VALUES


def _is_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _is_http_target_url(value: Any) -> bool:
    if not _non_placeholder(value):
        return False
    parsed = urlsplit(str(value).strip())
    return (
        parsed.scheme == "http"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and not parsed.query
        and not parsed.fragment
    )


def checklist_template() -> dict[str, Any]:
    return {
        "tester": {
            "name": "",
            "role": "",
            "is_developer": None,
            "contact": "",
        },
        "target": {
            "name": "",
            "base_url": "",
            "network": "",
            "release_identity": "",
        },
        "environment": {
            "name": "",
            "observed_at": "",
            "host_or_cluster": "",
            "evidence_refs": [],
        },
        "steps": {
            gate_id: {
                "status": UNPROVEN_STATUS,
                "evidence": [],
                "observed_at": "",
                "notes": "",
            }
            for gate_id in GATE_IDS
        },
        "evidence_refs": [],
        "signoff": {
            "signed_by": "",
            "signed_at": "",
            "signature_ref": "",
            "statement": "",
        },
    }


def validate_record(record: Any) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(record, dict):
        return {
            "schema_version": "1.0",
            "status": UNPROVEN_STATUS,
            "errors": ["UAT answer file must contain a JSON object"],
            "warnings": [],
            "gate_results": [],
        }

    tester = record.get("tester")
    target = record.get("target")
    environment = record.get("environment")
    if not isinstance(tester, dict):
        errors.append("tester metadata is required")
    else:
        for key in ("name", "role"):
            if not _non_placeholder(tester.get(key)):
                errors.append(f"tester.{key} must be supplied by the UAT executor")
        if not isinstance(tester.get("is_developer"), bool):
            errors.append("tester.is_developer must explicitly be true or false")
    if not isinstance(target, dict):
        errors.append("target metadata is required")
    else:
        for key in ("name", "base_url", "network", "release_identity"):
            if not _non_placeholder(target.get(key)):
                errors.append(f"target.{key} must be supplied by the UAT executor")
        if _non_placeholder(target.get("base_url")) and not _is_http_target_url(
            target.get("base_url")
        ):
            errors.append(
                "target.base_url must use http with a host and no userinfo/query/fragment"
            )
    if not isinstance(environment, dict):
        errors.append("environment metadata is required")
    else:
        for key in ("name", "host_or_cluster"):
            if not _non_placeholder(environment.get(key)):
                errors.append(f"environment.{key} must be supplied by the UAT executor")
        if not _is_timestamp(environment.get("observed_at")):
            errors.append("environment.observed_at must be an ISO-8601 observation time")
        refs = environment.get("evidence_refs")
        if (
            not isinstance(refs, list)
            or not refs
            or not all(_non_placeholder(item) for item in refs)
        ):
            errors.append("environment.evidence_refs must contain evidence references")

    raw_steps = record.get("steps")
    if not isinstance(raw_steps, dict):
        raw_steps = {}
        errors.append("steps mapping is required")
    gate_results: list[dict[str, Any]] = []
    for gate_id in GATE_IDS:
        step = raw_steps.get(gate_id)
        if not isinstance(step, dict):
            gate_results.append(
                {
                    "gate": gate_id,
                    "status": UNPROVEN_STATUS,
                    "evidence": [],
                    "notes": "missing UAT answer",
                }
            )
            errors.append(f"{gate_id} has no answer")
            continue
        status = step.get("status")
        evidence = step.get("evidence")
        if status not in {OK_STATUS, ERROR_STATUS, UNPROVEN_STATUS}:
            errors.append(f"{gate_id}.status must be PASS, FAIL, or NOT_PROVEN")
            status = UNPROVEN_STATUS
        if (
            not isinstance(evidence, list)
            or not evidence
            or not all(_non_placeholder(item) for item in evidence)
        ):
            errors.append(f"{gate_id}.evidence must contain an evidence reference")
            evidence = [] if not isinstance(evidence, list) else evidence
        if not _is_timestamp(step.get("observed_at")):
            errors.append(f"{gate_id}.observed_at must be an ISO-8601 observation time")
        gate_results.append(
            {
                "gate": gate_id,
                "status": status,
                "evidence": evidence,
                "observed_at": step.get("observed_at"),
                "notes": step.get("notes", ""),
            }
        )

    evidence_refs = record.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        errors.append("evidence_refs must contain the perimeter/UAT evidence references")
    else:
        for index, item in enumerate(evidence_refs):
            if not isinstance(item, dict) or not _non_placeholder(item.get("reference")):
                errors.append(f"evidence_refs[{index}].reference is required")

    signoff = record.get("signoff")
    signoff_valid = isinstance(signoff, dict)
    if not signoff_valid:
        errors.append("signoff metadata is required; the runner never signs")
        signoff = {}
    else:
        for key in ("signed_by", "signature_ref", "statement"):
            if not _non_placeholder(signoff.get(key)):
                errors.append(f"signoff.{key} must be supplied by the actual signer")
        if not _is_timestamp(signoff.get("signed_at")):
            errors.append("signoff.signed_at must be an ISO-8601 signature time")
        if str(signoff.get("signature_ref", "")).strip().lower() in {
            "auto",
            "generated",
        }:
            errors.append("signoff.signature_ref cannot be automatically generated")

    failed_gates = [item["gate"] for item in gate_results if item["status"] == ERROR_STATUS]
    pending_gates = [item["gate"] for item in gate_results if item["status"] != OK_STATUS]
    if failed_gates:
        warnings.append("one or more target UAT gates were explicitly marked FAIL")
    if pending_gates:
        warnings.append("all sixteen gates must be explicitly PASS to close Gate P1-16")
    status = OK_STATUS if not errors and not pending_gates and signoff_valid else UNPROVEN_STATUS
    return {
        "schema_version": "1.0",
        "status": status,
        "errors": errors,
        "warnings": warnings,
        "gate_results": gate_results,
        "failed_gates": failed_gates,
        "pending_gates": pending_gates,
        "signoff_status": "ATTESTATION_PRESENT"
        if signoff_valid and not errors
        else "PENDING_SIGNOFF",
    }


def render_markdown(record: dict[str, Any], result: dict[str, Any]) -> str:
    tester = record.get("tester", {})
    target = record.get("target", {})
    environment = record.get("environment", {})
    signoff = record.get("signoff", {})
    environment_line = (
        f"- Environment: `{environment.get('name', '[missing]')}` · "
        f"`{environment.get('host_or_cluster', '[missing]')}`"
    )
    pending = "[PENDING SIGN-OFF]"
    signed_by = signoff.get("signed_by") or pending
    signed_at = signoff.get("signed_at") or pending
    signature_ref = signoff.get("signature_ref") or pending
    statement = signoff.get("statement") or pending
    lines = [
        "# Crash-Cap Phase 1 Target UAT Sign-off Record",
        "",
        f"- Result: **{result['status']}**",
        f"- Generated at: `{datetime.now(UTC).isoformat()}`",
        f"- Tester: `{tester.get('name', '[missing]')}` ({tester.get('role', '[missing]')})",
        f"- Target: `{target.get('name', '[missing]')}` · `{target.get('base_url', '[missing]')}`",
        environment_line,
        "",
        (
            "This record is valid only with collected evidence. The runner does not sign, "
            "infer, or replace target-network evidence."
        ),
        "",
        "## Gate results",
        "",
        "| Gate | Status | Evidence | Notes |",
        "| --- | --- | --- | --- |",
    ]
    for item in result["gate_results"]:
        evidence = "; ".join(str(value) for value in item.get("evidence", [])) or "[missing]"
        notes = str(item.get("notes", "")).replace("\n", " ")
        lines.append(f"| `{item['gate']}` | **{item['status']}** | {evidence} | {notes} |")
    lines.extend(
        [
            "",
            "## Evidence references",
            "",
        ]
    )
    for item in record.get("evidence_refs", []):
        if isinstance(item, dict):
            lines.append(
                f"- `{item.get('kind', 'evidence')}`: {item.get('reference', '[missing]')}"
            )
    lines.extend(
        [
            "",
            "## Attestation",
            "",
            f"- Signed by: `{signed_by}`",
            f"- Signed at: `{signed_at}`",
            f"- Signature reference: `{signature_ref}`",
            f"- Statement: {statement}",
            "",
            "## Checker diagnostics",
            "",
        ]
    )
    for error in result.get("errors", []):
        lines.append(f"- ERROR: {error}")
    for warning in result.get("warnings", []):
        lines.append(f"- WARNING: {warning}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--answers", type=Path, required=True, help="completed UAT answer JSON")
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument(
        "--write-template",
        type=Path,
        help="write a blank unsigned answer template and exit",
    )
    args = parser.parse_args(argv)
    if args.write_template:
        args.write_template.write_text(
            json.dumps(checklist_template(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return 0
    try:
        record = json.loads(args.answers.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        record = {}
        result = {
            "schema_version": "1.0",
            "status": UNPROVEN_STATUS,
            "errors": [f"cannot read answer JSON: {exc}"],
            "warnings": [],
            "gate_results": [],
            "failed_gates": [],
            "pending_gates": list(GATE_IDS),
            "signoff_status": "PENDING_SIGNOFF",
        }
    else:
        result = validate_record(record)
    output = {"record": record, "validation": result}
    args.output_json.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.output_markdown.write_text(render_markdown(record, result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == OK_STATUS else 1


if __name__ == "__main__":
    raise SystemExit(main())
