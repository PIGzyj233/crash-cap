//! Optional source context read directly from the content-pinned ZIP. Never
//! trust Worker-extracted text and never extract archive paths onto a filesystem.

use crate::analysis_context::{resolve_entry, source_context_warning, supported_source_extension};
use crate::canonical::{sha256_hex, SourceContext};
use crate::canonical_v11::CanonicalResultV11;
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};

pub const MAX_ARCHIVE_BYTES: u64 = 512 * 1024 * 1024;
const MAX_ENTRIES: u64 = 20_000;
const MAX_INDEX_BYTES: u64 = 16 * 1024 * 1024;
const MAX_SOURCE_BYTES: u64 = 2 * 1024 * 1024;
const MAX_CONTEXT_BYTES: usize = 16 * 1024 * 1024;
const MAX_TEXT_SCAN_BYTES: usize = 64 * 1024 * 1024;
type SourceResult<T> = Result<T, &'static str>;

fn require(ok: bool, code: &'static str) -> SourceResult<()> {
    if ok {
        Ok(())
    } else {
        Err(code)
    }
}

fn number(bytes: &[u8], start: usize, width: usize) -> SourceResult<u64> {
    let end = start.checked_add(width).ok_or("SOURCE_ZIP_INVALID")?;
    let data = bytes.get(start..end).ok_or("SOURCE_ZIP_INVALID")?;
    Ok(data.iter().enumerate().fold(0, |value, (i, byte)| value | (u64::from(*byte) << (8 * i))))
}

// Bound central-directory allocation before handing the archive to the ZIP
// library. This is only a resource preflight, not an alternative ZIP decoder.
fn index_budget(bytes: &[u8]) -> SourceResult<()> {
    let start = bytes.len().saturating_sub(65535 + 22);
    let end = (start..bytes.len().saturating_sub(21))
        .rev()
        .find(|&i| {
            bytes.get(i..i + 4) == Some(b"PK\x05\x06")
                && number(bytes, i + 20, 2).is_ok_and(|n| i + 22 + n as usize == bytes.len())
        })
        .ok_or("SOURCE_ZIP_INVALID")?;
    let mut count = number(bytes, end + 10, 2)?;
    let mut index_size = number(bytes, end + 12, 4)?;
    if count == 0xffff || index_size == 0xffff_ffff {
        let locator = end.checked_sub(20).ok_or("SOURCE_ZIP_INVALID")?;
        require(bytes.get(locator..locator + 4) == Some(b"PK\x06\x07"), "SOURCE_ZIP_INVALID")?;
        let offset =
            usize::try_from(number(bytes, locator + 8, 8)?).map_err(|_| "SOURCE_ZIP_INVALID")?;
        require(
            bytes.get(offset..offset.saturating_add(4)) == Some(b"PK\x06\x06"),
            "SOURCE_ZIP_INVALID",
        )?;
        count = number(bytes, offset.checked_add(32).ok_or("SOURCE_ZIP_INVALID")?, 8)?;
        index_size = number(bytes, offset.checked_add(40).ok_or("SOURCE_ZIP_INVALID")?, 8)?;
    }
    require(count <= MAX_ENTRIES, "SOURCE_ZIP_ENTRY_LIMIT")?;
    require(index_size <= MAX_INDEX_BYTES, "SOURCE_ZIP_INDEX_LIMIT")
}

fn read_archive(path: &Path, sha: &str, size: u64) -> SourceResult<BTreeMap<String, String>> {
    require(size > 0 && size <= MAX_ARCHIVE_BYTES, "SOURCE_ARCHIVE_SIZE_LIMIT")?;
    let metadata = fs::symlink_metadata(path).map_err(|_| "SOURCE_ARCHIVE_UNAVAILABLE")?;
    require(
        metadata.is_file() && !metadata.file_type().is_symlink(),
        "SOURCE_ARCHIVE_NOT_REGULAR",
    )?;
    require(metadata.len() == size, "SOURCE_ARCHIVE_SIZE_MISMATCH")?;
    let file = File::open(path).map_err(|_| "SOURCE_ARCHIVE_UNAVAILABLE")?;
    let mut bytes = Vec::new();
    file.take(size + 1).read_to_end(&mut bytes).map_err(|_| "SOURCE_ARCHIVE_READ_FAILED")?;
    require(
        bytes.len() as u64 == size && sha256_hex(&bytes) == sha,
        "SOURCE_ARCHIVE_HASH_MISMATCH",
    )?;
    decode_archive(&bytes)
}

fn decode_archive(bytes: &[u8]) -> SourceResult<BTreeMap<String, String>> {
    index_budget(bytes)?;
    let mut archive = zip::ZipArchive::new(Cursor::new(bytes)).map_err(|_| "SOURCE_ZIP_INVALID")?;
    require(archive.len() as u64 <= MAX_ENTRIES, "SOURCE_ZIP_ENTRY_LIMIT")?;
    let mut names = BTreeSet::new();
    let mut total = 0u64;
    let mut sources = BTreeMap::new();
    for index in 0..archive.len() {
        // LZMA carries a dictionary size in its compressed header. Check it
        // through the raw reader before constructing an allocating decoder.
        {
            let mut raw = archive.by_index_raw(index).map_err(|_| "SOURCE_ZIP_INVALID")?;
            if raw.compression() == zip::CompressionMethod::Lzma {
                let mut properties = [0u8; 9];
                raw.read_exact(&mut properties).map_err(|_| "SOURCE_LZMA_PROPERTIES")?;
                require(number(&properties, 2, 2)? == 5, "SOURCE_LZMA_PROPERTIES")?;
                require(
                    number(&properties, 5, 4)? <= 16 * 1024 * 1024,
                    "SOURCE_LZMA_DICTIONARY_LIMIT",
                )?;
            }
        }
        let mut entry = archive.by_index(index).map_err(|_| "SOURCE_ZIP_INVALID")?;
        let raw =
            std::str::from_utf8(entry.name_raw()).map_err(|_| "SOURCE_PATH_ENCODING")?.to_owned();
        let name = raw.trim_end_matches('/');
        require(
            !name.is_empty()
                && !raw.starts_with('/')
                && !raw.contains(['\\', '\0', ':'])
                && name.split('/').all(|part| !part.is_empty() && part != "." && part != ".."),
            "SOURCE_PATH_UNSAFE",
        )?;
        let header =
            usize::try_from(entry.central_header_start()).map_err(|_| "SOURCE_ZIP_INVALID")?;
        let flags = number(bytes, header.checked_add(8).ok_or("SOURCE_ZIP_INVALID")?, 2)?;
        require(raw.is_ascii() || flags & 0x800 != 0, "SOURCE_PATH_ENCODING")?;
        require(!entry.encrypted() && !entry.is_symlink(), "SOURCE_ENTRY_UNSUPPORTED")?;
        require(names.insert(name.to_lowercase()), "SOURCE_PATH_DUPLICATE")?;
        if entry.is_dir() {
            continue;
        }
        require(entry.is_file(), "SOURCE_ENTRY_UNSUPPORTED")?;
        let path = Path::new(name);
        let extension = path.extension().and_then(|v| v.to_str()).unwrap_or("").to_lowercase();
        require(
            !["zip", "7z", "rar", "tar", "gz", "bz2", "xz"].contains(&extension.as_str()),
            "SOURCE_NESTED_ARCHIVE",
        )?;
        total = total.checked_add(entry.size()).ok_or("SOURCE_UNCOMPRESSED_LIMIT")?;
        require(total <= MAX_ARCHIVE_BYTES, "SOURCE_UNCOMPRESSED_LIMIT")?;
        require(
            entry.size() == 0
                || (entry.compressed_size() > 0
                    && u128::from(entry.size()) <= u128::from(entry.compressed_size()) * 100),
            "SOURCE_COMPRESSION_RATIO",
        )?;
        if !supported_source_extension(path) {
            continue;
        }
        let size = entry.size();
        require(size <= MAX_SOURCE_BYTES, "SOURCE_FILE_SIZE_LIMIT")?;
        let mut data = Vec::new();
        (&mut entry)
            .take(size + 1)
            .read_to_end(&mut data)
            .map_err(|_| "SOURCE_ENTRY_READ_FAILED")?;
        require(data.len() as u64 == size, "SOURCE_ENTRY_SIZE_MISMATCH")?;
        let text = String::from_utf8(data).map_err(|_| "SOURCE_TEXT_ENCODING")?;
        sources.insert(name.to_owned(), text.trim_start_matches('\u{feff}').to_owned());
    }
    require(!sources.is_empty(), "SOURCE_FILES_MISSING")?;
    Ok(sources)
}

fn attach(
    run: &Value,
    paths: &BTreeMap<String, PathBuf>,
    result: &mut CanonicalResultV11,
) -> SourceResult<Value> {
    let Some(build_id) = result.build_resolution.resolved_build_id.as_deref() else {
        return Ok(json!({"status":"not_applicable","attached_frames":0}));
    };
    let bundles = run["policy_snapshots"]["source_policy"]["bundles"].as_array().unwrap();
    let candidates = bundles.iter().filter(|b| b["build_id"] == build_id).collect::<Vec<_>>();
    let Some(first) = candidates.first() else {
        return Ok(json!({"status":"not_applicable","attached_frames":0}));
    };
    require(
        candidates.iter().all(|b| {
            b["sha256"] == first["sha256"]
                && b["size"] == first["size"]
                && b["descriptor"] == first["descriptor"]
        }),
        "SOURCE_BUNDLE_CONFLICT",
    )?;
    let build = run["policy_snapshots"]["build_snapshot"]["builds"]
        .as_array()
        .unwrap()
        .iter()
        .find(|b| b["build_id"] == build_id)
        .ok_or("SOURCE_BUILD_MISSING")?;
    require(
        build["manifest"]["source_bundle"] == first["descriptor"],
        "SOURCE_POLICY_BUILD_MISMATCH",
    )?;
    let mut loaded = None;
    let mut failure = "SOURCE_ARCHIVE_UNAVAILABLE";
    for bundle in &candidates {
        let id = bundle["artifact_id"].as_str().unwrap();
        if let Some(path) = paths.get(id) {
            match read_archive(
                path,
                bundle["sha256"].as_str().unwrap(),
                bundle["size"].as_u64().unwrap(),
            ) {
                Ok(sources) => {
                    loaded = Some((id.to_owned(), sources));
                    break;
                }
                Err(code) => failure = code,
            }
        }
    }
    let (artifact_id, sources) = loaded.ok_or(failure)?;
    let names = sources.keys().cloned().collect::<Vec<_>>();
    let descriptor = &first["descriptor"];
    let mut prefixes = vec![descriptor["source_root"].as_str().unwrap().to_owned()];
    if let Some(extra) = descriptor["strip_prefixes"].as_array() {
        prefixes.extend(extra.iter().map(|v| v.as_str().unwrap().to_owned()));
    }
    let context_lines = descriptor["context_lines"].as_u64().unwrap_or(3).min(10) as usize;
    let allowed = result
        .modules
        .iter()
        .filter(|module| {
            build["verified_modules"].as_array().unwrap().iter().any(|local| {
                local["identity"] == serde_json::to_value(&module.selection.identity).unwrap()
                    && module.selection.selected_pair_id.as_ref().is_some_and(|pair| {
                        local["verified_pair_ids"].as_array().unwrap().iter().any(|v| v == pair)
                    })
            })
        })
        .map(|m| m.module_index)
        .collect::<BTreeSet<_>>();
    let mut additions = Vec::new();
    let mut output_bytes = 0usize;
    let mut scanned_bytes = 0usize;
    for (ti, thread) in result.threads.iter().enumerate() {
        for (fi, frame) in thread.frames.iter().enumerate() {
            if !frame.module_index.is_some_and(|index| allowed.contains(&index)) {
                continue;
            }
            let (Some(file), Some(line)) = (frame.frame.file.as_deref(), frame.frame.line) else {
                continue;
            };
            if line == 0 {
                continue;
            }
            let Some(name) = resolve_entry(&names, file, &prefixes) else {
                continue;
            };
            scanned_bytes += sources[name].len();
            require(scanned_bytes <= MAX_TEXT_SCAN_BYTES, "SOURCE_TEXT_WORK_LIMIT")?;
            let lines = sources[name].lines().collect::<Vec<_>>();
            let index = usize::try_from(line - 1).map_err(|_| "SOURCE_LINE_RANGE")?;
            if index >= lines.len() {
                continue;
            }
            let clip = |value: &&str| value.chars().take(1000).collect::<String>();
            let context = SourceContext {
                pre: lines[index.saturating_sub(context_lines)..index].iter().map(clip).collect(),
                line: clip(&lines[index]),
                post: lines[index + 1..lines.len().min(index + 1 + context_lines)]
                    .iter()
                    .map(clip)
                    .collect(),
            };
            output_bytes += context.pre.iter().chain(&context.post).map(String::len).sum::<usize>()
                + context.line.len();
            require(output_bytes <= MAX_CONTEXT_BYTES, "SOURCE_CONTEXT_SIZE_LIMIT")?;
            additions.push((ti, fi, context));
        }
    }
    let attached = additions.len();
    for (ti, fi, context) in additions {
        result.threads[ti].frames[fi].frame.source_context = Some(context);
    }
    Ok(json!({"status":"attached","artifact_id":artifact_id,"archive_sha256":first["sha256"],
        "source_entry_count":sources.len(),"attached_frames":attached}))
}

pub fn enrich(
    run: &Value,
    paths: &BTreeMap<String, PathBuf>,
    result: &mut CanonicalResultV11,
) -> Value {
    let mut diagnostic = match attach(run, paths, result) {
        Ok(value) => value,
        Err(code) => {
            result.quality.warnings.push(source_context_warning(code));
            json!({"status":"unavailable","failure_code":code,"attached_frames":0})
        }
    };
    diagnostic["schema_version"] = json!("frozen-source-bundle-v1");
    diagnostic
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use zip::write::SimpleFileOptions;
    use zip::{CompressionMethod, ZipWriter};

    fn archive(files: &[(&str, &[u8])], method: CompressionMethod) -> Vec<u8> {
        let mut writer = ZipWriter::new(Cursor::new(Vec::new()));
        for (name, bytes) in files {
            writer
                .start_file(*name, SimpleFileOptions::default().compression_method(method))
                .unwrap();
            writer.write_all(bytes).unwrap();
        }
        writer.finish().unwrap().into_inner()
    }

    #[test]
    fn reads_actual_stored_deflated_utf8_and_bom_bytes() {
        for method in
            [CompressionMethod::Stored, CompressionMethod::Deflated, CompressionMethod::Bzip2]
        {
            let bytes = archive(&[("src/示例.cpp", b"\xef\xbb\xbfline one\nline two\n")], method);
            let sources = decode_archive(&bytes).unwrap();
            assert_eq!(sources["src/示例.cpp"], "line one\nline two\n");
        }
    }

    #[test]
    fn frozen_archive_hash_and_size_are_checked_before_parsing() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("source.zip");
        let bytes = archive(&[("a.cpp", b"actual text")], CompressionMethod::Stored);
        fs::write(&path, &bytes).unwrap();
        assert_eq!(
            read_archive(&path, &"0".repeat(64), bytes.len() as u64),
            Err("SOURCE_ARCHIVE_HASH_MISMATCH")
        );
        assert_eq!(
            read_archive(&path, &sha256_hex(&bytes), bytes.len() as u64 + 1),
            Err("SOURCE_ARCHIVE_SIZE_MISMATCH")
        );
        assert_eq!(
            read_archive(&path, &sha256_hex(&bytes), bytes.len() as u64).unwrap()["a.cpp"],
            "actual text"
        );
        assert_eq!(
            read_archive(&root.path().join("missing.zip"), &sha256_hex(&bytes), bytes.len() as u64),
            Err("SOURCE_ARCHIVE_UNAVAILABLE")
        );
    }

    #[test]
    fn rejects_unsafe_duplicate_and_nested_paths() {
        for name in ["../a.cpp", "a/../a.cpp", "/a.cpp", "C:/a.cpp", "a\\b.cpp"] {
            let bytes = archive(&[(name, b"text")], CompressionMethod::Stored);
            assert_eq!(decode_archive(&bytes), Err("SOURCE_PATH_UNSAFE"), "{name}");
        }
        let bytes = archive(&[("a.cpp", b"one"), ("A.CPP", b"two")], CompressionMethod::Stored);
        assert_eq!(decode_archive(&bytes), Err("SOURCE_PATH_DUPLICATE"));
        let bytes =
            archive(&[("a.cpp", b"one"), ("hidden.zip", b"two")], CompressionMethod::Stored);
        assert_eq!(decode_archive(&bytes), Err("SOURCE_NESTED_ARCHIVE"));
    }

    #[test]
    fn rejects_invalid_utf8_and_crc_damage() {
        let bytes = archive(&[("a.cpp", &[0xff, 0xfe, 0xfd])], CompressionMethod::Stored);
        assert_eq!(decode_archive(&bytes), Err("SOURCE_TEXT_ENCODING"));
        let mut bytes = archive(&[("a.cpp", b"unique original source")], CompressionMethod::Stored);
        let start =
            bytes.windows(22).position(|window| window == b"unique original source").unwrap();
        bytes[start] ^= 1;
        assert_eq!(decode_archive(&bytes), Err("SOURCE_ENTRY_READ_FAILED"));
    }

    #[test]
    fn size_ratio_and_central_index_budgets_fail_closed() {
        let huge = vec![b'x'; MAX_SOURCE_BYTES as usize + 1];
        let bytes = archive(&[("large.cpp", &huge)], CompressionMethod::Stored);
        assert_eq!(decode_archive(&bytes), Err("SOURCE_FILE_SIZE_LIMIT"));
        let bytes = archive(&[("ratio.cpp", &huge[..1024 * 1024])], CompressionMethod::Deflated);
        assert_eq!(decode_archive(&bytes), Err("SOURCE_COMPRESSION_RATIO"));
        let mut bytes = archive(&[("a.cpp", b"text")], CompressionMethod::Stored);
        let end = bytes.len() - 22;
        bytes[end + 10..end + 12].copy_from_slice(&20_001u16.to_le_bytes());
        assert_eq!(decode_archive(&bytes), Err("SOURCE_ZIP_ENTRY_LIMIT"));
        bytes[end + 10..end + 12].copy_from_slice(&1u16.to_le_bytes());
        bytes[end + 12..end + 16].copy_from_slice(&((MAX_INDEX_BYTES + 1) as u32).to_le_bytes());
        assert_eq!(decode_archive(&bytes), Err("SOURCE_ZIP_INDEX_LIMIT"));
    }

    #[test]
    fn lzma_dictionary_is_bounded_before_decoder_allocation() {
        // Python zipfile ZIP_LZMA, a.cpp = two lines of source text.
        let mut bytes = hex::decode(concat!(
            "504b03043f0002000e00ac05245d7855d8ed290000002000000005000000612e637070",
            "090405005d0000800000399bcb11efec3fd9c1e407de62e573004d84e8b610b0dfa9d253fff9a68000",
            "504b01023f003f0002000e00ac05245d7855d8ed2900000020000000050000000000000000000000800100000000612e637070",
            "504b05060000000001000100330000004c0000000000"
        )).unwrap();
        assert_eq!(decode_archive(&bytes).unwrap()["a.cpp"], "source line one\nsource line two\n");
        bytes[40..44].copy_from_slice(&u32::MAX.to_le_bytes());
        assert_eq!(decode_archive(&bytes), Err("SOURCE_LZMA_DICTIONARY_LIMIT"));
    }
}
