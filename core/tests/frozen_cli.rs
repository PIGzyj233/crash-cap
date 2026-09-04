//! Real subprocess and source qualification; isolated services are script-owned.
use dmp_core::canonical::sha256_hex;
use serde_json::{json, Value};
use std::fs;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::time::{SystemTime, UNIX_EPOCH};

fn read(path: &Path) -> Value {
    serde_json::from_slice(&fs::read(path).unwrap()).unwrap()
}
fn invoke(args: &[String]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_dmp-core")).args(args).output().unwrap()
}
fn failed(output: Output, code: &str) {
    assert!(!output.status.success());
    let value: Value = serde_json::from_slice(&output.stderr).expect("structured CLI error");
    assert_eq!(value["error"]["code"], code, "{value}");
}

#[test]
fn frozen_process_requires_explicit_opt_in_before_opening_inputs() {
    let output = invoke(
        &[
            "analyze-frozen",
            "--dump",
            "absent.dmp",
            "--inspect",
            "absent-inspect.json",
            "--run",
            "absent-run.json",
            "--resolution-manifest",
            "absent-manifest.json",
            "--execution",
            "absent-execution.json",
            "--symbolicator",
            "http://127.0.0.1:1",
            "--pair-source-root",
            "http://127.0.0.1:1",
            "--output-dir",
            "must-not-create",
            "--raw-object-prefix",
            "qualification/test",
        ]
        .map(str::to_owned),
    );
    failed(output, "FROZEN_WRITER_DISABLED");
}

#[test]
#[ignore = "requires isolated pinned service, full frozen Run and actual MSVC pair"]
fn frozen_cli_executes_sealed_run_and_retains_failure_evidence() {
    let endpoint = std::env::var("QAI_NATIVE_SOURCE_ENDPOINT").unwrap();
    let source_root = std::env::var("QAI_NATIVE_SOURCE_ROOT").unwrap();
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).parent().unwrap().to_path_buf();
    let fixture = root.join("fixtures/p0-b01-null-read/generated");
    let baseline = root.join("target/qa-symbol-import/frozen-context");
    let native = root.join("target/qa-symbol-import/native-source");
    let id = format!(
        "{}-{}",
        std::process::id(),
        SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()
    );
    let output_root = native.join(format!("cli-{id}"));
    fs::create_dir(&output_root).unwrap();
    let metadata = read(&baseline.join("qualification.json"));
    let pair = metadata["pair_id"].as_str().unwrap();
    let execution = json!({"schema_version":"frozen-execution-v1",
        "assignment":{"run_id":"run_frozen_context","occurrence_id":"occ_fixture","workspace_id":"wsp_fixture","object_sha256":metadata["run_sha256"]},
        "engines":{"core_image_digest":format!("sha256:{}","0".repeat(64)),"symbolicator_image_digest":std::env::var("QAI_NATIVE_SOURCE_IMAGE_DIGEST").unwrap(),"symbolicator_version":std::env::var("QAI_NATIVE_SOURCE_VERSION").unwrap()},
        "pairs":{pair:{"pe":fixture.join("null_read_target.exe"),"pdb":fixture.join("null_read_target.pdb")}}});
    let execution_path = output_root.join("execution.json");
    fs::write(&execution_path, serde_json::to_vec_pretty(&execution).unwrap()).unwrap();
    let prefix = format!("qualification/cli/{id}");
    let args = |output: &str, descriptor: &Path, engine: &str| {
        vec![
            "analyze-frozen".to_owned(),
            "--enable-frozen-v11".to_owned(),
            "--allow-local-core-sentinel".to_owned(),
            "--dump".to_owned(),
            fixture.join("null-read.dmp").display().to_string(),
            "--inspect".to_owned(),
            baseline.join("inspect.json").display().to_string(),
            "--run".to_owned(),
            baseline.join("run.json").display().to_string(),
            "--resolution-manifest".to_owned(),
            baseline.join("manifest.json").display().to_string(),
            "--execution".to_owned(),
            descriptor.display().to_string(),
            "--symbolicator".to_owned(),
            engine.to_owned(),
            "--pair-source-root".to_owned(),
            source_root.clone(),
            "--output-dir".to_owned(),
            output_root.join(output).display().to_string(),
            "--raw-object-prefix".to_owned(),
            format!("{prefix}/{output}"),
        ]
    };
    let mut no_sentinel = args("no-sentinel", &execution_path, &endpoint);
    no_sentinel.retain(|a| a != "--allow-local-core-sentinel");
    failed(invoke(&no_sentinel), "INVALID_FROZEN_EVIDENCE");
    assert!(!output_root.join("no-sentinel").exists());
    let mut changed = execution.clone();
    changed["assignment"]["object_sha256"] = json!("1".repeat(64));
    let changed_path = output_root.join("changed-execution.json");
    fs::write(&changed_path, serde_json::to_vec(&changed).unwrap()).unwrap();
    failed(invoke(&args("bad-seal", &changed_path, &endpoint)), "INVALID_FROZEN_EVIDENCE");
    assert!(!output_root.join("bad-seal").exists());
    changed = execution.clone();
    changed["pairs"][pair]["pdb"] = json!(baseline.join("changed-same-identity.pdb"));
    fs::write(&changed_path, serde_json::to_vec(&changed).unwrap()).unwrap();
    failed(invoke(&args("bad-pair", &changed_path, &endpoint)), "INVALID_FROZEN_EVIDENCE");
    assert!(output_root.join("bad-pair/failure.json").exists());
    assert!(!output_root.join("bad-pair/canonical.json").exists());
    let command = args("success", &execution_path, &endpoint);
    let success = invoke(&command);
    assert!(success.status.success(), "{}", String::from_utf8_lossy(&success.stderr));
    let canonical_path = output_root.join("success/canonical.json");
    let canonical = read(&canonical_path);
    assert_eq!(canonical["schema_version"], "1.1");
    assert_eq!(canonical["analysis_id"], "run_frozen_context");
    assert_eq!(canonical["build_resolution"]["resolved_build_id"], "bld_fixture");
    assert!(canonical["threads"]
        .as_array()
        .unwrap()
        .iter()
        .flat_map(|t| t["frames"].as_array().unwrap())
        .any(|f| f["function"].as_str().is_some_and(|s| s.contains("trigger_null_read"))
            && f["line"] == 76));
    let mut diagnostics = 0;
    for module in canonical["modules"].as_array().unwrap() {
        for outcome in module["source_outcomes"].as_array().unwrap() {
            if let Some(reference) = outcome.get("diagnostic_ref").filter(|r| !r.is_null()) {
                let relative = reference["object_key"]
                    .as_str()
                    .unwrap()
                    .strip_prefix(&format!("{prefix}/success/"))
                    .unwrap();
                assert_eq!(
                    reference["sha256"],
                    sha256_hex(&fs::read(output_root.join("success").join(relative)).unwrap())
                );
                diagnostics += 1;
            }
        }
    }
    assert!(diagnostics > 0);
    let canonical_sha = sha256_hex(&fs::read(&canonical_path).unwrap());
    failed(invoke(&command), "IO_ERROR");
    assert_eq!(sha256_hex(&fs::read(&canonical_path).unwrap()), canonical_sha);
    assert!(!output_root.join("success/failure.json").exists());
    // A transport failure retains exactly attributable raw evidence and cannot
    // produce a success-shaped Canonical or silently switch sources.
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let failing_endpoint = format!("http://{}", listener.local_addr().unwrap());
    let server = std::thread::spawn(move || {
        let (mut stream, _) = listener.accept().unwrap();
        stream.set_read_timeout(Some(std::time::Duration::from_secs(10))).unwrap();
        let mut request = [0; 65536];
        let count = stream.read(&mut request).unwrap();
        assert!(String::from_utf8_lossy(&request[..count]).starts_with("POST /symbolicate"));
        stream.write_all(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").unwrap();
    });
    failed(
        invoke(&args("http-failure", &execution_path, &failing_endpoint)),
        "FROZEN_SOURCE_FAILED",
    );
    server.join().unwrap();
    assert!(!output_root.join("http-failure/canonical.json").exists());
    let transport = read(&output_root.join("http-failure/raw/source-0-transport.json"));
    assert_eq!(transport["attempts"][0]["status"], 503);
    assert_eq!(transport["failure"], "http_503");
    let receipt = json!({"status":"PASS","run_sha256":metadata["run_sha256"],"command":command,
        "output_root":output_root,"canonical_sha256":canonical_sha,"diagnostic_refs_verified":diagnostics,
        "controls":["sentinel_opt_in","assignment_seal","same_identity_changed_pair_bytes","real_symbol_function_line","raw_reference_hashes","exclusive_output_replay","http_503_retains_raw_no_canonical"],
        "not_proven":["Worker integration","catalog/planner","source bundle enrichment","production enablement"]});
    fs::write(native.join("cli-qualification.json"), serde_json::to_vec_pretty(&receipt).unwrap())
        .unwrap();
}
