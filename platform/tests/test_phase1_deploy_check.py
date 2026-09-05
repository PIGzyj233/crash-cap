"""The current v3 deployment must pass without weakening isolation checks."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml
from crashcap_api.config import Settings

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "deploy/compose/phase1.yml"
spec = importlib.util.spec_from_file_location(
    "phase1_deploy_check_v3", ROOT / "scripts/phase1/deploy_check.py"
)
assert spec is not None and spec.loader is not None
deploy_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy_check)


@pytest.fixture
def document() -> dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text())  # type: ignore[no-any-return]


def run_check(
    document: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    runtime_extra: str = "",
    environment: dict[str, str] | None = None,
    compose_environment: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    for match in deploy_check.INTERPOLATION.finditer(COMPOSE.read_text()):
        monkeypatch.delenv(match.group(1), raising=False)
    for name, value in (environment or {}).items():
        monkeypatch.setenv(name, value)
    compose = tmp_path / "phase1.yml"
    compose.write_text(yaml.safe_dump(document))
    runtime = tmp_path / "runtime.env"
    runtime.write_text(
        "".join(f"{name}=private-test-value\n" for name in deploy_check.RUNTIME_REQUIRED)
        + runtime_extra
    )
    arguments = [
        "deploy_check.py",
        "--compose",
        str(compose),
        "--runtime-env-file",
        str(runtime),
        "--json",
    ]
    if compose_environment is not None:
        compose_env = tmp_path / "compose.env"
        compose_env.write_text(
            "".join(f"{name}={value}\n" for name, value in compose_environment.items())
        )
        arguments.extend(["--env-file", str(compose_env)])
    monkeypatch.setattr(sys, "argv", arguments)
    code = deploy_check.main()
    output = capsys.readouterr().out
    assert "private-test-value" not in output
    return code, json.loads(output)


def test_current_upload_v3_compose_passes(
    document: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, result = run_check(document, tmp_path, monkeypatch, capsys)
    assert result["errors"] == []
    assert result["warnings"] == []
    assert code == 0
    assert result["status"] == "PASS"


def test_explicit_settings_are_runtime_fields_not_removed_or_class_variables() -> None:
    settings_names = {"CRASHCAP_" + name.upper() for name in Settings.model_fields}
    assert settings_names >= deploy_check.CRASHCAP_REQUIRED_EXPLICIT
    assert settings_names >= deploy_check.CRASHCAP_RELAY_EXPLICIT
    assert Settings.task_handoff_mode == "outbox"
    assert Settings.task_receipt_mode == "strict"
    assert Settings.frozen_core_enabled is True
    assert Settings.frozen_analysis_enabled is True
    assert Settings.automatic_analysis_enabled is True
    assert Settings.catalog_source_enabled is True


def test_shell_environment_has_the_same_precedence_as_compose(
    document: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, result = run_check(
        document,
        tmp_path,
        monkeypatch,
        capsys,
        compose_environment={"CRASHCAP_EXTERNAL_BIND_HOST": "0.0.0.0"},  # noqa: S104
        environment={"CRASHCAP_EXTERNAL_BIND_HOST": "127.0.0.1"},
    )
    assert code == 0, result["errors"]


@pytest.mark.parametrize("service", ["automatic-analysis", "cache-init"])
def test_v3_background_services_are_required(
    service: str,
    document: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del document["services"][service]
    code, result = run_check(document, tmp_path, monkeypatch, capsys)
    assert code == 1
    assert any(
        "required services missing" in error and service in error for error in result["errors"]
    )


@pytest.mark.parametrize(
    ("service", "field", "value", "expected"),
    [
        ("postgres", "networks", ["data", "core"], "postgres networks must"),
        ("symbol-source", "ports", ["127.0.0.1:8081:8081"], "must not publish"),
        ("cache-init", "network_mode", "host", "cache-init"),
        ("automatic-analysis", "entrypoint", ["sleep", "infinity"], "resident planner"),
    ],
)
def test_runtime_topology_regressions_fail_closed(
    service: str,
    field: str,
    value: Any,
    expected: str,
    document: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document["services"][service][field] = value
    code, result = run_check(document, tmp_path, monkeypatch, capsys)
    assert code == 1
    assert any(expected in error for error in result["errors"])


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("CRASHCAP_FROZEN_PAIR_SOURCE_ROOT", "http://other-workspace:8081/v3/pairs"),
        ("CRASHCAP_FROZEN_SYMBOLICATOR_URL", "http://symbolicator-gateway:3021"),
        ("CRASHCAP_CORE_IMAGE_DIGEST", "sha256:" + "0" * 64),
    ],
)
def test_planner_and_workers_must_use_the_same_frozen_runtime(
    setting: str,
    value: str,
    document: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document["services"]["automatic-analysis"]["environment"] = {setting: value}
    code, result = run_check(document, tmp_path, monkeypatch, capsys)
    assert code == 1
    assert any(
        "automatic-analysis" in error and "frozen runtime" in error for error in result["errors"]
    )


def test_core_cannot_gain_direct_access_to_object_store(
    document: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document["x-core-runtime"]["allowed_peers"].append("rustfs")
    code, result = run_check(document, tmp_path, monkeypatch, capsys)
    assert code == 1
    assert any("Core runtime policy" in error for error in result["errors"])


def test_ops_exporter_mounts_stay_read_only(
    document: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document["services"]["ops-exporter"]["volumes"][0]["read_only"] = False
    code, result = run_check(document, tmp_path, monkeypatch, capsys)
    assert code == 1
    assert "ops-exporter data-volume mounts are missing or writable" in result["errors"]


@pytest.mark.parametrize(
    "extra",
    ["CRASHCAP_FROZEN_CORE_ENABLED=false\n", "CRASHCAP_ARTIFACT_BLOB_DEDUP_MODE=off\n"],
)
def test_ignored_legacy_runtime_switches_are_rejected(
    extra: str,
    document: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, result = run_check(document, tmp_path, monkeypatch, capsys, runtime_extra=extra)
    assert code == 1
    assert any("removed or fixed" in error for error in result["errors"])


def test_private_deployment_overrides_keep_the_topology_valid(
    document: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, result = run_check(
        document,
        tmp_path,
        monkeypatch,
        capsys,
        environment={
            "COMPOSE_PROJECT_NAME": "crashcap-v3-check",
            "CRASHCAP_CORE_NETWORK": "crashcap-v3-check-core",
            "CRASHCAP_CORE_IMAGE": "crash-cap/dmp-core:test-v3",
            "CRASHCAP_CORE_IMAGE_DIGEST": "sha256:" + "1" * 64,
            "CRASHCAP_EXTERNAL_BIND_HOST": "10.20.30.40",
            "PHASE1_WEB_PORT": "30081",
            "PHASE1_S3_GATEWAY_PORT": "59001",
            "CRASHCAP_S3_PUBLIC_ENDPOINT_URL": "http://10.20.30.40:59001",
            "S3_CORS_ALLOWED_ORIGINS": "http://10.20.30.40:30081",
        },
    )
    assert code == 0, result["errors"]
