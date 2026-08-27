from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CORPUS_MANIFEST = REPOSITORY_ROOT / "docs/evidence/pdb-storage-corpus-v1.json"
BENCHMARK_REPORT = REPOSITORY_ROOT / "docs/evidence/pdb-compression-benchmark-20260827.json"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _manifest() -> dict[str, Any]:
    return json.loads(CORPUS_MANIFEST.read_text(encoding="utf-8"))


def test_corpus_manifest_has_stable_identity_and_authorization_metadata() -> None:
    manifest = _manifest()
    samples = manifest["samples"]

    assert manifest["schema_version"] == "pdb-storage-corpus-v1"
    assert manifest["observed_sample_count"] == len(samples)
    assert len(samples) >= manifest["minimum_required_samples"] >= 20

    labels = [sample["label"] for sample in samples]
    paths = [sample["source_relpath"] for sample in samples]
    assert len(labels) == len(set(labels))
    assert len(paths) == len(set(paths))

    for sample in samples:
        path = PurePosixPath(sample["source_relpath"])
        assert sample["kind"] in {"pdb", "pe"}
        assert sample["size"] > 0
        assert SHA256_PATTERN.fullmatch(sample["sha256"])
        assert sample["authorization"].strip()
        assert not path.is_absolute()
        assert ".." not in path.parts
        assert "\\" not in sample["source_relpath"]


def test_partial_corpus_declares_missing_dimensions_and_current_size_coverage() -> None:
    manifest = _manifest()
    sizes = [sample["size"] for sample in manifest["samples"]]
    missing = manifest["missing_dimensions"]

    assert manifest["status"] == "PARTIAL"
    assert missing
    assert "near-2-GiB real PDB" in missing
    assert any(size < 16 * 1024 * 1024 for size in sizes)
    assert any(16 * 1024 * 1024 <= size < 64 * 1024 * 1024 for size in sizes)
    assert any(64 * 1024 * 1024 <= size < 512 * 1024 * 1024 for size in sizes)


def test_benchmark_report_covers_manifest_and_passes_storage_integrity_gates() -> None:
    manifest = _manifest()
    report = json.loads(BENCHMARK_REPORT.read_text(encoding="utf-8"))
    expected = {sample["label"]: sample for sample in manifest["samples"]}

    assert report["schema_version"] == "pdb-compression-benchmark-v1"
    assert report["sample_count"] == len(expected)
    assert report["failures"] == 0
    assert report["privacy"] == {"absolute_paths_included": False, "payloads_included": False}
    assert {case["label"] for case in report["cases"]} == set(expected)
    for case in report["cases"]:
        sample = expected[case["label"]]
        assert case["status"] == "PASS"
        assert case["raw_size"] == sample["size"]
        assert case["raw_sha256"] == sample["sha256"]
        assert case["round_trip_sha256"] == sample["sha256"]

    pdb = report["aggregates"]["pdb"]
    assert pdb["stored_ratio"] <= 0.25
    assert pdb["single_file_ratio_p95"] <= 0.35
    assert pdb["peak_process_rss_bytes"] <= 256 * 1024 * 1024
