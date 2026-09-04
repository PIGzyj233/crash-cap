use crate::canonical::{CanonicalAnalysisResult, DumpInfo};
use crate::canonical_v11::*;
use crate::minidump::{InspectModule, InspectReport};
use crate::symbolicator::SymbolicatedFrame;
use crate::unwind::{UnwindFrame, UnwindReport, UnwindThread};
use serde_json::json;

fn reference() -> ObjectRef {
    ObjectRef { object_key: "test/evidence.json".to_owned(), sha256: "a".repeat(64) }
}

fn sample() -> (InspectReport, UnwindReport, FrozenInputs) {
    let module = |name: &str, base: &str, debug: &str| InspectModule {
        code_file: name.to_owned(),
        code_id: "123456781000".to_owned(),
        debug_file: Some("same.pdb".to_owned()),
        debug_id: Some(debug.to_owned()),
        image_base: base.to_owned(),
        image_size: 4096,
        time_date_stamp: "0x12345678".to_owned(),
        checksum: "0x0".to_owned(),
    };
    let report: InspectReport = serde_json::from_value(json!({
        "schema_version":"0.1", "dump":{"kind":"user_minidump","size":1,"signature":"MDMP", "number_of_streams":1,"flags":"0x0","timestamp":null},
        "process":{"pid":1,"architecture":"x86_64","os":"windows","os_version":null,"platform_id":2,"build_number":null,"processor_count":1},
        "exception":{"thread_id":1,"code":"0xc0000005","name":"EXCEPTION_ACCESS_VIOLATION","flags":"0x0","address":"0x1010","fault_address":"0x0","access_type":"read","parameters":[],"context":null},
        "crash_thread_id":1, "threads":[{"id":1,"teb":"0x0","stack_start":"0x0","stack_size":1,"context":null}],
        "modules":[],"warnings":[]
    })).unwrap();
    let mut report = report;
    // Same filename and Code ID, distinct Debug IDs, load addresses and roles.
    report.modules = vec![
        module("same.exe", "0x1000", &format!("{}1", "1".repeat(32))),
        module("same.exe", "0x3000", &format!("{}1", "2".repeat(32))),
    ];
    let raw = |pc| UnwindFrame {
        instruction: pc,
        resume_address: pc,
        module: None,
        function: Some("untracked_raw_function".to_owned()),
        file: Some("secret.cpp".to_owned()),
        line: Some(123),
        trust: "context".to_owned(),
        unwind_method: Some("context".to_owned()),
        inline: false,
    };
    let unwind = UnwindReport {
        threads: vec![UnwindThread { id: 1, frames: vec![raw(0x1010), raw(0x3010), raw(0x3010)] }],
    };
    let modules = report
        .modules
        .iter()
        .enumerate()
        .map(|(index, m)| FrozenModule {
            selection: FrozenSelection {
                module_index: index,
                identity: ModuleIdentity::captured(m, "x86_64").unwrap(),
                state: "unique".to_owned(),
                candidates_complete: true,
                candidate_pair_ids: vec![
                    format!("{}", if index == 0 { "a" } else { "b" }).repeat(64)
                ],
                unavailable_pair_ids: vec![],
                selected_pair_id: Some(if index == 0 { "a" } else { "b" }.repeat(64)),
                reason: "unique".to_owned(),
                candidate_evidence: reference(),
                review_refs: vec![],
            },
            role: if index == 0 { "unknown" } else { "owned" }.to_owned(),
            in_app: index == 1,
            artifact_ids: vec![],
            source_outcomes: vec![SourceOutcome {
                source_id: format!("pair-{index}"),
                stage: "symbolicate".to_owned(),
                outcome: "found".to_owned(),
                failure_class: "none".to_owned(),
                reason: "verified_response".to_owned(),
                diagnostic_ref: Some(reference()),
            }],
        })
        .collect();
    let dump = DumpInfo {
        blob_id: "blob_test".to_owned(),
        sha256: crate::canonical::sha256_hex(b"x"),
        kind: "user_minidump".to_owned(),
        size: 1,
        capture_profile: None,
        dump_timestamp: None,
        reported_at: None,
        uploaded_at: "2026-09-03T00:00:00Z".to_owned(),
        occurred_at: "2026-09-03T00:00:00Z".to_owned(),
        time_source: "uploaded".to_owned(),
    };
    let inputs = FrozenInputs {
        workspace_id: "ws_test".to_owned(),
        occurrence_id: "occ_test".to_owned(),
        analysis_id: "run_test".to_owned(),
        dump,
        core_image_digest: format!("sha256:{}", "1".repeat(64)),
        symbolicator_version: "qualification".to_owned(),
        build_resolution: None,
        modules,
        public_source_ids: vec![],
        symbol_resolution: SymbolResolution {
            selection_version: "pair-selection-v1".to_owned(),
            resolution_evidence_fingerprint: "2".repeat(64),
            manifest: reference(),
            inspect_sha256: "3".repeat(64),
            context_sha256: "4".repeat(64),
        },
    };
    (report, unwind, inputs)
}

fn packet(frame: usize, module: usize, function: &str) -> FrameSymbol {
    FrameSymbol {
        thread_index: 0,
        physical_frame_index: frame,
        module_index: module,
        instruction: if module == 0 { 0x1010 } else { 0x3010 },
        pair_id: Some(if module == 0 { "a" } else { "b" }.repeat(64)),
        source_id: format!("pair-{module}"),
        symbol: SymbolicatedFrame { function: Some(function.to_owned()), ..Default::default() },
    }
}

#[test]
fn instance_indices_isolate_same_code_id_roles_symbols_and_recursive_slots() {
    let (report, raw, inputs) = sample();
    validate_inputs(&report, b"x", &inputs).unwrap();
    let symbols = vec![
        packet(0, 0, "vendor_fault"),
        packet(1, 1, "owned_first"),
        packet(2, 1, "owned_second"),
    ];
    let result = assemble_checked(&report, b"x", &raw, &symbols, inputs).unwrap();
    let frames = &result.threads[0].frames;
    assert_eq!(result.modules[0].module.role, "unknown");
    assert!(!frames[0].frame.in_app);
    assert_eq!(frames[0].frame.function.as_deref(), Some("vendor_fault"));
    assert!(frames[1].frame.in_app);
    assert_eq!(frames[1].frame.function.as_deref(), Some("owned_first"));
    assert_eq!(frames[2].frame.function.as_deref(), Some("owned_second"));
    assert_eq!(frames[1].physical_frame_index, 1);
    assert_eq!(frames[2].physical_frame_index, 2);
    assert_ne!(frames[0].frame.module_debug_id, frames[1].frame.module_debug_id);
    assert!(
        result.fingerprints.exact.is_some(),
        "unknown fault module can coexist with reliable owned caller"
    );
    assert!(result.build_resolution.resolved_build_id.is_none());
    assert_eq!(result.quality.symbol_coverage, 1.0);
    let value = serde_json::to_value(&result).unwrap();
    let schema: serde_json::Value =
        serde_json::from_str(include_str!("../../contracts/analysis-result-v1.1.schema.json"))
            .unwrap();
    let validator = jsonschema::validator_for(&schema).unwrap();
    assert!(validator.is_valid(&value), "{:?}", validator.iter_errors(&value).collect::<Vec<_>>());
    let legacy: serde_json::Value =
        serde_json::from_str(include_str!("../../contracts/analysis-result-v1.schema.json"))
            .unwrap();
    assert!(!jsonschema::validator_for(&legacy).unwrap().is_valid(&value));
}

#[test]
fn inline_records_preserve_physical_origin_and_repeated_names_without_weighting_quality() {
    let (report, raw, inputs) = sample();
    let mut symbol = packet(1, 1, "outer");
    symbol.symbol.inline =
        vec![SymbolicatedFrame { function: Some("repeated".to_owned()), ..Default::default() }; 2];
    let result = assemble_checked(&report, b"x", &raw, &[symbol], inputs).unwrap();
    let frames = &result.threads[0].frames;
    assert_eq!(frames.len(), 5);
    assert_eq!(frames.iter().map(|f| f.frame.index).collect::<Vec<_>>(), vec![0, 1, 2, 3, 4]);
    assert_eq!(
        frames.iter().map(|f| f.physical_frame_index).collect::<Vec<_>>(),
        vec![0, 1, 1, 1, 2]
    );
    assert!(frames[2].frame.inline && frames[3].frame.inline);
    assert!(!frames[1].frame.inline);
    assert_eq!(result.quality.symbol_coverage, 0.5);
    assert_eq!(
        frames[0].frame.function, None,
        "raw symbols cannot enter without a frozen source packet"
    );
    assert_eq!(frames[0].frame.file, None);
    assert_eq!(frames[0].frame.line, None);
}

#[test]
fn native_cfi_scan_is_low_trust_for_quality_and_exact_but_wire_trust_remains_compatible() {
    let (report, mut raw, mut inputs) = sample();
    raw.threads[0].frames.truncate(1);
    inputs.modules[0].role = "owned".to_owned();
    inputs.modules[0].in_app = true;
    let frame = &mut raw.threads[0].frames[0];
    frame.trust = "cfi".to_owned();
    frame.unwind_method = Some("call_frame_info".to_owned());
    let cfi =
        assemble_checked(&report, b"x", &raw, &[packet(0, 0, "fault")], inputs.clone()).unwrap();
    raw.threads[0].frames[0].unwind_method = Some("cfi_scan".to_owned());
    let scan = assemble_checked(&report, b"x", &raw, &[packet(0, 0, "fault")], inputs).unwrap();
    assert_eq!(cfi.quality.unwind_reliability, 1.0);
    assert_eq!(scan.quality.unwind_reliability, 0.2);
    assert!(cfi.fingerprints.exact.is_some());
    assert!(scan.fingerprints.exact.is_none());
    assert_eq!(scan.threads[0].frames[0].frame.trust, "cfi");
    assert_eq!(scan.threads[0].frames[0].unwind_method, "cfi_scan");
    assert!(scan.quality.warnings.iter().any(|w| w.code == "scan_frames"));
    assert_eq!(scan.engine.grouping_version, "group-v1.1");
    assert_eq!(scan.fingerprints.algorithm, "exact-v1.1");
    // The old API has no native provenance semantics and stays byte-compatible.
    let old = CanonicalAnalysisResult::from_inspect(&report, b"x", "ws", "occ", "run");
    assert_eq!(old.engine.grouping_version, "group-v1.0");
    assert_eq!(old.schema_version, "1.0");
}

#[test]
fn blocked_states_reject_symbol_packets_and_never_leak_raw_symbols() {
    for (state, reason, complete) in [
        ("conflict", "identity_conflict", true),
        ("unavailable", "withdrawn", true),
        ("indeterminate", "enumeration_failed", false),
    ] {
        let (report, raw, mut inputs) = sample();
        let m = &mut inputs.modules[0];
        m.selection.state = state.to_owned();
        m.selection.reason = reason.to_owned();
        m.selection.candidates_complete = complete;
        m.selection.selected_pair_id = None;
        m.selection.candidate_pair_ids =
            if state == "conflict" { vec!["a".repeat(64), "c".repeat(64)] } else { vec![] };
        if state == "unavailable" {
            m.selection.unavailable_pair_ids = vec!["a".repeat(64)];
        }
        m.source_outcomes.clear();
        validate_inputs(&report, b"x", &inputs).unwrap();
        assert!(
            assemble_checked(&report, b"x", &raw, &[packet(0, 0, "bad")], inputs.clone()).is_err()
        );
        let result = assemble_checked(&report, b"x", &raw, &[], inputs).unwrap();
        assert_eq!(result.threads[0].frames[0].frame.function, None);
        assert_eq!(result.modules[0].module.status, format!("symbol_{state}"));
    }
}

#[test]
fn ambiguous_ranges_missing_provenance_and_mismatched_packets_fail_closed() {
    let (report, raw, inputs) = sample();
    let mut overlap = report.clone();
    overlap.modules[1].image_base = "0x1008".to_owned();
    assert!(assemble_checked(&overlap, b"x", &raw, &[], inputs.clone()).is_err());
    let mut old = raw.clone();
    old.threads[0].frames[0].unwind_method = None;
    assert!(assemble_checked(&report, b"x", &old, &[], inputs.clone()).is_err());
    let mut contradictory = raw.clone();
    contradictory.threads[0].frames[0].unwind_method = Some("scan".to_owned());
    assert!(assemble_checked(&report, b"x", &contradictory, &[], inputs.clone()).is_err());
    for mut p in [
        packet(0, 1, "wrong module"),
        packet(0, 0, "wrong pair"),
        packet(0, 0, "wrong PC"),
        packet(0, 0, "wrong source"),
    ] {
        match p.symbol.function.as_deref().unwrap() {
            "wrong pair" => p.pair_id = Some("c".repeat(64)),
            "wrong PC" => p.instruction += 1,
            "wrong source" => p.source_id = "unrelated".to_owned(),
            _ => {}
        }
        assert!(assemble_checked(&report, b"x", &raw, &[p], inputs.clone()).is_err());
    }
    let p = packet(0, 0, "duplicate");
    assert!(assemble_checked(&report, b"x", &raw, &[p.clone(), p], inputs.clone()).is_err());
    let mut threads = raw.clone();
    threads.threads[0].id = 999;
    assert!(assemble_checked(&report, b"x", &threads, &[], inputs).is_err());
}

#[test]
fn frozen_identity_selection_role_time_and_source_diagnostics_are_validated() {
    let (report, _, inputs) = sample();
    validate_inputs(&report, b"x", &inputs).unwrap();
    let mut mutations = Vec::new();
    let mut v = inputs.clone();
    v.modules[0].selection.unavailable_pair_ids = v.modules[0].selection.candidate_pair_ids.clone();
    mutations.push(v);
    let mut v = inputs.clone();
    v.modules[1].selection.identity.debug_id = v.modules[0].selection.identity.debug_id.clone();
    mutations.push(v);
    let mut v = inputs.clone();
    v.modules[0].selection.candidates_complete = false;
    mutations.push(v);
    let mut v = inputs.clone();
    v.modules[0].in_app = true;
    mutations.push(v);
    let mut v = inputs.clone();
    v.dump.occurred_at = "2026-09-03T01:00:00Z".to_owned();
    mutations.push(v);
    let mut v = inputs.clone();
    v.modules[0].selection.selected_pair_id = Some("f".repeat(64));
    mutations.push(v);
    let mut v = inputs.clone();
    v.modules[0].source_outcomes[0].failure_class = "transient".to_owned();
    mutations.push(v);
    let mut v = inputs.clone();
    v.modules[0].source_outcomes[0].outcome = "failed".to_owned();
    v.modules[0].source_outcomes[0].failure_class = "transient".to_owned();
    v.modules[0].source_outcomes[0].diagnostic_ref = None;
    mutations.push(v);
    for v in mutations {
        assert!(validate_inputs(&report, b"x", &v).is_err());
    }
}

#[test]
fn public_symbols_require_frozen_policy_and_none_selection() {
    let (report, raw, mut inputs) = sample();
    let mut symbol = packet(0, 0, "public_function");
    symbol.pair_id = None;
    symbol.source_id = "public-test".to_owned();
    inputs.public_source_ids = vec!["public-test".to_owned()];
    inputs.modules[0].source_outcomes[0].source_id = "public-test".to_owned();
    assert!(
        assemble_checked(&report, b"x", &raw, &[symbol.clone()], inputs.clone()).is_err(),
        "public source cannot replace a unique private pair"
    );
    let selection = &mut inputs.modules[0].selection;
    selection.state = "none".to_owned();
    selection.reason = "missing".to_owned();
    selection.selected_pair_id = None;
    selection.candidate_pair_ids.clear();
    validate_inputs(&report, b"x", &inputs).unwrap();
    let result = assemble_checked(&report, b"x", &raw, &[symbol.clone()], inputs.clone()).unwrap();
    assert_eq!(result.threads[0].frames[0].frame.function.as_deref(), Some("public_function"));
    assert!(!result.modules[0].module.in_app);
    inputs.public_source_ids.clear();
    assert!(assemble_checked(&report, b"x", &raw, &[symbol], inputs).is_err());
}
