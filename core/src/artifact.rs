//! Artifact identity verification and minimal Workspace Build resolution.
//!
//! A filename is deliberately never used as a matching key.  PE identities
//! are derived from `TimeDateStamp + SizeOfImage`; PDB identities are read from
//! the PDB information stream and compared with the dump's CodeView RSDS ID.
//! The input is intentionally small and additive so a Worker can later pass a
//! richer immutable match spec without changing the core's matching rules.

use crate::canonical::sha256_hex;
use crate::minidump::{InspectModule, InspectReport};
use pdb::PDB;
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::File;
use std::io::{self, Read};
use std::path::{Path, PathBuf};

/// PE/PDB inputs are read by parsers that need random access. Keep a hard
/// bound before allocation; the worker applies the same limit to uploaded
/// artifacts.
pub const MAX_ARTIFACT_BYTES: u64 = 256 * 1024 * 1024;

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
    #[error("artifact exceeds the {limit}-byte size limit: {path}")]
    TooLarge { path: PathBuf, limit: u64 },
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
            let pe = parse_pe(&path).ok()?;
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
    let pe = match parse_pe(&pe_path) {
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
    let pdb = match parse_pdb(&pdb_path) {
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

fn parse_pe(path: &Path) -> Result<PeIdentity, ArtifactError> {
    let bytes = read_file(path)?;
    if bytes.len() < 0x40 || &bytes[0..2] != b"MZ" {
        return Err(ArtifactError::Pe(format!("{}: missing MZ header", path.display())));
    }
    let pe_offset = read_u32(&bytes, 0x3c)? as usize;
    let pe_signature_end = pe_offset
        .checked_add(4)
        .ok_or_else(|| ArtifactError::Pe(format!("{}: PE offset overflows", path.display())))?;
    if bytes.get(pe_offset..pe_signature_end) != Some(b"PE\0\0") {
        return Err(ArtifactError::Pe(format!("{}: missing PE signature", path.display())));
    }
    let coff = pe_offset + 4;
    let machine = read_u16(&bytes, coff)?;
    if machine != 0x8664 {
        return Err(ArtifactError::Pe(format!(
            "{}: unsupported PE machine 0x{machine:04x}",
            path.display()
        )));
    }
    let sections = read_u16(&bytes, coff + 2)? as usize;
    let timestamp = read_u32(&bytes, coff + 4)?;
    let optional_size = read_u16(&bytes, coff + 16)? as usize;
    let optional = coff + 20;
    let optional_end = optional.checked_add(optional_size).ok_or_else(|| {
        ArtifactError::Pe(format!("{}: optional header range overflows", path.display()))
    })?;
    if optional_end > bytes.len() {
        return Err(ArtifactError::Pe(format!("{}: optional header is truncated", path.display())));
    }
    let magic = read_u16(&bytes, optional)?;
    let image_size = read_u32(&bytes, optional + 56)?;
    let data_directory = match magic {
        0x20b => optional + 112,
        0x10b => optional + 96,
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
    let debug_rva = read_u32(&bytes, debug_dir)?;
    let debug_size = read_u32(&bytes, debug_dir + 4)?;
    let section_table = optional + optional_size;
    let debug_offset = rva_to_file_offset(&bytes, section_table, sections, debug_rva);
    let (debug_id, debug_file) = if let Some(offset) = debug_offset {
        parse_debug_directory(&bytes, offset, debug_size as usize)?
    } else {
        (None, None)
    };
    Ok(PeIdentity {
        code_id: format!("{timestamp:08X}{image_size:X}"),
        debug_id,
        debug_file,
        size_of_image: image_size,
        timestamp,
        sha256: sha256_hex(&bytes),
    })
}

fn parse_debug_directory(
    bytes: &[u8],
    offset: usize,
    size: usize,
) -> Result<(Option<String>, Option<String>), ArtifactError> {
    let count = size / 28;
    for index in 0..count {
        let entry = offset
            .checked_add(index.checked_mul(28).ok_or_else(|| {
                ArtifactError::Pe("debug directory entry offset overflows".to_owned())
            })?)
            .ok_or_else(|| {
                ArtifactError::Pe("debug directory entry offset overflows".to_owned())
            })?;
        let entry_end = entry
            .checked_add(28)
            .ok_or_else(|| ArtifactError::Pe("debug directory entry range overflows".to_owned()))?;
        if entry_end > bytes.len() {
            return Err(ArtifactError::Pe("debug directory is truncated".to_owned()));
        }
        let kind = read_u32(bytes, entry + 12)?;
        if kind != 2 {
            continue;
        }
        let data_size = read_u32(bytes, entry + 16)? as usize;
        // AddressOfRawData is an RVA; PointerToRawData is the file offset.
        let data_offset = read_u32(bytes, entry + 24)? as usize;
        let data_end = data_offset
            .checked_add(data_size)
            .ok_or_else(|| ArtifactError::Pe("CodeView record range overflows".to_owned()))?;
        if data_end > bytes.len() || data_size < 24 {
            return Err(ArtifactError::Pe("CodeView record is truncated".to_owned()));
        }
        let signature_end = data_offset
            .checked_add(4)
            .ok_or_else(|| ArtifactError::Pe("CodeView signature range overflows".to_owned()))?;
        if &bytes[data_offset..signature_end] != b"RSDS" {
            continue;
        }
        let data1 = read_u32(bytes, data_offset + 4)?;
        let data2 = read_u16(bytes, data_offset + 8)?;
        let data3 = read_u16(bytes, data_offset + 10)?;
        let guid_tail = &bytes[data_offset + 12..data_offset + 20];
        let age = read_u32(bytes, data_offset + 20)?;
        let debug_id = format_rsds_debug_id(data1, data2, data3, guid_tail, age);
        let debug_file = bytes
            .get(data_offset + 24..data_end)
            .map(|raw| String::from_utf8_lossy(raw).trim_end_matches('\0').to_owned());
        return Ok((Some(debug_id), debug_file));
    }
    Ok((None, None))
}

fn parse_pdb(path: &Path) -> Result<PdbIdentity, ArtifactError> {
    let bytes = read_file(path)?;
    let mut pdb = PDB::open(std::io::Cursor::new(bytes.clone()))
        .map_err(|error| ArtifactError::Pdb(error.to_string()))?;
    let info = pdb.pdb_information().map_err(|error| ArtifactError::Pdb(error.to_string()))?;
    // pdb parses the three little-endian GUID fields with Uuid::from_fields;
    // its canonical bytes are therefore already in Breakpad/RSDS display
    // order. Never hex-encode the raw on-disk GUID bytes here.
    let mut debug_id = hex::encode(info.guid.as_bytes());
    debug_id.push_str(&format!("{:x}", info.age));
    Ok(PdbIdentity { debug_id, sha256: sha256_hex(&bytes) })
}

fn read_file(path: &Path) -> Result<Vec<u8>, ArtifactError> {
    let metadata = std::fs::metadata(path).map_err(|error| {
        if error.kind() == io::ErrorKind::NotFound {
            ArtifactError::MissingPath(path.to_owned())
        } else {
            ArtifactError::Io { path: path.to_owned(), source: error }
        }
    })?;
    if metadata.len() > MAX_ARTIFACT_BYTES {
        return Err(ArtifactError::TooLarge { path: path.to_owned(), limit: MAX_ARTIFACT_BYTES });
    }
    let mut file = File::open(path).map_err(|error| {
        if error.kind() == io::ErrorKind::NotFound {
            ArtifactError::MissingPath(path.to_owned())
        } else {
            ArtifactError::Io { path: path.to_owned(), source: error }
        }
    })?;
    let mut bytes = Vec::new();
    file.read_to_end(&mut bytes)
        .map_err(|error| ArtifactError::Io { path: path.to_owned(), source: error })?;
    Ok(bytes)
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
        format_rsds_debug_id, infer_role, match_artifacts, read_file, resolve_build, select_status,
        verify_candidate, ArtifactError, ArtifactSpec, BuildModuleSpec, BuildSpec, MatchInput,
        MatchedModule, MAX_ARTIFACT_BYTES,
    };
    use crate::minidump::{InspectDump, InspectModule, InspectProcess, InspectReport};

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

    #[test]
    fn oversized_artifact_is_rejected_before_reading() {
        let path = std::env::temp_dir()
            .join(format!("crash-cap-artifact-limit-{}.bin", std::process::id()));
        let file = std::fs::File::create(&path).expect("create sparse artifact");
        file.set_len(MAX_ARTIFACT_BYTES + 1).expect("extend sparse artifact");
        let result = read_file(&path);
        let _ = std::fs::remove_file(&path);
        assert!(matches!(result, Err(ArtifactError::TooLarge { .. })));
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
