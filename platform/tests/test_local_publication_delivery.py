from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools" / "crashcap"


def test_release_metadata_and_checksums_cover_fixed_unified_cli_paths() -> None:
    release = json.loads((TOOLS / "release.json").read_text(encoding="utf-8"))
    assert release["tool"] == "crashcap"
    artifacts = {item["path"]: item for item in release["artifacts"]}
    assert set(artifacts) == {
        "linux-x86_64/crashcap",
        "windows-x86_64/crashcap.exe",
    }
    checksum_rows = {
        path: digest
        for digest, path in (
            line.split(maxsplit=1)
            for line in (TOOLS / "SHA256SUMS").read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    }
    assert set(checksum_rows) == set(artifacts)
    for relative_path, metadata in artifacts.items():
        payload = (TOOLS / relative_path).read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        assert actual == checksum_rows[relative_path] == metadata["sha256"]

    signing = release["signing"]
    assert signing["required_before_general_availability"] is True
    if signing["status"] == "unsigned-pilot":
        assert signing["windows_signed_sha256"] is None
        assert signing["certificate_thumbprint"] is None
    else:
        assert signing["status"] == "authenticode-signed"
        assert (
            signing["windows_signed_sha256"] == artifacts["windows-x86_64/crashcap.exe"]["sha256"]
        )
        assert signing["certificate_thumbprint"]


def test_frontend_download_location_is_not_served_by_spa_fallback() -> None:
    dockerfile = (ROOT / "platform" / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    nginx = (ROOT / "platform" / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert "tools/crashcap/ /usr/share/nginx/html/downloads/crashcap/" in dockerfile
    download_location = nginx.index("location ^~ /downloads/crashcap/")
    spa_location = nginx.index("location / {")
    assert download_location < spa_location
    download_block = nginx[download_location:spa_location]
    assert "try_files $uri =404;" in download_block
    assert "autoindex off;" in download_block
    assert "/index.html" not in download_block


def test_feature_flag_and_ci_templates_default_to_safe_unified_flow() -> None:
    compose = (ROOT / "deploy" / "compose" / "phase1.yml").read_text(encoding="utf-8")
    gitlab = (ROOT / ".gitlab" / "ci" / "crashcap.yml").read_text(encoding="utf-8")
    github = (ROOT / ".github" / "workflows" / "phase2-build-publish.yml").read_text(
        encoding="utf-8"
    )
    assert "CRASHCAP_BUILD_PUBLICATIONS_ENABLED:-false" in compose
    for template in (gitlab, github):
        assert "tools/crashcap/windows-x86_64/crashcap.exe" in template
        assert "--origin ci" in template
        assert "crashcap-ci" not in template
