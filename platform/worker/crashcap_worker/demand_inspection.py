"""Bounded, real inspection materialization outside the demand transaction."""

from __future__ import annotations

import hashlib
import shutil
import tempfile
from pathlib import Path

from crashcap_api.frozen_inputs import INSPECTOR_VERSION
from crashcap_api.ids import new_ulid
from crashcap_api.services.analysis_demands import InspectionEvidence, inspection_evidence
from crashcap_api.services.artifact_payloads import TEMP_DISK_RESERVE_BYTES
from crashcap_api.services.uploads import FILE_LIMITS
from crashcap_api.storage import ObjectStore

from .core_runner import CoreExecutionError, CoreExecutor


def inspector_provenance(core: CoreExecutor) -> str:
    if core.settings.core_executor == "fake":
        raise CoreExecutionError(
            "INSPECT_REAL_CORE_REQUIRED", "Fake Core cannot prepare demand evidence"
        )
    if core.settings.core_executor == "local":
        binary = Path(shutil.which(core.settings.core_command) or core.settings.core_command)
        with binary.open("rb") as source:
            return (
                "core-inspect-v1:binary-sha256:" + hashlib.file_digest(source, "sha256").hexdigest()
            )
    return "core-inspect-v1:" + core.settings.core_image_digest


def prepare_inspection(
    core: CoreExecutor,
    store: ObjectStore,
    *,
    workspace_id: str,
    dump_key: str,
    dump_sha256: str,
    dump_size: int,
) -> InspectionEvidence:
    provenance = inspector_provenance(core)
    if not 0 < dump_size <= FILE_LIMITS["dmp"]:
        raise CoreExecutionError("INSPECT_DUMP_LIMIT", "DMP exceeds inspection limit")
    core.settings.task_tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="demand-inspect-", dir=core.settings.task_tmp_root
    ) as temporary:
        root = Path(temporary)
        if shutil.disk_usage(root).free < dump_size + TEMP_DISK_RESERVE_BYTES:
            raise CoreExecutionError(
                "INSPECT_TEMP_CAPACITY", "Insufficient inspection staging space"
            )
        sha, size = hashlib.sha256(), 0
        with (root / "dump.dmp").open("xb") as output:
            for block in store.stream(dump_key, 1024 * 1024):
                size += len(block)
                if size > dump_size:
                    raise CoreExecutionError(
                        "INSPECT_DUMP_SIZE_MISMATCH", "DMP exceeds declared size"
                    )
                sha.update(block)
                output.write(block)
        if (sha.hexdigest(), size) != (dump_sha256, dump_size):
            raise CoreExecutionError("INSPECT_DUMP_HASH_MISMATCH", "DMP verification failed")
        core.inspect(root, {})
        if inspector_provenance(core) != provenance:
            raise CoreExecutionError(
                "INSPECT_EXECUTOR_CHANGED", "Inspector changed during execution"
            )
        path = root / "inspect.json"
        data = path.read_bytes()
        key = f"workspaces/{workspace_id}/inspections/{new_ulid()}/inspect.json"
        evidence = inspection_evidence(
            data,
            dump_sha256=dump_sha256,
            dump_size=dump_size,
            inspector_version=INSPECTOR_VERSION,
            inspector_provenance=provenance,
            object_key=key,
        )
        store.put_file(key, path, "application/json")
        stored_sha, stored_size = hashlib.sha256(), 0
        for block in store.stream(key, 1024 * 1024):
            stored_size += len(block)
            if stored_size > len(data):
                raise CoreExecutionError("INSPECT_READBACK_MISMATCH", "Stored inspect grew")
            stored_sha.update(block)
        if (stored_sha.hexdigest(), stored_size) != (evidence.object_sha256, len(data)):
            raise CoreExecutionError("INSPECT_READBACK_MISMATCH", "Stored inspect differs")
        return evidence
