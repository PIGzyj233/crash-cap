use crate::canonical::{
    CanonicalAnalysisResult, QualityWarning, SourceContext, GROUPING_VERSION, NORMALIZATION_VERSION,
};
use crate::minidump::InspectReport;
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Component, Path, PathBuf};

const CONTEXT_VERSION: &str = "analysis-context-v1";
const SOURCE_POLICY_VERSION: &str = "source-bundle-v1.0";
const MAX_SOURCE_ENTRIES: usize = 20_000;
const MAX_SOURCE_FILE_BYTES: u64 = 2 * 1024 * 1024;
const MAX_UNCOMPRESSED_BYTES: u64 = 512 * 1024 * 1024;

#[derive(Debug, Clone, Deserialize)]
pub struct AnalysisContext {
    schema_version: String,
    identity: IdentityContext,
    dump: DumpContext,
    engine: EngineContext,
    policy: PolicyContext,
    inspect: InspectContext,
    #[serde(default)]
    inputs: InputContext,
}

#[derive(Debug, Clone, Deserialize)]
struct IdentityContext {
    workspace_id: String,
    occurrence_id: String,
    analysis_id: String,
}

#[derive(Debug, Clone, Deserialize)]
struct DumpContext {
    blob_id: String,
    sha256: String,
    kind: String,
    size: u64,
    dump_timestamp: Option<String>,
    reported_at: Option<String>,
    uploaded_at: String,
    occurred_at: String,
    time_source: String,
}

#[derive(Debug, Clone, Deserialize)]
struct EngineContext {
    core_image_digest: String,
    symbolicator_version: String,
    grouping_version: String,
    normalization_version: String,
}

#[derive(Debug, Clone, Deserialize)]
struct PolicyContext {
    symbol_inventory_version: u64,
    source_bundle_policy_version: String,
}

#[derive(Debug, Clone, Deserialize)]
struct InspectContext {
    sha256: String,
}

#[derive(Debug, Clone, Default, Deserialize)]
struct InputContext {
    #[serde(default)]
    source_bundles: Vec<SourceBundleContext>,
    source_bundle_error: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
struct SourceBundleContext {
    build_id: String,
    sha256: String,
    size: u64,
    archive_path: PathBuf,
    extracted_root: PathBuf,
    ingest_metadata: SourceBundleMetadata,
    #[serde(default)]
    source_bundle_config: SourceBundleConfig,
    #[serde(default)]
    entries: Vec<SourceEntry>,
}

#[derive(Debug, Clone, Deserialize)]
struct SourceBundleMetadata {
    policy_version: String,
    entry_count: usize,
    source_entry_count: usize,
    uncompressed_size: u64,
    source_entries: Vec<String>,
}

#[derive(Debug, Clone, Default, Deserialize)]
struct SourceBundleConfig {
    #[serde(default)]
    source_root: String,
    #[serde(default)]
    strip_prefixes: Vec<String>,
    context_lines: Option<usize>,
}

#[derive(Debug, Clone, Deserialize)]
struct SourceEntry {
    path: String,
    sha256: String,
    size: u64,
}

impl AnalysisContext {
    pub fn validate_and_apply(
        &self,
        result: &mut CanonicalAnalysisResult,
        inspect: &InspectReport,
        dump_bytes: &[u8],
        cli_workspace_id: &str,
        cli_symbol_inventory_version: u64,
    ) -> Result<(), String> {
        if self.schema_version != CONTEXT_VERSION {
            return Err(format!("unsupported analysis context version: {}", self.schema_version));
        }
        if self.identity.workspace_id.is_empty()
            || self.identity.occurrence_id.is_empty()
            || self.identity.analysis_id.is_empty()
        {
            return Err("analysis context identity contains an empty ID".to_owned());
        }
        if self.identity.workspace_id != cli_workspace_id {
            return Err("analysis context Workspace does not match --workspace-id".to_owned());
        }
        if self.policy.symbol_inventory_version != cli_symbol_inventory_version {
            return Err(
                "analysis context symbol inventory does not match --symbol-inventory-version"
                    .to_owned(),
            );
        }
        if self.policy.source_bundle_policy_version != SOURCE_POLICY_VERSION {
            return Err("analysis context has an unsupported source bundle policy".to_owned());
        }
        if self.dump.sha256 != sha256_bytes(dump_bytes) {
            return Err("analysis context Dump SHA-256 does not match input bytes".to_owned());
        }
        if self.dump.size != dump_bytes.len() as u64 || self.dump.size != inspect.dump.size {
            return Err("analysis context Dump size does not match inspect evidence".to_owned());
        }
        if self.dump.kind != inspect.dump.kind {
            return Err("analysis context Dump kind does not match inspect evidence".to_owned());
        }
        if self.dump.dump_timestamp != inspect.dump.timestamp {
            return Err(
                "analysis context Dump timestamp does not match inspect evidence".to_owned()
            );
        }
        let inspect_value = serde_json::to_value(inspect)
            .map_err(|error| format!("inspect evidence cannot be serialized: {error}"))?;
        let inspect_bytes = serde_json::to_vec(&inspect_value)
            .map_err(|error| format!("inspect evidence cannot be serialized: {error}"))?;
        if sha256_bytes(&inspect_bytes) != self.inspect.sha256 {
            return Err(
                "analysis context inspect digest does not match inspect evidence".to_owned()
            );
        }
        for (label, value) in [
            ("uploaded_at", Some(self.dump.uploaded_at.as_str())),
            ("occurred_at", Some(self.dump.occurred_at.as_str())),
            ("reported_at", self.dump.reported_at.as_deref()),
            ("dump_timestamp", self.dump.dump_timestamp.as_deref()),
        ] {
            if let Some(value) = value {
                chrono::DateTime::parse_from_rfc3339(value).map_err(|_| {
                    format!("analysis context {label} is not an RFC 3339 timestamp")
                })?;
            }
        }
        if !["dump", "reported", "uploaded", "manual"].contains(&self.dump.time_source.as_str()) {
            return Err("analysis context has an invalid time_source".to_owned());
        }
        if self.engine.grouping_version != GROUPING_VERSION
            || self.engine.normalization_version != NORMALIZATION_VERSION
        {
            return Err("analysis context algorithm version does not match this Core".to_owned());
        }
        if result.engine.core_image_digest != self.engine.core_image_digest
            || result.engine.symbolicator_version != self.engine.symbolicator_version
        {
            return Err("analysis context engine pin does not match Core arguments".to_owned());
        }

        result.workspace_id.clone_from(&self.identity.workspace_id);
        result.occurrence_id.clone_from(&self.identity.occurrence_id);
        result.analysis_id.clone_from(&self.identity.analysis_id);
        result.dump.blob_id.clone_from(&self.dump.blob_id);
        result.dump.sha256.clone_from(&self.dump.sha256);
        result.dump.kind.clone_from(&self.dump.kind);
        result.dump.size = self.dump.size;
        result.dump.dump_timestamp.clone_from(&self.dump.dump_timestamp);
        result.dump.reported_at.clone_from(&self.dump.reported_at);
        result.dump.uploaded_at.clone_from(&self.dump.uploaded_at);
        result.dump.occurred_at.clone_from(&self.dump.occurred_at);
        result.dump.time_source.clone_from(&self.dump.time_source);
        result.engine.core_image_digest.clone_from(&self.engine.core_image_digest);
        result.engine.symbolicator_version.clone_from(&self.engine.symbolicator_version);
        result.engine.grouping_version.clone_from(&self.engine.grouping_version);
        result.engine.normalization_version.clone_from(&self.engine.normalization_version);
        Ok(())
    }

    pub fn enrich_source_context(
        &self,
        result: &mut CanonicalAnalysisResult,
        context_file: &Path,
    ) -> Result<usize, String> {
        if let Some(error) = &self.inputs.source_bundle_error {
            return Err(error.clone());
        }
        let Some(build_id) = result.build_resolution.resolved_build_id.as_deref() else {
            return Ok(0);
        };
        let Some(bundle) =
            self.inputs.source_bundles.iter().rev().find(|bundle| bundle.build_id == build_id)
        else {
            return Ok(0);
        };
        bundle.validate_and_enrich(result, context_file)
    }
}

impl SourceBundleContext {
    fn validate_and_enrich(
        &self,
        result: &mut CanonicalAnalysisResult,
        context_file: &Path,
    ) -> Result<usize, String> {
        if self.ingest_metadata.policy_version != SOURCE_POLICY_VERSION {
            return Err("unsupported source bundle policy version".to_owned());
        }
        if self.ingest_metadata.entry_count > MAX_SOURCE_ENTRIES
            || self.ingest_metadata.source_entry_count != self.entries.len()
            || self.ingest_metadata.source_entries.len() != self.entries.len()
            || self.ingest_metadata.uncompressed_size > MAX_UNCOMPRESSED_BYTES
        {
            return Err("source bundle metadata exceeds its frozen budget".to_owned());
        }
        if !safe_relative(&self.archive_path) || !safe_relative(&self.extracted_root) {
            return Err("source bundle runtime path is unsafe".to_owned());
        }
        let base = context_file.parent().unwrap_or_else(|| Path::new("."));
        let archive = base.join(&self.archive_path);
        let archive_metadata = fs::symlink_metadata(&archive)
            .map_err(|error| format!("source bundle archive is unavailable: {error}"))?;
        if archive_metadata.file_type().is_symlink() || !archive_metadata.is_file() {
            return Err("source bundle archive is not a regular file".to_owned());
        }
        if archive_metadata.len() != self.size || sha256_file(&archive)? != self.sha256 {
            return Err("source bundle archive differs from immutable Run facts".to_owned());
        }
        let root = base.join(&self.extracted_root);
        let root = root
            .canonicalize()
            .map_err(|error| format!("staged source root is unavailable: {error}"))?;
        let mut validated = Vec::with_capacity(self.entries.len());
        let mut source_bytes = 0u64;
        for entry in &self.entries {
            let relative = Path::new(&entry.path);
            if !safe_relative(relative)
                || !supported_source_extension(relative)
                || entry.size > MAX_SOURCE_FILE_BYTES
            {
                return Err("staged source entry violates the source-bundle policy".to_owned());
            }
            source_bytes = source_bytes
                .checked_add(entry.size)
                .ok_or_else(|| "staged source entry size overflow".to_owned())?;
            if source_bytes > MAX_UNCOMPRESSED_BYTES {
                return Err("staged source entries exceed the uncompressed budget".to_owned());
            }
            let path = root.join(relative);
            let metadata = fs::symlink_metadata(&path)
                .map_err(|error| format!("staged source entry is unavailable: {error}"))?;
            if metadata.file_type().is_symlink()
                || !metadata.is_file()
                || metadata.len() != entry.size
            {
                return Err("staged source entry is not the declared regular file".to_owned());
            }
            let canonical = path
                .canonicalize()
                .map_err(|error| format!("staged source entry cannot be resolved: {error}"))?;
            if !canonical.starts_with(&root) || sha256_file(&canonical)? != entry.sha256 {
                return Err("staged source entry differs from its runtime manifest".to_owned());
            }
            validated.push((entry.path.clone(), canonical));
        }

        let mut prefixes = vec![self.source_bundle_config.source_root.clone()];
        prefixes.extend(self.source_bundle_config.strip_prefixes.clone());
        let context_lines = self.source_bundle_config.context_lines.unwrap_or(3).min(10);
        let names = validated.iter().map(|(name, _)| name.clone()).collect::<Vec<_>>();
        let mut attached = 0usize;
        for thread in &mut result.threads {
            for frame in &mut thread.frames {
                let (Some(frame_file), Some(line_number)) = (frame.file.as_deref(), frame.line)
                else {
                    continue;
                };
                if line_number == 0 {
                    continue;
                }
                let Some(name) = resolve_entry(&names, frame_file, &prefixes) else {
                    continue;
                };
                let Some((_, path)) = validated.iter().find(|(candidate, _)| candidate == name)
                else {
                    continue;
                };
                let source = fs::read_to_string(path)
                    .map_err(|error| format!("staged source entry is not UTF-8: {error}"))?;
                let lines = source.lines().collect::<Vec<_>>();
                let Ok(index) = usize::try_from(line_number - 1) else {
                    continue;
                };
                if index >= lines.len() {
                    continue;
                }
                frame.source_context = Some(SourceContext {
                    pre: lines[index.saturating_sub(context_lines)..index]
                        .iter()
                        .map(|line| clip(line))
                        .collect(),
                    line: clip(lines[index]),
                    post: lines[index + 1..lines.len().min(index + 1 + context_lines)]
                        .iter()
                        .map(|line| clip(line))
                        .collect(),
                });
                attached += 1;
            }
        }
        Ok(attached)
    }
}

pub fn source_context_warning(message: impl Into<String>) -> QualityWarning {
    QualityWarning {
        code: "other".to_owned(),
        message: format!("Source context omitted: {}", message.into()),
        module: None,
        debug_id: None,
    }
}

fn safe_relative(path: &Path) -> bool {
    !path.as_os_str().is_empty()
        && !path.is_absolute()
        && !path.to_string_lossy().contains(['\\', '\0'])
        && path.components().all(|component| matches!(component, Component::Normal(_)))
        && path.components().all(|component| !component.as_os_str().to_string_lossy().contains(':'))
}

pub(crate) fn supported_source_extension(path: &Path) -> bool {
    path.extension().and_then(|extension| extension.to_str()).is_some_and(|extension| {
        matches!(
            extension.to_ascii_lowercase().as_str(),
            "c" | "cc"
                | "cpp"
                | "cxx"
                | "h"
                | "hh"
                | "hpp"
                | "hxx"
                | "inl"
                | "ipp"
                | "m"
                | "mm"
                | "rs"
        )
    })
}

fn normalize_symbol_path(value: &str, prefixes: &[String]) -> String {
    let normalized = value.replace('\\', "/");
    let folded = normalized.to_lowercase();
    let mut ordered = prefixes.iter().collect::<Vec<_>>();
    ordered.sort_by_key(|prefix| std::cmp::Reverse(prefix.len()));
    for prefix in ordered {
        let candidate = format!("{}/", prefix.replace('\\', "/").trim_end_matches('/'));
        if folded.starts_with(&candidate.to_lowercase()) {
            return normalized[candidate.len()..].trim_start_matches('/').to_owned();
        }
    }
    let without_drive =
        if normalized.as_bytes().get(1..3) == Some(b":/") { &normalized[3..] } else { &normalized };
    without_drive.trim_start_matches('/').to_owned()
}

pub(crate) fn resolve_entry<'a>(
    names: &'a [String],
    frame_file: &str,
    prefixes: &[String],
) -> Option<&'a str> {
    let wanted = normalize_symbol_path(frame_file, prefixes).to_lowercase();
    let exact = names.iter().filter(|name| name.to_lowercase() == wanted).collect::<Vec<_>>();
    if exact.len() == 1 {
        return Some(exact[0]);
    }
    let suffix = names
        .iter()
        .filter(|name| name.to_lowercase().ends_with(&format!("/{wanted}")))
        .collect::<Vec<_>>();
    if suffix.len() == 1 {
        return Some(suffix[0]);
    }
    let basename = Path::new(&wanted).file_name()?.to_string_lossy();
    let matches = names
        .iter()
        .filter(|name| {
            Path::new(&name.to_lowercase())
                .file_name()
                .is_some_and(|candidate| candidate == basename.as_ref())
        })
        .collect::<Vec<_>>();
    (matches.len() == 1).then(|| matches[0].as_str())
}

fn clip(value: &str) -> String {
    value.chars().take(1000).collect()
}

fn sha256_bytes(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn sha256_file(path: &Path) -> Result<String, String> {
    let mut file = File::open(path).map_err(io_message)?;
    let mut digest = Sha256::new();
    let mut buffer = [0u8; 1024 * 1024];
    loop {
        let read = file.read(&mut buffer).map_err(io_message)?;
        if read == 0 {
            break;
        }
        digest.update(&buffer[..read]);
    }
    Ok(hex::encode(digest.finalize()))
}

fn io_message(error: io::Error) -> String {
    error.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_frame_source_has_no_context_without_panicking() {
        let names = vec!["scripts/fixtures/null_read_target.cpp".to_owned()];
        assert_eq!(resolve_entry(&names, "runtime/startup.cpp", &[]), None);
        assert_eq!(resolve_entry(&[], "runtime/startup.cpp", &[]), None);
    }

    use crate::canonical::{CanonicalAnalysisResult, FrameInfo};
    use crate::minidump::{InspectDump, InspectProcess, InspectReport, InspectThread};
    use std::time::{SystemTime, UNIX_EPOCH};

    #[test]
    fn relative_path_policy_rejects_escape_and_windows_absolute_forms() {
        assert!(safe_relative(Path::new("src/main.cpp")));
        assert!(!safe_relative(Path::new("../main.cpp")));
        assert!(!safe_relative(Path::new("C:/main.cpp")));
        assert!(!safe_relative(Path::new(r"src\main.cpp")));
    }

    #[test]
    fn source_resolution_requires_a_unique_match() {
        let names = vec!["src/main.cpp".to_owned(), "other/main.cpp".to_owned()];
        assert_eq!(resolve_entry(&names, "src/main.cpp", &[]), Some("src/main.cpp"));
        assert_eq!(resolve_entry(&names, "main.cpp", &[]), None);
    }

    #[test]
    fn staged_source_is_verified_before_core_enrichment() {
        let nonce =
            SystemTime::now().duration_since(UNIX_EPOCH).expect("clock after epoch").as_nanos();
        let root = std::env::temp_dir().join(format!("crash-cap-source-context-{nonce}"));
        let source_root = root.join("source");
        fs::create_dir_all(&source_root).expect("create source root");
        let archive = root.join("bundle.zip");
        let archive_bytes = b"immutable verified archive";
        fs::write(&archive, archive_bytes).expect("write archive sentinel");
        let source = "line 1\nline 2\nline 3\n";
        fs::write(source_root.join("fake.cpp"), source).expect("write source");
        let context_path = root.join("analysis-context.json");
        let value = serde_json::json!({
            "schema_version": "analysis-context-v1",
            "identity": {
                "workspace_id": "wsp_test",
                "occurrence_id": "occ_test",
                "analysis_id": "run_test"
            },
            "dump": {
                "blob_id": "blob_test",
                "sha256": "0".repeat(64),
                "kind": "user_minidump",
                "size": 1,
                "dump_timestamp": null,
                "reported_at": null,
                "uploaded_at": "2025-01-01T00:00:00+00:00",
                "occurred_at": "2025-01-01T00:00:00+00:00",
                "time_source": "uploaded"
            },
            "engine": {
                "core_image_digest": format!("sha256:{}", "0".repeat(64)),
                "symbolicator_version": "test",
                "grouping_version": "group-v1.0",
                "normalization_version": "norm-v1.0"
            },
            "policy": {
                "symbol_inventory_version": 0,
                "source_bundle_policy_version": "source-bundle-v1.0"
            },
            "inspect": {"sha256": "0".repeat(64)},
            "inputs": {
                "source_bundles": [{
                    "build_id": "bld_test",
                    "sha256": sha256_bytes(archive_bytes),
                    "size": archive_bytes.len(),
                    "archive_path": "bundle.zip",
                    "extracted_root": "source",
                    "ingest_metadata": {
                        "policy_version": "source-bundle-v1.0",
                        "entry_count": 1,
                        "source_entry_count": 1,
                        "uncompressed_size": source.len(),
                        "source_entries": ["fake.cpp"]
                    },
                    "source_bundle_config": {"context_lines": 1},
                    "entries": [{
                        "path": "fake.cpp",
                        "sha256": sha256_bytes(source.as_bytes()),
                        "size": source.len()
                    }]
                }]
            }
        });
        fs::write(&context_path, serde_json::to_vec(&value).expect("serialize context"))
            .expect("write context");
        let context: AnalysisContext = serde_json::from_value(value).expect("parse context");
        let mut result = minimal_result();
        result.build_resolution.resolved_build_id = Some("bld_test".to_owned());
        result.threads[0].frames.push(FrameInfo {
            index: 0,
            instruction_addr: "0x1".to_owned(),
            module: None,
            module_debug_id: None,
            relative_addr: None,
            function: None,
            function_raw: None,
            function_normalized: None,
            function_offset: None,
            file: Some("fake.cpp".to_owned()),
            line: Some(2),
            trust: "context".to_owned(),
            in_app: true,
            inline: false,
            source_context: None,
        });

        assert_eq!(context.enrich_source_context(&mut result, &context_path), Ok(1));
        let attached = result.threads[0].frames[0].source_context.as_ref().expect("source context");
        assert_eq!(attached.pre, ["line 1"]);
        assert_eq!(attached.line, "line 2");
        assert_eq!(attached.post, ["line 3"]);

        fs::write(&archive, b"replacement").expect("replace archive");
        assert!(context
            .enrich_source_context(&mut result, &context_path)
            .expect_err("replacement must fail")
            .contains("immutable Run facts"));
        let _ = fs::remove_dir_all(root);
    }

    fn minimal_result() -> CanonicalAnalysisResult {
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
                platform_id: Some(2),
                build_number: None,
                processor_count: Some(1),
            },
            exception: None,
            crash_thread_id: None,
            threads: vec![InspectThread {
                id: 1,
                teb: "0x0".to_owned(),
                stack_start: "0x0".to_owned(),
                stack_size: 0,
                context: None,
            }],
            modules: Vec::new(),
            warnings: Vec::new(),
        };
        CanonicalAnalysisResult::from_inspect(&report, b"x", "wsp_test", "occ_test", "run_test")
    }
}
