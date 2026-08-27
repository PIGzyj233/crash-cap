from __future__ import annotations

import argparse
import hashlib
import json
import mmap
import os
import platform
import statistics
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import zstandard
from crashcap_api.services.artifact_payloads import ArtifactBlobCodec


@dataclass(frozen=True)
class Sample:
    label: str
    kind: str
    source_relpath: str
    size: int
    sha256: str
    authorization: str


class RssSampler:
    def __init__(self) -> None:
        self.peak = _current_rss()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def __enter__(self) -> RssSampler:
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self._stop.set()
        self._thread.join()
        self.peak = max(self.peak, _current_rss())

    def _run(self) -> None:
        while not self._stop.wait(0.02):
            self.peak = max(self.peak, _current_rss())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crashcap-pdb-benchmark",
        description=(
            "Benchmark the frozen zstd-v1 profile against an approved private Artifact corpus"
        ),
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.artifact_root.resolve()
    samples = _load_manifest(args.manifest, root)
    iterations = max(1, min(args.iterations, 20))
    cases: list[dict[str, Any]] = []
    failures = 0
    for sample in samples:
        try:
            cases.append(_benchmark_sample(sample, root, iterations))
        except Exception as error:
            failures += 1
            cases.append(
                {
                    "label": sample.label,
                    "kind": sample.kind,
                    "status": "FAIL",
                    "error_code": getattr(error, "code", type(error).__name__),
                }
            )
    report = {
        "schema_version": "pdb-compression-benchmark-v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "profile": {
            "encoding": "zstd-v1",
            "python_zstandard": zstandard.__version__,
            "level": 6,
            "checksum": True,
            "content_size": True,
            "threads": 0,
            "max_window_bytes": 64 * 1024 * 1024,
        },
        "runtime": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "sample_count": len(samples),
        "iterations": iterations,
        "failures": failures,
        "cases": cases,
        "aggregates": _aggregate_cases(cases),
        "privacy": {"absolute_paths_included": False, "payloads_included": False},
    }
    _write_json(args.output, report)
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(_render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 1 if failures else 0


def _load_manifest(path: Path, root: Path) -> list[Sample]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != "pdb-storage-corpus-v1":
        raise ValueError("unsupported corpus manifest schema")
    result: list[Sample] = []
    for raw in value.get("samples", []):
        relative = Path(str(raw["source_relpath"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("corpus source_relpath must stay under --artifact-root")
        resolved = (root / relative).resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("corpus source escaped --artifact-root")
        result.append(
            Sample(
                label=str(raw["label"]),
                kind=str(raw["kind"]),
                source_relpath=relative.as_posix(),
                size=int(raw["size"]),
                sha256=str(raw["sha256"]).lower(),
                authorization=str(raw["authorization"]),
            )
        )
    if not result:
        raise ValueError("corpus manifest has no samples")
    return result


def _benchmark_sample(sample: Sample, root: Path, iterations: int) -> dict[str, Any]:
    source = (root / sample.source_relpath).resolve()
    digest, size = _file_digest(source)
    if size != sample.size or digest != sample.sha256:
        raise ValueError("private Artifact does not match the approved manifest")
    codec = ArtifactBlobCodec()
    compression: list[float] = []
    decompression: list[float] = []
    compression_cpu: list[float] = []
    decompression_cpu: list[float] = []
    peak_rss = _current_rss()
    stored_size = 0
    with tempfile.TemporaryDirectory(prefix="crashcap-pdb-benchmark-") as raw_temp:
        temp = Path(raw_temp)
        for index in range(iterations):
            encoded = temp / f"payload-{index}.zst"
            decoded = temp / f"decoded-{index}"
            with RssSampler() as rss:
                started = time.perf_counter()
                cpu_started = time.process_time()
                result = codec.encode_file(
                    source,
                    encoded,
                    kind=sample.kind,
                    encoding="zstd-v1",
                    expected_raw_size=sample.size,
                    expected_raw_sha256=sample.sha256,
                )
                compression.append(time.perf_counter() - started)
                compression_cpu.append(time.process_time() - cpu_started)
                started = time.perf_counter()
                cpu_started = time.process_time()
                codec.decode_file(
                    encoded,
                    decoded,
                    kind=sample.kind,
                    encoding="zstd-v1",
                    expected_raw_size=sample.size,
                    expected_raw_sha256=sample.sha256,
                )
                decompression.append(time.perf_counter() - started)
                decompression_cpu.append(time.process_time() - cpu_started)
            peak_rss = max(peak_rss, rss.peak)
            stored_size = result.payload_size
            if _file_digest(decoded) != (sample.sha256, sample.size):
                raise RuntimeError("round-trip identity mismatch")
    return {
        "label": sample.label,
        "kind": sample.kind,
        "authorization": sample.authorization,
        "status": "PASS",
        "raw_size": sample.size,
        "raw_sha256": sample.sha256,
        "stored_size": stored_size,
        "stored_ratio": round(stored_size / sample.size, 6),
        "saved_bytes": sample.size - stored_size,
        "compress_seconds": _distribution(compression),
        "decompress_seconds": _distribution(decompression),
        "compress_cpu_seconds": _distribution(compression_cpu),
        "decompress_cpu_seconds": _distribution(decompression_cpu),
        "compress_mib_per_second": round(
            sample.size / (1024 * 1024) / statistics.median(compression), 3
        ),
        "decompress_mib_per_second": round(
            sample.size / (1024 * 1024) / statistics.median(decompression), 3
        ),
        "peak_process_rss_bytes": peak_rss,
        "peak_temp_bytes": sample.size + stored_size,
        "round_trip_sha256": sample.sha256,
    }


def _aggregate_cases(cases: list[dict[str, Any]]) -> dict[str, Any]:
    aggregates: dict[str, Any] = {}
    for kind in ("pdb", "pe"):
        successful = [
            case for case in cases if case.get("status") == "PASS" and case.get("kind") == kind
        ]
        if not successful:
            continue
        raw_bytes = sum(int(case["raw_size"]) for case in successful)
        stored_bytes = sum(int(case["stored_size"]) for case in successful)
        ratios = [float(case["stored_ratio"]) for case in successful]
        compress_p95 = [float(case["compress_seconds"]["p95"]) for case in successful]
        decompress_p95 = [float(case["decompress_seconds"]["p95"]) for case in successful]
        peak_rss = [int(case["peak_process_rss_bytes"]) for case in successful]
        peak_temp = [int(case["peak_temp_bytes"]) for case in successful]
        aggregates[kind] = {
            "sample_count": len(successful),
            "raw_bytes": raw_bytes,
            "stored_bytes": stored_bytes,
            "stored_ratio": round(stored_bytes / raw_bytes, 6),
            "single_file_ratio_p95": round(_percentile(ratios, 0.95), 6),
            "compress_seconds_p95": round(_percentile(compress_p95, 0.95), 6),
            "decompress_seconds_p95": round(_percentile(decompress_p95, 0.95), 6),
            "peak_process_rss_bytes": max(peak_rss),
            "peak_temp_bytes": max(peak_temp),
        }
    return aggregates


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "p50": round(statistics.median(ordered), 6),
        "p95": round(ordered[max(0, int(len(ordered) * 0.95 + 0.999) - 1)], 6),
    }


def _percentile(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, int(len(ordered) * quantile + 0.999) - 1)]


def _current_rss() -> int:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        process = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        return int(counters.WorkingSetSize if ok else 0)
    statm = Path("/proc/self/statm")
    if statm.is_file():
        pages = int(statm.read_text(encoding="ascii").split()[1])
        return pages * mmap.PAGESIZE
    return 0


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# PDB compression benchmark",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "| Sample | Kind | Raw bytes | Stored bytes | Ratio | "
        "Compress p50 | Compress CPU p50 | Decompress p50 | Decompress CPU p50 | Status |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for case in report["cases"]:
        lines.append(
            (
                "| {label} | {kind} | {raw} | {stored} | {ratio} | "
                "{compress} | {compress_cpu} | {decompress} | {decompress_cpu} | {status} |"
            ).format(
                label=case["label"],
                kind=case["kind"],
                raw=case.get("raw_size", "-"),
                stored=case.get("stored_size", "-"),
                ratio=case.get("stored_ratio", "-"),
                compress=case.get("compress_seconds", {}).get("p50", "-"),
                compress_cpu=case.get("compress_cpu_seconds", {}).get("p50", "-"),
                decompress=case.get("decompress_seconds", {}).get("p50", "-"),
                decompress_cpu=case.get("decompress_cpu_seconds", {}).get("p50", "-"),
                status=case["status"],
            )
        )
    lines.extend(
        [
            "",
            "## Aggregates",
            "",
            "| Kind | Samples | Raw bytes | Stored bytes | Aggregate ratio | "
            "Single-file ratio p95 | Compress p95 | Decompress p95 | Peak RSS | Peak temp |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for kind, aggregate in report["aggregates"].items():
        lines.append(
            "| {kind} | {sample_count} | {raw_bytes} | {stored_bytes} | {stored_ratio} | "
            "{single_file_ratio_p95} | {compress_seconds_p95} | "
            "{decompress_seconds_p95} | {peak_process_rss_bytes} | {peak_temp_bytes} |".format(
                kind=kind,
                **aggregate,
            )
        )
    return "\n".join(lines) + "\n"


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())
