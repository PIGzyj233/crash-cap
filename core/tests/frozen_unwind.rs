//! Explicit real-fixture S1 lane; not silently counted when fixture bytes are absent.

use dmp_core::unwind::unwind_bytes_with_selected_modules;
use std::collections::BTreeMap;
use std::path::PathBuf;

#[test]
#[ignore = "requires generated MSVC p0-b01 fixture; run explicit QAI qualification lane"]
fn only_frozen_module_instances_supply_pe_unwind() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    let fixture = root.join("fixtures/p0-b01-null-read/generated");
    let dump =
        std::fs::read(fixture.join("null-read.dmp")).expect("generate real MSVC fixture first");
    let pe = fixture.join("null_read_target.exe");
    assert!(pe.is_file());
    let pe_sha256 = dmp_core::canonical::sha256_hex(&std::fs::read(&pe).unwrap());
    let dump_sha256 = dmp_core::canonical::sha256_hex(&dump);
    let inspect = dmp_core::minidump::inspect_bytes(&dump).unwrap();
    let index =
        inspect.modules.iter().position(|m| m.code_file.ends_with("null_read_target.exe")).unwrap();
    let blocked = unwind_bytes_with_selected_modules(&dump, &BTreeMap::new()).unwrap();
    let selected =
        unwind_bytes_with_selected_modules(&dump, &BTreeMap::from([(index, pe)])).unwrap();
    let methods = |report: &dmp_core::unwind::UnwindReport| {
        report
            .threads
            .iter()
            .flat_map(|t| t.frames.iter())
            .filter_map(|f| f.unwind_method.clone())
            .collect::<Vec<_>>()
    };
    assert!(!methods(&blocked).iter().any(|m| m == "call_frame_info" || m == "cfi_scan"));
    assert!(methods(&selected).iter().any(|m| m == "call_frame_info"));
    assert!(unwind_bytes_with_selected_modules(&dump, &BTreeMap::from([(usize::MAX, fixture)]))
        .is_err());
    let output = root.join("target/qa-symbol-import/frozen-unwind.json");
    std::fs::create_dir_all(output.parent().unwrap()).unwrap();
    std::fs::write(output, serde_json::to_vec_pretty(&serde_json::json!({
        "schema_version": "qai-frozen-unwind-v1", "status": "PASS", "module_index": index,
        "dump_sha256": dump_sha256, "pe_sha256": pe_sha256,
        "core_version": env!("CARGO_PKG_VERSION"),
        "selected": selected, "blocked": blocked,
        "scope": "real MSVC fixture with producer-local PE reachable; explicit selected provider only"
    })).unwrap()).unwrap();
}
