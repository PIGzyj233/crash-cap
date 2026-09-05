use std::collections::HashMap;
use std::fs::File;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;
use std::thread;
use std::time::Duration;

use reqwest::blocking::{Body, Client, Response};
use reqwest::header::{HeaderMap, HeaderName, HeaderValue, ETAG};
use reqwest::{Method, StatusCode, Url};
use serde::de::DeserializeOwned;
use serde_json::Value;

use crate::error::{PublishError, Result};
use crate::redaction::redact;

const REQUEST_ATTEMPTS: usize = 5;

pub struct ApiClient {
    base_url: Url,
    client: Client,
    retry_base: Duration,
}

impl ApiClient {
    pub fn resource_url(&self, path: &str) -> Result<String> {
        self.base_url
            .join(path)
            .map(|url| url.to_string())
            .map_err(|_| PublishError::message("cannot construct resource URL"))
    }
    pub fn new(base_url: &str) -> Result<Self> {
        Self::with_retry_base(base_url, Duration::from_secs(1))
    }

    pub(crate) fn with_retry_base(base_url: &str, retry_base: Duration) -> Result<Self> {
        let normalized = format!("{}/", base_url.trim_end_matches('/'));
        let parsed = Url::parse(&normalized)
            .map_err(|_| PublishError::message("--api-url must be a valid HTTP(S) URL"))?;
        if !matches!(parsed.scheme(), "http" | "https") {
            return Err(PublishError::message("--api-url must use the http or https scheme"));
        }
        if !parsed.username().is_empty()
            || parsed.password().is_some()
            || parsed.query().is_some()
            || parsed.fragment().is_some()
        {
            return Err(PublishError::message(
                "--api-url must not contain credentials, query parameters, or a fragment",
            ));
        }
        let client = Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .connect_timeout(Duration::from_secs(60))
            .build()
            .map_err(|_| PublishError::message("cannot initialize the HTTP client"))?;
        Ok(Self { base_url: parsed, client, retry_base })
    }

    pub fn request_value(
        &self,
        method: Method,
        path: &str,
        json_body: Option<&Value>,
    ) -> Result<Value> {
        let url = self
            .base_url
            .join(&format!("./{}", path.trim_start_matches('/')))
            .map_err(|_| PublishError::message("cannot construct API request URL"))?;
        for attempt in 0..REQUEST_ATTEMPTS {
            let mut request =
                self.client.request(method.clone(), url.clone()).timeout(Duration::from_secs(60));
            if let Some(body) = json_body {
                request = request.json(body);
            }
            match request.send() {
                Ok(response)
                    if response.status().is_server_error() && attempt + 1 < REQUEST_ATTEMPTS =>
                {
                    self.backoff(attempt);
                }
                Ok(response) => return decode_api_response(response, &method, path),
                Err(_) if attempt + 1 < REQUEST_ATTEMPTS => self.backoff(attempt),
                Err(_) => {
                    return Err(PublishError::message(format!(
                        "API transport failed after retries for {} {}",
                        method.as_str(),
                        path
                    )))
                }
            }
        }
        Err(PublishError::message("unreachable API retry state"))
    }

    pub fn request_json<T: DeserializeOwned>(
        &self,
        method: Method,
        path: &str,
        json_body: Option<&Value>,
    ) -> Result<T> {
        let value = self.request_value(method.clone(), path, json_body)?;
        serde_json::from_value(value).map_err(|_| {
            PublishError::message(format!(
                "API {} {} returned an invalid response",
                method.as_str(),
                path
            ))
        })
    }

    pub fn put_file_range(
        &self,
        url: &str,
        headers: &HashMap<String, String>,
        path: &Path,
        offset: u64,
        length: u64,
        part_number: Option<u32>,
    ) -> Result<Option<String>> {
        let header_map = upload_headers(headers)?;
        for attempt in 0..REQUEST_ATTEMPTS {
            let body = file_body(path, offset, length)?;
            let response = self
                .client
                .put(url)
                .headers(header_map.clone())
                .timeout(Duration::from_secs(900))
                .body(body)
                .send();
            match response {
                Ok(response)
                    if response.status().is_server_error() && attempt + 1 < REQUEST_ATTEMPTS =>
                {
                    self.backoff(attempt);
                }
                Ok(response) if response.status().is_success() => {
                    let etag = response
                        .headers()
                        .get(ETAG)
                        .and_then(|value| value.to_str().ok())
                        .map(str::to_owned);
                    return Ok(etag);
                }
                Ok(response) => {
                    return Err(PublishError::message(upload_status_error(
                        part_number,
                        response.status(),
                    )))
                }
                Err(_) if attempt + 1 < REQUEST_ATTEMPTS => self.backoff(attempt),
                Err(_) => {
                    let label =
                        part_number.map(|number| format!(" part {number}")).unwrap_or_default();
                    return Err(PublishError::message(format!(
                        "object upload{label} transport failed after retries"
                    )));
                }
            }
        }
        Err(PublishError::message("unreachable upload retry state"))
    }

    fn backoff(&self, attempt: usize) {
        let multiplier = 1_u32 << attempt.min(3);
        thread::sleep(self.retry_base.saturating_mul(multiplier));
    }
}

fn decode_api_response(response: Response, method: &Method, path: &str) -> Result<Value> {
    let status = response.status();
    if !status.is_success() {
        let body = response.json::<Value>().ok();
        let detail = body.as_ref().and_then(|value| value.get("error"));
        let code = detail
            .and_then(|value| value.get("code"))
            .and_then(Value::as_str)
            .unwrap_or("HTTP_ERROR");
        let message = detail
            .and_then(|value| value.get("message"))
            .and_then(Value::as_str)
            .unwrap_or_default();
        let safe_code = redact(code);
        let safe_message = redact(message);
        return Err(PublishError::message(
            format!(
                "API {} {} failed ({}): {} {}",
                method.as_str(),
                path,
                status.as_u16(),
                safe_code,
                safe_message
            )
            .trim()
            .to_owned(),
        ));
    }
    response.json::<Value>().map_err(|_| {
        PublishError::message(format!("API {} {} returned invalid JSON", method.as_str(), path))
    })
}

fn upload_headers(headers: &HashMap<String, String>) -> Result<HeaderMap> {
    let mut result = HeaderMap::new();
    for (name, value) in headers {
        let name = HeaderName::from_bytes(name.as_bytes())
            .map_err(|_| PublishError::message("object upload returned an invalid header name"))?;
        let value = HeaderValue::from_str(value)
            .map_err(|_| PublishError::message("object upload returned an invalid header value"))?;
        result.insert(name, value);
    }
    Ok(result)
}

fn file_body(path: &Path, offset: u64, length: u64) -> Result<Body> {
    let mut file = File::open(path).map_err(|error| {
        PublishError::message(format!("cannot open artifact {}: {error}", path.display()))
    })?;
    file.seek(SeekFrom::Start(offset)).map_err(|error| {
        PublishError::message(format!("cannot seek artifact {}: {error}", path.display()))
    })?;
    let reader = file.take(length);
    Ok(Body::sized(reader, length))
}

fn upload_status_error(part_number: Option<u32>, status: StatusCode) -> String {
    match part_number {
        Some(number) => format!("object upload part {number} failed ({})", status.as_u16()),
        None => format!("object upload failed ({})", status.as_u16()),
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::fs;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Arc;
    use std::thread;
    use std::time::Duration;

    use reqwest::Method;
    use tempfile::tempdir;

    use super::ApiClient;

    #[test]
    fn api_url_rejects_embedded_credentials_and_query_data() {
        for url in [
            "http://user:secret@127.0.0.1/api/v1",
            "http://127.0.0.1/api/v1?token=secret",
            "http://127.0.0.1/api/v1#fragment",
        ] {
            assert!(ApiClient::with_retry_base(url, Duration::ZERO).is_err(), "{url}");
        }
    }

    #[test]
    fn retries_server_errors_without_exposing_response_body() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind mock API");
        let address = listener.local_addr().expect("mock address");
        let calls = Arc::new(AtomicUsize::new(0));
        let server_calls = Arc::clone(&calls);
        let server = thread::spawn(move || {
            for stream in listener.incoming().take(2) {
                let mut stream = stream.expect("accept request");
                let mut buffer = [0_u8; 4096];
                let _ = stream.read(&mut buffer).expect("read request");
                let call = server_calls.fetch_add(1, Ordering::SeqCst);
                let (status, body) = if call == 0 {
                    (500, r#"{"error":{"message":"first failure"}}"#)
                } else {
                    (200, r#"[{"id":"wsp_test","name":"test"}]"#)
                };
                write!(
                    stream,
                    "HTTP/1.1 {status} Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                    body.len()
                )
                .expect("write response");
            }
        });
        let client =
            ApiClient::with_retry_base(&format!("http://{address}/api/v1"), Duration::ZERO)
                .expect("client");
        let value = client.request_value(Method::GET, "/workspaces", None).expect("retry succeeds");
        assert_eq!(value[0]["id"], "wsp_test");
        server.join().expect("join server");
        assert_eq!(calls.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn does_not_retry_4xx_and_redacts_api_message() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind mock API");
        let address = listener.local_addr().expect("mock address");
        let calls = Arc::new(AtomicUsize::new(0));
        let server_calls = Arc::clone(&calls);
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept request");
            let mut buffer = [0_u8; 4096];
            let _ = stream.read(&mut buffer).expect("read request");
            server_calls.fetch_add(1, Ordering::SeqCst);
            let body = r#"{"error":{"code":"VALIDATION","message":"https://store/object?X-Amz-Signature=SUPER_SECRET_SENTINEL"}}"#;
            write!(
                stream,
                "HTTP/1.1 400 Test\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            )
            .expect("write response");
        });
        let client =
            ApiClient::with_retry_base(&format!("http://{address}/api/v1"), Duration::ZERO)
                .expect("client");
        let error = client
            .request_value(Method::GET, "/workspaces", None)
            .expect_err("400 must fail")
            .to_string();
        server.join().expect("join server");
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert!(!error.contains("SUPER_SECRET_SENTINEL"));
        assert!(error.contains("[REDACTED_URL]"));
    }

    #[test]
    fn retries_streamed_put_and_returns_etag() {
        let directory = tempdir().expect("temporary directory");
        let payload_path = directory.path().join("payload.bin");
        fs::write(&payload_path, b"streamed-payload").expect("write payload");
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind object server");
        let address = listener.local_addr().expect("object address");
        let calls = Arc::new(AtomicUsize::new(0));
        let server_calls = Arc::clone(&calls);
        let server = thread::spawn(move || {
            for stream in listener.incoming().take(2) {
                let mut stream = stream.expect("accept request");
                let mut data = Vec::new();
                let mut buffer = [0_u8; 4096];
                let header_end;
                loop {
                    let count = stream.read(&mut buffer).expect("read upload headers");
                    data.extend_from_slice(&buffer[..count]);
                    if let Some(position) = data.windows(4).position(|window| window == b"\r\n\r\n")
                    {
                        header_end = position + 4;
                        break;
                    }
                }
                let headers = String::from_utf8_lossy(&data[..header_end]);
                let length = headers
                    .lines()
                    .find_map(|line| {
                        let (name, value) = line.split_once(':')?;
                        name.eq_ignore_ascii_case("content-length")
                            .then(|| value.trim().parse::<usize>().expect("content length"))
                    })
                    .expect("content length header");
                while data.len() - header_end < length {
                    let count = stream.read(&mut buffer).expect("read upload body");
                    data.extend_from_slice(&buffer[..count]);
                }
                assert_eq!(&data[header_end..header_end + length], b"streamed-payload");
                let call = server_calls.fetch_add(1, Ordering::SeqCst);
                let status = if call == 0 { 500 } else { 200 };
                let etag = if call == 0 { "" } else { "ETag: retry-etag\r\n" };
                write!(
                    stream,
                    "HTTP/1.1 {status} Test\r\n{etag}Content-Length: 0\r\nConnection: close\r\n\r\n"
                )
                .expect("write upload response");
            }
        });
        let client =
            ApiClient::with_retry_base(&format!("http://{address}/api/v1"), Duration::ZERO)
                .expect("client");
        let etag = client
            .put_file_range(
                &format!("http://{address}/object"),
                &HashMap::new(),
                &payload_path,
                0,
                16,
                None,
            )
            .expect("retry upload")
            .expect("ETag");
        server.join().expect("join server");
        assert_eq!(etag, "retry-etag");
        assert_eq!(calls.load(Ordering::SeqCst), 2);
    }

    #[test]
    fn does_not_retry_object_upload_4xx_or_expose_its_url() {
        let directory = tempdir().expect("temporary directory");
        let payload_path = directory.path().join("payload.bin");
        fs::write(&payload_path, b"payload").expect("write payload");
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind object server");
        let address = listener.local_addr().expect("object address");
        let calls = Arc::new(AtomicUsize::new(0));
        let server_calls = Arc::clone(&calls);
        let server = thread::spawn(move || {
            let (mut stream, _) = listener.accept().expect("accept request");
            stream.set_read_timeout(Some(Duration::from_secs(5))).expect("set upload read timeout");
            let mut buffer = [0_u8; 4096];
            let mut request = Vec::new();
            let header_end = loop {
                let count = stream.read(&mut buffer).expect("read upload headers");
                assert!(count > 0, "request ended before headers");
                request.extend_from_slice(&buffer[..count]);
                if let Some(position) = request.windows(4).position(|bytes| bytes == b"\r\n\r\n") {
                    break position + 4;
                }
            };
            // Closing a socket with an unread request body can reset the TCP
            // connection, turning the intended HTTP 403 into a transport error.
            while request.len() - header_end < 7 {
                let count = stream.read(&mut buffer).expect("read upload body");
                assert!(count > 0, "request ended before payload");
                request.extend_from_slice(&buffer[..count]);
            }
            assert_eq!(&request[header_end..], b"payload");
            server_calls.fetch_add(1, Ordering::SeqCst);
            write!(
                stream,
                "HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
            )
            .expect("write response");
        });
        let client =
            ApiClient::with_retry_base(&format!("http://{address}/api/v1"), Duration::ZERO)
                .expect("client");
        let sensitive_url =
            format!("http://{address}/object?X-Amz-Signature=SUPER_SECRET_SENTINEL");
        let error = client
            .put_file_range(&sensitive_url, &HashMap::new(), &payload_path, 0, 7, Some(3))
            .expect_err("403 must fail")
            .to_string();
        server.join().expect("join server");
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(error, "object upload part 3 failed (403)");
        assert!(!error.contains("SUPER_SECRET_SENTINEL"));
    }

    #[test]
    fn does_not_expose_invalid_upload_header_values() {
        let directory = tempdir().expect("temporary directory");
        let payload_path = directory.path().join("payload.bin");
        fs::write(&payload_path, b"payload").expect("write payload");
        let headers = HashMap::from([(
            "Authorization".to_owned(),
            "Bearer SUPER_SECRET_SENTINEL\ninvalid".to_owned(),
        )]);
        let client = ApiClient::with_retry_base("http://127.0.0.1:1/api/v1", Duration::ZERO)
            .expect("client");
        let error = client
            .put_file_range(
                "http://127.0.0.1:1/object?X-Amz-Signature=SUPER_SECRET_SENTINEL",
                &headers,
                &payload_path,
                0,
                7,
                None,
            )
            .expect_err("invalid header must fail")
            .to_string();
        assert_eq!(error, "object upload returned an invalid header value");
        assert!(!error.contains("SUPER_SECRET_SENTINEL"));
    }

    #[test]
    fn stops_api_transport_retries_after_five_attempts() {
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind mock API");
        let address = listener.local_addr().expect("mock address");
        let calls = Arc::new(AtomicUsize::new(0));
        let server_calls = Arc::clone(&calls);
        let server = thread::spawn(move || {
            for stream in listener.incoming().take(5) {
                let stream = stream.expect("accept request");
                server_calls.fetch_add(1, Ordering::SeqCst);
                drop(stream);
            }
        });
        let client =
            ApiClient::with_retry_base(&format!("http://{address}/api/v1"), Duration::ZERO)
                .expect("client");
        let error = client
            .request_value(Method::GET, "/workspaces", None)
            .expect_err("all transport attempts must fail")
            .to_string();
        server.join().expect("join server");
        assert_eq!(calls.load(Ordering::SeqCst), 5);
        assert_eq!(error, "API transport failed after retries for GET /workspaces");
    }

    #[test]
    fn stops_object_transport_retries_after_five_attempts_without_exposing_url() {
        let directory = tempdir().expect("temporary directory");
        let payload_path = directory.path().join("payload.bin");
        fs::write(&payload_path, b"payload").expect("write payload");
        let listener = TcpListener::bind("127.0.0.1:0").expect("bind object server");
        let address = listener.local_addr().expect("object address");
        let calls = Arc::new(AtomicUsize::new(0));
        let server_calls = Arc::clone(&calls);
        let server = thread::spawn(move || {
            for stream in listener.incoming().take(5) {
                let stream = stream.expect("accept request");
                server_calls.fetch_add(1, Ordering::SeqCst);
                drop(stream);
            }
        });
        let client =
            ApiClient::with_retry_base(&format!("http://{address}/api/v1"), Duration::ZERO)
                .expect("client");
        let sensitive_url =
            format!("http://{address}/object?X-Amz-Signature=SUPER_SECRET_SENTINEL");
        let error = client
            .put_file_range(&sensitive_url, &HashMap::new(), &payload_path, 0, 7, Some(7))
            .expect_err("all transport attempts must fail")
            .to_string();
        server.join().expect("join server");
        assert_eq!(calls.load(Ordering::SeqCst), 5);
        assert_eq!(error, "object upload part 7 transport failed after retries");
        assert!(!error.contains("SUPER_SECRET_SENTINEL"));
    }
}
