//! Bounded, streaming PE/PDB identity extraction shared by the Core and CLI.

use pdb::{FallibleIterator, Source, SourceSlice, SourceView, PDB};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::fs::File;
use std::io::{self, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};

pub const MAX_PE_BYTES: u64 = 512 * 1024 * 1024;
pub const MAX_PDB_BYTES: u64 = 2 * 1024 * 1024 * 1024;

const HASH_BUFFER_BYTES: usize = 1024 * 1024;
const MAX_PE_SECTION_TABLE_BYTES: usize = 4 * 1024 * 1024;
const MAX_PE_DEBUG_DIRECTORY_ENTRIES: usize = 4096;
const MAX_CODEVIEW_RECORD_BYTES: usize = 64 * 1024;
const MAX_PDB_VIEW_BYTES: usize = 256 * 1024 * 1024;

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
pub struct PeIdentity {
    pub code_id: String,
    pub debug_id: Option<String>,
    pub debug_file: Option<String>,
    pub size_of_image: u32,
    pub timestamp: u32,
    pub sha256: String,
    pub size: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PdbIdentity {
    pub debug_id: String,
    pub sha256: String,
    pub is_fastlink: bool,
    pub size: u64,
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

pub fn identify_artifact(path: &Path, kind: &str) -> Result<ArtifactIdentityReport, ArtifactError> {
    match kind {
        "pe" => {
            let identity = identify_pe(path)?;
            Ok(ArtifactIdentityReport {
                kind: kind.to_owned(),
                size: identity.size,
                sha256: identity.sha256,
                code_id: Some(identity.code_id),
                debug_id: identity.debug_id,
                debug_file: identity.debug_file,
                is_fastlink: false,
            })
        }
        "pdb" => {
            let identity = identify_pdb(path)?;
            Ok(ArtifactIdentityReport {
                kind: kind.to_owned(),
                size: identity.size,
                sha256: identity.sha256,
                code_id: None,
                debug_id: Some(identity.debug_id),
                debug_file: None,
                is_fastlink: identity.is_fastlink,
            })
        }
        other => Err(ArtifactError::UnsupportedKind(other.to_owned())),
    }
}

pub fn identify_pe(path: &Path) -> Result<PeIdentity, ArtifactError> {
    let (mut file, size) = open_limited(path, "pe", MAX_PE_BYTES)?;
    parse_pe(&mut file, path, size)
}

pub fn identify_pdb(path: &Path) -> Result<PdbIdentity, ArtifactError> {
    let (file, size) = open_limited(path, "pdb", MAX_PDB_BYTES)?;
    parse_pdb(file, path, size)
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
        size: file_size,
    })
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
    Ok(PdbIdentity { debug_id, sha256, is_fastlink, size: file_size })
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
                format!(
                    "artifact size changed during identification: expected {expected_size}, read {total}"
                ),
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

#[doc(hidden)]
pub fn format_rsds_debug_id(
    data1: u32,
    data2: u16,
    data3: u16,
    guid_tail: &[u8],
    age: u32,
) -> String {
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
    use super::format_rsds_debug_id;

    #[test]
    fn rsds_debug_id_uses_pe_guid_field_order() {
        assert_eq!(
            format_rsds_debug_id(
                0x5295c1f4,
                0x535d,
                0x4f8a,
                &[0xa0, 0xb1, 0x98, 0x98, 0x05, 0x19, 0x8b, 0xb8],
                0x15,
            ),
            "5295c1f4535d4f8aa0b1989805198bb815"
        );
    }
}
