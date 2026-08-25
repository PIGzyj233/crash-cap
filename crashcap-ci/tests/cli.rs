use std::io::{Read, Write};
use std::net::TcpListener;
use std::process::Command;
use std::thread;

#[test]
fn help_and_version_exit_successfully_with_unified_name() {
    let binary = env!("CARGO_BIN_EXE_crashcap");
    for argument in ["--help", "--version"] {
        let output = Command::new(binary).arg(argument).output().expect("run binary");
        assert!(output.status.success(), "{argument} failed");
        let stdout = String::from_utf8(output.stdout).expect("UTF-8 stdout");
        assert!(stdout.contains("crashcap"));
        assert!(!stdout.contains("crashcap-ci"));
    }
}

#[test]
fn missing_subcommand_exits_two() {
    let output = Command::new(env!("CARGO_BIN_EXE_crashcap")).output().expect("run binary");
    assert_eq!(output.status.code(), Some(2));
}

#[test]
fn json_error_boundary_redacts_api_secrets() {
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

    let output = Command::new(env!("CARGO_BIN_EXE_crashcap"))
        .args([
            "--json",
            "--api-url",
            &format!("http://{address}/api/v1"),
            "doctor",
            "--workspace",
            "test",
        ])
        .output()
        .expect("run binary");
    server.join().expect("join server");

    assert_eq!(output.status.code(), Some(2));
    assert!(output.stdout.is_empty());
    let stderr = String::from_utf8(output.stderr).expect("UTF-8 stderr");
    assert!(!stderr.contains("SUPER_SECRET_SENTINEL"), "stderr: {stderr}");
    assert!(stderr.contains("[REDACTED_URL]"), "stderr: {stderr}");
    assert!(stderr.contains("token=[REDACTED]"), "stderr: {stderr}");
    assert!(stderr.contains("\"code\": \"CLI_ERROR\""));
}
