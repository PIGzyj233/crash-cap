"""Explicit version boundary for immutable result reads."""

from __future__ import annotations

from .errors import ApiError
from .models import AnalysisRun

READER_VERSIONS = ("2.0",)


def require_canonical_version(run: AnalysisRun, versions: tuple[str, ...]) -> None:
    if run.schema_version not in versions:
        raise ApiError(
            "CANONICAL_VERSION_UNSUPPORTED",
            "This endpoint cannot read the selected Canonical version; use a compatible client",
            status_code=409,
            details={"schema_version": run.schema_version, "reader_versions": list(versions)},
        )
