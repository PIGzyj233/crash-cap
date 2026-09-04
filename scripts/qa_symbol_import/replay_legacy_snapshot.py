"""Load an exported historical Current into isolated storage, without a database."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from datetime import datetime
from pathlib import Path

from crashcap_api.errors import ApiError
from crashcap_api.models import AnalysisRun, Base, Occurrence
from crashcap_api.services.result_reviews import load_result_review_evidence
from crashcap_api.storage import LocalObjectStore, ObjectNotFoundError
from sqlalchemy import DateTime, create_engine, text
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]


def verify_database_restore(snapshot, store):
    """Exercise real FK constraints in a fresh in-memory database, never the application DB."""
    if not snapshot.get("database_rows"):
        return {"restored": False, "reason": "dependency_snapshot_absent"}
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("PRAGMA foreign_keys=ON"))
            connection.execute(text("PRAGMA defer_foreign_keys=ON"))
            for item in snapshot["database_rows"]:
                table = Base.metadata.tables[item["table"]]
                values = dict(item["row"])
                for column in table.columns:
                    if isinstance(column.type, DateTime) and values.get(column.name) is not None:
                        values[column.name] = datetime.fromisoformat(values[column.name])
                connection.execute(table.insert().values(**values))
            if connection.execute(text("PRAGMA foreign_key_check")).all():
                raise ValueError("historical dependency restore has dangling foreign keys")
        with Session(engine) as session:
            occurrence = session.get(Occurrence, snapshot["occurrence"]["id"])
            run = session.get(AnalysisRun, occurrence.current_run_id)
            if run.id != snapshot["run"]["id"]:
                raise ValueError("restored Current identity differs")
            canonical = b"".join(store.stream(run.result_object_key))
            loaded = load_result_review_evidence(
                run, store, hashlib.sha256(canonical).hexdigest(),
                initial_decision=None, schema_root=ROOT / "contracts",
            )
            return {"restored": True, "database": "isolated SQLite memory",
                    "rows": len(snapshot["database_rows"]), "foreign_keys_verified": True,
                    "run_id": run.id, "provenance": loaded.evidence.provenance}
    finally:
        engine.dispose()


def load_snapshot(manifest: Path, store: LocalObjectStore):
    """Verify every payload before populating the caller's isolated object store."""
    manifest_bytes = manifest.read_bytes()
    snapshot = json.loads(manifest_bytes)
    if snapshot.get("schema_version") != "qai-legacy-snapshot-v1":
        raise ValueError("unsupported snapshot version")
    run_data, occurrence, blob = (
        snapshot["run"], snapshot["occurrence"], snapshot["dump_blob"]
    )
    if (occurrence["current_run_id"] != run_data["id"]
            or occurrence["id"] != run_data["occurrence_id"]
            or occurrence["dump_blob_id"] != blob["id"]
            or run_data["schema_version"] != "1.0"):
        raise ValueError("snapshot identity mismatch")
    root = manifest.parent.resolve()
    payloads, seen = {}, set()
    for item in snapshot["objects"]:
        key = item["key"]
        store.path_for(key)  # Validate remote keys before any writes.
        if key in seen:
            raise ValueError("duplicate snapshot object")
        seen.add(key)
        if item["status"] == "missing":
            continue
        if item["status"] != "present" or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("invalid snapshot object metadata")
        if item["local_path"] != "objects/" + item["sha256"]:
            raise ValueError("unexpected snapshot payload path")
        path = (root / item["local_path"]).resolve()
        if root not in path.parents:
            raise ValueError("snapshot payload escaped root")
        payload = path.read_bytes()
        if len(payload) != item["size"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise ValueError("snapshot payload digest or size mismatch")
        payloads[key] = payload
    if (blob["object_key"] in payloads
            and hashlib.sha256(payloads[blob["object_key"]]).hexdigest() != blob["sha256"]):
        raise ValueError("snapshot Dump Blob identity mismatch")
    for key, payload in payloads.items():
        store.put_bytes(key, payload, "application/octet-stream")
    return AnalysisRun(**run_data), snapshot, hashlib.sha256(manifest_bytes).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="qai-legacy-replay-") as temporary:
        store = LocalObjectStore(Path(temporary))
        run, snapshot, snapshot_sha = load_snapshot(args.snapshot, store)
        restored = verify_database_restore(snapshot, store)
        key = run.result_object_key
        canonical = b"".join(store.stream(key))
        canonical_sha = hashlib.sha256(canonical).hexdigest()

        def read():
            return load_result_review_evidence(
                run, store, canonical_sha, initial_decision=None, schema_root=ROOT / "contracts"
            )

        loaded = read()
        if loaded.evidence.dump_sha256 != snapshot["dump_blob"]["sha256"]:
            raise ValueError("legacy evidence does not bind exported DMP")
        if loaded.evidence.provenance != "insufficient":
            raise ValueError("legacy provenance must remain conservative")
        faults = []
        for fault, payload in (("missing", None), ("truncated", canonical[:len(canonical)//2]),
                               ("same_length_corruption", bytes([canonical[0] ^ 1]) + canonical[1:])):
            try:
                if payload is None:
                    store.delete(key)
                else:
                    store.put_bytes(key, payload, "application/json")
                try:
                    read()
                except ObjectNotFoundError:
                    if payload is not None:
                        raise
                    code = "ObjectNotFoundError"
                except ApiError as error:
                    if payload is None or error.code != "REVIEW_OBJECT_INVALID":
                        raise
                    code = error.code
                else:
                    raise AssertionError("damaged historical evidence was accepted")
                faults.append({"fault": fault, "rejection": code})
            finally:
                store.put_bytes(key, canonical, "application/json")
            if read().canonical_bytes != canonical:
                raise AssertionError("restored historical bytes changed")
        auxiliary_faults = []
        auxiliary = [
            item for item in snapshot["objects"]
            if item["status"] == "present" and item["key"] != key
            and (item["key"] == run.inspect_object_key
                 or (run.raw_object_prefix and item["key"].startswith(run.raw_object_prefix)))
        ]
        for item in auxiliary:
            auxiliary_key = item["key"]
            original = b"".join(store.stream(auxiliary_key))
            for fault, payload in (("missing", None), ("invalid_json", b"not-json")):
                try:
                    if payload is None:
                        store.delete(auxiliary_key)
                    else:
                        store.put_bytes(auxiliary_key, payload, "application/octet-stream")
                    observed = read()
                    if (observed.canonical_bytes != canonical
                            or observed.evidence.as_dict() != loaded.evidence.as_dict()):
                        raise AssertionError("legacy auxiliary fault changed conservative evidence")
                    auxiliary_faults.append({"key": auxiliary_key, "fault": fault,
                                             "provenance": observed.evidence.provenance})
                finally:
                    store.put_bytes(auxiliary_key, original, "application/octet-stream")
                if hashlib.sha256(b"".join(store.stream(auxiliary_key))).hexdigest() != item["sha256"]:
                    raise AssertionError("historical auxiliary bytes were not restored")
        report = {"status": "PASS", "snapshot_sha256": snapshot_sha, "run_id": run.id,
                  "evidence": loaded.evidence.as_dict(), "faults": faults,
                  "auxiliary_faults": auxiliary_faults,
                  "database_restore": restored,
                  "scope": "historical evidence and optional isolated SQLite restore; no new candidate",
                  "application_database_touched": False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "run_id": run.id, "output": str(args.output)}))


if __name__ == "__main__":
    main()
