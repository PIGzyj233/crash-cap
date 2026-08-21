from __future__ import annotations

from typing import Any

PRODUCER_MATRIX: dict[str, dict[str, Any]] = {
    "msvc": {
        "status": "supported",
        "artifact_format": "PE x64 + complete PDB 7.0",
        "fixture_suite": "phase0-msvc-golden",
        "gate": "21/21 Golden; zero silent wrong symbols",
    },
    "clang-cl": {
        "status": "experimental",
        "artifact_format": "PE x64 + complete PDB 7.0",
        "fixture_suite": None,
        "gate": "requires producer fixture and Phase 0 Golden metrics before supported",
    },
    "crashpad": {
        "status": "experimental",
        "artifact_format": "Crashpad Windows user-mode x64 minidump",
        "fixture_suite": None,
        "gate": "requires producer fixture and Phase 0 Golden metrics before supported",
    },
}


def producer_matrix_view() -> list[dict[str, Any]]:
    return [{"producer": name, **details} for name, details in PRODUCER_MATRIX.items()]
