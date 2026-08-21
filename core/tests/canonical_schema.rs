use dmp_core::canonical::CanonicalAnalysisResult;
use dmp_core::minidump::{InspectDump, InspectProcess, InspectReport, InspectThread};
use serde_json::Value;

fn minimal_report() -> InspectReport {
    InspectReport {
        schema_version: "0.1".to_owned(),
        dump: InspectDump {
            kind: "user_minidump".to_owned(),
            size: 32,
            signature: "MDMP".to_owned(),
            number_of_streams: 1,
            flags: "0x0".to_owned(),
            timestamp: None,
        },
        process: InspectProcess {
            pid: None,
            architecture: "x86_64".to_owned(),
            os: "windows".to_owned(),
            os_version: Some("10.0.22631".to_owned()),
            platform_id: Some(2),
            build_number: Some(22631),
            processor_count: Some(1),
        },
        exception: None,
        crash_thread_id: None,
        threads: vec![InspectThread {
            id: 1,
            teb: "0x0".to_owned(),
            stack_start: "0x0".to_owned(),
            stack_size: 0,
            context: None,
        }],
        modules: Vec::new(),
        warnings: Vec::new(),
    }
}

#[test]
fn canonical_type_serializes_to_analysis_result_v1() {
    let schema: Value =
        serde_json::from_str(include_str!("../../contracts/analysis-result-v1.schema.json"))
            .expect("analysis schema JSON");
    let validator = jsonschema::validator_for(&schema).expect("Draft 2020-12 schema");
    let result = CanonicalAnalysisResult::from_inspect(
        &minimal_report(),
        b"synthetic dump bytes",
        "wsp_test",
        "occ_test",
        "run_test",
    );
    let value = serde_json::to_value(result).expect("canonical JSON");
    assert!(validator.is_valid(&value), "generated canonical does not match schema: {value}");
}

#[test]
fn canonical_contract_rejects_unknown_top_level_fields() {
    let schema: Value =
        serde_json::from_str(include_str!("../../contracts/analysis-result-v1.schema.json"))
            .expect("analysis schema JSON");
    let validator = jsonschema::validator_for(&schema).expect("Draft 2020-12 schema");
    let mut value = serde_json::to_value(CanonicalAnalysisResult::from_inspect(
        &minimal_report(),
        b"synthetic dump bytes",
        "wsp_test",
        "occ_test",
        "run_test",
    ))
    .expect("canonical JSON");
    value["unexpected"] = Value::Bool(true);
    assert!(!validator.is_valid(&value));
}
