"""Cross-check the Phase 1 HTTP-only transport boundary."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load_script(name: str, relative: str) -> ModuleType:
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


deploy_check = _load_script("phase1_deploy_check_http", "scripts/phase1/deploy_check.py")
storage_init = _load_script("phase1_ops_storage_init_http", "scripts/phase1/ops_storage_init.py")
emergency_delete = _load_script(
    "phase1_ops_emergency_delete_http", "scripts/phase1/ops_emergency_delete.py"
)


def test_all_operator_helpers_enforce_the_same_plain_http_contract() -> None:
    validators = (
        deploy_check.is_plain_http_endpoint,
        storage_init.plain_http_endpoint,
        emergency_delete.plain_http_endpoint,
    )

    for validator in validators:
        assert validator("http://rustfs:9000")
        assert validator("http://127.0.0.1:59000/path")

        for invalid in (
            "https://rustfs:9000",
            "rustfs:9000",
            "http:///missing-host",
            "http://user:secret@rustfs:9000",
            "http://rustfs:9000?token=secret",
            "http://rustfs:9000#fragment",
        ):
            assert not validator(invalid)


def test_storage_bootstrap_requires_exact_http_cors_origins() -> None:
    assert storage_init.parse_cors_allowed_origins(
        "http://crashcap.intranet.example, http://127.0.0.1:30080/"
    ) == ["http://crashcap.intranet.example", "http://127.0.0.1:30080"]

    for invalid in (
        "",
        "https://crashcap.intranet.example",
        "http://*.intranet.example",
        "http://user:secret@crashcap.intranet.example",
        "http://crashcap.intranet.example/web",
        "http://crashcap.intranet.example?token=secret",
    ):
        try:
            storage_init.parse_cors_allowed_origins(invalid)
        except ValueError:
            pass
        else:  # pragma: no cover - keeps the failure message precise
            raise AssertionError(f"invalid CORS origin was accepted: {invalid!r}")


def test_backup_restore_script_has_no_tls_or_ca_input_contract() -> None:
    script = (ROOT / "scripts" / "phase1" / "ops_backup_restore.sh").read_text(encoding="utf-8")

    assert "S3_CA_BUNDLE" not in script
    assert "must use http://" in script
    assert "https://" not in script


def test_backup_restore_script_checksums_every_mirrored_object_before_restore() -> None:
    script = (ROOT / "scripts" / "phase1" / "ops_backup_restore.sh").read_text(encoding="utf-8")

    assert "backup target already exists; choose a new empty path" in script
    assert "find postgres.dump phase1.yml rustfs -type f -print0" in script
    assert "LC_ALL=C sort -z" in script
    assert "xargs -0 sha256sum > checksums.sha256" in script
    assert script.index("sha256sum -c checksums.sha256") < script.index("pg_restore --clean")


def _bash_path(path: Path) -> str:
    if os.name != "nt":
        return str(path)
    cygpath = shutil.which("cygpath")
    if cygpath is None:
        pytest.skip("Git Bash cygpath is required for the shell integration test")
    return subprocess.run(  # noqa: S603 - resolved local cygpath executable
        [cygpath, "-u", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def test_backup_script_manifest_is_relocatable_and_blocks_corruption_before_restore(
    tmp_path: Path,
) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for the operator backup integration test")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_s3 = tmp_path / "fake-s3"
    fake_s3.mkdir()
    (fake_s3 / "pdb.zst").write_bytes(b"pdb-zstd-payload")
    (fake_s3 / "pe.zst").write_bytes(b"pe-zstd-payload")
    restore_marker = tmp_path / "pg-restore-called"
    _write_executable(
        fake_bin / "pg_dump",
        """#!/usr/bin/env bash
set -eu
while [ "$#" -gt 0 ]; do
  if [ "$1" = "--file" ]; then
    shift
    printf 'postgres-custom-dump' > "$1"
    exit 0
  fi
  shift
done
exit 2
""",
    )
    _write_executable(
        fake_bin / "pg_restore",
        """#!/usr/bin/env bash
set -eu
printf 'called' > "$FAKE_RESTORE_MARKER"
""",
    )
    _write_executable(
        fake_bin / "aws",
        """#!/usr/bin/env bash
set -eu
destination=''
for argument in "$@"; do
  case "$argument" in
    */rustfs/) destination=$argument ;;
  esac
done
if [ -n "$destination" ]; then
  mkdir -p "$destination/artifact-blob-payloads/a" "$destination/artifact-blob-payloads/b"
  cp "$FAKE_S3_SOURCE/pdb.zst" "$destination/artifact-blob-payloads/a/payload.zst"
  cp "$FAKE_S3_SOURCE/pe.zst" "$destination/artifact-blob-payloads/b/payload.zst"
fi
""",
    )
    password = tmp_path / "pg-password"
    access_key = tmp_path / "s3-access-key"
    secret_key = tmp_path / "s3-secret-key"
    password.write_text("postgres-password", encoding="utf-8")
    access_key.write_text("access-key", encoding="utf-8")
    secret_key.write_text("secret-key", encoding="utf-8")
    backup = tmp_path / "backup"
    script = ROOT / "scripts" / "phase1" / "ops_backup_restore.sh"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{_bash_path(fake_bin)}:{environment['PATH']}",
            "PGHOST": "postgres",
            "PGPORT": "5432",
            "PGDATABASE": "crashcap",
            "PGUSER": "crashcap",
            "PG_PASSWORD_FILE": _bash_path(password),
            "S3_ENDPOINT": "http://rustfs:9000",
            "S3_BUCKET": "crashcap-private",
            "S3_REGION": "us-east-1",
            "S3_ACCESS_KEY_FILE": _bash_path(access_key),
            "S3_SECRET_KEY_FILE": _bash_path(secret_key),
            "FAKE_S3_SOURCE": _bash_path(fake_s3),
            "FAKE_RESTORE_MARKER": _bash_path(restore_marker),
        }
    )
    backup_result = subprocess.run(  # noqa: S603 - fixed repository shell test command
        [bash, _bash_path(script), "backup", _bash_path(backup)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert backup_result.returncode == 0, backup_result.stderr
    checksum_names = {
        line[64:].lstrip(" *")
        for line in (backup / "checksums.sha256").read_text(encoding="utf-8").splitlines()
        if line
    }
    assert checksum_names == {
        "phase1.yml",
        "postgres.dump",
        "rustfs/artifact-blob-payloads/a/payload.zst",
        "rustfs/artifact-blob-payloads/b/payload.zst",
    }
    duplicate = subprocess.run(  # noqa: S603 - fixed repository shell test command
        [bash, _bash_path(script), "backup", _bash_path(backup)],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert duplicate.returncode != 0
    assert "backup target already exists" in duplicate.stderr

    (backup / "rustfs" / "artifact-blob-payloads" / "a" / "payload.zst").write_bytes(b"corrupted")
    restore = subprocess.run(  # noqa: S603 - fixed repository shell test command
        [
            bash,
            _bash_path(script),
            "restore",
            _bash_path(backup),
            "--confirm",
            f"RESTORE {_bash_path(backup)}",
        ],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert restore.returncode != 0
    assert "FAILED" in restore.stdout
    assert not restore_marker.exists()
