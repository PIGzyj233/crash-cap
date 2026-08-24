//! Artifact identity verification and minimal Workspace Build resolution.
//!
//! A filename is deliberately never used as a matching key.  PE identities
//! are derived from `TimeDateStamp + SizeOfImage`; PDB identities are read from
//! the PDB information stream and compared with the dump's CodeView RSDS ID.
//! The input is intentionally small and additive so a Worker can later pass a
//! richer immutable match spec without changing the core's matching rules.

use crate::minidump::{InspectModule, InspectReport};
use pdb::{FallibleIterator, Source, SourceSlice, SourceView, PDB};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::File;
use std::io::{self, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

/// Stable per-kind upload/ingest limits shared with the Platform contract.
pub const MAX_PE_BYTES: u64 = 512 * 1024 * 1024;
pub const MAX_PDB_BYTES: u64 = 2 * 1024 * 1024 * 1024;

const HASH_BUFFER_BYTES: usize = 1024 * 1024;
const MAX_PE_SECTION_TABLE_BYTES: usize = 4 * 1024 * 1024;
const MAX_PE_DEBUG_DIRECTORY_ENTRIES: usize = 4096;
const MAX_CODEVIEW_RECORD_BYTES: usize = 64 * 1024;
/// The `pdb` crate materializes one requested MSF stream at a time. Bound any
/// one view so a malformed PDB cannot turn the 2 GiB file contract into a
/// comparably sized heap allocation.
const MAX_PDB_VIEW_BYTES: usize = 256 * 1024 * 1024;

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

#[derive(Debug, thiserror::Error)]
pub enum ArtifactError {
    #[error("artifact path does not exist: {0}")]
    MissingPath(PathBuf),
    #[error("artifact I/O error for {path}: {source}")]
    Io { path: PathBuf, source: io::Error },
    #[error("artifact is not a valid PE image: {0}")]
    Pe(String),
    #[error("artifact is not a valid PDB: {0}")]
    Pdb(String),
    #[error("{kind} artifact is {size} bytes and exceeds the {limit}-byte size limit: {path}")]
    TooLarge { path: PathBuf, kind: String, size: u64, limit: u64 },
    #[error("unsupported artifact kind: {0}")]
    UnsupportedKind(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PeIdentity {
    code_id: String,
    debug_id: Option<String>,
    debug_file: Option<String>,
    size_of_image: u32,
    timestamp: u32,
    sha256: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PdbIdentity {
    debug_id: String,
    sha256: String,
    is_fastlink: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ArtifactIdentityReport {
    pub kind: String,
    pub size: u64,
    pub sha256: String,
    pub code_id: Option<String>,
    pub debug_id: Option<String>,
    pub debug_file: Option<String>,
    pub is_fastlink: bool,
}

/// Extract authoritative identity directly from verified PE/PDB bytes. This
/// command-facing shape prevents the Platform from trusting Manifest hints.
pub fn identify_artifact(path: &Path, kind: &str) -> Result<ArtifactIdentityReport, ArtifactError> {
    let limit = match kind {
        "pe" => MAX_PE_BYTES,
        "pdb" => MAX_PDB_BYTES,
        other => return Err(ArtifactError::UnsupportedKind(other.to_owned())),
    };
    let (mut file, size) = open_limited(path, kind, limit)?;
    match kind {
        "pe" => {
            let identity = parse_pe(&mut file, path, size)?;
            Ok(ArtifactIdentityReport {
                kind: kind.to_owned(),
                size,
                sha256: identity.sha256,
                code_id: Some(identity.code_id),
                debug_id: identity.debug_id,
                debug_file: identity.debug_file,
                is_fastlink: false,
            })
        }
        "pdb" => {
            let identity = parse_pdb(file, path, size)?;
            Ok(ArtifactIdentityReport {
                kind: kind.to_owned(),
                size,
                sha256: identity.sha256,
                code_id: None,
                debug_id: Some(identity.debug_id),
                debug_file: None,
                is_fastlink: identity.is_fastlink,
            })
        }
        _ => unreachable!("artifact kind was validated before opening"),
    }
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
            let pe = parse_pe_path(&path).ok()?;
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
    let pe = match parse_pe_path(&pe_path) {
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
    let pdb = match parse_pdb_path(&pdb_path) {
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

fn parse_pe(file: &mut File, path: &Path, file_size: u64) -> Result<PeIdentity, ArtifactError> {
    let dos = read_pe_range(file, path, file_size, 0, 0x40, "DOS header")?;
    if &dos[0..2] != b"MZ" {
        return Err(ArtifactError::Pe(format!("{}: missing MZ header", path.display())));
    }
    let pe_offset = read_u32(&dos, 0x3c)? as u64;
    let coff_header = read_pe_range(file, path, file_size, pe_offset, 24, "PE/COFF header")?;
    if &coff_header[0..4] != b"PE\0\0" {
        return Err(ArtifactError::Pe(format!("{}: missing PE signature", path.display())));
    }
    let machine = read_u16(&coff_header, 4)?;
    if machine != 0x8664 {
        return Err(ArtifactError::Pe(format!(
            "{}: unsupported PE machine 0x{machine:04x}",
            path.display()
        )));
    }
    let sections = read_u16(&coff_header, 6)? as usize;
    let timestamp = read_u32(&coff_header, 8)?;
    let optional_size = read_u16(&coff_header, 20)? as usize;
    let optional_offset = pe_offset.checked_add(24).ok_or_else(|| {
        ArtifactError::Pe(format!("{}: optional header offset overflows", path.display()))
    })?;
    let optional =
        read_pe_range(file, path, file_size, optional_offset, optional_size, "optional header")?;
    let magic = read_u16(&optional, 0)?;
    let image_size = read_u32(&optional, 56)?;
    let data_directory: usize = match magic {
        0x20b => 112,
        0x10b => 96,
        _ => {
            return Err(ArtifactError::Pe(format!(
                "{}: unknown optional-header magic",
                path.display()
            )))
        }
    };
    let debug_dir = data_directory.checked_add(6 * 8).ok_or_else(|| {
        ArtifactError::Pe(format!("{}: debug directory offset overflows", path.display()))
    })?;
    let debug_rva = read_u32(&optional, debug_dir)?;
    let debug_size = read_u32(&optional, debug_dir + 4)?;
    let section_table_bytes = sections.checked_mul(40).ok_or_else(|| {
        ArtifactError::Pe(format!("{}: section table size overflows", path.display()))
    })?;
    if section_table_bytes > MAX_PE_SECTION_TABLE_BYTES {
        return Err(ArtifactError::Pe(format!(
            "{}: section table exceeds the {}-byte parser budget",
            path.display(),
            MAX_PE_SECTION_TABLE_BYTES
        )));
    }
    let section_table_offset =
        optional_offset.checked_add(optional_size as u64).ok_or_else(|| {
            ArtifactError::Pe(format!("{}: section table offset overflows", path.display()))
        })?;
    let section_table = read_pe_range(
        file,
        path,
        file_size,
        section_table_offset,
        section_table_bytes,
        "section table",
    )?;
    let debug_offset = if debug_rva == 0 || debug_size == 0 {
        None
    } else {
        rva_to_file_offset(&section_table, 0, sections, debug_rva).map(|offset| offset as u64)
    };
    let (debug_id, debug_file) = if let Some(offset) = debug_offset {
        parse_debug_directory(file, path, file_size, offset, debug_size as usize)?
    } else {
        (None, None)
    };
    let sha256 = sha256_file(file, path, file_size)?;
    Ok(PeIdentity {
        code_id: format!("{timestamp:08X}{image_size:X}"),
        debug_id,
        debug_file,
        size_of_image: image_size,
        timestamp,
        sha256,
    })
}

fn parse_pe_path(path: &Path) -> Result<PeIdentity, ArtifactError> {
    let (mut file, size) = open_limited(path, "pe", MAX_PE_BYTES)?;
    parse_pe(&mut file, path, size)
}

fn parse_debug_directory(
    file: &mut File,
    path: &Path,
    file_size: u64,
    offset: u64,
    size: usize,
) -> Result<(Option<String>, Option<String>), ArtifactError> {
    let count = size / 28;
    if count > MAX_PE_DEBUG_DIRECTORY_ENTRIES {
        return Err(ArtifactError::Pe(format!(
            "{}: debug directory exceeds the {}-entry parser budget",
            path.display(),
            MAX_PE_DEBUG_DIRECTORY_ENTRIES
        )));
    }
    for index in 0..count {
        let entry = offset
            .checked_add((index as u64).checked_mul(28).ok_or_else(|| {
                ArtifactError::Pe("debug directory entry offset overflows".to_owned())
            })?)
            .ok_or_else(|| {
                ArtifactError::Pe("debug directory entry offset overflows".to_owned())
            })?;
        let entry = read_pe_range(file, path, file_size, entry, 28, "debug directory")?;
        let kind = read_u32(&entry, 12)?;
        if kind != 2 {
            continue;
        }
        let data_size = read_u32(&entry, 16)? as usize;
        // AddressOfRawData is an RVA; PointerToRawData is the file offset.
        let data_offset = read_u32(&entry, 24)? as u64;
        if data_size < 24 {
            return Err(ArtifactError::Pe("CodeView record is truncated".to_owned()));
        }
        let read_size = data_size.min(MAX_CODEVIEW_RECORD_BYTES);
        let record =
            read_pe_range(file, path, file_size, data_offset, read_size, "CodeView record")?;
        if &record[0..4] != b"RSDS" {
            continue;
        }
        let data1 = read_u32(&record, 4)?;
        let data2 = read_u16(&record, 8)?;
        let data3 = read_u16(&record, 10)?;
        let guid_tail = &record[12..20];
        let age = read_u32(&record, 20)?;
        let debug_id = format_rsds_debug_id(data1, data2, data3, guid_tail, age);
        let raw_name = &record[24..];
        let name_end = raw_name.iter().position(|byte| *byte == 0).unwrap_or(raw_name.len());
        if data_size > MAX_CODEVIEW_RECORD_BYTES && name_end == raw_name.len() {
            return Err(ArtifactError::Pe(format!(
                "{}: CodeView path exceeds the {}-byte parser budget",
                path.display(),
                MAX_CODEVIEW_RECORD_BYTES
            )));
        }
        let debug_file = Some(String::from_utf8_lossy(&raw_name[..name_end]).into_owned());
        return Ok((Some(debug_id), debug_file));
    }
    Ok((None, None))
}

fn parse_pdb(mut file: File, path: &Path, file_size: u64) -> Result<PdbIdentity, ArtifactError> {
    let sha256 = sha256_file(&mut file, path, file_size)?;
    let source = BoundedPdbSource { file, file_size };
    let mut pdb = PDB::open(source).map_err(|error| ArtifactError::Pdb(error.to_string()))?;
    let info = pdb.pdb_information().map_err(|error| ArtifactError::Pdb(error.to_string()))?;
    // pdb parses the three little-endian GUID fields with Uuid::from_fields;
    // its canonical bytes are therefore already in Breakpad/RSDS display
    // order. Never hex-encode the raw on-disk GUID bytes here.
    let mut debug_id = hex::encode(info.guid.as_bytes());
    debug_id.push_str(&format!("{:x}", info.age));
    drop(info);
    let is_fastlink = match pdb.global_symbols() {
        Ok(symbols) => {
            let mut iter = symbols.iter();
            loop {
                match iter.next() {
                    Ok(Some(symbol)) if symbol.raw_kind() == 0x1167 => break true,
                    Ok(Some(_)) => {}
                    Ok(None) => break false,
                    Err(error) => return Err(ArtifactError::Pdb(error.to_string())),
                }
            }
        }
        Err(pdb::Error::StreamNotFound(_) | pdb::Error::GlobalSymbolsNotFound) => false,
        Err(error) => return Err(ArtifactError::Pdb(error.to_string())),
    };
    Ok(PdbIdentity { debug_id, sha256, is_fastlink })
}

fn parse_pdb_path(path: &Path) -> Result<PdbIdentity, ArtifactError> {
    let (file, size) = open_limited(path, "pdb", MAX_PDB_BYTES)?;
    parse_pdb(file, path, size)
}

fn open_limited(path: &Path, kind: &str, limit: u64) -> Result<(File, u64), ArtifactError> {
    let file = File::open(path).map_err(|error| {
        if error.kind() == io::ErrorKind::NotFound {
            ArtifactError::MissingPath(path.to_owned())
        } else {
            ArtifactError::Io { path: path.to_owned(), source: error }
        }
    })?;
    let size = file
        .metadata()
        .map_err(|source| ArtifactError::Io { path: path.to_owned(), source })?
        .len();
    if size > limit {
        return Err(ArtifactError::TooLarge {
            path: path.to_owned(),
            kind: kind.to_owned(),
            size,
            limit,
        });
    }
    Ok((file, size))
}

fn sha256_file(file: &mut File, path: &Path, expected_size: u64) -> Result<String, ArtifactError> {
    file.seek(SeekFrom::Start(0))
        .map_err(|source| ArtifactError::Io { path: path.to_owned(), source })?;
    let mut hasher = Sha256::new();
    let mut buffer = vec![0_u8; HASH_BUFFER_BYTES];
    let mut total = 0_u64;
    let mut reader = file.take(expected_size.saturating_add(1));
    loop {
        let read = reader
            .read(&mut buffer)
            .map_err(|source| ArtifactError::Io { path: path.to_owned(), source })?;
        if read == 0 {
            break;
        }
        total = total.saturating_add(read as u64);
        hasher.update(&buffer[..read]);
    }
    if total != expected_size {
        return Err(ArtifactError::Io {
            path: path.to_owned(),
            source: io::Error::new(
                io::ErrorKind::InvalidData,
                format!("artifact size changed during identification: expected {expected_size}, read {total}"),
            ),
        });
    }
    Ok(hex::encode(hasher.finalize()))
}

fn read_pe_range(
    file: &mut File,
    path: &Path,
    file_size: u64,
    offset: u64,
    size: usize,
    label: &str,
) -> Result<Vec<u8>, ArtifactError> {
    let end = offset
        .checked_add(size as u64)
        .ok_or_else(|| ArtifactError::Pe(format!("{}: {label} range overflows", path.display())))?;
    if end > file_size {
        return Err(ArtifactError::Pe(format!("{}: {label} is truncated", path.display())));
    }
    file.seek(SeekFrom::Start(offset))
        .map_err(|source| ArtifactError::Io { path: path.to_owned(), source })?;
    let mut bytes = vec![0_u8; size];
    file.read_exact(&mut bytes)
        .map_err(|source| ArtifactError::Io { path: path.to_owned(), source })?;
    Ok(bytes)
}

#[derive(Debug)]
struct BoundedPdbSource {
    file: File,
    file_size: u64,
}

#[derive(Debug)]
struct OwnedPdbView {
    bytes: Vec<u8>,
}

impl SourceView<'_> for OwnedPdbView {
    fn as_slice(&self) -> &[u8] {
        &self.bytes
    }
}

impl<'source> Source<'source> for BoundedPdbSource {
    fn view(&mut self, slices: &[SourceSlice]) -> Result<Box<dyn SourceView<'source>>, io::Error> {
        let total = slices.iter().try_fold(0_usize, |total, slice| {
            total.checked_add(slice.size).ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidData, "PDB view size overflows")
            })
        })?;
        if total > MAX_PDB_VIEW_BYTES {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                format!("PDB parser view exceeds the {MAX_PDB_VIEW_BYTES}-byte memory budget"),
            ));
        }
        let mut bytes = Vec::new();
        bytes.try_reserve_exact(total).map_err(|error| {
            io::Error::new(io::ErrorKind::OutOfMemory, format!("cannot reserve PDB view: {error}"))
        })?;
        bytes.resize(total, 0);
        let mut output_offset = 0;
        for slice in slices {
            let end = slice.offset.checked_add(slice.size as u64).ok_or_else(|| {
                io::Error::new(io::ErrorKind::InvalidData, "PDB source range overflows")
            })?;
            if end > self.file_size {
                return Err(io::Error::new(
                    io::ErrorKind::UnexpectedEof,
                    "PDB source range exceeds the artifact",
                ));
            }
            self.file.seek(SeekFrom::Start(slice.offset))?;
            self.file.read_exact(&mut bytes[output_offset..output_offset + slice.size])?;
            output_offset += slice.size;
        }
        Ok(Box::new(OwnedPdbView { bytes }))
    }
}

fn rva_to_file_offset(
    bytes: &[u8],
    section_table: usize,
    sections: usize,
    rva: u32,
) -> Option<usize> {
    for index in 0..sections {
        let offset = section_table.checked_add(index.checked_mul(40)?)?;
        if offset.checked_add(40)? > bytes.len() {
            return None;
        }
        let virtual_size = read_u32(bytes, offset + 8).ok()?;
        let virtual_address = read_u32(bytes, offset + 12).ok()?;
        let raw_size = read_u32(bytes, offset + 16).ok()?;
        let raw_offset = read_u32(bytes, offset + 20).ok()?;
        let size = virtual_size.max(raw_size);
        if rva >= virtual_address && rva < virtual_address.saturating_add(size) {
            return raw_offset.checked_add(rva - virtual_address).map(|value| value as usize);
        }
    }
    None
}

fn format_rsds_debug_id(data1: u32, data2: u16, data3: u16, guid_tail: &[u8], age: u32) -> String {
    let mut debug_id = format!("{data1:08x}{data2:04x}{data3:04x}");
    debug_id.push_str(&hex::encode(guid_tail));
    debug_id.push_str(&format!("{age:x}"));
    debug_id
}

fn read_u16(bytes: &[u8], offset: usize) -> Result<u16, ArtifactError> {
    let end =
        offset.checked_add(2).ok_or_else(|| ArtifactError::Pe("truncated integer".to_owned()))?;
    let bytes =
        bytes.get(offset..end).ok_or_else(|| ArtifactError::Pe("truncated integer".to_owned()))?;
    Ok(u16::from_le_bytes([bytes[0], bytes[1]]))
}

fn read_u32(bytes: &[u8], offset: usize) -> Result<u32, ArtifactError> {
    let end =
        offset.checked_add(4).ok_or_else(|| ArtifactError::Pe("truncated integer".to_owned()))?;
    let bytes =
        bytes.get(offset..end).ok_or_else(|| ArtifactError::Pe("truncated integer".to_owned()))?;
    Ok(u32::from_le_bytes([bytes[0], bytes[1], bytes[2], bytes[3]]))
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
            ],
            warnings: Vec::new(),
        };
        let result = match_artifacts(&report, &MatchInput::default()).expect("match report");
        assert_eq!(result.modules[0].status, "missing_pe");
        assert_eq!(result.modules[1].status, "system_symbol_pending");
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
