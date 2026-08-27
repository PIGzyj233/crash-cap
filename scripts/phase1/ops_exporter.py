#!/usr/bin/env python3
"""Read-only Phase 1 Prometheus text exporter.

The API remains the source of truth for durable queue/state/duration/object
metrics.  This sidecar scrapes that endpoint and adds host-volume and cgroup
telemetry that it can read without a Docker socket or application secrets.
Signals for which the current components expose no reliable source are emitted
as explicit ``supported=0``/``unknown`` metrics instead of guessed values.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

QUEUE_NAMES = ("verify", "ingest", "dump-small", "dump-large")
RESOURCE_SERVICES = (
    "postgres",
    "redis",
    "rustfs",
    "symbolicator",
    "symbolicator-gateway",
    "api",
    "worker",
    "worker-verify",
    "worker-ingest",
    "worker-dump-large",
    "retention",
    "frontend",
)
DOCKER_ID = re.compile(r"^[0-9a-fA-F]{12,64}$")
DEFAULT_FILESYSTEMS = {
    "rustfs": "/host/rustfs",
    "symbols": "/host/symbols",
    "symbolicator_cache": "/host/symbolicator-cache",
}
METRIC_NAME = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")
RETENTION_METRIC_PREFIXES = ("crashcap_upload_payload_",)
# Pinned Symbolicator 26.7.2 maps policy groups onto these physical cache
# directories. Diagnostics, the source index, and tmp use separate policies and
# are intentionally excluded from downloaded/derived TTL alerts.
SYMBOLICATOR_CACHE_DIRECTORIES = {
    "downloaded": ("objects", "auxdifs", "il2cpp", "sourcefiles", "proguard"),
    "derived": (
        "object_meta",
        "symcaches",
        "cficaches",
        "ppdb_caches",
        "sourcemap_caches",
    ),
}


def _label(value: object) -> str:
    text = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{text}"'


def _labels(values: dict[str, object]) -> str:
    if not values:
        return ""
    return (
        "{"
        + ",".join(f"{key}={_label(value)}" for key, value in sorted(values.items()))
        + "}"
    )


def _sample(name: str, values: dict[str, object], value: float | str) -> str:
    return f"{name}{_labels(values)} {value}"


def _block(
    name: str, help_text: str, metric_type: str, samples: Iterable[str]
) -> list[str]:
    if not METRIC_NAME.fullmatch(name):
        raise ValueError(f"invalid metric name: {name}")
    return [
        f"# HELP {name} {help_text}",
        f"# TYPE {name} {metric_type}",
        *samples,
    ]


def _float_text(value: float) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if value == float("inf"):
            return "+Inf"
        if value == float("-inf"):
            return "-Inf"
        return f"{value:.6f}"
    return str(value)


def _filter_metric_families(text: str, prefixes: tuple[str, ...]) -> str:
    """Keep owned metric families while dropping duplicate process/runtime families."""

    selected: list[str] = []
    for line in text.splitlines():
        if line.startswith(("# HELP ", "# TYPE ")):
            parts = line.split(maxsplit=3)
            metric_name = parts[2] if len(parts) >= 3 else ""
        elif line.startswith("#") or not line.strip():
            continue
        else:
            metric_name = line.split("{", 1)[0].split(maxsplit=1)[0]
        if metric_name.startswith(prefixes):
            selected.append(line)
    return "\n".join(selected)


def _parse_filesystems(raw: str | None) -> dict[str, Path]:
    if not raw:
        return {name: Path(path) for name, path in DEFAULT_FILESYSTEMS.items()}
    result: dict[str, Path] = {}
    for item in raw.split(","):
        name, separator, path = item.partition("=")
        if not separator or not name or not path:
            continue
        result[name] = Path(path)
    return result


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _filesystem_metrics(filesystems: dict[str, Path]) -> list[str]:
    samples: list[str] = []
    probe_samples: list[str] = []
    inode_samples: list[str] = []
    logical_bytes_samples: list[str] = []
    logical_file_samples: list[str] = []
    logical_probe_samples: list[str] = []
    for name, path in filesystems.items():
        try:
            statvfs = os.__dict__.get("statvfs")
            if callable(statvfs):
                stats = statvfs(path)
                block_size = int(stats.f_frsize or stats.f_bsize)
                total = int(stats.f_blocks) * block_size
                free = int(stats.f_bavail) * block_size
                inode_total = int(stats.f_files)
                inode_free = int(stats.f_favail)
            else:
                usage = shutil.disk_usage(path)
                total = int(usage.total)
                free = int(usage.free)
                inode_total = None
                inode_free = None
            used = max(0, total - free)
            probe_samples.append(
                _sample("crashcap_ops_filesystem_probe_up", {"filesystem": name}, 1)
            )
            for state, value in (("total", total), ("used", used), ("free", free)):
                samples.append(
                    _sample(
                        "crashcap_ops_filesystem_bytes",
                        {"filesystem": name, "state": state},
                        value,
                    )
                )
            for inode_state, inode_value in (
                ("total", inode_total if inode_total is not None else "NaN"),
                (
                    "used",
                    max(0, inode_total - inode_free)
                    if inode_total is not None and inode_free is not None
                    else "NaN",
                ),
                ("free", inode_free if inode_free is not None else "NaN"),
            ):
                inode_samples.append(
                    _sample(
                        "crashcap_ops_filesystem_inodes",
                        {"filesystem": name, "state": inode_state},
                        inode_value,
                    )
                )
        except OSError:
            probe_samples.append(
                _sample("crashcap_ops_filesystem_probe_up", {"filesystem": name}, 0)
            )
            for state in ("total", "used", "free"):
                samples.append(
                    _sample(
                        "crashcap_ops_filesystem_bytes",
                        {"filesystem": name, "state": state},
                        "NaN",
                    )
                )
            for state in ("total", "used", "free"):
                inode_samples.append(
                    _sample(
                        "crashcap_ops_filesystem_inodes",
                        {"filesystem": name, "state": state},
                        "NaN",
                    )
                )
        try:
            logical_bytes = 0
            logical_files = 0
            pending = [path]
            while pending:
                current = pending.pop()
                with os.scandir(current) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                pending.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False):
                                logical_files += 1
                                logical_bytes += int(
                                    entry.stat(follow_symlinks=False).st_size
                                )
                        except OSError:
                            continue
            logical_probe_samples.append(
                _sample("crashcap_ops_volume_scan_up", {"volume": name}, 1)
            )
            logical_bytes_samples.append(
                _sample(
                    "crashcap_ops_volume_logical_bytes", {"volume": name}, logical_bytes
                )
            )
            logical_file_samples.append(
                _sample(
                    "crashcap_ops_volume_file_count", {"volume": name}, logical_files
                )
            )
        except OSError:
            logical_probe_samples.append(
                _sample("crashcap_ops_volume_scan_up", {"volume": name}, 0)
            )
            logical_bytes_samples.append(
                _sample("crashcap_ops_volume_logical_bytes", {"volume": name}, "NaN")
            )
            logical_file_samples.append(
                _sample("crashcap_ops_volume_file_count", {"volume": name}, "NaN")
            )
    return [
        *_block(
            "crashcap_ops_filesystem_probe_up",
            "Whether statvfs succeeded for the read-only filesystem mount.",
            "gauge",
            probe_samples,
        ),
        *_block(
            "crashcap_ops_filesystem_bytes",
            "Filesystem bytes from read-only statvfs mounts.",
            "gauge",
            samples,
        ),
        *_block(
            "crashcap_ops_filesystem_inodes",
            "Filesystem inode counts from read-only statvfs mounts.",
            "gauge",
            inode_samples,
        ),
        *_block(
            "crashcap_ops_volume_scan_up",
            "Whether a read-only lstat walk completed for the named volume.",
            "gauge",
            logical_probe_samples,
        ),
        *_block(
            "crashcap_ops_volume_logical_bytes",
            "Logical bytes of regular files in the named volume; file contents are never read.",
            "gauge",
            logical_bytes_samples,
        ),
        *_block(
            "crashcap_ops_volume_file_count",
            "Count of regular files in the named volume; symlinks are not followed.",
            "gauge",
            logical_file_samples,
        ),
    ]


def _symbolicator_cache_metrics(root: Path, *, now: float | None = None) -> list[str]:
    """Report bounded, read-only downloaded/derived cache inventory.

    A missing or partially unreadable subtree is reported as unavailable rather
    than publishing a partial byte total. Symlinks are never followed.
    """

    observed_at = time.time() if now is None else now
    scan_samples: list[str] = []
    byte_samples: list[str] = []
    file_samples: list[str] = []
    age_samples: list[str] = []
    for cache_kind, directory_names in SYMBOLICATOR_CACHE_DIRECTORIES.items():
        try:
            logical_bytes = 0
            file_count = 0
            oldest_mtime: float | None = None
            with os.scandir(root) as root_entries:
                children = {entry.name: entry for entry in root_entries}
            pending: list[Path] = []
            for directory_name in directory_names:
                entry = children.get(directory_name)
                if entry is None:
                    continue
                if not entry.is_dir(follow_symlinks=False):
                    raise OSError("Symbolicator cache path is not a regular directory")
                pending.append(Path(entry.path))
            while pending:
                current = pending.pop()
                with os.scandir(current) as entries:
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(Path(entry.path))
                        elif entry.is_file(follow_symlinks=False):
                            stats = entry.stat(follow_symlinks=False)
                            file_count += 1
                            logical_bytes += int(stats.st_size)
                            oldest_mtime = (
                                stats.st_mtime
                                if oldest_mtime is None
                                else min(oldest_mtime, stats.st_mtime)
                            )
            oldest_age = max(0.0, observed_at - oldest_mtime) if oldest_mtime else 0.0
            scan_up: int | str = 1
            byte_value: int | str = logical_bytes
            file_value: int | str = file_count
            age_value: str = _float_text(oldest_age)
        except OSError:
            scan_up = 0
            byte_value = "NaN"
            file_value = "NaN"
            age_value = "NaN"
        labels = {"cache_kind": cache_kind}
        scan_samples.append(_sample("crashcap_ops_symbolicator_cache_scan_up", labels, scan_up))
        byte_samples.append(_sample("crashcap_ops_symbolicator_cache_bytes", labels, byte_value))
        file_samples.append(
            _sample("crashcap_ops_symbolicator_cache_file_count", labels, file_value)
        )
        age_samples.append(
            _sample("crashcap_ops_symbolicator_cache_oldest_age_seconds", labels, age_value)
        )
    return [
        *_block(
            "crashcap_ops_symbolicator_cache_scan_up",
            "Whether the read-only scan completed for one Symbolicator cache subtree.",
            "gauge",
            scan_samples,
        ),
        *_block(
            "crashcap_ops_symbolicator_cache_bytes",
            "Logical regular-file bytes in one Symbolicator cache subtree.",
            "gauge",
            byte_samples,
        ),
        *_block(
            "crashcap_ops_symbolicator_cache_file_count",
            "Regular-file count in one Symbolicator cache subtree; symlinks are not followed.",
            "gauge",
            file_samples,
        ),
        *_block(
            "crashcap_ops_symbolicator_cache_oldest_age_seconds",
            "Age of the oldest regular file in one Symbolicator cache subtree; zero when empty.",
            "gauge",
            age_samples,
        ),
    ]


def _cgroup_metrics(root: Path) -> list[str]:
    container = "ops-exporter"
    probe = _read_int(root / "memory.current")
    cpu_stat: dict[str, int] = {}
    try:
        for line in (root / "cpu.stat").read_text(encoding="utf-8").splitlines():
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                key, value = parts
            else:
                key, value = "", ""
            if key and value.isdigit():
                cpu_stat[key] = int(value)
    except OSError:
        pass
    pids_current = _read_int(root / "pids.current")
    supported = int(probe is not None and bool(cpu_stat) and pids_current is not None)
    samples = [
        _sample(
            "crashcap_ops_container_resource_probe_up",
            {"container": container},
            supported,
        ),
        _sample(
            "crashcap_ops_self_cpu_usage_seconds_total",
            {"container": container},
            _float_text(cpu_stat.get("usage_usec", float("nan")) / 1_000_000),
        ),
        _sample(
            "crashcap_ops_self_memory_bytes",
            {"container": container, "state": "current"},
            probe if probe is not None else "NaN",
        ),
        _sample(
            "crashcap_ops_self_memory_bytes",
            {"container": container, "state": "limit"},
            _read_int(root / "memory.max") or "NaN",
        ),
        _sample(
            "crashcap_ops_self_pids",
            {"container": container, "state": "current"},
            pids_current if pids_current is not None else "NaN",
        ),
        _sample(
            "crashcap_ops_self_pids",
            {"container": container, "state": "limit"},
            _read_int(root / "pids.max") or "NaN",
        ),
    ]
    if _read_int(root / "memory.max") == 0:
        samples[3] = _sample(
            "crashcap_ops_self_memory_bytes",
            {"container": container, "state": "limit"},
            0,
        )
    if _read_int(root / "pids.max") == 0:
        samples[5] = _sample(
            "crashcap_ops_self_pids",
            {"container": container, "state": "limit"},
            0,
        )
    return [
        *_block(
            "crashcap_ops_self_resource_probe_up",
            "Whether cgroup v2 resource files were readable for this exporter.",
            "gauge",
            [
                _sample(
                    "crashcap_ops_self_resource_probe_up",
                    {"container": container},
                    supported,
                )
            ],
        ),
        *_block(
            "crashcap_ops_self_cpu_usage_seconds_total",
            "Cgroup CPU usage for the exporter container only.",
            "counter",
            samples[1:2],
        ),
        *_block(
            "crashcap_ops_self_memory_bytes",
            "Cgroup memory current and limit for the exporter container only.",
            "gauge",
            samples[2:4],
        ),
        *_block(
            "crashcap_ops_self_pids",
            "Cgroup process count and limit for the exporter container only.",
            "gauge",
            samples[4:6],
        ),
    ]


def _number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _nested_number(value: object, *keys: str) -> int | None:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _number(current)


def _docker_metrics(
    stats_by_service: dict[str, dict[str, object]] | None,
    docker_status: int,
) -> list[str]:
    service_samples: list[str] = []
    probe_samples: list[str] = []
    cpu_samples: list[str] = []
    memory_samples: list[str] = []
    pids_samples: list[str] = []
    for service in RESOURCE_SERVICES:
        stats = (stats_by_service or {}).get(service)
        cpu_usage = _nested_number(stats, "cpu_stats", "cpu_usage", "total_usage")
        memory_usage = _nested_number(stats, "memory_stats", "usage")
        memory_limit = _nested_number(stats, "memory_stats", "limit")
        pids_current = _nested_number(stats, "pids_stats", "current")
        pids_limit = _nested_number(stats, "pids_stats", "limit")
        supported = int(
            docker_status == HTTPStatus.OK
            and cpu_usage is not None
            and memory_usage is not None
            and memory_limit is not None
            and pids_current is not None
        )
        probe_samples.append(
            _sample(
                "crashcap_ops_container_resource_probe_up",
                {"container": service},
                supported,
            )
        )
        service_samples.append(
            _sample(
                "crashcap_ops_service_resource_supported",
                {"resource": "cpu_memory_pids", "service": service},
                supported,
            )
        )
        cpu_samples.append(
            _sample(
                "crashcap_ops_container_cpu_usage_seconds_total",
                {"container": service},
                _float_text(
                    cpu_usage / 1_000_000_000 if cpu_usage is not None else float("nan")
                ),
            )
        )
        memory_samples.extend(
            [
                _sample(
                    "crashcap_ops_container_memory_bytes",
                    {"container": service, "state": "current"},
                    memory_usage if memory_usage is not None else "NaN",
                ),
                _sample(
                    "crashcap_ops_container_memory_bytes",
                    {"container": service, "state": "limit"},
                    memory_limit if memory_limit is not None else "NaN",
                ),
            ]
        )
        pids_samples.extend(
            [
                _sample(
                    "crashcap_ops_container_pids",
                    {"container": service, "state": "current"},
                    pids_current if pids_current is not None else "NaN",
                ),
                _sample(
                    "crashcap_ops_container_pids",
                    {"container": service, "state": "limit"},
                    pids_limit if pids_limit is not None else "NaN",
                ),
            ]
        )
    return [
        *_block(
            "crashcap_ops_docker_api_up",
            "Whether the allowlisted read-only Docker API proxy responded.",
            "gauge",
            [
                _sample(
                    "crashcap_ops_docker_api_up",
                    {},
                    int(docker_status == HTTPStatus.OK),
                )
            ],
        ),
        *_block(
            "crashcap_ops_container_resource_probe_up",
            "Whether Docker stats contained CPU, memory and pids fields for a service.",
            "gauge",
            probe_samples,
        ),
        *_block(
            "crashcap_ops_service_resource_supported",
            "Whether per-service CPU, memory and pids telemetry was read via the proxy.",
            "gauge",
            service_samples,
        ),
        *_block(
            "crashcap_ops_container_cpu_usage_seconds_total",
            "Cumulative Docker CPU usage for Phase 1 service containers.",
            "counter",
            cpu_samples,
        ),
        *_block(
            "crashcap_ops_container_memory_bytes",
            "Docker memory usage and configured limit for Phase 1 service containers.",
            "gauge",
            memory_samples,
        ),
        *_block(
            "crashcap_ops_container_pids",
            "Docker process count and configured limit for Phase 1 service containers.",
            "gauge",
            pids_samples,
        ),
    ]


def _otel_signal_lines(otel_text: str) -> list[str]:
    return [
        line.lower()
        for line in otel_text.splitlines()
        if line and not line.startswith("#") and not line.startswith("crashcap_ops_")
    ]


def _unsupported_metrics(otel_text: str) -> list[str]:
    signal_lines = _otel_signal_lines(otel_text)
    symbolicator_metric_names = {
        line.split("{", 1)[0].split(maxsplit=1)[0]
        for line in signal_lines
        if line.startswith("symbolicator_")
    }
    cache_event_tokens = {
        "hit": ("cache_hit", "cache_hits"),
        "miss": ("cache_miss", "cache_misses"),
        "refetch": ("refetch", "re_fetch"),
        "eviction": ("eviction", "evictions", "evicted", "_removed"),
    }
    cache_event_supported = {
        event: int(any(token in name for name in symbolicator_metric_names for token in tokens))
        for event, tokens in cache_event_tokens.items()
    }
    symbolicator_cache_supported = int(
        cache_event_supported["hit"] == 1 and cache_event_supported["miss"] == 1
    )
    rustfs_lines = [line for line in signal_lines if "rustfs" in line]
    rustfs_status_known = int(
        any(
            any(
                token in line
                for token in ("status_code", "statuscode", "http_status", "status")
            )
            for line in rustfs_lines
        )
    )
    operation_supported = {
        "head": int(
            any(
                'method="head"' in line
                or "http_request_method=head" in line
                or 'operation="head"' in line
                for line in rustfs_lines
            )
        ),
        "range": int(any("range" in line for line in rustfs_lines)),
        "multipart": int(any("multipart" in line for line in rustfs_lines)),
    }
    queue_samples = [
        _sample("crashcap_ops_queue_oldest_age_seconds", {"queue": queue}, "NaN")
        for queue in QUEUE_NAMES
    ]
    queue_supported = [
        _sample("crashcap_ops_queue_oldest_age_supported", {"queue": queue}, 0)
        for queue in QUEUE_NAMES
    ]
    return [
        *_block(
            "crashcap_ops_queue_oldest_age_seconds",
            (
                "Oldest Dramatiq message age; unavailable because Redis does not expose "
                "enqueue timestamps."
            ),
            "gauge",
            queue_samples,
        ),
        *_block(
            "crashcap_ops_queue_oldest_age_supported",
            "Whether queue oldest age is available for the queue.",
            "gauge",
            queue_supported,
        ),
        *_block(
            "crashcap_ops_symbolicator_cold_cache_supported",
            "Whether Symbolicator exposes both reliable cache-hit and cache-miss counters.",
            "gauge",
            [
                _sample(
                    "crashcap_ops_symbolicator_cold_cache_supported",
                    {},
                    symbolicator_cache_supported,
                )
            ],
        ),
        *_block(
            "crashcap_ops_symbolicator_cache_event_supported",
            "Whether Symbolicator exposes a reliable native counter for the named cache event.",
            "gauge",
            [
                _sample(
                    "crashcap_ops_symbolicator_cache_event_supported",
                    {"event": event},
                    supported,
                )
                for event, supported in cache_event_supported.items()
            ],
        ),
        *_block(
            "crashcap_ops_symbolicator_cold_cache_state",
            "Cold-cache state; unknown when Symbolicator does not expose hit/miss telemetry.",
            "gauge",
            [
                _sample(
                    "crashcap_ops_symbolicator_cold_cache_state",
                    {"state": "unknown"},
                    1,
                )
            ],
        ),
        *_block(
            "crashcap_ops_rustfs_operation_supported",
            "Whether reliable application-level RustFS operation telemetry is available.",
            "gauge",
            [
                _sample(
                    "crashcap_ops_rustfs_operation_supported",
                    {"operation": operation},
                    operation_supported[operation],
                )
                for operation in operation_supported
            ],
        ),
        *_block(
            "crashcap_ops_rustfs_operation_status_known",
            "Whether RustFS 4xx/5xx, HEAD, Range and multipart status is known.",
            "gauge",
            [
                _sample(
                    "crashcap_ops_rustfs_operation_status_known",
                    {"operation": operation},
                    int(operation_supported[operation] and rustfs_status_known),
                )
                for operation in ("head", "range", "multipart")
            ],
        ),
    ]


def _fetch_metrics(url: str, timeout: float) -> tuple[str, int]:
    request = urllib.request.Request(
        url, headers={"Accept": "text/plain; version=0.0.4"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4 * 1024 * 1024)
            return body.decode("utf-8", errors="replace"), int(response.status)
    except (OSError, urllib.error.URLError):
        return "", 0


def _fetch_json(url: str, timeout: float) -> tuple[object, int]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(16 * 1024 * 1024)
            return json.loads(body.decode("utf-8")), int(response.status)
    except (OSError, TypeError, ValueError, urllib.error.URLError):
        return None, 0


def _fetch_docker_stats(
    url: str | None, timeout: float
) -> tuple[dict[str, dict[str, object]], int]:
    if not url:
        return {}, 0
    base = url.rstrip("/")
    containers, status = _fetch_json(f"{base}/containers/json?all=1", timeout)
    if status != HTTPStatus.OK or not isinstance(containers, list):
        return {}, status
    stats_by_service: dict[str, dict[str, object]] = {}
    request_specs: list[tuple[str, str]] = []
    for container in containers:
        if not isinstance(container, dict):
            continue
        container_id = container.get("Id")
        labels = container.get("Labels")
        if not isinstance(container_id, str) or not DOCKER_ID.fullmatch(container_id):
            continue
        if not isinstance(labels, dict):
            continue
        service = labels.get("com.docker.compose.service")
        if not isinstance(service, str) or service not in RESOURCE_SERVICES:
            continue
        request_specs.append((service, container_id))
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(
                _fetch_json,
                f"{base}/containers/{container_id}/stats?stream=false",
                timeout,
            ): service
            for service, container_id in request_specs
        }
        for future in as_completed(futures):
            stats, stats_status = future.result()
            service = futures[future]
            if stats_status == HTTPStatus.OK and isinstance(stats, dict):
                stats_by_service[service] = stats
    return stats_by_service, status


def render_metrics(
    api_text: str,
    *,
    api_status: int = 200,
    otel_text: str = "",
    otel_status: int = 0,
    retention_text: str = "",
    retention_status: int = 0,
    filesystems: dict[str, Path] | None = None,
    cgroup_root: Path = Path("/sys/fs/cgroup"),
    docker_stats: dict[str, dict[str, object]] | None = None,
    docker_status: int = 0,
) -> str:
    lines = [api_text.rstrip()] if api_text.strip() else []
    lines.extend(
        _block(
            "crashcap_ops_api_scrape_up",
            "Whether the API Prometheus endpoint was scraped successfully.",
            "gauge",
            [
                _sample(
                    "crashcap_ops_api_scrape_up", {}, int(api_status == HTTPStatus.OK)
                )
            ],
        )
    )
    if otel_text.strip():
        lines.append(otel_text.rstrip())
    lines.extend(
        _block(
            "crashcap_ops_otel_scrape_up",
            (
                "Whether the internal OpenTelemetry collector Prometheus endpoint was "
                "scraped successfully."
            ),
            "gauge",
            [
                _sample(
                    "crashcap_ops_otel_scrape_up", {}, int(otel_status == HTTPStatus.OK)
                )
            ],
        )
    )
    filtered_retention = _filter_metric_families(retention_text, RETENTION_METRIC_PREFIXES)
    if filtered_retention:
        lines.append(filtered_retention)
    lines.extend(
        _block(
            "crashcap_ops_retention_scrape_up",
            "Whether the internal retention Prometheus endpoint was scraped successfully.",
            "gauge",
            [
                _sample(
                    "crashcap_ops_retention_scrape_up",
                    {},
                    int(retention_status == HTTPStatus.OK),
                )
            ],
        )
    )
    selected_filesystems = filesystems or _parse_filesystems(None)
    lines.extend(_filesystem_metrics(selected_filesystems))
    symbolicator_cache_root = selected_filesystems.get("symbolicator_cache")
    if symbolicator_cache_root is not None:
        lines.extend(_symbolicator_cache_metrics(symbolicator_cache_root))
    lines.extend(_cgroup_metrics(cgroup_root))
    lines.extend(_docker_metrics(docker_stats, docker_status))
    lines.extend(_unsupported_metrics(otel_text))
    return "\n".join(line for line in lines if line) + "\n"


class ExporterHandler(BaseHTTPRequestHandler):
    server: ExporterServer

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._write(HTTPStatus.OK, b"ok\n", "text/plain; charset=utf-8")
            return
        if self.path != "/metrics":
            self._write(
                HTTPStatus.NOT_FOUND, b"not found\n", "text/plain; charset=utf-8"
            )
            return
        api_text, status = _fetch_metrics(
            self.server.api_url, self.server.scrape_timeout
        )
        otel_text, otel_status = (
            _fetch_metrics(self.server.otel_url, self.server.scrape_timeout)
            if self.server.otel_url
            else ("", 0)
        )
        retention_text, retention_status = (
            _fetch_metrics(self.server.retention_url, self.server.scrape_timeout)
            if self.server.retention_url
            else ("", 0)
        )
        docker_stats, docker_status = _fetch_docker_stats(
            self.server.docker_api_url, self.server.scrape_timeout
        )
        body = render_metrics(
            api_text,
            api_status=status,
            otel_text=otel_text,
            otel_status=otel_status,
            retention_text=retention_text,
            retention_status=retention_status,
            filesystems=self.server.filesystems,
            cgroup_root=self.server.cgroup_root,
            docker_stats=docker_stats,
            docker_status=docker_status,
        ).encode("utf-8")
        self._write(HTTPStatus.OK, body, "text/plain; version=0.0.4; charset=utf-8")

    def _write(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class ExporterServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        *,
        api_url: str,
        timeout: float,
        filesystems: dict[str, Path],
        cgroup_root: Path,
        docker_api_url: str | None,
        otel_url: str | None,
        retention_url: str | None,
    ) -> None:
        super().__init__(address, ExporterHandler)
        self.api_url = api_url
        self.scrape_timeout = timeout
        self.filesystems = filesystems
        self.cgroup_root = cgroup_root
        self.docker_api_url = docker_api_url
        self.otel_url = otel_url
        self.retention_url = retention_url


def main() -> None:
    host = os.environ.get("OPS_EXPORTER_BIND", "0.0.0.0")
    port = int(os.environ.get("OPS_EXPORTER_PORT", "9108"))
    timeout = float(os.environ.get("OPS_EXPORTER_TIMEOUT_SECONDS", "3"))
    server = ExporterServer(
        (host, port),
        api_url=os.environ.get("OPS_EXPORTER_API_URL", "http://api:8000/metrics"),
        timeout=timeout,
        filesystems=_parse_filesystems(os.environ.get("OPS_EXPORTER_FILESYSTEMS")),
        cgroup_root=Path(os.environ.get("OPS_EXPORTER_CGROUP_ROOT", "/sys/fs/cgroup")),
        docker_api_url=os.environ.get("OPS_EXPORTER_DOCKER_API_URL"),
        otel_url=os.environ.get("OPS_EXPORTER_OTEL_URL"),
        retention_url=os.environ.get("OPS_EXPORTER_RETENTION_URL"),
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
