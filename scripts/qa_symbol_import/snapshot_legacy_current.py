"""Export one explicitly selected Current, read-only, for local isolated replay."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from pathlib import Path

REMOTE = r'''
import base64, hashlib, json
from datetime import datetime, timezone
from sqlalchemy import text, select
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import AnalysisRun, Occurrence, DumpBlob, Artifact, BuildModule
from crashcap_api.storage import create_object_store, ObjectNotFoundError
settings = Settings(create_schema=False)
database = Database(settings)
store = create_object_store(settings)
def row_data(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}
with database.sessions() as session:
    session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    occurrence = session.get(Occurrence, occurrence_id)
    if occurrence is None or not occurrence.current_run_id:
        raise ValueError('selected Occurrence has no Current')
    run = session.get(AnalysisRun, occurrence.current_run_id)
    blob = session.get(DumpBlob, occurrence.dump_blob_id)
    if run is None or blob is None or run.schema_version != '1.0':
        raise ValueError('expected an existing 1.0 Current with Dump Blob')
    report = {'schema_version': 'qai-legacy-snapshot-v1',
              'time_utc': datetime.now(timezone.utc).isoformat(),
              'occurrence': row_data(occurrence), 'run': row_data(run),
              'dump_blob': row_data(blob), 'objects': [], 'database_read_only': True}
    keys = {run.result_object_key, run.inspect_object_key, blob.object_key}
    prefix = run.raw_object_prefix
    # Follow actual FK values, including winner TaskIntent and Build/Workspace rows.
    pending = [(row.__table__, row_data(row)) for row in (occurrence, run, blob)]
    if include_failed:
        failed_runs = session.scalars(select(AnalysisRun).where(
            AnalysisRun.occurrence_id == occurrence_id, AnalysisRun.status == 'FAILED'
        )).all()
        pending.extend((row.__table__, row_data(row)) for row in failed_runs)
    closure = {}
    while pending:
        table, values = pending.pop()
        identity = (table.name, tuple(values[c.name] for c in table.primary_key.columns))
        if identity in closure:
            continue
        if len(closure) >= 100:
            raise ValueError('snapshot dependency limit exceeded')
        closure[identity] = (table, values)
        if table.name == 'builds':
            for child in (BuildModule.__table__, Artifact.__table__):
                children = session.execute(select(child).where(child.c.build_id == values['id'])).mappings()
                pending.extend((child, dict(value)) for value in children)
        for foreign in table.foreign_keys:
            value = values[foreign.parent.name]
            if value is None:
                continue
            target = foreign.column
            dependency = session.execute(select(target.table).where(target == value)).mappings().one()
            pending.append((target.table, dict(dependency)))
    report['database_rows'] = [{'table': table.name, 'row': values}
                               for table, values in closure.values()]
    bindings = {blob.object_key: blob.sha256}
    for table, values in closure.values():
        if table.name == 'builds' and values.get('manifest_object_key'):
            keys.add(values['manifest_object_key'])
        if table.name in ('artifacts', 'artifact_blobs'):
            keys.add(values['object_key'])
            bindings[values['object_key']] = values['sha256']
        if table.name == 'artifact_blobs':
            keys.add(values['payload_object_key'])
            bindings[values['payload_object_key']] = values['payload_sha256']
# No transaction is held during storage reads. Historical objects are copied as bytes.
if prefix:
    for index, entry in enumerate(store.iter_objects(prefix)):
        if index >= 100:
            raise ValueError('raw object enumeration exceeds snapshot limit')
        keys.add(entry.key)
total = 0
for key in sorted(key for key in keys if key):
    try:
        size = store.head(key).size
        if size < 0 or size > 64 * 1024 * 1024:
            raise ValueError('object exceeds snapshot size limit')
        data = bytearray()
        for chunk in store.stream(key):
            if len(data) + len(chunk) > size:
                raise ValueError('object size changed during snapshot')
            total += len(chunk)
            if total > 128 * 1024 * 1024:
                raise ValueError('snapshot exceeds total size limit')
            data.extend(chunk)
        if len(data) != size:
            raise ValueError('object truncated during snapshot')
        digest = hashlib.sha256(data).hexdigest()
        if key in bindings and digest != bindings[key]:
            raise ValueError('stored object identity mismatch')
        report['objects'].append({'key': key, 'status': 'present', 'size': size,
                                  'sha256': digest, 'payload': base64.b64encode(data).decode()})
    except ObjectNotFoundError:
        report['objects'].append({'key': key, 'status': 'missing'})
with database.sessions() as session:
    session.execute(text('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY'))
    occurrence = session.get(Occurrence, occurrence_id)
    run = session.get(AnalysisRun, report['run']['id'])
    blob = session.get(DumpBlob, report['dump_blob']['id'])
    if (row_data(occurrence) != report['occurrence'] or row_data(run) != report['run']
            or row_data(blob) != report['dump_blob']):
        raise ValueError('selected metadata changed during snapshot')
    for table, values in closure.values():
        if table.name == 'builds':
            for child in (BuildModule.__table__, Artifact.__table__):
                expected = {
                    tuple(row[c.name] for c in child.primary_key.columns)
                    for saved_table, row in closure.values()
                    if saved_table.name == child.name and row['build_id'] == values['id']
                }
                actual = {
                    tuple(row[c.name] for c in child.primary_key.columns)
                    for row in session.execute(
                        select(child).where(child.c.build_id == values['id'])
                    ).mappings()
                }
                if actual != expected:
                    raise ValueError('Build material membership changed during snapshot')
        query = select(table)
        for column in table.primary_key.columns:
            query = query.where(column == values[column.name])
        if dict(session.execute(query).mappings().one()) != values:
            raise ValueError('dependency changed during snapshot')
print(json.dumps(report, default=str))
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", required=True)
    parser.add_argument("--occurrence", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--include-failed", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output must be a new directory")
    result = subprocess.run(
        ["docker", "exec", "-i", args.container, "python", "-"],
        input=("occurrence_id = " + repr(args.occurrence) + "\ninclude_failed = "
               + repr(args.include_failed) + "\n" + REMOTE),
        text=True, capture_output=True, timeout=180, check=False,
    )
    if result.returncode:
        raise RuntimeError("Read-only snapshot failed: " + result.stderr[-1000:])
    report = json.loads(result.stdout)
    args.output.mkdir(parents=True, exist_ok=False)
    objects = args.output / "objects"
    objects.mkdir()
    for item in report["objects"]:
        if item["status"] != "present":
            continue
        payload = base64.b64decode(item.pop("payload"), validate=True)
        if len(payload) != item["size"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
            raise ValueError("exported bytes failed verification")
        item["local_path"] = "objects/" + item["sha256"]
        (objects / item["sha256"]).write_bytes(payload)
    report["exporter_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    report["source_container"] = args.container
    manifest = args.output / "snapshot.json"
    manifest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot": str(manifest), "run_id": report["run"]["id"],
                      "objects": len(report["objects"]), "database_read_only": True}))


if __name__ == "__main__":
    main()
