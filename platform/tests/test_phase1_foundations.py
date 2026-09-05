"""Independent tests for the Phase 1 platform foundations.

These tests intentionally exercise the existing production helpers from the
outside.  The test package must not make the API more permissive just to make
the checks pass: security and state-machine behavior are treated as contracts.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
for _source_root in (REPOSITORY_ROOT / "platform" / "api", REPOSITORY_ROOT / "platform" / "worker"):
    if str(_source_root) not in sys.path:
        sys.path.insert(0, str(_source_root))

from crashcap_api.config import Settings  # noqa: E402
from crashcap_api.errors import ApiError, error_payload  # noqa: E402
from crashcap_api.ids import ID_RE, new_id, validate_id  # noqa: E402
from crashcap_api.models import AnalysisRun, Upload  # noqa: E402
from crashcap_api.object_keys import (  # noqa: E402
    analysis_generation_key,
    analysis_key,
    analysis_prefix,
    assert_scoped_key,
    dump_blob_key,
    safe_filename,
    upload_key,
)
from crashcap_api.redaction import RedactingFilter, redact  # noqa: E402
from crashcap_api.routes import router  # noqa: E402
from crashcap_api.services.common import (  # noqa: E402
    _sanitize_details,
    assert_no_delete_routes,
    transition_analysis,
    transition_upload,
)
from crashcap_worker.main import worker_arguments  # noqa: E402


def test_settings_reject_public_production_bind_and_missing_s3_credentials() -> None:
    with pytest.raises(ValidationError, match="public bind"):
        Settings(
            environment="production",
            object_store_backend="s3",
            s3_access_key="access-key",
            s3_secret_key="secret-key",  # noqa: S106 - deliberate credential-boundary fixture
            external_bind_host="8.8.8.8",
        )

    with pytest.raises(ValidationError, match="S3 service credentials"):
        Settings(environment="test", object_store_backend="s3")


def test_settings_require_and_hide_service_credentials(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        object_store_backend="s3",
        s3_access_key="access-key",
        s3_secret_key="super-secret-value",  # noqa: S106 - deliberate redaction fixture
    )
    assert settings.s3_access_key.get_secret_value() == "access-key"
    assert settings.s3_secret_key.get_secret_value() == "super-secret-value"
    assert str(settings.s3_secret_key) == "**********"
    assert "super-secret-value" not in repr(settings)
    assert settings.s3_endpoint_url == "http://rustfs:9000"
    assert settings.s3_public_endpoint_url is None

    for invalid_endpoint in (
        "https://rustfs:9000",
        "http:///missing-host",
        "http://user:secret@rustfs:9000",
        "http://rustfs:9000?token=secret",
        "http://rustfs:9000#fragment",
    ):
        with pytest.raises(ValidationError, match="must use http://"):
            Settings(
                environment="production",
                object_store_backend="s3",
                s3_access_key="access-key",
                s3_secret_key="super-secret-value",  # noqa: S106 - deliberate validation fixture
                external_bind_host="127.0.0.1",
                s3_endpoint_url=invalid_endpoint,
            )
    with pytest.raises(ValidationError, match="must use http://"):
        Settings(
            environment="production",
            object_store_backend="s3",
            s3_access_key="access-key",
            s3_secret_key="super-secret-value",  # noqa: S106 - deliberate validation fixture
            external_bind_host="127.0.0.1",
            s3_public_endpoint_url="https://rustfs.intranet:9000",
        )

    test_settings = Settings.for_test(tmp_path)
    assert test_settings.object_store_backend == "local"
    assert test_settings.queue_mode == "memory"


def test_prefixed_ulids_are_valid_and_unique_at_10k() -> None:
    values = [new_id("wsp") for _ in range(10_000)]

    assert len(set(values)) == 10_000
    assert all(ID_RE.fullmatch(value) for value in values)
    assert all(validate_id(value, "wsp") == value for value in values)

    with pytest.raises(ValueError, match="unsupported Crash-Cap ID prefix"):
        new_id("user")
    with pytest.raises(ValueError, match="expected art_"):
        validate_id(values[0], "art")


def test_object_key_builders_scope_workspace_and_reject_traversal() -> None:
    workspace_id = new_id("wsp")
    upload_id = new_id("upl")
    blob_id = new_id("blob")
    occurrence_id = new_id("occ")
    run_id = new_id("run")

    assert upload_key(workspace_id, upload_id) == f"uploads/{workspace_id}/{upload_id}/blob"
    assert dump_blob_key(workspace_id, blob_id).endswith(f"/{blob_id}/original.dmp")
    assert analysis_prefix(workspace_id, occurrence_id, run_id).startswith(
        f"analysis/{workspace_id}/{occurrence_id}/{run_id}"
    )
    assert analysis_key(workspace_id, occurrence_id, run_id, "raw/inspect.json").endswith(
        "/raw/inspect.json"
    )
    generation_key = analysis_generation_key(
        workspace_id,
        occurrence_id,
        run_id,
        "att_test",
        2,
        "canonical.json",
    )
    assert generation_key.startswith(f"analysis/{workspace_id}/{occurrence_id}/{run_id}/g/2-")
    assert generation_key.endswith("/canonical.json")

    for filename in ("../dump.dmp", r"..\dump.dmp", "C:/dump.dmp", "dump/name.dmp", ""):
        with pytest.raises(ValueError):
            safe_filename(filename)
    assert safe_filename("dump.dmp") == "dump.dmp"

    for unsafe in (
        f"uploads/{workspace_id}/../escape",
        f"uploads/{workspace_id}\\escape",
        f"/absolute/{workspace_id}/escape",
        f"uploads/{workspace_id}/escape\x00",
        "uploads/wsp_missing/escape",
    ):
        with pytest.raises(ValueError):
            assert_scoped_key(unsafe, workspace_id)
    assert assert_scoped_key(f"uploads/{workspace_id}/{upload_id}/blob", workspace_id).startswith(
        "uploads/"
    )


def test_upload_state_machine_rejects_illegal_jumps() -> None:
    upload = Upload(
        id=new_id("upl"),
        workspace_id=new_id("wsp"),
        object_key="uploads/test/blob",
        original_filename="dump.dmp",
        declared_length=1,
        file_kind="dmp",
        verification_status="INITIALIZED",
    )

    with pytest.raises(ApiError, match="illegal upload state transition") as error:
        transition_upload(upload, "ACCEPTED")
    assert error.value.code == "CONFLICT"
    assert error.value.status_code == 409
    assert error.value.details == {"from": "INITIALIZED", "to": "ACCEPTED"}

    transition_upload(upload, "UPLOADED")
    transition_upload(upload, "VERIFYING")
    with pytest.raises(ApiError):
        transition_upload(upload, "INITIALIZED")
    with pytest.raises(ValueError, match="unknown upload state"):
        transition_upload(upload, "NOT_A_STATE")


def test_analysis_state_machine_rejects_illegal_jumps() -> None:
    run = AnalysisRun(
        id=new_id("run"),
        occurrence_id=new_id("occ"),
        run_spec={},
        core_version="test",
        core_image_digest="sha256:" + "0" * 64,
        symbolicator_version="test",
        symbol_inventory_version=0,
        idempotency_key="0" * 64,
        status="UPLOADED",
    )

    with pytest.raises(ApiError, match="illegal analysis state transition") as error:
        transition_analysis(run, "COMPLETE")
    assert error.value.code == "CONFLICT"
    assert error.value.details == {"from": "UPLOADED", "to": "COMPLETE"}

    transition_analysis(run, "VALIDATING")
    with pytest.raises(ApiError):
        transition_analysis(run, "GROUPING")
    with pytest.raises(ValueError, match="unknown analysis state"):
        transition_analysis(run, "INVALID")


def test_error_and_operation_details_are_redacted() -> None:
    raw = (
        "token=token-value password=pass-value "
        "https://storage.local/blob?X-Amz-Signature=signature-value"
    )
    redacted = redact(raw)
    assert "token-value" not in redacted
    assert "pass-value" not in redacted
    assert "signature-value" not in redacted
    assert "[REDACTED]" in redacted

    safe = _sanitize_details(
        {
            "reason": "length_mismatch",
            "token": "token-value",
            "presigned_url": "https://storage.local/presigned",
            "Memory": b"raw bytes",
            "source": "source code",
            "safe": {
                "attempt": 2,
                "nested": [
                    {"password": "nested-password", "keep": "ordinary"},
                    ("safe tuple value", {"access_key": "nested-access-key"}),
                ],
            },
            "note": (
                "https://storage.local/blob?X-Amz-Credential=credential"
                "&X-Amz-Signature=signature-value"
            ),
        }
    )
    assert safe == {
        "reason": "length_mismatch",
        "safe": {
            "attempt": 2,
            "nested": [{"keep": "ordinary"}, ("safe tuple value", {})],
        },
        "note": "[REDACTED_URL]",
    }
    assert "nested-password" not in repr(safe)
    assert "nested-access-key" not in repr(safe)
    assert "signature-value" not in repr(safe)

    api_error = ApiError(
        "VALIDATION",
        "token=message-token",
        details={"nested": {"secret": "error-secret", "safe": "value"}},
    )
    assert str(api_error) == "token=[REDACTED]"
    assert api_error.details == {"nested": {"safe": "value"}}

    payload = error_payload(
        "VALIDATION",
        "request validation failed",
        {"field": "filename", "nested": {"secret": "payload-secret", "ok": True}},
    )
    assert payload == {
        "error": {
            "code": "VALIDATION",
            "message": "request validation failed",
            "details": {"field": "filename", "nested": {"ok": True}},
        }
    }

    record = logging.LogRecord("test", logging.INFO, __file__, 1, "done", (), None)
    record.attempt_id = "att_test"  # type: ignore[attr-defined]
    record.reason = "token=log-secret"  # type: ignore[attr-defined]
    assert RedactingFilter().filter(record) is True
    assert record.attempt_id == "att_test"  # type: ignore[attr-defined]
    assert record.reason == "token=[REDACTED]"  # type: ignore[attr-defined]
    for field in (
        "request_id",
        "task_type",
        "queue",
        "logical_target",
        "domain_identity",
        "claim_generation",
        "from_status",
        "to_status",
        "outcome",
    ):
        assert getattr(record, field) == "-"


def test_api_routes_have_no_delete_or_identity_routes() -> None:
    assert_no_delete_routes(router.routes)

    paths = [str(route.path).lower() for route in router.routes]
    methods = [set(getattr(route, "methods", set()) or set()) for route in router.routes]
    assert all("delete" not in route_methods for route_methods in methods)
    for forbidden_segment in ("login", "users", "roles"):
        assert all(forbidden_segment not in path.split("/") for path in paths)


def test_worker_queue_process_isolation_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRASHCAP_WORKER_QUEUES", "dump-large")
    monkeypatch.setenv("CRASHCAP_WORKER_PROCESSES", "1")
    monkeypatch.setenv("CRASHCAP_WORKER_THREADS", "1")
    arguments = worker_arguments()
    assert arguments[arguments.index("--queues") + 1] == "dump-large"
    assert arguments[arguments.index("--processes") + 1] == "1"
    assert arguments[arguments.index("--threads") + 1] == "1"

    monkeypatch.setenv("CRASHCAP_WORKER_QUEUES", "dump-huge")
    with pytest.raises(ValueError, match="Phase 1 queues"):
        worker_arguments()
