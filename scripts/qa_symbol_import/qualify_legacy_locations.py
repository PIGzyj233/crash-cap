"""Read-only qualification of retained legacy PE/PDB payloads, not a backfill.

Run against an explicitly named local API container. Metadata transactions end
before I/O. Raw materialization uses the existing bounded codec in temporary
files; no canonical payload, Artifact, Build, or Run is changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory


def probe(limit):
    from crashcap_api.config import Settings
    from crashcap_api.db import Database
    from crashcap_api.models import Artifact, ArtifactBlob, ArtifactBlobPair
    from crashcap_api.services.artifact_payloads import (
        BlobMaterializer,
        artifact_blob_from_snapshot,
        artifact_blob_snapshot,
    )
    from crashcap_api.storage import create_object_store
    from sqlalchemy import func, select, text

    settings = Settings(create_schema=False)
    database = Database(settings)
    store = create_object_store(settings)
    with database.sessions() as session:
        if database.engine.dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        counts = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (Artifact, ArtifactBlob, ArtifactBlobPair)
        }
        blobs = [
            {
                "snapshot": artifact_blob_snapshot(blob),
                "code_id": blob.code_id,
                "debug_id": blob.debug_id,
                "verification_status": blob.verification_status,
            }
            for blob in session.scalars(select(ArtifactBlob).order_by(ArtifactBlob.id).limit(limit))
        ]
        artifacts = [
            {
                "id": a.id,
                "kind": a.kind,
                "blob_id": a.artifact_blob_id,
                "key": a.object_key,
                "sha256": a.sha256,
                "size": a.size,
                "verification_status": a.verification_status,
            }
            for a in session.scalars(select(Artifact).order_by(Artifact.id).limit(limit))
        ]
        pairs = [
            {"id": p.id, "state": p.state, "pe_blob_id": p.pe_blob_id, "pdb_blob_id": p.pdb_blob_id}
            for p in session.scalars(
                select(ArtifactBlobPair).order_by(ArtifactBlobPair.id).limit(limit)
            )
        ]
    results = []
    with TemporaryDirectory(prefix="qai-legacy-locations-") as directory:
        root = Path(directory)
        materializer = BlobMaterializer(store, root / "temporary")
        for item in blobs:
            snapshot = item["snapshot"]
            row = {
                k: snapshot[k]
                for k in (
                    "id",
                    "sha256",
                    "kind",
                    "size",
                    "payload_encoding",
                    "payload_sha256",
                    "payload_size",
                )
            }
            row.update({k: item[k] for k in ("code_id", "debug_id", "verification_status")})
            row["location_key_sha256"] = hashlib.sha256(
                snapshot["payload_object_key"].encode()
            ).hexdigest()
            try:
                raw = root / snapshot["id"]
                digest = materializer.materialize(artifact_blob_from_snapshot(snapshot), raw)
                row["observed"] = asdict(digest)
                row.update(status="verified_bytes", identity_status="not_reidentified")
            except Exception as error:
                row.update(
                    status="unavailable", reason=getattr(error, "code", type(error).__name__)
                )
            results.append(row)
    by_id = {r["id"]: r for r in results}
    artifact_results = []
    for item in artifacts:
        key = item.pop("key")
        item["location_key_sha256"] = hashlib.sha256(key.encode()).hexdigest()
        if item["kind"] not in {"pe", "pdb"}:
            item["status"] = "outside_symbol_scope"
        elif item["blob_id"] in by_id and by_id[item["blob_id"]]["status"] == "verified_bytes":
            blob = by_id[item["blob_id"]]
            item["status"] = (
                "retained_blob_available"
                if (item["sha256"], item["size"]) == (blob["sha256"], blob["size"])
                else "blob_identity_mismatch"
            )
        else:
            try:
                digest, size = hashlib.sha256(), 0
                for chunk in store.stream(key):
                    size += len(chunk)
                    if size > item["size"]:
                        raise ValueError("oversized")
                    digest.update(chunk)
                item["status"] = (
                    "legacy_bytes_available"
                    if (size, digest.hexdigest()) == (item["size"], item["sha256"])
                    else "legacy_bytes_mismatch"
                )
            except Exception as error:
                item.update(status="unavailable", reason=type(error).__name__)
        artifact_results.append(item)
    return {
        "schema_version": "qai-legacy-locations-v1",
        "time_utc": datetime.now(UTC).isoformat(),
        "status": "PASS" if all(c <= limit for c in counts.values()) else "NOT_PROVEN",
        "counts": counts,
        "enumeration_complete": all(c <= limit for c in counts.values()),
        "blobs": results,
        "artifacts": artifact_results,
        "pairs": pairs,
        "boundary": (
            "PASS means complete inspection with explicit gaps, not global catalog admission "
            "or successful backfill. Existing pair state is metadata, not a new pair "
            "qualification. No DB or object-store writes."
        ),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container")
    parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("limit must be between 1 and 1000")
    if args.inside:
        print(json.dumps(probe(args.limit)))
        return
    if not args.container or not args.output:
        parser.error("--container and --output are required")
    source = Path(__file__).read_text(encoding="utf-8")
    wrapper = (
        "import sys\nsys.argv = ['qualify_legacy_locations.py', '--inside', '--limit', "
        f"{str(args.limit)!r}]\n" + source.replace("from __future__ import annotations", "")
    )
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker CLI unavailable")
    # Explicit container and trusted local script, structured argv; no shell.
    result = subprocess.run(  # noqa: S603
        [docker, "exec", "-i", args.container, "python", "-"],
        input=wrapper,
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    report = json.loads(result.stdout)
    report.update(
        container=args.container, script_sha256=hashlib.sha256(source.encode()).hexdigest()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "counts": report["counts"],
                "blob_statuses": [b["status"] for b in report["blobs"]],
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
