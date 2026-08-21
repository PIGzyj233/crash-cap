from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_ROOT = REPOSITORY_ROOT / "scripts" / "phase1"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from ops_docker_proxy import allowed_container_id, filter_containers  # noqa: E402
from ops_exporter import render_metrics  # noqa: E402


def test_ops_exporter_preserves_api_metrics_and_marks_unavailable_signals(tmp_path: Path) -> None:
    (tmp_path / "sample.bin").write_bytes(b"1234")
    metrics = render_metrics(
        "# HELP crashcap_queue_depth queue\n"
        "# TYPE crashcap_queue_depth gauge\n"
        'crashcap_queue_depth{queue="verify"} 3.0\n',
        filesystems={"symbols": tmp_path},
        cgroup_root=tmp_path / "missing-cgroup",
    )

    assert 'crashcap_queue_depth{queue="verify"} 3.0' in metrics
    assert "crashcap_ops_api_scrape_up 1" in metrics
    assert 'crashcap_ops_filesystem_probe_up{filesystem="symbols"} 1' in metrics
    assert 'crashcap_ops_volume_logical_bytes{volume="symbols"} 4' in metrics
    assert 'crashcap_ops_volume_file_count{volume="symbols"} 1' in metrics
    assert 'crashcap_ops_queue_oldest_age_supported{queue="verify"} 0' in metrics
    assert 'crashcap_ops_queue_oldest_age_seconds{queue="verify"} NaN' in metrics
    assert 'crashcap_ops_symbolicator_cold_cache_state{state="unknown"} 1' in metrics
    assert 'crashcap_ops_rustfs_operation_supported{operation="multipart"} 0' in metrics
    assert (
        'crashcap_ops_service_resource_supported{resource="cpu_memory_pids",service="api"} 0'
        in metrics
    )


def test_ops_exporter_reexports_internal_otel_metrics() -> None:
    metrics = render_metrics(
        "",
        filesystems={},
        cgroup_root=Path("missing"),
        otel_text=(
            "# TYPE rustfs_http_server_requests_total counter\n"
            'rustfs_http_server_requests_total{http_request_method="HEAD",status_code="200"} 4\n'
            "symbolicator_cache_hits_total 2\n"
        ),
        otel_status=200,
    )

    assert (
        'rustfs_http_server_requests_total{http_request_method="HEAD",status_code="200"} 4'
        in metrics
    )
    assert "crashcap_ops_otel_scrape_up 1" in metrics
    assert "crashcap_ops_symbolicator_cold_cache_supported 1" in metrics
    assert 'crashcap_ops_rustfs_operation_supported{operation="head"} 1' in metrics
    assert 'crashcap_ops_rustfs_operation_status_known{operation="head"} 1' in metrics


def test_ops_exporter_reads_linux_cgroup_v2_files_without_logging_contents(tmp_path: Path) -> None:
    (tmp_path / "memory.current").write_text("1234\n", encoding="utf-8")
    (tmp_path / "memory.max").write_text("4096\n", encoding="utf-8")
    (tmp_path / "pids.current").write_text("7\n", encoding="utf-8")
    (tmp_path / "pids.max").write_text("64\n", encoding="utf-8")
    (tmp_path / "cpu.stat").write_text("usage_usec 250000\n", encoding="utf-8")

    metrics = render_metrics(
        "",
        filesystems={},
        cgroup_root=tmp_path,
    )

    assert 'crashcap_ops_self_resource_probe_up{container="ops-exporter"} 1' in metrics
    assert 'crashcap_ops_self_cpu_usage_seconds_total{container="ops-exporter"} 0.250000' in metrics
    assert (
        'crashcap_ops_self_memory_bytes{container="ops-exporter",state="current"} 1234' in metrics
    )
    assert 'crashcap_ops_self_memory_bytes{container="ops-exporter",state="limit"} 4096' in metrics
    assert 'crashcap_ops_self_pids{container="ops-exporter",state="current"} 7' in metrics
    assert 'crashcap_ops_self_pids{container="ops-exporter",state="limit"} 64' in metrics


def test_ops_exporter_reports_service_resources_from_allowlisted_docker_stats() -> None:
    stats = {
        "api": {
            "cpu_stats": {"cpu_usage": {"total_usage": 2_000_000_000}},
            "memory_stats": {"usage": 4096, "limit": 8192},
            "pids_stats": {"current": 3, "limit": 64},
        }
    }

    metrics = render_metrics(
        "",
        filesystems={},
        cgroup_root=Path("missing"),
        docker_stats=stats,
        docker_status=200,
    )

    assert "crashcap_ops_docker_api_up 1" in metrics
    assert (
        'crashcap_ops_service_resource_supported{resource="cpu_memory_pids",service="api"} 1'
        in metrics
    )
    assert 'crashcap_ops_container_cpu_usage_seconds_total{container="api"} 2.000000' in metrics
    assert 'crashcap_ops_container_memory_bytes{container="api",state="current"} 4096' in metrics
    assert 'crashcap_ops_container_pids{container="api",state="current"} 3' in metrics


def test_docker_proxy_filters_project_service_and_exact_container_id() -> None:
    allowed = filter_containers(
        [
            {
                "Id": "a" * 64,
                "Labels": {
                    "com.docker.compose.project": "crash-cap-phase1",
                    "com.docker.compose.service": "api",
                },
            },
            {
                "Id": "b" * 64,
                "Labels": {
                    "com.docker.compose.project": "other-project",
                    "com.docker.compose.service": "api",
                },
            },
            {
                "Id": "c" * 64,
                "Labels": {
                    "com.docker.compose.project": "crash-cap-phase1",
                    "com.docker.compose.service": "unrelated",
                },
            },
        ],
        project="crash-cap-phase1",
    )

    assert [container["Id"] for container in allowed] == ["a" * 64]
    assert allowed_container_id("a" * 64, allowed)
    assert not allowed_container_id("b" * 64, allowed)
    assert not allowed_container_id("a" * 12, allowed)
