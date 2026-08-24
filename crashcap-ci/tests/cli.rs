use std::fs;
use std::io::{Read, Write};
use std::net::TcpListener;
use std::process::Command;
use std::thread;

use tempfile::tempdir;

#[test]
fn help_and_version_exit_successfully() {
    let binary = env!("CARGO_BIN_EXE_crashcap-ci");
    for argument in ["--help", "--version"] {
        let output = Command::new(binary).arg(argument).output().expect("run binary");
        assert!(output.status.success(), "{argument} failed");
    }
}

#[test]
fn missing_required_arguments_exit_two() {
    let output = Command::new(env!("CARGO_BIN_EXE_crashcap-ci")).output().expect("run binary");
    assert_eq!(output.status.code(), Some(2));
}

#[test]
fn final_stderr_boundary_redacts_api_secrets_and_keeps_stdout_empty() {
    let directory = tempdir().expect("temporary directory");
    let artifact_root = directory.path().join("artifacts");
    fs::create_dir(&artifact_root).expect("create artifacts");
    fs::write(artifact_root.join("target.exe"), b"pe").expect("write PE");
    fs::write(artifact_root.join("target.pdb"), b"pdb").expect("write PDB");
    let manifest = directory.path().join("build-manifest.json");
    fs::write(&manifest, include_str!("fixtures/build-manifest-v1.json")).expect("write manifest");

    let listener = TcpListener::bind("127.0.0.1:0").expect("bind mock API");
    let address = listener.local_addr().expect("mock address");
    let server = thread::spawn(move || {
        let (mut stream, _) = listener.accept().expect("accept request");
        let mut buffer = [0_u8; 4096];
        let _ = stream.read(&mut buffer).expect("read request");
        let body = r#"{"error":{"code":"BAD_TOKEN","message":"upload https://store/object?X-Amz-Credential=SUPER_SECRET_SENTINEL&X-Amz-Signature=SUPER_SECRET_SENTINEL token=SUPER_SECRET_SENTINEL"}}"#;
        write!(
            stream,
            "HTTP/1.1 400 Bad Request\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        )
        .expect("write response");
    });

    let output = Command::new(env!("CARGO_BIN_EXE_crashcap-ci"))
        .args([
            "--api-url",
            &format!("http://{address}/api/v1"),
            "--workspace",
            "test",
            "--manifest",
        ])
        .arg(&manifest)
        .arg("--artifact-root")
        .arg(&artifact_root)
        .args(["--producer-build-id", "pipeline-1"])
        .output()
        .expect("run binary");
    server.join().expect("join server");

    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    let stderr = String::from_utf8(output.stderr).expect("UTF-8 stderr");
    assert!(!stderr.contains("SUPER_SECRET_SENTINEL"), "stderr: {stderr}");
    assert!(stderr.contains("[REDACTED_URL]"), "stderr: {stderr}");
    assert!(stderr.contains("token=[REDACTED]"), "stderr: {stderr}");
}
