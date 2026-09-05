//! Public PE unwind material through the pinned engine's Microsoft-only proxy.
//! Only an explicit, unrestricted Microsoft policy and a complete `none`
//! selection permit a fetch. Downloaded identity is checked before local unwind.

use crate::canonical::sha256_hex;
use crate::canonical_v11::{EvidenceError, FrozenSelection, ObjectRef, SourceOutcome};
use crate::minidump::InspectReport;
use crate::unwind::{unwind_bytes_with_selected_modules, UnwindReport};
use reqwest::blocking::Client;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

const SOURCE: &str = "crash-cap:microsoft";
const MAX_PE_BYTES: u64 = 32 * 1024 * 1024;
const MAX_TOTAL_BYTES: u64 = 64 * 1024 * 1024;
const MAX_REQUESTS: usize = 16;

fn error(e: impl std::fmt::Display) -> EvidenceError {
    EvidenceError(e.to_string())
}

fn microsoft_enabled(sources: &[Value]) -> bool {
    // A filtered/custom policy cannot silently broaden into the proxy's policy.
    sources.iter().any(|s| {
        s == &json!({
            "id": SOURCE, "type": "http", "url": "https://msdl.microsoft.com/download/symbols/",
            "layout": {"type": "symstore"}, "filters": {"filetypes": ["pdb", "pe", "portablepdb"]},
            "is_public": true
        })
    })
}

fn filename(value: &str) -> Option<String> {
    let name = value.rsplit(['/', '\\']).next()?.to_ascii_lowercase();
    (!name.is_empty()
        && name.len() <= 255
        && name != "."
        && name != ".."
        && name.bytes().all(|b| b.is_ascii_alphanumeric() || b"-_.".contains(&b)))
    .then_some(name)
}

pub struct PublicUnwind {
    pub report: UnwindReport,
    pub outcomes: BTreeMap<usize, Vec<SourceOutcome>>,
}

pub struct PublicPeRequest<'a> {
    pub dump: &'a [u8],
    pub inspect: &'a InspectReport,
    pub selections: &'a [FrozenSelection],
    pub sources: &'a [Value],
    pub engine: &'a str,
    pub raw_dir: &'a Path,
    pub raw_prefix: &'a str,
    pub deadline: Instant,
}

pub fn unwind(
    request: PublicPeRequest<'_>,
    mut paths: BTreeMap<usize, PathBuf>,
) -> Result<PublicUnwind, EvidenceError> {
    let mut report = unwind_bytes_with_selected_modules(request.dump, &paths).map_err(error)?;
    let mut outcomes = BTreeMap::new();
    if !microsoft_enabled(request.sources) {
        return Ok(PublicUnwind { report, outcomes });
    }
    let client =
        Client::builder().redirect(reqwest::redirect::Policy::none()).build().map_err(error)?;
    let mut attempted = BTreeSet::new();
    let mut total = 0u64;
    while attempted.len() < MAX_REQUESTS
        && total < MAX_TOTAL_BYTES
        && Instant::now() < request.deadline
    {
        let index = request.inspect.modules.iter().enumerate().find_map(|(index, module)| {
            let selection = &request.selections[index];
            if selection.state != "none"
                || !selection.candidates_complete
                || selection.identity.architecture != "x86_64"
                || selection.identity.debug_id.is_none()
                || paths.contains_key(&index)
                || attempted.contains(&index)
                || filename(&module.code_file).is_none()
            {
                return None;
            }
            let base = u64::from_str_radix(module.image_base.trim_start_matches("0x"), 16).ok()?;
            let end = base.checked_add(u64::from(module.image_size))?;
            report
                .threads
                .iter()
                .flat_map(|t| &t.frames)
                .any(|f| f.instruction >= base && f.instruction < end)
                .then_some(index)
        });
        let Some(index) = index else { break };
        attempted.insert(index);
        let module = &request.inspect.modules[index];
        let name = filename(&module.code_file).unwrap();
        let url = format!(
            "{}/proxy/{}/{}/{}",
            request.engine.trim_end_matches('/'),
            name,
            module.code_id.to_ascii_lowercase(),
            name
        );
        let timeout =
            request.deadline.saturating_duration_since(Instant::now()).min(Duration::from_secs(10));
        if timeout.is_zero() {
            break;
        }
        let mut diagnostic = json!({"module_index": index, "source_id": SOURCE,
            "request_url": url, "captured_identity": request.selections[index].identity});
        let (outcome, failure, reason, downloaded) = match client.get(&url).timeout(timeout).send()
        {
            Err(e) => (
                "failed",
                "transient",
                if e.is_timeout() { "timeout" } else { "transport_error" },
                None,
            ),
            Ok(response) => {
                let status = response.status().as_u16();
                diagnostic["http_status"] = json!(status);
                if status == 200 {
                    let limit = MAX_PE_BYTES.min(MAX_TOTAL_BYTES - total);
                    let mut bytes = Vec::new();
                    let read = response.take(limit + 1).read_to_end(&mut bytes);
                    total += bytes.len() as u64;
                    match read {
                        Ok(_) if bytes.len() as u64 <= limit => {
                            ("found", "none", "downloaded", Some(bytes))
                        }
                        Ok(_) => ("failed", "permanent", "material_size_limit", None),
                        Err(_) => ("failed", "transient", "body_transport_error", None),
                    }
                } else if matches!(status, 404 | 410) {
                    ("missing", "permanent", "not_found", None)
                } else {
                    // The proxy may summarize upstream errors; do not invent a
                    // temporary upstream cause from a generic proxy failure.
                    ("failed", "unknown", "proxy_failure", None)
                }
            }
        };
        let (mut outcome, mut failure, mut reason) = (outcome, failure, reason);
        if let Some(bytes) = downloaded {
            let pe_path = request.raw_dir.join(format!("public-pe-{index}.dll"));
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&pe_path)
                .and_then(|mut f| f.write_all(&bytes))
                .map_err(error)?;
            diagnostic["content_sha256"] = json!(sha256_hex(&bytes));
            diagnostic["content_size"] = json!(bytes.len());
            let captured = &request.selections[index].identity;
            let identity_ok = crate::artifact::identify_artifact(&pe_path, "pe").is_ok_and(|pe| {
                pe.code_id.map(|s| s.to_ascii_lowercase()) == captured.code_id
                    && pe.debug_id.map(|s| s.replace('-', "").to_ascii_lowercase())
                        == captured.debug_id
            });
            diagnostic["identity_verified"] = json!(identity_ok);
            if identity_ok {
                paths.insert(index, pe_path);
                report = unwind_bytes_with_selected_modules(request.dump, &paths).map_err(error)?;
                reason = "identity_verified_for_unwind";
            } else {
                outcome = "failed";
                failure = "permanent";
                reason = "pe_identity_mismatch";
            }
        }
        diagnostic["outcome"] = json!(outcome);
        diagnostic["failure_class"] = json!(failure);
        diagnostic["reason"] = json!(reason);
        let encoded = serde_json::to_vec_pretty(&diagnostic).map_err(error)?;
        let name = format!("public-pe-{index}.json");
        fs::write(request.raw_dir.join(&name), &encoded).map_err(error)?;
        outcomes.insert(
            index,
            vec![SourceOutcome {
                source_id: SOURCE.to_owned(),
                stage: "unwind".to_owned(),
                outcome: outcome.to_owned(),
                failure_class: failure.to_owned(),
                reason: reason.to_owned(),
                diagnostic_ref: Some(ObjectRef {
                    object_key: format!("{}/raw/{name}", request.raw_prefix),
                    sha256: sha256_hex(&encoded),
                }),
            }],
        );
    }
    Ok(PublicUnwind { report, outcomes })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn public_proxy_requires_exact_unrestricted_deployment_policy() {
        let mut policy = json!({"id": SOURCE, "type": "http", "url": "https://msdl.microsoft.com/download/symbols/",
            "layout": {"type": "symstore"}, "filters": {"filetypes": ["pdb", "pe", "portablepdb"]}, "is_public": true});
        assert!(microsoft_enabled(&[policy.clone()]));
        policy["filters"]["path_patterns"] = json!(["kernel32.dll"]);
        assert!(!microsoft_enabled(&[policy]));
        assert!(!microsoft_enabled(&[]));
        assert_eq!(
            filename("C:\\Windows\\System32\\KERNEL32.dll"),
            Some("kernel32.dll".to_owned())
        );
        assert_eq!(filename("kernel32.dll?source=other"), None);
    }
}
