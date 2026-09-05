"""Local operational checks; user uploads use the native crashcap command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from crashcap_api.architecture_health import collect_architecture_health
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.services.upload_gc import sweep_terminal_upload_payloads
from crashcap_api.storage import create_object_store
from crashcap_api.task_reconciliation import reconcile_task_intents
from crashcap_worker.retention import expire_dump_blobs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="crashcap-ops")
    commands = parser.add_subparsers(dest="command", required=True)
    health = commands.add_parser("architecture-health")
    health.add_argument("--skip-object-check", action="store_true")
    health.add_argument("--output", type=Path)
    for name in ("reconcile-task-intents", "upload-gc"):
        command = commands.add_parser(name)
        command.add_argument("--limit", type=int, default=100)
        command.add_argument("--apply", action="store_true")
    retention = commands.add_parser("retention")
    retention.add_argument("--limit", type=int, default=1000)
    args = parser.parse_args(argv)
    settings = Settings()
    database = Database(settings)
    store = create_object_store(settings)
    try:
        if args.command == "architecture-health":
            with database.sessions() as session:
                report = collect_architecture_health(
                    session, None if args.skip_object_check else store
                )
        elif args.command == "reconcile-task-intents":
            with database.sessions.begin() as session:
                report = reconcile_task_intents(
                    session, settings, limit=args.limit, apply=args.apply
                )
        elif args.command == "upload-gc":
            report = sweep_terminal_upload_payloads(
                database.sessions, store, settings, limit=args.limit, apply=args.apply
            )
        else:
            report = {"expired": expire_dump_blobs(database.sessions, store, limit=args.limit)}
        rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        if getattr(args, "output", None):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return int(report.get("status") == "FAIL")
    finally:
        database.dispose()
