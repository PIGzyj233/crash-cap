//! Run only under qualify_native_sources.py, which owns the isolated service.
use dmp_core::canonical::sha256_hex;
use dmp_core::canonical_v11::{self, ObjectRef};
use dmp_core::frozen_context::{self, EnginePins, RunAssignment, StagedPair};
use dmp_core::frozen_symbolicator::{self, Collected};
use dmp_core::unwind::unwind_bytes_with_selected_modules;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

fn save(directory: &Path, name: &str, value: &Value) -> ObjectRef {
    let bytes = serde_json::to_vec_pretty(value).unwrap();
    std::fs::write(directory.join(name), &bytes).unwrap();
    ObjectRef {
        object_key: format!("qualification/native-source/{name}"),
        sha256: sha256_hex(&bytes),
    }
}

#[test]
#[ignore = "requires explicit isolated pinned Symbolicator and real MSVC fixture"]
fn native_partitioned_source_produces_real_functions_lines_and_core_v11() {
    let endpoint =
        std::env::var("QAI_NATIVE_SOURCE_ENDPOINT").expect("run qualification owner script");
    let source_root = std::env::var("QAI_NATIVE_SOURCE_ROOT").expect("managed fixture source root");
    let version =
        std::env::var("QAI_NATIVE_SOURCE_VERSION").expect("observed pinned engine version");
    let image_digest =
        std::env::var("QAI_NATIVE_SOURCE_IMAGE_DIGEST").expect("observed engine image digest");
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    let fixture = root.join("fixtures/p0-b01-null-read/generated");
    let baseline = root.join("target/qa-symbol-import/frozen-context");
    let output = root.join("target/qa-symbol-import/native-source");
    std::fs::create_dir_all(&output).unwrap();
    let dump = std::fs::read(fixture.join("null-read.dmp")).unwrap();
    let inspect_bytes =
        std::fs::read(baseline.join("inspect.json")).expect("run full context fixture lane first");
    let run_bytes = std::fs::read(baseline.join("run.json")).unwrap();
    let manifest_bytes = std::fs::read(baseline.join("manifest.json")).unwrap();
    let metadata: Value =
        serde_json::from_slice(&std::fs::read(baseline.join("qualification.json")).unwrap())
            .unwrap();
    let assignment = RunAssignment {
        run_id: "run_frozen_context".to_owned(),
        occurrence_id: "occ_fixture".to_owned(),
        workspace_id: "wsp_fixture".to_owned(),
        object_sha256: metadata["run_sha256"].as_str().unwrap().to_owned(),
    };
    let pins = EnginePins {
        core_image_digest: format!("sha256:{}", "0".repeat(64)),
        symbolicator_image_digest: image_digest,
        symbolicator_version: version,
    };
    let verified = frozen_context::verify(
        &run_bytes,
        &manifest_bytes,
        &inspect_bytes,
        &dump,
        &pins,
        &assignment,
    )
    .unwrap();
    let pair = metadata["pair_id"].as_str().unwrap().to_owned();
    let paths = verified
        .verify_pairs(&BTreeMap::from([(
            pair,
            StagedPair {
                pe: fixture.join("null_read_target.exe"),
                pdb: fixture.join("null_read_target.pdb"),
            },
        )]))
        .unwrap();
    let unwind = unwind_bytes_with_selected_modules(&dump, &paths).unwrap();
    let plan = frozen_symbolicator::plan(
        verified.inspect(),
        &unwind,
        verified.selections(),
        &source_root,
        verified.public_sources(),
    )
    .unwrap();
    assert_eq!(plan.partitions.len(), 1);
    assert!(plan.blocked_modules.len() + 1 == verified.selections().len());
    save(&output, "plan.json", &serde_json::to_value(&plan).unwrap());
    save(&output, "unwind.json", &serde_json::to_value(&unwind).unwrap());
    // Exercise real source HTTP failures through the pinned engine and Core
    // collector. The pinned engine's candidate diagnostics carry the exact
    // failure for the verified source/location; fixture logs alone are not used.
    for (mode, expected) in [("native-missing", "permanent"), ("native-unavailable", "transient")] {
        let mut fault_run: Value = serde_json::from_slice(&run_bytes).unwrap();
        let fault_run_id = format!("run_frozen_context_{mode}");
        fault_run["run_id"] = json!(fault_run_id);
        fault_run["reason"] = json!("manual");
        fault_run["retry_attempt"] = json!(if mode == "native-missing" { 1 } else { 2 });
        fault_run["idempotency_key"] = json!(frozen_context::run_key(&fault_run).unwrap());
        let fault_run_bytes = serde_json::to_vec(&fault_run).unwrap();
        std::fs::write(output.join(format!("{mode}-run.json")), &fault_run_bytes).unwrap();
        let fault_verified = frozen_context::verify(
            &fault_run_bytes,
            &manifest_bytes,
            &inspect_bytes,
            &dump,
            &pins,
            &RunAssignment {
                run_id: fault_run_id,
                occurrence_id: assignment.occurrence_id.clone(),
                workspace_id: assignment.workspace_id.clone(),
                object_sha256: sha256_hex(&fault_run_bytes),
            },
        )
        .unwrap();
        let fault_plan = frozen_symbolicator::plan(
            verified.inspect(),
            &unwind,
            verified.selections(),
            &format!("{source_root}/{mode}"),
            verified.public_sources(),
        )
        .unwrap();
        let job = &fault_plan.partitions[0];
        let transport = frozen_symbolicator::execute(&endpoint, job, 90).unwrap();
        let diagnostic = save(
            &output,
            &format!("{mode}-transport.json"),
            &serde_json::to_value(&transport).unwrap(),
        );
        assert!(transport.failure.is_none(), "{mode}: {:?}", transport.failure);
        let collected =
            frozen_symbolicator::collect(job, transport.response.as_ref().unwrap(), diagnostic)
                .unwrap();
        assert!(collected.frames.is_empty(), "{mode}: unexpected symbols");
        let downloads = collected
            .modules
            .iter()
            .flat_map(|(_, outcomes)| outcomes)
            .filter(|outcome| outcome.stage == "download_pdb")
            .collect::<Vec<_>>();
        assert!(!downloads.is_empty(), "{mode}: missing source evidence");
        assert!(
            downloads.iter().all(|outcome| outcome.failure_class == expected),
            "{mode}: {downloads:?}"
        );
        let fault_canonical = canonical_v11::assemble(
            &inspect_bytes,
            &dump,
            &unwind,
            &collected.frames,
            fault_verified.canonical_inputs(collected.modules.into_iter().collect()).unwrap(),
        )
        .unwrap();
        save(
            &output,
            &format!("{mode}-canonical.json"),
            &serde_json::to_value(&fault_canonical).unwrap(),
        );
    }
    let mut gathered = Vec::<Collected>::new();
    for phase in ["cold", "warm"] {
        let mut collected = Collected { frames: vec![], modules: vec![] };
        for (i, job) in plan.partitions.iter().enumerate() {
            let transport = frozen_symbolicator::execute(&endpoint, job, 90).unwrap();
            let diagnostic = save(
                &output,
                &format!("{phase}-{i}-transport.json"),
                &serde_json::to_value(&transport).unwrap(),
            );
            assert!(transport.failure.is_none(), "{:?}", transport.failure);
            let result =
                frozen_symbolicator::collect(job, transport.response.as_ref().unwrap(), diagnostic)
                    .unwrap();
            collected.frames.extend(result.frames);
            collected.modules.extend(result.modules);
        }
        assert!(collected.frames.iter().any(|f| f
            .symbol
            .function
            .as_deref()
            .is_some_and(|s| s.contains("trigger_null_read"))
            && f.symbol.line == Some(76)));
        gathered.push(collected);
    }
    let signature = |r: &Collected| {
        r.frames
            .iter()
            .map(|f| {
                (
                    f.thread_index,
                    f.physical_frame_index,
                    f.module_index,
                    f.instruction,
                    f.symbol.clone(),
                )
            })
            .collect::<Vec<_>>()
    };
    assert_eq!(signature(&gathered[0]), signature(&gathered[1]));
    let selected = gathered.remove(0);
    let outcomes = selected.modules.into_iter().collect::<BTreeMap<_, _>>();
    let canonical = canonical_v11::assemble(
        &inspect_bytes,
        &dump,
        &unwind,
        &selected.frames,
        verified.canonical_inputs(outcomes).unwrap(),
    )
    .unwrap();
    assert_eq!(canonical.schema_version, "2.0");
    assert_eq!(canonical.analysis_id, "run_frozen_context");
    let value = serde_json::to_value(&canonical).unwrap();
    let schema: Value =
        serde_json::from_str(include_str!("../../contracts/analysis-result-v2.0.schema.json"))
            .unwrap();
    let validator = jsonschema::validator_for(&schema).unwrap();
    assert!(validator.is_valid(&value), "{:?}", validator.iter_errors(&value).collect::<Vec<_>>());
    assert!(canonical.threads.iter().flat_map(|t| &t.frames).any(|f| f
        .frame
        .function
        .as_deref()
        .is_some_and(|s| s.contains("trigger_null_read"))
        && f.frame.line == Some(76)));
    let result_ref = save(&output, "canonical.json", &value);
    save(
        &output,
        "qualification.json",
        &json!({"status":"PASS","scope":"full Run/context/assignment and actual pairs -> native PE unwind/source -> Core 1.1; synthetic platform records, no Worker/Current/deployment proof","run_sha256":metadata["run_sha256"],"dump_sha256":sha256_hex(&dump),"canonical":result_ref,"private_source_count_per_request":1,"partition_count":plan.partitions.len(),"cold_warm_equal":true,"symbolized_physical_frames":selected.frames.len(),"core_image_attested":false}),
    );
}
