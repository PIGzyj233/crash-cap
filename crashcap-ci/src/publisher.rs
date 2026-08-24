use std::collections::HashMap;
use std::path::Path;
use std::thread;
use std::time::{Duration, Instant};

use reqwest::Method;
use serde::Deserialize;
use serde_json::{json, Value};

use crate::cli::ResolvedArgs;
use crate::error::{PublishError, Result};
use crate::http::ApiClient;
use crate::manifest::{LoadedManifest, PreparedArtifact};

const DEFAULT_PART_SIZE: u64 = 64 * 1024 * 1024;

#[derive(Debug, Deserialize)]
struct UploadInit {
    upload_id: String,
    #[serde(default)]
    method: String,
    #[serde(default)]
    url: String,
    #[serde(default)]
    headers: HashMap<String, String>,
    multipart: Option<MultipartInit>,
}

#[derive(Debug, Deserialize)]
struct MultipartInit {
    upload_id: String,
    part_size: Option<u64>,
    parts: Vec<MultipartPart>,
}

#[derive(Debug, Deserialize)]
struct MultipartPart {
    part_number: u32,
    url: String,
}

pub struct Publisher<'a> {
    api: &'a ApiClient,
    poll_interval: Duration,
}

impl<'a> Publisher<'a> {
    pub fn new(api: &'a ApiClient) -> Self {
        Self { api, poll_interval: Duration::from_secs(1) }
    }

    #[cfg(test)]
    fn with_poll_interval(api: &'a ApiClient, poll_interval: Duration) -> Self {
        Self { api, poll_interval }
    }

    pub fn publish(
        &self,
        args: &ResolvedArgs,
        manifest: &LoadedManifest,
        artifacts: &[PreparedArtifact],
    ) -> Result<Value> {
        let workspace_id = self.workspace_id(&args.workspace)?;
        self.validate_producer(args.producer.as_str(), args.allow_experimental)?;
        let create_body = json!({
            "version": manifest.manifest.version,
            "build_number": manifest.manifest.build_number,
            "commit_sha": manifest.manifest.commit,
            "channel": manifest.manifest.channel,
            "architecture": manifest.manifest.architecture,
            "toolchain": manifest.manifest.toolchain,
            "producer": args.producer.as_str(),
            "producer_build_id": args.producer_build_id,
        });
        let build = self.api.request_value(
            Method::POST,
            &format!("/workspaces/{workspace_id}/builds"),
            Some(&create_body),
        )?;
        let build_id = required_string(&build, "id", "Build response")?;
        let build = self.api.request_value(
            Method::PUT,
            &format!("/builds/{build_id}/manifest"),
            Some(&manifest.raw),
        )?;

        let mut uploaded = Vec::new();
        for artifact in artifacts {
            if is_already_verified(&build, artifact) {
                uploaded.push(json!({
                    "kind": artifact.kind.as_str(),
                    "path": artifact.path.display().to_string(),
                    "status": "already_verified",
                }));
                continue;
            }
            self.upload(&build_id, artifact, args.wait_seconds)?;
            uploaded.push(json!({
                "kind": artifact.kind.as_str(),
                "path": artifact.path.display().to_string(),
                "status": "uploaded",
            }));
        }

        let status = self.wait_for_build(&build_id, args.wait_seconds)?;
        Ok(json!({
            "workspace_id": workspace_id,
            "build_id": build_id,
            "ci_status": status,
            "artifacts": uploaded,
        }))
    }

    fn workspace_id(&self, requested: &str) -> Result<String> {
        let rows = self.api.request_value(Method::GET, "/workspaces", None)?;
        let rows = rows.as_array().ok_or_else(|| {
            PublishError::message("API GET /workspaces returned an invalid response")
        })?;
        let matches = rows
            .iter()
            .filter(|row| {
                row.get("id").and_then(Value::as_str) == Some(requested)
                    || row.get("name").and_then(Value::as_str) == Some(requested)
            })
            .collect::<Vec<_>>();
        if matches.len() != 1 {
            return Err(PublishError::message(format!(
                "Workspace {requested:?} must resolve uniquely; found {}",
                matches.len()
            )));
        }
        required_string(matches[0], "id", "Workspace response")
    }

    fn validate_producer(&self, producer: &str, allow_experimental: bool) -> Result<()> {
        let rows = self.api.request_value(Method::GET, "/ci/producers", None)?;
        let rows = rows.as_array().ok_or_else(|| {
            PublishError::message("API GET /ci/producers returned an invalid response")
        })?;
        let row = rows
            .iter()
            .find(|row| row.get("producer").and_then(Value::as_str) == Some(producer))
            .ok_or_else(|| PublishError::message(format!("unknown CI producer: {producer}")))?;
        let status = required_string(row, "status", "CI producer response")?;
        if status != "supported" && !allow_experimental {
            return Err(PublishError::message(format!(
                "producer {producer} is {status}; use --allow-experimental only for qualification"
            )));
        }
        Ok(())
    }

    fn upload(&self, build_id: &str, artifact: &PreparedArtifact, wait_seconds: u64) -> Result<()> {
        let body = json!({
            "file_kind": artifact.kind.as_str(),
            "filename": file_name(&artifact.path)?,
            "size": artifact.size,
            "sha256": artifact.sha256,
        });
        let initialized = self.api.request_value(
            Method::POST,
            &format!("/builds/{build_id}/artifacts/uploads:init"),
            Some(&body),
        )?;
        let initialized: UploadInit = serde_json::from_value(initialized).map_err(|_| {
            PublishError::message("artifact upload initialization returned an invalid response")
        })?;
        if !initialized.method.eq_ignore_ascii_case("PUT") {
            return Err(PublishError::message("artifact upload initialization did not return PUT"));
        }

        let (multipart_upload_id, completed_parts) = match initialized.multipart {
            Some(multipart) => {
                let parts = self.upload_multipart(&initialized.headers, artifact, &multipart)?;
                (Some(multipart.upload_id), parts)
            }
            None => {
                if initialized.url.is_empty() {
                    return Err(PublishError::message(
                        "artifact upload initialization returned no URL",
                    ));
                }
                self.api.put_file_range(
                    &initialized.url,
                    &initialized.headers,
                    &artifact.path,
                    0,
                    artifact.size,
                    None,
                )?;
                (None, Vec::new())
            }
        };
        let completion = json!({
            "multipart_upload_id": multipart_upload_id,
            "parts": completed_parts,
        });
        self.api.request_value(
            Method::POST,
            &format!("/uploads/{}/complete", initialized.upload_id),
            Some(&completion),
        )?;
        self.wait_for_upload(&initialized.upload_id, wait_seconds)
    }

    fn upload_multipart(
        &self,
        headers: &HashMap<String, String>,
        artifact: &PreparedArtifact,
        multipart: &MultipartInit,
    ) -> Result<Vec<Value>> {
        let part_size = multipart.part_size.unwrap_or(DEFAULT_PART_SIZE);
        if part_size == 0 {
            return Err(PublishError::message("multipart upload returned an invalid part_size"));
        }
        let expected_count = artifact.size.div_ceil(part_size);
        if multipart.parts.len() as u64 != expected_count {
            return Err(PublishError::message(format!(
                "multipart upload returned {} parts; expected {expected_count}",
                multipart.parts.len()
            )));
        }
        let mut result = Vec::with_capacity(multipart.parts.len());
        for (index, part) in multipart.parts.iter().enumerate() {
            let expected_number = u32::try_from(index + 1)
                .map_err(|_| PublishError::message("multipart part number overflow"))?;
            if part.part_number != expected_number {
                return Err(PublishError::message(
                    "multipart upload returned non-contiguous part numbers",
                ));
            }
            let offset = u64::from(part.part_number - 1) * part_size;
            let length = (artifact.size - offset).min(part_size);
            let etag = self
                .api
                .put_file_range(
                    &part.url,
                    headers,
                    &artifact.path,
                    offset,
                    length,
                    Some(part.part_number),
                )?
                .ok_or_else(|| {
                    PublishError::message(format!(
                        "multipart upload part {} returned no ETag",
                        part.part_number
                    ))
                })?;
            result.push(json!({"part_number": part.part_number, "etag": etag}));
        }
        Ok(result)
    }

    fn wait_for_upload(&self, upload_id: &str, wait_seconds: u64) -> Result<()> {
        let deadline = Instant::now() + Duration::from_secs(wait_seconds);
        loop {
            let upload =
                self.api.request_value(Method::GET, &format!("/uploads/{upload_id}"), None)?;
            let status = required_string(&upload, "verification_status", "Upload response")?
                .to_ascii_uppercase();
            if matches!(status.as_str(), "ACCEPTED" | "REJECTED" | "QUARANTINED") {
                if status == "ACCEPTED" {
                    return Ok(());
                }
                return Err(PublishError::message(format!("artifact upload ended in {status}")));
            }
            if Instant::now() >= deadline {
                return Err(PublishError::message(format!(
                    "timed out waiting for upload {upload_id}"
                )));
            }
            thread::sleep(self.poll_interval);
        }
    }

    fn wait_for_build(&self, build_id: &str, wait_seconds: u64) -> Result<Value> {
        let deadline = Instant::now() + Duration::from_secs(wait_seconds);
        loop {
            let status = self.api.request_value(
                Method::GET,
                &format!("/builds/{build_id}/ci-status"),
                None,
            )?;
            if status.get("ready").and_then(Value::as_bool) == Some(true) {
                return Ok(status);
            }
            let rejected =
                status.get("rejected_artifacts").and_then(Value::as_array).ok_or_else(|| {
                    PublishError::message("Build CI status returned an invalid response")
                })?;
            if !rejected.is_empty() {
                return Err(PublishError::message(format!(
                    "Build verification rejected artifacts: {}",
                    Value::Array(rejected.clone())
                )));
            }
            if Instant::now() >= deadline {
                return Err(PublishError::message(
                    "timed out waiting for complete CI Build verification",
                ));
            }
            thread::sleep(self.poll_interval);
        }
    }
}

fn is_already_verified(build: &Value, artifact: &PreparedArtifact) -> bool {
    build.get("artifacts").and_then(Value::as_array).into_iter().flatten().any(|item| {
        item.get("kind").and_then(Value::as_str) == Some(artifact.kind.as_str())
            && item.get("logical_name").and_then(Value::as_str).is_some_and(|name| {
                file_name(&artifact.path).is_ok_and(|expected| name.eq_ignore_ascii_case(expected))
            })
            && item
                .get("sha256")
                .and_then(Value::as_str)
                .is_some_and(|digest| digest.eq_ignore_ascii_case(&artifact.sha256))
            && item.get("verification_status").and_then(Value::as_str) == Some("verified")
    })
}

fn file_name(path: &Path) -> Result<&str> {
    path.file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| PublishError::message("artifact filename is not valid UTF-8"))
}

fn required_string(value: &Value, field: &str, label: &str) -> Result<String> {
    value
        .get(field)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| PublishError::message(format!("{label} is missing {field}")))
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::sync::{Arc, Mutex};
    use std::thread;
    use std::time::Duration;

    use serde_json::{json, Value};
    use tempfile::tempdir;

    use crate::cli::{Producer, ResolvedArgs};
    use crate::http::ApiClient;
    use crate::manifest::{load_manifest, prepare_artifacts, required_artifacts};

    use super::Publisher;

    #[derive(Debug)]
    struct RequestRecord {
        method: String,
        path: String,
        body: Vec<u8>,
    }

    fn read_request(mut stream: &TcpStream) -> RequestRecord {
        let mut data = Vec::new();
        let mut buffer = [0_u8; 4096];
        let header_end;
        loop {
            let count = stream.read(&mut buffer).expect("read request");
            assert!(count > 0, "request ended before headers");
            data.extend_from_slice(&buffer[..count]);
            if let Some(position) = data.windows(4).position(|window| window == b"\r\n\r\n") {
                header_end = position + 4;
                break;
            }
        }
        let headers = String::from_utf8_lossy(&data[..header_end]);
        let first = headers.lines().next().expect("request line");
        let mut request_line = first.split_whitespace();
        let method = request_line.next().expect("method").to_owned();
        let path = request_line.next().expect("path").to_owned();
        let content_length = headers
            .lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse::<usize>().expect("content length"))
            })
            .unwrap_or(0);
        while data.len() - header_end < content_length {
            let count = stream.read(&mut buffer).expect("read request body");
            assert!(count > 0, "request body ended early");
            data.extend_from_slice(&buffer[..count]);
        }
        RequestRecord { method, path, body: data[header_end..header_end + content_length].to_vec() }
    }

    fn respond(mut stream: TcpStream, status: u16, body: &Value, etag: Option<&str>) {
        let payload = body.to_string();
        let etag_header = etag.map(|value| format!("ETag: {value}\r\n")).unwrap_or_default();
        write!(
            stream,
            "HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\n{etag_header}Content-Length: {}\r\nConnection: close\r\n\r\n{payload}",
            payload.len()
        )
        .expect("write response");
    }

    fn single_response_error<T, F>(expected_path: &str, body: Value, action: F) -> String
    where
        F: FnOnce(&ApiClient) -> crate::error::Result<T>,
    {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind server");
        let address = listener.local_addr().expect("server address");
        let expected_path = expected_path.to_owned();
        let server = thread::spawn(move || {
            let (stream, _) = listener.accept().expect("accept request");
            let request = read_request(&stream);
            assert_eq!(request.method, "GET");
            assert_eq!(request.path, expected_path);
            respond(stream, 200, &body, None);
        });
        let api = ApiClient::with_retry_base(&format!("http://{address}/api/v1"), Duration::ZERO)
            .expect("API client");
        let error = match action(&api) {
            Ok(_) => panic!("action must fail"),
            Err(error) => error.to_string(),
        };
        server.join().expect("join server");
        error
    }

    #[test]
    fn publishes_single_put_and_multipart_artifacts() {
        let directory = tempdir().expect("temporary directory");
        let root = directory.path().join("package");
        fs::create_dir_all(&root).expect("create package");
        fs::write(root.join("app.exe"), b"12345678").expect("write PE");
        fs::write(root.join("app.pdb"), b"abcdefgh").expect("write PDB");
        let manifest_path = root.join("build-manifest.json");
        fs::write(
            &manifest_path,
            json!({
                "schema_version": "1.0",
                "product": "Publisher Test",
                "version": "1.0.0",
                "architecture": "x86_64",
                "compiler": "msvc",
                "modules": [{
                    "code_file": "app.exe",
                    "debug_file": "app.pdb",
                    "role": "entrypoint"
                }]
            })
            .to_string(),
        )
        .expect("write manifest");
        let loaded = load_manifest(&manifest_path).expect("load manifest");
        let artifacts = prepare_artifacts(
            required_artifacts(&loaded.manifest, &root).expect("required artifacts"),
        )
        .expect("prepare artifacts");

        let listener = TcpListener::bind("127.0.0.1:0").expect("bind server");
        let address = listener.local_addr().expect("server address");
        let base = format!("http://{address}");
        let records = Arc::new(Mutex::new(Vec::new()));
        let server_records = Arc::clone(&records);
        let server_base = base.clone();
        let server = thread::spawn(move || {
            let mut upload_index = 0_u32;
            for stream in listener.incoming() {
                let stream = stream.expect("accept request");
                let request = read_request(&stream);
                let response = match (request.method.as_str(), request.path.as_str()) {
                    ("GET", "/api/v1/workspaces") => {
                        (200, json!([{"id": "wsp_test", "name": "ci"}]), None)
                    }
                    ("GET", "/api/v1/ci/producers") => {
                        (200, json!([{"producer": "msvc", "status": "supported"}]), None)
                    }
                    ("POST", "/api/v1/workspaces/wsp_test/builds") => {
                        (201, json!({"id": "bld_test", "artifacts": []}), None)
                    }
                    ("PUT", "/api/v1/builds/bld_test/manifest") => {
                        (200, json!({"id": "bld_test", "artifacts": []}), None)
                    }
                    ("POST", "/api/v1/builds/bld_test/artifacts/uploads:init") => {
                        upload_index += 1;
                        let upload_id = format!("upl_{upload_index}");
                        if upload_index == 1 {
                            (
                                201,
                                json!({
                                    "upload_id": upload_id,
                                    "method": "PUT",
                                    "url": format!("{server_base}/object/{upload_index}/single"),
                                    "headers": {"Content-Type": "application/octet-stream"}
                                }),
                                None,
                            )
                        } else {
                            (
                                201,
                                json!({
                                    "upload_id": upload_id,
                                    "method": "PUT",
                                    "url": "",
                                    "headers": {"Content-Type": "application/octet-stream"},
                                    "multipart": {
                                        "upload_id": format!("s3_{upload_index}"),
                                        "part_size": 5,
                                        "parts": [
                                            {"part_number": 1, "url": format!("{server_base}/object/{upload_index}/1")},
                                            {"part_number": 2, "url": format!("{server_base}/object/{upload_index}/2")}
                                        ]
                                    }
                                }),
                                None,
                            )
                        }
                    }
                    ("PUT", path) if path.starts_with("/object/") => {
                        let part = path.rsplit('/').next().expect("part number");
                        let etag = match part {
                            "1" => Some("etag-1"),
                            "2" => Some("etag-2"),
                            _ => None,
                        };
                        (200, json!({}), etag)
                    }
                    ("POST", path)
                        if path.starts_with("/api/v1/uploads/") && path.ends_with("/complete") =>
                    {
                        (200, json!({"verification_status": "VERIFYING"}), None)
                    }
                    ("GET", path) if path.starts_with("/api/v1/uploads/") => {
                        (200, json!({"verification_status": "ACCEPTED"}), None)
                    }
                    ("GET", "/api/v1/builds/bld_test/ci-status") => {
                        (200, json!({"ready": true, "rejected_artifacts": []}), None)
                    }
                    _ => panic!("unexpected request: {request:?}"),
                };
                let should_stop = request.path == "/api/v1/builds/bld_test/ci-status";
                server_records.lock().expect("records").push(request);
                respond(stream, response.0, &response.1, response.2);
                if should_stop {
                    break;
                }
            }
        });

        let api = ApiClient::with_retry_base(&format!("{base}/api/v1"), Duration::ZERO)
            .expect("API client");
        let publisher = Publisher::with_poll_interval(&api, Duration::ZERO);
        let args = ResolvedArgs {
            api_url: format!("{base}/api/v1"),
            workspace: "ci".to_owned(),
            manifest: manifest_path,
            artifact_root: root,
            producer: Producer::Msvc,
            producer_build_id: "pipeline-42".to_owned(),
            allow_experimental: false,
            wait_seconds: 1,
        };
        let result = publisher.publish(&args, &loaded, &artifacts).expect("publish succeeds");
        assert_eq!(result["build_id"], "bld_test");
        assert_eq!(result["artifacts"].as_array().expect("artifacts").len(), 2);
        server.join().expect("join server");

        let records = records.lock().expect("records");
        let object_bodies = records
            .iter()
            .filter(|request| request.path.starts_with("/object/"))
            .map(|request| request.body.clone())
            .collect::<Vec<_>>();
        assert_eq!(object_bodies, vec![b"12345678".to_vec(), b"abcde".to_vec(), b"fgh".to_vec()]);
        let completions = records
            .iter()
            .filter(|request| request.path.ends_with("/complete"))
            .map(|request| serde_json::from_slice::<Value>(&request.body).expect("completion JSON"))
            .collect::<Vec<_>>();
        assert_eq!(completions.len(), 2);
        assert_eq!(completions[0]["parts"], json!([]));
        assert_eq!(completions[1]["parts"][0]["etag"], "etag-1");
        assert_eq!(completions[1]["parts"][1]["etag"], "etag-2");
    }

    #[test]
    fn recognizes_already_verified_artifacts_case_insensitively() {
        let artifact = crate::manifest::PreparedArtifact {
            kind: crate::manifest::ArtifactKind::Pe,
            path: std::path::PathBuf::from("out/App.EXE"),
            size: 3,
            sha256: "a".repeat(64),
        };
        let build = json!({
            "artifacts": [{
                "kind": "pe",
                "logical_name": "app.exe",
                "sha256": "A".repeat(64),
                "verification_status": "verified"
            }]
        });
        assert!(super::is_already_verified(&build, &artifact));
    }

    #[test]
    fn upload_polling_rejects_rejected_and_quarantined_terminal_states() {
        for status in ["REJECTED", "QUARANTINED"] {
            let error = single_response_error(
                "/api/v1/uploads/upl_test",
                json!({"verification_status": status}),
                |api| {
                    Publisher::with_poll_interval(api, Duration::ZERO)
                        .wait_for_upload("upl_test", 0)
                },
            );
            assert_eq!(error, format!("artifact upload ended in {status}"));
        }
    }

    #[test]
    fn build_polling_rejects_failed_artifacts_and_times_out_when_incomplete() {
        let rejected = single_response_error(
            "/api/v1/builds/bld_test/ci-status",
            json!({
                "ready": false,
                "rejected_artifacts": [{"logical_name": "app.pdb"}]
            }),
            |api| Publisher::with_poll_interval(api, Duration::ZERO).wait_for_build("bld_test", 0),
        );
        assert!(rejected.contains("app.pdb"));

        let timed_out = single_response_error(
            "/api/v1/builds/bld_test/ci-status",
            json!({"ready": false, "rejected_artifacts": []}),
            |api| Publisher::with_poll_interval(api, Duration::ZERO).wait_for_build("bld_test", 0),
        );
        assert_eq!(timed_out, "timed out waiting for complete CI Build verification");
    }
}
