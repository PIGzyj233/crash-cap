"""Generate reviewable S0 schemas; these are NOT published production contracts."""

from __future__ import annotations

import copy
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "contracts/drafts/qa-symbol-import"
HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
TEXT = {"type": "string", "minLength": 1}
UINT = {"type": "integer", "minimum": 0, "maximum": 9007199254740991}
NULL_TEXT = {"type": ["string", "null"]}


def enum(*values):
    return {"enum": list(values)}


def array(items, **kwargs):
    return {"type": "array", "items": items, **kwargs}


def obj(properties, optional=()):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [k for k in properties if k not in optional],
        "properties": properties,
    }


def nullable(schema):
    return {"anyOf": [schema, {"type": "null"}]}


def ref(name):
    return {"$ref": name + ".schema.json"}


def write(name, schema):
    schema = copy.deepcopy(schema)
    schema.update(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://crash-cap.local/contracts/drafts/qa-symbol-import/{name}.schema.json",
            "title": f"DRAFT QAI S0 {name}",
            "$comment": (
                "Unpublished. S1 real qualification required before freeze; "
                "no production writer may emit this draft."
            ),
        }
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.schema.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


def main():
    identity = obj(
        {
            "code_id": nullable({"type": "string", "pattern": "^[0-9a-f]{9,24}$"}),
            "debug_id": nullable({"type": "string", "pattern": "^[0-9a-f]{33,40}$"}),
            "architecture": enum("x86_64", "x86", "arm64", "unknown"),
        }
    )
    evidence_ref = obj({"object_key": TEXT, "sha256": HASH})
    selection = obj(
        {
            "module_index": UINT,
            "identity": identity,
            "state": enum("none", "unique", "conflict", "unavailable", "indeterminate"),
            "candidates_complete": {"type": "boolean"},
            "candidate_pair_ids": array(HASH, uniqueItems=True),
            "unavailable_pair_ids": array(HASH, uniqueItems=True),
            "selected_pair_id": nullable(HASH),
            "reason": enum(
                "missing",
                "unique",
                "identity_conflict",
                "withdrawn",
                "location_unavailable",
                "incomplete_identity",
                "enumeration_failed",
                "validation_incomplete",
            ),
            "candidate_evidence": evidence_ref,
            "review_refs": array(TEXT, uniqueItems=True),
        }
    )
    selection["allOf"] = [
        {
            "if": {"properties": {"state": {"const": "unique"}}},
            "then": {
                "properties": {
                    "candidates_complete": {"const": True},
                    "selected_pair_id": HASH,
                    "candidate_pair_ids": {"minItems": 1, "maxItems": 1},
                }
            },
            "else": {"properties": {"selected_pair_id": {"type": "null"}}},
        },
        {
            "if": {"properties": {"state": {"const": "conflict"}}},
            "then": {
                "properties": {
                    "candidates_complete": {"const": True},
                    "candidate_pair_ids": {"minItems": 2},
                }
            },
        },
        {
            "if": {"properties": {"state": {"const": "indeterminate"}}},
            "then": {"properties": {"candidates_complete": {"const": False}}},
        },
        {
            "if": {"properties": {"state": {"enum": ["none", "unavailable"]}}},
            "then": {
                "properties": {
                    "candidates_complete": {"const": True},
                    "candidate_pair_ids": {"maxItems": 0},
                }
            },
        },
    ]
    write(
        "resolution-manifest-v1",
        obj(
            {
                "schema_version": {"const": "resolution-manifest-v1"},
                "dump_sha256": HASH,
                "inspector_version": TEXT,
                "inspect_sha256": HASH,
                "selection_version": {"const": "pair-selection-v1"},
                "catalog_revision": UINT,
                "modules": array(selection),
            }
        ),
    )
    source = obj(
        {
            "source_id": TEXT,
            "stage": enum("download_pe", "download_pdb", "unwind", "symbolicate"),
            "outcome": enum("found", "missing", "failed", "blocked", "unknown"),
            "failure_class": enum("none", "transient", "permanent", "unknown"),
            "reason": TEXT,
            "diagnostic_ref": nullable(evidence_ref),
        }
    )
    canonical = json.loads((ROOT / "contracts/analysis-result-v1.schema.json").read_text())
    canonical["description"] = (
        "Draft 1.1: Core-owned frozen symbol evidence. Historical 1.0 remains unchanged."
    )
    canonical["properties"]["schema_version"] = {"const": "1.1"}
    canonical["required"].append("symbol_resolution")
    canonical["properties"]["symbol_resolution"] = obj(
        {
            "selection_version": {"const": "pair-selection-v1"},
            "resolution_evidence_fingerprint": HASH,
            "manifest": evidence_ref,
            "inspect_sha256": HASH,
            "context_sha256": HASH,
        }
    )
    frame = canonical["$defs"]["frame"]
    frame["required"] += ["module_index", "unwind_method", "physical_frame_index"]
    frame["properties"].update(
        {
            "module_index": nullable(UINT),
            "physical_frame_index": UINT,
            "unwind_method": enum(
                "context",
                "call_frame_info",
                "cfi_scan",
                "frame_pointer",
                "scan",
                "prewalked",
                "unknown",
            ),
        }
    )
    module = canonical["$defs"]["module"]
    module["required"] += ["module_index", "selection", "source_outcomes"]
    module["properties"].update(
        {"module_index": UINT, "selection": selection, "source_outcomes": array(source)}
    )
    module["properties"]["status"]["enum"] += [
        "symbol_conflict",
        "symbol_unavailable",
        "symbol_indeterminate",
    ]
    canonical["$defs"]["qualityWarning"]["properties"]["code"]["enum"] += [
        "symbol_conflict",
        "symbol_unavailable",
        "symbol_indeterminate",
    ]
    write("analysis-result-v1.1", canonical)
    # Reader preparation precedes writer activation. This separate candidate
    # schema is packaged with the API; the frozen v1.0 file is never edited.
    reader_candidate = copy.deepcopy(canonical)
    reader_candidate.update(
        {
            "$id": "https://crash-cap.local/contracts/analysis-result-v1.1.schema.json",
            "title": "Crash-Cap Canonical Analysis Result v1.1 release candidate",
            "$comment": (
                "QAI reader preparation. Writer activation requires the remaining QAI gates."
            ),
        }
    )
    (ROOT / "contracts/analysis-result-v1.1.schema.json").write_text(
        json.dumps(reader_candidate, indent=2) + "\n", encoding="utf-8"
    )
    context = obj(
        {
            "schema_version": {"const": "analysis-context-v2"},
            "workspace_id": TEXT,
            "reported_build_id": NULL_TEXT,
            "build_snapshot_sha256": HASH,
            "role_policy_sha256": HASH,
            "source_policy_sha256": HASH,
            "capture_profile": enum(None, "light-crash", "rich-crash", "hang", "full-memory"),
            "core_image_digest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
            "symbolicator_image_digest": {
                "type": "string",
                "pattern": "^sha256:[0-9a-f]{64}$",
            },
            "symbolicator_version": TEXT,
            "source_bundle_policy_version": {"const": "source-bundle-v1.0"},
            "normalization_version": TEXT,
            "grouping_version": TEXT,
            "inspector_version": TEXT,
            "canonical_version": {"const": "1.1"},
            "selection_version": {"const": "pair-selection-v1"},
        }
    )
    write("analysis-context-v2", context)
    result_dump = copy.deepcopy(canonical["properties"]["dump"])
    result_dump["required"] = list(result_dump["properties"])
    result_dump["properties"]["size"] = {**UINT, "minimum": 1}
    # The semantic context carries capture intent; the result facts bind all
    # timestamps and platform identities without making every new Run a new
    # semantic context. Keep local references valid in this independent schema.
    for key in ("dump_timestamp", "reported_at", "uploaded_at", "occurred_at"):
        if "$ref" in result_dump["properties"][key]:
            result_dump["properties"][key] = copy.deepcopy(canonical["$defs"]["nullableTimestamp"])
    source_descriptor = json.loads((ROOT / "contracts/source-bundle-v1.schema.json").read_text())
    for key in ("$id", "$schema", "title", "description"):
        source_descriptor.pop(key, None)
    public_source = obj(
        {
            "id": TEXT,
            "type": {"const": "http"},
            "url": {"type": "string", "pattern": "^https?://", "format": "uri"},
            "layout": obj(
                {"type": enum("symstore", "unified"), "casing": {"const": "lowercase"}},
                optional=("casing",),
            ),
            "filters": obj(
                {
                    "filetypes": array(
                        enum("pe", "pdb", "portablepdb"), minItems=1, uniqueItems=True
                    ),
                    "path_patterns": array(TEXT, uniqueItems=True),
                },
                optional=("path_patterns",),
            ),
            "is_public": {"const": True},
        }
    )
    policies = obj(
        {
            "build_snapshot": obj(
                {
                    "schema_version": {"const": "frozen-builds-v1"},
                    "builds": array(
                        obj(
                            {
                                "build_id": TEXT,
                                "workspace_id": TEXT,
                                "manifest_sha256": HASH,
                                "verified_modules": array(
                                    obj(
                                        {
                                            "module_id": TEXT,
                                            "manifest_module_index": UINT,
                                            "identity": identity,
                                            "role": enum("entrypoint", "owned", "dependency"),
                                            "verified_pair_ids": array(HASH, uniqueItems=True),
                                            "artifact_ids": array(TEXT, uniqueItems=True),
                                        }
                                    )
                                ),
                                "manifest": {
                                    "oneOf": [
                                        {
                                            "$ref": f"https://crash-cap.local/contracts/build-manifest-{version}.schema.json"
                                        }
                                        for version in ("v0", "v1", "v2")
                                    ]
                                },
                            }
                        )
                    ),
                }
            ),
            "role_policy": obj(
                {
                    "schema_version": {"const": "workspace-role-policy-v1"},
                    "modules": array(
                        obj(
                            {
                                "module_index": UINT,
                                "identity": identity,
                                "role": enum(
                                    "entrypoint", "owned", "dependency", "system", "unknown"
                                ),
                                "in_app": {"type": "boolean"},
                            }
                        )
                    ),
                }
            ),
            "source_policy": obj(
                {
                    "schema_version": {"const": "frozen-source-policy-v1"},
                    "pair_source_protocol": {"const": "pair-http-v2"},
                    "public_sources": array(public_source),
                    "bundles": array(
                        obj(
                            {
                                "build_id": TEXT,
                                "artifact_id": TEXT,
                                "sha256": HASH,
                                "size": {**UINT, "minimum": 1},
                                "descriptor": source_descriptor,
                            }
                        )
                    ),
                }
            ),
        }
    )
    write(
        "analysis-run-v2",
        obj(
            {
                "schema_version": {"const": "analysis-run-v2"},
                "run_id": TEXT,
                "occurrence_id": TEXT,
                "demand_id": TEXT,
                "demand_generation": {**UINT, "minimum": 1},
                "retry_attempt": UINT,
                "reason": enum(
                    "initial",
                    "symbol_refresh",
                    "role_change",
                    "engine_upgrade",
                    "evidence_correction",
                    "manual",
                ),
                "dump": obj({"sha256": HASH, "object_key": TEXT, "size": {**UINT, "minimum": 1}}),
                "result_facts": obj({"dump": result_dump}),
                "policy_snapshots": policies,
                "source_bundle_locations": array(
                    obj({"artifact_id": TEXT, "content": evidence_ref})
                ),
                "inspect": evidence_ref,
                "resolution_manifest": evidence_ref,
                "resolution_evidence_fingerprint": HASH,
                "context": ref("analysis-context-v2"),
                "context_sha256": HASH,
                "idempotency_key": HASH,
            }
        ),
    )
    tasks = []
    for task, key, queue in [
        ("verify_symbol_import_pair", "item_id", "ingest"),
        ("plan_analysis_demand", "demand_id", "verify"),
        ("analyze_frozen_run", "run_id", "dump-small"),
        ("dispatch_catalog_change", "change_id", "ingest"),
    ]:
        tasks.append(
            obj(
                {
                    "schema_version": {"const": "1.2"},
                    "task_type": {"const": task},
                    key: TEXT,
                    "attempt_id": TEXT,
                    "queue": enum("dump-small", "dump-large")
                    if task == "analyze_frozen_run"
                    else {"const": queue},
                    "request_id": TEXT,
                },
                optional=("request_id",),
            )
        )
    tasks.append(obj({
        "schema_version": {"const": "1.2"},
        "task_type": {"const": "dispatch_workspace_role"},
        "workspace_id": TEXT,
        "role_version": {"type": "integer", "minimum": 1},
        "attempt_id": TEXT,
        "queue": {"const": "ingest"},
        "request_id": TEXT,
    }, optional=("request_id",)))
    write("task-message-v1.2", {"oneOf": tasks})
    file_claim = obj({"name": TEXT, "raw_sha256": HASH, "raw_size": {**UINT, "minimum": 1}})
    write(
        "symbol-import-request-v1",
        obj(
            {
                "idempotency_key": TEXT,
                "source_label": TEXT,
                "pairs": array(
                    obj({"client_pair_id": TEXT, "pe": file_claim, "pdb": file_claim}),
                    minItems=1,
                    maxItems=200,
                ),
            }
        ),
    )
    write(
        "symbol-import-result-v1",
        obj(
            {
                "import_id": TEXT,
                "items": array(
                    obj(
                        {
                            "item_id": TEXT,
                            "client_pair_id": TEXT,
                            "state": enum(
                                "staging",
                                "queued",
                                "verifying",
                                "available",
                                "rejected",
                                "retry_exhausted",
                            ),
                            "pair_id": nullable(HASH),
                            "error_code": NULL_TEXT,
                            "pe_upload_id": TEXT,
                            "pdb_upload_id": TEXT,
                        }
                    )
                ),
            }
        ),
    )
    write(
        "analysis-demand-v1",
        obj(
            {
                "demand_id": TEXT,
                "occurrence_id": TEXT,
                "state": enum(
                    "preparing",
                    "coalescing",
                    "queued",
                    "running",
                    "updated",
                    "retained",
                    "needs_review",
                    "retry_wait",
                    "retry_exhausted",
                    "cannot_recompute",
                    "paused",
                ),
                "generation": UINT,
                "retry_attempt": UINT,
                "run_id": NULL_TEXT,
                "reason": NULL_TEXT,
                "not_before": nullable({"type": "string", "format": "date-time"}),
            }
        ),
    )
    frame = obj(
        {
            "thread_id": UINT,
            "module_index": UINT,
            "rva": UINT,
            "unwind_method": enum(
                None,
                "context",
                "call_frame_info",
                "frame_pointer",
                "cfi_scan",
                "scan",
                "prewalked",
                "unknown",
            ),
            "in_app": {"type": "boolean"},
            "function": NULL_TEXT,
            "file": NULL_TEXT,
            "line": nullable(UINT),
        }
    )
    write(
        "comparison-evidence-v1",
        obj(
            {
                "schema_version": {"const": "comparison-evidence-v1"},
                "run_id": TEXT,
                "occurrence_id": TEXT,
                "dump_sha256": HASH,
                "inspect_sha256": HASH,
                "context_sha256": HASH,
                "canonical_sha256": HASH,
                "status": enum("PENDING", "RUNNING", "COMPLETE", "PARTIAL", "FAILED"),
                "reason": enum(
                    "initial",
                    "manual",
                    "symbol_refresh",
                    "engine_upgrade",
                    "role_change",
                    "evidence_correction",
                ),
                "provenance": enum("native_1.1", "verified_raw_mapping", "insufficient"),
                "usable": {"type": "boolean"},
                "pair_evidence_complete": {"type": "boolean"},
                "fault": obj(
                    {
                        "kind": TEXT,
                        "exception_code": NULL_TEXT,
                        "access_type": enum(None, "read", "write", "execute", "readwrite"),
                        "thread_id": nullable(UINT),
                        "module_index": nullable(UINT),
                        "rva": nullable(UINT),
                        "fault_address": nullable({"type": "string", "pattern": "^0x[0-9a-f]+$"}),
                    }
                ),
                "frames": array(frame),
                "modules": array(
                    obj(
                        {
                            "index": UINT,
                            "identity": {
                                "type": "array",
                                "prefixItems": list(identity["properties"].values()),
                                "items": False,
                                "minItems": 3,
                                "maxItems": 3,
                            },
                            "role": enum("entrypoint", "owned", "dependency", "system", "unknown"),
                            "in_app": {"type": "boolean"},
                            "selection_state": enum(
                                "none", "unique", "conflict", "unavailable", "indeterminate"
                            ),
                            "pair_id": nullable(HASH),
                            "symbol_status": TEXT,
                            "sources": array(
                                obj(
                                    {
                                        "source_id": TEXT,
                                        "stage": enum(
                                            "unwind", "download_pe", "download_pdb", "symbolicate"
                                        ),
                                        "outcome": enum("found", "missing", "failed", "unknown"),
                                        "failure_class": enum(
                                            "none", "transient", "permanent", "unknown"
                                        ),
                                        "reason": TEXT,
                                        "diagnostic_sha256": nullable(HASH),
                                    }
                                )
                            ),
                        }
                    )
                ),
            }
        ),
    )
    write(
        "comparison-decision-v1",
        obj(
            {
                "version": {"const": "evidence-v1"},
                "current_run_id": NULL_TEXT,
                "candidate_run_id": TEXT,
                "decision": enum("promote", "retain", "incomparable", "correct"),
                "reason": enum(
                    "initial",
                    "equivalent",
                    "improved",
                    "q16_system_transient",
                    "business_transient_loss",
                    "permanent_loss",
                    "unknown_loss",
                    "context_mismatch",
                    "fault_changed",
                    "anchor_lost",
                    "ambiguous_alignment",
                    "unwind_changed",
                    "interpretation_changed",
                    "legacy_evidence_missing",
                    "verified_correction",
                    "older_candidate",
                    "candidate_not_eligible",
                    "candidate_evidence_missing",
                    "occurrence_or_dump_mismatch",
                    "reviewed_transition",
                    "transition_requires_review",
                    "pair_evidence_incomplete",
                    "module_evidence_incomplete",
                    "correction_required",
                    "selection_evidence_incomplete",
                    "system_transient_loss",
                    "non_system_transient_loss",
                ),
                "retry": {"type": "boolean"},
                "differences": array(obj({"path": TEXT, "before": {}, "after": {}})),
                "audit_id": NULL_TEXT,
                "audit_sha256": nullable(HASH),
            }
        ),
    )


if __name__ == "__main__":
    main()
