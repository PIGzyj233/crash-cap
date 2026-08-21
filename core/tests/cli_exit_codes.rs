use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{SystemTime, UNIX_EPOCH};

const MDMP_SIGNATURE: u32 = 0x504d_444d;
const STREAM_SYSTEM_INFO: u32 = 7;

fn unique_path(label: &str, extension: &str) -> PathBuf {
    let nanos = SystemTime::now().duration_since(UNIX_EPOCH).expect("clock after epoch").as_nanos();
    std::env::temp_dir().join(format!("crash-cap-{label}-{}.{extension}", nanos))
}

fn put_u16(bytes: &mut [u8], offset: usize, value: u16) {
    bytes[offset..offset + 2].copy_from_slice(&value.to_le_bytes());
}

fn put_u32(bytes: &mut [u8], offset: usize, value: u32) {
    bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes());
}

fn minimal_x64_dump() -> Vec<u8> {
    let directory_rva = 32usize;
    let system_rva = 44usize;
    let mut bytes = vec![0; system_rva + 56];
    put_u32(&mut bytes, 0, MDMP_SIGNATURE);
    put_u32(&mut bytes, 8, 1);
    put_u32(&mut bytes, 12, directory_rva as u32);
    put_u32(&mut bytes, directory_rva, STREAM_SYSTEM_INFO);
    put_u32(&mut bytes, directory_rva + 4, 56);
    put_u32(&mut bytes, directory_rva + 8, system_rva as u32);
    put_u16(&mut bytes, system_rva, 9); // PROCESSOR_ARCHITECTURE_AMD64
    bytes[system_rva + 6] = 1;
    put_u32(&mut bytes, system_rva + 8, 10);
    put_u32(&mut bytes, system_rva + 12, 0);
    put_u32(&mut bytes, system_rva + 16, 22631);
    put_u32(&mut bytes, system_rva + 20, 2);
    bytes
}

fn run_inspect(dump: &Path, output: &Path) -> std::process::Output {
    Command::new(env!("CARGO_BIN_EXE_dmp-core"))
        .args([
            "inspect",
            "--dump",
            dump.to_str().expect("UTF-8 temp path"),
            "--output",
            output.to_str().expect("UTF-8 temp path"),
        ])
        .output()
        .expect("start dmp-core")
}

fn cleanup(paths: &[&Path]) {
    for path in paths {
        let _ = fs::remove_file(path);
    }
}

#[test]
fn version_flag_is_successful_and_script_friendly() {
    let result = Command::new(env!("CARGO_BIN_EXE_dmp-core"))
        .arg("--version")
        .output()
        .expect("start dmp-core");
    assert_eq!(result.status.code(), Some(0));
    assert_eq!(String::from_utf8_lossy(&result.stdout).trim(), "dmp-core 1.0.0");
    assert!(result.stderr.is_empty());
}

#[test]
fn inspect_accepts_minimal_x64_and_extracts_process_fields() {
    let dump = unique_path("valid", "dmp");
    let output = unique_path("valid", "json");
    fs::write(&dump, minimal_x64_dump()).expect("write dump");

    let result = run_inspect(&dump, &output);
    assert_eq!(result.status.code(), Some(0), "stderr: {:?}", result.stderr);
    let report: Value = serde_json::from_slice(&fs::read(&output).expect("read inspect output"))
        .expect("inspect JSON");
    assert_eq!(report["dump"]["kind"], "user_minidump");
    assert_eq!(report["process"]["architecture"], "x86_64");
    assert_eq!(report["process"]["os"], "windows");
    assert_eq!(report["process"]["os_version"], "10.0.22631");
    cleanup(&[&dump, &output]);
}

#[test]
fn inspect_maps_non_minidump_to_exit_code_2_and_structured_error() {
    let dump = unique_path("unsupported", "bin");
    let output = unique_path("unsupported", "json");
    fs::write(&dump, b"not a minidump").expect("write input");

    let result = run_inspect(&dump, &output);
    assert_eq!(result.status.code(), Some(2));
    let error: Value = serde_json::from_slice(&result.stderr).expect("structured stderr");
    assert_eq!(error["error"]["code"], "UNSUPPORTED_DUMP");
    cleanup(&[&dump, &output]);
}

#[test]
fn inspect_maps_truncated_minidump_to_exit_code_3() {
    let dump = unique_path("corrupt", "dmp");
    let output = unique_path("corrupt", "json");
    let mut bytes = vec![0; 32];
    put_u32(&mut bytes, 0, MDMP_SIGNATURE);
    put_u32(&mut bytes, 8, 1);
    put_u32(&mut bytes, 12, 32);
    fs::write(&dump, bytes).expect("write truncated dump");

    let result = run_inspect(&dump, &output);
    assert_eq!(result.status.code(), Some(3));
    let error: Value = serde_json::from_slice(&result.stderr).expect("structured stderr");
    assert_eq!(error["error"]["code"], "CORRUPT_DUMP");
    cleanup(&[&dump, &output]);
}

#[test]
fn inspect_maps_non_x64_minidump_to_exit_code_2() {
    let dump = unique_path("non-x64", "dmp");
    let output = unique_path("non-x64", "json");
    let mut bytes = minimal_x64_dump();
    put_u16(&mut bytes, 44, 0); // PROCESSOR_ARCHITECTURE_INTEL
    fs::write(&dump, bytes).expect("write x86 dump");

    let result = run_inspect(&dump, &output);
    assert_eq!(result.status.code(), Some(2));
    let error: Value = serde_json::from_slice(&result.stderr).expect("structured stderr");
    assert_eq!(error["error"]["code"], "UNSUPPORTED_DUMP");
    cleanup(&[&dump, &output]);
}

#[test]
fn inspect_rejects_real_wow64_fixture_without_success_output() {
    let fixture =
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../fixtures/p0-d06-non-x64/generated/dump.dmp");
    if !fixture.is_file() {
        // Generated fixture binaries are optional in a source-only checkout;
        // minidump's unconditional detector test still covers the rule.
        return;
    }
    let output = unique_path("real-wow64", "json");
    let result = run_inspect(&fixture, &output);
    assert_eq!(result.status.code(), Some(2));
    let error: Value = serde_json::from_slice(&result.stderr).expect("structured stderr");
    assert_eq!(error["error"]["code"], "UNSUPPORTED_DUMP");
    assert!(error["error"]["message"].as_str().unwrap_or_default().contains("WOW64"));
    assert!(!output.exists(), "unsupported inspect must not emit a success report");
    cleanup(&[&output]);
}

#[test]
fn inspect_maps_non_windows_platform_to_exit_code_2() {
    let dump = unique_path("non-windows-platform", "dmp");
    let output = unique_path("non-windows-platform", "json");
    let mut bytes = minimal_x64_dump();
    put_u32(&mut bytes, 64, 0x8201); // Breakpad Linux platform id
    fs::write(&dump, bytes).expect("write Linux-platform dump");

    let result = run_inspect(&dump, &output);
    assert_eq!(result.status.code(), Some(2));
    let error: Value = serde_json::from_slice(&result.stderr).expect("structured stderr");
    assert_eq!(error["error"]["code"], "UNSUPPORTED_DUMP");
    cleanup(&[&dump, &output]);
}

#[test]
fn inspect_rejects_oversized_sparse_input_before_reading() {
    let dump = unique_path("oversized", "dmp");
    let output = unique_path("oversized", "json");
    let file = fs::File::create(&dump).expect("create sparse dump");
    file.set_len(256 * 1024 * 1024 + 1).expect("extend sparse dump");

    let result = run_inspect(&dump, &output);
    assert_eq!(result.status.code(), Some(2));
    let error: Value = serde_json::from_slice(&result.stderr).expect("structured stderr");
    assert_eq!(error["error"]["code"], "INPUT_TOO_LARGE");
    assert_eq!(error["error"]["details"]["size"], 256 * 1024 * 1024 + 1);
    assert!(!String::from_utf8_lossy(&result.stderr).contains("MDMP"));
    cleanup(&[&dump, &output]);
}

#[test]
fn analyze_writes_canonical_and_raw_outputs() {
    let dump = unique_path("analyze", "dmp");
    let output = unique_path("analyze", "json");
    let raw_dir = unique_path("analyze-raw", "dir");
    fs::write(&dump, minimal_x64_dump()).expect("write dump");

    let result = Command::new(env!("CARGO_BIN_EXE_dmp-core"))
        .args([
            "analyze",
            "--dump",
            dump.to_str().expect("UTF-8 temp path"),
            "--output",
            output.to_str().expect("UTF-8 temp path"),
            "--raw-dir",
            raw_dir.to_str().expect("UTF-8 temp path"),
        ])
        .output()
        .expect("start dmp-core");
    assert_eq!(result.status.code(), Some(0), "stderr: {:?}", result.stderr);
    let canonical: Value = serde_json::from_slice(&fs::read(&output).expect("read canonical"))
        .expect("canonical JSON");
    assert_eq!(canonical["schema_version"], "1.0");
    assert_eq!(canonical["process"]["architecture"], "x86_64");
    assert!(raw_dir.join("inspect.json").is_file());
    assert!(raw_dir.join("minidump.json").is_file());
    cleanup(&[&dump, &output]);
    let _ = fs::remove_dir_all(&raw_dir);
}
