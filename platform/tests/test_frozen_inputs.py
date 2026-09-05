from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
from crashcap_api.frozen_inputs import (
    FrozenInputError,
    canonical_bytes,
    digest,
    frozen_run_key,
    resolution_fingerprint,
    verify_frozen_run,
)

DRAFTS = Path(__file__).resolve().parents[2] / "contracts/drafts/qa-symbol-import"
DUMP_BYTES = b"controlled dump identity"
DUMP_SHA = hashlib.sha256(DUMP_BYTES).hexdigest()
IDENTITY = {
    "code_id": "6a87124ac8000",
    "debug_id": "5295c1f4535d4f8aa0b1989805198bb815",
    "architecture": "x86_64",
}


def inputs():
    inspected = {
        "schema_version": "0.1",
        "dump": {
            "kind": "user_minidump",
            "size": len(DUMP_BYTES),
            "timestamp": "2026-09-03T00:00:00Z",
        },
        "process": {"architecture": "x86_64"},
        "modules": [{"code_id": IDENTITY["code_id"].upper(), "debug_id": IDENTITY["debug_id"]}],
    }
    manifest = {
        "schema_version": "resolution-manifest-v1",
        "dump_sha256": DUMP_SHA,
        "inspector_version": "inspect-v1",
        "inspect_sha256": digest(inspected),
        "selection_version": "pair-selection-v1",
        "catalog_revision": 1,
        "modules": [
            {
                "module_index": 0,
                "identity": IDENTITY,
                "state": "unique",
                "candidates_complete": True,
                "candidate_pair_ids": ["a" * 64],
                "unavailable_pair_ids": [],
                "selected_pair_id": "a" * 64,
                "reason": "unique",
                "candidate_evidence": {"object_key": "frozen/candidates", "sha256": "b" * 64},
                "review_refs": [],
            }
        ],
    }
    policies = {
        "role_policy": {
            "schema_version": "workspace-role-policy-v1",
            "modules": [{"module_index": 0, "identity": IDENTITY, "role": "owned", "in_app": True}],
        },
        "source_policy": {
            "schema_version": "frozen-source-policy-v2",
            "pair_source_protocol": "pair-http-v3",
            "public_sources": [],
        },
    }
    context = {
        "schema_version": "analysis-context-v3",
        "workspace_id": "wsp_local",
        **{key + "_sha256": digest(value) for key, value in policies.items()},
        "capture_profile": None,
        "core_image_digest": "sha256:" + "e" * 64,
        "symbolicator_image_digest": "sha256:" + "f" * 64,
        "symbolicator_version": "26.7.2",
        "normalization_version": "norm-v1.0",
        "grouping_version": "group-v1.1",
        "inspector_version": "inspect-v1",
        "canonical_version": "2.0",
        "selection_version": "pair-selection-v1",
    }
    run = {
        "schema_version": "analysis-run-v3",
        "run_id": "run_00000000000000000000000001",
        "occurrence_id": "occ_one",
        "demand_id": "dem_one",
        "demand_generation": 1,
        "retry_attempt": 0,
        "reason": "initial",
        "dump": {"sha256": DUMP_SHA, "size": len(DUMP_BYTES), "object_key": "dumps/raw"},
        "result_facts": {
            "dump": {
                "blob_id": "dmp_one",
                "sha256": DUMP_SHA,
                "size": len(DUMP_BYTES),
                "kind": "user_minidump",
                "capture_profile": None,
                "dump_timestamp": "2026-09-03T00:00:00Z",
                "reported_at": None,
                "uploaded_at": "2026-09-03T00:00:00Z",
                "occurred_at": "2026-09-03T00:00:00Z",
                "time_source": "dump",
            }
        },
        "policy_snapshots": policies,
        "inspect": {"object_key": "frozen/inspect", "sha256": digest(inspected)},
        "resolution_manifest": {"object_key": "frozen/manifest", "sha256": digest(manifest)},
        "resolution_evidence_fingerprint": resolution_fingerprint(manifest),
        "context": context,
        "context_sha256": digest(context),
        "idempotency_key": "0" * 64,
    }
    run["idempotency_key"] = frozen_run_key(run)
    return (run, manifest, inspected)


def verify(run, manifest, inspected):
    return verify_frozen_run(
        run,
        manifest_bytes=canonical_bytes(manifest),
        inspect_bytes=canonical_bytes(inspected),
        observed_dump_sha256=DUMP_SHA,
        observed_dump_size=len(DUMP_BYTES),
        schema_root=DRAFTS,
    )


def refresh(run, manifest):
    for key, value in run["policy_snapshots"].items():
        run["context"][key + "_sha256"] = digest(value)
    run["context_sha256"] = digest(run["context"])
    run["resolution_manifest"]["sha256"] = digest(manifest)
    run["resolution_evidence_fingerprint"] = resolution_fingerprint(manifest)
    run["idempotency_key"] = frozen_run_key(run)


def test_complete_run_binds_old_manifest_roles_source_and_result_facts():
    run, manifest, inspected = inputs()
    assert verify(run, manifest, inspected) == (manifest, inspected)


@pytest.mark.parametrize(
    "defect,expected",
    [
        ("context", "context digest"),
        ("dump", "Dump digest"),
        ("result_time", "inspect Dump dump_timestamp"),
        ("role_digest", "role_policy digest"),
        ("module_omitted", "cover every captured module"),
        ("module_identity", "captured identity"),
        ("selected_pair", "selected pair differs"),
        ("inspect_ref", "manifest inspect digest"),
        ("key", "Run key"),
    ],
)
def test_inconsistent_frozen_inputs_are_rejected(defect, expected):
    run, manifest, inspected = inputs()
    if defect == "context":
        run["context"]["workspace_id"] = "wsp_other"
    elif defect == "dump":
        run["dump"]["sha256"] = "0" * 64
    elif defect == "result_time":
        run["result_facts"]["dump"]["dump_timestamp"] = "2026-09-04T00:00:00Z"
    elif defect == "role_digest":
        run["policy_snapshots"]["role_policy"]["modules"][0]["role"] = "dependency"
    elif defect == "module_omitted":
        manifest["modules"] = []
        refresh(run, manifest)
    elif defect == "module_identity":
        manifest["modules"][0]["identity"] = {**IDENTITY, "code_id": "987654321"}
        refresh(run, manifest)
    elif defect == "selected_pair":
        manifest["modules"][0]["selected_pair_id"] = "9" * 64
        refresh(run, manifest)
    elif defect == "inspect_ref":
        manifest["inspect_sha256"] = "7" * 64
        refresh(run, manifest)
    elif defect == "key":
        run["idempotency_key"] = "7" * 64
    with pytest.raises(FrozenInputError, match=expected):
        verify(run, manifest, inspected)


def test_run_creation_and_physical_locations_do_not_change_semantic_context():
    run, manifest, inspected = inputs()
    before = copy.deepcopy(run)
    run["run_id"] = "run_00000000000000000000000002"
    run["dump"]["object_key"] = "new/retained"
    assert verify(run, manifest, inspected)
    assert run["context_sha256"] == before["context_sha256"]
    run["demand_generation"] += 1
    refresh(run, manifest)
    assert verify(run, manifest, inspected)
    assert run["idempotency_key"] != before["idempotency_key"]


def test_exact_stored_bytes_and_duplicate_json_keys_are_checked():
    run, manifest, inspected = inputs()
    raw = canonical_bytes(manifest)
    with pytest.raises(FrozenInputError, match="object digest"):
        verify_frozen_run(
            run,
            manifest_bytes=raw + b"\n",
            inspect_bytes=canonical_bytes(inspected),
            observed_dump_sha256=DUMP_SHA,
            observed_dump_size=len(DUMP_BYTES),
            schema_root=DRAFTS,
        )
    duplicate = b'{"schema_version":"wrong",' + raw[1:]
    run["resolution_manifest"]["sha256"] = hashlib.sha256(duplicate).hexdigest()
    with pytest.raises(FrozenInputError, match="duplicate JSON keys"):
        verify_frozen_run(
            run,
            manifest_bytes=duplicate,
            inspect_bytes=canonical_bytes(inspected),
            observed_dump_sha256=DUMP_SHA,
            observed_dump_size=len(DUMP_BYTES),
            schema_root=DRAFTS,
        )


@pytest.mark.parametrize("invalid", [1.5, 1.0, 2**53, {"中文键": 1}])
def test_hash_encoding_is_strict(invalid):
    with pytest.raises(FrozenInputError):
        canonical_bytes(invalid)


def test_unicode_values_and_safe_integers_have_fixed_encoding():
    assert (
        canonical_bytes({"z": "中文", "a": [None, True, -(2**53 - 1)]})
        == '{"a":[null,true,-9007199254740991],"z":"中文"}'.encode()
    )


def public_source():
    return {
        "id": "public-test",
        "type": "http",
        "url": "https://symbols.example.test/symbols/",
        "layout": {"type": "symstore"},
        "filters": {"filetypes": ["pdb", "pe"]},
        "is_public": True,
    }


def test_public_source_policy_changes_context_without_changing_pair_fingerprint():
    run, manifest, inspected = inputs()
    before = copy.deepcopy(run)
    run["policy_snapshots"]["source_policy"]["public_sources"] = [public_source()]
    refresh(run, manifest)
    assert verify(run, manifest, inspected)
    assert run["context_sha256"] != before["context_sha256"]
    assert run["idempotency_key"] != before["idempotency_key"]
    assert run["resolution_evidence_fingerprint"] == before["resolution_evidence_fingerprint"]


@pytest.mark.parametrize(
    "defect",
    [
        "credentials",
        "query",
        "fragment",
        "reserved_id",
        "duplicate_id",
        "filter_order",
        "source_protocol",
        "role_mismatch",
        "availability_overlap",
        "preauthorized_correction",
        "invalid_time",
        "time_source",
    ],
)
def test_frozen_policy_and_cross_field_defects_are_rejected_even_after_rehash(defect):
    run, manifest, inspected = inputs()
    policy = run["policy_snapshots"]["source_policy"]
    source = public_source()
    policy["public_sources"] = [source]
    if defect == "credentials":
        source["url"] = "https://user:secret@symbols.example.test/"
    elif defect == "query":
        source["url"] += "?token=unsafe"
    elif defect == "fragment":
        source["url"] += "#different"
    elif defect == "reserved_id":
        source["id"] = "crash-cap:pair:unowned"
    elif defect == "duplicate_id":
        policy["public_sources"].append(copy.deepcopy(source))
    elif defect == "filter_order":
        source["filters"]["filetypes"] = ["pe", "pdb"]
    elif defect == "source_protocol":
        policy["pair_source_protocol"] = "unfrozen-v9"
    elif defect == "role_mismatch":
        run["policy_snapshots"]["role_policy"]["modules"][0]["in_app"] = False
    elif defect == "availability_overlap":
        manifest["modules"][0]["unavailable_pair_ids"] = ["a" * 64]
    elif defect == "preauthorized_correction":
        run["reason"] = "evidence_correction"
        run["correction_ref"] = {"object_key": "future.json", "sha256": "a" * 64}
    elif defect == "invalid_time":
        run["result_facts"]["dump"]["occurred_at"] = "not-a-date"
        run["result_facts"]["dump"]["uploaded_at"] = "not-a-date"
        run["result_facts"]["dump"]["time_source"] = "uploaded"
    elif defect == "time_source":
        run["result_facts"]["dump"]["occurred_at"] = "2026-09-03T01:00:00Z"
    refresh(run, manifest)
    with pytest.raises(FrozenInputError):
        verify(run, manifest, inspected)
