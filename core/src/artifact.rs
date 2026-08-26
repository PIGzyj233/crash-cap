//! Artifact identity verification and minimal Workspace Build resolution.
//!
//! A filename is deliberately never used as a matching key.  PE identities
//! are derived from `TimeDateStamp + SizeOfImage`; PDB identities are read from
//! the PDB information stream and compared with the dump's CodeView RSDS ID.
//! The input is intentionally small and additive so a Worker can later pass a
//! richer immutable match spec without changing the core's matching rules.

use crate::minidump::{InspectModule, InspectReport};
pub use crashcap_artifact_identity::{
    format_rsds_debug_id, identify_artifact, ArtifactError, ArtifactIdentityReport, MAX_PDB_BYTES,
    MAX_PE_BYTES,
};
use crashcap_artifact_identity::{identify_pdb, identify_pe};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::path::PathBuf;

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
#[serde(default)]
pub struct MatchInput {
    pub workspace_id: Option<String>,
    pub reported_build_id: Option<String>,
    pub manual_build_id: Option<String>,
    pub modules: Vec<ArtifactSpec>,
    pub artifacts: Vec<ArtifactSpec>,
    pub builds: Vec<BuildSpec>,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
#[serde(default)]
pub struct ArtifactSpec {
    pub artifact_id: Option<String>,
    pub code_file: Option<String>,
    pub debug_file: Option<String>,
    pub pe_path: Option<PathBuf>,
    pub pdb_path: Option<PathBuf>,
    /// `path` is accepted as a convenient PE path alias in local match specs.
    pub path: Option<PathBuf>,
    pub code_id: Option<String>,
    pub debug_id: Option<String>,
    pub role: Option<String>,
    pub in_app: Option<bool>,
    pub build_id: Option<String>,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
#[serde(default)]
pub struct BuildSpec {
    pub build_id: String,
    pub modules: Vec<BuildModuleSpec>,
}

#[derive(Debug, Clone, Default, Deserialize, Serialize)]
#[serde(default)]
pub struct BuildModuleSpec {
    pub code_id: Option<String>,
    pub debug_id: Option<String>,
    pub role: Option<String>,
    pub code_file: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MatchReport {
    pub workspace_id: Option<String>,
    pub modules: Vec<MatchedModule>,
    pub build_resolution: BuildResolutionEvidence,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct MatchedModule {
    pub code_file: String,
    pub code_id: Option<String>,
    pub debug_file: Option<String>,
    pub debug_id: Option<String>,
    pub role: String,
    pub in_app: bool,
    pub artifact_ids: Vec<String>,
    pub status: String,
    pub candidate_build_ids: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BuildResolutionEvidence {
    pub reported_build_id: Option<String>,
    pub resolved_build_id: Option<String>,
    pub resolution_method: String,
    pub candidate_build_ids: Vec<String>,
    pub matched_entrypoints: Vec<String>,
    pub matched_owned_modules: Vec<String>,
    pub conflicting_modules: Vec<String>,
    pub note: Option<String>,
}

/// Match every module in an inspect report using exact identities.
pub fn match_artifacts(
    report: &InspectReport,
    input: &MatchInput,
) -> Result<MatchReport, ArtifactError> {
    let mut specs = input.modules.clone();
    specs.extend(input.artifacts.clone());
    let mut modules = Vec::with_capacity(report.modules.len());

    for dump_module in &report.modules {
        let role = specs
            .iter()
            .find(|spec| identity_matches(dump_module, spec))
            .and_then(|spec| spec.role.clone())
            .unwrap_or_else(|| infer_role(&dump_module.code_file).to_owned());
        let in_app = specs
            .iter()
            .find(|spec| identity_matches(dump_module, spec))
            .and_then(|spec| spec.in_app)
            .unwrap_or(matches!(role.as_str(), "entrypoint" | "owned"));

        let candidates =
            specs.iter().filter(|spec| identity_matches(dump_module, spec)).collect::<Vec<_>>();
        let mut artifact_ids = Vec::new();
        let status = if candidates.is_empty() {
            if role == "system" {
                "system_symbol_pending".to_owned()
            } else {
                "missing_pe".to_owned()
            }
        } else {
            let mut statuses = Vec::new();
            for spec in candidates {
                let result = verify_candidate(dump_module, spec)?;
                statuses.push(result.status);
                artifact_ids.extend(result.artifact_ids);
            }
            select_status(&statuses)
        };

        artifact_ids.sort();
        artifact_ids.dedup();
        let candidate_build_ids = input
            .builds
            .iter()
            .filter(|build| {
                build.modules.iter().any(|module| {
                    module_matches_dump(module, dump_module)
                        && module.role.as_deref() == Some(role.as_str())
                })
            })
            .map(|build| build.build_id.clone())
            .collect::<Vec<_>>();

        modules.push(MatchedModule {
            code_file: dump_module.code_file.clone(),
            code_id: Some(dump_module.code_id.clone()),
            debug_file: dump_module.debug_file.clone(),
            debug_id: dump_module.debug_id.clone(),
            role,
            in_app,
            artifact_ids,
            status,
            candidate_build_ids,
        });
    }

    let build_resolution = resolve_build(&modules, input);
    Ok(MatchReport { workspace_id: input.workspace_id.clone(), modules, build_resolution })
}

/// Return only PE paths that are attached to an exact dump identity.  This is
/// intentionally separate from the report so unwind cannot accidentally use a
/// file that merely shares a basename.
pub fn module_paths_for_unwind(
    report: &InspectReport,
    input: &MatchInput,
) -> BTreeMap<String, PathBuf> {
    let mut specs = input.modules.clone();
    specs.extend(input.artifacts.clone());
    report
        .modules
        .iter()
        .filter_map(|module| {
            let path = specs
                .iter()
                .find(|spec| identity_matches(module, spec))
                .and_then(|spec| spec.pe_path.clone().or_else(|| spec.path.clone()))?;
            let pe = identify_pe(&path).ok()?;
            if pe.code_id.eq_ignore_ascii_case(&module.code_id) {
                Some((module.code_id.clone(), path))
            } else {
                None
            }
        })
        .collect()
}

fn identity_matches(module: &InspectModule, spec: &ArtifactSpec) -> bool {
    let code = spec.code_id.as_ref().map(|id| id.eq_ignore_ascii_case(&module.code_id));
    let debug = spec.debug_id.as_ref().is_some_and(|expected| {
        module.debug_id.as_ref().is_some_and(|actual| expected.eq_ignore_ascii_case(actual))
    });
    code.unwrap_or(false) || debug
}

fn module_matches_dump(module: &BuildModuleSpec, dump: &InspectModule) -> bool {
    module.code_id.as_ref().is_some_and(|id| id.eq_ignore_ascii_case(&dump.code_id))
        || module.debug_id.as_ref().is_some_and(|id| {
            dump.debug_id.as_ref().is_some_and(|actual| id.eq_ignore_ascii_case(actual))
        })
}

fn infer_role(code_file: &str) -> &'static str {
    let lower = code_file.to_ascii_lowercase();
    if lower.ends_with(".exe") {
        "entrypoint"
    } else if lower.contains("\\windows\\system32\\driverstore\\")
        || lower.contains("/windows/system32/driverstore/")
    {
        "dependency"
    } else if lower.contains("\\windows\\")
        || lower.contains("/windows/")
        || [
            "ntdll.dll",
            "kernel32.dll",
            "kernelbase.dll",
            "user32.dll",
            "ucrtbase.dll",
            "msvcp140.dll",
        ]
        .iter()
        .any(|name| lower.ends_with(name))
    {
        "system"
    } else {
        "unknown"
    }
}

struct CandidateVerification {
    status: String,
    artifact_ids: Vec<String>,
}

fn verify_candidate(
    module: &InspectModule,
    spec: &ArtifactSpec,
) -> Result<CandidateVerification, ArtifactError> {
    let pe_path = spec.pe_path.clone().or_else(|| spec.path.clone());
    let pdb_path = spec.pdb_path.clone();
    let Some(pe_path) = pe_path else {
        return Ok(CandidateVerification {
            status: "missing_pe".to_owned(),
            artifact_ids: Vec::new(),
        });
    };
    let pe = match identify_pe(&pe_path) {
        Ok(pe) => pe,
        Err(ArtifactError::MissingPath(_)) => {
            return Ok(CandidateVerification {
                status: "missing_pe".to_owned(),
                artifact_ids: Vec::new(),
            })
        }
        Err(ArtifactError::Pe(_) | ArtifactError::TooLarge { .. }) => {
            return Ok(CandidateVerification {
                status: "corrupted".to_owned(),
                artifact_ids: Vec::new(),
            })
        }
        Err(error) => return Err(error),
    };
    if !pe.code_id.eq_ignore_ascii_case(&module.code_id) {
        return Ok(CandidateVerification {
            status: "pe_mismatch".to_owned(),
            artifact_ids: vec![format!("sha256:{}", pe.sha256)],
        });
    }
    let mut ids = vec![format!("sha256:{}", pe.sha256)];
    if let Some(artifact_id) = &spec.artifact_id {
        ids.push(artifact_id.clone());
    }
    let Some(pdb_path) = pdb_path else {
        return Ok(CandidateVerification { status: "missing_pdb".to_owned(), artifact_ids: ids });
    };
    let pdb = match identify_pdb(&pdb_path) {
        Ok(pdb) => pdb,
        Err(ArtifactError::MissingPath(_)) => {
            return Ok(CandidateVerification {
                status: "missing_pdb".to_owned(),
                artifact_ids: ids,
            })
        }
        Err(ArtifactError::Pdb(_) | ArtifactError::TooLarge { .. }) => {
            return Ok(CandidateVerification { status: "corrupted".to_owned(), artifact_ids: ids })
        }
        Err(error) => return Err(error),
    };
    ids.push(format!("sha256:{}", pdb.sha256));
    if module.debug_id.as_ref().is_some_and(|id| !id.eq_ignore_ascii_case(&pdb.debug_id)) {
        return Ok(CandidateVerification { status: "pdb_mismatch".to_owned(), artifact_ids: ids });
    }
    if pe.debug_id.as_ref().is_some_and(|id| !id.eq_ignore_ascii_case(&pdb.debug_id)) {
        return Ok(CandidateVerification { status: "pdb_mismatch".to_owned(), artifact_ids: ids });
    }
    Ok(CandidateVerification { status: "matched".to_owned(), artifact_ids: ids })
}

fn select_status(statuses: &[String]) -> String {
    for wanted in
        ["matched", "pdb_mismatch", "pe_mismatch", "corrupted", "missing_pdb", "missing_pe"]
    {
        if statuses.iter().any(|status| status == wanted) {
            return wanted.to_owned();
        }
    }
    "unsupported".to_owned()
}

fn resolve_build(modules: &[MatchedModule], input: &MatchInput) -> BuildResolutionEvidence {
    let mut candidate_build_ids = BTreeSet::new();
    let mut matched_entrypoints = BTreeSet::new();
    let mut matched_owned = BTreeSet::new();
    let mut conflicting = BTreeSet::new();
    let mut satisfying = Vec::new();

    for build in &input.builds {
        let mut entrypoints = Vec::new();
        let mut owned = Vec::new();
        let mut conflicts = Vec::new();
        for module in modules {
            let matches = build
                .modules
                .iter()
                .filter(|spec| {
                    (spec.code_id.as_ref().is_some_and(|id| {
                        module
                            .code_id
                            .as_ref()
                            .is_some_and(|actual| id.eq_ignore_ascii_case(actual))
                    })) || (spec.debug_id.as_ref().is_some_and(|id| {
                        module
                            .debug_id
                            .as_ref()
                            .is_some_and(|actual| id.eq_ignore_ascii_case(actual))
                    }))
                })
                .collect::<Vec<_>>();
            match module.role.as_str() {
                "entrypoint" if !matches.is_empty() => entrypoints.push(module.code_file.clone()),
                "owned" if !matches.is_empty() => owned.push(module.code_file.clone()),
                "owned" if matches.is_empty() && module.in_app => {
                    conflicts.push(module.code_file.clone())
                }
                _ => {}
            }
        }
        if !entrypoints.is_empty() && conflicts.is_empty() {
            satisfying.push(build.build_id.clone());
            candidate_build_ids.insert(build.build_id.clone());
            matched_entrypoints.extend(entrypoints);
            matched_owned.extend(owned);
        } else if !conflicts.is_empty() {
            conflicting.extend(conflicts);
        }
    }

    let (resolved_build_id, resolution_method, note) = if let Some(manual) = &input.manual_build_id
    {
        (Some(manual.clone()), "manual".to_owned(), None)
    } else if let Some(reported) = &input.reported_build_id {
        (Some(reported.clone()), "reported".to_owned(), None)
    } else if satisfying.len() == 1 {
        (satisfying.first().cloned(), "auto_unique".to_owned(), None)
    } else if satisfying.len() > 1 {
        (
            None,
            "ambiguous".to_owned(),
            Some("multiple Builds satisfy the exact module intersection".to_owned()),
        )
    } else {
        (
            None,
            "unresolved".to_owned(),
            Some("no registered Build satisfies the exact module intersection".to_owned()),
        )
    };

    BuildResolutionEvidence {
        reported_build_id: input.reported_build_id.clone(),
        resolved_build_id,
        resolution_method,
        candidate_build_ids: candidate_build_ids.into_iter().collect(),
        matched_entrypoints: matched_entrypoints.into_iter().collect(),
        matched_owned_modules: matched_owned.into_iter().collect(),
        conflicting_modules: conflicting.into_iter().collect(),
        note,
    }
}

#[cfg(test)]
mod tests {
    use super::{
        format_rsds_debug_id, identify_artifact, infer_role, match_artifacts, resolve_build,
        select_status, verify_candidate, ArtifactError, ArtifactSpec, BuildModuleSpec, BuildSpec,
        MatchInput, MatchedModule, MAX_PDB_BYTES,
    };
    use crate::minidump::{InspectDump, InspectModule, InspectProcess, InspectReport};
    use std::io::{Seek, SeekFrom, Write};

    fn matched_module(code_file: &str, code_id: &str, role: &str) -> MatchedModule {
        MatchedModule {
            code_file: code_file.to_owned(),
            code_id: Some(code_id.to_owned()),
            debug_file: None,
            debug_id: None,
            role: role.to_owned(),
            in_app: matches!(role, "entrypoint" | "owned"),
            artifact_ids: vec![format!("art_{code_id}")],
            status: "matched".to_owned(),
            candidate_build_ids: Vec::new(),
        }
    }

    fn build(build_id: &str, modules: &[(&str, &str)]) -> BuildSpec {
        BuildSpec {
            build_id: build_id.to_owned(),
            modules: modules
                .iter()
                .map(|(code_id, role)| BuildModuleSpec {
                    code_id: Some((*code_id).to_owned()),
                    role: Some((*role).to_owned()),
                    ..Default::default()
                })
                .collect(),
        }
    }

    #[test]
    fn role_inference_keeps_system_modules_out_of_app() {
        assert_eq!(infer_role("C:\\Windows\\System32\\kernel32.dll"), "system");
        assert_eq!(infer_role("app.exe"), "entrypoint");
        assert_eq!(infer_role("engine.dll"), "unknown");
    }

    #[test]
    fn rsds_debug_id_uses_pe_guid_field_order() {
        let id = format_rsds_debug_id(
            0x5295c1f4,
            0x535d,
            0x4f8a,
            &[0xa0, 0xb1, 0x98, 0x98, 0x05, 0x19, 0x8b, 0xb8],
            0x15,
        );
        assert_eq!(id, "5295c1f4535d4f8aa0b1989805198bb815");
    }

    fn write_minimal_pdb(path: &std::path::Path, size: u64) {
        const PAGE_SIZE: usize = 512;
        let mut bytes = vec![0_u8; PAGE_SIZE * 4];
        bytes[0..32].copy_from_slice(b"Microsoft C/C++ MSF 7.00\r\n\x1aDS\0\0\0");
        bytes[32..36].copy_from_slice(&(PAGE_SIZE as u32).to_le_bytes());
        bytes[36..40].copy_from_slice(&1_u32.to_le_bytes());
        bytes[40..44].copy_from_slice(&4_u32.to_le_bytes());
        bytes[44..48].copy_from_slice(&24_u32.to_le_bytes());
        bytes[52..56].copy_from_slice(&1_u32.to_le_bytes());
        bytes[PAGE_SIZE..PAGE_SIZE + 4].copy_from_slice(&2_u32.to_le_bytes());

        let directory = PAGE_SIZE * 2;
        bytes[directory..directory + 4].copy_from_slice(&4_u32.to_le_bytes());
        bytes[directory + 4..directory + 8].copy_from_slice(&u32::MAX.to_le_bytes());
        bytes[directory + 8..directory + 12].copy_from_slice(&32_u32.to_le_bytes());
        bytes[directory + 12..directory + 16].copy_from_slice(&u32::MAX.to_le_bytes());
        bytes[directory + 16..directory + 20].copy_from_slice(&u32::MAX.to_le_bytes());
        bytes[directory + 20..directory + 24].copy_from_slice(&3_u32.to_le_bytes());

        let info = PAGE_SIZE * 3;
        bytes[info..info + 4].copy_from_slice(&20_000_404_u32.to_le_bytes());
        bytes[info + 8..info + 12].copy_from_slice(&1_u32.to_le_bytes());
        bytes[info + 12..info + 16].copy_from_slice(&0x1234_5678_u32.to_le_bytes());
        bytes[info + 16..info + 18].copy_from_slice(&0x9abc_u16.to_le_bytes());
        bytes[info + 18..info + 20].copy_from_slice(&0xdef0_u16.to_le_bytes());
        bytes[info + 20..info + 28]
            .copy_from_slice(&[0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]);

        let mut file = std::fs::File::create(path).expect("create synthetic PDB");
        file.write_all(&bytes).expect("write synthetic PDB pages");
        file.set_len(size).expect("extend sparse synthetic PDB");
        file.seek(SeekFrom::Start(0)).expect("rewind synthetic PDB");
    }

    #[test]
    fn pdb_larger_than_legacy_256_mib_is_identified_with_streaming_hash() {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .expect("clock after epoch")
            .as_nanos();
        let path = std::env::temp_dir()
            .join(format!("crash-cap-large-pdb-{}-{nonce}.pdb", std::process::id(),));
        let size = 256 * 1024 * 1024 + 4096;
        write_minimal_pdb(&path, size);
        let report = identify_artifact(&path, "pdb").expect("identify >256 MiB PDB");
        let _ = std::fs::remove_file(&path);
        assert_eq!(report.size, size);
        assert_eq!(report.debug_id.as_deref(), Some("123456789abcdef011223344556677881"));
        assert_eq!(report.sha256.len(), 64);
        assert!(!report.is_fastlink);
    }

    #[test]
    fn oversized_pdb_is_rejected_before_reading() {
        let path =
            std::env::temp_dir().join(format!("crash-cap-pdb-limit-{}.pdb", std::process::id()));
        let file = std::fs::File::create(&path).expect("create sparse artifact");
        file.set_len(MAX_PDB_BYTES + 1).expect("extend sparse artifact");
        let result = identify_artifact(&path, "pdb");
        let _ = std::fs::remove_file(&path);
        assert!(matches!(
            result,
            Err(ArtifactError::TooLarge { kind, size, limit, .. })
                if kind == "pdb" && size == MAX_PDB_BYTES + 1 && limit == MAX_PDB_BYTES
        ));
    }

    #[test]
    fn absent_artifacts_distinguish_business_and_system_modules() {
        let module = |code_file: &str, code_id: &str| InspectModule {
            code_file: code_file.to_owned(),
            code_id: code_id.to_owned(),
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
                platform_id: Some(2),
                build_number: None,
                processor_count: None,
            },
            exception: None,
            crash_thread_id: None,
            threads: Vec::new(),
            modules: vec![
                module("app.exe", "APP"),
                module("C:\\Windows\\System32\\ntdll.dll", "NTDLL"),
                module(
                    "C:\\Windows\\System32\\DriverStore\\FileRepository\\vendor.inf_amd64\\vendor.dll",
                    "VENDOR",
                ),
            ],
            warnings: Vec::new(),
        };
        let result = match_artifacts(&report, &MatchInput::default()).expect("match report");
        assert_eq!(result.modules[0].status, "missing_pe");
        assert_eq!(result.modules[1].status, "system_symbol_pending");
        assert_eq!(result.modules[2].role, "dependency");
        assert_eq!(result.modules[2].status, "missing_pe");
    }

    #[test]
    fn corrupt_exact_candidate_is_reported_without_parser_failure() {
        let path = std::env::temp_dir()
            .join(format!("crash-cap-corrupt-artifact-{}.exe", std::process::id()));
        std::fs::write(&path, b"not a PE").expect("write corrupt PE");
        let module = InspectModule {
            code_file: "app.exe".to_owned(),
            code_id: "APP".to_owned(),
            debug_file: None,
            debug_id: None,
            image_base: "0x1000".to_owned(),
            image_size: 0x1000,
            time_date_stamp: "0x0".to_owned(),
            checksum: "0x0".to_owned(),
        };
        let spec = ArtifactSpec {
            code_id: Some("APP".to_owned()),
            pe_path: Some(path.clone()),
            ..Default::default()
        };
        let result = verify_candidate(&module, &spec).expect("classified candidate");
        let _ = std::fs::remove_file(path);
        assert_eq!(result.status, "corrupted");
    }

    #[test]
    fn unrecognized_candidate_status_is_never_promoted_to_matched() {
        assert_eq!(select_status(&[]), "unsupported");
        assert_eq!(select_status(&["future_format".to_owned()]), "unsupported");
    }

    #[test]
    fn build_resolution_selects_one_exact_candidate() {
        let modules = vec![matched_module("app.exe", "CODE-A", "entrypoint")];
        let input = MatchInput {
            builds: vec![build("bld_exact", &[("CODE-A", "entrypoint")])],
            ..Default::default()
        };
        let result = resolve_build(&modules, &input);
        assert_eq!(result.resolution_method, "auto_unique");
        assert_eq!(result.resolved_build_id.as_deref(), Some("bld_exact"));
        assert_eq!(result.candidate_build_ids, ["bld_exact"]);
    }

    #[test]
    fn build_resolution_never_guesses_between_exact_candidates() {
        let modules = vec![matched_module("app.exe", "CODE-A", "entrypoint")];
        let input = MatchInput {
            builds: vec![
                build("bld_first", &[("CODE-A", "entrypoint")]),
                build("bld_second", &[("CODE-A", "entrypoint")]),
            ],
            ..Default::default()
        };
        let result = resolve_build(&modules, &input);
        assert_eq!(result.resolution_method, "ambiguous");
        assert_eq!(result.resolved_build_id, None);
        assert_eq!(result.candidate_build_ids, ["bld_first", "bld_second"]);
    }

    #[test]
    fn build_resolution_rejects_an_owned_module_conflict() {
        let modules = vec![
            matched_module("app.exe", "CODE-A", "entrypoint"),
            matched_module("engine.dll", "CODE-B", "owned"),
        ];
        let input = MatchInput {
            builds: vec![build("bld_incomplete", &[("CODE-A", "entrypoint")])],
            ..Default::default()
        };
        let result = resolve_build(&modules, &input);
        assert_eq!(result.resolution_method, "unresolved");
        assert_eq!(result.resolved_build_id, None);
        assert_eq!(result.conflicting_modules, ["engine.dll"]);
    }

    #[test]
    fn reported_build_is_explicit_and_not_replaced_by_auto_resolution() {
        let modules = vec![matched_module("app.exe", "CODE-A", "entrypoint")];
        let input = MatchInput {
            reported_build_id: Some("bld_reported".to_owned()),
            builds: vec![build("bld_auto", &[("CODE-A", "entrypoint")])],
            ..Default::default()
        };
        let result = resolve_build(&modules, &input);
        assert_eq!(result.resolution_method, "reported");
        assert_eq!(result.resolved_build_id.as_deref(), Some("bld_reported"));
        assert_eq!(result.candidate_build_ids, ["bld_auto"]);
    }

    #[test]
    fn manual_build_takes_precedence_over_reported_and_auto_resolution() {
        let modules = vec![matched_module("app.exe", "CODE-A", "entrypoint")];
        let input = MatchInput {
            manual_build_id: Some("bld_manual".to_owned()),
            reported_build_id: Some("bld_reported".to_owned()),
            builds: vec![build("bld_auto", &[("CODE-A", "entrypoint")])],
            ..Default::default()
        };
        let result = resolve_build(&modules, &input);
        assert_eq!(result.resolution_method, "manual");
        assert_eq!(result.resolved_build_id.as_deref(), Some("bld_manual"));
        assert_eq!(result.reported_build_id.as_deref(), Some("bld_reported"));
    }
}
