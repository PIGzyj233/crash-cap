from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from crashcap_api.architecture_health import collect_architecture_health
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import Artifact, ArtifactBlob, Build, DumpBlob, utcnow
from crashcap_api.services.artifact_blob_backfill import (
    backfill_artifact_blobs,
    cleanup_artifact_blob_legacy_copies,
)
from crashcap_api.services.artifact_blob_export import (
    ArtifactBlobExportError,
    materialize_artifact_blob_export,
)
from crashcap_api.services.artifact_payload_backfill import (
    backfill_artifact_blob_payloads,
    cleanup_artifact_blob_raw_payloads,
)
from crashcap_api.services.artifact_payloads import ArtifactPayloadError, payload_object_key
from crashcap_api.services.common import operation_log
from crashcap_api.services.pdb_storage_inventory import (
    collect_pdb_storage_inventory,
    render_pdb_storage_inventory_markdown,
)
from crashcap_api.services.symbol_backfill import backfill_symbol_projection
from crashcap_api.services.upload_gc import sweep_terminal_upload_payloads
from crashcap_api.storage import ObjectNotFoundError, create_object_store
from crashcap_api.task_reconciliation import reconcile_task_intents
from crashcap_worker.core_runner import CoreExecutor
from crashcap_worker.retention import expire_dump_blobs
from sqlalchemy import func, select


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

    artifact_backfill = commands.add_parser(
        "backfill-artifact-blobs",
        help="verify historical PE/PDB bytes and populate Workspace Artifact Blobs",
    )
    artifact_backfill.add_argument("--after", "--cursor", dest="after")
    artifact_backfill.add_argument("--limit", "--batch-size", dest="limit", type=int, default=100)
    artifact_backfill.add_argument("--apply", action="store_true")
    artifact_backfill.add_argument(
        "--confirm",
        help="apply requires the exact token APPLY_ARTIFACT_BLOB_BACKFILL",
    )
    artifact_backfill.add_argument("--output", type=Path, help="optional JSON report path")

    artifact_cleanup = commands.add_parser(
        "cleanup-artifact-blob-legacy-copies",
        help="dry-run cleanup of retained per-Build copies after Blob UAT",
    )
    artifact_cleanup.add_argument("--after", "--cursor", dest="after")
    artifact_cleanup.add_argument("--limit", "--batch-size", dest="limit", type=int, default=100)
    artifact_cleanup.add_argument("--apply", action="store_true")
    artifact_cleanup.add_argument(
        "--confirm",
        help="apply requires the exact token DELETE_ARTIFACT_BLOB_LEGACY_COPIES",
    )
    artifact_cleanup.add_argument("--output", type=Path, help="optional JSON report path")

    upload_gc = commands.add_parser(
        "gc-upload-payloads",
        help="dry-run terminal Upload payload cleanup after authoritative-copy verification",
    )
    upload_gc.add_argument("--limit", "--batch-size", dest="limit", type=int, default=100)
    upload_gc.add_argument("--apply", action="store_true")
    upload_gc.add_argument(
        "--confirm", help="apply requires the exact token DELETE_TERMINAL_UPLOAD_PAYLOADS"
    )
    upload_gc.add_argument("--output", type=Path, help="optional JSON report path")

    storage_inventory = commands.add_parser(
        "pdb-storage-inventory",
        help="read-only aggregate PostgreSQL, object-store and symbol-volume capacity",
    )
    storage_inventory.add_argument("--output", type=Path, help="optional JSON report path")
    storage_inventory.add_argument(
        "--markdown-output", type=Path, help="optional Markdown review report path"
    )

    payload_backfill = commands.add_parser(
        "backfill-artifact-payloads",
        help="verify and compress identity Artifact Blobs with resumable Blob cursors",
    )
    payload_backfill.add_argument("--after", "--cursor", dest="after")
    payload_backfill.add_argument("--limit", "--batch-size", dest="limit", type=int, default=100)
    payload_backfill.add_argument("--apply", action="store_true")
    payload_backfill.add_argument(
        "--confirm", help="apply requires the exact token APPLY_ARTIFACT_PAYLOAD_BACKFILL"
    )
    payload_backfill.add_argument("--output", type=Path, help="optional JSON report path")

    payload_cleanup = commands.add_parser(
        "cleanup-artifact-payload-raw-copies",
        help="dry-run exact raw canonical cleanup after the payload rollback window",
    )
    payload_cleanup.add_argument("--after", "--cursor", dest="after")
    payload_cleanup.add_argument("--limit", "--batch-size", dest="limit", type=int, default=100)
    payload_cleanup.add_argument("--apply", action="store_true")
    payload_cleanup.add_argument(
        "--confirm", help="apply requires DELETE_ARTIFACT_PAYLOAD_RAW_COPIES"
    )
    payload_cleanup.add_argument("--output", type=Path, help="optional JSON report path")
    storage_inventory.add_argument(
        "--skip-volumes", action="store_true", help="omit local Unified/cache filesystem scans"
    )

    materialize_blob = commands.add_parser(
        "materialize-artifact-blob",
        help="verify and export one exact logical PE/PDB through the dual-format reader",
    )
    materialize_blob.add_argument("--artifact-blob-id", required=True)
    materialize_blob.add_argument(
        "--destination",
        type=Path,
        required=True,
        help="new local output file; existing paths are never overwritten",
    )
    materialize_blob.add_argument("--output", type=Path, help="optional JSON report path")

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

    shared_blob = commands.add_parser(
        "emergency-delete-artifact-blob",
        help="impact-report or explicitly delete one exact shared canonical Artifact Blob",
    )
    shared_blob.add_argument("--artifact-blob-id", required=True)
    shared_blob.add_argument("--apply", action="store_true")
    shared_blob.add_argument(
        "--confirm",
        help="apply requires DELETE_SHARED_ARTIFACT_BLOB followed by the exact ID",
    )
    shared_blob.add_argument("--output", type=Path, help="optional JSON impact report path")
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

    if args.command == "backfill-artifact-blobs":
        if args.apply and args.confirm != "APPLY_ARTIFACT_BLOB_BACKFILL":
            print(
                "apply requires --confirm APPLY_ARTIFACT_BLOB_BACKFILL",
                file=sys.stderr,
            )
            return 2
        store = create_object_store(settings)
        report = backfill_artifact_blobs(
            database.sessions,
            store,
            CoreExecutor(settings),
            after=args.after,
            limit=max(1, args.limit),
            apply=bool(args.apply),
        )
        _emit_json(report, args.output)
        return 1 if report["gaps"] or (args.apply and report["unresolved_gaps"]) else 0

    if args.command == "cleanup-artifact-blob-legacy-copies":
        if args.apply and args.confirm != "DELETE_ARTIFACT_BLOB_LEGACY_COPIES":
            print(
                "apply requires --confirm DELETE_ARTIFACT_BLOB_LEGACY_COPIES",
                file=sys.stderr,
            )
            return 2
        report = cleanup_artifact_blob_legacy_copies(
            database.sessions,
            create_object_store(settings),
            after=args.after,
            limit=max(1, args.limit),
            apply=bool(args.apply),
        )
        _emit_json(report, args.output)
        return 1 if report["skipped"] else 0

    if args.command == "gc-upload-payloads":
        if args.apply and args.confirm != "DELETE_TERMINAL_UPLOAD_PAYLOADS":
            print(
                "apply requires --confirm DELETE_TERMINAL_UPLOAD_PAYLOADS",
                file=sys.stderr,
            )
            return 2
        report = sweep_terminal_upload_payloads(
            database.sessions,
            create_object_store(settings),
            settings,
            limit=max(1, args.limit),
            apply=bool(args.apply),
        )
        _emit_json(report, args.output)
        return 1 if report["failed"] else 0

    if args.command == "pdb-storage-inventory":
        with database.sessions() as session:
            report = collect_pdb_storage_inventory(
                session,
                create_object_store(settings),
                unified_root=None if args.skip_volumes else settings.unified_symbol_root,
                symbolicator_cache_root=(
                    None if args.skip_volumes else settings.symbolicator_cache_root
                ),
            )
        if args.markdown_output:
            args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
            args.markdown_output.write_text(
                render_pdb_storage_inventory_markdown(report), encoding="utf-8"
            )
        _emit_json(report, args.output)
        return 0

    if args.command == "backfill-artifact-payloads":
        if args.apply and args.confirm != "APPLY_ARTIFACT_PAYLOAD_BACKFILL":
            print(
                "apply requires --confirm APPLY_ARTIFACT_PAYLOAD_BACKFILL",
                file=sys.stderr,
            )
            return 2
        report = backfill_artifact_blob_payloads(
            database.sessions,
            create_object_store(settings),
            settings,
            after=args.after,
            limit=max(1, args.limit),
            apply=bool(args.apply),
        )
        _emit_json(report, args.output)
        return 1 if report["gaps"] or (args.apply and report["unresolved_gaps"]) else 0

    if args.command == "cleanup-artifact-payload-raw-copies":
        if args.apply and args.confirm != "DELETE_ARTIFACT_PAYLOAD_RAW_COPIES":
            print(
                "apply requires --confirm DELETE_ARTIFACT_PAYLOAD_RAW_COPIES",
                file=sys.stderr,
            )
            return 2
        report = cleanup_artifact_blob_raw_payloads(
            database.sessions,
            create_object_store(settings),
            settings,
            after=args.after,
            limit=max(1, args.limit),
            apply=bool(args.apply),
        )
        _emit_json(report, args.output)
        return 1 if report["skipped"] else 0

    if args.command == "materialize-artifact-blob":
        destination = args.destination.resolve()
        try:
            with database.sessions() as session:
                report = materialize_artifact_blob_export(
                    session,
                    create_object_store(settings),
                    settings.task_tmp_root,
                    artifact_blob_id=args.artifact_blob_id,
                    destination=destination,
                )
                session.commit()
        except ArtifactBlobExportError as error:
            print(f"materialization refused: {error.code}", file=sys.stderr)
            return 3
        except ArtifactPayloadError as error:
            print(f"materialization failed integrity verification: {error.code}", file=sys.stderr)
            return 4
        except ObjectNotFoundError:
            print("materialization failed: payload object is missing", file=sys.stderr)
            return 4
        except OSError:
            print("materialization failed: local I/O error", file=sys.stderr)
            return 4
        _emit_json(report, args.output)
        return 0

    if args.command == "emergency-delete-artifact-blob":
        identifier = args.artifact_blob_id
        with database.sessions() as session:
            blob = session.get(ArtifactBlob, identifier)
            if blob is None:
                print("exact Artifact Blob was not found", file=sys.stderr)
                return 3
            artifact_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(Artifact)
                    .where(Artifact.artifact_blob_id == identifier)
                )
                or 0
            )
            build_count = int(
                session.scalar(
                    select(func.count(func.distinct(Artifact.build_id))).where(
                        Artifact.artifact_blob_id == identifier
                    )
                )
                or 0
            )
            sealed_build_count = int(
                session.scalar(
                    select(func.count(func.distinct(Build.id)))
                    .join(Artifact, Artifact.build_id == Build.id)
                    .where(
                        Artifact.artifact_blob_id == identifier,
                        Build.sealed_at.is_not(None),
                    )
                )
                or 0
            )
            impact = {
                "schema_version": "artifact-blob-emergency-delete-impact-v1",
                "mode": "apply" if args.apply else "dry-run",
                "artifact_blob_id": identifier,
                "workspace_id": blob.workspace_id,
                "sha256": blob.sha256,
                "kind": blob.kind,
                "size": blob.size,
                "artifact_count": artifact_count,
                "build_count": build_count,
                "sealed_build_count": sealed_build_count,
                "would_mark_missing": True,
            }
            if not args.apply:
                _emit_json(impact, args.output)
                return 0
            expected = f"DELETE_SHARED_ARTIFACT_BLOB {identifier}"
            if args.confirm != expected:
                print(f"apply requires --confirm {expected}", file=sys.stderr)
                return 2
            create_object_store(settings).delete(payload_object_key(blob))
            blob.verification_status = "missing"
            blob.verification_reason = "emergency_deleted"
            blob.updated_at = utcnow()
            operation_log(
                session,
                action="artifact_blob.emergency_delete",
                target_type="artifact_blob",
                target_id=identifier,
                workspace_id=blob.workspace_id,
                result="deleted_canonical",
                details={
                    "artifact_count": artifact_count,
                    "build_count": build_count,
                    "sealed_build_count": sealed_build_count,
                },
            )
            session.commit()
        impact["deleted"] = True
        _emit_json(impact, args.output)
        return 0

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
                build = session.get(Build, row.build_id)
                workspace_id = build.workspace_id if build else None
        if row is None:
            print("exact target was not found", file=sys.stderr)
            return 3
        if isinstance(row, Artifact) and row.artifact_blob_id is not None:
            print(
                "refusing to delete a shared canonical Blob through one Artifact; "
                "use emergency-delete-artifact-blob for an impact report",
                file=sys.stderr,
            )
            return 4
        store.delete(row.object_key)
        if isinstance(row, DumpBlob):
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


def _emit_json(report: dict[str, object], output: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    raise SystemExit(main())
