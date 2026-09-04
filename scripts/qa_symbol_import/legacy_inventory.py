"""Read-only S0/S1 inventory; run inside the selected platform environment.

Only metadata and content digests are emitted, not raw dumps, source text or secrets.
No old Run, Canonical, Blob or Build is updated. Explicit row limit is reported.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone

from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import AnalysisRun, ArtifactBlob, Build, DumpBlob, Occurrence
from crashcap_api.storage import create_object_store
from sqlalchemy import func, select, text


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--qualify", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.limit <= 1000:
        parser.error("limit must be between 1 and 1000")
    settings = Settings(create_schema=False)
    database = Database(settings)
    store = create_object_store(settings)
    report = {
        "schema_version": "qai-legacy-inventory-v1",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "explicitly selected local Compose; not target UAT",
        "limit": args.limit,
        "runs": [],
    }

    def object_info(key, read_json=False):
        if not key:
            return {"status": "absent_reference"}, None
        try:
            head = store.head(key)
            if not read_json:
                return {"status": "present", "size": head.size}, None
            if head.size > 32 * 1024 * 1024:
                return {"status": "not_read_size_limit", "size": head.size}, None
            data = b"".join(store.stream(key))
            return {
                "status": "present",
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }, json.loads(data)
        except Exception as error:
            # Do not emit exception strings: storage SDK errors can include endpoints.
            return {"status": "unavailable", "error_type": type(error).__name__}, None

    with database.sessions() as session:
        if database.engine.dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
        report["counts"] = {
            model.__tablename__: session.scalar(select(func.count()).select_from(model))
            for model in (AnalysisRun, Occurrence, Build, ArtifactBlob, DumpBlob)
        }
        report["alembic_version"] = list(
            session.scalars(text("SELECT version_num FROM alembic_version"))
        )
        rows = session.execute(
            select(AnalysisRun, Occurrence, DumpBlob)
            .join(Occurrence, AnalysisRun.occurrence_id == Occurrence.id)
            .join(DumpBlob, Occurrence.dump_blob_id == DumpBlob.id)
            .order_by(AnalysisRun.id)
            .limit(args.limit)
        ).all()
        # Load immutable metadata, then release the DB transaction before object I/O.
        snapshots = [
            {
                "run_id": run.id,
                "occurrence_id": occurrence.id,
                "workspace_id": occurrence.workspace_id,
                "is_current": occurrence.current_run_id == run.id,
                "schema_version": run.schema_version,
                "status": run.status,
                "assembly_mode": run.assembly_mode,
                "result_key": run.result_object_key,
                "inspect_key": run.inspect_object_key,
                "raw_prefix": run.raw_object_prefix,
                "has_analysis_context": bool(run.analysis_context),
                "context_version": (run.analysis_context or {}).get("schema_version"),
                "context_snapshot_sha256": hashlib.sha256(
                    json.dumps(run.analysis_context, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest()
                if run.analysis_context
                else None,
                "run_spec_snapshot_sha256": hashlib.sha256(
                    json.dumps(run.run_spec, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "dump_sha256": blob.sha256,
                "dump_key": blob.object_key,
                "dump_deleted": blob.deleted_at is not None,
                "roles": dict(
                    Counter(a.get("role") or "unknown" for a in run.run_spec.get("artifacts", []))
                ),
                "resolved_build_id": run.resolved_build_id,
            }
            for run, occurrence, blob in rows
        ]
    verified_dumps = {}
    for item in snapshots:
        result_key = item.pop("result_key")
        inspect_key = item.pop("inspect_key")
        raw_prefix = item.pop("raw_prefix")
        dump_key = item.pop("dump_key")
        item["canonical"], canonical = object_info(result_key, True)
        item["inspect"], inspect = object_info(inspect_key, True)
        item["dump"], _ = object_info(dump_key)
        if args.qualify and item["dump"]["status"] == "present":
            if dump_key not in verified_dumps:
                try:
                    digest, size = hashlib.sha256(), 0
                    for chunk in store.stream(dump_key):
                        digest.update(chunk)
                        size += len(chunk)
                    verified_dumps[dump_key] = {"sha256": digest.hexdigest(), "size": size}
                except Exception as error:
                    verified_dumps[dump_key] = {"error_type": type(error).__name__}
            item["dump"].update(verified_dumps[dump_key])
            item["dump"]["verified_identity"] = item["dump"].get("sha256") == item["dump_sha256"]
            if not item["dump"]["verified_identity"]:
                item["dump"]["status"] = "unavailable_or_mismatched"
        raw = list(store.iter_objects(raw_prefix)) if raw_prefix else []
        item["raw_objects"] = []
        raw_unwind = None
        for entry in raw:
            info, value = object_info(entry.key, entry.key.endswith(".json"))
            info["name"] = entry.key[len(raw_prefix) :]
            if info["name"] == "minidump.json":
                raw_unwind = value
            if isinstance(value, dict):
                info["frame_keys"] = sorted(
                    {
                        k
                        for thread in value.get("threads", [])
                        for frame in thread.get("frames", [])
                        for k in frame
                    }
                )
            item["raw_objects"].append(info)
        if isinstance(canonical, dict):
            frames = [f for t in canonical.get("threads", []) for f in t.get("frames", [])]
            item["canonical_unwind_methods_present"] = bool(frames) and all(
                "unwind_method" in f for f in frames
            )
            item["canonical_trust_counts"] = dict(Counter(f.get("trust", "absent") for f in frames))
        item["continuity"] = (
            "requires_explicit_recompute"
            if item["dump"]["status"] == "present" and not item["dump_deleted"]
            else "needs_review_cannot_recompute"
        )
        item["comparison_evidence_status"] = "NOT_PROVEN"
        if args.qualify:
            from legacy_continuity import qualify_legacy

            item["legacy_qualification"] = qualify_legacy(
                canonical,
                inspect,
                raw_unwind,
                dump_available=item["dump"]["status"] == "present" and not item["dump_deleted"],
            )
        report["runs"].append(item)
    report["enumeration_complete"] = report["counts"]["analysis_runs"] <= args.limit
    report["status"] = "PASS" if report["enumeration_complete"] else "NOT_PROVEN"
    report["boundary"] = (
        "PASS means inventory enumeration completed, not legacy comparator qualification. Raw trust provenance requires verification; no synthetic mapping is assumed."
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
