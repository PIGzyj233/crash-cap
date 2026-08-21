"""Cross-check the Phase 1 HTTP-only transport boundary."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

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
