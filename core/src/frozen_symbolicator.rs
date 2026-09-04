//! Content-partitioned Symbolicator transport for the frozen 1.1 path.
//! Plans are constructed here and cannot be deserialized from upload input.
//! A private request has exactly one content-addressed source. Public policy
//! is deployment-owned and is consulted only for an explicit `none` selection.

use crate::canonical::sha256_hex;
use crate::canonical_v11::{
    EvidenceError, FrameSymbol, FrozenSelection, ModuleIdentity, ObjectRef, SourceOutcome,
};
use crate::minidump::{InspectModule, InspectReport};
use crate::symbolicator::SymbolicatedFrame;
use crate::unwind::UnwindReport;
use reqwest::blocking::Client;
use serde::Serialize;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::io::Read;
use std::time::{Duration, Instant};

fn check(ok: bool, reason: &str) -> Result<(), EvidenceError> {
    if ok {
        Ok(())
    } else {
        Err(EvidenceError(reason.to_owned()))
    }
}

/// `root` is the managed content service root, not a producer-provided URL.
pub fn pair_source(pair_id: &str, root: &str) -> Result<Value, EvidenceError> {
    check(
        pair_id.len() == 64
            && pair_id.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "invalid source pair ID",
    )?;
    safe_http_url(root)?;
    Ok(json!({"id":format!("crash-cap:pair:{pair_id}:http-v2"),"type":"http",
        "url":format!("{}/{pair_id}/",root.trim_end_matches('/')),
        "layout":{"type":"unified","casing":"lowercase"},"filters":{"filetypes":["pe","pdb"]},"is_public":false}))
}

fn safe_http_url(value: &str) -> Result<reqwest::Url, EvidenceError> {
    let url = reqwest::Url::parse(value)
        .map_err(|_| EvidenceError("invalid source/engine URL".to_owned()))?;
    check(
        matches!(url.scheme(), "http" | "https")
            && url.host_str().is_some()
            && url.username().is_empty()
            && url.password().is_none()
            && url.query().is_none()
            && url.fragment().is_none(),
        "source/engine URL must be HTTP(S), without credentials, query or fragment",
    )?;
    Ok(url)
}

#[derive(Debug, Clone, Serialize)]
pub struct FrameRef {
    pub thread_index: usize,
    pub physical_frame_index: usize,
    pub module_index: usize,
    pub instruction: u64,
}

#[derive(Debug, Clone, Serialize)]
pub struct Partition {
    key: String,
    pair_id: Option<String>,
    module_indexes: Vec<usize>,
    captured_modules: Vec<InspectModule>,
    architecture: String,
    frame_refs: Vec<FrameRef>,
    source_ids: BTreeSet<String>,
    request: Value,
}

impl Partition {
    pub fn key(&self) -> &str {
        &self.key
    }
    pub fn request(&self) -> &Value {
        &self.request
    }
    pub fn frame_refs(&self) -> &[FrameRef] {
        &self.frame_refs
    }
    pub fn module_indexes(&self) -> &[usize] {
        &self.module_indexes
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Plan {
    pub partitions: Vec<Partition>,
    pub blocked_modules: Vec<usize>,
}

pub fn plan(
    report: &InspectReport,
    unwind: &UnwindReport,
    selections: &[FrozenSelection],
    managed_root: &str,
    public_sources: &[Value],
) -> Result<Plan, EvidenceError> {
    check(selections.len() == report.modules.len(), "selection does not cover captured modules")?;
    check(
        unwind.threads.len() == report.threads.len()
            && unwind.threads.iter().zip(&report.threads).all(|(a, b)| a.id == b.id),
        "unwind thread instances differ from inspect",
    )?;
    let mut public_ids = BTreeSet::new();
    for source in public_sources {
        let id = source
            .get("id")
            .and_then(Value::as_str)
            .filter(|s| !s.is_empty())
            .ok_or_else(|| EvidenceError("public source ID is missing".to_owned()))?;
        check(
            !id.starts_with("crash-cap:pair:") && public_ids.insert(id.to_owned()),
            "public sources have duplicate/reserved IDs",
        )?;
        check(
            source.get("type").and_then(Value::as_str) == Some("http"),
            "only explicit HTTP public sources are supported",
        )?;
        safe_http_url(source.get("url").and_then(Value::as_str).unwrap_or(""))?;
    }
    let mut ranges = Vec::new();
    let mut groups: BTreeMap<String, Partition> = BTreeMap::new();
    let mut blocked_modules = Vec::new();
    for (index, (selection, module)) in selections.iter().zip(&report.modules).enumerate() {
        selection.validate(index, module, &report.process.architecture)?;
        let base = address(&Value::String(module.image_base.clone()))?;
        let end = base
            .checked_add(u64::from(module.image_size))
            .ok_or_else(|| EvidenceError("module range overflow".to_owned()))?;
        if end > base {
            ranges.push((base, end, index));
        }
        let (key, pair_id, sources) = match selection.state.as_str() {
            "unique" => {
                let pair = selection.selected_pair_id.as_ref().unwrap();
                (pair.clone(), Some(pair.clone()), vec![pair_source(pair, managed_root)?])
            }
            // Keep public modules separate too: return-position and module
            // provenance must stay independent even for colliding Debug IDs.
            "none" if !public_sources.is_empty() => {
                (format!("public:{index}"), None, public_sources.to_vec())
            }
            _ => {
                blocked_modules.push(index);
                continue;
            }
        };
        let group=groups.entry(key.clone()).or_insert_with(||Partition {key,pair_id,module_indexes:vec![],captured_modules:vec![],architecture:report.process.architecture.clone(),frame_refs:vec![],
            source_ids:sources.iter().map(|s|s["id"].as_str().unwrap().to_owned()).collect(),
            request:json!({"platform":"native","modules":[],"stacktraces":[],"sources":sources,"options":{"dif_candidates":true,"apply_source_context":false}})});
        if let Some(first) = group.captured_modules.first() {
            let a = ModuleIdentity::captured(first, &report.process.architecture)?;
            let b = ModuleIdentity::captured(module, &report.process.architecture)?;
            check(
                a.code_id == b.code_id
                    && (a.debug_id.is_none() || b.debug_id.is_none() || a.debug_id == b.debug_id),
                "one selected pair has contradictory captured identities",
            )?;
        }
        group.module_indexes.push(index);
        group.captured_modules.push(module.clone());
        group.request["modules"].as_array_mut().unwrap().push(json!({"type":"pe","code_file":module.code_file,"code_id":module.code_id,"debug_file":module.debug_file,"debug_id":module.debug_id,"image_addr":format!("0x{base:x}"),"image_size":module.image_size}));
    }
    ranges.sort_unstable();
    check(
        ranges.windows(2).all(|w| w[0].1 <= w[1].0),
        "overlapping captured modules are ambiguous",
    )?;
    for (thread_index, thread) in unwind.threads.iter().enumerate() {
        for (physical_frame_index, frame) in thread.frames.iter().enumerate() {
            let Some((_, _, module_index)) =
                ranges.iter().find(|(b, e, _)| frame.instruction >= *b && frame.instruction < *e)
            else {
                continue;
            };
            let Some(group) = groups.values_mut().find(|g| g.module_indexes.contains(module_index))
            else {
                continue;
            };
            group.frame_refs.push(FrameRef {
                thread_index,
                physical_frame_index,
                module_index: *module_index,
                instruction: frame.instruction,
            });
            group.request["stacktraces"]
                .as_array_mut()
                .unwrap()
                .push(json!({"frames":[{"instruction_addr":format!("0x{:x}",frame.instruction)}]}));
        }
    }
    Ok(Plan {
        partitions: groups.into_values().filter(|g| !g.frame_refs.is_empty()).collect(),
        blocked_modules,
    })
}

#[derive(Debug, Clone, Serialize)]
pub struct Attempt {
    pub operation: String,
    pub status: Option<u16>,
    pub response_sha256: Option<String>,
    pub reason: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct TransportEvidence {
    pub request_sha256: String,
    pub attempts: Vec<Attempt>,
    pub response: Option<Value>,
    pub failure: Option<String>,
}

/// Direct pinned Symbolicator endpoint, not the legacy gateway that supplies
/// its own sources. A missing ephemeral polling object reposts the SAME body.
/// All attempts share a total deadline; response bytes are bounded to 32 MiB.
pub fn execute(
    endpoint: &str,
    partition: &Partition,
    budget_seconds: u64,
) -> Result<TransportEvidence, EvidenceError> {
    safe_http_url(endpoint)?;
    let endpoint = endpoint.trim_end_matches('/');
    let budget = Duration::from_secs(budget_seconds.clamp(1, 300));
    let deadline = Instant::now() + budget;
    let client = Client::builder()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(|_| EvidenceError("could not create frozen source client".to_owned()))?;
    let body = serde_json::to_vec(partition.request())
        .map_err(|_| EvidenceError("invalid partition request".to_owned()))?;
    let mut evidence = TransportEvidence {
        request_sha256: sha256_hex(&body),
        attempts: vec![],
        response: None,
        failure: None,
    };
    let mut poll_id: Option<String> = None;
    let mut posts = 0;
    for attempt_index in 0..27 {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            evidence.failure = Some("partition_deadline_exceeded".to_owned());
            break;
        }
        let (operation, request) = if let Some(id) = &poll_id {
            (
                format!("poll:{attempt_index}"),
                client.get(format!("{endpoint}/requests/{id}")).query(&[("timeout", "1")]),
            )
        } else {
            if posts == 3 {
                evidence.failure = Some("repost_budget_exhausted".to_owned());
                break;
            }
            posts += 1;
            (
                format!("post:{posts}"),
                client
                    .post(format!("{endpoint}/symbolicate"))
                    .query(&[("timeout", "1"), ("scope", "crash-cap:frozen:v1")])
                    .header("content-type", "application/json")
                    .body(body.clone()),
            )
        };
        let mut trace = Attempt { operation, status: None, response_sha256: None, reason: None };
        let result = request.timeout(remaining).send();
        match result {
            Err(error) => {
                trace.reason = Some(
                    if error.is_timeout() { "transport_timeout" } else { "transport_error" }
                        .to_owned(),
                );
                evidence.failure = trace.reason.clone();
                evidence.attempts.push(trace);
                break;
            }
            Ok(response) => {
                let status = response.status().as_u16();
                trace.status = Some(status);
                if status == 404 && poll_id.is_some() {
                    evidence.attempts.push(trace);
                    poll_id = None;
                    continue;
                }
                let mut bytes = Vec::new();
                if response.take(32 * 1024 * 1024 + 1).read_to_end(&mut bytes).is_err() {
                    trace.reason = Some("response_read_failed".to_owned());
                } else if bytes.len() > 32 * 1024 * 1024 {
                    trace.reason = Some("response_too_large".to_owned());
                } else {
                    trace.response_sha256 = Some(sha256_hex(&bytes));
                }
                if trace.reason.is_none() && !(200..300).contains(&status) {
                    trace.reason = Some(format!("http_{status}"));
                }
                let value = if trace.reason.is_none() {
                    serde_json::from_slice::<Value>(&bytes).ok()
                } else {
                    None
                };
                if trace.reason.is_none() && value.is_none() {
                    trace.reason = Some("invalid_response_json".to_owned());
                }
                if trace.reason.is_some() {
                    evidence.failure = trace.reason.clone();
                    evidence.attempts.push(trace);
                    break;
                }
                let value = value.unwrap();
                evidence.attempts.push(trace);
                match value.get("status").and_then(Value::as_str) {
                    Some("completed") => {
                        evidence.response = Some(value);
                        return Ok(evidence);
                    }
                    Some("pending") => {
                        let id = value
                            .get("request_id")
                            .or_else(|| value.get("id"))
                            .and_then(Value::as_str)
                            .map(|s| s.strip_prefix("/requests/").unwrap_or(s));
                        if let Some(id) = id.filter(|s| {
                            !s.is_empty()
                                && s.len() <= 128
                                && s.bytes().all(|b| b.is_ascii_hexdigit() || b == b'-')
                        }) {
                            poll_id = Some(id.to_owned());
                        } else {
                            evidence.failure = Some("invalid_pending_request_id".to_owned());
                            break;
                        }
                    }
                    _ => {
                        evidence.failure = Some("unexpected_response_state".to_owned());
                        evidence.response = Some(value);
                        break;
                    }
                }
            }
        }
    }
    if evidence.failure.is_none() {
        evidence.failure = Some("poll_budget_exhausted".to_owned());
    }
    Ok(evidence)
}

#[derive(Debug, Clone)]
pub struct Collected {
    pub frames: Vec<FrameSymbol>,
    pub modules: Vec<(usize, Vec<SourceOutcome>)>,
}

pub fn collect(
    partition: &Partition,
    response: &Value,
    diagnostic_ref: ObjectRef,
) -> Result<Collected, EvidenceError> {
    check(
        response.get("status").and_then(Value::as_str) == Some("completed"),
        "partition response is not completed",
    )?;
    check(
        !diagnostic_ref.object_key.is_empty()
            && diagnostic_ref.sha256.len() == 64
            && diagnostic_ref
                .sha256
                .bytes()
                .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b)),
        "invalid diagnostic object reference",
    )?;
    let modules = response
        .get("modules")
        .and_then(Value::as_array)
        .ok_or_else(|| EvidenceError("response modules missing".to_owned()))?;
    let traces = response
        .get("stacktraces")
        .and_then(Value::as_array)
        .ok_or_else(|| EvidenceError("response traces missing".to_owned()))?;
    check(
        modules.len() == partition.module_indexes.len()
            && traces.len() == partition.frame_refs.len(),
        "partition response changed module/trace cardinality",
    )?;
    let mut owners = BTreeMap::new();
    let mut module_outcomes = Vec::new();
    for (local_index, (returned, expected)) in
        modules.iter().zip(&partition.captured_modules).enumerate()
    {
        let expected_identity = ModuleIdentity::captured(expected, &partition.architecture)?;
        // Without downloadable debug material Symbolicator cannot infer an
        // architecture. Preserve failure diagnostics while still checking the
        // captured IDs/range below; successful symbols require an exact arch.
        let unavailable_arch = returned.get("arch").and_then(Value::as_str) == Some("unknown")
            && matches!(
                returned.get("debug_status").and_then(Value::as_str),
                Some("missing" | "fetching_failed" | "malformed" | "unsupported")
            );
        check(
            returned.get("type").and_then(Value::as_str) == Some("pe")
                && (partition.architecture == "unknown"
                    || unavailable_arch
                    || returned.get("arch").and_then(Value::as_str)
                        == Some(partition.architecture.as_str())),
            "returned module type or architecture differs from request",
        )?;
        let mut observed = expected.clone();
        observed.code_id = returned.get("code_id").and_then(Value::as_str).unwrap_or("").to_owned();
        observed.debug_id = returned.get("debug_id").and_then(Value::as_str).map(str::to_owned);
        let observed_identity = ModuleIdentity::captured(&observed, &partition.architecture)?;
        check(
            expected_identity.code_id == observed_identity.code_id
                && (expected_identity.debug_id.is_none()
                    || expected_identity.debug_id == observed_identity.debug_id)
                && address(returned.get("image_addr").unwrap_or(&Value::Null))?
                    == address(&Value::String(expected.image_base.clone()))?
                && returned.get("image_size").and_then(Value::as_u64)
                    == Some(u64::from(expected.image_size)),
            "returned module identity or load range differs from request",
        )?;
        let global_index = partition.module_indexes[local_index];
        let candidates = returned
            .get("candidates")
            .and_then(Value::as_array)
            .ok_or_else(|| EvidenceError("dif_candidates diagnostics missing".to_owned()))?;
        let mut downloads: BTreeMap<(String, String), Vec<String>> = BTreeMap::new();
        let mut pdb_owners = BTreeSet::new();
        for candidate in candidates {
            let source = candidate.get("source").and_then(Value::as_str).unwrap_or("");
            check(
                partition.source_ids.contains(source),
                "response consulted a source outside the frozen partition",
            )?;
            let location = candidate.get("location").and_then(Value::as_str).unwrap_or("");
            let url = reqwest::Url::parse(location)
                .map_err(|_| EvidenceError("source candidate location is invalid".to_owned()))?;
            let configured = partition.request["sources"]
                .as_array()
                .unwrap()
                .iter()
                .find(|s| s["id"].as_str() == Some(source))
                .unwrap();
            let root = safe_http_url(configured["url"].as_str().unwrap())?;
            check(
                url.origin() == root.origin()
                    && url.path().starts_with(&format!("{}/", root.path().trim_end_matches('/'))),
                "candidate location escapes its frozen source root",
            )?;
            let leaf = url.path().rsplit('/').next().unwrap_or("").to_ascii_lowercase();
            let stage =
                if leaf.starts_with("debuginf") || leaf.ends_with(".pdb") || leaf.ends_with(".pd_")
                {
                    "download_pdb"
                } else if leaf.starts_with("executabl")
                    || [".exe", ".ex_", ".dll", ".dl_"].iter().any(|s| leaf.ends_with(s))
                {
                    "download_pe"
                } else {
                    return Err(EvidenceError(
                        "source candidate file type is indeterminate".to_owned(),
                    ));
                };
            let status =
                candidate.pointer("/download/status").and_then(Value::as_str).unwrap_or("unknown");
            // The pinned engine emits these exact messages in this candidate's
            // download record. Module identity, source and URL were checked above;
            // the full response is retained by diagnostic_ref. Do not infer a
            // cause from arbitrary substrings, request-level errors or other URLs.
            let classified = if status == "error" {
                match candidate.pointer("/download/details").and_then(Value::as_str) {
                    Some("download failed: 503 Service Unavailable"
                        | "download failed: 429 Too Many Requests"
                        | "download failed: 408 Request Timeout"
                        | "download failed: 502 Bad Gateway"
                        | "download failed: 504 Gateway Timeout") => "transient_http",
                    Some("download failed: 422 Unprocessable Entity") => "permanent_http",
                    _ => status,
                }
            } else {
                status
            };
            downloads
                .entry((source.to_owned(), stage.to_owned()))
                .or_default()
                .push(classified.to_owned());
            if stage == "download_pdb"
                && status == "ok"
                && candidate.pointer("/debug/status").and_then(Value::as_str) == Some("ok")
            {
                pdb_owners.insert(source.to_owned());
            }
        }
        let mut outcomes = Vec::new();
        for ((source, stage), statuses) in downloads {
            let (outcome, failure, reason) = if statuses.iter().any(|s| s == "ok") {
                ("found", "none", "downloaded")
            } else if statuses.iter().all(|s| s == "notfound") {
                ("missing", "permanent", "source_missing")
            } else if statuses.iter().any(|s| s == "malformed" || s == "permanent_http") {
                ("failed", "permanent", "malformed")
            } else if statuses.iter().all(|s| s == "notfound" || s == "transient_http")
                && statuses.iter().any(|s| s == "transient_http")
            {
                ("failed", "transient", "correlated_candidate_http_failure")
            } else {
                ("failed", "unknown", "source_failure_without_correlated_cause")
            };
            outcomes.push(SourceOutcome {
                source_id: source,
                stage,
                outcome: outcome.to_owned(),
                failure_class: failure.to_owned(),
                reason: reason.to_owned(),
                diagnostic_ref: Some(diagnostic_ref.clone()),
            });
        }
        let debug_status =
            returned.get("debug_status").and_then(Value::as_str).unwrap_or("unknown");
        if debug_status == "found" && pdb_owners.len() == 1 {
            let source = pdb_owners.into_iter().next().unwrap();
            owners.insert(global_index, source.clone());
            outcomes.push(SourceOutcome {
                source_id: source,
                stage: "symbolicate".to_owned(),
                outcome: "found".to_owned(),
                failure_class: "none".to_owned(),
                reason: "verified_partition_response".to_owned(),
                diagnostic_ref: Some(diagnostic_ref.clone()),
            });
        } else {
            let permanent = matches!(debug_status, "malformed" | "unsupported");
            for source in &partition.source_ids {
                let download_failure = outcomes.iter().find(|o| {
                    o.source_id == *source && o.stage == "download_pdb" && o.outcome == "failed"
                });
                let failure = if permanent {
                    "permanent"
                } else if debug_status == "fetching_failed" {
                    download_failure.map_or("unknown", |o| o.failure_class.as_str())
                } else {
                    "unknown"
                };
                outcomes.push(SourceOutcome {
                    source_id: source.clone(),
                    stage: "symbolicate".to_owned(),
                    outcome: if failure != "unknown" { "failed" } else { "unknown" }.to_owned(),
                    failure_class: failure.to_owned(),
                    reason: format!("module_{debug_status}_or_source_ownership_incomplete"),
                    diagnostic_ref: Some(diagnostic_ref.clone()),
                });
            }
        }
        module_outcomes.push((global_index, outcomes));
    }
    let mut frames = Vec::new();
    for (trace, reference) in traces.iter().zip(&partition.frame_refs) {
        let records = trace
            .get("frames")
            .and_then(Value::as_array)
            .ok_or_else(|| EvidenceError("response trace frames missing".to_owned()))?;
        let symbolicated =
            |record: &Value| record.get("status").and_then(Value::as_str) == Some("symbolicated");
        check(
            !records.iter().any(symbolicated) || records.iter().all(symbolicated),
            "mixed physical/inline response statuses are ambiguous",
        )?;
        let mut symbols = Vec::new();
        for record in records {
            check(
                record.get("original_index").and_then(Value::as_u64) == Some(0)
                    && address(record.get("instruction_addr").unwrap_or(&Value::Null))?
                        == reference.instruction,
                "response changed physical frame provenance",
            )?;
            if let Some(package) = record.get("package").and_then(Value::as_str) {
                let local = partition
                    .module_indexes
                    .iter()
                    .position(|i| *i == reference.module_index)
                    .unwrap();
                check(
                    basename(package) == basename(&partition.captured_modules[local].code_file),
                    "response frame package differs from captured module",
                )?;
            }
            if record.get("status").and_then(Value::as_str) != Some("symbolicated") {
                continue;
            }
            symbols.push(SymbolicatedFrame {
                function: record
                    .get("function")
                    .or_else(|| record.get("symbol"))
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                file: record
                    .get("abs_path")
                    .or_else(|| record.get("filename"))
                    .and_then(Value::as_str)
                    .map(str::to_owned),
                line: record.get("lineno").and_then(Value::as_u64),
                inline: vec![],
            });
        }
        if let (Some(source), Some(mut symbol)) =
            (owners.get(&reference.module_index), symbols.pop())
        {
            symbol.inline = symbols;
            frames.push(FrameSymbol {
                thread_index: reference.thread_index,
                physical_frame_index: reference.physical_frame_index,
                module_index: reference.module_index,
                instruction: reference.instruction,
                pair_id: partition.pair_id.clone(),
                source_id: source.clone(),
                symbol,
            });
        }
    }
    Ok(Collected { frames, modules: module_outcomes })
}

fn address(value: &Value) -> Result<u64, EvidenceError> {
    value
        .as_u64()
        .or_else(|| {
            value.as_str().and_then(|s| {
                s.strip_prefix("0x")
                    .or_else(|| s.strip_prefix("0X"))
                    .map(|s| u64::from_str_radix(s, 16).ok())
                    .unwrap_or_else(|| s.parse().ok())
            })
        })
        .ok_or_else(|| EvidenceError("invalid instruction/module address".to_owned()))
}
fn basename(value: &str) -> String {
    value.rsplit(['/', '\\']).next().unwrap_or(value).to_ascii_lowercase()
}

#[cfg(test)]
#[path = "frozen_symbolicator_tests.rs"]
mod tests;
