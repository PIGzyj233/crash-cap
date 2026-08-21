from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_capacity_gate() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "phase1" / "capacity_gate.py"
    spec = importlib.util.spec_from_file_location("phase1_capacity_gate", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load capacity gate runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_capacity_fixture() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "phase1" / "capacity_fixture.py"
    spec = importlib.util.spec_from_file_location("phase1_capacity_fixture", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load capacity fixture generator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


capacity_gate = _load_capacity_gate()
capacity_fixture = _load_capacity_fixture()


def test_capacity_buckets_are_inclusive_at_the_phase_boundaries() -> None:
    assert capacity_gate.classify_bucket(64 * 1024 * 1024) == "le_64MiB"
    assert capacity_gate.classify_bucket(64 * 1024 * 1024 + 1) == "64_256MiB"
    assert capacity_gate.classify_bucket(256 * 1024 * 1024) == "64_256MiB"
    assert capacity_gate.classify_bucket(256 * 1024 * 1024 + 1) == "over_256MiB"
    assert capacity_gate.classify_bucket(None) == "unknown"


def test_percentile_is_deterministic_and_handles_empty_samples() -> None:
    assert capacity_gate.percentile([1, 2, 3, 4], 50) == 2.5
    assert capacity_gate.percentile([1, 2, 3, 4], 95) == 3.85
    assert capacity_gate.percentile([], 99) is None


def test_manifest_supports_reprocess_and_upload_shapes(tmp_path: Path) -> None:
    payload = tmp_path / "sample.dmp"
    payload.write_bytes(b"MDMP" + b"x" * 100)
    reprocess_manifest = tmp_path / "reprocess.json"
    reprocess_manifest.write_text(
        json.dumps({"tasks": [{"occurrence_id": "occ_a", "size_bytes": 100}]}),
        encoding="utf-8",
    )
    upload_manifest = tmp_path / "upload.json"
    upload_manifest.write_text(
        json.dumps(
            {
                "tasks": [
                    {
                        "task_id": "upload-a",
                        "workspace_id": "wsp_a",
                        "payload_path": payload.name,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    reprocess_tasks = capacity_gate.load_manifest(reprocess_manifest, workload="reprocess")
    assert [task.occurrence_id for task in reprocess_tasks] == ["occ_a"]
    upload_tasks = capacity_gate.load_manifest(upload_manifest, workload="upload")
    assert upload_tasks[0].payload_path == payload.resolve()
    assert upload_tasks[0].size_bytes == payload.stat().st_size


def test_fixture_generator_emits_deterministic_unique_small_and_large_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(capacity_fixture, "SMALL_MAX_BYTES", 64)
    template = tmp_path / "template.dmp"
    template.write_bytes(b"MDMP")
    manifest = capacity_fixture.generate_fixture_manifest(
        template=template,
        output_dir=tmp_path / "dumps",
        manifest_path=tmp_path / "manifest.json",
        workspace_id="wsp-a",
        build_id="bld-a",
        small_count=1,
        large_count=99,
        large_size_bytes=65,
    )

    assert manifest["small_count"] == 1
    assert manifest["large_count"] == 99
    assert manifest["tasks"][0]["task_id"] == "small-0001"
    assert manifest["tasks"][-1]["task_id"] == "large-0099"
    first_payload = Path(manifest["tasks"][0]["payload_path"])
    last_payload = Path(manifest["tasks"][-1]["payload_path"])
    assert first_payload.stat().st_size == len(
        b"MDMP" + b"\nCRASHCAP_CAPACITY_FIXTURE=v1;bucket=small;index=0001\n"
    )
    assert last_payload.stat().st_size == 65
    assert first_payload.read_bytes() != last_payload.read_bytes()


def test_fixture_generator_rejects_a_non_minidump_template(tmp_path: Path) -> None:
    template = tmp_path / "not-a-dump.bin"
    template.write_bytes(b"NOPE")

    with pytest.raises(ValueError, match="MDMP signature"):
        capacity_fixture.generate_fixture_manifest(
            template=template,
            output_dir=tmp_path / "dumps",
            manifest_path=tmp_path / "manifest.json",
            workspace_id="wsp-a",
            build_id=None,
            small_count=80,
            large_count=20,
            large_size_bytes=capacity_fixture.DEFAULT_LARGE_SIZE,
        )


def test_queue_parser_and_security_boundary_do_not_echo_credentials() -> None:
    metrics = "\n".join(
        [
            'crashcap_queue_depth{queue="dump-small"} 4.0',
            'crashcap_queue_depth{queue="dump-large"} 2',
        ]
    )
    assert capacity_gate.parse_queue_depths(metrics) == {"dump-small": 4.0, "dump-large": 2.0}
    for value in (
        "https://example.test/api/v1",
        "ftp://example.test/api/v1",
        "http://user:secret@example.test/api/v1",
    ):
        with pytest.raises(ValueError) as exc_info:
            capacity_gate.normalize_api_base_url(value)
        assert "secret" not in str(exc_info.value)
    for value in (
        "https://example.test/metrics",
        "ftp://example.test/metrics",
        "http://user:secret@example.test/metrics",
    ):
        with pytest.raises(ValueError) as exc_info:
            capacity_gate.normalize_metrics_url(value)
        assert "secret" not in str(exc_info.value)
    assert capacity_gate.derive_metrics_url("http://127.0.0.1:8080/api/v1") == (
        "http://127.0.0.1:8080/metrics"
    )


class _MetricsResponse:
    status = 200

    def __enter__(self) -> _MetricsResponse:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self) -> bytes:
        return b'crashcap_queue_depth{queue="verify"} 0\n'


class _UploadResponse:
    status = 200

    def read(self) -> bytes:
        return b""

    def getheader(self, name: str) -> str | None:
        return '"etag-value"' if name.lower() == "etag" else None


class _UploadConnection:
    def __init__(self, host: str, timeout: float) -> None:
        self.host = host
        self.timeout = timeout
        self.request: tuple[str, str] | None = None
        self.headers: list[tuple[str, str]] = []
        self.sent: list[bytes] = []
        self.closed = False

    def putrequest(self, method: str, target: str) -> None:
        self.request = (method, target)

    def putheader(self, key: str, value: str) -> None:
        self.headers.append((key, value))

    def endheaders(self) -> None:
        return None

    def send(self, chunk: bytes) -> None:
        self.sent.append(chunk)

    def getresponse(self) -> _UploadResponse:
        return _UploadResponse()

    def close(self) -> None:
        self.closed = True


def test_stream_upload_uses_http_connection_and_streams_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / "sample.dmp"
    payload.write_bytes(b"MDMP" + b"x" * 100)
    connections: list[_UploadConnection] = []

    def fake_connection(host: str, timeout: float) -> _UploadConnection:
        connection = _UploadConnection(host, timeout)
        connections.append(connection)
        return connection

    monkeypatch.setattr(capacity_gate.http.client, "HTTPConnection", fake_connection)
    etag = capacity_gate.stream_upload_file(
        "http://objects.example/upload?signature=redacted",
        "PUT",
        {"X-Test": "ok", "Host": "ignored"},
        payload,
    )

    assert etag == '"etag-value"'
    assert len(connections) == 1
    connection = connections[0]
    assert connection.host == "objects.example"
    assert connection.request == ("PUT", "/upload?signature=redacted")
    assert b"".join(connection.sent) == payload.read_bytes()
    assert ("Content-Length", str(payload.stat().st_size)) in connection.headers
    assert connection.closed is True


@pytest.mark.parametrize(
    "url",
    [
        "https://objects.example/upload",
        "ftp://objects.example/upload",
        "http://user:secret@objects.example/upload",
    ],
)
def test_stream_upload_rejects_https_userinfo_and_non_http(
    tmp_path: Path, url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / "sample.dmp"
    payload.write_bytes(b"MDMP")
    monkeypatch.setattr(
        capacity_gate.http.client,
        "HTTPConnection",
        lambda *_args, **_kwargs: pytest.fail("HTTPConnection must not be opened"),
    )

    with pytest.raises(ValueError):
        capacity_gate.stream_upload_file(url, "PUT", {}, payload)


def test_report_does_not_emit_endpoint_url_or_credentials() -> None:
    report = capacity_gate.build_report(
        mode="dry-run",
        workload="reprocess",
        tasks=[],
        results=[],
        preflight_errors=[],
        queue={"status": "NOT_PROVEN", "local_in_flight_peak": 0},
        digest={"status": "NOT_PROVEN"},
        microsoft={"status": "NOT_PROVEN"},
        manifest_name="manifest.json",
        base_url="http://user:secret@example.test/api/v1",
        expected_count=0,
        requested_concurrency=1,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
    )

    emitted = json.dumps(report)
    assert "http://" not in emitted
    assert "secret" not in emitted


def test_metrics_client_requests_exact_metrics_url(monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str] = []

    def fake_urlopen(request: Any, timeout: float) -> _MetricsResponse:
        del timeout
        requested.append(request.full_url)
        return _MetricsResponse()

    monkeypatch.setattr(capacity_gate, "urlopen", fake_urlopen)
    client = capacity_gate.ApiClient("http://127.0.0.1:8080/metrics", 1)

    assert "crashcap_queue_depth" in client.get_metrics()
    assert requested == ["http://127.0.0.1:8080/metrics"]


def test_microsoft_cold_cache_is_not_proven_without_explicit_independent_evidence(
    tmp_path: Path,
) -> None:
    absent = capacity_gate.load_microsoft_evidence(None)
    assert absent["status"] == "NOT_PROVEN"

    unqualified = tmp_path / "cold.json"
    unqualified.write_text(json.dumps({"cold_cache_duration_ms": 10}), encoding="utf-8")
    assert capacity_gate.load_microsoft_evidence(unqualified)["status"] == "NOT_PROVEN"

    valid_context = {
        "status": "PROVEN",
        "cold_cache_downloads": 1,
        "cold_cache_duration_ms": 1234,
        "source_kind": "microsoft_symbol_server",
        "controlled_cache_reset_method": "fresh-volume",
        "measurement_source": "gateway-metrics",
        "evidence_ref": "ticket-123",
        "observed_at": "2026-01-01T00:00:00Z",
    }
    for field, value in (
        ("cold_cache_downloads", 0),
        ("cold_cache_duration_ms", 0),
        ("cache_misses", 0),
        ("observed_at", "not-a-timestamp"),
    ):
        invalid = tmp_path / f"invalid-{field}.json"
        document = {**valid_context, field: value}
        invalid.write_text(json.dumps(document), encoding="utf-8")
        assert capacity_gate.load_microsoft_evidence(invalid)["status"] == "NOT_PROVEN"

    proven = tmp_path / "proven.json"
    proven.write_text(
        json.dumps({**valid_context, "secret": "must-not-be-copied"}),
        encoding="utf-8",
    )
    evidence = capacity_gate.load_microsoft_evidence(proven)
    assert evidence["status"] == "PROVEN"
    assert "secret" not in evidence


class _FakeReprocessClient:
    def reprocess(self, occurrence_id: str) -> dict[str, Any]:
        return {"id": f"run-{occurrence_id}"}

    def get_occurrence(self, occurrence_id: str) -> dict[str, Any]:
        return {
            "latest_attempt": {
                "id": f"run-{occurrence_id}",
                "status": "COMPLETE",
                "duration_ms": 20,
            }
        }

    def get_analysis(self, occurrence_id: str, run_id: str) -> dict[str, Any]:
        del occurrence_id, run_id
        return {"engine": {"core_image_digest": "sha256:" + "a" * 64}}


class _FakeUploadClient:
    def __init__(self) -> None:
        self.uploads = 0

    def init_dump_upload(self, workspace_id: str, **_kwargs: Any) -> dict[str, Any]:
        self.uploads += 1
        return {
            "upload_id": f"upl-{self.uploads}",
            "method": "PUT",
            "url": "http://objects.example/upload",
            "headers": {},
        }

    def complete_upload(self, upload_id: str, **_kwargs: Any) -> dict[str, Any]:
        return {"upload_id": upload_id, "status": "VERIFYING"}

    def get_upload(self, upload_id: str) -> dict[str, Any]:
        number = upload_id.rsplit("-", 1)[-1]
        return {
            "upload_id": upload_id,
            "status": "ACCEPTED",
            "occurrence_id": f"occ-{number}",
            "blob_id": f"blob-{number}",
            "sha256": "a" * 64,
            "duplicate": False,
        }

    def get_occurrence(self, occurrence_id: str) -> dict[str, Any]:
        number = occurrence_id.rsplit("-", 1)[-1]
        return {
            "latest_attempt": {
                "id": f"run-{number}",
                "status": "COMPLETE",
                "duration_ms": 20,
            }
        }

    def get_analysis(self, occurrence_id: str, run_id: str) -> dict[str, Any]:
        del occurrence_id, run_id
        return {"engine": {"core_image_digest": "sha256:" + "b" * 64}}


def test_reprocess_execution_is_reported_as_smoke_not_a_capacity_pass() -> None:
    tasks = [
        capacity_gate.CapacityTask(
            task_id="occ-small",
            occurrence_id="occ-small",
            size_bytes=64 * 1024 * 1024,
        )
    ]
    results, tracker = capacity_gate.execute_tasks(
        _FakeReprocessClient(),
        tasks,
        workload="reprocess",
        concurrency=1,
        timeout_seconds=1,
        poll_interval_seconds=0,
    )
    assert results[0]["status"] == "COMPLETE"
    assert tracker.peak == 1
    report = capacity_gate.build_report(
        mode="execute",
        workload="reprocess",
        tasks=tasks,
        results=results,
        preflight_errors=[],
        queue={"status": "PROVEN", "local_in_flight_peak": 1},
        digest=capacity_gate.digest_summary(results, None),
        microsoft={"status": "PROVEN"},
        manifest_name="smoke.json",
        base_url="http://127.0.0.1:8080/api/v1",
        expected_count=1,
        requested_concurrency=1,
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
    )
    assert report["status"] == "NOT_PROVEN"
    assert "smoke-only" in " ".join(report["gate"]["reasons"])


def test_upload_execution_tracks_unique_blob_and_occurrence_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = tmp_path / "sample.dmp"
    payload.write_bytes(b"MDMP" + b"x" * 100)
    tasks = [
        capacity_gate.CapacityTask(
            task_id="task-1",
            workspace_id="wsp-a",
            payload_path=payload,
            size_bytes=payload.stat().st_size,
        )
    ]
    monkeypatch.setattr(capacity_gate, "stream_upload_file", lambda *_args, **_kwargs: '"etag"')
    results, tracker = capacity_gate.execute_tasks(
        _FakeUploadClient(),
        tasks,
        workload="upload",
        concurrency=1,
        timeout_seconds=1,
        poll_interval_seconds=0,
    )
    assert results[0]["accepted"] is True
    assert results[0]["upload_status"] == "ACCEPTED"
    assert tracker.peak == 1
    assert capacity_gate.uniqueness_summary("upload", results)["status"] == "PROVEN"
