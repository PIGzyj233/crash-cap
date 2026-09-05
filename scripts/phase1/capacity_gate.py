#!/usr/bin/env python3
"""Run the Phase 1 capacity gate against real API/Compose state.

The default mode is a side-effect-free plan.  ``--execute`` is required before
the runner can call the API, and execution requires an external occurrence
manifest so the runner never creates synthetic SQLite or in-memory evidence.
The upload workload creates unique real Dump Blobs through the existing
presigned-upload API.  The force-reprocess workload remains available for a
small queue exercise and is never eligible for a P1-G10 PASS.
"""

from __future__ import annotations

import argparse
import csv
import http.client
import json
import math
import re
import sys
import threading
import time
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

SCHEMA_VERSION = "phase1.capacity-gate.v1"
TARGET_TASKS = 100
TARGET_CONCURRENCY = 5
SMALL_MAX_BYTES = 64 * 1024 * 1024
LARGE_MAX_BYTES = 256 * 1024 * 1024
SMALL_BUCKET = "le_64MiB"
LARGE_BUCKET = "64_256MiB"
UNKNOWN_BUCKET = "unknown"
OVER_LIMIT_BUCKET = "over_256MiB"
BUCKETS = (SMALL_BUCKET, LARGE_BUCKET)
P95_TARGET_MS = {SMALL_BUCKET: 10 * 60 * 1000, LARGE_BUCKET: 20 * 60 * 1000}
REQUIRED_QUEUES = frozenset({"verify", "ingest", "dump-small", "dump-large"})
TERMINAL_STATUSES = frozenset(
    {"COMPLETE", "PARTIAL", "FAILED", "REJECTED", "CANCELLED", "TIMEOUT", "OOM"}
)
SUCCESS_STATUSES = frozenset({"COMPLETE", "PARTIAL"})
QUEUE_METRIC_RE = re.compile(
    r"^crashcap_queue_depth\{(?P<labels>[^}]*)\}\s+(?P<value>-?(?:\d+(?:\.\d*)?|\.\d+))"
)


@dataclass(frozen=True, slots=True)
class CapacityTask:
    task_id: str
    occurrence_id: str | None = None
    workspace_id: str | None = None
    payload_path: Path | None = None
    filename: str | None = None
    capture_profile: str = "rich-crash"
    reported_build_id: str | None = None
    size_bytes: int | None = None
    manifest_size_bytes: int | None = None
    label: str | None = None


class ApiError(RuntimeError):
    """An API failure whose message is deliberately safe for evidence output."""

    def __init__(self, kind: str, status: int | None = None) -> None:
        self.kind = kind
        self.status = status
        suffix = f" (HTTP {status})" if status is not None else ""
        super().__init__(f"{kind}{suffix}")


class ApiClient:
    """Minimal anonymous JSON client; response bodies are never echoed on error."""

    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = normalize_api_base_url(base_url)
        self.timeout_seconds = timeout_seconds

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        expected_status: set[int] | None = None,
    ) -> tuple[int, bytes]:
        url = self.base_url if not path else f"{self.base_url}/{path.lstrip('/')}"
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload else None
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(  # noqa: S310 - constructor receives a validated HTTP-only URL
            url, data=data, headers=headers, method=method
        )
        try:
            with urlopen(  # noqa: S310 - base URL is validated as HTTP-only at startup
                request, timeout=self.timeout_seconds
            ) as response:
                status = int(response.status)
                body = response.read()
        except HTTPError as exc:
            raise ApiError("http_error", int(exc.code)) from None
        except (OSError, URLError, TimeoutError):
            raise ApiError("network_error") from None
        if expected_status is not None and status not in expected_status:
            raise ApiError("unexpected_http_status", status)
        return status, body

    def _json(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
        expected_status: set[int] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        status, body = self._request(method, path, payload, expected_status)
        try:
            decoded = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError("invalid_json_response", status) from None
        if not isinstance(decoded, dict):
            raise ApiError("invalid_json_object", status)
        return status, decoded

    def get_occurrence(self, occurrence_id: str) -> dict[str, Any]:
        _, body = self._json(
            "GET", f"occurrences/{quote(occurrence_id, safe='')}", expected_status={200}
        )
        return body

    def init_dump_upload(
        self,
        workspace_id: str,
        *,
        filename: str,
        size_bytes: int,
        capture_profile: str,
        reported_build_id: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "filename": filename,
            "size": size_bytes,
            "capture_profile": capture_profile,
        }
        if reported_build_id:
            payload["reported_build_id"] = reported_build_id
        _, body = self._json(
            "POST",
            f"workspaces/{quote(workspace_id, safe='')}/dumps/uploads:init",
            payload,
            expected_status={201},
        )
        return body

    def complete_upload(
        self,
        upload_id: str,
        *,
        multipart_upload_id: str | None = None,
        parts: Sequence[Mapping[str, Any]] = (),
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"parts": list(parts)}
        if multipart_upload_id:
            payload["multipart_upload_id"] = multipart_upload_id
        _, body = self._json(
            "POST",
            f"uploads/{quote(upload_id, safe='')}/complete",
            payload,
            expected_status={200},
        )
        return body

    def get_upload(self, upload_id: str) -> dict[str, Any]:
        _, body = self._json("GET", f"uploads/{quote(upload_id, safe='')}", expected_status={200})
        return body

    def reprocess(self, occurrence_id: str) -> dict[str, Any]:
        _, body = self._json(
            "POST",
            f"occurrences/{quote(occurrence_id, safe='')}/reprocess",
            {"force": True},
            expected_status={202},
        )
        return body

    def get_analysis(self, occurrence_id: str, run_id: str) -> dict[str, Any]:
        _, body = self._json(
            "GET",
            f"occurrences/{quote(occurrence_id, safe='')}/analysis?run_id={quote(run_id, safe='')}",
            expected_status={200},
        )
        return body

    def get_metrics(self) -> str:
        status, body = self._request("GET", "", expected_status={200})
        try:
            return body.decode("utf-8")
        except UnicodeDecodeError:
            raise ApiError("invalid_metrics_response", status) from None


def stream_upload_file(
    url: str,
    method: str,
    headers: Mapping[str, Any],
    path: Path,
    *,
    offset: int = 0,
    length: int | None = None,
) -> str | None:
    """Stream one presigned PUT without loading a large dump into memory."""

    parts = urlsplit(url)
    if parts.scheme != "http" or not parts.netloc:
        raise ValueError("presigned upload URL must be an http URL")
    if parts.username or parts.password:
        raise ValueError("presigned upload URL must not contain credentials")
    connection = http.client.HTTPConnection(parts.netloc, timeout=120)
    target = urlunsplit(("", "", parts.path or "/", parts.query, ""))
    actual_length = path.stat().st_size - offset if length is None else length
    if actual_length < 0:
        raise ValueError("presigned upload range exceeds payload size")
    try:
        connection.putrequest(method, target)
        for key, value in headers.items():
            normalized = str(key).lower()
            if normalized not in {"host", "content-length"}:
                connection.putheader(str(key), str(value))
        connection.putheader("Content-Length", str(actual_length))
        connection.endheaders()
        with path.open("rb") as source:
            source.seek(offset)
            remaining = actual_length
            while remaining:
                chunk = source.read(min(8 * 1024 * 1024, remaining))
                if not chunk:
                    raise ValueError("payload ended before declared upload length")
                connection.send(chunk)
                remaining -= len(chunk)
        response = connection.getresponse()
        response.read()
        if not 200 <= response.status < 300:
            raise ApiError("object_upload_http_error", response.status)
        return response.getheader("ETag") or response.getheader("etag")
    except (OSError, http.client.HTTPException, TimeoutError):
        raise ApiError("object_upload_network_error") from None
    finally:
        connection.close()


def normalize_api_base_url(value: str) -> str:
    """Validate an HTTP API URL and reject embedded credentials/query parameters."""

    parts = urlsplit(value.strip())
    if parts.scheme != "http" or not parts.netloc:
        raise ValueError("base URL must be an http URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("base URL must not contain credentials, query parameters, or fragments")
    path = parts.path.rstrip("/")
    if path in {"", "/"}:
        path = "/api/v3"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def normalize_metrics_url(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme != "http" or not parts.netloc:
        raise ValueError("metrics URL must be an http URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("metrics URL must not contain credentials, query parameters, or fragments")
    path = parts.path.rstrip("/") or "/metrics"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


def derive_metrics_url(api_base_url: str) -> str:
    parts = urlsplit(normalize_api_base_url(api_base_url))
    path = parts.path.rstrip("/")
    path = path.removesuffix("/api/v3")
    return normalize_metrics_url(
        urlunsplit((parts.scheme, parts.netloc, f"{path}/metrics", "", ""))
    )


def classify_bucket(size_bytes: int | None) -> str:
    if size_bytes is None:
        return UNKNOWN_BUCKET
    if size_bytes < 0:
        raise ValueError("size_bytes must not be negative")
    if size_bytes <= SMALL_MAX_BYTES:
        return SMALL_BUCKET
    if size_bytes <= LARGE_MAX_BYTES:
        return LARGE_BUCKET
    return OVER_LIMIT_BUCKET


def _parse_size(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise TypeError("size_bytes must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("size_bytes must be an integer") from exc
    if parsed < 0:
        raise ValueError("size_bytes must not be negative")
    return parsed


def _manifest_rows(path: Path) -> list[Mapping[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        rows = list(csv.DictReader(text.splitlines()))
    else:
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            rows = [
                json.loads(line)
                for line in text.splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
        else:
            if isinstance(document, dict):
                rows = document.get("tasks", document.get("samples", []))
            else:
                rows = document
    if not isinstance(rows, list):
        raise TypeError("manifest must contain a task list")
    if not all(isinstance(row, Mapping) for row in rows):
        raise ValueError("manifest task entries must be objects")
    return rows


def load_manifest(path: Path, *, workload: str = "reprocess") -> list[CapacityTask]:
    rows = _manifest_rows(path)
    tasks: list[CapacityTask] = []
    seen: set[str] = set()
    for index, row in enumerate(rows, 1):
        occurrence_value = row.get("occurrence_id", row.get("id"))
        occurrence_id = (
            occurrence_value.strip()
            if isinstance(occurrence_value, str) and occurrence_value.strip()
            else None
        )
        workspace_value = row.get("workspace_id")
        workspace_id = (
            workspace_value.strip()
            if isinstance(workspace_value, str) and workspace_value.strip()
            else None
        )
        payload_value = row.get("payload_path", row.get("file", row.get("path")))
        payload_path = Path(str(payload_value)).expanduser() if payload_value else None
        if workload == "reprocess":
            if occurrence_id is None:
                raise ValueError(f"manifest task {index} is missing occurrence_id")
            task_id = occurrence_id
        else:
            if workspace_id is None or payload_path is None:
                raise ValueError(
                    f"upload manifest task {index} requires workspace_id and payload_path"
                )
            if not payload_path.is_absolute():
                payload_path = (path.parent / payload_path).resolve()
            task_id_value = row.get("task_id", row.get("label"))
            task_id = (
                str(task_id_value).strip()
                if isinstance(task_id_value, str) and task_id_value.strip()
                else f"task-{index:04d}"
            )
        if task_id in seen:
            raise ValueError(f"manifest contains duplicate task_id at task {index}")
        seen.add(task_id)
        raw_size = row.get("size_bytes", row.get("size", row.get("blob_size_bytes")))
        size_bytes = _parse_size(raw_size)
        if workload == "upload" and payload_path is not None:
            try:
                actual_size = payload_path.stat().st_size
            except OSError as exc:
                raise ValueError(f"cannot stat upload payload for task {index}") from exc
            if size_bytes is not None and size_bytes != actual_size:
                raise ValueError(f"manifest size differs from payload for task {index}")
            size_bytes = actual_size
        label_value = row.get("label", row.get("name"))
        label = str(label_value) if label_value is not None else None
        tasks.append(
            CapacityTask(
                task_id=task_id,
                occurrence_id=occurrence_id,
                workspace_id=workspace_id,
                payload_path=payload_path,
                filename=str(row.get("filename")) if row.get("filename") else None,
                capture_profile=str(row.get("capture_profile", "rich-crash")),
                reported_build_id=(
                    str(row.get("reported_build_id")) if row.get("reported_build_id") else None
                ),
                size_bytes=size_bytes,
                manifest_size_bytes=size_bytes,
                label=label,
            )
        )
    return tasks


def parse_queue_depths(metrics_text: str) -> dict[str, float]:
    depths: dict[str, float] = {}
    for line in metrics_text.splitlines():
        match = QUEUE_METRIC_RE.match(line.strip())
        if match is None:
            continue
        labels = dict(re.findall(r'([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"', match["labels"]))
        queue = labels.get("queue")
        if queue:
            depths[queue] = max(0.0, float(match["value"]))
    return depths


class QueueMonitor:
    def __init__(self, client: ApiClient, interval_seconds: float) -> None:
        self.client = client
        self.interval_seconds = interval_seconds
        self.samples: list[dict[str, Any]] = []
        self.errors: Counter[str] = Counter()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        try:
            depths = parse_queue_depths(self.client.get_metrics())
        except ApiError as exc:
            with self._lock:
                self.errors[exc.kind] += 1
            return
        if not depths:
            with self._lock:
                self.errors["queue_metric_missing"] += 1
            return
        missing_queues = REQUIRED_QUEUES - set(depths)
        if missing_queues:
            with self._lock:
                self.errors["required_queue_metric_missing"] += 1
            return
        with self._lock:
            self.samples.append(
                {
                    "observed_at": datetime.now(UTC).isoformat(),
                    "depth_by_queue": depths,
                    "depth_total": round(sum(depths.values()), 3),
                }
            )

    def _run(self) -> None:
        while not self._stop.is_set():
            self._sample()
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        self._sample()
        self._thread = threading.Thread(
            target=self._run, name="phase1-capacity-metrics", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds + 1.0))
        self._sample()

    def report(self, local_peak: int, requested_concurrency: int) -> dict[str, Any]:
        with self._lock:
            samples = list(self.samples)
            errors = dict(sorted(self.errors.items()))
        peak_by_queue: dict[str, float] = {}
        peak_total = 0.0
        observed_queues: set[str] = set()
        for sample in samples:
            peak_total = max(peak_total, float(sample["depth_total"]))
            observed_queues.update(sample["depth_by_queue"])
            for queue, depth in sample["depth_by_queue"].items():
                peak_by_queue[queue] = max(peak_by_queue.get(queue, 0.0), float(depth))
        return {
            "status": "PROVEN"
            if samples and not errors and REQUIRED_QUEUES.issubset(observed_queues)
            else "NOT_PROVEN",
            "sample_count": len(samples),
            "monitor_errors": errors,
            "peak_by_queue": dict(sorted(peak_by_queue.items())),
            "peak_total": int(peak_total) if peak_total.is_integer() else peak_total,
            "observed_queue_names": sorted(observed_queues),
            "requested_concurrency": requested_concurrency,
            "local_in_flight_peak": local_peak,
            "samples": samples,
        }


class InFlightTracker:
    def __init__(self) -> None:
        self._active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def enter(self) -> None:
        with self._lock:
            self._active += 1
            self.peak = max(self.peak, self._active)

    def leave(self) -> None:
        with self._lock:
            self._active -= 1


def _safe_error(error: BaseException) -> str:
    if isinstance(error, ApiError):
        return error.kind if error.status is None else f"{error.kind}_{error.status}"
    return type(error).__name__


def execute_one(
    client: ApiClient,
    task: CapacityTask,
    tracker: InFlightTracker,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    tracker.enter()
    started_at = datetime.now(UTC)
    started_mono = time.monotonic()
    run_id: str | None = None
    status: str | None = None
    accepted = False
    error: str | None = None
    worker_duration_ms: float | None = None
    digest: str | None = None
    try:
        if task.occurrence_id is None:
            raise ValueError("missing_occurrence_id")
        response = client.reprocess(task.occurrence_id)
        run_id_value = response.get("id")
        if not isinstance(run_id_value, str) or not run_id_value:
            error = "missing_run_id"
        else:
            run_id = run_id_value
            accepted = True
            deadline = time.monotonic() + timeout_seconds
            while True:
                detail = client.get_occurrence(task.occurrence_id)
                latest = detail.get("latest_attempt")
                if isinstance(latest, Mapping) and latest.get("id") == run_id:
                    candidate_status = latest.get("status")
                    if isinstance(candidate_status, str):
                        status = candidate_status
                    if status in TERMINAL_STATUSES:
                        duration = latest.get("duration_ms")
                        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                            worker_duration_ms = float(duration)
                        break
                if time.monotonic() >= deadline:
                    error = "poll_timeout"
                    break
                time.sleep(max(0.01, min(poll_interval_seconds, deadline - time.monotonic())))
            if status in SUCCESS_STATUSES:
                try:
                    analysis = client.get_analysis(task.occurrence_id, run_id)
                    engine = analysis.get("engine")
                    if isinstance(engine, Mapping) and isinstance(
                        engine.get("core_image_digest"), str
                    ):
                        digest = str(engine["core_image_digest"])
                except ApiError:
                    error = error or "analysis_fetch_failed"
    except (ApiError, OSError, TypeError, ValueError) as exc:
        error = error or _safe_error(exc)
    finally:
        tracker.leave()
    finished_at = datetime.now(UTC)
    return {
        "task_id": task.task_id,
        "occurrence_id": task.occurrence_id,
        "workspace_id": task.workspace_id,
        "blob_id": None,
        "sha256": None,
        "label": task.label,
        "size_bytes": task.size_bytes,
        "manifest_size_bytes": task.manifest_size_bytes,
        "bucket": classify_bucket(task.size_bytes),
        "accepted": accepted,
        "upload_status": "NOT_APPLICABLE",
        "duplicate": None,
        "terminal": status in TERMINAL_STATUSES,
        "status": status or "NOT_STARTED",
        "run_id": run_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": round((time.monotonic() - started_mono) * 1000, 3),
        "worker_duration_ms": worker_duration_ms,
        "core_image_digest": digest,
        "error": error,
    }


def execute_upload_one(
    client: ApiClient,
    task: CapacityTask,
    tracker: InFlightTracker,
    *,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    tracker.enter()
    started_at = datetime.now(UTC)
    started_mono = time.monotonic()
    upload_id: str | None = None
    occurrence_id: str | None = None
    blob_id: str | None = None
    upload_status: str | None = None
    run_id: str | None = None
    status: str | None = None
    worker_duration_ms: float | None = None
    digest: str | None = None
    duplicate: bool | None = None
    verified_sha256: str | None = None
    error: str | None = None
    try:
        if task.workspace_id is None or task.payload_path is None:
            raise ValueError("missing_upload_manifest_fields")
        filename = task.filename or task.payload_path.name
        initialized = client.init_dump_upload(
            task.workspace_id,
            filename=filename,
            size_bytes=task.size_bytes or 0,
            capture_profile=task.capture_profile,
            reported_build_id=task.reported_build_id,
        )
        upload_id_value = initialized.get("upload_id")
        if not isinstance(upload_id_value, str) or not upload_id_value:
            raise ValueError("missing_upload_id")
        upload_id = upload_id_value
        multipart = initialized.get("multipart")
        if isinstance(multipart, Mapping):
            multipart_id = multipart.get("upload_id")
            parts = multipart.get("parts")
            if not isinstance(multipart_id, str) or not isinstance(parts, list) or not parts:
                raise ValueError("invalid_multipart_presign")
            completed_parts: list[dict[str, Any]] = []
            offset = 0
            for part in parts:
                if not isinstance(part, Mapping) or not isinstance(part.get("url"), str):
                    raise TypeError("invalid_multipart_part")
                part_number = part.get("part_number")
                if not isinstance(part_number, int):
                    raise TypeError("invalid_multipart_part_number")
                length = min(64 * 1024 * 1024, (task.size_bytes or 0) - offset)
                if length <= 0:
                    raise ValueError("multipart_part_size_mismatch")
                etag = stream_upload_file(
                    str(part["url"]),
                    "PUT",
                    {},
                    task.payload_path,
                    offset=offset,
                    length=length,
                )
                if not etag:
                    raise ValueError("missing_multipart_etag")
                completed_parts.append({"part_number": part_number, "etag": etag})
                offset += length
            if offset != task.size_bytes:
                raise ValueError("multipart_payload_size_mismatch")
            completion = client.complete_upload(
                upload_id, multipart_upload_id=multipart_id, parts=completed_parts
            )
        else:
            upload_url = initialized.get("url")
            method = initialized.get("method", "PUT")
            headers = initialized.get("headers", {})
            if (
                not isinstance(upload_url, str)
                or not isinstance(method, str)
                or not isinstance(headers, Mapping)
            ):
                raise TypeError("invalid_presigned_upload")
            stream_upload_file(upload_url, method, headers, task.payload_path)
            completion = client.complete_upload(upload_id)
        upload_status_value = completion.get("verification_status", completion.get("status"))
        if isinstance(upload_status_value, str):
            upload_status = upload_status_value
        deadline = time.monotonic() + timeout_seconds
        while True:
            upload_view = client.get_upload(upload_id)
            upload_status_value = upload_view.get("verification_status", upload_view.get("status"))
            if isinstance(upload_status_value, str):
                upload_status = upload_status_value
            if isinstance(upload_view.get("occurrence_id"), str):
                occurrence_id = str(upload_view["occurrence_id"])
            if isinstance(upload_view.get("blob_id"), str):
                blob_id = str(upload_view["blob_id"])
            if isinstance(upload_view.get("duplicate"), bool):
                duplicate = bool(upload_view["duplicate"])
            if isinstance(upload_view.get("sha256"), str):
                verified_sha256 = str(upload_view["sha256"])
            if upload_status in {"REJECTED", "QUARANTINED"}:
                error = f"upload_{str(upload_status).lower()}"
                break
            if upload_status == "ACCEPTED" and occurrence_id:
                break
            if time.monotonic() >= deadline:
                error = "upload_poll_timeout"
                break
            time.sleep(max(0.01, min(poll_interval_seconds, deadline - time.monotonic())))
        if upload_status == "ACCEPTED" and occurrence_id:
            deadline = time.monotonic() + timeout_seconds
            while True:
                detail = client.get_occurrence(occurrence_id)
                latest = detail.get("latest_attempt")
                if isinstance(latest, Mapping):
                    latest_id = latest.get("id")
                    if isinstance(latest_id, str):
                        run_id = latest_id
                    candidate_status = latest.get("status")
                    if isinstance(candidate_status, str):
                        status = candidate_status
                    if status in TERMINAL_STATUSES:
                        duration = latest.get("duration_ms")
                        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
                            worker_duration_ms = float(duration)
                        break
                if time.monotonic() >= deadline:
                    error = "poll_timeout"
                    break
                time.sleep(max(0.01, min(poll_interval_seconds, deadline - time.monotonic())))
            if status in SUCCESS_STATUSES and run_id:
                try:
                    analysis = client.get_analysis(occurrence_id, run_id)
                    engine = analysis.get("engine")
                    if isinstance(engine, Mapping) and isinstance(
                        engine.get("core_image_digest"), str
                    ):
                        digest = str(engine["core_image_digest"])
                except ApiError:
                    error = error or "analysis_fetch_failed"
    except (ApiError, OSError, TypeError, ValueError) as exc:
        error = error or _safe_error(exc)
    finally:
        tracker.leave()
    finished_at = datetime.now(UTC)
    analysis_terminal = status in TERMINAL_STATUSES
    pipeline_accepted = upload_status == "ACCEPTED" and analysis_terminal
    return {
        "task_id": task.task_id,
        "occurrence_id": occurrence_id,
        "workspace_id": task.workspace_id,
        "blob_id": blob_id,
        "sha256": verified_sha256,
        "label": task.label,
        "size_bytes": task.size_bytes,
        "manifest_size_bytes": task.manifest_size_bytes,
        "bucket": classify_bucket(task.size_bytes),
        "accepted": pipeline_accepted,
        "upload_status": upload_status or "NOT_STARTED",
        "duplicate": duplicate,
        "terminal": analysis_terminal,
        "status": status or (f"UPLOAD_{upload_status}" if upload_status else "NOT_STARTED"),
        "run_id": run_id,
        "upload_id": upload_id,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_ms": round((time.monotonic() - started_mono) * 1000, 3),
        "worker_duration_ms": worker_duration_ms,
        "core_image_digest": digest,
        "error": error,
    }


def execute_tasks(
    client: ApiClient,
    tasks: Sequence[CapacityTask],
    *,
    workload: str = "reprocess",
    concurrency: int,
    timeout_seconds: float,
    poll_interval_seconds: float,
) -> tuple[list[dict[str, Any]], InFlightTracker]:
    tracker = InFlightTracker()
    results: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="phase1-capacity") as pool:
        futures = {
            pool.submit(
                execute_upload_one if workload == "upload" else execute_one,
                client,
                task,
                tracker,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            ): task
            for task in tasks
        }
        for future in as_completed(futures):
            task = futures[future]
            try:
                results[task.task_id] = future.result()
            except Exception as exc:  # noqa: BLE001 - preserve one result per submitted task
                results[task.task_id] = {
                    "task_id": task.task_id,
                    "occurrence_id": task.occurrence_id,
                    "workspace_id": task.workspace_id,
                    "blob_id": None,
                    "sha256": None,
                    "label": task.label,
                    "size_bytes": task.size_bytes,
                    "manifest_size_bytes": task.manifest_size_bytes,
                    "bucket": classify_bucket(task.size_bytes),
                    "accepted": False,
                    "upload_status": "NOT_STARTED",
                    "duplicate": None,
                    "terminal": False,
                    "status": "RUNNER_ERROR",
                    "run_id": None,
                    "started_at": None,
                    "finished_at": None,
                    "duration_ms": None,
                    "worker_duration_ms": None,
                    "core_image_digest": None,
                    "error": _safe_error(exc),
                }
    return [results[task.task_id] for task in tasks], tracker


def preflight_tasks(
    client: ApiClient, tasks: Sequence[CapacityTask]
) -> tuple[list[CapacityTask], list[dict[str, str]]]:
    prepared: list[CapacityTask] = []
    errors: list[dict[str, str]] = []
    for task in tasks:
        if task.occurrence_id is None:
            errors.append({"task_id": task.task_id, "error": "missing_occurrence_id"})
            continue
        try:
            detail = client.get_occurrence(task.occurrence_id)
            blob = detail.get("blob")
            if not isinstance(blob, Mapping):
                raise TypeError("missing_blob")
            actual_size = _parse_size(blob.get("size"))
            if actual_size is None:
                raise ValueError("missing_blob_size")
            prepared.append(replace(task, size_bytes=actual_size))
        except (ApiError, ValueError, TypeError) as exc:
            errors.append({"task_id": task.task_id, "error": _safe_error(exc)})
    return prepared, errors


def preflight_upload_tasks(
    tasks: Sequence[CapacityTask],
) -> tuple[list[CapacityTask], list[dict[str, str]]]:
    prepared: list[CapacityTask] = []
    errors: list[dict[str, str]] = []
    for task in tasks:
        if task.workspace_id is None or task.payload_path is None:
            errors.append({"task_id": task.task_id, "error": "missing_upload_manifest_fields"})
            continue
        try:
            if not task.payload_path.is_file():
                raise ValueError("payload_not_found")
            size_bytes = task.payload_path.stat().st_size
            if size_bytes <= 0:
                raise ValueError("payload_empty")
            if classify_bucket(size_bytes) not in BUCKETS:
                raise ValueError("size_outside_phase1_buckets")
            prepared.append(replace(task, size_bytes=size_bytes, manifest_size_bytes=size_bytes))
        except (OSError, TypeError, ValueError) as exc:
            errors.append({"task_id": task.task_id, "error": _safe_error(exc)})
    return prepared, errors


def percentile(values: Iterable[float], percentile_value: float) -> float | None:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return None
    if not 0 <= percentile_value <= 100:
        raise ValueError("percentile must be between 0 and 100")
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * percentile_value / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    value = ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
    return round(value, 3)


def summarize_buckets(
    tasks: Sequence[CapacityTask], results: Sequence[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    result_by_id = {str(result["task_id"]): result for result in results}
    summary: dict[str, dict[str, Any]] = {}
    for bucket in BUCKETS:
        bucket_tasks = [task for task in tasks if classify_bucket(task.size_bytes) == bucket]
        bucket_results = [
            result
            for task in bucket_tasks
            if (result := result_by_id.get(task.task_id)) is not None
        ]
        durations = [
            float(result["duration_ms"])
            for result in bucket_results
            if isinstance(result.get("duration_ms"), (int, float))
            and not isinstance(result.get("duration_ms"), bool)
        ]
        terminal_durations = [
            float(result["duration_ms"])
            for result in bucket_results
            if result.get("terminal")
            and isinstance(result.get("duration_ms"), (int, float))
            and not isinstance(result.get("duration_ms"), bool)
        ]
        summary[bucket] = {
            "sample_count": len(bucket_tasks),
            "result_count": len(bucket_results),
            "terminal_count": sum(bool(result.get("terminal")) for result in bucket_results),
            "duration_sample_count": len(durations),
            "terminal_duration_sample_count": len(terminal_durations),
            "status_counts": dict(
                sorted(Counter(str(result["status"]) for result in bucket_results).items())
            ),
            "p50_ms": percentile(terminal_durations, 50),
            "p95_ms": percentile(terminal_durations, 95),
            "p99_ms": percentile(terminal_durations, 99),
            "p95_target_ms": P95_TARGET_MS[bucket],
        }
    return summary


def size_summary(tasks: Sequence[CapacityTask]) -> dict[str, Any]:
    sizes = [task.size_bytes for task in tasks if task.size_bytes is not None]
    bucket_counts = Counter(classify_bucket(task.size_bytes) for task in tasks)
    return {
        "task_count": len(tasks),
        "known_size_count": len(sizes),
        "unknown_size_count": bucket_counts.get(UNKNOWN_BUCKET, 0),
        "over_limit_count": bucket_counts.get(OVER_LIMIT_BUCKET, 0),
        "bucket_counts": {
            bucket: bucket_counts.get(bucket, 0)
            for bucket in (*BUCKETS, UNKNOWN_BUCKET, OVER_LIMIT_BUCKET)
        },
        "min_bytes": min(sizes) if sizes else None,
        "max_bytes": max(sizes) if sizes else None,
        "total_bytes": sum(sizes),
        "total_mib": round(sum(sizes) / (1024 * 1024), 3),
    }


def digest_summary(results: Sequence[Mapping[str, Any]], declared: str | None) -> dict[str, Any]:
    observed = sorted(
        {
            str(result["core_image_digest"])
            for result in results
            if isinstance(result.get("core_image_digest"), str) and result.get("core_image_digest")
        }
    )
    if len(observed) > 1:
        status = "CONFLICT"
    elif observed and declared and observed[0] != declared:
        status = "MISMATCH"
    elif observed:
        status = "PROVEN"
    else:
        status = "NOT_PROVEN"
    return {"status": status, "observed": observed, "declared": declared}


def load_microsoft_evidence(path: Path | None) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "NOT_PROVEN",
        "source": path.name if path else None,
        "reason": "no independent cold-cache evidence supplied" if path is None else None,
    }
    if path is None:
        return base
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        base["reason"] = "cold-cache evidence could not be read as JSON"
        return base
    if not isinstance(document, Mapping) or document.get("status") != "PROVEN":
        base["reason"] = "evidence must explicitly set status=PROVEN"
        return base
    allowed = (
        "cold_cache_downloads",
        "cold_cache_duration_ms",
        "cache_hits",
        "cache_misses",
        "observed_at",
        "source_kind",
        "controlled_cache_reset_method",
        "measurement_source",
        "evidence_ref",
    )
    for key in allowed:
        value = document.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            base[key] = value
    required_context = (
        "controlled_cache_reset_method",
        "measurement_source",
        "evidence_ref",
        "observed_at",
    )
    if document.get("source_kind") != "microsoft_symbol_server":
        base["reason"] = "source_kind must be microsoft_symbol_server"
        return base
    if any(
        not isinstance(document.get(key), str) or not document[key].strip()
        for key in required_context
    ):
        base["reason"] = (
            "PROVEN evidence must include reset method, source, reference and observed_at"
        )
        return base
    downloads = document.get("cold_cache_downloads")
    duration_ms = document.get("cold_cache_duration_ms")
    cache_misses = document.get("cache_misses")
    if not isinstance(downloads, int) or isinstance(downloads, bool) or downloads < 1:
        base["reason"] = "cold_cache_downloads must be an integer >= 1"
        return base
    if (
        not isinstance(duration_ms, (int, float))
        or isinstance(duration_ms, bool)
        or not math.isfinite(float(duration_ms))
        or duration_ms <= 0
    ):
        base["reason"] = "cold_cache_duration_ms must be a finite number > 0"
        return base
    if cache_misses is not None and (
        not isinstance(cache_misses, int) or isinstance(cache_misses, bool) or cache_misses < 1
    ):
        base["reason"] = "cache_misses must be an integer >= 1 when supplied"
        return base
    try:
        observed_at = datetime.fromisoformat(str(document["observed_at"]).replace("Z", "+00:00"))
    except ValueError:
        base["reason"] = "observed_at must be an ISO-8601 timestamp"
        return base
    if observed_at.tzinfo is None:
        base["reason"] = "observed_at must include an ISO-8601 timezone"
        return base
    if "cold_cache_downloads" not in base or "cold_cache_duration_ms" not in base:
        base["reason"] = "PROVEN evidence must include cold-cache downloads and duration"
        return base
    base["status"] = "PROVEN"
    base.pop("reason", None)
    return base


def uniqueness_summary(workload: str, results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if workload != "upload":
        return {
            "status": "NOT_APPLICABLE",
            "task_count": len(results),
            "unique_blob_count": None,
            "unique_occurrence_count": None,
            "duplicate_upload_count": None,
            "unique_sha256_count": None,
        }
    blob_ids = [str(result["blob_id"]) for result in results if result.get("blob_id")]
    occurrence_ids = [
        str(result["occurrence_id"]) for result in results if result.get("occurrence_id")
    ]
    duplicate_upload_count = sum(result.get("duplicate") is True for result in results)
    sha256_values = [str(result["sha256"]) for result in results if result.get("sha256")]
    return {
        "status": "PROVEN"
        if len(blob_ids) == len(results)
        and len(occurrence_ids) == len(results)
        and len(sha256_values) == len(results)
        and len(set(blob_ids)) == len(results)
        and len(set(occurrence_ids)) == len(results)
        and len(set(sha256_values)) == len(results)
        and duplicate_upload_count == 0
        else "NOT_PROVEN",
        "task_count": len(results),
        "unique_blob_count": len(set(blob_ids)),
        "unique_occurrence_count": len(set(occurrence_ids)),
        "duplicate_upload_count": duplicate_upload_count,
        "unique_sha256_count": len(set(sha256_values)),
    }


def assess_gate(
    *,
    mode: str,
    workload: str,
    tasks: Sequence[CapacityTask],
    results: Sequence[Mapping[str, Any]],
    preflight_errors: Sequence[Mapping[str, str]],
    buckets: Mapping[str, Mapping[str, Any]],
    queue: Mapping[str, Any],
    digest: Mapping[str, Any],
    microsoft: Mapping[str, Any],
    uniqueness: Mapping[str, Any],
    expected_count: int,
    requested_concurrency: int,
) -> tuple[str, list[str], dict[str, bool]]:
    if mode == "dry-run":
        return (
            "DRY_RUN",
            ["execution was not requested"],
            {
                "zero_loss": False,
                "all_successful_terminal": False,
                "size_buckets_complete": False,
                "p95_targets_met": False,
            },
        )
    reasons: list[str] = []
    hard_fail = False
    not_proven = False
    zero_loss = (
        not preflight_errors
        and len(results) == len(tasks)
        and all(bool(result.get("accepted")) and bool(result.get("terminal")) for result in results)
    )
    if not zero_loss:
        hard_fail = True
        reasons.append("zero-loss condition failed: every task must be accepted and terminal")
    all_successful_terminal = all(
        result.get("status") in SUCCESS_STATUSES for result in results
    ) and bool(results)
    if not all_successful_terminal:
        hard_fail = True
        reasons.append("one or more tasks ended in a non-success terminal status")
    if workload == "reprocess":
        not_proven = True
        reasons.append("reprocess workload is smoke-only and cannot prove 100 unique Dumps/Blobs")
    elif uniqueness.get("status") != "PROVEN":
        hard_fail = True
        reasons.append("upload workload did not produce one unique Blob and Occurrence per task")
    if expected_count != TARGET_TASKS:
        not_proven = True
        reasons.append(f"requested gate count is {expected_count}, target is {TARGET_TASKS}")
    if len(tasks) != expected_count:
        not_proven = True
        reasons.append(f"task count is {len(tasks)}, target is {expected_count}")
    if requested_concurrency != TARGET_CONCURRENCY:
        not_proven = True
        reasons.append(
            f"requested concurrency is {requested_concurrency}, target is {TARGET_CONCURRENCY}"
        )
    if int(queue.get("local_in_flight_peak", 0)) > TARGET_CONCURRENCY:
        hard_fail = True
        reasons.append("local in-flight concurrency exceeded five")
    size_buckets_complete = all(
        int(buckets[bucket].get("sample_count", 0)) > 0 for bucket in BUCKETS
    )
    if not size_buckets_complete:
        not_proven = True
        reasons.append("both size buckets require at least one observed sample")
    p95_targets_met = True
    for bucket in BUCKETS:
        p95 = buckets[bucket].get("p95_ms")
        if p95 is None:
            p95_targets_met = False
            not_proven = True
            reasons.append(f"{bucket} has no terminal duration percentile")
        elif float(p95) > P95_TARGET_MS[bucket]:
            p95_targets_met = False
            hard_fail = True
            reasons.append(f"{bucket} p95 exceeded {P95_TARGET_MS[bucket]}ms")
    for evidence_name, evidence in (
        ("queue", queue),
        ("core digest", digest),
        ("Microsoft cold-cache", microsoft),
    ):
        if evidence.get("status") != "PROVEN":
            not_proven = True
            reasons.append(f"{evidence_name} evidence is {evidence.get('status', 'NOT_PROVEN')}")
    if hard_fail:
        status = "FAIL"
    elif not_proven:
        status = "NOT_PROVEN"
    else:
        status = "PASS"
    checks = {
        "zero_loss": zero_loss,
        "all_successful_terminal": all_successful_terminal,
        "size_buckets_complete": size_buckets_complete,
        "p95_targets_met": p95_targets_met,
    }
    return status, reasons, checks


def build_report(
    *,
    mode: str,
    workload: str,
    tasks: Sequence[CapacityTask],
    results: Sequence[Mapping[str, Any]],
    preflight_errors: Sequence[Mapping[str, str]],
    queue: Mapping[str, Any],
    digest: Mapping[str, Any],
    microsoft: Mapping[str, Any],
    manifest_name: str | None,
    base_url: str | None,
    expected_count: int,
    requested_concurrency: int,
    started_at: str,
    finished_at: str,
) -> dict[str, Any]:
    buckets = summarize_buckets(tasks, results)
    uniqueness = uniqueness_summary(workload, results)
    status, reasons, checks = assess_gate(
        mode=mode,
        workload=workload,
        tasks=tasks,
        results=results,
        preflight_errors=preflight_errors,
        buckets=buckets,
        queue=queue,
        digest=digest,
        microsoft=microsoft,
        uniqueness=uniqueness,
        expected_count=expected_count,
        requested_concurrency=requested_concurrency,
    )
    terminal_statuses = dict(sorted(Counter(str(result["status"]) for result in results).items()))
    upload_terminal_statuses = dict(
        sorted(
            Counter(
                str(result.get("upload_status", "NOT_APPLICABLE")) for result in results
            ).items()
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "mode": mode,
        "workload": workload,
        "started_at": started_at,
        "finished_at": finished_at,
        "source": {
            "manifest": manifest_name,
            # Endpoint URLs may contain sensitive host/query context; retain only
            # the local manifest identity in emitted evidence.
            "base_url": None,
        },
        "target": {
            "tasks": TARGET_TASKS,
            "requested_tasks": expected_count,
            "max_concurrency": TARGET_CONCURRENCY,
            "requested_concurrency": requested_concurrency,
            "bucket_boundaries_bytes": {
                "small_max": SMALL_MAX_BYTES,
                "large_max": LARGE_MAX_BYTES,
            },
            "p95_targets_ms": P95_TARGET_MS,
        },
        "sample": size_summary(tasks),
        "preflight_errors": list(preflight_errors),
        "terminal_statuses": terminal_statuses,
        "upload_terminal_statuses": upload_terminal_statuses,
        "buckets": buckets,
        "queue": dict(queue),
        "core_digest": dict(digest),
        "microsoft_cold_cache": dict(microsoft),
        "uniqueness": uniqueness,
        "gate": {"checks": checks, "reasons": reasons},
        "tasks": [dict(result) for result in results],
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    target = report["target"]
    sample = report["sample"]
    lines = [
        "# Phase 1 Capacity Gate",
        "",
        f"- Status: **{report['status']}**",
        f"- Mode: `{report['mode']}`",
        f"- Workload: `{report.get('workload', 'unknown')}`",
        (
            f"- Sample: `{sample['task_count']}/{target['tasks']}` tasks; "
            f"known sizes `{sample['known_size_count']}`"
        ),
        (
            f"- Requested/local concurrency: `{target['requested_concurrency']}/"
            f"{report['queue'].get('local_in_flight_peak', 0)}`"
        ),
        f"- Manifest: `{report['source'].get('manifest') or 'none'}`",
        "",
        "## Bucket latency",
        "",
        (
            "| Bucket | Samples | Terminal | p50 (ms) | p95 (ms) | p99 (ms) | "
            "Target p95 (ms) | Statuses |"
        ),
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for bucket in BUCKETS:
        item = report["buckets"][bucket]
        statuses = (
            ", ".join(f"{key}={value}" for key, value in item["status_counts"].items()) or "-"
        )
        lines.append(
            f"| {bucket} | {item['sample_count']} | {item['terminal_count']} | "
            f"{item['p50_ms'] if item['p50_ms'] is not None else '-'} | "
            f"{item['p95_ms'] if item['p95_ms'] is not None else '-'} | "
            f"{item['p99_ms'] if item['p99_ms'] is not None else '-'} | "
            f"{item['p95_target_ms']} | {statuses} |"
        )
    queue = report["queue"]
    digest = report["core_digest"]
    microsoft = report["microsoft_cold_cache"]
    lines.extend(
        [
            "",
            "## Evidence",
            "",
            (
                f"- Queue peak: `{queue.get('peak_total', 0)}` total; "
                f"by queue `{queue.get('peak_by_queue', {})}`; "
                f"observed `{queue.get('observed_queue_names', [])}`; "
                f"evidence `{queue.get('status')}`"
            ),
            f"- Terminal statuses: `{report['terminal_statuses']}`",
            f"- Upload terminal statuses: `{report.get('upload_terminal_statuses', {})}`",
            (
                f"- Core image digest: `{digest.get('status')}`; "
                f"observed `{digest.get('observed', [])}`"
            ),
            f"- Microsoft cold-cache: `{microsoft.get('status')}`",
            (
                "- Unique Blob/Occurrence evidence: "
                f"`{report.get('uniqueness', {}).get('status')}`; "
                f"counts `{report.get('uniqueness', {}).get('unique_blob_count')}/"
                f"{report.get('uniqueness', {}).get('unique_occurrence_count')}`"
            ),
            "",
            "## Gate checks",
            "",
        ]
    )
    for key, value in report["gate"]["checks"].items():
        lines.append(f"- `{key}`: `{value}`")
    reasons = report["gate"].get("reasons", [])
    if reasons:
        lines.extend(["", "## Reasons", ""])
        lines.extend(f"- {reason}" for reason in reasons)
    failures = [
        result
        for result in report["tasks"]
        if result.get("error") or result.get("status") not in SUCCESS_STATUSES
    ]
    if failures:
        lines.extend(["", "## Non-success tasks", ""])
        lines.append("| Occurrence | Status | Error |")
        lines.append("| --- | --- | --- |")
        for result in failures:
            lines.append(
                f"| {result.get('occurrence_id')} | {result.get('status')} | "
                f"{result.get('error') or '-'} |"
            )
    lines.append("")
    return "\n".join(lines)


def write_output(path: Path | None, content: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def _empty_queue(concurrency: int) -> dict[str, Any]:
    return {
        "status": "NOT_PROVEN",
        "sample_count": 0,
        "monitor_errors": {},
        "peak_by_queue": {},
        "peak_total": 0,
        "observed_queue_names": [],
        "requested_concurrency": concurrency,
        "local_in_flight_peak": 0,
        "samples": [],
    }


def run_capacity_gate(
    *,
    tasks: Sequence[CapacityTask],
    execute: bool,
    workload: str = "reprocess",
    base_url: str | None,
    metrics_url: str | None,
    expected_count: int = TARGET_TASKS,
    concurrency: int = TARGET_CONCURRENCY,
    timeout_seconds: float = 1500,
    poll_interval_seconds: float = 5,
    metrics_interval_seconds: float = 5,
    microsoft_evidence: Mapping[str, Any] | None = None,
    declared_core_digest: str | None = None,
    manifest_name: str | None = None,
) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    prepared = list(tasks)
    preflight_errors: list[dict[str, str]] = []
    results: list[dict[str, Any]] = []
    queue: dict[str, Any] = _empty_queue(concurrency)
    normalized_base = normalize_api_base_url(base_url) if base_url else None
    if execute:
        if normalized_base is None:
            raise ValueError("--execute requires --base-url")
        client = ApiClient(normalized_base, timeout_seconds=min(60.0, timeout_seconds))
        if workload == "upload":
            prepared, preflight_errors = preflight_upload_tasks(tasks)
        else:
            prepared, preflight_errors = preflight_tasks(client, tasks)
        if (
            not preflight_errors
            and len(prepared) == len(tasks)
            and all(classify_bucket(task.size_bytes) in BUCKETS for task in prepared)
        ):
            monitor_url = (
                normalize_metrics_url(metrics_url)
                if metrics_url
                else derive_metrics_url(normalized_base)
            )
            monitor_client = ApiClient(monitor_url, timeout_seconds=min(60.0, timeout_seconds))
            monitor = QueueMonitor(monitor_client, metrics_interval_seconds)
            monitor.start()
            results, tracker = execute_tasks(
                client,
                prepared,
                workload=workload,
                concurrency=concurrency,
                timeout_seconds=timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
            monitor.stop()
            queue = monitor.report(tracker.peak, concurrency)
        else:
            for task in prepared:
                if classify_bucket(task.size_bytes) not in BUCKETS:
                    preflight_errors.append(
                        {
                            "occurrence_id": task.occurrence_id,
                            "error": "size_outside_phase1_buckets",
                        }
                    )
    microsoft = dict(
        microsoft_evidence or {"status": "NOT_PROVEN", "reason": "no independent evidence"}
    )
    digest = digest_summary(results, declared_core_digest)
    finished_at = datetime.now(UTC).isoformat()
    return build_report(
        mode="execute" if execute else "dry-run",
        workload=workload,
        tasks=prepared,
        results=results,
        preflight_errors=preflight_errors,
        queue=queue,
        digest=digest,
        microsoft=microsoft,
        manifest_name=manifest_name,
        base_url=normalized_base,
        expected_count=expected_count,
        requested_concurrency=concurrency,
        started_at=started_at,
        finished_at=finished_at,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, help="external JSON/JSONL/CSV occurrence manifest")
    parser.add_argument(
        "--workload",
        choices=("upload", "reprocess"),
        default="reprocess",
        help="upload creates unique Dump Blobs; reprocess is an explicit smoke workload",
    )
    parser.add_argument(
        "--execute", action="store_true", help="call the real API; default is dry-run"
    )
    parser.add_argument("--base-url", help="API base URL, normally http://host:port/api/v3")
    parser.add_argument("--metrics-url", help="optional Prometheus metrics URL; derived by default")
    parser.add_argument("--microsoft-evidence", type=Path, help="external cold-cache evidence JSON")
    parser.add_argument("--core-digest", help="optional expected sha256 OCI digest")
    parser.add_argument(
        "--count",
        type=int,
        default=TARGET_TASKS,
        help="target task count (default: 100)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=TARGET_CONCURRENCY,
        help="max in-flight API tasks (default: 5)",
    )
    parser.add_argument("--timeout-seconds", type=float, default=1500)
    parser.add_argument("--poll-interval-seconds", type=float, default=5)
    parser.add_argument("--metrics-interval-seconds", type=float, default=5)
    parser.add_argument("--json-out", type=Path, help="write JSON evidence; omit to print JSON")
    parser.add_argument("--markdown-out", type=Path, help="write Markdown evidence")
    args = parser.parse_args()

    if args.count <= 0 or args.count > TARGET_TASKS:
        parser.error("--count must be between 1 and 100")
    if args.concurrency <= 0 or args.concurrency > TARGET_CONCURRENCY:
        parser.error("--concurrency must be between 1 and 5")
    if args.execute and (args.manifest is None or args.base_url is None):
        parser.error("--execute requires both --manifest and --base-url")
    if (
        args.json_out is not None
        and args.markdown_out is not None
        and args.json_out == args.markdown_out
    ):
        parser.error("--json-out and --markdown-out must be different files")
    try:
        tasks = load_manifest(args.manifest, workload=args.workload) if args.manifest else []
        if args.manifest and len(tasks) != args.count:
            raise ValueError(f"manifest contains {len(tasks)} tasks but --count is {args.count}")
        if args.core_digest is not None and not re.fullmatch(
            r"sha256:[0-9a-fA-F]{64}", args.core_digest
        ):
            raise ValueError("--core-digest must be sha256 followed by 64 hex characters")
        microsoft = load_microsoft_evidence(args.microsoft_evidence)
        report = run_capacity_gate(
            tasks=tasks,
            execute=args.execute,
            workload=args.workload,
            base_url=args.base_url,
            metrics_url=args.metrics_url,
            expected_count=args.count,
            concurrency=args.concurrency,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            metrics_interval_seconds=args.metrics_interval_seconds,
            microsoft_evidence=microsoft,
            declared_core_digest=args.core_digest,
            manifest_name=args.manifest.name if args.manifest else None,
        )
    except (OSError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    json_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    write_output(args.json_out, json_text)
    write_output(args.markdown_out, render_markdown(report))
    if args.json_out is None:
        print(json_text, end="")
    else:
        print(f"Wrote JSON evidence: {args.json_out}")
    if args.markdown_out is not None:
        print(f"Wrote Markdown evidence: {args.markdown_out}")
    return 0 if report["status"] in {"PASS", "DRY_RUN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
