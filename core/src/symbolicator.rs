//! Small policy-aware client for Crash-Cap's internal Symbolicator gateway.
//!
//! The request intentionally contains no `sources` field.  Scope is supplied
//! in the query string and the gateway is responsible for deployment-owned
//! sources.  A pending request is a temporary Symbolicator object: a missing
//! polling object causes the original POST body to be submitted again.

use crate::minidump::{InspectModule, InspectReport};
use crate::unwind::{UnwindFrame, UnwindReport};
use reqwest::blocking::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::time::Duration;

const MAX_REPOSTS: usize = 3;
const MAX_POLLS_PER_POST: usize = 8;
const HTTP_CLIENT_HEADROOM_SECONDS: u64 = 15;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SymbolicatorRaw {
    pub endpoint: String,
    pub scope: String,
    pub inventory_version: u64,
    pub timeout_seconds: u64,
    pub attempts: Vec<SymbolicatorAttempt>,
    pub final_response: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SymbolicatorAttempt {
    pub operation: String,
    pub http_status: Option<u16>,
    pub body: Option<Value>,
    pub error: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SymbolicationResult {
    pub frames: BTreeMap<FrameKey, SymbolicatedFrame>,
    /// Final per-module status returned by Symbolicator. This is kept separate
    /// from Build artifact status: `found` can come from a deployment-owned
    /// public source even when no Workspace Artifact was materialized.
    pub modules: Vec<SymbolicatedModule>,
    pub version: Option<String>,
    /// Number of response frames discarded because their provenance could not
    /// be mapped to a requested unwind frame.  This is deliberately a count,
    /// not a copy of untrusted response content.
    pub rejected_frames: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SymbolicatedModule {
    pub code_file: Option<String>,
    pub code_id: Option<String>,
    pub debug_file: Option<String>,
    pub debug_id: Option<String>,
    pub debug_status: String,
}

impl SymbolicationResult {
    /// Return Symbolicator's terminal debug-file status using identity before
    /// names. A filename-only fallback is accepted only for the exact original
    /// path, never a basename, so public results cannot cross-fill a module.
    pub fn module_debug_status(
        &self,
        code_file: &str,
        code_id: Option<&str>,
        debug_file: Option<&str>,
        debug_id: Option<&str>,
    ) -> Option<&str> {
        if let Some(debug_id) = debug_id {
            let normalized = normalize_module_id(debug_id);
            if let Some(module) = self.modules.iter().find(|module| {
                module
                    .debug_id
                    .as_deref()
                    .is_some_and(|candidate| normalize_module_id(candidate) == normalized)
            }) {
                return Some(module.debug_status.as_str());
            }
        }
        if let Some(code_id) = code_id {
            let normalized = normalize_module_id(code_id);
            if let Some(module) = self.modules.iter().find(|module| {
                module
                    .code_id
                    .as_deref()
                    .is_some_and(|candidate| normalize_module_id(candidate) == normalized)
                    && module
                        .code_file
                        .as_deref()
                        .is_some_and(|candidate| same_basename(candidate, code_file))
            }) {
                return Some(module.debug_status.as_str());
            }
        }
        self.modules
            .iter()
            .find(|module| {
                module
                    .code_file
                    .as_deref()
                    .is_some_and(|candidate| candidate.eq_ignore_ascii_case(code_file))
                    || debug_file.is_some_and(|debug_file| {
                        module
                            .debug_file
                            .as_deref()
                            .is_some_and(|candidate| candidate.eq_ignore_ascii_case(debug_file))
                    })
            })
            .map(|module| module.debug_status.as_str())
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct FrameKey {
    pub module: String,
    pub instruction_addr: u64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct SymbolicatedFrame {
    pub function: Option<String>,
    pub file: Option<String>,
    pub line: Option<u64>,
    /// Additional symbolication records for the same physical frame.  The
    /// gateway can return multiple inline records with one original_index;
    /// retain them without allowing a second record to overwrite provenance.
    pub inline: Vec<SymbolicatedFrame>,
}

#[derive(Debug, thiserror::Error)]
pub enum SymbolicatorError {
    #[error("symbolicator endpoint is invalid: {0}")]
    InvalidEndpoint(String),
    #[error("symbolicator request failed: {0}")]
    Request(String),
}

/// Call the gateway and return both normalized fields and raw response events.
pub fn symbolicate(
    endpoint: &str,
    scope: &str,
    inventory_version: u64,
    timeout_seconds: u64,
    report: &InspectReport,
    unwind: &UnwindReport,
) -> Result<(SymbolicationResult, SymbolicatorRaw), SymbolicatorError> {
    symbolicate_with_request_report(
        endpoint,
        scope,
        inventory_version,
        timeout_seconds,
        report,
        report,
        unwind,
    )
}

/// Call the gateway with a request-specific report while retaining the
/// original dump report as the canonical module identity source.  The request
/// report may contain verified local PE/PDB paths that deliberately differ
/// from the producer path embedded in the dump.
pub fn symbolicate_with_request_report(
    endpoint: &str,
    scope: &str,
    inventory_version: u64,
    timeout_seconds: u64,
    request_report: &InspectReport,
    identity_report: &InspectReport,
    unwind: &UnwindReport,
) -> Result<(SymbolicationResult, SymbolicatorRaw), SymbolicatorError> {
    let endpoint = endpoint.trim_end_matches('/');
    if endpoint.is_empty() || !endpoint.starts_with("http") {
        return Err(SymbolicatorError::InvalidEndpoint(endpoint.to_owned()));
    }
    if !scope.starts_with("wsp_") {
        return Err(SymbolicatorError::InvalidEndpoint("scope must start with wsp_".to_owned()));
    }
    let body = request_body(request_report, unwind);
    let effective_timeout = timeout_seconds.clamp(1, 300);
    let client = Client::builder()
        // Symbolicator uses `effective_timeout` as its server-side long-poll
        // budget. The transport deadline needs headroom for gateway forwarding
        // and JSON serialization or a successful cold-cache response can race
        // the client deadline and be misreported as a request failure.
        .timeout(Duration::from_secs(
            effective_timeout.saturating_add(HTTP_CLIENT_HEADROOM_SECONDS),
        ))
        .build()
        .map_err(|error| SymbolicatorError::Request(error.to_string()))?;
    let mut raw = SymbolicatorRaw {
        endpoint: endpoint.to_owned(),
        scope: scope.to_owned(),
        inventory_version,
        timeout_seconds: effective_timeout,
        attempts: Vec::new(),
        final_response: None,
    };

    for post_number in 0..MAX_REPOSTS {
        let url = format!(
            "{endpoint}/symbolicate?scope={scope}&inventory={inventory_version}&timeout={effective_timeout}"
        );
        let response = client.post(&url).json(&body).send();
        let (status, value, error) = read_response(response);
        raw.attempts.push(SymbolicatorAttempt {
            operation: format!("post:{post_number}"),
            http_status: status,
            body: value.clone(),
            error: error.clone(),
        });
        let Some(status) = status else {
            if post_number + 1 == MAX_REPOSTS {
                return Err(SymbolicatorError::Request(
                    format!(
                        "POST failed or timed out (endpoint={endpoint}, scope={scope}, timeout_seconds={effective_timeout}): {}",
                        error.unwrap_or_else(|| "no response".to_owned())
                    ),
                ));
            }
            continue;
        };
        if !(200..300).contains(&status) {
            if status == 404 && post_number + 1 < MAX_REPOSTS {
                continue;
            }
            return Err(SymbolicatorError::Request(format!("POST returned HTTP {status}")));
        }
        let Some(value) = value else {
            return Err(SymbolicatorError::Request("POST returned an empty JSON body".to_owned()));
        };
        let state = value.get("status").and_then(Value::as_str).unwrap_or("completed");
        if state != "pending" {
            raw.final_response = Some(value.clone());
            return Ok((parse_result(&value, identity_report, unwind), raw));
        }
        let Some(request_id) = request_id(&value) else {
            return Err(SymbolicatorError::Request(
                "pending response has no request_id".to_owned(),
            ));
        };
        let poll_url = format!("{endpoint}/requests/{request_id}");
        let mut repoll = false;
        for poll_number in 0..MAX_POLLS_PER_POST {
            let response = client.get(&poll_url).send();
            let (poll_status, poll_value, poll_error) = read_response(response);
            raw.attempts.push(SymbolicatorAttempt {
                operation: format!("poll:{post_number}:{poll_number}"),
                http_status: poll_status,
                body: poll_value.clone(),
                error: poll_error,
            });
            if poll_status == Some(404) {
                // Symbolicator's request cache is ephemeral. Re-submit the
                // entire body; the old request id is never returned as a task id.
                repoll = true;
                break;
            }
            let Some(poll_value) = poll_value else {
                continue;
            };
            let poll_state =
                poll_value.get("status").and_then(Value::as_str).unwrap_or("completed");
            if poll_state != "pending" {
                raw.final_response = Some(poll_value.clone());
                return Ok((parse_result(&poll_value, identity_report, unwind), raw));
            }
            std::thread::sleep(Duration::from_millis(25));
        }
        if !repoll && post_number + 1 == MAX_REPOSTS {
            return Err(SymbolicatorError::Request(
                format!(
                    "symbolicator request remained pending after {MAX_POLLS_PER_POST} polls (endpoint={endpoint}, scope={scope}, timeout_seconds={effective_timeout})"
                ),
            ));
        }
    }
    Err(SymbolicatorError::Request("symbolicator retry budget exhausted".to_owned()))
}

fn request_body(report: &InspectReport, unwind: &UnwindReport) -> Value {
    let modules = report
        .modules
        .iter()
        .map(|module| {
            json!({
                "type": "pe",
                "code_file": module.code_file,
                "code_id": module.code_id,
                "debug_file": module.debug_file,
                "debug_id": module.debug_id,
                "image_addr": parse_numeric_address(&module.image_base),
                "image_size": module.image_size,
            })
        })
        .collect::<Vec<_>>();
    let stacktraces = unwind
        .threads
        .iter()
        .map(|thread| {
            json!({
                "frames": thread.frames.iter().map(|frame| {
                    json!({
                        "instruction_addr": format!("0x{:x}", frame.instruction),
                    })
                }).collect::<Vec<_>>()
            })
        })
        .collect::<Vec<_>>();
    json!({ "platform": "native", "modules": modules, "stacktraces": stacktraces })
}

fn read_response(
    response: Result<reqwest::blocking::Response, reqwest::Error>,
) -> (Option<u16>, Option<Value>, Option<String>) {
    let Ok(response) = response else {
        return (None, None, response.err().map(|error| error.to_string()));
    };
    let status = response.status().as_u16();
    let body = response.json::<Value>().ok();
    (Some(status), body, None)
}

fn request_id(value: &Value) -> Option<String> {
    value
        .get("request_id")
        .or_else(|| value.get("id"))
        .and_then(Value::as_str)
        .and_then(|id| id.strip_prefix("/requests/").or(Some(id)))
        .filter(|id| !id.is_empty() && id.chars().all(|c| c.is_ascii_hexdigit() || c == '-'))
        .map(ToOwned::to_owned)
}

fn parse_result(
    value: &Value,
    report: &InspectReport,
    unwind: &UnwindReport,
) -> SymbolicationResult {
    let mut result = SymbolicationResult {
        version: value.get("version").and_then(Value::as_str).map(ToOwned::to_owned),
        ..Default::default()
    };
    result.modules = value
        .get("modules")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|module| {
            Some(SymbolicatedModule {
                code_file: module.get("code_file").and_then(Value::as_str).map(ToOwned::to_owned),
                code_id: module.get("code_id").and_then(Value::as_str).map(ToOwned::to_owned),
                debug_file: module.get("debug_file").and_then(Value::as_str).map(ToOwned::to_owned),
                debug_id: module.get("debug_id").and_then(Value::as_str).map(ToOwned::to_owned),
                debug_status: module.get("debug_status")?.as_str()?.to_owned(),
            })
        })
        .collect();
    let Some(traces) = value.get("stacktraces").and_then(Value::as_array) else {
        return result;
    };
    for (trace_index, trace) in traces.iter().enumerate() {
        let Some(frames) = trace.get("frames").and_then(Value::as_array) else {
            continue;
        };
        for frame in frames {
            let Some(response_address) = frame.get("instruction_addr").and_then(parse_address)
            else {
                result.rejected_frames += 1;
                continue;
            };
            let requested_thread = match trace_thread_id(trace) {
                Ok(Some(thread_id)) => unwind.threads.iter().find(|thread| thread.id == thread_id),
                Ok(None) => unwind.threads.get(trace_index),
                Err(()) => {
                    result.rejected_frames += 1;
                    continue;
                }
            };
            let Some(requested_thread) = requested_thread else {
                result.rejected_frames += 1;
                continue;
            };
            // Provenance is anchored by the gateway's original_index.  A
            // positional response without that field is not auditable and
            // must never fall back to a raw response address.
            let Some(request_index) = frame
                .get("original_index")
                .and_then(Value::as_u64)
                .and_then(|value| usize::try_from(value).ok())
            else {
                result.rejected_frames += 1;
                continue;
            };
            let Some(requested) = requested_thread.frames.get(request_index) else {
                result.rejected_frames += 1;
                continue;
            };
            let requested_address = requested.instruction;
            // The deployed gateway may report the symbol boundary one byte
            // away from the unwind instruction.  Provenance still requires
            // the request index and keeps the accepted address delta bounded.
            let address_ok = response_address.abs_diff(requested_address) <= 1;
            if !address_ok {
                result.rejected_frames += 1;
                continue;
            }
            let requested_report_module = report.modules.iter().find(|module| {
                let start = parse_numeric_address(&module.image_base);
                let end = start.saturating_add(module.image_size as u64);
                requested_address >= start && requested_address < end
            });
            if !response_provenance_matches(
                value,
                frame,
                response_address,
                requested_address,
                requested,
                requested_report_module,
            ) {
                result.rejected_frames += 1;
                continue;
            }
            // Canonical frames use the original dump module path.  Prefer that
            // report identity when the address resolved to it; the unwind
            // module is only a fallback for reports without a matching module.
            // Response paths must never become a new identity key.
            let Some(module) = requested_report_module
                .map(|module| module.code_file.clone())
                .or_else(|| requested.module.as_ref().map(|module| module.code_file.clone()))
            else {
                result.rejected_frames += 1;
                continue;
            };
            let symbol = SymbolicatedFrame {
                function: string_field(frame, &["function", "function_name"]),
                file: string_field(frame, &["filename", "file", "source_file"]),
                line: number_field(frame, &["lineno", "line", "source_line"]),
                inline: Vec::new(),
            };
            let key = FrameKey {
                module: module.to_ascii_lowercase(),
                instruction_addr: requested_address,
            };
            merge_symbol(&mut result.frames, key, symbol);
        }
    }
    result
}

#[derive(Debug, Default)]
struct ModuleIdentity {
    code_id: Option<String>,
    debug_id: Option<String>,
    image_base: Option<u64>,
    image_size: Option<u64>,
}

fn response_provenance_matches(
    response: &Value,
    frame: &Value,
    response_address: u64,
    requested_address: u64,
    requested: &UnwindFrame,
    requested_report_module: Option<&InspectModule>,
) -> bool {
    let requested_name = requested
        .module
        .as_ref()
        .map(|module| module.code_file.as_str())
        .or_else(|| requested_report_module.map(|module| module.code_file.as_str()));
    let response_modules = response.get("modules").and_then(Value::as_array);
    let mut paths = Vec::new();
    for field_name in ["package", "module", "code_file"] {
        let Some(field) = frame.get(field_name) else {
            continue;
        };
        if field.is_null() {
            continue;
        }
        let Some(path) = field.as_str() else {
            return false;
        };
        paths.push(path);
    }

    let Some(response_modules) = response_modules else {
        // Older gateway responses did not include a top-level module list.
        // Preserve the safe basename check for those responses; the stronger
        // identity check below is mandatory whenever the list is present.
        return paths
            .iter()
            .all(|path| requested_name.is_some_and(|name| same_basename(path, name)));
    };

    if response_modules.is_empty() {
        return paths
            .iter()
            .all(|path| requested_name.is_some_and(|name| same_basename(path, name)));
    }

    let mut selected_index = None;
    for path in &paths {
        let candidates =
            response_module_candidates(response_modules, path, response_address, requested_address);
        let Some(index) = unique_index(candidates) else {
            return false;
        };
        if selected_index.is_some_and(|selected| selected != index) {
            return false;
        }
        selected_index = Some(index);
    }

    let module = if let Some(index) = selected_index {
        response_modules.get(index)
    } else {
        // A response without a package can still be tied to one module by
        // its absolute instruction address.  Ambiguous ranges are rejected.
        let candidates = response_modules
            .iter()
            .enumerate()
            .filter(|(_, module)| {
                response_module_range_contains(module, response_address)
                    || response_module_range_contains(module, requested_address)
            })
            .map(|(index, _)| index)
            .collect::<Vec<_>>();
        unique_index(candidates).and_then(|index| response_modules.get(index))
    };

    let Some(module) = module else {
        return false;
    };
    response_module_identity_matches(
        module,
        response_address,
        requested_address,
        requested,
        requested_report_module,
    )
}

fn response_module_candidates(
    modules: &[Value],
    path: &str,
    response_address: u64,
    requested_address: u64,
) -> Vec<usize> {
    let exact = modules
        .iter()
        .enumerate()
        .filter(|(_, module)| {
            module
                .get("code_file")
                .and_then(Value::as_str)
                .is_some_and(|code_file| code_file.eq_ignore_ascii_case(path))
        })
        .map(|(index, _)| index)
        .collect::<Vec<_>>();
    if !exact.is_empty() {
        return exact;
    }

    let basename = basename_lower(path);
    let by_basename = modules
        .iter()
        .enumerate()
        .filter(|(_, module)| {
            module
                .get("code_file")
                .and_then(Value::as_str)
                .is_some_and(|code_file| basename_lower(code_file) == basename)
        })
        .map(|(index, _)| index)
        .collect::<Vec<_>>();
    if by_basename.len() == 1 {
        return by_basename;
    }
    let range_candidates = modules
        .iter()
        .enumerate()
        .filter(|(_, module)| {
            response_module_range_contains(module, response_address)
                || response_module_range_contains(module, requested_address)
        })
        .map(|(index, _)| index)
        .collect::<Vec<_>>();
    if by_basename.is_empty() {
        range_candidates
    } else if range_candidates.is_empty() {
        by_basename
    } else {
        by_basename.iter().copied().filter(|index| range_candidates.contains(index)).collect()
    }
}

fn unique_index(mut candidates: Vec<usize>) -> Option<usize> {
    candidates.sort_unstable();
    candidates.dedup();
    if candidates.len() == 1 {
        candidates.into_iter().next()
    } else {
        None
    }
}

fn response_module_identity_matches(
    module: &Value,
    response_address: u64,
    requested_address: u64,
    requested: &UnwindFrame,
    requested_report_module: Option<&InspectModule>,
) -> bool {
    let requested_identity = requested_module_identity(requested, requested_report_module);
    let response_debug_id = module.get("debug_id").and_then(Value::as_str).map(normalize_module_id);
    let response_code_id = module.get("code_id").and_then(Value::as_str).map(normalize_module_id);
    let response_range = response_module_range(module);
    let response_range_present =
        module.get("image_addr").is_some() || module.get("image_size").is_some();
    if response_range_present {
        let Some((base, size)) = response_range else {
            return false;
        };
        if !range_contains(base, size, response_address)
            && !range_contains(base, size, requested_address)
        {
            return false;
        }
    }

    if let (Some(requested_debug_id), Some(response_debug_id)) =
        (requested_identity.debug_id.as_deref(), response_debug_id.as_deref())
    {
        return normalize_module_id(requested_debug_id) == response_debug_id;
    }

    let Some(requested_code_id) = requested_identity.code_id.as_deref() else {
        return false;
    };
    let Some(response_code_id) = response_code_id.as_deref() else {
        return false;
    };
    let Some((requested_base, requested_size)) =
        requested_identity.image_base.zip(requested_identity.image_size)
    else {
        return false;
    };
    let Some((response_base, response_size)) = response_range else {
        return false;
    };
    normalize_module_id(requested_code_id) == response_code_id
        && requested_base == response_base
        && requested_size == response_size
}

fn requested_module_identity(
    requested: &UnwindFrame,
    requested_report_module: Option<&InspectModule>,
) -> ModuleIdentity {
    let module = requested.module.as_ref();
    ModuleIdentity {
        code_id: module
            .and_then(|module| module.code_id.clone())
            .or_else(|| requested_report_module.map(|module| module.code_id.clone())),
        debug_id: module
            .and_then(|module| module.debug_id.clone())
            .or_else(|| requested_report_module.and_then(|module| module.debug_id.clone())),
        image_base: module.map(|module| module.image_base).or_else(|| {
            requested_report_module.map(|module| parse_numeric_address(&module.image_base))
        }),
        image_size: module
            .map(|module| module.image_size)
            .or_else(|| requested_report_module.map(|module| module.image_size as u64)),
    }
}

fn response_module_range(module: &Value) -> Option<(u64, u64)> {
    Some((
        module.get("image_addr").and_then(parse_address)?,
        module.get("image_size").and_then(parse_address)?,
    ))
}

fn response_module_range_contains(module: &Value, address: u64) -> bool {
    response_module_range(module).is_some_and(|(base, size)| range_contains(base, size, address))
}

fn range_contains(base: u64, size: u64, address: u64) -> bool {
    address >= base && address < base.saturating_add(size)
}

fn normalize_module_id(value: &str) -> String {
    value
        .chars()
        .filter(|character| character.is_ascii_hexdigit())
        .flat_map(char::to_lowercase)
        .collect()
}

fn same_basename(left: &str, right: &str) -> bool {
    basename_lower(left) == basename_lower(right)
}

fn basename_lower(value: &str) -> String {
    basename(value).to_ascii_lowercase()
}

fn merge_symbol(
    frames: &mut BTreeMap<FrameKey, SymbolicatedFrame>,
    key: FrameKey,
    symbol: SymbolicatedFrame,
) {
    let Some(existing) = frames.get_mut(&key) else {
        frames.insert(key, symbol);
        return;
    };
    // Preserve every same-physical-frame response as inline metadata while
    // retaining the last response as the primary lookup value for backwards
    // compatibility with the canonical frame shape.
    let previous = SymbolicatedFrame {
        function: existing.function.take(),
        file: existing.file.take(),
        line: existing.line.take(),
        inline: Vec::new(),
    };
    let mut inline = std::mem::take(&mut existing.inline);
    inline.push(previous);
    inline.push(SymbolicatedFrame {
        function: symbol.function.clone(),
        file: symbol.file.clone(),
        line: symbol.line,
        inline: Vec::new(),
    });
    existing.function = symbol.function;
    existing.file = symbol.file;
    existing.line = symbol.line;
    existing.inline = inline;
}

fn basename(value: &str) -> &str {
    value.rsplit(['\\', '/']).next().unwrap_or(value)
}

fn parse_address(value: &Value) -> Option<u64> {
    value.as_u64().or_else(|| {
        value.as_str().and_then(|text| {
            u64::from_str_radix(text.trim_start_matches("0x").trim_start_matches("0X"), 16).ok()
        })
    })
}

fn parse_numeric_address(value: &str) -> u64 {
    u64::from_str_radix(value.trim().trim_start_matches("0x").trim_start_matches("0X"), 16)
        .unwrap_or(0)
}

fn trace_thread_id(trace: &Value) -> Result<Option<u32>, ()> {
    for field in ["thread_id", "threadId", "thread"] {
        let Some(value) = trace.get(field) else {
            continue;
        };
        if value.is_null() {
            return Ok(None);
        }
        return parse_thread_id(value).map(Some).ok_or(());
    }
    Ok(None)
}

fn parse_thread_id(value: &Value) -> Option<u32> {
    if let Some(value) = value.as_u64() {
        return u32::try_from(value).ok();
    }
    if let Some(value) = value.as_str() {
        let value = value.trim();
        return if let Some(value) = value.strip_prefix("0x").or_else(|| value.strip_prefix("0X")) {
            u32::from_str_radix(value, 16).ok()
        } else {
            value.parse::<u32>().ok()
        };
    }
    value.get("id").and_then(parse_thread_id)
}

fn string_field(value: &Value, fields: &[&str]) -> Option<String> {
    fields.iter().find_map(|field| value.get(*field).and_then(Value::as_str).map(ToOwned::to_owned))
}

fn number_field(value: &Value, fields: &[&str]) -> Option<u64> {
    fields.iter().find_map(|field| value.get(*field).and_then(parse_address))
}

#[cfg(test)]
mod tests {
    use super::{parse_address, parse_result, request_body, symbolicate, unique_index, FrameKey};
    use crate::minidump::{InspectDump, InspectModule, InspectProcess, InspectReport};
    use crate::unwind::{UnwindFrame, UnwindModule, UnwindReport, UnwindThread};
    use serde_json::json;
    use std::io::{Read, Write};
    use std::net::{TcpListener, TcpStream};
    use std::thread;

    fn empty_report() -> InspectReport {
        InspectReport {
            schema_version: "0.1".to_owned(),
            dump: InspectDump {
                kind: "user_minidump".to_owned(),
                size: 1,
                signature: "MDMP".to_owned(),
                number_of_streams: 1,
                flags: "0x0".to_owned(),
                timestamp: None,
            },
            process: InspectProcess {
                pid: None,
                architecture: "x86_64".to_owned(),
                os: "windows".to_owned(),
                os_version: None,
                platform_id: None,
                build_number: None,
                processor_count: None,
            },
            exception: None,
            crash_thread_id: None,
            threads: Vec::new(),
            modules: Vec::new(),
            warnings: Vec::new(),
        }
    }

    fn read_http_request(stream: &mut TcpStream) -> String {
        let mut bytes = Vec::new();
        let mut chunk = [0_u8; 4096];
        loop {
            let count = stream.read(&mut chunk).expect("read HTTP request");
            if count == 0 {
                break;
            }
            bytes.extend_from_slice(&chunk[..count]);
            let Some(header_end) = bytes.windows(4).position(|window| window == b"\r\n\r\n") else {
                continue;
            };
            let content_length = String::from_utf8_lossy(&bytes[..header_end])
                .lines()
                .find_map(|line| {
                    line.strip_prefix("Content-Length:")
                        .or_else(|| line.strip_prefix("content-length:"))
                        .and_then(|value| value.trim().parse::<usize>().ok())
                })
                .unwrap_or(0);
            if bytes.len() >= header_end + 4 + content_length {
                break;
            }
        }
        String::from_utf8_lossy(&bytes).into_owned()
    }

    fn respond(stream: &mut TcpStream, body: &str, status: &str) {
        let response = format!(
            "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
            body.len()
        );
        stream.write_all(response.as_bytes()).expect("write HTTP response");
        stream.flush().expect("flush HTTP response");
    }

    #[test]
    fn request_omits_sources_and_uses_absolute_instruction_addresses() {
        let report = InspectReport {
            schema_version: "0.1".to_owned(),
            dump: InspectDump {
                kind: "user_minidump".to_owned(),
                size: 1,
                signature: "MDMP".to_owned(),
                number_of_streams: 1,
                flags: "0x0".to_owned(),
                timestamp: None,
            },
            process: InspectProcess {
                pid: None,
                architecture: "x86_64".to_owned(),
                os: "windows".to_owned(),
                os_version: None,
                platform_id: None,
                build_number: None,
                processor_count: None,
            },
            exception: None,
            crash_thread_id: None,
            threads: Vec::new(),
            modules: vec![InspectModule {
                code_file: "app.exe".to_owned(),
                code_id: "ABC".to_owned(),
                debug_file: None,
                debug_id: None,
                image_base: "0x1000".to_owned(),
                image_size: 1,
                time_date_stamp: "0x0".to_owned(),
                checksum: "0x0".to_owned(),
            }],
            warnings: Vec::new(),
        };
        let body = request_body(&report, &UnwindReport { threads: Vec::new() });
        assert!(body.get("sources").is_none());
        assert_eq!(body["modules"][0]["type"], "pe");
        assert_eq!(body["modules"][0]["image_addr"], 0x1000);
        assert_eq!(body["modules"][0]["image_size"].as_u64(), Some(1));
        assert!(body["modules"][0]["image_size"].is_number());
        assert_eq!(parse_address(&json!("0x10")), Some(16));
        assert_eq!(parse_address(&json!("0X10")), Some(16));
    }

    #[test]
    fn terminal_module_status_is_retained_without_stacktraces() {
        let value = json!({
            "status": "completed",
            "modules": [{
                "code_file": "C:\\Windows\\System32\\ntdll.dll",
                "code_id": "AABB",
                "debug_file": "ntdll.pdb",
                "debug_id": "23E72AA7-E387-3AC7-9882-BF6E394DA71E-1",
                "debug_status": "found"
            }]
        });
        let result = parse_result(&value, &empty_report(), &UnwindReport { threads: Vec::new() });
        assert_eq!(result.modules.len(), 1);
        assert_eq!(
            result.module_debug_status(
                r"c:\windows\system32\NTDLL.DLL",
                Some("aabb"),
                Some("NTDLL.PDB"),
                Some("23e72aa7e3873ac79882bf6e394da71e1"),
            ),
            Some("found")
        );
    }

    #[test]
    fn response_without_package_uses_the_corresponding_requested_module() {
        let report = InspectReport {
            schema_version: "0.1".to_owned(),
            dump: InspectDump {
                kind: "user_minidump".to_owned(),
                size: 1,
                signature: "MDMP".to_owned(),
                number_of_streams: 1,
                flags: "0x0".to_owned(),
                timestamp: None,
            },
            process: InspectProcess {
                pid: None,
                architecture: "x86_64".to_owned(),
                os: "windows".to_owned(),
                os_version: None,
                platform_id: None,
                build_number: None,
                processor_count: None,
            },
            exception: None,
            crash_thread_id: None,
            threads: Vec::new(),
            modules: vec![InspectModule {
                code_file: "app.exe".to_owned(),
                code_id: "ABC".to_owned(),
                debug_file: None,
                debug_id: None,
                image_base: "0x1000".to_owned(),
                image_size: 0x1000,
                time_date_stamp: "0x0".to_owned(),
                checksum: "0x0".to_owned(),
            }],
            warnings: Vec::new(),
        };
        let unwind = UnwindReport {
            threads: vec![UnwindThread {
                id: 1,
                frames: vec![UnwindFrame {
                    unwind_method: None,
                    instruction: 0x1100,
                    resume_address: 0x1100,
                    module: Some(UnwindModule {
                        code_file: "app.exe".to_owned(),
                        code_id: Some("ABC".to_owned()),
                        debug_file: None,
                        debug_id: Some("DBG".to_owned()),
                        image_base: 0x1000,
                        image_size: 0x1000,
                    }),
                    function: None,
                    file: None,
                    line: None,
                    trust: "context".to_owned(),
                    inline: false,
                }],
            }],
        };
        let value = json!({"status":"completed","stacktraces":[{"frames":[{"original_index":0,"instruction_addr":"0x10ff","package":null,"function":"app::entry"}]}],"modules":[]});
        let parsed = parse_result(&value, &report, &unwind);
        let key = parsed.frames.keys().next().expect("frame key");
        assert_eq!(key.module, "app.exe");
        assert_eq!(key.instruction_addr, 0x1100);
        assert_eq!(parsed.frames[key].function.as_deref(), Some("app::entry"));
        assert_eq!(parsed.rejected_frames, 0);
    }

    #[test]
    fn response_thread_id_maps_multiple_traces_without_positional_cross_fill() {
        let mut report = empty_report();
        report.modules.push(InspectModule {
            code_file: "app.exe".to_owned(),
            code_id: "ABC".to_owned(),
            debug_file: None,
            debug_id: None,
            image_base: "0x1000".to_owned(),
            image_size: 0x1000,
            time_date_stamp: "0x0".to_owned(),
            checksum: "0x0".to_owned(),
        });
        let module = |instruction| UnwindFrame {
            unwind_method: None,
            instruction,
            resume_address: instruction,
            module: Some(UnwindModule {
                code_file: "app.exe".to_owned(),
                code_id: Some("ABC".to_owned()),
                debug_file: None,
                debug_id: None,
                image_base: 0x1000,
                image_size: 0x1000,
            }),
            function: None,
            file: None,
            line: None,
            trust: "context".to_owned(),
            inline: false,
        };
        let unwind = UnwindReport {
            // Deliberately order the unwind threads opposite to the response
            // traces.  The explicit thread_id is the only safe association.
            threads: vec![
                UnwindThread { id: 11, frames: vec![module(0x1100)] },
                UnwindThread { id: 22, frames: vec![module(0x1200)] },
            ],
        };
        let value = json!({
            "status": "completed",
            "stacktraces": [
                {"thread_id": 22, "frames": [{"original_index": 0, "instruction_addr": "0x1200", "package": "app.exe", "function": "thread::two"}]},
                {"thread_id": 11, "frames": [{"original_index": 0, "instruction_addr": "0x1100", "package": "app.exe", "function": "thread::one"}]}
            ],
            "modules": []
        });
        let parsed = parse_result(&value, &report, &unwind);
        assert_eq!(parsed.rejected_frames, 0);
        assert_eq!(parsed.frames.len(), 2);
        assert_eq!(
            parsed.frames[&FrameKey { module: "app.exe".to_owned(), instruction_addr: 0x1100 }]
                .function
                .as_deref(),
            Some("thread::one")
        );
        assert_eq!(
            parsed.frames[&FrameKey { module: "app.exe".to_owned(), instruction_addr: 0x1200 }]
                .function
                .as_deref(),
            Some("thread::two")
        );
    }

    #[test]
    fn provenance_rejects_wrong_index_address_and_module_without_fallback() {
        let report = InspectReport {
            schema_version: "0.1".to_owned(),
            dump: InspectDump {
                kind: "user_minidump".to_owned(),
                size: 1,
                signature: "MDMP".to_owned(),
                number_of_streams: 1,
                flags: "0x0".to_owned(),
                timestamp: None,
            },
            process: InspectProcess {
                pid: None,
                architecture: "x86_64".to_owned(),
                os: "windows".to_owned(),
                os_version: None,
                platform_id: None,
                build_number: None,
                processor_count: None,
            },
            exception: None,
            crash_thread_id: None,
            threads: Vec::new(),
            modules: vec![InspectModule {
                code_file: "app.exe".to_owned(),
                code_id: "ABC".to_owned(),
                debug_file: None,
                debug_id: None,
                image_base: "0x1000".to_owned(),
                image_size: 0x1000,
                time_date_stamp: "0x0".to_owned(),
                checksum: "0x0".to_owned(),
            }],
            warnings: Vec::new(),
        };
        let unwind = UnwindReport {
            threads: vec![UnwindThread {
                id: 1,
                frames: vec![
                    UnwindFrame {
                        unwind_method: None,
                        instruction: 0x1100,
                        resume_address: 0x1100,
                        module: Some(UnwindModule {
                            code_file: "app.exe".to_owned(),
                            code_id: Some("ABC".to_owned()),
                            debug_file: None,
                            debug_id: None,
                            image_base: 0x1000,
                            image_size: 0x1000,
                        }),
                        function: None,
                        file: None,
                        line: None,
                        trust: "context".to_owned(),
                        inline: false,
                    },
                    UnwindFrame {
                        unwind_method: None,
                        instruction: 0x1200,
                        resume_address: 0x1200,
                        module: Some(UnwindModule {
                            code_file: "app.exe".to_owned(),
                            code_id: Some("ABC".to_owned()),
                            debug_file: None,
                            debug_id: None,
                            image_base: 0x1000,
                            image_size: 0x1000,
                        }),
                        function: None,
                        file: None,
                        line: None,
                        trust: "cfi".to_owned(),
                        inline: false,
                    },
                ],
            }],
        };
        let value = json!({
            "status": "completed",
            "stacktraces": [{"frames": [
                {"original_index": 1, "instruction_addr": "0x1100", "function": "wrong::index"},
                {"original_index": 0, "instruction_addr": "0x1200", "function": "wrong::address"},
                {"original_index": 0, "instruction_addr": "0x1100", "package": "other.dll", "function": "wrong::module"},
                {"original_index": 99, "instruction_addr": "0x1100", "function": "wrong::range"}
            ]}],
            "modules": []
        });
        let parsed = parse_result(&value, &report, &unwind);
        assert!(parsed.frames.is_empty(), "rejected responses must not enter the symbol map");
        assert_eq!(parsed.rejected_frames, 4);
    }

    #[test]
    fn provenance_accepts_multiple_inline_records_for_one_request_frame() {
        let report = InspectReport {
            schema_version: "0.1".to_owned(),
            dump: InspectDump {
                kind: "user_minidump".to_owned(),
                size: 1,
                signature: "MDMP".to_owned(),
                number_of_streams: 1,
                flags: "0x0".to_owned(),
                timestamp: None,
            },
            process: InspectProcess {
                pid: None,
                architecture: "x86_64".to_owned(),
                os: "windows".to_owned(),
                os_version: None,
                platform_id: None,
                build_number: None,
                processor_count: None,
            },
            exception: None,
            crash_thread_id: None,
            threads: Vec::new(),
            modules: vec![InspectModule {
                code_file: "app.exe".to_owned(),
                code_id: "ABC".to_owned(),
                debug_file: None,
                debug_id: None,
                image_base: "0x1000".to_owned(),
                image_size: 0x1000,
                time_date_stamp: "0x0".to_owned(),
                checksum: "0x0".to_owned(),
            }],
            warnings: Vec::new(),
        };
        let unwind = UnwindReport {
            threads: vec![UnwindThread {
                id: 1,
                frames: vec![UnwindFrame {
                    unwind_method: None,
                    instruction: 0x1100,
                    resume_address: 0x1100,
                    module: Some(UnwindModule {
                        code_file: "app.exe".to_owned(),
                        code_id: Some("ABC".to_owned()),
                        debug_file: None,
                        debug_id: None,
                        image_base: 0x1000,
                        image_size: 0x1000,
                    }),
                    function: None,
                    file: None,
                    line: None,
                    trust: "context".to_owned(),
                    inline: false,
                }],
            }],
        };
        let value = json!({
            "status": "completed",
            "stacktraces": [{"frames": [
                {"original_index": 0, "instruction_addr": "0x1100", "package": "app.exe", "function": "inline::outer"},
                {"original_index": 0, "instruction_addr": "0x10ff", "package": "app.exe", "function": "app::physical"}
            ]}],
            "modules": []
        });
        let parsed = parse_result(&value, &report, &unwind);
        let key = FrameKey { module: "app.exe".to_owned(), instruction_addr: 0x1100 };
        let symbol = parsed.frames.get(&key).expect("physical frame symbol");
        assert_eq!(parsed.rejected_frames, 0);
        assert_eq!(parsed.frames.len(), 1);
        assert_eq!(symbol.function.as_deref(), Some("app::physical"));
        assert_eq!(symbol.inline.len(), 2);
        assert_eq!(symbol.inline[0].function.as_deref(), Some("inline::outer"));
        assert_eq!(symbol.inline[1].function.as_deref(), Some("app::physical"));
    }

    #[test]
    fn provenance_accepts_renamed_artifact_path_when_module_identity_matches() {
        let report = InspectReport {
            schema_version: "0.1".to_owned(),
            dump: InspectDump {
                kind: "user_minidump".to_owned(),
                size: 1,
                signature: "MDMP".to_owned(),
                number_of_streams: 1,
                flags: "0x0".to_owned(),
                timestamp: None,
            },
            process: InspectProcess {
                pid: None,
                architecture: "x86_64".to_owned(),
                os: "windows".to_owned(),
                os_version: None,
                platform_id: None,
                build_number: None,
                processor_count: None,
            },
            exception: None,
            crash_thread_id: None,
            threads: Vec::new(),
            modules: vec![InspectModule {
                code_file: r"E:\dump\original.exe".to_owned(),
                code_id: "ABC".to_owned(),
                debug_file: Some(r"E:\dump\original.pdb".to_owned()),
                debug_id: Some("DBG".to_owned()),
                image_base: "0x1000".to_owned(),
                image_size: 0x1000,
                time_date_stamp: "0x0".to_owned(),
                checksum: "0x0".to_owned(),
            }],
            warnings: Vec::new(),
        };
        let unwind = UnwindReport {
            threads: vec![UnwindThread {
                id: 1,
                frames: vec![UnwindFrame {
                    unwind_method: None,
                    instruction: 0x1100,
                    resume_address: 0x1100,
                    module: Some(UnwindModule {
                        code_file: r"E:\worker\golden_target_debug.exe".to_owned(),
                        code_id: Some("abc".to_owned()),
                        debug_file: Some(r"E:\worker\golden_target_debug.pdb".to_owned()),
                        debug_id: Some("dbg".to_owned()),
                        image_base: 0x1000,
                        image_size: 0x1000,
                    }),
                    function: None,
                    file: None,
                    line: None,
                    trust: "context".to_owned(),
                    inline: false,
                }],
            }],
        };
        let value = json!({
            "status": "completed",
            "stacktraces": [{"frames": [{
                "original_index": 0,
                "instruction_addr": "0x10ff",
                "package": "E:\\symbols\\published-renamed-artifact.exe",
                "function": "renamed::symbol"
            }]}],
            "modules": [{
                "code_file": "E:\\symbols\\published-renamed-artifact.exe",
                "code_id": "abc",
                "debug_id": "dbg",
                "image_addr": "0x1000",
                "image_size": 4096
            }]
        });
        let parsed = parse_result(&value, &report, &unwind);
        let key = FrameKey { module: r"e:\dump\original.exe".to_owned(), instruction_addr: 0x1100 };
        assert_eq!(parsed.rejected_frames, 0);
        assert_eq!(parsed.frames[&key].function.as_deref(), Some("renamed::symbol"));
    }

    #[test]
    fn response_without_package_does_not_guess_an_ambiguous_module() {
        let module = |name: &str, id: &str| InspectModule {
            code_file: name.to_owned(),
            code_id: id.to_owned(),
            debug_file: None,
            debug_id: None,
            image_base: "0x1000".to_owned(),
            image_size: 0x1000,
            time_date_stamp: "0x0".to_owned(),
            checksum: "0x0".to_owned(),
        };
        let report = InspectReport {
            schema_version: "0.1".to_owned(),
            dump: InspectDump {
                kind: "user_minidump".to_owned(),
                size: 1,
                signature: "MDMP".to_owned(),
                number_of_streams: 1,
                flags: "0x0".to_owned(),
                timestamp: None,
            },
            process: InspectProcess {
                pid: None,
                architecture: "x86_64".to_owned(),
                os: "windows".to_owned(),
                os_version: None,
                platform_id: None,
                build_number: None,
                processor_count: None,
            },
            exception: None,
            crash_thread_id: None,
            threads: Vec::new(),
            modules: vec![module("first.dll", "A"), module("second.dll", "B")],
            warnings: Vec::new(),
        };
        let value = json!({
            "status":"completed",
            "stacktraces":[{"frames":[{"instruction_addr":"0x1100","function":"ambiguous"}]}],
            "modules":[]
        });
        let parsed = parse_result(&value, &report, &UnwindReport { threads: Vec::new() });
        assert!(parsed.frames.is_empty(), "ambiguous address must not cross-fill a module");
        assert_eq!(parsed.rejected_frames, 1);
    }

    #[test]
    fn empty_response_module_candidates_are_rejected_without_panic() {
        assert_eq!(unique_index(Vec::new()), None);
    }

    #[test]
    fn pending_poll_404_reposts_the_entire_symbolication_body() {
        let listener = TcpListener::bind(("127.0.0.1", 0)).expect("bind local gateway");
        let endpoint = format!("http://{}", listener.local_addr().expect("gateway address"));
        let server = thread::spawn(move || {
            let responses = [
                ("200 OK", r#"{"status":"pending","request_id":"abc123"}"#),
                ("404 Not Found", r#"{"error":"expired"}"#),
                ("200 OK", r#"{"status":"completed","stacktraces":[]}"#),
            ];
            let mut requests = Vec::new();
            for (status, body) in responses {
                let (mut stream, _) = listener.accept().expect("accept gateway request");
                requests.push(read_http_request(&mut stream));
                respond(&mut stream, body, status);
            }
            requests
        });

        let (result, raw) = symbolicate(
            &endpoint,
            "wsp_p0test",
            7,
            2,
            &empty_report(),
            &UnwindReport { threads: Vec::new() },
        )
        .expect("404 after pending should trigger a repost");
        let requests = server.join().expect("gateway thread");
        assert_eq!(requests.len(), 3);
        assert!(requests[0].starts_with("POST /symbolicate?scope=wsp_p0test&inventory=7&timeout=2"));
        assert!(requests[1].starts_with("GET /requests/abc123"));
        assert!(requests[2].starts_with("POST /symbolicate?scope=wsp_p0test&inventory=7&timeout=2"));
        let first_body = requests[0].split_once("\r\n\r\n").expect("first POST body").1;
        let repost_body = requests[2].split_once("\r\n\r\n").expect("repost body").1;
        assert_eq!(first_body, repost_body, "pending 404 must repost the exact JSON body");
        assert_eq!(
            raw.attempts.iter().map(|attempt| attempt.operation.as_str()).collect::<Vec<_>>(),
            ["post:0", "poll:0:0", "post:1"]
        );
        assert_eq!(raw.inventory_version, 7);
        assert!(result.frames.is_empty());
    }
}
