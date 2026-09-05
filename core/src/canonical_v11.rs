//! Native Canonical 1.1 assembly from frozen, instance-indexed evidence.
//!
//! This library boundary does not activate a writer. The caller must validate
//! the complete Run/context/manifest, stage and verify the selected bytes, use
//! `unwind_bytes_with_selected_modules`, and validate each partitioned source
//! response before constructing these inputs. No catalog or filesystem lookup
//! occurs here, and legacy name/Code-ID symbol fallbacks are never used.

use crate::canonical::{
    self, CanonicalAnalysisResult, CanonicalInputs, DumpInfo, FrameInfo, ModuleInfo,
    QualityWarning, ThreadInfo,
};
use crate::minidump::{InspectModule, InspectReport};
use crate::symbolicator::SymbolicatedFrame;
use crate::unwind::UnwindReport;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

pub const SCHEMA_VERSION: &str = "2.0";
// CFI scanning no longer receives true-CFI eligibility in Exact. Keep this
// semantic change out of historical group-v1.0 / exact-v1.0 results.
pub const GROUPING_VERSION: &str = "group-v1.1";
pub const EXACT_ALGORITHM: &str = "exact-v1.1";

#[derive(Debug, thiserror::Error)]
#[error("invalid frozen Canonical evidence: {0}")]
pub struct EvidenceError(pub String);

fn require(condition: bool, reason: &str) -> Result<(), EvidenceError> {
    if condition {
        Ok(())
    } else {
        Err(EvidenceError(reason.to_owned()))
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ObjectRef {
    pub object_key: String,
    pub sha256: String,
}

impl ObjectRef {
    fn validate(&self) -> Result<(), EvidenceError> {
        require(!self.object_key.is_empty() && is_hash(&self.sha256), "invalid object reference")
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ModuleIdentity {
    pub code_id: Option<String>,
    pub debug_id: Option<String>,
    pub architecture: String,
}

impl ModuleIdentity {
    pub fn captured(module: &InspectModule, architecture: &str) -> Result<Self, EvidenceError> {
        let code = module.code_id.to_ascii_lowercase();
        require((9..=24).contains(&code.len()) && is_hex(&code), "invalid captured Code ID")?;
        let debug = module
            .debug_id
            .as_ref()
            .map(|id| {
                let id = id.replace('-', "").to_ascii_lowercase();
                require((33..=40).contains(&id.len()) && is_hex(&id), "invalid captured Debug ID")?;
                let age = u32::from_str_radix(&id[32..], 16)
                    .map_err(|_| EvidenceError("invalid Debug ID age".to_owned()))?;
                Ok(format!("{}{:x}", &id[..32], age))
            })
            .transpose()?;
        require(
            matches!(architecture, "x86_64" | "x86" | "arm64" | "unknown"),
            "invalid architecture",
        )?;
        Ok(Self { code_id: Some(code), debug_id: debug, architecture: architecture.to_owned() })
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct FrozenSelection {
    pub module_index: usize,
    pub identity: ModuleIdentity,
    pub state: String,
    pub candidates_complete: bool,
    pub candidate_pair_ids: Vec<String>,
    pub unavailable_pair_ids: Vec<String>,
    pub selected_pair_id: Option<String>,
    pub reason: String,
    pub candidate_evidence: ObjectRef,
    pub review_refs: Vec<String>,
}

impl FrozenSelection {
    pub(crate) fn validate(
        &self,
        index: usize,
        module: &InspectModule,
        architecture: &str,
    ) -> Result<(), EvidenceError> {
        require(
            self.module_index == index,
            "selection must cover every captured module once in order",
        )?;
        require(
            self.identity == ModuleIdentity::captured(module, architecture)?,
            "captured module identity mismatch",
        )?;
        for ids in [&self.candidate_pair_ids, &self.unavailable_pair_ids] {
            require(
                ids.iter().all(|id| is_hash(id)) && ids.windows(2).all(|w| w[0] < w[1]),
                "pair IDs must be sorted unique SHA-256 values",
            )?;
        }
        self.candidate_evidence.validate()?;
        require(self.review_refs.iter().all(|r| !r.is_empty()), "empty review reference")?;
        require(
            self.state == "indeterminate"
                || !self
                    .candidate_pair_ids
                    .iter()
                    .any(|id| self.unavailable_pair_ids.binary_search(id).is_ok()),
            "one pair has contradictory availability observations",
        )?;
        let selected = self.selected_pair_id.as_ref();
        let valid = match self.state.as_str() {
            "unique" => {
                self.candidates_complete
                    && self.reason == "unique"
                    && (self.identity.code_id.is_some() || self.identity.debug_id.is_some())
                    && self.candidate_pair_ids.len() == 1
                    && selected == self.candidate_pair_ids.first()
            }
            "conflict" => {
                self.candidates_complete
                    && self.reason == "identity_conflict"
                    && self.candidate_pair_ids.len() >= 2
                    && selected.is_none()
            }
            "none" => {
                self.candidates_complete
                    && self.reason == "missing"
                    && self.candidate_pair_ids.is_empty()
                    && self.unavailable_pair_ids.is_empty()
                    && selected.is_none()
            }
            "unavailable" => {
                self.candidates_complete
                    && matches!(self.reason.as_str(), "withdrawn" | "location_unavailable")
                    && self.candidate_pair_ids.is_empty()
                    && !self.unavailable_pair_ids.is_empty()
                    && selected.is_none()
            }
            "indeterminate" => {
                !self.candidates_complete
                    && matches!(
                        self.reason.as_str(),
                        "incomplete_identity" | "enumeration_failed" | "validation_incomplete"
                    )
                    && selected.is_none()
            }
            _ => false,
        };
        require(valid, "selection state, completeness, candidates and reason contradict")
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct SourceOutcome {
    pub source_id: String,
    pub stage: String,
    pub outcome: String,
    pub failure_class: String,
    pub reason: String,
    pub diagnostic_ref: Option<ObjectRef>,
}

impl SourceOutcome {
    fn validate(&self) -> Result<(), EvidenceError> {
        require(!self.source_id.is_empty() && !self.reason.is_empty(), "empty source diagnostic")?;
        require(
            matches!(
                self.stage.as_str(),
                "download_pe" | "download_pdb" | "unwind" | "symbolicate"
            ),
            "invalid source stage",
        )?;
        require(
            matches!(self.outcome.as_str(), "found" | "missing" | "failed" | "blocked" | "unknown"),
            "invalid source outcome",
        )?;
        require(
            matches!(self.failure_class.as_str(), "none" | "transient" | "permanent" | "unknown"),
            "invalid failure class",
        )?;
        require(
            (self.outcome == "found") == (self.failure_class == "none"),
            "source success and failure class contradict",
        )?;
        require(
            self.failure_class != "transient"
                || (self.outcome == "failed" && self.diagnostic_ref.is_some()),
            "transient requires correlated failure evidence",
        )?;
        if let Some(reference) = &self.diagnostic_ref {
            reference.validate()?;
        }
        Ok(())
    }
}

#[derive(Debug, Clone)]
pub struct FrozenModule {
    pub selection: FrozenSelection,
    /// Supplied exclusively by the frozen Workspace policy, never inferred.
    pub role: String,
    pub in_app: bool,
    pub artifact_ids: Vec<String>,
    pub source_outcomes: Vec<SourceOutcome>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct SymbolResolution {
    pub selection_version: String,
    pub resolution_evidence_fingerprint: String,
    pub selection: ObjectRef,
    pub inspect_sha256: String,
    pub context_sha256: String,
}

#[derive(Debug, Clone)]
pub struct FrozenInputs {
    pub workspace_id: String,
    pub occurrence_id: String,
    pub analysis_id: String,
    pub dump: DumpInfo,
    pub core_image_digest: String,
    pub symbolicator_version: String,
    pub modules: Vec<FrozenModule>,
    /// IDs from the frozen deployment source policy; never supplied by an upload.
    pub public_source_ids: Vec<String>,
    pub symbol_resolution: SymbolResolution,
}

/// One source response already validated against its frozen request. A PC alone
/// is not a key: recursion and distinct module instances retain separate slots.
#[derive(Debug, Clone)]
pub struct FrameSymbol {
    pub thread_index: usize,
    pub physical_frame_index: usize,
    pub module_index: usize,
    pub instruction: u64,
    pub pair_id: Option<String>,
    pub source_id: String,
    pub symbol: SymbolicatedFrame,
}

#[derive(Debug, Clone, Serialize)]
pub struct FrameV11 {
    #[serde(flatten)]
    pub frame: FrameInfo,
    pub module_index: Option<usize>,
    pub physical_frame_index: usize,
    pub unwind_method: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ThreadV11 {
    pub id: u32,
    pub name: Option<String>,
    pub is_crashing: bool,
    pub frames: Vec<FrameV11>,
}

#[derive(Debug, Clone, Serialize)]
pub struct ModuleV11 {
    #[serde(flatten)]
    pub module: ModuleInfo,
    pub module_index: usize,
    pub selection: FrozenSelection,
    pub source_outcomes: Vec<SourceOutcome>,
}

#[derive(Debug, Clone, Serialize)]
pub struct CanonicalResultV11 {
    pub schema_version: String,
    pub workspace_id: String,
    pub occurrence_id: String,
    pub analysis_id: String,
    pub engine: canonical::EngineInfo,
    pub dump: DumpInfo,
    pub process: canonical::ProcessInfo,
    pub crash: canonical::CrashInfo,
    pub threads: Vec<ThreadV11>,
    pub modules: Vec<ModuleV11>,
    pub quality: canonical::QualityInfo,
    pub fingerprints: canonical::Fingerprints,
    pub symbol_resolution: SymbolResolution,
}

/// Assemble without any lookup by filename, Debug ID alone, or Code ID alone.
/// `inspect_bytes` is the exact frozen object; its contents are checked against
/// an independent native inspection of `dump_bytes` before interpreting frames.
pub fn assemble(
    inspect_bytes: &[u8],
    dump_bytes: &[u8],
    unwind: &UnwindReport,
    symbols: &[FrameSymbol],
    inputs: FrozenInputs,
) -> Result<CanonicalResultV11, EvidenceError> {
    let report: InspectReport = serde_json::from_slice(inspect_bytes)
        .map_err(|_| EvidenceError("invalid inspect object".to_owned()))?;
    let actual = crate::minidump::inspect_bytes(dump_bytes)
        .map_err(|_| EvidenceError("native inspection failed".to_owned()))?;
    require(report == actual, "frozen inspect differs from native Dump inspection")?;
    require(
        canonical::sha256_hex(inspect_bytes) == inputs.symbol_resolution.inspect_sha256,
        "inspect object digest mismatch",
    )?;
    validate_inputs(&report, dump_bytes, &inputs)?;
    assemble_checked(&report, dump_bytes, unwind, symbols, inputs)
}

fn validate_inputs(
    report: &InspectReport,
    dump_bytes: &[u8],
    inputs: &FrozenInputs,
) -> Result<(), EvidenceError> {
    require(
        [
            &inputs.workspace_id,
            &inputs.occurrence_id,
            &inputs.analysis_id,
            &inputs.symbolicator_version,
        ]
        .iter()
        .all(|v| !v.is_empty()),
        "missing immutable identity or engine version",
    )?;
    require(
        inputs.core_image_digest.strip_prefix("sha256:").is_some_and(is_hash),
        "invalid Core image digest",
    )?;
    let resolution = &inputs.symbol_resolution;
    resolution.selection.validate()?;
    require(
        resolution.selection_version == "pair-selection-v1"
            && is_hash(&resolution.context_sha256)
            && is_hash(&resolution.resolution_evidence_fingerprint),
        "invalid frozen resolution reference",
    )?;
    require(
        inputs.dump.sha256 == canonical::sha256_hex(dump_bytes)
            && inputs.dump.size == dump_bytes.len() as u64
            && inputs.dump.size == report.dump.size
            && inputs.dump.kind == report.dump.kind
            && inputs.dump.dump_timestamp == report.dump.timestamp,
        "frozen Dump facts differ from native evidence",
    )?;
    require(!inputs.dump.blob_id.is_empty(), "missing Blob identity")?;
    require(
        matches!(
            inputs.dump.capture_profile.as_deref(),
            None | Some("light-crash" | "rich-crash" | "hang" | "full-memory")
        ),
        "invalid capture profile",
    )?;
    for timestamp in [
        Some(&inputs.dump.uploaded_at),
        Some(&inputs.dump.occurred_at),
        inputs.dump.reported_at.as_ref(),
        inputs.dump.dump_timestamp.as_ref(),
    ]
    .into_iter()
    .flatten()
    {
        require(
            chrono::DateTime::parse_from_rfc3339(timestamp).is_ok(),
            "invalid frozen timestamp",
        )?;
    }
    let expected_time = match inputs.dump.time_source.as_str() {
        "dump" => inputs.dump.dump_timestamp.as_ref(),
        "reported" => inputs.dump.reported_at.as_ref(),
        "uploaded" => Some(&inputs.dump.uploaded_at),
        "manual" => Some(&inputs.dump.occurred_at),
        _ => None,
    };
    require(
        expected_time == Some(&inputs.dump.occurred_at),
        "occurred_at contradicts time_source",
    )?;
    require(inputs.modules.len() == report.modules.len(), "frozen modules do not cover inspect")?;
    require(
        inputs.public_source_ids.iter().all(|s| !s.is_empty())
            && inputs.public_source_ids.windows(2).all(|w| w[0] < w[1]),
        "public source IDs must be sorted and unique",
    )?;
    for (index, (frozen, captured)) in inputs.modules.iter().zip(&report.modules).enumerate() {
        frozen.selection.validate(index, captured, &report.process.architecture)?;
        require(
            matches!(
                frozen.role.as_str(),
                "entrypoint" | "owned" | "dependency" | "system" | "unknown"
            ) && frozen.in_app == matches!(frozen.role.as_str(), "entrypoint" | "owned"),
            "role and in_app contradict",
        )?;
        require(
            frozen.artifact_ids.iter().all(|s| !s.is_empty())
                && frozen.artifact_ids.windows(2).all(|w| w[0] < w[1]),
            "artifact IDs must be sorted and unique",
        )?;
        let mut stages = BTreeSet::new();
        for outcome in &frozen.source_outcomes {
            outcome.validate()?;
            require(
                stages.insert((&outcome.source_id, &outcome.stage)),
                "duplicate terminal source stage",
            )?;
            if matches!(
                frozen.selection.state.as_str(),
                "conflict" | "unavailable" | "indeterminate"
            ) {
                require(
                    outcome.outcome == "blocked",
                    "blocked module cannot contain a source request outcome",
                )?;
            }
        }
    }
    Ok(())
}

fn assemble_checked(
    report: &InspectReport,
    dump_bytes: &[u8],
    unwind: &UnwindReport,
    symbols: &[FrameSymbol],
    inputs: FrozenInputs,
) -> Result<CanonicalResultV11, EvidenceError> {
    let mut ranges = Vec::new();
    for (index, module) in report.modules.iter().enumerate() {
        let base = u64::from_str_radix(module.image_base.trim_start_matches("0x"), 16)
            .map_err(|_| EvidenceError("invalid module range".to_owned()))?;
        let end = base
            .checked_add(u64::from(module.image_size))
            .ok_or_else(|| EvidenceError("module range overflow".to_owned()))?;
        if end > base {
            ranges.push((base, end, index));
        }
    }
    ranges.sort_unstable();
    require(
        ranges.windows(2).all(|w| w[0].1 <= w[1].0),
        "overlapping captured modules are ambiguous",
    )?;
    let module_at =
        |pc: u64| ranges.iter().find(|(base, end, _)| pc >= *base && pc < *end).map(|(_, _, i)| *i);
    require(
        unwind.threads.len() == report.threads.len()
            && unwind.threads.iter().zip(&report.threads).all(|(a, b)| a.id == b.id)
            && unwind.threads.iter().map(|t| t.id).collect::<BTreeSet<_>>().len()
                == unwind.threads.len(),
        "unwind thread instances differ from inspect",
    )?;
    let mut packets = BTreeMap::new();
    for packet in symbols {
        let frame = unwind
            .threads
            .get(packet.thread_index)
            .and_then(|t| t.frames.get(packet.physical_frame_index))
            .ok_or_else(|| {
                EvidenceError("symbol packet references absent physical frame".to_owned())
            })?;
        require(
            frame.instruction == packet.instruction
                && module_at(frame.instruction) == Some(packet.module_index),
            "symbol packet PC/module provenance mismatch",
        )?;
        let module = &inputs.modules[packet.module_index];
        let allowed = match &packet.pair_id {
            Some(pair_id) => {
                module.selection.state == "unique"
                    && module.selection.selected_pair_id.as_ref() == Some(pair_id)
            }
            None => {
                module.selection.state == "none"
                    && inputs.public_source_ids.binary_search(&packet.source_id).is_ok()
            }
        };
        require(allowed, "symbol packet is not from the frozen selected or public source")?;
        require(
            module.source_outcomes.iter().any(|o| {
                o.source_id == packet.source_id
                    && o.stage == "symbolicate"
                    && o.outcome == "found"
                    && o.diagnostic_ref.is_some()
            }),
            "symbol packet lacks correlated successful source evidence",
        )?;
        require(
            packet.symbol.inline.iter().all(|s| s.inline.is_empty()),
            "nested inline records are not physical source responses",
        )?;
        require(
            packets
                .insert((packet.thread_index, packet.physical_frame_index), &packet.symbol)
                .is_none(),
            "duplicate physical symbol packet",
        )?;
    }
    let modules = inputs
        .modules
        .iter()
        .zip(&report.modules)
        .map(|(frozen, captured)| ModuleInfo {
            code_file: captured.code_file.clone(),
            code_id: Some(captured.code_id.clone()),
            debug_file: captured.debug_file.clone(),
            debug_id: captured.debug_id.clone(),
            image_base: Some(captured.image_base.clone()),
            image_size: Some(u64::from(captured.image_size)),
            role: frozen.role.clone(),
            in_app: frozen.in_app,
            artifact_ids: frozen.artifact_ids.clone(),
            status: match frozen.selection.state.as_str() {
                "unique" => "matched",
                "conflict" => "symbol_conflict",
                "unavailable" => "symbol_unavailable",
                "indeterminate" => "symbol_indeterminate",
                "none"
                    if frozen.source_outcomes.iter().any(|o| {
                        o.stage == "unwind"
                            && o.outcome == "found"
                            && o.reason == "identity_verified_for_unwind"
                    }) =>
                {
                    if frozen
                        .source_outcomes
                        .iter()
                        .any(|o| o.stage == "download_pdb" && o.outcome == "found")
                    {
                        "matched"
                    } else {
                        "missing_pdb"
                    }
                }
                _ => "missing_pe",
            }
            .to_owned(),
        })
        .collect::<Vec<_>>();
    let mut threads = Vec::new();
    let mut provenance = Vec::new();
    for (thread_index, raw_thread) in unwind.threads.iter().enumerate() {
        let mut frames = Vec::new();
        let mut thread_provenance = Vec::new();
        for (physical_index, raw) in raw_thread.frames.iter().enumerate() {
            let method = raw.unwind_method.as_deref().ok_or_else(|| {
                EvidenceError(
                    "native unwind method is absent; folded legacy trust is insufficient"
                        .to_owned(),
                )
            })?;
            let (folded, effective) = match method {
                "context" => ("context", "context"),
                "call_frame_info" => ("cfi", "cfi"),
                "cfi_scan" => ("cfi", "scan"),
                "frame_pointer" => ("frame_pointer", "frame_pointer"),
                "scan" => ("scan", "scan"),
                "prewalked" | "unknown" => ("unknown", "unknown"),
                _ => return Err(EvidenceError("unsupported native unwind method".to_owned())),
            };
            require(raw.trust == folded, "folded trust contradicts native unwind method")?;
            let module_index = module_at(raw.instruction);
            let captured = module_index.map(|i| &report.modules[i]);
            let module = module_index.map(|i| &modules[i]);
            let base = module_index
                .and_then(|i| ranges.iter().find(|(_, _, r)| *r == i).map(|(b, _, _)| *b));
            let relative = base.map(|base| raw.instruction - base);
            // A raw engine function may originate in an untracked local file.
            // Only explicitly associated frozen source symbols enter 1.1.
            let mut clean = raw.clone();
            clean.function = None;
            clean.file = None;
            clean.line = None;
            clean.module = None;
            clean.trust = effective.to_owned();
            let symbol = packets.get(&(thread_index, physical_index)).copied();
            let mut records = vec![(symbol, false)];
            if let Some(symbol) = symbol {
                // The partition adapter supplies inline-only records separately
                // from the physical symbol. Preserve repeats and recursion.
                records.extend(symbol.inline.iter().map(|s| (Some(s), true)));
            }
            for (symbol, inline) in records {
                let index = u32::try_from(frames.len())
                    .map_err(|_| EvidenceError("too many frames".to_owned()))?;
                frames.push(canonical::frame_info(
                    &clean,
                    index,
                    captured.map(|m| m.code_file.clone()),
                    captured,
                    relative,
                    module,
                    symbol,
                    inline,
                ));
                thread_provenance.push((
                    module_index,
                    physical_index,
                    method.to_owned(),
                    folded.to_owned(),
                ));
            }
        }
        threads.push(ThreadInfo {
            id: raw_thread.id,
            name: None,
            is_crashing: Some(raw_thread.id) == report.crash_thread_id,
            frames,
        });
        provenance.push(thread_provenance);
    }
    let mut base = CanonicalAnalysisResult::from_prepared(
        report,
        dump_bytes,
        CanonicalInputs {
            workspace_id: inputs.workspace_id,
            occurrence_id: inputs.occurrence_id,
            analysis_id: inputs.analysis_id,
            capture_profile: inputs.dump.capture_profile.clone(),
            match_report: None,
            symbolicator_version: inputs.symbolicator_version,
            core_image_digest: Some(inputs.core_image_digest),
            ..Default::default()
        },
        Some((modules, threads)),
    );
    base.engine.grouping_version = GROUPING_VERSION.to_owned();
    base.fingerprints.algorithm = EXACT_ALGORITHM.to_owned();
    if base.engine.core_image_digest == format!("sha256:{}", "0".repeat(64)) {
        base.quality.warnings.push(QualityWarning {
            code: "other".to_owned(),
            message: "local zero image digest is not an OCI attestation".to_owned(),
            module: None,
            debug_id: None,
        });
    }
    for (frozen, module) in inputs.modules.iter().zip(&base.modules) {
        if matches!(frozen.selection.state.as_str(), "conflict" | "unavailable" | "indeterminate") {
            base.quality.warnings.push(QualityWarning {
                code: "other".to_owned(),
                message: format!(
                    "frozen selection {}: {}",
                    frozen.selection.state, frozen.selection.reason
                ),
                module: Some(module.code_file.clone()),
                debug_id: module.debug_id.clone(),
            });
        }
        for outcome in
            frozen.source_outcomes.iter().filter(|o| o.outcome != "found" && o.outcome != "blocked")
        {
            base.quality.warnings.push(QualityWarning {
                code: "other".to_owned(),
                message: format!(
                    "source {} stage {} outcome {} ({})",
                    outcome.source_id, outcome.stage, outcome.outcome, outcome.failure_class
                ),
                module: Some(module.code_file.clone()),
                debug_id: module.debug_id.clone(),
            });
        }
    }
    let threads = base
        .threads
        .into_iter()
        .zip(provenance)
        .map(|(thread, provenance)| ThreadV11 {
            id: thread.id,
            name: thread.name,
            is_crashing: thread.is_crashing,
            frames: thread
                .frames
                .into_iter()
                .zip(provenance)
                .map(|(mut frame, (module_index, physical_frame_index, unwind_method, folded))| {
                    frame.trust = folded;
                    FrameV11 { frame, module_index, physical_frame_index, unwind_method }
                })
                .collect(),
        })
        .collect();
    let modules = base
        .modules
        .into_iter()
        .zip(inputs.modules)
        .enumerate()
        .map(|(module_index, (module, frozen))| ModuleV11 {
            module,
            module_index,
            selection: frozen.selection,
            source_outcomes: frozen.source_outcomes,
        })
        .collect();
    Ok(CanonicalResultV11 {
        schema_version: SCHEMA_VERSION.to_owned(),
        workspace_id: base.workspace_id,
        occurrence_id: base.occurrence_id,
        analysis_id: base.analysis_id,
        engine: base.engine,
        dump: inputs.dump,
        process: base.process,
        crash: base.crash,
        threads,
        modules,
        quality: base.quality,
        fingerprints: base.fingerprints,
        symbol_resolution: inputs.symbol_resolution,
    })
}

fn is_hex(value: &str) -> bool {
    !value.is_empty() && value.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
}
fn is_hash(value: &str) -> bool {
    value.len() == 64 && is_hex(value)
}

#[cfg(test)]
#[path = "canonical_v11_tests.rs"]
mod tests;
