use crate::artifact::{BuildResolutionEvidence, MatchReport};
use crate::minidump::{InspectModule, InspectReport};
use crate::symbolicator::{FrameKey, SymbolicationResult};
use crate::unwind::{UnwindFrame, UnwindReport};
use chrono::Utc;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

pub const SCHEMA_VERSION: &str = "1.0";
pub const NORMALIZATION_VERSION: &str = "norm-v1.0";
pub const GROUPING_VERSION: &str = "group-v1.0";
pub const EXACT_ALGORITHM: &str = "exact-v1.0";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CanonicalAnalysisResult {
    pub schema_version: String,
    pub workspace_id: String,
    pub occurrence_id: String,
    pub analysis_id: String,
    pub engine: EngineInfo,
    pub build_resolution: BuildResolution,
    pub dump: DumpInfo,
    pub process: ProcessInfo,
    pub crash: CrashInfo,
    pub threads: Vec<ThreadInfo>,
    pub modules: Vec<ModuleInfo>,
    pub quality: QualityInfo,
    pub fingerprints: Fingerprints,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct EngineInfo {
    pub core_version: String,
    pub core_image_digest: String,
    pub symbolicator_version: String,
    pub grouping_version: String,
    pub normalization_version: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BuildResolution {
    pub reported_build_id: Option<String>,
    pub resolved_build_id: Option<String>,
    pub resolution_method: String,
    pub evidence: BuildEvidence,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct BuildEvidence {
    pub candidate_build_ids: Vec<String>,
    pub matched_entrypoints: Vec<String>,
    pub matched_owned_modules: Vec<String>,
    pub conflicting_modules: Vec<String>,
    pub note: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct DumpInfo {
    pub blob_id: String,
    pub sha256: String,
    pub kind: String,
    pub size: u64,
    pub capture_profile: Option<String>,
    pub dump_timestamp: Option<String>,
    pub reported_at: Option<String>,
    pub uploaded_at: String,
    pub occurred_at: String,
    pub time_source: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ProcessInfo {
    pub pid: Option<u32>,
    pub architecture: String,
    pub os: String,
    pub os_version: Option<String>,
    pub uptime_seconds: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CrashInfo {
    pub r#type: String,
    pub type_evidence: String,
    pub thread_id: Option<u32>,
    pub exception_code: Option<String>,
    pub exception_name: Option<String>,
    pub access_type: Option<String>,
    pub address: Option<String>,
    pub fault_module: Option<String>,
    pub fault_module_debug_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ThreadInfo {
    pub id: u32,
    pub name: Option<String>,
    pub is_crashing: bool,
    pub frames: Vec<FrameInfo>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct FrameInfo {
    pub index: u32,
    pub instruction_addr: String,
    pub module: Option<String>,
    pub module_debug_id: Option<String>,
    pub relative_addr: Option<String>,
    pub function: Option<String>,
    pub function_raw: Option<String>,
    pub function_normalized: Option<String>,
    pub function_offset: Option<u64>,
    pub file: Option<String>,
    pub line: Option<u64>,
    pub trust: String,
    pub in_app: bool,
    pub inline: bool,
    pub source_context: Option<SourceContext>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SourceContext {
    pub pre: Vec<String>,
    pub line: String,
    pub post: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ModuleInfo {
    pub code_file: String,
    pub code_id: Option<String>,
    pub debug_file: Option<String>,
    pub debug_id: Option<String>,
    pub image_base: Option<String>,
    pub image_size: Option<u64>,
    pub role: String,
    pub in_app: bool,
    pub artifact_ids: Vec<String>,
    pub status: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct QualityInfo {
    pub score: f64,
    pub symbol_coverage: f64,
    pub unwind_reliability: f64,
    pub artifact_completeness: f64,
    pub warnings: Vec<QualityWarning>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct QualityWarning {
    pub code: String,
    pub message: String,
    pub module: Option<String>,
    pub debug_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Fingerprints {
    pub exact: Option<String>,
    pub family: Option<String>,
    pub algorithm: String,
}

#[derive(Debug, Clone, Default)]
pub struct CanonicalInputs {
    pub workspace_id: String,
    pub occurrence_id: String,
    pub analysis_id: String,
    pub capture_profile: Option<String>,
    pub match_report: Option<MatchReport>,
    pub unwind: Option<UnwindReport>,
    pub symbolication: Option<SymbolicationResult>,
    pub symbolicator_version: String,
    pub core_image_digest: Option<String>,
}

impl CanonicalAnalysisResult {
    /// Backwards-compatible partial result for callers that only have inspect
    /// evidence. Full `analyze` runs use [`Self::from_evidence`].
    pub fn from_inspect(
        report: &InspectReport,
        dump_bytes: &[u8],
        workspace_id: impl Into<String>,
        occurrence_id: impl Into<String>,
        analysis_id: impl Into<String>,
    ) -> Self {
        Self::from_evidence(
            report,
            dump_bytes,
            CanonicalInputs {
                workspace_id: workspace_id.into(),
                occurrence_id: occurrence_id.into(),
                analysis_id: analysis_id.into(),
                ..Default::default()
            },
        )
    }

    pub fn from_evidence(
        report: &InspectReport,
        dump_bytes: &[u8],
        inputs: CanonicalInputs,
    ) -> Self {
        Self::from_prepared(report, dump_bytes, inputs, None)
    }

    /// Shared normalization after the version-specific evidence association.
    /// The legacy caller retains its original matching and frame semantics.
    pub(crate) fn from_prepared(
        report: &InspectReport,
        dump_bytes: &[u8],
        inputs: CanonicalInputs,
        prepared: Option<(Vec<ModuleInfo>, Vec<ThreadInfo>)>,
    ) -> Self {
        let (prepared_modules, prepared_threads) = match prepared {
            Some((modules, threads)) => (Some(modules), Some(threads)),
            None => (None, None),
        };
        let digest = sha256_hex(dump_bytes);
        let now = Utc::now().to_rfc3339();
        let exception = report.exception.as_ref();
        let hang_requested = inputs.capture_profile.as_deref() == Some("hang");
        let crash_type = if exception.is_some() {
            "crash"
        } else if hang_requested {
            "hang"
        } else {
            "unknown"
        };
        let type_evidence = if exception.is_some() {
            "exception_stream"
        } else if hang_requested {
            "reported_hang"
        } else {
            "insufficient"
        };
        let fault_module = exception.and_then(|value| module_for_address(report, &value.address));
        let fault_module_debug_id = fault_module.and_then(|module| module.debug_id.clone());
        let modules = prepared_modules.unwrap_or_else(|| {
            report
                .modules
                .iter()
                .map(|module| canonical_module_with_match(module, inputs.match_report.as_ref()))
                .collect::<Vec<_>>()
        });
        let unwind = inputs.unwind.as_ref();
        let symbolication = inputs.symbolication.as_ref();
        let mut suppressed_symbol_count = 0usize;
        let threads = prepared_threads.unwrap_or_else(|| {
            report
                .threads
                .iter()
                .map(|thread| {
                    let frames = unwind
                        .and_then(|value| {
                            value.threads.iter().find(|candidate| candidate.id == thread.id)
                        })
                        .map(|candidate| {
                            candidate
                                .frames
                                .iter()
                                .enumerate()
                                .flat_map(|(index, frame)| {
                                    canonical_frames(
                                        report,
                                        frame,
                                        index as u32,
                                        symbolication,
                                        &modules,
                                        &mut suppressed_symbol_count,
                                    )
                                })
                                .collect()
                        })
                        .unwrap_or_default();
                    ThreadInfo {
                        id: thread.id,
                        name: None,
                        is_crashing: Some(thread.id) == report.crash_thread_id,
                        frames,
                    }
                })
                .collect::<Vec<_>>()
        });

        let mut warnings = report
            .warnings
            .iter()
            .map(|warning| QualityWarning {
                code: warning_code(&warning.code),
                message: warning.message.clone(),
                module: None,
                debug_id: None,
            })
            .collect::<Vec<_>>();
        let core_image_digest = inputs
            .core_image_digest
            .clone()
            .unwrap_or_else(|| format!("sha256:{}", "0".repeat(64)));
        if inputs.core_image_digest.is_none() {
            warnings.push(QualityWarning { code: "other".to_owned(), message: "core image digest was not supplied; local zero sentinel is not an OCI attestation".to_owned(), module: None, debug_id: None });
        }
        let match_report = inputs.match_report.as_ref();
        for module in &modules {
            warning_for_status(module, symbolication, &mut warnings);
        }
        if suppressed_symbol_count > 0 {
            warnings.push(QualityWarning {
                // The stable v1 contract keeps the warning-code vocabulary closed;
                // retain the exact count in the safe, schema-approved
                // message rather than widening contracts in Phase 0.
                code: "other".to_owned(),
                message: format!(
                    "Symbolicator symbol ignored count: {suppressed_symbol_count}; module artifact status is not symbol-safe"
                ),
                module: None,
                debug_id: None,
            });
        }
        if let Some(symbolication) = symbolication {
            if symbolication.rejected_frames > 0 {
                warnings.push(QualityWarning {
                    // Keep this count-only diagnostic within the stable v1 warning
                    // enum; raw response fields are intentionally omitted.
                    code: "other".to_owned(),
                    message: format!(
                        "Symbolicator frame provenance rejected count: {}",
                        symbolication.rejected_frames
                    ),
                    module: None,
                    debug_id: None,
                });
            }
        }
        if exception.is_none() {
            warnings.push(QualityWarning {
                code: "unknown_crash_type".to_owned(),
                message: if hang_requested {
                    "hang profile was explicitly reported without an exception stream".to_owned()
                } else {
                    "no exception stream was available".to_owned()
                },
                module: None,
                debug_id: None,
            });
        }
        if let Some(evidence) = match_report.map(|value| &value.build_resolution) {
            if evidence.resolution_method == "ambiguous" {
                warnings.push(QualityWarning {
                    code: "ambiguous_build".to_owned(),
                    message: evidence
                        .note
                        .clone()
                        .unwrap_or_else(|| "multiple exact Build candidates remain".to_owned()),
                    module: None,
                    debug_id: None,
                });
            } else if evidence.resolution_method == "unresolved" {
                warnings.push(QualityWarning {
                    code: "unresolved_build".to_owned(),
                    message: evidence
                        .note
                        .clone()
                        .unwrap_or_else(|| "no exact Build candidate matched".to_owned()),
                    module: None,
                    debug_id: None,
                });
            }
        }
        let (symbol_coverage, unwind_reliability, artifact_completeness) =
            quality(&threads, &modules, &mut warnings);
        let exact = exact_fingerprint(
            &inputs.workspace_id,
            crash_type,
            exception,
            report.crash_thread_id,
            &modules,
            &threads,
        );
        if crash_type == "crash" && exact.is_none() {
            warnings.push(QualityWarning {
                code: "unclassified_exact".to_owned(),
                message: "Exact prerequisites were not all satisfied".to_owned(),
                module: None,
                debug_id: fault_module_debug_id.clone(),
            });
        }
        let score =
            0.45 * symbol_coverage + 0.35 * unwind_reliability + 0.20 * artifact_completeness;
        let build_resolution = match_report
            .map(|value| build_resolution(value.build_resolution.clone()))
            .unwrap_or_else(default_build_resolution);
        Self {
            schema_version: SCHEMA_VERSION.to_owned(),
            workspace_id: inputs.workspace_id,
            occurrence_id: inputs.occurrence_id,
            analysis_id: inputs.analysis_id,
            engine: EngineInfo {
                core_version: env!("CARGO_PKG_VERSION").to_owned(),
                core_image_digest,
                symbolicator_version: inputs.symbolicator_version,
                grouping_version: GROUPING_VERSION.to_owned(),
                normalization_version: NORMALIZATION_VERSION.to_owned(),
            },
            build_resolution,
            dump: DumpInfo {
                blob_id: format!("blob_{}", &digest[..16]),
                sha256: digest,
                kind: report.dump.kind.clone(),
                size: report.dump.size,
                capture_profile: inputs.capture_profile,
                dump_timestamp: report.dump.timestamp.clone(),
                reported_at: None,
                uploaded_at: now.clone(),
                occurred_at: now,
                time_source: "uploaded".to_owned(),
            },
            process: ProcessInfo {
                pid: report.process.pid,
                architecture: report.process.architecture.clone(),
                os: report.process.os.clone(),
                os_version: report.process.os_version.clone(),
                uptime_seconds: None,
            },
            crash: CrashInfo {
                r#type: crash_type.to_owned(),
                type_evidence: type_evidence.to_owned(),
                thread_id: exception.map(|value| value.thread_id),
                exception_code: exception.map(|value| value.code.clone()),
                exception_name: exception.and_then(|value| value.name.clone()),
                access_type: exception.and_then(|value| value.access_type.clone()),
                address: exception.map(|value| lower_hex(&value.address)),
                fault_module: fault_module.map(|module| module.code_file.clone()),
                fault_module_debug_id,
            },
            threads,
            modules,
            quality: QualityInfo {
                score,
                symbol_coverage,
                unwind_reliability,
                artifact_completeness,
                warnings,
            },
            fingerprints: Fingerprints {
                exact,
                family: None,
                algorithm: EXACT_ALGORITHM.to_owned(),
            },
        }
    }
}

fn canonical_module_with_match(
    module: &InspectModule,
    matched: Option<&MatchReport>,
) -> ModuleInfo {
    let exact = matched.and_then(|report| {
        report.modules.iter().find(|candidate| {
            candidate.code_id.as_deref().is_some_and(|id| id.eq_ignore_ascii_case(&module.code_id))
        })
    });
    let inferred_role = infer_role_for_canonical(&module.code_file);
    ModuleInfo {
        code_file: module.code_file.clone(),
        code_id: Some(module.code_id.clone()),
        debug_file: module.debug_file.clone(),
        debug_id: module.debug_id.clone(),
        image_base: Some(lower_hex(&module.image_base)),
        image_size: Some(module.image_size as u64),
        role: exact.map(|value| value.role.clone()).unwrap_or_else(|| inferred_role.clone()),
        in_app: exact
            .map(|value| value.in_app)
            .unwrap_or_else(|| matches!(inferred_role.as_str(), "entrypoint" | "owned")),
        artifact_ids: exact.map(|value| value.artifact_ids.clone()).unwrap_or_default(),
        status: exact.map(|value| value.status.clone()).unwrap_or_else(|| "missing_pe".to_owned()),
    }
}

fn canonical_frames(
    report: &InspectReport,
    frame: &UnwindFrame,
    index: u32,
    symbolication: Option<&SymbolicationResult>,
    modules: &[ModuleInfo],
    suppressed_symbol_count: &mut usize,
) -> Vec<FrameInfo> {
    let dump_module = module_for_instruction(report, frame.instruction);
    let module_name = dump_module
        .map(|value| value.code_file.clone())
        .or_else(|| frame.module.as_ref().map(|value| value.code_file.clone()));
    let module_info = dump_module.and_then(|value| {
        modules
            .iter()
            .find(|candidate| candidate.code_id.as_deref() == Some(value.code_id.as_str()))
    });
    let relative = dump_module.and_then(|module| {
        let base = parse_hex(&module.image_base)?;
        frame.instruction.checked_sub(base)
    });
    let candidate_symbol = symbolication
        .and_then(|value| find_symbol(value, module_name.as_deref(), frame.instruction));
    let symbol_allowed = module_info.is_some_and(|module| {
        module.status == "matched"
            || (module.status == "system_symbol_pending"
                && module.role == "system"
                && !module.in_app)
    });
    let symbol = if candidate_symbol.is_some() && !symbol_allowed {
        *suppressed_symbol_count += 1;
        None
    } else {
        candidate_symbol
    };
    let has_inline_symbols = symbol.is_some_and(|value| !value.inline.is_empty());
    let mut frames = vec![frame_info(
        frame,
        index,
        module_name.clone(),
        dump_module,
        relative,
        module_info,
        symbol,
        // A physical frame remains the quality/fingerprint unit.  When the
        // gateway supplied inline records, the records below carry
        // `inline=true` and this physical record stays false even if the
        // underlying rust-minidump frame also advertises inline metadata.
        if has_inline_symbols { false } else { frame.inline },
    )];

    if let Some(symbol) = symbol {
        let mut inline_symbols: Vec<&crate::symbolicator::SymbolicatedFrame> = Vec::new();
        for inline_symbol in &symbol.inline {
            let is_duplicate =
                inline_symbols.last().is_some_and(|previous| same_symbol(previous, inline_symbol));
            if !is_duplicate {
                inline_symbols.push(inline_symbol);
            }
        }
        // merge_symbol retains the last response both as the primary symbol
        // and as the last inline record.  Avoid emitting that one duplicate,
        // while retaining earlier records even when their names happen to
        // match the primary symbol.
        if inline_symbols.last().is_some_and(|value| same_symbol(value, symbol)) {
            inline_symbols.pop();
        }
        frames.extend(inline_symbols.into_iter().map(|inline_symbol| {
            frame_info(
                frame,
                index,
                module_name.clone(),
                dump_module,
                relative,
                module_info,
                Some(inline_symbol),
                true,
            )
        }));
    }
    frames
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn frame_info(
    frame: &UnwindFrame,
    index: u32,
    module: Option<String>,
    dump_module: Option<&InspectModule>,
    relative: Option<u64>,
    module_info: Option<&ModuleInfo>,
    symbol: Option<&crate::symbolicator::SymbolicatedFrame>,
    inline: bool,
) -> FrameInfo {
    let function_raw =
        symbol.and_then(|value| value.function.clone()).or_else(|| frame.function.clone());
    let function_normalized = function_raw.as_deref().map(normalize_function).or_else(|| {
        module
            .as_ref()
            .zip(relative)
            .map(|(module, offset)| format!("{}+0x{offset:x}", basename(module)))
    });
    FrameInfo {
        index,
        instruction_addr: format!("0x{:x}", frame.instruction),
        module,
        module_debug_id: dump_module
            .and_then(|value| value.debug_id.clone())
            .or_else(|| frame.module.as_ref().and_then(|value| value.debug_id.clone())),
        relative_addr: relative.map(|value| format!("0x{value:x}")),
        function: function_raw.clone(),
        function_raw,
        function_normalized,
        function_offset: relative,
        file: symbol.and_then(|value| value.file.clone()).or_else(|| frame.file.clone()),
        line: symbol.and_then(|value| value.line).or_else(|| frame.line.map(u64::from)),
        trust: frame.trust.clone(),
        in_app: module_info.map(|value| value.in_app).unwrap_or(false),
        inline,
        source_context: None,
    }
}

fn same_symbol(
    left: &crate::symbolicator::SymbolicatedFrame,
    right: &crate::symbolicator::SymbolicatedFrame,
) -> bool {
    left.function == right.function && left.file == right.file && left.line == right.line
}

fn find_symbol<'a>(
    symbols: &'a SymbolicationResult,
    module: Option<&str>,
    address: u64,
) -> Option<&'a crate::symbolicator::SymbolicatedFrame> {
    let exact_module = module.map(|value| value.to_ascii_lowercase()).unwrap_or_default();
    symbols
        .frames
        .get(&FrameKey { module: exact_module.clone(), instruction_addr: address })
        .or_else(|| {
            let short = basename(&exact_module).to_ascii_lowercase();
            symbols
                .frames
                .iter()
                .find(|(key, _)| key.instruction_addr == address && basename(&key.module) == short)
                .map(|(_, value)| value)
        })
}

fn warning_for_status(
    module: &ModuleInfo,
    symbolication: Option<&SymbolicationResult>,
    warnings: &mut Vec<QualityWarning>,
) {
    if module.status == "matched" && module.in_app {
        let final_status = symbolication.and_then(|result| {
            result.module_debug_status(
                &module.code_file,
                module.code_id.as_deref(),
                module.debug_file.as_deref(),
                module.debug_id.as_deref(),
            )
        });
        match final_status {
            Some("found" | "unused") => {}
            None if symbolication.is_none() => {}
            Some(status) => {
                warnings.push(QualityWarning {
                    code: "symbolicator_failed".to_owned(),
                    message: format!(
                        "deployment-owned application symbol source returned debug_status={status}"
                    ),
                    module: Some(module.code_file.clone()),
                    debug_id: module.debug_id.clone(),
                });
                return;
            }
            None => {
                warnings.push(QualityWarning {
                    code: "symbolicator_failed".to_owned(),
                    message: "deployment-owned application symbol source omitted module status"
                        .to_owned(),
                    module: Some(module.code_file.clone()),
                    debug_id: module.debug_id.clone(),
                });
                return;
            }
        }
    }
    if module.status == "system_symbol_pending" {
        let final_status = symbolication.and_then(|result| {
            result.module_debug_status(
                &module.code_file,
                module.code_id.as_deref(),
                module.debug_file.as_deref(),
                module.debug_id.as_deref(),
            )
        });
        match final_status {
            Some("found" | "unused") => return,
            Some(status) => {
                warnings.push(QualityWarning {
                    code: "system_symbol_failed".to_owned(),
                    message: format!(
                        "deployment-owned public symbol sources returned debug_status={status}"
                    ),
                    module: Some(module.code_file.clone()),
                    debug_id: module.debug_id.clone(),
                });
                return;
            }
            None => {}
        }
    }
    let (code, message) = match module.status.as_str() {
        "missing_pe" => ("missing_pe", "no verified PE matched this dump module"),
        "missing_pdb" => ("missing_pdb", "the verified PE has no matching PDB"),
        "pdb_mismatch" => ("pdb_mismatch", "PDB identity does not match PE or dump CodeView"),
        "pe_mismatch" => ("pe_mismatch", "PE identity does not match the dump module"),
        "system_symbol_pending" => (
            "system_symbol_pending",
            "system symbols were left to the deployment-owned Symbolicator sources",
        ),
        "corrupted" => ("other", "artifact bytes could not be parsed"),
        _ => return,
    };
    warnings.push(QualityWarning {
        code: code.to_owned(),
        message: message.to_owned(),
        module: Some(module.code_file.clone()),
        debug_id: module.debug_id.clone(),
    });
    if module.in_app && module.status == "missing_pe" {
        warnings.push(QualityWarning {
            code: "missing_pe_unwind".to_owned(),
            message: "x64 unwind cannot use verified local PE bytes".to_owned(),
            module: Some(module.code_file.clone()),
            debug_id: module.debug_id.clone(),
        });
    }
}

fn quality(
    threads: &[ThreadInfo],
    modules: &[ModuleInfo],
    warnings: &mut Vec<QualityWarning>,
) -> (f64, f64, f64) {
    let selected = threads.iter().find(|thread| thread.is_crashing).or_else(|| threads.first());
    let physical_frames = selected
        .map(|thread| thread.frames.iter().filter(|frame| !frame.inline).collect::<Vec<_>>())
        .unwrap_or_default();
    let frames = physical_frames.as_slice();
    let identifiable =
        frames.iter().filter(|frame| frame.in_app && frame.module.is_some()).collect::<Vec<_>>();
    let symbolized = identifiable
        .iter()
        .filter(|frame| frame.function.is_some() || frame.file.is_some() || frame.line.is_some())
        .count();
    let symbol_coverage = if identifiable.is_empty() {
        warnings.push(QualityWarning {
            code: "other".to_owned(),
            message: "symbol_coverage denominator is zero".to_owned(),
            module: None,
            debug_id: None,
        });
        0.0
    } else {
        symbolized as f64 / identifiable.len() as f64
    };
    let unwind_reliability = if frames.is_empty() {
        warnings.push(QualityWarning {
            code: "other".to_owned(),
            message: "unwind_reliability denominator is zero".to_owned(),
            module: None,
            debug_id: None,
        });
        0.0
    } else {
        frames
            .iter()
            .map(|frame| match frame.trust.as_str() {
                "context" | "cfi" => 1.0,
                "frame_pointer" => 0.75,
                "scan" => 0.20,
                _ => 0.0,
            })
            .sum::<f64>()
            / frames.len() as f64
    };
    if frames.iter().any(|frame| frame.trust == "scan") {
        warnings.push(QualityWarning {
            code: "scan_frames".to_owned(),
            message: "one or more frames were recovered by stack scanning".to_owned(),
            module: None,
            debug_id: None,
        });
    }
    let app_modules = modules.iter().filter(|module| module.in_app).collect::<Vec<_>>();
    let matched_modules = app_modules.iter().filter(|module| module.status == "matched").count();
    let artifact_completeness = if app_modules.is_empty() {
        warnings.push(QualityWarning {
            code: "other".to_owned(),
            message: "artifact_completeness denominator is zero".to_owned(),
            module: None,
            debug_id: None,
        });
        0.0
    } else {
        matched_modules as f64 / app_modules.len() as f64
    };
    (symbol_coverage, unwind_reliability, artifact_completeness)
}

fn exact_fingerprint(
    workspace: &str,
    crash_type: &str,
    exception: Option<&crate::minidump::InspectException>,
    crash_thread_id: Option<u32>,
    modules: &[ModuleInfo],
    threads: &[ThreadInfo],
) -> Option<String> {
    if crash_type != "crash" || exception.is_none() || crash_thread_id.is_none() {
        return None;
    }
    let exception = exception?;
    let fault_module = module_for_address_from_modules(modules, &exception.address)?;
    if fault_module.status != "matched" || fault_module.debug_id.is_none() {
        return None;
    }
    let thread = threads.iter().find(|thread| Some(thread.id) == crash_thread_id)?;
    let physical_frames = thread.frames.iter().filter(|frame| !frame.inline).collect::<Vec<_>>();
    let mut seen = std::collections::BTreeSet::new();
    let selected = physical_frames
        .iter()
        .enumerate()
        .filter(|(index, frame)| {
            if !frame.in_app || deny_frame(frame) || frame.trust == "unknown" {
                return false;
            }
            if frame.trust == "scan" {
                let previous = index.checked_sub(1).and_then(|value| physical_frames.get(value));
                let next = physical_frames.get(*index + 1);
                if ![previous, next]
                    .into_iter()
                    .flatten()
                    .any(|adjacent| matches!(adjacent.trust.as_str(), "context" | "cfi"))
                {
                    return false;
                }
            }
            seen.insert(frame.instruction_addr.clone())
        })
        .map(|(_, frame)| frame)
        .take(5)
        .collect::<Vec<_>>();
    if selected.is_empty() || !selected.iter().any(|frame| frame.trust != "scan") {
        return None;
    }
    let tokens = selected
        .iter()
        .map(|frame| {
            let debug_id = frame.module_debug_id.as_deref()?;
            let relative = frame.relative_addr.as_deref()?.strip_prefix("0x")?;
            let relative = u64::from_str_radix(relative, 16).ok()? & !0xf;
            Some(format!("{debug_id}\n{}\n0x{relative:x}", frame.function_normalized.as_deref()?))
        })
        .collect::<Option<Vec<_>>>()?;
    let payload = format!(
        "{workspace}\n{}\n{}\n{}\n{}",
        exception.code,
        exception.access_type.as_deref().unwrap_or("-"),
        fault_module.debug_id.as_deref()?,
        tokens.join("\n")
    );
    Some(sha256_hex(payload.as_bytes()))
}

fn deny_frame(frame: &FrameInfo) -> bool {
    let Some(module) = &frame.module else {
        return false;
    };
    [
        "ntdll.dll",
        "kernel32.dll",
        "kernelbase.dll",
        "user32.dll",
        "gdi32.dll",
        "ucrtbase.dll",
        "vcruntime140.dll",
        "vcruntime140_1.dll",
        "msvcp140.dll",
        "msvcrt.dll",
        "advapi32.dll",
        "sechost.dll",
        "rpcrt4.dll",
        "ole32.dll",
        "combase.dll",
        "ws2_32.dll",
        "bcryptprimitives.dll",
        "win32u.dll",
    ]
    .iter()
    .any(|name| basename(module).eq_ignore_ascii_case(name))
}

fn module_for_address_from_modules<'a>(
    modules: &'a [ModuleInfo],
    address: &str,
) -> Option<&'a ModuleInfo> {
    let address = parse_hex(address)?;
    modules.iter().find(|module| {
        let Some(base) = module.image_base.as_deref().and_then(parse_hex) else {
            return false;
        };
        let Some(size) = module.image_size else {
            return false;
        };
        address >= base && address < base.saturating_add(size)
    })
}

fn build_resolution(evidence: BuildResolutionEvidence) -> BuildResolution {
    BuildResolution {
        reported_build_id: evidence.reported_build_id,
        resolved_build_id: evidence.resolved_build_id,
        resolution_method: evidence.resolution_method,
        evidence: BuildEvidence {
            candidate_build_ids: evidence.candidate_build_ids,
            matched_entrypoints: evidence.matched_entrypoints,
            matched_owned_modules: evidence.matched_owned_modules,
            conflicting_modules: evidence.conflicting_modules,
            note: evidence.note,
        },
    }
}

fn default_build_resolution() -> BuildResolution {
    BuildResolution {
        reported_build_id: None,
        resolved_build_id: None,
        resolution_method: "unresolved".to_owned(),
        evidence: BuildEvidence {
            candidate_build_ids: Vec::new(),
            matched_entrypoints: Vec::new(),
            matched_owned_modules: Vec::new(),
            conflicting_modules: Vec::new(),
            note: Some("artifact matching was not supplied to this analysis".to_owned()),
        },
    }
}

fn normalize_function(function: &str) -> String {
    let mut result = function.trim().to_owned();
    if let Some(index) = result.find('(') {
        result.truncate(index);
    }
    if let Some(index) = result.find("::<lambda_") {
        result.truncate(index);
    }
    result
}

fn basename(value: &str) -> &str {
    value.rsplit(['/', '\\']).next().unwrap_or(value)
}

fn infer_role_for_canonical(code_file: &str) -> String {
    let lower = code_file.to_ascii_lowercase();
    if lower.ends_with(".exe") {
        "entrypoint".to_owned()
    } else if lower.contains("\\windows\\system32\\driverstore\\")
        || lower.contains("/windows/system32/driverstore/")
    {
        // DriverStore contains vendor-owned display/audio/network modules.
        // A Windows path alone does not make their symbols Microsoft-owned.
        "dependency".to_owned()
    } else if deny_frame(&FrameInfo {
        index: 0,
        instruction_addr: "0x0".to_owned(),
        module: Some(code_file.to_owned()),
        module_debug_id: None,
        relative_addr: None,
        function: None,
        function_raw: None,
        function_normalized: None,
        function_offset: None,
        file: None,
        line: None,
        trust: "unknown".to_owned(),
        in_app: false,
        inline: false,
        source_context: None,
    }) {
        "system".to_owned()
    } else {
        "unknown".to_owned()
    }
}

fn module_for_instruction(report: &InspectReport, address: u64) -> Option<&InspectModule> {
    report.modules.iter().find(|module| {
        parse_hex(&module.image_base).is_some_and(|base| {
            address >= base && address < base.saturating_add(module.image_size as u64)
        })
    })
}

fn parse_hex(value: &str) -> Option<u64> {
    u64::from_str_radix(value.trim().trim_start_matches("0x").trim_start_matches("0X"), 16).ok()
}

fn lower_hex(value: &str) -> String {
    parse_hex(value)
        .map(|number| format!("0x{number:x}"))
        .unwrap_or_else(|| value.to_ascii_lowercase())
}

fn module_for_address<'a>(report: &'a InspectReport, address: &str) -> Option<&'a InspectModule> {
    let address = address.strip_prefix("0x")?;
    let address = u64::from_str_radix(address, 16).ok()?;
    report.modules.iter().find(|module| {
        let Some(base) = module.image_base.strip_prefix("0x") else {
            return false;
        };
        let Ok(base) = u64::from_str_radix(base, 16) else {
            return false;
        };
        let end = base.saturating_add(module.image_size as u64);
        address >= base && address < end
    })
}

fn warning_code(code: &str) -> String {
    match code {
        "missing_thread_list" | "missing_module_list" => "other".to_owned(),
        "missing_exception_stream" => "unknown_crash_type".to_owned(),
        value => value.to_owned(),
    }
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    hex::encode(digest)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::artifact::{
        match_artifacts, BuildResolutionEvidence, MatchInput, MatchReport, MatchedModule,
    };
    use crate::minidump::{
        InspectDump, InspectException, InspectModule, InspectProcess, InspectReport, InspectThread,
    };
    use crate::symbolicator::{SymbolicatedModule, SymbolicationResult};
    use crate::unwind::{UnwindFrame, UnwindModule, UnwindReport, UnwindThread};
    use serde_json::Value;
    use std::collections::BTreeMap;

    fn report() -> InspectReport {
        InspectReport {
            schema_version: "0.1".to_owned(),
            dump: InspectDump {
                kind: "user_minidump".to_owned(),
                size: 32,
                signature: "MDMP".to_owned(),
                number_of_streams: 1,
                flags: "0x0".to_owned(),
                timestamp: None,
            },
            process: InspectProcess {
                pid: None,
                architecture: "x86_64".to_owned(),
                os: "windows".to_owned(),
                os_version: Some("10.0.22631".to_owned()),
                platform_id: Some(2),
                build_number: Some(22631),
                processor_count: Some(1),
            },
            exception: Some(InspectException {
                thread_id: 7,
                code: "0xc0000005".to_owned(),
                name: Some("EXCEPTION_ACCESS_VIOLATION".to_owned()),
                flags: "0x00000000".to_owned(),
                address: "0x140001000".to_owned(),
                fault_address: Some("0x0".to_owned()),
                access_type: Some("read".to_owned()),
                parameters: vec!["0x0".to_owned()],
                context: None,
            }),
            crash_thread_id: Some(7),
            threads: vec![InspectThread {
                id: 7,
                teb: "0x0".to_owned(),
                stack_start: "0x0".to_owned(),
                stack_size: 0,
                context: None,
            }],
            modules: Vec::new(),
            warnings: Vec::new(),
        }
    }

    #[test]
    fn canonical_result_has_all_contract_sections() {
        let result = CanonicalAnalysisResult::from_inspect(
            &report(),
            &[1, 2, 3],
            "wsp_test",
            "occ_test",
            "run_test",
        );
        let value = serde_json::to_value(&result).expect("canonical serializes");
        for key in [
            "schema_version",
            "workspace_id",
            "occurrence_id",
            "analysis_id",
            "engine",
            "build_resolution",
            "dump",
            "process",
            "crash",
            "threads",
            "modules",
            "quality",
            "fingerprints",
        ] {
            assert!(value.get(key).is_some(), "missing {key}");
        }
        assert_eq!(value["crash"]["address"], "0x140001000");
        assert_eq!(value["fingerprints"]["exact"], Value::Null);
    }

    #[test]
    fn crash_hang_and_unknown_classification_requires_hang_intent() {
        let mut no_exception = report();
        no_exception.exception = None;
        no_exception.crash_thread_id = None;
        no_exception.threads.clear();

        let unknown = CanonicalAnalysisResult::from_evidence(
            &no_exception,
            b"unknown",
            CanonicalInputs {
                workspace_id: "wsp_test".to_owned(),
                occurrence_id: "occ_unknown".to_owned(),
                analysis_id: "run_unknown".to_owned(),
                symbolicator_version: "unavailable".to_owned(),
                ..Default::default()
            },
        );
        assert_eq!(unknown.crash.r#type, "unknown");

        let hang = CanonicalAnalysisResult::from_evidence(
            &no_exception,
            b"hang",
            CanonicalInputs {
                workspace_id: "wsp_test".to_owned(),
                occurrence_id: "occ_hang".to_owned(),
                analysis_id: "run_hang".to_owned(),
                capture_profile: Some("hang".to_owned()),
                symbolicator_version: "unavailable".to_owned(),
                ..Default::default()
            },
        );
        assert_eq!(hang.crash.r#type, "hang");
        assert_eq!(hang.crash.type_evidence, "reported_hang");
    }

    #[test]
    fn inferred_entrypoint_without_artifact_emits_missing_pe_unwind() {
        let mut report = report();
        report.modules.push(InspectModule {
            code_file: "app.exe".to_owned(),
            code_id: "CODE".to_owned(),
            debug_file: Some("app.pdb".to_owned()),
            debug_id: Some("DEBUG".to_owned()),
            image_base: "0x140000000".to_owned(),
            image_size: 0x2000,
            time_date_stamp: "0x0".to_owned(),
            checksum: "0x0".to_owned(),
        });
        let result = CanonicalAnalysisResult::from_inspect(
            &report,
            b"missing pe",
            "wsp_test",
            "occ_missing_pe",
            "run_missing_pe",
        );
        assert!(result.modules[0].in_app);
        assert!(result.quality.warnings.iter().any(|warning| {
            warning.code == "missing_pe_unwind" && warning.module.as_deref() == Some("app.exe")
        }));
    }

    #[test]
    fn terminal_public_symbol_status_reconciles_pending_artifact_status() {
        let mut report = report();
        report.modules.push(InspectModule {
            code_file: r"C:\Windows\System32\ntdll.dll".to_owned(),
            code_id: "CODE".to_owned(),
            debug_file: Some("ntdll.pdb".to_owned()),
            debug_id: Some("23E72AA7-E387-3AC7-9882-BF6E394DA71E-1".to_owned()),
            image_base: "0x180000000".to_owned(),
            image_size: 0x2000,
            time_date_stamp: "0x0".to_owned(),
            checksum: "0x0".to_owned(),
        });
        let match_report = match_artifacts(&report, &MatchInput::default()).expect("match report");

        let analyze = |debug_status: &str| {
            CanonicalAnalysisResult::from_evidence(
                &report,
                b"public symbols",
                CanonicalInputs {
                    workspace_id: "wsp_test".to_owned(),
                    occurrence_id: "occ_public".to_owned(),
                    analysis_id: format!("run_{debug_status}"),
                    match_report: Some(match_report.clone()),
                    symbolication: Some(SymbolicationResult {
                        modules: vec![SymbolicatedModule {
                            code_file: Some(r"C:\Windows\System32\ntdll.dll".to_owned()),
                            code_id: Some("CODE".to_owned()),
                            debug_file: Some("ntdll.pdb".to_owned()),
                            debug_id: Some("23e72aa7-e387-3ac7-9882-bf6e394da71e-1".to_owned()),
                            debug_status: debug_status.to_owned(),
                        }],
                        ..Default::default()
                    }),
                    symbolicator_version: "test".to_owned(),
                    ..Default::default()
                },
            )
        };

        for status in ["found", "unused"] {
            let result = analyze(status);
            assert!(!result
                .quality
                .warnings
                .iter()
                .any(|warning| warning.code.starts_with("system_symbol_")));
        }

        let missing = analyze("missing");
        let warning = missing
            .quality
            .warnings
            .iter()
            .find(|warning| warning.code == "system_symbol_failed")
            .expect("terminal failure warning");
        assert_eq!(warning.module.as_deref(), Some(r"C:\Windows\System32\ntdll.dll"));
        assert!(warning.message.contains("debug_status=missing"));
    }

    #[test]
    fn matched_application_symbol_failure_is_explicit_and_blocking() {
        let module = ModuleInfo {
            code_file: "app.exe".to_owned(),
            code_id: Some("CODE".to_owned()),
            debug_file: Some("app.pdb".to_owned()),
            debug_id: Some("23E72AA7-E387-3AC7-9882-BF6E394DA71E-1".to_owned()),
            image_base: Some("0x140000000".to_owned()),
            image_size: Some(0x2000),
            role: "entrypoint".to_owned(),
            in_app: true,
            artifact_ids: vec!["art_app".to_owned()],
            status: "matched".to_owned(),
        };
        let symbolication = SymbolicationResult {
            modules: vec![SymbolicatedModule {
                code_file: Some("app.exe".to_owned()),
                code_id: Some("CODE".to_owned()),
                debug_file: Some("app.pdb".to_owned()),
                debug_id: Some("23e72aa7-e387-3ac7-9882-bf6e394da71e-1".to_owned()),
                debug_status: "missing".to_owned(),
            }],
            ..Default::default()
        };
        let mut warnings = Vec::new();

        warning_for_status(&module, Some(&symbolication), &mut warnings);

        assert_eq!(warnings.len(), 1);
        assert_eq!(warnings[0].code, "symbolicator_failed");
        assert_eq!(warnings[0].module.as_deref(), Some("app.exe"));
        assert!(warnings[0].message.contains("debug_status=missing"));
    }

    #[test]
    fn rejected_symbolicator_frames_are_visible_as_a_count_only_warning() {
        let result = CanonicalAnalysisResult::from_evidence(
            &report(),
            b"provenance",
            CanonicalInputs {
                workspace_id: "wsp_test".to_owned(),
                occurrence_id: "occ_rejected".to_owned(),
                analysis_id: "run_rejected".to_owned(),
                symbolication: Some(SymbolicationResult {
                    rejected_frames: 3,
                    ..Default::default()
                }),
                symbolicator_version: "test".to_owned(),
                ..Default::default()
            },
        );
        let warning = result
            .quality
            .warnings
            .iter()
            .find(|warning| {
                warning.code == "other"
                    && warning.message.contains("Symbolicator frame provenance rejected count")
            })
            .expect("rejected-frame warning");
        assert_eq!(warning.module, None);
        assert_eq!(warning.debug_id, None);
        assert_eq!(warning.message, "Symbolicator frame provenance rejected count: 3");
    }

    #[test]
    fn symbolicator_result_is_ignored_for_non_matched_business_module() {
        let mut report = report();
        report.modules.push(InspectModule {
            code_file: "app.exe".to_owned(),
            code_id: "CODE".to_owned(),
            debug_file: Some("app.pdb".to_owned()),
            debug_id: Some("DUMP_DEBUG".to_owned()),
            image_base: "0x140000000".to_owned(),
            image_size: 0x2000,
            time_date_stamp: "0x0".to_owned(),
            checksum: "0x0".to_owned(),
        });
        let mut symbols = BTreeMap::new();
        symbols.insert(
            FrameKey { module: "app.exe".to_owned(), instruction_addr: 0x140001000 },
            crate::symbolicator::SymbolicatedFrame {
                function: Some("wrong::pdb_symbol".to_owned()),
                ..Default::default()
            },
        );
        let result = CanonicalAnalysisResult::from_evidence(
            &report,
            b"pdb-mismatch",
            CanonicalInputs {
                workspace_id: "wsp_test".to_owned(),
                occurrence_id: "occ_pdb_mismatch".to_owned(),
                analysis_id: "run_pdb_mismatch".to_owned(),
                match_report: Some(MatchReport {
                    workspace_id: Some("wsp_test".to_owned()),
                    modules: vec![MatchedModule {
                        code_file: "app.exe".to_owned(),
                        code_id: Some("CODE".to_owned()),
                        debug_file: Some("other.pdb".to_owned()),
                        debug_id: Some("OTHER_DEBUG".to_owned()),
                        role: "entrypoint".to_owned(),
                        in_app: true,
                        artifact_ids: Vec::new(),
                        status: "pdb_mismatch".to_owned(),
                        candidate_build_ids: Vec::new(),
                    }],
                    build_resolution: BuildResolutionEvidence {
                        reported_build_id: None,
                        resolved_build_id: None,
                        resolution_method: "unresolved".to_owned(),
                        candidate_build_ids: Vec::new(),
                        matched_entrypoints: Vec::new(),
                        matched_owned_modules: Vec::new(),
                        conflicting_modules: Vec::new(),
                        note: None,
                    },
                }),
                unwind: Some(UnwindReport {
                    threads: vec![UnwindThread {
                        id: 7,
                        frames: vec![UnwindFrame {
                            unwind_method: None,
                            instruction: 0x140001000,
                            resume_address: 0x140001000,
                            module: Some(UnwindModule {
                                code_file: "app.exe".to_owned(),
                                code_id: Some("CODE".to_owned()),
                                debug_file: Some("app.pdb".to_owned()),
                                debug_id: Some("DUMP_DEBUG".to_owned()),
                                image_base: 0x140000000,
                                image_size: 0x2000,
                            }),
                            function: None,
                            file: None,
                            line: None,
                            trust: "context".to_owned(),
                            inline: false,
                        }],
                    }],
                }),
                symbolication: Some(SymbolicationResult { frames: symbols, ..Default::default() }),
                symbolicator_version: "test".to_owned(),
                ..Default::default()
            },
        );
        let frame = &result.threads[0].frames[0];
        assert_eq!(frame.function, None, "pdb mismatch must not consume symbol response");
        assert!(result.quality.warnings.iter().any(|warning| {
            warning.code == "other"
                && warning.message.contains("Symbolicator symbol ignored count: 1")
        }));
    }

    #[test]
    fn inline_symbolication_expands_without_double_counting_quality_or_exact() {
        let mut report = report();
        report.modules.push(InspectModule {
            code_file: "app.exe".to_owned(),
            code_id: "CODE".to_owned(),
            debug_file: Some("app.pdb".to_owned()),
            debug_id: Some("DEBUG".to_owned()),
            image_base: "0x140000000".to_owned(),
            image_size: 0x2000,
            time_date_stamp: "0x0".to_owned(),
            checksum: "0x0".to_owned(),
        });
        let mut symbols = BTreeMap::new();
        symbols.insert(
            FrameKey { module: "app.exe".to_owned(), instruction_addr: 0x140001000 },
            crate::symbolicator::SymbolicatedFrame {
                function: Some("crashcap::trigger_release_inline()".to_owned()),
                inline: vec![
                    crate::symbolicator::SymbolicatedFrame {
                        function: Some("crashcap::release_inline_leaf()".to_owned()),
                        ..Default::default()
                    },
                    crate::symbolicator::SymbolicatedFrame {
                        function: Some("crashcap::release_inline_middle()".to_owned()),
                        ..Default::default()
                    },
                    crate::symbolicator::SymbolicatedFrame {
                        function: Some("crashcap::trigger_release_inline()".to_owned()),
                        ..Default::default()
                    },
                ],
                ..Default::default()
            },
        );
        let result = CanonicalAnalysisResult::from_evidence(
            &report,
            b"inline",
            CanonicalInputs {
                workspace_id: "wsp_test".to_owned(),
                occurrence_id: "occ_inline".to_owned(),
                analysis_id: "run_inline".to_owned(),
                match_report: Some(MatchReport {
                    workspace_id: Some("wsp_test".to_owned()),
                    modules: vec![MatchedModule {
                        code_file: "app.exe".to_owned(),
                        code_id: Some("CODE".to_owned()),
                        debug_file: Some("app.pdb".to_owned()),
                        debug_id: Some("DEBUG".to_owned()),
                        role: "entrypoint".to_owned(),
                        in_app: true,
                        artifact_ids: vec!["art_app".to_owned()],
                        status: "matched".to_owned(),
                        candidate_build_ids: Vec::new(),
                    }],
                    build_resolution: BuildResolutionEvidence {
                        reported_build_id: None,
                        resolved_build_id: Some("build".to_owned()),
                        resolution_method: "exact".to_owned(),
                        candidate_build_ids: vec!["build".to_owned()],
                        matched_entrypoints: vec!["app.exe".to_owned()],
                        matched_owned_modules: Vec::new(),
                        conflicting_modules: Vec::new(),
                        note: None,
                    },
                }),
                unwind: Some(UnwindReport {
                    threads: vec![UnwindThread {
                        id: 7,
                        frames: vec![UnwindFrame {
                            unwind_method: None,
                            instruction: 0x140001000,
                            resume_address: 0x140001000,
                            module: Some(UnwindModule {
                                code_file: "app.exe".to_owned(),
                                code_id: Some("CODE".to_owned()),
                                debug_file: Some("app.pdb".to_owned()),
                                debug_id: Some("DEBUG".to_owned()),
                                image_base: 0x140000000,
                                image_size: 0x2000,
                            }),
                            function: None,
                            file: None,
                            line: None,
                            trust: "context".to_owned(),
                            inline: true,
                        }],
                    }],
                }),
                symbolication: Some(SymbolicationResult { frames: symbols, ..Default::default() }),
                symbolicator_version: "test".to_owned(),
                ..Default::default()
            },
        );
        let frames = &result.threads[0].frames;
        assert_eq!(frames.len(), 3, "physical frame plus two non-duplicate inline records");
        assert_eq!(frames.iter().map(|frame| frame.index).collect::<Vec<_>>(), vec![0, 0, 0]);
        assert_eq!(frames[0].function.as_deref(), Some("crashcap::trigger_release_inline()"));
        assert!(!frames[0].inline, "the physical frame remains the quality unit");
        assert_eq!(frames[1].function.as_deref(), Some("crashcap::release_inline_leaf()"));
        assert_eq!(frames[2].function.as_deref(), Some("crashcap::release_inline_middle()"));
        assert!(frames[1..].iter().all(|frame| frame.inline));
        assert_eq!(result.quality.symbol_coverage, 1.0);
        assert!(result.fingerprints.exact.is_some());
    }

    #[test]
    fn exact_requires_a_non_scan_in_app_frame() {
        let module = ModuleInfo {
            code_file: "app.exe".to_owned(),
            code_id: Some("CODE".to_owned()),
            debug_file: Some("app.pdb".to_owned()),
            debug_id: Some("DEBUG".to_owned()),
            image_base: Some("0x140000000".to_owned()),
            image_size: Some(0x2000),
            role: "entrypoint".to_owned(),
            in_app: true,
            artifact_ids: vec!["art_app".to_owned()],
            status: "matched".to_owned(),
        };
        let frame = FrameInfo {
            index: 0,
            instruction_addr: "0x140001000".to_owned(),
            module: Some("app.exe".to_owned()),
            module_debug_id: Some("DEBUG".to_owned()),
            relative_addr: Some("0x1000".to_owned()),
            function: Some("app::crash()".to_owned()),
            function_raw: Some("app::crash()".to_owned()),
            function_normalized: Some("app::crash".to_owned()),
            function_offset: Some(0x1000),
            file: None,
            line: None,
            trust: "context".to_owned(),
            in_app: true,
            inline: false,
            source_context: None,
        };
        let thread =
            ThreadInfo { id: 7, name: None, is_crashing: true, frames: vec![frame.clone()] };
        let report = report();
        let positive = exact_fingerprint(
            "wsp_test",
            "crash",
            report.exception.as_ref(),
            report.crash_thread_id,
            &[module],
            std::slice::from_ref(&thread),
        );
        assert!(positive.is_some());

        let mut scan_thread = thread;
        scan_thread.frames[0].trust = "scan".to_owned();
        let scan_only = exact_fingerprint(
            "wsp_test",
            "crash",
            report.exception.as_ref(),
            report.crash_thread_id,
            &[ModuleInfo {
                code_file: "app.exe".to_owned(),
                code_id: Some("CODE".to_owned()),
                debug_file: Some("app.pdb".to_owned()),
                debug_id: Some("DEBUG".to_owned()),
                image_base: Some("0x140000000".to_owned()),
                image_size: Some(0x2000),
                role: "entrypoint".to_owned(),
                in_app: true,
                artifact_ids: vec!["art_app".to_owned()],
                status: "matched".to_owned(),
            }],
            &[scan_thread],
        );
        assert!(scan_only.is_none());
    }

    #[test]
    fn function_normalization_removes_signature_but_keeps_namespace() {
        assert_eq!(normalize_function("app::crash(int, void*)"), "app::crash");
        assert_eq!(normalize_function("app::<lambda_42>()"), "app");
    }

    #[test]
    fn sha256_is_lowercase_fixed_width() {
        assert_eq!(
            sha256_hex(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }
}
