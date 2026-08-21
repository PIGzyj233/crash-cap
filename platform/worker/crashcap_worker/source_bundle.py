from __future__ import annotations

import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from crashcap_api.storage import ObjectStore

MAX_ENTRIES = 20_000
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 2 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
SOURCE_EXTENSIONS = frozenset(
    {".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".ipp", ".m", ".mm", ".rs"}
)
NESTED_ARCHIVE_EXTENSIONS = frozenset({".zip", ".7z", ".rar", ".tar", ".gz", ".bz2", ".xz"})


class SourceBundleError(ValueError):
    pass


def _safe_entry(info: zipfile.ZipInfo) -> PurePosixPath | None:
    raw = info.filename
    if "\\" in raw or "\x00" in raw:
        raise SourceBundleError("source bundle entry uses an unsafe separator or NUL")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or any(":" in part for part in path.parts)
    ):
        raise SourceBundleError("source bundle entry escapes its relative root")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise SourceBundleError("source bundle symlinks are not accepted")
    if info.flag_bits & 0x1:
        raise SourceBundleError("encrypted source bundle entries are not accepted")
    if any(ord(character) > 127 for character in raw) and not info.flag_bits & 0x800:
        raise SourceBundleError("non-ASCII source bundle paths must carry the UTF-8 flag")
    if info.is_dir():
        return None
    if path.suffix.casefold() in NESTED_ARCHIVE_EXTENSIONS:
        raise SourceBundleError("nested archives are not accepted in source bundles")
    return path


def inspect_source_bundle(path: Path) -> dict[str, Any]:
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        raise SourceBundleError("source bundle is not a valid ZIP archive") from error
    with archive:
        entries: list[str] = []
        source_entries: list[str] = []
        normalized_entries: set[str] = set()
        total_uncompressed = 0
        for info in archive.infolist():
            entry = _safe_entry(info)
            if entry is None:
                continue
            entries.append(entry.as_posix())
            folded = entry.as_posix().casefold()
            if folded in normalized_entries:
                raise SourceBundleError("source bundle contains duplicate normalized paths")
            normalized_entries.add(folded)
            if len(entries) > MAX_ENTRIES:
                raise SourceBundleError("source bundle exceeds the 20000 entry limit")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise SourceBundleError("source bundle exceeds the 512MiB uncompressed limit")
            if info.file_size and info.compress_size == 0:
                raise SourceBundleError("source bundle entry has an invalid compression size")
            if info.compress_size and info.file_size / info.compress_size > MAX_COMPRESSION_RATIO:
                raise SourceBundleError("source bundle exceeds the 100:1 compression-ratio limit")
            if entry.suffix.casefold() in SOURCE_EXTENSIONS:
                if info.file_size > MAX_SOURCE_FILE_BYTES:
                    raise SourceBundleError("individual source file exceeds the 2MiB context limit")
                source_entries.append(entry.as_posix())
        if not source_entries:
            raise SourceBundleError("source bundle contains no supported source files")
        return {
            "policy_version": "source-bundle-v1.0",
            "entry_count": len(entries),
            "source_entry_count": len(source_entries),
            "uncompressed_size": total_uncompressed,
            "source_entries": sorted(source_entries),
        }


def _normalize_symbol_path(value: str, prefixes: list[str]) -> str:
    normalized = value.replace("\\", "/")
    folded = normalized.casefold()
    for prefix in sorted(prefixes, key=len, reverse=True):
        candidate = prefix.replace("\\", "/").rstrip("/") + "/"
        if folded.startswith(candidate.casefold()):
            return normalized[len(candidate) :].lstrip("/")
    if len(normalized) >= 3 and normalized[1:3] == ":/":
        normalized = normalized[3:]
    return normalized.lstrip("/")


def _resolve_entry(names: list[str], frame_file: str, prefixes: list[str]) -> str | None:
    wanted = _normalize_symbol_path(frame_file, prefixes).casefold()
    exact = [name for name in names if name.casefold() == wanted]
    if len(exact) == 1:
        return exact[0]
    suffix = [name for name in names if name.casefold().endswith("/" + wanted)]
    if len(suffix) == 1:
        return suffix[0]
    basename = PurePosixPath(wanted).name
    basename_matches = [name for name in names if PurePosixPath(name.casefold()).name == basename]
    return basename_matches[0] if len(basename_matches) == 1 else None


def attach_source_context(
    store: ObjectStore,
    canonical: dict[str, Any],
    run_spec: dict[str, Any],
    task_dir: Path,
) -> int:
    resolved_build_id = canonical.get("build_resolution", {}).get("resolved_build_id")
    if not resolved_build_id:
        return 0
    candidates = [
        artifact
        for artifact in run_spec.get("artifacts", [])
        if artifact.get("kind") == "source_bundle"
        and artifact.get("build_id") == resolved_build_id
        and artifact.get("ingest_metadata", {}).get("policy_version") == "source-bundle-v1.0"
    ]
    if not candidates:
        return 0
    artifact = candidates[-1]
    destination = task_dir / "source-bundle.zip"
    store.download_file(artifact["object_key"], destination)
    metadata = inspect_source_bundle(destination)
    config = artifact.get("source_bundle_config") or {}
    context_lines = max(0, min(int(config.get("context_lines", 3)), 10))
    prefixes = [str(config.get("source_root", "")), *map(str, config.get("strip_prefixes", []))]
    names = list(metadata["source_entries"])
    attached = 0
    with zipfile.ZipFile(destination) as archive:
        for thread in canonical.get("threads", []):
            for frame in thread.get("frames", []):
                frame_file = frame.get("file")
                line_number = frame.get("line")
                if (
                    not isinstance(frame_file, str)
                    or not isinstance(line_number, int)
                    or line_number < 1
                ):
                    continue
                entry = _resolve_entry(names, frame_file, prefixes)
                if entry is None:
                    continue
                try:
                    source = archive.read(entry).decode("utf-8-sig")
                except (KeyError, UnicodeDecodeError):
                    continue
                lines = source.splitlines()
                if line_number > len(lines):
                    continue
                index = line_number - 1

                def clip(value: str) -> str:
                    return value[:1000]

                frame["source_context"] = {
                    "pre": [clip(value) for value in lines[max(0, index - context_lines) : index]],
                    "line": clip(lines[index]),
                    "post": [clip(value) for value in lines[index + 1 : index + 1 + context_lines]],
                }
                attached += 1
    return attached
