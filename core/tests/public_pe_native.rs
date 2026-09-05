//! Opt-in real Microsoft proxy / PE unwind / PDB integration qualification.
use dmp_core::canonical_v11::{FrozenSelection, ModuleIdentity, ObjectRef};
use dmp_core::frozen_public_pe::{unwind, PublicPeRequest};
use dmp_core::{frozen_symbolicator, inspect_bytes};
use serde_json::json;
use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

#[test]
#[ignore = "requires pinned Symbolicator with Microsoft-only PE proxy and network"]
fn real_public_pe_extends_stack_and_loads_microsoft_pdb_without_catalog_pair() {
    let engine = std::env::var("QAI_PUBLIC_PE_ENGINE").expect("owned pinned engine URL");
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).parent().unwrap();
    let fixture = root.join("fixtures/p0-b01-null-read/generated");
    let dump = fs::read(fixture.join("null-read.dmp")).unwrap();
    let inspect = inspect_bytes(&dump).unwrap();
    let sources = vec![json!({"id": "crash-cap:microsoft", "type": "http",
        "url": "https://msdl.microsoft.com/download/symbols/", "layout": {"type": "symstore"},
        "filters": {"filetypes": ["pdb", "pe", "portablepdb"]}, "is_public": true})];
    let mut selections: Vec<_> = inspect
        .modules
        .iter()
        .enumerate()
        .map(|(index, module)| FrozenSelection {
            module_index: index,
            identity: ModuleIdentity::captured(module, "x86_64").unwrap(),
            state: "none".into(),
            candidates_complete: true,
            candidate_pair_ids: vec![],
            unavailable_pair_ids: vec![],
            selected_pair_id: None,
            reason: "missing".into(),
            candidate_evidence: ObjectRef { object_key: "fixture".into(), sha256: "a".repeat(64) },
            review_refs: vec![],
        })
        .collect();
    let own =
        inspect.modules.iter().position(|m| m.code_file.ends_with("null_read_target.exe")).unwrap();
    selections[own].state = "unique".into();
    selections[own].reason = "unique".into();
    selections[own].selected_pair_id = Some("a".repeat(64));
    selections[own].candidate_pair_ids = vec!["a".repeat(64)];
    let paths = BTreeMap::from([(own, fixture.join("null_read_target.exe"))]);
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
    let out = root.join(format!("target/qa-first-launch/system-native-{nonce}"));
    fs::create_dir_all(&out).unwrap();
    let result = unwind(
        PublicPeRequest {
            dump: &dump,
            inspect: &inspect,
            selections: &selections,
            sources: &sources,
            engine: &engine,
            raw_dir: &out,
            raw_prefix: "native-public-pe",
            deadline: Instant::now() + Duration::from_secs(30),
        },
        paths.clone(),
    )
    .unwrap();
    let ntdll = inspect
        .modules
        .iter()
        .position(|m| m.code_file.to_ascii_lowercase().ends_with("ntdll.dll"))
        .unwrap();
    assert!(result.outcomes[&ntdll].iter().any(|o| o.outcome == "found"));
    let plan = frozen_symbolicator::plan(&inspect, &result.report, &selections, &engine, &sources)
        .unwrap();
    let mut functions = Vec::new();
    let mut diagnostics = Vec::new();
    for part in plan.partitions.iter().filter(|p| p.key().starts_with("public:")) {
        let response = frozen_symbolicator::execute(&engine, part, 60).unwrap();
        assert!(response.failure.is_none(), "{response:?}");
        let collected = frozen_symbolicator::collect(
            part,
            response.response.as_ref().unwrap(),
            ObjectRef {
                object_key: format!("native-public-pe/{}", part.key()),
                sha256: "b".repeat(64),
            },
        )
        .unwrap();
        for frame in collected.frames {
            functions.push(format!("{:?}", frame.symbol));
        }
        diagnostics.push(serde_json::to_value(&response).unwrap());
    }
    assert!(functions.iter().any(|s| s.contains("BaseThreadInitThunk")), "{functions:?}");
    assert!(functions.iter().any(|s| s.contains("RtlUserThreadStart")), "{functions:?}");
    // The same warm engine must not contribute PE unwind after a conflict.
    for (index, selection) in selections.iter_mut().enumerate() {
        if index != own {
            selection.state = "conflict".into();
        }
    }
    let blocked = unwind(
        PublicPeRequest {
            dump: &dump,
            inspect: &inspect,
            selections: &selections,
            sources: &sources,
            engine: &engine,
            raw_dir: &out,
            raw_prefix: "blocked-public-pe",
            deadline: Instant::now() + Duration::from_secs(30),
        },
        paths,
    )
    .unwrap();
    assert!(blocked.outcomes.is_empty());
    fs::write(
        out.join("result.json"),
        serde_json::to_vec_pretty(&json!({
            "status": "PASS", "functions": functions, "source_responses": diagnostics,
            "public_pe_outcomes": result.outcomes, "warm_conflict_guard": true,
        }))
        .unwrap(),
    )
    .unwrap();
    println!("native public PE/PDB receipt: {}", out.display());
}
