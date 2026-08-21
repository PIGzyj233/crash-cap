"""PILOT-01 deployment and bucket-policy regression tests."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

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


deploy_check = _load_script("phase1_deploy_check_gateway", "scripts/phase1/deploy_check.py")
storage_init = _load_script("phase1_storage_init_gateway", "scripts/phase1/ops_storage_init.py")


def test_gateway_config_preserves_sigv4_transport_without_logging_query() -> None:
    config = (ROOT / "deploy" / "s3-gateway" / "nginx.conf").read_text(encoding="utf-8")

    assert deploy_check.gateway_config_violations(config) == []
    assert "proxy_pass http://rustfs:9000;" in config
    assert "proxy_pass http://rustfs:9000/" not in config
    assert "$remote_addr" not in config


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ("proxy_request_buffering off;", "proxy_request_buffering on;", "missing proxy_request"),
        ("client_max_body_size 256m;", "client_max_body_size 257m;", "missing client_max"),
        ("$uri host=$http_host", "$request_uri host=$http_host", "presigned query"),
        ("$request_method $uri", "$remote_addr $request_method $uri", "only method"),
        ("listen 9000;", "listen 9000 ssl;", "HTTP-only"),
    ],
)
def test_gateway_config_contract_rejects_unsafe_changes(old: str, new: str, expected: str) -> None:
    config = (ROOT / "deploy" / "s3-gateway" / "nginx.conf").read_text(encoding="utf-8")
    violations = deploy_check.gateway_config_violations(config.replace(old, new))

    assert any(expected in violation for violation in violations)


def test_gateway_bind_and_cors_parsers_are_exact() -> None:
    env: dict[str, str] = {}
    assert deploy_check.parse_published_port(
        ["${CRASHCAP_EXTERNAL_BIND_HOST:-127.0.0.1}:${PHASE1_S3_GATEWAY_PORT:-59000}:9000"],
        env,
    ) == ("127.0.0.1", 59000, 9000)
    assert deploy_check.exact_http_origins("http://127.0.0.1:30080") == ["http://127.0.0.1:30080"]
    assert deploy_check.exact_http_origins("http://*.example.test") == []
    assert deploy_check.exact_http_origins("https://127.0.0.1:30080") == []


class RecordingS3Client:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def put_bucket_acl(self, **kwargs: Any) -> None:
        self.calls.append(("acl", kwargs))

    def put_bucket_encryption(self, **kwargs: Any) -> None:
        self.calls.append(("encryption", kwargs))

    def put_bucket_cors(self, **kwargs: Any) -> None:
        self.calls.append(("cors", kwargs))


def test_storage_policy_is_exact_and_idempotently_reapplied() -> None:
    client = RecordingS3Client()
    origins = ["http://127.0.0.1:30080"]

    storage_init.apply_bucket_policy(client, "crashcap-private", origins)
    storage_init.apply_bucket_policy(client, "crashcap-private", origins)

    assert [name for name, _ in client.calls] == [
        "acl",
        "encryption",
        "cors",
        "acl",
        "encryption",
        "cors",
    ]
    cors = client.calls[2][1]["CORSConfiguration"]["CORSRules"][0]
    assert cors == {
        "AllowedOrigins": origins,
        "AllowedMethods": ["GET", "HEAD", "PUT"],
        "AllowedHeaders": ["*"],
        "ExposeHeaders": ["ETag"],
        "MaxAgeSeconds": 300,
    }


def _run_deploy_check(
    compose_text: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    **environment: str,
) -> dict[str, Any]:
    compose = tmp_path / "phase1.yml"
    compose.write_text(compose_text, encoding="utf-8")
    for key in (
        "CRASHCAP_EXTERNAL_BIND_HOST",
        "CRASHCAP_S3_PUBLIC_ENDPOINT_URL",
        "PHASE1_S3_GATEWAY_PORT",
        "PHASE1_WEB_PORT",
        "S3_CORS_ALLOWED_ORIGINS",
    ):
        monkeypatch.delenv(key, raising=False)
    for key, value in environment.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(sys, "argv", ["deploy_check.py", "--compose", str(compose), "--json"])
    deploy_check.main()
    return json.loads(capsys.readouterr().out)


def test_deploy_check_rejects_public_container_name_and_cors_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = (ROOT / "deploy" / "compose" / "phase1.yml").read_text(encoding="utf-8")
    unsafe = original.replace("http://127.0.0.1:59000", "http://rustfs:9000")
    result = _run_deploy_check(unsafe, tmp_path, monkeypatch, capsys)
    assert result["status"] == "FAIL"
    assert any("Compose service name" in error for error in result["errors"])

    wrong_cors = original.replace("http://127.0.0.1:30080", "http://127.0.0.1:30081")
    result = _run_deploy_check(wrong_cors, tmp_path, monkeypatch, capsys)
    assert result["status"] == "FAIL"
    assert any("published Frontend" in error for error in result["errors"])


@pytest.mark.parametrize(
    "replacement",
    [
        "http://127.0.0.1:59001",
        "https://127.0.0.1:59000",
    ],
)
def test_deploy_check_rejects_public_endpoint_transport_or_port_mismatch(
    replacement: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = (ROOT / "deploy" / "compose" / "phase1.yml").read_text(encoding="utf-8")
    unsafe = original.replace("http://127.0.0.1:59000", replacement)

    result = _run_deploy_check(unsafe, tmp_path, monkeypatch, capsys)

    assert result["status"] == "FAIL"
    assert any(
        "must use http://" in error or "must match the S3 Gateway" in error
        for error in result["errors"]
    )


def test_deploy_check_rejects_data_port_and_wildcard_gateway_bind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = (ROOT / "deploy" / "compose" / "phase1.yml").read_text(encoding="utf-8")
    published_rustfs = original.replace(
        '    expose:\n      - "9000"',
        '    expose:\n      - "9000"\n    ports:\n      - "127.0.0.1:59001:9000"',
        1,
    )
    result = _run_deploy_check(published_rustfs, tmp_path, monkeypatch, capsys)
    assert result["status"] == "FAIL"
    assert "rustfs must not publish a host port" in result["errors"]

    result = _run_deploy_check(
        original,
        tmp_path,
        monkeypatch,
        capsys,
        CRASHCAP_EXTERNAL_BIND_HOST="0.0.0.0",  # noqa: S104 - rejection fixture
        CRASHCAP_S3_PUBLIC_ENDPOINT_URL="http://0.0.0.0:59000",
        S3_CORS_ALLOWED_ORIGINS="http://0.0.0.0:30080",
    )
    assert result["status"] == "FAIL"
    assert any("s3-gateway has wildcard/public bind" in error for error in result["errors"])
