from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from crashcap_api.architecture_health import collect_architecture_health
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import Artifact, DumpBlob
from crashcap_api.services.common import operation_log
from crashcap_api.services.symbol_backfill import backfill_symbol_projection
from crashcap_api.storage import create_object_store
from crashcap_api.task_reconciliation import reconcile_task_intents
from crashcap_worker.retention import expire_dump_blobs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crashcap-ops", description="Local-only Crash-Cap Phase 1 operations"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    retention = commands.add_parser("retention", help="expire raw Dump Blobs past retention")
    retention.add_argument("--limit", type=int, default=1000)

    health = commands.add_parser(
        "architecture-health",
        help="read-only Current Analysis, Canonical and Symbol Health preflight",
    )
    health.add_argument(
        "--skip-object-check",
        action="store_true",
        help="check PostgreSQL only; report status is PARTIAL when it passes",
    )
    health.add_argument("--output", type=Path, help="optional JSON report path")

    reconcile = commands.add_parser(
        "reconcile-task-intents",
        help="dry-run scan for committed work that lacks active task ownership",
    )
    reconcile.add_argument("--after", help="resume strictly after this cursor")
    reconcile.add_argument("--limit", type=int, default=100)
    reconcile.add_argument("--apply", action="store_true")
    reconcile.add_argument(
        "--confirm",
        help="apply requires the exact token APPLY_TASK_RECONCILIATION",
    )

    symbol_backfill = commands.add_parser(
        "backfill-symbol-projection",
        help="dry-run or resume Current Analysis based Symbol Health projection",
    )
    symbol_backfill.add_argument("--after", help="resume strictly after this Occurrence ID")
    symbol_backfill.add_argument("--limit", type=int, default=100)
    symbol_backfill.add_argument(
        "--retry-gaps",
        action="store_true",
        help="retry unresolved durable gaps instead of advancing the main cursor",
    )
    symbol_backfill.add_argument("--apply", action="store_true")
    symbol_backfill.add_argument(
        "--confirm",
        help="apply requires the exact token APPLY_SYMBOL_PROJECTION_BACKFILL",
    )
    symbol_backfill.add_argument("--output", type=Path, help="optional JSON report path")

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
    if args.command == "architecture-health":
        store = None if args.skip_object_check else create_object_store(settings)
        with database.sessions() as session:
            report = collect_architecture_health(session, store)
        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 1 if report["status"] == "FAIL" else 0

    if args.command == "reconcile-task-intents":
        if args.apply and args.confirm != "APPLY_TASK_RECONCILIATION":
            print(
                "apply requires --confirm APPLY_TASK_RECONCILIATION",
                file=sys.stderr,
            )
            return 2
        with database.sessions() as session:
            report = reconcile_task_intents(
                session,
                settings,
                after=args.after,
                limit=max(1, args.limit),
                apply=bool(args.apply),
            )
            if args.apply:
                session.commit()
            else:
                session.rollback()
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    if args.command == "backfill-symbol-projection":
        if args.apply and args.confirm != "APPLY_SYMBOL_PROJECTION_BACKFILL":
            print(
                "apply requires --confirm APPLY_SYMBOL_PROJECTION_BACKFILL",
                file=sys.stderr,
            )
            return 2
        store = create_object_store(settings)
        report = backfill_symbol_projection(
            database.sessions,
            store,
            settings.schema_root,
            after=args.after,
            limit=max(1, args.limit),
            apply=bool(args.apply),
            retry_gaps=bool(args.retry_gaps),
        )
        rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 1 if report["gaps"] or (args.apply and report["unresolved_gaps"]) else 0

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
