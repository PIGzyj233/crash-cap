from __future__ import annotations

import argparse
import sys

from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import Artifact, DumpBlob
from crashcap_api.services.common import operation_log
from crashcap_api.storage import create_object_store
from crashcap_worker.retention import expire_dump_blobs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crashcap-ops", description="Local-only Crash-Cap Phase 1 operations"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    retention = commands.add_parser("retention", help="expire raw Dump Blobs past retention")
    retention.add_argument("--limit", type=int, default=1000)

    emergency = commands.add_parser(
        "emergency-delete", help="irreversibly remove one exact raw object"
    )
    target = emergency.add_mutually_exclusive_group(required=True)
    target.add_argument("--blob-id")
    target.add_argument("--artifact-id")
    emergency.add_argument(
        "--confirm",
        required=True,
        help="must exactly equal the selected Blob or Artifact ID",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    database = Database(settings)
    store = create_object_store(settings)
    if args.command == "retention":
        count = expire_dump_blobs(database.sessions, store, limit=max(1, args.limit))
        print(f"expired_raw_dump_blobs={count}")
        return 0

    identifier = args.blob_id or args.artifact_id
    if args.confirm != identifier:
        print("confirmation does not match the exact target ID", file=sys.stderr)
        return 2
    with database.sessions() as session:
        row: DumpBlob | Artifact | None
        if args.blob_id:
            row = session.get(DumpBlob, identifier)
            target_type = "dump_blob"
            workspace_id = row.workspace_id if row else None
        else:
            row = session.get(Artifact, identifier)
            target_type = "artifact"
            workspace_id = None
            if row:
                from crashcap_api.models import Build

                build = session.get(Build, row.build_id)
                workspace_id = build.workspace_id if build else None
        if row is None:
            print("exact target was not found", file=sys.stderr)
            return 3
        store.delete(row.object_key)
        if isinstance(row, DumpBlob):
            from crashcap_api.models import utcnow

            row.deleted_at = utcnow()
        operation_log(
            session,
            action="emergency.delete",
            target_type=target_type,
            target_id=identifier,
            workspace_id=workspace_id,
            result="deleted_raw_only",
            details={
                "object_key_sha256": __import__("hashlib")
                .sha256(row.object_key.encode())
                .hexdigest()
            },
        )
        session.commit()
    print(f"deleted {target_type} {identifier}; metadata and historical statistics retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
