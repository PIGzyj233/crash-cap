from __future__ import annotations

import importlib.util
import shutil
import tarfile
from pathlib import Path
from types import ModuleType

import pytest
from crashcap_api.config import Settings


def _load_backup_module() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "symbolicator"
        / "seed_database_zstd_source.py"
    )
    spec = importlib.util.spec_from_file_location("pdb_storage_backup_helper", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load PDB storage backup helper")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _object_files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_checksummed_object_backup_restores_exact_files(tmp_path: Path) -> None:
    helper = _load_backup_module()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    helper.BACKUP_ROOT = evidence
    source_settings = Settings.for_test(tmp_path / "source")
    source_store = helper.require_local_store(source_settings)
    source_store.put_bytes("artifact-blob-payloads/a/payload.zst", b"zstd-a", "application/zstd")
    source_store.put_bytes("artifact-blob-payloads/b/payload.zst", b"zstd-b", "application/zstd")
    archive = evidence / "blob-objects.tar"

    backup = helper.backup_objects(source_settings, archive)

    restored_settings = Settings.for_test(tmp_path / "restored")
    restore = helper.restore_objects(restored_settings, archive)
    restored_store = helper.require_local_store(restored_settings)
    assert backup["format"] == "artifact-blob-object-backup-v1"
    assert backup["object_count"] == restore["object_count"] == 2
    assert backup["total_bytes"] == restore["total_bytes"]
    assert _object_files(restored_store.root) == _object_files(source_store.root)


def test_tampered_object_backup_is_failure_atomic(tmp_path: Path) -> None:
    helper = _load_backup_module()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    helper.BACKUP_ROOT = evidence
    source_settings = Settings.for_test(tmp_path / "source")
    source_store = helper.require_local_store(source_settings)
    source_store.put_bytes("artifact-blob-payloads/a/payload.zst", b"zstd-a", "application/zstd")
    source_store.put_bytes("artifact-blob-payloads/b/payload.zst", b"zstd-b", "application/zstd")
    archive = evidence / "blob-objects.tar"
    corrupt_archive = evidence / "blob-objects-corrupt.tar"
    helper.backup_objects(source_settings, archive)
    shutil.copyfile(archive, corrupt_archive)
    with tarfile.open(corrupt_archive, "r:") as bundle:
        member = next(item for item in bundle.getmembers() if item.name.startswith("objects/"))
        offset = member.offset_data + member.size // 2
    with corrupt_archive.open("r+b") as handle:
        handle.seek(offset)
        value = handle.read(1)
        handle.seek(offset)
        handle.write(bytes([value[0] ^ 1]))

    restored_settings = Settings.for_test(tmp_path / "restored")
    with pytest.raises(RuntimeError, match="SHA-256 verification"):
        helper.restore_objects(restored_settings, corrupt_archive)

    restored_store = helper.require_local_store(restored_settings)
    assert _object_files(restored_store.root) == {}


@pytest.mark.parametrize("key", [".", "a/./b", "a//b", "../a", "/absolute", "a\\b"])
def test_backup_manifest_rejects_noncanonical_object_keys(key: str) -> None:
    helper = _load_backup_module()
    with pytest.raises(ValueError, match="unsafe object path"):
        helper.safe_object_key(key)
