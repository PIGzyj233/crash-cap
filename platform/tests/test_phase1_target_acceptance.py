"""Offline checks for target perimeter and internal UAT evidence tooling."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str, relative: str) -> ModuleType:
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


perimeter = _load_script(
    "phase1_target_perimeter_probe", "scripts/phase1/target_perimeter_probe.py"
)
uat = _load_script("phase1_uat_runner", "scripts/phase1/uat_runner.py")


def test_endpoint_validation_is_strictly_http_only() -> None:
    assert (
        perimeter.endpoint_url("http://crashcap.intranet.example/base", "/healthz")
        == "http://crashcap.intranet.example/base/healthz"
    )

    for invalid in (
        "https://crashcap.intranet.example",
        "crashcap.intranet.example",
        "http:///missing-host",
        "http://user:secret@crashcap.intranet.example",
        "http://crashcap.intranet.example?token=secret",
        "http://crashcap.intranet.example#fragment",
    ):
        with pytest.raises(ValueError):
            perimeter.endpoint_url(invalid, "/healthz")


def test_run_probe_rejects_https_endpoints() -> None:
    result = perimeter.run_probe(
        argparse.Namespace(
            api_url="https://crashcap.intranet.example",
            frontend_url="https://crashcap.intranet.example/web",
            object_store_url="https://rustfs.intranet.example",
            allowed_cidr=["127.0.0.0/8"],
            timeout=0.1,
            occurrence_id=None,
            outside_evidence=None,
        )
    )
    statuses = {item["name"]: item["status"] for item in result["checks"]}
    assert statuses["api.http"] == "FAIL"
    assert statuses["frontend.http"] == "FAIL"
    assert not any(name.endswith(".https") for name in statuses)


def test_openapi_inventory_rejects_delete_and_identity_routes() -> None:
    clean = perimeter.inspect_openapi({"paths": {"/healthz": {"get": {}}}})
    assert {item.name: item.status for item in clean} == {
        "api.no_delete": "PASS",
        "api.no_identity_routes": "PASS",
        "api.route_inventory": "PASS",
    }

    unsafe = perimeter.inspect_openapi(
        {"paths": {"/login": {"post": {}}, "/users": {"delete": {}}}}
    )
    assert {item.name: item.status for item in unsafe} == {
        "api.no_delete": "FAIL",
        "api.no_identity_routes": "FAIL",
        "api.route_inventory": "PASS",
    }


def test_outside_evidence_requires_probe_metadata_and_unreachable_results(
    tmp_path: Path,
) -> None:
    api_url = "http://crashcap.intranet.example"
    frontend_url = "http://crashcap.intranet.example/web"
    object_store_url = "http://rustfs.intranet.example"
    missing = tmp_path / "missing.json"
    missing.write_text(json.dumps({"probes": []}), encoding="utf-8")
    missing_result = perimeter.load_outside_evidence(
        missing, api_url, frontend_url, object_store_url
    )
    assert missing_result.status == "NOT_PROVEN"

    evidence: dict[str, Any] = {
        "tester": {"name": "perimeter-operator", "is_developer": False},
        "target": {
            "api_url": api_url,
            "frontend_url": frontend_url,
            "object_store_url": object_store_url,
        },
        "environment": {"name": "target-net", "observed_at": "2026-08-21T12:00:00Z"},
        "probes": [
            {"name": "api", "source_network": "outside", "reachable": False},
            {"name": "frontend", "source_network": "outside", "reachable": False},
            {
                "name": "object_store",
                "source_network": "outside",
                "reachable": False,
            },
        ],
        "attestation": {"signed_by": "perimeter-operator", "signature_ref": "ticket-123"},
    }
    valid = tmp_path / "outside.json"
    valid.write_text(json.dumps(evidence), encoding="utf-8")
    valid_result = perimeter.load_outside_evidence(valid, api_url, frontend_url, object_store_url)
    assert valid_result.status == "PASS"

    developer = dict(evidence)
    developer["tester"] = {"name": "developer-operator", "is_developer": True}
    developer["attestation"] = {
        "signed_by": "developer-operator",
        "signature_ref": "ticket-124",
    }
    developer_path = tmp_path / "developer-outside.json"
    developer_path.write_text(json.dumps(developer), encoding="utf-8")
    assert (
        perimeter.load_outside_evidence(
            developer_path, api_url, frontend_url, object_store_url
        ).status
        == "PASS"
    )

    untyped = dict(evidence)
    untyped["tester"] = {"name": "perimeter-operator", "is_developer": None}
    untyped_path = tmp_path / "untyped.json"
    untyped_path.write_text(json.dumps(untyped), encoding="utf-8")
    assert (
        perimeter.load_outside_evidence(
            untyped_path, api_url, frontend_url, object_store_url
        ).status
        == "NOT_PROVEN"
    )

    reachable = dict(evidence)
    reachable["probes"] = [{"name": "api", "source_network": "outside", "reachable": True}]
    reachable_path = tmp_path / "reachable.json"
    reachable_path.write_text(json.dumps(reachable), encoding="utf-8")
    assert (
        perimeter.load_outside_evidence(
            reachable_path, api_url, frontend_url, object_store_url
        ).status
        == "FAIL"
    )

    auto_signed = dict(evidence)
    auto_signed["attestation"] = {
        "signed_by": "perimeter-operator",
        "signature_ref": "auto",
    }
    auto_path = tmp_path / "auto.json"
    auto_path.write_text(json.dumps(auto_signed), encoding="utf-8")
    assert (
        perimeter.load_outside_evidence(auto_path, api_url, frontend_url, object_store_url).status
        == "NOT_PROVEN"
    )


def _complete_uat_record() -> dict[str, Any]:
    record = uat.checklist_template()
    record["tester"] = {
        "name": "phase1-developer",
        "role": "developer",
        "is_developer": True,
    }
    record["target"] = {
        "name": "crashcap-target",
        "base_url": "http://crashcap.intranet.example",
        "network": "trusted-intranet",
        "release_identity": "compose-sha-abc",
    }
    record["environment"] = {
        "name": "target-net",
        "observed_at": "2026-08-21T12:00:00Z",
        "host_or_cluster": "qa-vm-01",
        "evidence_refs": ["evidence://target-session"],
    }
    for gate_id in uat.GATE_IDS:
        record["steps"][gate_id] = {
            "status": "PASS",
            "evidence": [f"evidence://{gate_id.lower()}"],
            "observed_at": "2026-08-21T12:00:00Z",
            "notes": "observed by internal UAT executor",
        }
    record["evidence_refs"] = [
        {"kind": "perimeter", "reference": "evidence://perimeter-probe"},
        {"kind": "session", "reference": "evidence://target-session"},
    ]
    record["signoff"] = {
        "signed_by": "phase1-developer",
        "signed_at": "2026-08-21T12:30:00Z",
        "signature_ref": "ticket-uat-123",
        "statement": "I observed the target workflow and recorded the evidence.",
    }
    return record


def test_uat_runner_never_self_signs_blank_or_untyped_records() -> None:
    blank = uat.validate_record(uat.checklist_template())
    assert blank["status"] == "NOT_PROVEN"
    assert len(blank["pending_gates"]) == 16
    assert blank["signoff_status"] == "PENDING_SIGNOFF"

    complete = _complete_uat_record()
    result = uat.validate_record(complete)
    assert result["status"] == "PASS"
    assert result["pending_gates"] == []
    assert result["signoff_status"] == "ATTESTATION_PRESENT"

    operator = _complete_uat_record()
    operator["tester"] = {
        "name": "phase1-ops",
        "role": "operations",
        "is_developer": False,
    }
    operator_result = uat.validate_record(operator)
    assert operator_result["status"] == "PASS"

    untyped = _complete_uat_record()
    untyped["tester"]["is_developer"] = None
    untyped_result = uat.validate_record(untyped)
    assert untyped_result["status"] == "NOT_PROVEN"
    assert any("true or false" in error for error in untyped_result["errors"])

    auto_signed = _complete_uat_record()
    auto_signed["signoff"]["signature_ref"] = "auto"
    auto_result = uat.validate_record(auto_signed)
    assert auto_result["status"] == "NOT_PROVEN"
    assert any("automatically generated" in error for error in auto_result["errors"])

    self_signed = _complete_uat_record()
    self_signed["signoff"]["signed_by"] = self_signed["tester"]["name"]
    self_signed["signoff"]["signature_ref"] = "uat-record-2026-08-21"
    self_result = uat.validate_record(self_signed)
    assert self_result["status"] == "PASS"

    https_target = _complete_uat_record()
    https_target["target"]["base_url"] = "https://crashcap.intranet.example"
    https_result = uat.validate_record(https_target)
    assert https_result["status"] == "NOT_PROVEN"
    assert any("target.base_url must use http" in error for error in https_result["errors"])


def test_uat_markdown_keeps_pending_signature_visible() -> None:
    record = uat.checklist_template()
    result = uat.validate_record(record)
    markdown = uat.render_markdown(record, result)
    assert "NOT_PROVEN" in markdown
    assert "PENDING SIGN-OFF" in markdown
    assert "GATE-P1-16" in markdown
