"""Local operational checks; user uploads use the native crashcap command."""

from __future__ import annotations

import argparse
import getpass
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
    bootstrap = commands.add_parser("create-admin")
    bootstrap.add_argument("--username", required=True)
    bootstrap.add_argument("--display-name", required=True)
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
    if args.command == "create-admin":
        from crashcap_api.auth import normalize_username, password_hash
        from crashcap_api.ids import new_id
        from crashcap_api.models import User
        from crashcap_api.services.common import operation_log

        password = getpass.getpass("New administrator password: ")
        if password != getpass.getpass("Repeat password: "):
            raise ValueError("Passwords do not match")
        try:
            with database.sessions.begin() as session:
                row = User(
                    id=new_id("usr"),
                    username=normalize_username(args.username),
                    display_name=args.display_name,
                    password_hash=password_hash(password),
                    kind="human",
                    role="admin",
                    enabled=True,
                )
                session.add(row)
                session.flush()
                operation_log(
                    session,
                    action="account.bootstrap_admin",
                    target_type="user",
                    target_id=row.id,
                    workspace_id=None,
                )
            print("Administrator created")
            return 0
        finally:
            database.dispose()
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
