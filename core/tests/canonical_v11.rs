//! Real native fixture lane. This does not impersonate a Worker/Current rollout.
use dmp_core::canonical::{sha256_hex, CanonicalAnalysisResult};
use dmp_core::canonical_v11::*;
use dmp_core::unwind::unwind_bytes_with_selected_modules;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

fn save(directory: &Path, name: &str, value: &Value) -> ObjectRef {
    let bytes = serde_json::to_vec_pretty(value).unwrap();
    std::fs::write(directory.join(name), &bytes).unwrap();
    ObjectRef { object_key: format!("qualification/native-v11/{name}"), sha256: sha256_hex(&bytes) }
}

#[test]
#[ignore = "requires generated MSVC p0-b01 fixture; run explicit QAI qualification lane"]
fn real_dump_produces_core_owned_v11_with_selected_instance_unwind_and_frozen_facts() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    let fixture = root.join("fixtures/p0-b01-null-read/generated");
    let output = root.join("target/qa-symbol-import/native-v11");
    std::fs::create_dir_all(&output).unwrap();
    let dump = std::fs::read(fixture.join("null-read.dmp")).expect("generate real MSVC fixture");
    let pe = fixture.join("null_read_target.exe");
    let pdb = fixture.join("null_read_target.pdb");
    let pe_sha = sha256_hex(&std::fs::read(&pe).unwrap());
    let pdb_sha = sha256_hex(&std::fs::read(&pdb).unwrap());
    let pair_id = sha256_hex(&serde_json::to_vec(&json!(["pair-v1", pe_sha, pdb_sha])).unwrap());
    let report = dmp_core::inspect_bytes(&dump).unwrap();
    let index =
        report.modules.iter().position(|m| m.code_file.ends_with("null_read_target.exe")).unwrap();
    let inspect_ref = save(&output, "inspect.json", &serde_json::to_value(&report).unwrap());
    let inspect_bytes = std::fs::read(output.join("inspect.json")).unwrap();
    let candidate_ref = save(
        &output,
        "candidates.json",
        &json!({"scope":"known real qualification fixture; not catalog admission","pair_id":pair_id,"pe_raw_sha256":pe_sha,"pdb_raw_sha256":pdb_sha}),
    );
    let selections = report
        .modules
        .iter()
        .enumerate()
        .map(|(i, m)| FrozenSelection {
            module_index: i,
            identity: ModuleIdentity::captured(m, &report.process.architecture).unwrap(),
            state: if i == index { "unique" } else { "none" }.to_owned(),
            candidates_complete: true,
            candidate_pair_ids: if i == index { vec![pair_id.clone()] } else { vec![] },
            unavailable_pair_ids: vec![],
            selected_pair_id: if i == index { Some(pair_id.clone()) } else { None },
            reason: if i == index { "unique" } else { "missing" }.to_owned(),
            candidate_evidence: candidate_ref.clone(),
            review_refs: vec![],
        })
        .collect::<Vec<_>>();
    let manifest = json!({"schema_version":"resolution-manifest-v1","dump_sha256":sha256_hex(&dump),"inspector_version":"inspect-v0.1","inspect_sha256":inspect_ref.sha256,"selection_version":"pair-selection-v1","catalog_revision":0,"modules":selections});
    let manifest_ref = save(&output, "manifest.json", &manifest);
    let semantic_modules=selections.iter().map(|s| json!({"module_index":s.module_index,"identity":s.identity,"state":s.state,"candidates_complete":s.candidates_complete,"candidate_pair_ids":s.candidate_pair_ids,"unavailable_pair_ids":s.unavailable_pair_ids,"selected_pair_id":s.selected_pair_id,"reason":s.reason})).collect::<Vec<_>>();
    let fingerprint = sha256_hex(
        &serde_json::to_vec(&json!([
            "resolution-evidence-v1",
            sha256_hex(&dump),
            "inspect-v0.1",
            "pair-selection-v1",
            semantic_modules
        ]))
        .unwrap(),
    );
    let context = json!({"scope":"native assembler fixture, not full Run/context-v2","workspace_id":"ws_native_qualification","grouping_version":GROUPING_VERSION,"selection_version":"pair-selection-v1"});
    save(&output, "context.json", &context);
    let context_sha = sha256_hex(&serde_json::to_vec(&context).unwrap());
    let selected =
        unwind_bytes_with_selected_modules(&dump, &BTreeMap::from([(index, pe)])).unwrap();
    let blocked = unwind_bytes_with_selected_modules(&dump, &BTreeMap::new()).unwrap();
    save(&output, "raw-selected.json", &serde_json::to_value(&selected).unwrap());
    save(&output, "raw-no-private-pe.json", &serde_json::to_value(&blocked).unwrap());
    let diagnostic = save(
        &output,
        "source-diagnostic.json",
        &json!({"scope":"local real fixture PE read and selected unwind","module_index":index,"pe_raw_sha256":pe_sha,"pair_id":pair_id,"private_pe_indices":[index]}),
    );
    let modules = selections
        .into_iter()
        .map(|selection| {
            let selected = selection.module_index == index;
            FrozenModule {
                selection,
                role: if selected { "entrypoint" } else { "unknown" }.to_owned(),
                in_app: selected,
                artifact_ids: vec![],
                source_outcomes: if selected {
                    vec![SourceOutcome {
                        source_id: format!("pair-{pair_id}"),
                        stage: "download_pe".to_owned(),
                        outcome: "found".to_owned(),
                        failure_class: "none".to_owned(),
                        reason: "local_fixture_bytes_verified".to_owned(),
                        diagnostic_ref: Some(diagnostic.clone()),
                    }]
                } else {
                    vec![]
                },
            }
        })
        .collect();
    let old = CanonicalAnalysisResult::from_inspect(
        &report,
        &dump,
        "ws_native_qualification",
        "occ_native",
        "run_native",
    );
    let mut facts = old.dump;
    facts.uploaded_at = "2026-09-03T00:00:00Z".to_owned();
    facts.occurred_at = facts.uploaded_at.clone();
    let inputs = FrozenInputs {
        workspace_id: "ws_native_qualification".to_owned(),
        occurrence_id: "occ_native".to_owned(),
        analysis_id: "run_native".to_owned(),
        dump: facts.clone(),
        core_image_digest: format!("sha256:{}", "0".repeat(64)),
        symbolicator_version: "not_called".to_owned(),
        build_resolution: None,
        modules,
        public_source_ids: vec![],
        symbol_resolution: SymbolResolution {
            selection_version: "pair-selection-v1".to_owned(),
            resolution_evidence_fingerprint: fingerprint,
            manifest: manifest_ref,
            inspect_sha256: inspect_ref.sha256,
            context_sha256: context_sha,
        },
    };
    let result = assemble(&inspect_bytes, &dump, &selected, &[], inputs.clone()).unwrap();
    assert_eq!(result.dump, facts);
    assert!(result
        .threads
        .iter()
        .flat_map(|t| &t.frames)
        .any(|f| f.unwind_method == "call_frame_info"));
    for (thread, raw) in result.threads.iter().zip(&selected.threads) {
        assert_eq!(thread.frames.len(), raw.frames.len());
        for frame in &thread.frames {
            let raw = &raw.frames[frame.physical_frame_index];
            assert_eq!(Some(frame.unwind_method.as_str()), raw.unwind_method.as_deref());
            assert_eq!(frame.frame.instruction_addr, format!("0x{:x}", raw.instruction));
        }
    }
    let value = serde_json::to_value(&result).unwrap();
    let schema: Value =
        serde_json::from_str(include_str!("../../contracts/analysis-result-v1.1.schema.json"))
            .unwrap();
    let validator = jsonschema::validator_for(&schema).unwrap();
    assert!(validator.is_valid(&value), "{:?}", validator.iter_errors(&value).collect::<Vec<_>>());
    let canonical_ref = save(&output, "canonical.json", &value);
    let mut wrong = inputs.clone();
    wrong.symbol_resolution.inspect_sha256 = "f".repeat(64);
    assert!(assemble(&inspect_bytes, &dump, &selected, &[], wrong).is_err());
    let mut wrong_report = report.clone();
    wrong_report.modules[index].code_id = "123456781000".to_owned();
    let wrong_bytes = serde_json::to_vec(&wrong_report).unwrap();
    let mut wrong = inputs.clone();
    wrong.symbol_resolution.inspect_sha256 = sha256_hex(&wrong_bytes);
    assert!(assemble(&wrong_bytes, &dump, &selected, &[], wrong).is_err());
    let mut old_raw = selected.clone();
    old_raw.threads[0].frames[0].unwind_method = None;
    assert!(assemble(&inspect_bytes, &dump, &old_raw, &[], inputs).is_err());
    save(
        &output,
        "qualification.json",
        &json!({"status":"PASS","scope":"native Core assembler + real selected PE unwind; no source request, full Run validation, Worker, Current or deployment proof","dump_sha256":sha256_hex(&dump),"pe_sha256":pe_sha,"pdb_sha256":pdb_sha,"pair_id":pair_id,"selected_module_index":index,"canonical":canonical_ref,"core_image_attested":false,"native_method_frame_count":result.threads.iter().map(|t|t.frames.len()).sum::<usize>()}),
    );
}
