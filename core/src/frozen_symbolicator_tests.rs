use super::*;
use crate::unwind::{UnwindFrame, UnwindThread};
use std::io::Write;
use std::net::TcpListener;
use std::thread;

fn sample() -> (InspectReport, UnwindReport, Vec<FrozenSelection>) {
    let mut report:InspectReport=serde_json::from_value(json!({"schema_version":"0.1","dump":{"kind":"user_minidump","size":1,"signature":"MDMP","number_of_streams":1,"flags":"0x0","timestamp":null},
        "process":{"pid":1,"architecture":"x86_64","os":"windows","os_version":null,"platform_id":2,"build_number":null,"processor_count":1},"exception":null,"crash_thread_id":null,
        "threads":[{"id":7,"teb":"0x0","stack_start":"0x0","stack_size":1,"context":null}],"modules":[],"warnings":[]})).unwrap();
    report.modules = (0..2)
        .map(|i| InspectModule {
            code_file: "same.exe".to_owned(),
            code_id: format!("1234567{i}1000"),
            debug_file: Some("same.pdb".to_owned()),
            debug_id: Some(format!("{}1", "a".repeat(32))),
            image_base: format!("0x{:x}", 0x1000 + i * 0x2000),
            image_size: 4096,
            time_date_stamp: "0x0".to_owned(),
            checksum: "0x0".to_owned(),
        })
        .collect();
    let unwind = UnwindReport {
        threads: vec![UnwindThread {
            id: 7,
            frames: [0x1010, 0x3010, 0x3010]
                .into_iter()
                .map(|instruction| UnwindFrame {
                    instruction,
                    resume_address: instruction,
                    module: None,
                    function: None,
                    file: None,
                    line: None,
                    trust: "context".to_owned(),
                    unwind_method: Some("context".to_owned()),
                    inline: false,
                })
                .collect(),
        }],
    };
    let selections = report
        .modules
        .iter()
        .enumerate()
        .map(|(i, m)| {
            let pair = if i == 0 { "a" } else { "b" }.repeat(64);
            FrozenSelection {
                module_index: i,
                identity: ModuleIdentity::captured(m, "x86_64").unwrap(),
                state: "unique".to_owned(),
                candidates_complete: true,
                candidate_pair_ids: vec![pair.clone()],
                unavailable_pair_ids: vec![],
                selected_pair_id: Some(pair),
                reason: "unique".to_owned(),
                candidate_evidence: diagnostic(),
                review_refs: vec![],
            }
        })
        .collect();
    (report, unwind, selections)
}

fn diagnostic() -> ObjectRef {
    ObjectRef { object_key: "tests/response.json".to_owned(), sha256: "c".repeat(64) }
}

fn response(job: &Partition) -> Value {
    let source = &job.request["sources"][0];
    let modules=job.request["modules"].as_array().unwrap().iter().map(|m|{
        let mut value=m.clone();value["debug_status"]=json!("found");value["arch"]=json!("x86_64");
        value["candidates"]=json!([{"source":source["id"],"location":format!("{}aa/bb/debuginfo",source["url"].as_str().unwrap()),"download":{"status":"ok"},"debug":{"status":"ok"}}]);value
    }).collect::<Vec<_>>();
    json!({"status":"completed","modules":modules,"stacktraces":job.frame_refs.iter().map(|r|json!({"frames":[{"status":"symbolicated","original_index":0,"instruction_addr":format!("0x{:x}",r.instruction),"package":"same.exe","function":format!("physical_{}",r.physical_frame_index),"abs_path":"sample.cpp","lineno":7}]})).collect::<Vec<_>>()})
}

#[test]
fn distinct_contents_never_share_a_source_request_and_recursive_frames_keep_slots() {
    let (report, raw, selections) = sample();
    let plan = plan(&report, &raw, &selections, "http://localhost:9999/content", &[]).unwrap();
    assert_eq!(plan.partitions.len(), 2);
    assert!(plan.blocked_modules.is_empty());
    for job in &plan.partitions {
        assert_eq!(job.request()["sources"].as_array().unwrap().len(), 1);
        assert_eq!(job.request()["modules"].as_array().unwrap().len(), 1);
        assert!(job.request()["stacktraces"].as_array().unwrap().iter().all(|t| t["frames"]
            .as_array()
            .unwrap()
            .len()
            == 1));
    }
    let second = &plan.partitions[1];
    let result = collect(second, &response(second), diagnostic()).unwrap();
    assert_eq!(result.frames.len(), 2);
    assert_eq!(result.frames[0].instruction, result.frames[1].instruction);
    assert_eq!(result.frames[0].physical_frame_index, 1);
    assert_eq!(result.frames[1].physical_frame_index, 2);
    assert_ne!(result.frames[0].symbol.function, result.frames[1].symbol.function);
    assert_eq!(result.frames[0].pair_id, Some("b".repeat(64)));
}

#[test]
fn public_policy_applies_only_to_none_and_never_bypasses_blocked_selections() {
    let (report, raw, selections) = sample();
    let public = vec![
        json!({"id":"public-test","type":"http","url":"https://symbols.example.test/","layout":{"type":"symstore"},"is_public":true}),
    ];
    for (state, reason, complete) in [
        ("none", "missing", true),
        ("conflict", "identity_conflict", true),
        ("unavailable", "withdrawn", true),
        ("indeterminate", "enumeration_failed", false),
    ] {
        let mut selected = selections.clone();
        let s = &mut selected[0];
        s.state = state.to_owned();
        s.reason = reason.to_owned();
        s.candidates_complete = complete;
        s.selected_pair_id = None;
        s.candidate_pair_ids =
            if state == "conflict" { vec!["a".repeat(64), "c".repeat(64)] } else { vec![] };
        if state == "unavailable" {
            s.unavailable_pair_ids = vec!["a".repeat(64)];
        }
        let result = plan(&report, &raw, &selected, "http://localhost/content", &public).unwrap();
        assert_eq!(result.partitions.len(), if state == "none" { 2 } else { 1 });
        assert_eq!(result.blocked_modules.contains(&0), state != "none");
        if state == "none" {
            let job = result.partitions.iter().find(|p| p.pair_id.is_none()).unwrap();
            let collected = collect(job, &response(job), diagnostic()).unwrap();
            assert!(collected.frames[0].pair_id.is_none());
            assert_eq!(collected.frames[0].source_id, "public-test");
        }
    }
}

#[test]
fn response_provenance_is_required_and_failures_do_not_become_transient_by_name() {
    let (report, raw, selections) = sample();
    let jobs = plan(&report, &raw, &selections, "http://localhost/content", &[]).unwrap();
    let job = &jobs.partitions[0];
    let original = response(job);
    let mut mutations = Vec::new();
    let mut v = original.clone();
    v["modules"][0]["arch"] = json!("arm64");
    mutations.push(v);
    let mut v = original.clone();
    v["modules"][0]["arch"] = json!("unknown");
    mutations.push(v);
    let mut v = original.clone();
    v["modules"][0]["candidates"][0]["location"] = json!("http://localhost/unfrozen/debuginfo");
    mutations.push(v);
    let mut v = original.clone();
    let mut unknown = v["stacktraces"][0]["frames"][0].clone();
    unknown["status"] = json!("missing");
    v["stacktraces"][0]["frames"].as_array_mut().unwrap().push(unknown);
    mutations.push(v);
    let mut v = original.clone();
    v["stacktraces"][0]["frames"][0].as_object_mut().unwrap().remove("original_index");
    mutations.push(v);
    let mut v = original.clone();
    v["stacktraces"][0]["frames"][0]["original_index"] = json!(1);
    mutations.push(v);
    let mut v = original.clone();
    v["stacktraces"][0]["frames"][0]["instruction_addr"] = json!("0x1011");
    mutations.push(v);
    let mut v = original.clone();
    v["modules"][0]["code_id"] = json!("876543211000");
    mutations.push(v);
    let mut v = original.clone();
    v["modules"][0]["image_addr"] = json!("0x3000");
    mutations.push(v);
    let mut v = original.clone();
    v["modules"][0]["candidates"][0]["source"] = json!("unrequested-cache");
    mutations.push(v);
    let mut v = original.clone();
    v["stacktraces"].as_array_mut().unwrap().clear();
    mutations.push(v);
    for v in mutations {
        assert!(collect(job, &v, diagnostic()).is_err());
    }
    let mut failed = original;
    failed["modules"][0]["debug_status"] = json!("fetching_failed");
    failed["modules"][0]["arch"] = json!("unknown");
    failed["modules"][0]["candidates"][0]["download"] =
        json!({"status":"error","details":"503 Service Unavailable"});
    let result = collect(job, &failed, diagnostic()).unwrap();
    assert!(result.frames.is_empty());
    assert!(result.modules[0].1.iter().all(|o| o.failure_class == "unknown"));
    for (details, expected) in [
        ("download failed: 503 Service Unavailable", "transient"),
        ("download failed: 429 Too Many Requests", "transient"),
        ("download failed: 422 Unprocessable Entity", "permanent"),
        ("download failed: 500 Internal Server Error", "unknown"),
        ("unrelated log says download failed: 503 Service Unavailable", "unknown"),
    ] {
        failed["modules"][0]["candidates"][0]["download"]["details"] = json!(details);
        let result = collect(job, &failed, diagnostic()).unwrap();
        assert!(result.modules[0].1.iter().all(|o| o.failure_class == expected), "{details}");
    }
    failed["modules"][0]["arch"] = json!("arm64");
    assert!(collect(job, &failed, diagnostic()).is_err());
}

#[test]
fn inline_expansion_preserves_repeated_records_and_uses_last_as_physical_symbol() {
    let (report, raw, selections) = sample();
    let jobs = plan(&report, &raw, &selections, "http://localhost/content", &[]).unwrap();
    let job = &jobs.partitions[0];
    let mut value = response(job);
    let physical = value["stacktraces"][0]["frames"][0].clone();
    let mut inline = physical.clone();
    inline["function"] = json!("inline_repeated");
    value["stacktraces"][0]["frames"] = json!([inline.clone(), inline, physical]);
    let result = collect(job, &value, diagnostic()).unwrap();
    assert_eq!(result.frames.len(), 1);
    assert_eq!(result.frames[0].symbol.inline.len(), 2);
    assert_eq!(result.frames[0].symbol.function.as_deref(), Some("physical_0"));
}

fn serve(sequence: Vec<(u16, Value)>) -> (String, thread::JoinHandle<Vec<String>>) {
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let endpoint = format!("http://{}", listener.local_addr().unwrap());
    let handle = thread::spawn(move || {
        let mut requests = Vec::new();
        for (status, body) in sequence {
            let (mut stream, _) = listener.accept().unwrap();
            stream.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
            let mut bytes = Vec::new();
            let mut buffer = [0u8; 4096];
            loop {
                let n = stream.read(&mut buffer).unwrap();
                if n == 0 {
                    break;
                }
                bytes.extend_from_slice(&buffer[..n]);
                if let Some(end) = bytes.windows(4).position(|w| w == b"\r\n\r\n") {
                    let headers = String::from_utf8_lossy(&bytes[..end]);
                    let length = headers
                        .lines()
                        .find_map(|l| {
                            l.to_ascii_lowercase()
                                .strip_prefix("content-length:")
                                .map(|s| s.trim().parse::<usize>().unwrap())
                        })
                        .unwrap_or(0);
                    if bytes.len() >= end + 4 + length {
                        break;
                    }
                }
            }
            requests.push(String::from_utf8(bytes).unwrap());
            let body = serde_json::to_vec(&body).unwrap();
            let redirect =
                if status == 302 { "Location: http://127.0.0.1:9/outside\r\n" } else { "" };
            write!(stream,"HTTP/1.1 {status} response\r\n{redirect}Content-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",body.len()).unwrap();
            stream.write_all(&body).unwrap();
        }
        requests
    });
    (endpoint, handle)
}

#[test]
fn pending_object_loss_reposts_identical_sources_and_never_accepts_an_http_error_body() {
    let (report, raw, selections) = sample();
    let jobs = plan(&report, &raw, &selections, "http://localhost/content", &[]).unwrap();
    let job = &jobs.partitions[0];
    let (endpoint, server) = serve(vec![
        (200, json!({"status":"pending","request_id":"abc-123"})),
        (404, json!({"status":"not_found"})),
        (200, response(job)),
    ]);
    let result = execute(&endpoint, job, 10).unwrap();
    assert!(result.failure.is_none());
    assert_eq!(result.attempts.len(), 3);
    let requests = server.join().unwrap();
    let body = |i: usize| requests[i].split_once("\r\n\r\n").unwrap().1;
    assert_eq!(body(0), body(2));
    assert!(requests[1].starts_with("GET /requests/abc-123?timeout=1 "));
    assert_eq!(serde_json::from_str::<Value>(body(0)).unwrap(), *job.request());
    let (endpoint, server) = serve(vec![(503, response(job))]);
    let failed = execute(&endpoint, job, 10).unwrap();
    server.join().unwrap();
    assert_eq!(failed.failure.as_deref(), Some("http_503"));
    assert!(failed.response.is_none());
}

#[test]
fn malformed_poll_ids_and_redirects_cannot_change_the_frozen_endpoint() {
    let (report, raw, selections) = sample();
    let jobs = plan(&report, &raw, &selections, "http://localhost/content", &[]).unwrap();
    let job = &jobs.partitions[0];
    let (endpoint, server) =
        serve(vec![(200, json!({"status":"pending","request_id":"../other"}))]);
    let result = execute(&endpoint, job, 10).unwrap();
    server.join().unwrap();
    assert_eq!(result.failure.as_deref(), Some("invalid_pending_request_id"));
    let (endpoint, server) = serve(vec![(302, json!({}))]);
    let result = execute(&endpoint, job, 10).unwrap();
    server.join().unwrap();
    assert_eq!(result.failure.as_deref(), Some("http_302"));
    assert!(pair_source(&"a".repeat(64), "file:///private").is_err());
    assert!(pair_source(&"a".repeat(64), "https://user:secret@example.test").is_err());
}
