from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..models import ArtifactBlob
from ..storage import ObjectStore
from .artifact_payloads import BlobMaterializer
from .common import operation_log


class ArtifactBlobExportError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def materialize_artifact_blob_export(
    session: Session,
    store: ObjectStore,
    temp_root: Path,
    *,
    artifact_blob_id: str,
    destination: Path,
) -> dict[str, Any]:
    """Materialize one exact logical PE/PDB for export or restore validation.

    The destination must not exist. BlobMaterializer verifies the stored payload
    and the decoded raw size/SHA before atomically publishing the output.
    """

    blob = session.get(ArtifactBlob, artifact_blob_id)
    if blob is None:
        raise ArtifactBlobExportError(
            "artifact_blob_not_found", "exact Artifact Blob was not found"
        )
    if blob.verification_status != "verified":
        raise ArtifactBlobExportError(
            "artifact_blob_not_verified", "Artifact Blob is not in verified state"
        )
    if destination.exists():
        raise ArtifactBlobExportError(
            "destination_exists", "refusing to overwrite an existing destination"
        )

    digest = BlobMaterializer(store, temp_root).materialize(blob, destination)
    operation_log(
        session,
        action="artifact_blob.materialize_export",
        target_type="artifact_blob",
        target_id=blob.id,
        workspace_id=blob.workspace_id,
        details={
            "kind": blob.kind,
            "payload_encoding": digest.encoding,
            "logical_size": digest.raw_size,
        },
    )
    return {
        "schema_version": "artifact-blob-materialization-v1",
        "artifact_blob_id": blob.id,
        "workspace_id": blob.workspace_id,
        "kind": blob.kind,
        "payload_encoding": digest.encoding,
        "logical_size": digest.raw_size,
        "logical_sha256": digest.raw_sha256,
        "stored_size": digest.payload_size,
        "stored_sha256": digest.payload_sha256,
        "output_created": True,
    }
