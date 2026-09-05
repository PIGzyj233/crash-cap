#![cfg(test)]
use serde_json::{json, Value};
fn validator(name: &str) -> jsonschema::Validator {
    let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../contracts");
    let schema: Value =
        serde_json::from_str(&std::fs::read_to_string(root.join(name)).unwrap()).unwrap();
    jsonschema::validator_for(&schema).unwrap()
}
#[test]
fn canonical_native_v2_accepts_exact_schema_and_rejects_retired_business_fields() {
    let canonical: Value =
        serde_json::from_str(include_str!("../../../contracts/fixtures/canonical-v2.json"))
            .unwrap();
    let v = validator("analysis-result-v2.0.schema.json");
    assert!(v.is_valid(&canonical), "{:?}", v.iter_errors(&canonical).collect::<Vec<_>>());
    for field in ["build_resolution", "build_id", "version"] {
        let mut invalid = canonical.clone();
        invalid[field] = json!("forbidden");
        assert!(!v.is_valid(&invalid), "unexpectedly accepted {field}");
    }
    for version in ["0.1", "1.0", "1.1"] {
        let mut invalid = canonical.clone();
        invalid["schema_version"] = json!(version);
        assert!(!v.is_valid(&invalid));
    }
}
#[test]
fn task_routes_and_payloads_are_exclusive() {
    let v = validator("task-message-v3.schema.json");
    let tasks = [
        json!({"schema_version":"1.0","task_type":"verify_upload","upload_id":"upl_one","attempt_id":"att_one","queue":"verify"}),
        json!({"schema_version":"1.2","task_type":"dispatch_workspace_role","workspace_id":"wsp_one","role_version":1,"attempt_id":"att_two","queue":"ingest"}),
        json!({"schema_version":"1.2","task_type":"analyze_frozen_run","run_id":"run_one","attempt_id":"att_three","queue":"dump-small"}),
    ];
    for task in tasks {
        assert!(v.is_valid(&task));
        for queue in ["invalid", "verify"] {
            if task["queue"] == queue {
                continue;
            }
            let mut invalid = task.clone();
            invalid["queue"] = json!(queue);
            assert!(!v.is_valid(&invalid));
        }
        let mut invalid = task.clone();
        invalid["build_id"] = json!("bld_old");
        assert!(!v.is_valid(&invalid));
    }
}
