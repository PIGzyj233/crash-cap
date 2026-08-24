from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, cast

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


def stage_source_bundles(
    store: ObjectStore,
    context: dict[str, Any],
    task_dir: Path,
) -> dict[str, Any]:
    """Materialize immutable bundles and add an ephemeral, Core-verifiable manifest."""

    staged = cast(dict[str, Any], json.loads(json.dumps(context)))
    inputs = staged.get("inputs")
    if not isinstance(inputs, dict):
        raise SourceBundleError("analysis context has no inputs object")
    bundles = inputs.get("source_bundles") or []
    if not isinstance(bundles, list):
        raise SourceBundleError("analysis context source_bundles must be a list")
    runtime_bundles: list[dict[str, Any]] = []
    bundle_root = task_dir / "source-bundles"
    bundle_root.mkdir(parents=True, exist_ok=True)
    for bundle in bundles:
        if not isinstance(bundle, dict):
            raise SourceBundleError("analysis context source bundle is not an object")
        artifact_id = bundle.get("artifact_id")
        object_key = bundle.get("object_key")
        if (
            not isinstance(artifact_id, str)
            or not artifact_id
            or not all(character.isalnum() or character in "_-" for character in artifact_id)
            or not isinstance(object_key, str)
        ):
            raise SourceBundleError("analysis context source bundle identity is invalid")
        archive_relative = PurePosixPath("source-bundles", f"{artifact_id}.zip")
        archive_path = task_dir / Path(*archive_relative.parts)
        store.download_file(object_key, archive_path)
        digest, size = _file_sha256(archive_path)
        expected_digest = str(bundle.get("sha256") or "").lower()
        expected_size = bundle.get("size")
        if digest != expected_digest:
            raise SourceBundleError("staged source bundle SHA-256 does not match Run context")
        if not isinstance(expected_size, int) or size != expected_size:
            raise SourceBundleError("staged source bundle size does not match Run context")

        metadata = inspect_source_bundle(archive_path)
        expected_metadata = bundle.get("ingest_metadata")
        if not isinstance(expected_metadata, dict):
            raise SourceBundleError("source bundle has no frozen ingest metadata")
        for key in (
            "policy_version",
            "entry_count",
            "source_entry_count",
            "uncompressed_size",
            "source_entries",
        ):
            if metadata.get(key) != expected_metadata.get(key):
                raise SourceBundleError(
                    f"source bundle {key} differs from frozen ingest metadata"
                )

        extracted_relative = PurePosixPath("source-bundles", artifact_id)
        extracted_root = task_dir / Path(*extracted_relative.parts)
        extracted_root.mkdir(parents=True, exist_ok=True)
        entries: list[dict[str, Any]] = []
        with zipfile.ZipFile(archive_path) as archive:
            for raw_name in metadata["source_entries"]:
                info = archive.getinfo(raw_name)
                entry = _safe_entry(info)
                if entry is None:
                    raise SourceBundleError("source bundle manifest unexpectedly names a directory")
                payload = archive.read(info)
                if len(payload) != info.file_size:
                    raise SourceBundleError("source bundle entry size changed during extraction")
                destination = extracted_root / Path(*entry.parts)
                resolved_root = extracted_root.resolve()
                resolved_destination = destination.resolve()
                if resolved_root not in resolved_destination.parents:
                    raise SourceBundleError("source bundle entry escaped the staged root")
                resolved_destination.parent.mkdir(parents=True, exist_ok=True)
                resolved_destination.write_bytes(payload)
                entries.append(
                    {
                        "path": entry.as_posix(),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                        "size": len(payload),
                    }
                )
        runtime = dict(bundle)
        runtime.update(
            {
                "archive_path": archive_relative.as_posix(),
                "extracted_root": extracted_relative.as_posix(),
                "entries": entries,
            }
        )
        runtime_bundles.append(runtime)
    inputs["source_bundles"] = runtime_bundles
    return staged


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def attach_staged_source_context(
    canonical: dict[str, Any],
    runtime_context: dict[str, Any],
    task_dir: Path,
) -> int:
    """Python fake-Core equivalent of the Rust Core's defensive enrichment."""

    inputs = runtime_context.get("inputs") or {}
    if inputs.get("source_bundle_error"):
        raise SourceBundleError(str(inputs["source_bundle_error"]))
    resolved_build_id = canonical.get("build_resolution", {}).get("resolved_build_id")
    candidates = [
        bundle
        for bundle in inputs.get("source_bundles", [])
        if bundle.get("build_id") == resolved_build_id
    ]
    if not candidates:
        return 0
    bundle = candidates[-1]
    if bundle.get("ingest_metadata", {}).get("policy_version") != "source-bundle-v1.0":
        raise SourceBundleError("unsupported source bundle policy version")
    root_relative = PurePosixPath(str(bundle.get("extracted_root") or ""))
    if root_relative.is_absolute() or ".." in root_relative.parts:
        raise SourceBundleError("staged source root is unsafe")
    root = (task_dir / Path(*root_relative.parts)).resolve()
    entries = bundle.get("entries") or []
    names = [str(entry.get("path")) for entry in entries]
    entry_by_name = {str(entry.get("path")): entry for entry in entries}
    config = bundle.get("source_bundle_config") or {}
    context_lines = max(0, min(int(config.get("context_lines", 3)), 10))
    prefixes = [str(config.get("source_root", "")), *map(str, config.get("strip_prefixes", []))]
    attached = 0
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
            name = _resolve_entry(names, frame_file, prefixes)
            if name is None:
                continue
            entry = entry_by_name[name]
            relative = PurePosixPath(name)
            if relative.is_absolute() or ".." in relative.parts or "\\" in name:
                raise SourceBundleError("staged source entry path is unsafe")
            path = (root / Path(*relative.parts)).resolve()
            if root not in path.parents:
                raise SourceBundleError("staged source entry escaped its root")
            digest, size = _file_sha256(path)
            if digest != entry.get("sha256") or size != entry.get("size"):
                raise SourceBundleError("staged source entry differs from its runtime manifest")
            try:
                source = path.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
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
