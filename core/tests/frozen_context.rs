//! Explicit real-fixture full Run verification, including actual staged pairs.
use dmp_core::canonical::sha256_hex;
use dmp_core::canonical_v11::ModuleIdentity;
use dmp_core::frozen_context::{
    self, canonical_bytes, digest, EnginePins, RunAssignment, StagedPair,
};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::PathBuf;

fn refresh(run: &mut Value, manifest: &Value) {
    let keys = ["build_snapshot", "role_policy", "source_policy"];
    for key in keys {
        run["context"][format!("{key}_sha256")] =
            json!(digest(&run["policy_snapshots"][key]).unwrap());
    }
    run["context_sha256"] = json!(digest(&run["context"]).unwrap());
    run["resolution_manifest"]["sha256"] = json!(digest(manifest).unwrap());
    run["resolution_evidence_fingerprint"] =
        json!(frozen_context::resolution_fingerprint(manifest).unwrap());
    run["idempotency_key"] = json!(frozen_context::run_key(run).unwrap());
}

fn assignment(run: &Value) -> RunAssignment {
    RunAssignment {
        run_id: run["run_id"].as_str().unwrap().to_owned(),
        occurrence_id: run["occurrence_id"].as_str().unwrap().to_owned(),
        workspace_id: run["context"]["workspace_id"].as_str().unwrap().to_owned(),
        object_sha256: digest(run).unwrap(),
    }
}

#[test]
#[ignore = "requires generated real MSVC fixture; run explicit QAI full-context lane"]
fn real_dump_full_run_snapshot_and_actual_staged_pair_are_verified() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    let fixture = root.join("fixtures/p0-b01-null-read/generated");
    let output = root.join("target/qa-symbol-import/frozen-context");
    std::fs::create_dir_all(&output).unwrap();
    let dump = std::fs::read(fixture.join("null-read.dmp")).expect("generate real fixture first");
    let pe = fixture.join("null_read_target.exe");
    let pdb = fixture.join("null_read_target.pdb");
    let pe_sha = sha256_hex(&std::fs::read(&pe).unwrap());
    let pdb_bytes = std::fs::read(&pdb).unwrap();
    let pdb_sha = sha256_hex(&pdb_bytes);
    let pair = digest(&json!(["pair-v1", pe_sha, pdb_sha])).unwrap();
    let inspected = dmp_core::inspect_bytes(&dump).unwrap();
    let inspect = serde_json::to_value(&inspected).unwrap();
    let inspect_bytes = canonical_bytes(&inspect).unwrap();
    let target = inspected
        .modules
        .iter()
        .position(|m| m.code_file.ends_with("null_read_target.exe"))
        .unwrap();
    let selections=inspected.modules.iter().enumerate().map(|(index,module)|json!({
        "module_index":index,"identity":ModuleIdentity::captured(module,&inspected.process.architecture).unwrap(),
        "state":if index==target {"unique"}else{"none"},"candidates_complete":true,
        "candidate_pair_ids":if index==target {vec![pair.clone()]} else {vec![]},"unavailable_pair_ids":[],
        "selected_pair_id":if index==target {Some(pair.clone())}else{None},"reason":if index==target {"unique"}else{"missing"},
        "candidate_evidence":{"object_key":"qualification/candidates","sha256":"c".repeat(64)},"review_refs":[]
    })).collect::<Vec<_>>();
    let manifest = json!({"schema_version":"resolution-manifest-v1","dump_sha256":sha256_hex(&dump),"inspect_sha256":sha256_hex(&inspect_bytes),
        "inspector_version":"inspect-v0.1","selection_version":"pair-selection-v1","catalog_revision":1,"modules":selections});
    let build_manifest = json!({"schema_version":"1.0","product":"fixture","version":"qualification","architecture":"x86_64","modules":[{"code_file":"null_read_target.exe","debug_file":"null_read_target.pdb","role":"entrypoint","code_id":"untrusted-producer-hint"}]});
    let policies = json!({
        "build_snapshot":{"schema_version":"frozen-builds-v1","builds":[{"build_id":"bld_fixture","workspace_id":"wsp_fixture","manifest_sha256":digest(&build_manifest).unwrap(),"manifest":build_manifest,
            "verified_modules":[{"module_id":"mod_target","manifest_module_index":0,"identity":selections[target]["identity"],"role":"entrypoint","verified_pair_ids":[pair.clone()],"artifact_ids":["art_fixture"]}]}]},
        "role_policy":{"schema_version":"workspace-role-policy-v1","modules":selections.iter().enumerate().map(|(index,s)|json!({"module_index":index,"identity":s["identity"],"role":if index==target {"owned"}else{"unknown"},"in_app":index==target})).collect::<Vec<_>>()},
        "source_policy":{"schema_version":"frozen-source-policy-v1","pair_source_protocol":"pair-http-v2","public_sources":[],"bundles":[]}
    });
    let pins = EnginePins {
        core_image_digest: format!("sha256:{}", "0".repeat(64)),
        symbolicator_image_digest:
            "sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959".to_owned(),
        symbolicator_version: "26.7.2".to_owned(),
    };
    let mut run = json!({"schema_version":"analysis-run-v2","run_id":"run_frozen_context","occurrence_id":"occ_fixture","demand_id":"dem_fixture","demand_generation":1,"retry_attempt":0,"reason":"initial",
        "dump":{"object_key":"qualification/dump","sha256":sha256_hex(&dump),"size":dump.len()},
        "result_facts":{"dump":{"blob_id":"blob_fixture","sha256":sha256_hex(&dump),"size":dump.len(),"kind":inspected.dump.kind,"capture_profile":null,"dump_timestamp":inspected.dump.timestamp,"reported_at":null,"uploaded_at":"2026-09-03T00:00:00Z","occurred_at":"2026-09-03T00:00:00Z","time_source":"uploaded"}},
        "policy_snapshots":policies,"source_bundle_locations":[],"inspect":{"object_key":"qualification/inspect","sha256":sha256_hex(&inspect_bytes)},"resolution_manifest":{"object_key":"qualification/manifest","sha256":"0".repeat(64)},
        "resolution_evidence_fingerprint":"0".repeat(64),"context_sha256":"0".repeat(64),"idempotency_key":"0".repeat(64),
        "context":{"schema_version":"analysis-context-v2","workspace_id":"wsp_fixture","reported_build_id":null,"build_snapshot_sha256":"0".repeat(64),"role_policy_sha256":"0".repeat(64),"source_policy_sha256":"0".repeat(64),"capture_profile":null,
            "core_image_digest":pins.core_image_digest,"symbolicator_image_digest":pins.symbolicator_image_digest,"symbolicator_version":pins.symbolicator_version,
            "source_bundle_policy_version":"source-bundle-v1.0","normalization_version":"norm-v1.0","grouping_version":"group-v1.1","inspector_version":"inspect-v0.1","canonical_version":"1.1","selection_version":"pair-selection-v1"}});
    refresh(&mut run, &manifest);
    let verify = |run: &Value, manifest: &Value| {
        frozen_context::verify(
            &canonical_bytes(run).unwrap(),
            &canonical_bytes(manifest).unwrap(),
            &inspect_bytes,
            &dump,
            &pins,
            &assignment(run),
        )
    };
    let verified = verify(&run, &manifest).unwrap();
    let assembled_inputs = verified.canonical_inputs(BTreeMap::new()).unwrap();
    assert_eq!(
        assembled_inputs.build_resolution.as_ref().unwrap().resolved_build_id.as_deref(),
        Some("bld_fixture")
    );
    assert_eq!(assembled_inputs.modules[target].role, "owned");
    assert_eq!(assembled_inputs.modules[target].artifact_ids, vec!["art_fixture"]);
    let pairs = BTreeMap::from([(pair.clone(), StagedPair { pe: pe.clone(), pdb: pdb.clone() })]);
    let paths = verified.verify_pairs(&pairs).unwrap();
    assert_eq!(paths, BTreeMap::from([(target, pe.clone())]));
    let mut cases = vec![json!({"case":"full_run_and_actual_pair","status":"PASS"})];
    let mut ambiguous = run.clone();
    let mut other = ambiguous["policy_snapshots"]["build_snapshot"]["builds"][0].clone();
    other["build_id"] = json!("bld_other");
    ambiguous["policy_snapshots"]["build_snapshot"]["builds"].as_array_mut().unwrap().push(other);
    refresh(&mut ambiguous, &manifest);
    let ambiguous_inputs =
        verify(&ambiguous, &manifest).unwrap().canonical_inputs(BTreeMap::new()).unwrap();
    assert_eq!(ambiguous_inputs.build_resolution.unwrap().resolution_method, "ambiguous");
    let mut partial_identity = run.clone();
    partial_identity["policy_snapshots"]["build_snapshot"]["builds"][0]["verified_modules"][0]
        ["identity"]["debug_id"] = json!(format!("{}1", "e".repeat(32)));
    refresh(&mut partial_identity, &manifest);
    let partial_inputs =
        verify(&partial_identity, &manifest).unwrap().canonical_inputs(BTreeMap::new()).unwrap();
    assert!(partial_inputs.build_resolution.unwrap().resolved_build_id.is_none());
    assert!(partial_inputs.modules[target].artifact_ids.is_empty());
    cases.push(
        json!({"case":"Build_ambiguity_and_complete_identity_not_Code_ID_alone","status":"PASS"}),
    );
    for defect in [
        "role",
        "build_scope",
        "build_role",
        "manifest_index",
        "source_url",
        "source_protocol",
        "algorithm",
        "preauthorized_correction",
        "overlap",
        "run_key",
        "time_source",
    ] {
        let mut r = run.clone();
        let mut m = manifest.clone();
        match defect {
            "role" => {
                r["policy_snapshots"]["role_policy"]["modules"][target]["in_app"] = json!(false)
            }
            "build_scope" => {
                r["policy_snapshots"]["build_snapshot"]["builds"][0]["workspace_id"] =
                    json!("wsp_other")
            }
            "build_role" => {
                r["policy_snapshots"]["build_snapshot"]["builds"][0]["verified_modules"][0]
                    ["role"] = json!("owned")
            }
            "manifest_index" => {
                r["policy_snapshots"]["build_snapshot"]["builds"][0]["verified_modules"][0]
                    ["manifest_module_index"] = json!(99)
            }
            "source_url" => {
                r["policy_snapshots"]["source_policy"]["public_sources"] = json!([{"id":"public","type":"http","url":"https://user:secret@example.test/","layout":{"type":"symstore"},"filters":{"filetypes":["pdb","pe"]},"is_public":true}])
            }
            "source_protocol" => {
                r["policy_snapshots"]["source_policy"]["pair_source_protocol"] =
                    json!("unfrozen-v9")
            }
            "algorithm" => r["context"]["grouping_version"] = json!("group-v1.0"),
            "preauthorized_correction" => {
                r["reason"] = json!("evidence_correction");
                r["correction_ref"] = json!({"object_key":"future.json","sha256":"a".repeat(64)});
            }
            "overlap" => m["modules"][target]["unavailable_pair_ids"] = json!([pair.clone()]),
            "time_source" => {
                r["result_facts"]["dump"]["occurred_at"] = json!("2026-09-03T01:00:00Z")
            }
            _ => {}
        }
        refresh(&mut r, &m);
        if defect == "run_key" {
            r["idempotency_key"] = json!("f".repeat(64));
        }
        assert!(verify(&r, &m).is_err(), "accepted {defect}");
        cases.push(json!({"case":defect,"status":"PASS"}));
    }
    let mut wrong_assignment = assignment(&run);
    wrong_assignment.workspace_id = "wsp_other".to_owned();
    assert!(frozen_context::verify(
        &canonical_bytes(&run).unwrap(),
        &canonical_bytes(&manifest).unwrap(),
        &inspect_bytes,
        &dump,
        &pins,
        &wrong_assignment
    )
    .is_err());
    let mut changed = run.clone();
    changed["run_id"] = json!("run_other");
    assert!(frozen_context::verify(
        &canonical_bytes(&changed).unwrap(),
        &canonical_bytes(&manifest).unwrap(),
        &inspect_bytes,
        &dump,
        &pins,
        &assignment(&run)
    )
    .is_err());
    cases.push(json!({"case":"independent_assignment_identity_and_object_hash","status":"PASS"}));
    let mut wrong_pins = pins.clone();
    wrong_pins.symbolicator_version = "other".to_owned();
    assert!(frozen_context::verify(
        &canonical_bytes(&run).unwrap(),
        &canonical_bytes(&manifest).unwrap(),
        &inspect_bytes,
        &dump,
        &wrong_pins,
        &assignment(&run)
    )
    .is_err());
    cases.push(json!({"case":"executing_engine_pins","status":"PASS"}));
    assert!(verified.verify_pairs(&BTreeMap::new()).is_err());
    let mut changed_pdb = pdb_bytes;
    let old = b"trigger_null_read";
    let position = changed_pdb.windows(old.len()).position(|w| w == old).unwrap();
    changed_pdb[position..position + old.len()].copy_from_slice(b"trigger_fake_read");
    let changed_path = output.join("changed-same-identity.pdb");
    std::fs::write(&changed_path, changed_pdb).unwrap();
    let wrong_pairs = BTreeMap::from([(pair.clone(), StagedPair { pe, pdb: changed_path })]);
    assert!(verified.verify_pairs(&wrong_pairs).is_err());
    cases.push(json!({"case":"actual_pair_content_and_staging_membership","status":"PASS"}));
    for (name, value) in
        [("run.json", &run), ("manifest.json", &manifest), ("inspect.json", &inspect)]
    {
        std::fs::write(output.join(name), canonical_bytes(value).unwrap()).unwrap();
    }
    std::fs::write(output.join("qualification.json"),serde_json::to_vec_pretty(&json!({"status":"PASS","scope":"native full Run/context validation and actual PE/PDB staging; synthetic platform snapshots, no Worker/Current/deployment proof","cases":cases,"run_sha256":digest(&run).unwrap(),"dump_sha256":sha256_hex(&dump),"pair_id":pair,"selected_module_index":target})).unwrap()).unwrap();
}
