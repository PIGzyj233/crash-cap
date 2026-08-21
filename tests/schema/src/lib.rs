#![allow(dead_code)]

use jsonschema::Validator;
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};

fn contract_path(name: &str) -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("..").join("..").join("contracts").join(name)
}

fn load_schema(name: &str) -> Value {
    let path = contract_path(name);
    let source = fs::read_to_string(&path)
        .unwrap_or_else(|error| panic!("read schema {}: {error}", path.display()));
    serde_json::from_str(&source)
        .unwrap_or_else(|error| panic!("parse schema {}: {error}", path.display()))
}

fn validator(name: &str) -> Validator {
    let schema = load_schema(name);
    jsonschema::validator_for(&schema)
        .unwrap_or_else(|error| panic!("schema {name} is not valid Draft 2020-12: {error}"))
}

fn assert_valid(name: &str, instance: &Value) {
    let validator = validator(name);
    if let Err(error) = validator.validate(instance) {
        panic!("expected {name} instance to be valid: {error}");
    }
}

fn assert_invalid(name: &str, instance: &Value) {
    let validator = validator(name);
    assert!(!validator.is_valid(instance), "expected {name} instance to be rejected: {instance}");
}

fn canonical_result() -> Value {
    json!({
        "schema_version": "0.1",
        "workspace_id": "wsp_demo",
        "occurrence_id": "occ_demo",
        "analysis_id": "run_demo",
        "engine": {
            "core_version": "0.1.0",
            "core_image_digest": format!("sha256:{}", "0".repeat(64)),
            "symbolicator_version": "unavailable",
            "grouping_version": "group-v0.1",
            "normalization_version": "norm-v0.1"
        },
        "build_resolution": {
            "reported_build_id": null,
            "resolved_build_id": null,
            "resolution_method": "unresolved",
            "evidence": {
                "candidate_build_ids": [],
                "matched_entrypoints": [],
                "matched_owned_modules": [],
                "conflicting_modules": [],
                "note": "no build supplied"
            }
        },
        "dump": {
            "blob_id": "blob_demo",
            "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            "kind": "user_minidump",
            "size": 64,
            "capture_profile": null,
            "dump_timestamp": null,
            "reported_at": null,
            "uploaded_at": "2026-08-20T00:00:00Z",
            "occurred_at": "2026-08-20T00:00:00Z",
            "time_source": "uploaded"
        },
        "process": {
            "pid": null,
            "architecture": "x86_64",
            "os": "windows",
            "os_version": "10.0.22631",
            "uptime_seconds": null
        },
        "crash": {
            "type": "unknown",
            "type_evidence": "insufficient",
            "thread_id": null,
            "exception_code": null,
            "exception_name": null,
            "access_type": null,
            "address": null,
            "fault_module": null,
            "fault_module_debug_id": null
        },
        "threads": [{
            "id": 1,
            "name": null,
            "is_crashing": false,
            "frames": []
        }],
        "modules": [{
            "code_file": "app.exe",
            "code_id": "67A1B9231F000",
            "debug_file": null,
            "debug_id": null,
            "image_base": "0x140000000",
            "image_size": 126976,
            "role": "unknown",
            "in_app": false,
            "artifact_ids": [],
            "status": "missing_pe"
        }],
        "quality": {
            "score": 0,
            "symbol_coverage": 0,
            "unwind_reliability": 0,
            "artifact_completeness": 0,
            "warnings": [{
                "code": "unknown_crash_type",
                "message": "no exception stream was available",
                "module": null,
                "debug_id": null
            }]
        },
        "fingerprints": {
            "exact": null,
            "family": null,
            "algorithm": "exact-v0.1"
        }
    })
}

fn build_manifest() -> Value {
    json!({
        "schema_version": "0.1",
        "product": "Crash-Cap Demo",
        "version": "2026.08.20",
        "channel": "internal",
        "commit": "0123456789abcdef",
        "build_number": "42",
        "architecture": "x86_64",
        "compiler": "msvc",
        "toolchain": "vs2022",
        "modules": [
            {"code_file": "app.exe", "debug_file": "app.pdb", "role": "entrypoint"},
            {"code_file": "engine.dll", "debug_file": "engine.pdb", "role": "owned"}
        ]
    })
}

fn task_message() -> Value {
    json!({
        "schema_version": "0.1",
        "task_type": "analyze_occurrence",
        "run_id": "run_demo",
        "attempt_id": "attempt_1",
        "queue": "dump-small",
        "request_id": "req_demo"
    })
}

fn with_schema_version(mut value: Value, version: &str) -> Value {
    value["schema_version"] = json!(version);
    value
}

fn assert_version_pair(v0_schema: &str, v1_schema: &str, v0_instance: Value) {
    let v1_instance = with_schema_version(v0_instance.clone(), "1.0");
    assert_valid(v0_schema, &v0_instance);
    assert_valid(v1_schema, &v1_instance);
    assert_invalid(v0_schema, &v1_instance);
    assert_invalid(v1_schema, &v0_instance);
}

#[test]
fn all_contracts_validate_against_draft_2020_12_meta_schema() {
    for name in [
        "analysis-result-v0.schema.json",
        "analysis-result-v1.schema.json",
        "build-manifest-v0.schema.json",
        "build-manifest-v1.schema.json",
        "task-message-v0.schema.json",
        "task-message-v1.schema.json",
    ] {
        // validator_for performs the Draft 2020-12 meta-schema check before
        // compiling local refs. A malformed schema fails this test before any
        // instance assertions run.
        let _ = validator(name);
    }
}

#[test]
fn stable_v1_contracts_accept_own_version_and_reject_cross_version_payloads() {
    assert_version_pair(
        "analysis-result-v0.schema.json",
        "analysis-result-v1.schema.json",
        canonical_result(),
    );
    assert_version_pair(
        "build-manifest-v0.schema.json",
        "build-manifest-v1.schema.json",
        build_manifest(),
    );
    assert_version_pair(
        "task-message-v0.schema.json",
        "task-message-v1.schema.json",
        task_message(),
    );
}

#[test]
fn stable_v1_contracts_keep_v0_negative_constraints() {
    let mut canonical = with_schema_version(canonical_result(), "1.0");
    canonical["engine"]["core_image_digest"] = json!("sha256:not-a-digest");
    assert_invalid("analysis-result-v1.schema.json", &canonical);

    let mut manifest = with_schema_version(build_manifest(), "1.0");
    manifest["modules"][0]["role"] = json!("owned");
    assert_invalid("build-manifest-v1.schema.json", &manifest);

    let mut task = with_schema_version(task_message(), "1.0");
    task["queue"] = json!("verify");
    assert_invalid("task-message-v1.schema.json", &task);
}

#[test]
fn validator_rejects_a_schema_that_violates_the_draft_meta_schema() {
    let malformed = json!({
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "not-a-json-schema-type"
    });
    assert!(jsonschema::validator_for(&malformed).is_err());
}

#[test]
fn canonical_positive_and_negative_examples() {
    let valid = canonical_result();
    assert_valid("analysis-result-v0.schema.json", &valid);

    let mut extra = valid.clone();
    extra.as_object_mut().expect("object").insert("unexpected".to_owned(), json!(true));
    assert_invalid("analysis-result-v0.schema.json", &extra);

    let mut bad_digest = valid;
    bad_digest["engine"]["core_image_digest"] = json!("sha256:not-a-digest");
    assert_invalid("analysis-result-v0.schema.json", &bad_digest);

    let mut bad_frame = canonical_result();
    bad_frame["threads"][0]["frames"] = json!([{
        "index": 0,
        "instruction_addr": "0xABC",
        "trust": "not-a-trust-level",
        "in_app": true
    }]);
    assert_invalid("analysis-result-v0.schema.json", &bad_frame);

    let mut bad_module_role = canonical_result();
    bad_module_role["modules"][0]["role"] = json!("primary");
    assert_invalid("analysis-result-v0.schema.json", &bad_module_role);
}

#[test]
fn manifest_positive_and_negative_examples() {
    let valid = build_manifest();
    assert_valid("build-manifest-v0.schema.json", &valid);

    let mut missing_entrypoint = valid.clone();
    missing_entrypoint["modules"][0]["role"] = json!("owned");
    assert_invalid("build-manifest-v0.schema.json", &missing_entrypoint);

    let mut extra = valid;
    extra.as_object_mut().expect("object").insert("untrusted_code_id".to_owned(), json!("guess"));
    assert_invalid("build-manifest-v0.schema.json", &extra);
}

#[test]
fn task_positive_and_negative_examples() {
    let valid = task_message();
    assert_valid("task-message-v0.schema.json", &valid);

    let mut wrong_queue = valid.clone();
    wrong_queue["queue"] = json!("verify");
    assert_invalid("task-message-v0.schema.json", &wrong_queue);

    let mut extra = valid;
    extra.as_object_mut().expect("object").insert("dump_path".to_owned(), json!("/tmp/dump.dmp"));
    assert_invalid("task-message-v0.schema.json", &extra);
}

#[test]
fn every_task_variant_has_a_valid_routing_payload() {
    for (version, schema) in
        [("0.1", "task-message-v0.schema.json"), ("1.0", "task-message-v1.schema.json")]
    {
        let variants = [
            json!({"schema_version":version,"task_type":"verify_upload","upload_id":"upl_1","attempt_id":"a_1","queue":"verify"}),
            json!({"schema_version":version,"task_type":"analyze_occurrence","run_id":"run_1","attempt_id":"a_1","queue":"dump-large"}),
            json!({"schema_version":version,"task_type":"ingest_artifact","artifact_id":"art_1","attempt_id":"a_1","queue":"ingest"}),
            json!({"schema_version":version,"task_type":"reindex_symbols","workspace_id":"wsp_1","attempt_id":"a_1","queue":"ingest"}),
        ];
        for variant in variants {
            assert_valid(schema, &variant);
        }
    }
}
