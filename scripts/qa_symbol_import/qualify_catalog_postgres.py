"""Qualify catalog transactions using an owned disposable PostgreSQL only."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from qualify_compatibility_postgres import docker

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "target/qa-symbol-import"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=("source-failures",),
                        help="Run one first-launch scenario without combining legacy flags")
    parser.add_argument("--restore", action="store_true", help="Restore C08 metadata and payload and replay with a fresh Symbolicator cache")
    parser.add_argument("--cross-module-browser", action="store_true", help="Observe real C08/C09 reports in browser")
    parser.add_argument("--cross-module", action="store_true", help="Qualify C08 unknown DLL and owned caller")
    parser.add_argument(
        "--imports",
        action="store_true",
        help="Also qualify import API and durable validation",
    )
    parser.add_argument(
        "--history", action="store_true", help="Also qualify historical pair admission"
    )
    parser.add_argument(
        "--materials",
        action="store_true",
        help="Qualify catalog HTTP materials and native analysis",
    )
    parser.add_argument(
        "--demands",
        action="store_true",
        help="Qualify durable inspect and demand fanout",
    )
    parser.add_argument(
        "--planner",
        action="store_true",
        help="Qualify real catalog resolution planning",
    )
    parser.add_argument(
        "--workspace-builds",
        action="store_true",
        help="Qualify consumer Workspace Build snapshots",
    )
    parser.add_argument(
        "--workspace-policies",
        action="store_true",
        help="Qualify consumer role and source policies",
    )
    parser.add_argument(
        "--native-source",
        action="store_true",
        help="Qualify native frozen ZIP source enrichment",
    )
    parser.add_argument(
        "--delivery", action="store_true", help="Qualify frozen Redis delivery recovery"
    )
    parser.add_argument(
        "--large-automatic",
        action="store_true",
        help="Run 201 real automatic analyses across the default enumeration page",
    )
    parser.add_argument(
        "--late-pair",
        action="store_true",
        help="Qualify catalog arrival after native reports exist",
    )
    parser.add_argument(
        "--large-late-pair",
        action="store_true",
        help="Qualify catalog arrival and native updates for 201 Workspaces",
    )
    parser.add_argument(
        "--demand-restart-browser",
        action="store_true",
        help="Interactively qualify C20 browser submission and lost-response recovery",
    )
    parser.add_argument(
        "--native-demand-restart",
        action="store_true",
        help="Qualify real Core timeout exhaustion and explicit manual restart",
    )
    parser.add_argument(
        "--resident-restart",
        action="store_true",
        help="Kill and restart the real resident planner after its first adopted Run",
    )
    parser.add_argument(
        "--legacy-current", action="store_true",
        help="Qualify native 1.0 Current preservation with a native 1.1 candidate",
    )
    parser.add_argument(
        "--submissions", action="store_true", help="Qualify manual submission history"
    )
    parser.add_argument(
        "--reviews",
        action="store_true",
        help="Qualify provider review API transactions",
    )
    parser.add_argument(
        "--review-browser", action="store_true",
        help="Serve real legacy/new reports on loopback for explicit browser qualification",
    )
    parser.add_argument(
        "--review-browser-drop-response", action="store_true",
        help="Return a test-only 503 after the first successful browser review commit",
    )
    parser.add_argument("--correction-browser", action="store_true", help="Serve native withdrawn candidate for browser correction review")
    parser.add_argument("--expiry-browser", action="store_true", help="Serve real expired-DMP reports for browser observation")
    parser.add_argument("--role-browser", action="store_true", help="Declare a Workspace role and review its native candidate in the browser")
    parser.add_argument("--historical-current", type=Path, help="Replay an exported existing 1.0 Current")
    parser.add_argument("--historical-incomplete", action="store_true", help="Require incomplete historical pair rejection")
    parser.add_argument("--historical-expired", action="store_true", help="Evaluate snapshot after its recorded DMP expiry")
    parser.add_argument("--historical-auxiliary-missing", action="store_true", help="Remove old inspect/raw from the isolated replay store")
    parser.add_argument("--historical-auxiliary-corrupt", action="store_true", help="Corrupt old inspect/raw in the isolated replay store")
    parser.add_argument("--historical-exhausted", action="store_true", help="Keep historical Canonical missing through all retry attempts")
    parser.add_argument("--historical-material-blocked", action="store_true", help="Keep a historical symbol payload corrupt during planning retries")
    args = parser.parse_args()
    if args.scenario:
        if any(value for key, value in vars(args).items() if key != "scenario"):
            parser.error("--scenario cannot be combined with legacy qualification flags")
        args.materials = True
    late_pair_requested = any((
        args.late_pair, args.large_late_pair, args.role_browser,
        args.expiry_browser, args.correction_browser,
    ))
    restart_requested = args.native_demand_restart or args.demand_restart_browser
    if late_pair_requested and restart_requested:
        parser.error("late-pair and demand-restart scenarios must run separately")
    if args.historical_material_blocked and (not args.historical_current or args.historical_expired or args.historical_incomplete):
        parser.error("--historical-material-blocked requires a complete historical Current without expiry")
    os.environ["QAI_HISTORICAL_MATERIAL_BLOCKED"] = "1" if args.historical_material_blocked else "0"
    if args.historical_exhausted and (not args.historical_current or args.historical_expired):
        parser.error("--historical-exhausted requires --historical-current without --historical-expired")
    os.environ["QAI_HISTORICAL_EXHAUSTED"] = "1" if args.historical_exhausted else "0"
    if args.historical_auxiliary_corrupt and (
        not args.historical_current or args.historical_expired or args.historical_auxiliary_missing
    ):
        parser.error("--historical-auxiliary-corrupt requires --historical-current and excludes expired/missing")
    os.environ["QAI_HISTORICAL_AUXILIARY_CORRUPT"] = "1" if args.historical_auxiliary_corrupt else "0"
    if args.historical_auxiliary_missing and (not args.historical_current or args.historical_expired):
        parser.error("--historical-auxiliary-missing requires --historical-current without --historical-expired")
    os.environ["QAI_HISTORICAL_AUXILIARY_MISSING"] = "1" if args.historical_auxiliary_missing else "0"
    if args.historical_expired and not args.historical_current:
        parser.error("--historical-expired requires --historical-current")
    os.environ["QAI_HISTORICAL_EXPIRED"] = "1" if args.historical_expired else "0"
    if args.historical_incomplete and not args.historical_current:
        parser.error("--historical-incomplete requires --historical-current")
    os.environ["QAI_HISTORICAL_INCOMPLETE"] = "1" if args.historical_incomplete else "0"
    if args.historical_current:
        args.legacy_current = True
        os.environ["QAI_HISTORICAL_SNAPSHOT"] = str(args.historical_current.resolve(strict=True))
    if args.role_browser:
        if args.expiry_browser or args.correction_browser or args.review_browser or args.review_browser_drop_response or args.large_late_pair:
            parser.error("--role-browser requires the isolated two-Workspace lane")
        args.late_pair = True
    if args.expiry_browser:
        if args.correction_browser or args.review_browser or args.review_browser_drop_response or args.large_late_pair:
            parser.error("--expiry-browser requires the isolated two-Workspace lane")
        args.late_pair = True
    if args.correction_browser:
        args.late_pair = True
    if args.review_browser_drop_response and not args.correction_browser:
        args.review_browser = True
    if args.review_browser:
        args.legacy_current = True
    if args.large_late_pair:
        args.late_pair = True
    if args.demand_restart_browser:
        args.native_demand_restart = True
    if args.resident_restart or args.legacy_current or args.native_demand_restart:
        args.materials = True
    if args.late_pair:
        args.materials = True
    if args.large_automatic:
        args.materials = True
    if args.restore:
        args.cross_module = True
        os.environ["CRASHCAP_QA_RESTORE"] = "1"
    if args.cross_module_browser:
        args.cross_module = True
        os.environ["CRASHCAP_QA_CROSS_MODULE_BROWSER"] = "1"
    if args.cross_module:
        args.materials = True
    if args.native_source:
        args.materials = True
    if args.history:
        args.imports = True
    prefix = args.scenario or (
        "historical-material-blocked"
        if args.historical_material_blocked
        else
        "historical-exhausted"
        if args.historical_exhausted
        else
        "historical-auxiliary-corrupt"
        if args.historical_auxiliary_corrupt
        else
        "historical-auxiliary-missing"
        if args.historical_auxiliary_missing
        else
        "historical-expired"
        if args.historical_expired
        else "historical-incomplete"
        if args.historical_incomplete
        else "historical-current"
        if args.historical_current
        else "restore"
        if args.restore
        else "cross-module"
        if args.cross_module
        else "role-browser"
        if args.role_browser
        else
        "expiry-browser"
        if args.expiry_browser
        else
        "correction-review-browser"
        if args.correction_browser
        else "result-review-browser"
        if args.review_browser
        else "legacy-current"
        if args.legacy_current
        else "late-pair-large"
        if args.large_late_pair
        else "reviews-postgres"
        if args.reviews
        else "submissions-postgres"
        if args.submissions
        else "demand-restart-browser"
        if args.demand_restart_browser
        else "native-demand-restart"
        if args.native_demand_restart
        else "resident-restart"
        if args.resident_restart
        else "late-pair"
        if args.late_pair
        else "automatic-large"
        if args.large_automatic
        else "frozen-delivery"
        if args.delivery
        else "native-source"
        if args.native_source
        else "workspace-policies"
        if args.workspace_policies
        else "workspace-builds"
        if args.workspace_builds
        else "planner-native"
        if args.planner and args.materials
        else "planner-postgres"
        if args.planner
        else "demand-postgres"
        if args.demands
        else "material-source"
        if args.materials
        else (
            "history-postgres"
            if args.history
            else "import-postgres"
            if args.imports
            else "catalog-postgres"
        )
    )
    OUT.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    container = None
    report = {
        "status": "RUNNING",
        "time_utc": datetime.now(UTC).isoformat(),
        "application_database_touched": False,
    }
    receipt = OUT / f"{prefix}.json"
    catalog_receipt = OUT / f"{prefix}-catalog-real.json"
    receipt.write_text(json.dumps(report) + "\n", encoding="utf-8")
    try:
        image = json.loads(
            docker("image", "inspect", "postgres:16.10-bookworm").stdout
        )[0]
        report["image_id"] = image["Id"]
        container = docker(
            "run",
            "--pull=never",
            "-d",
            "--name",
            "qai-catalog-pg-" + token,
            "--label",
            "crashcap.qai.catalog=" + token,
            "-e",
            "POSTGRES_PASSWORD=qai-local-fixture",
            "-e",
            "POSTGRES_DB=crashcap_qai_catalog",
            "-p",
            "127.0.0.1::5432",
            image["Id"],
        ).stdout.strip()
        report["container_id"] = container
        for _ in range(60):
            try:
                docker(
                    "exec",
                    container,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "postgres",
                    "-d",
                    "crashcap_qai_catalog",
                )
                break
            except subprocess.CalledProcessError:
                time.sleep(0.5)
        else:
            raise RuntimeError("Owned PostgreSQL did not become ready")
        mapping = docker("port", container, "5432/tcp").stdout.strip()
        if (
            not mapping.startswith("127.0.0.1:")
            or not mapping.removeprefix("127.0.0.1:").isdigit()
        ):
            raise RuntimeError("Owned PostgreSQL was not mapped only to loopback")
        report["postgres_version"] = docker(
            "exec",
            container,
            "psql",
            "-U",
            "postgres",
            "-d",
            "crashcap_qai_catalog",
            "-Atc",
            "SHOW server_version",
        ).stdout.strip()
        url = f"postgresql+psycopg://postgres:qai-local-fixture@{mapping}/crashcap_qai_catalog"
        junit = OUT / f"{prefix}.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-v"
            if args.workspace_builds or args.workspace_policies or args.native_source
            else "-q",
            "tests/test_symbol_catalog_postgres.py",
            *(["tests/test_catalog_review_postgres.py"] if args.reviews else []),
            *(["tests/test_frozen_delivery_redis.py"] if args.delivery else []),
            *(
                ["tests/test_occurrence_submissions_postgres.py"]
                if args.submissions
                else []
            ),
            *(["tests/test_symbol_imports_postgres.py"] if args.imports else []),
            *(["tests/test_catalog_backfill_postgres.py"] if args.history else []),
            *(
                ["tests/test_native_source_failures.py"]
                if args.scenario == "source-failures"
                else ["tests/test_historical_current_native.py::test_historical_current_native_candidate"]
                if args.historical_current
                else ["tests/test_catalog_source_real.py::test_unknown_fault_with_owned_caller"]
                if args.cross_module
                else ["tests/test_catalog_source_real.py::test_legacy_current_preserved_for_native_candidate"]
                if args.legacy_current
                else
                [
                    "tests/test_catalog_source_real.py::test_late_catalog_pair_updates_existing_native_reports"
                ]
                if args.late_pair
                else [
                    "tests/test_native_demand_restart.py::test_native_timeout_exhaustion_then_explicit_restart"
                    if args.native_demand_restart
                    else "tests/test_catalog_source_real.py::test_automatic_planner_to_real_worker_promotes_current"
                ]
                if args.resident_restart or args.native_demand_restart
                else [
                    "tests/test_catalog_source_real.py::test_real_frozen_worker_uses_catalog_materials_for_unwind_and_symbols",
                    "tests/test_catalog_source_real.py::test_native_publications_preserve_sealed_history",
                ]
                if args.native_source
                else ["tests/test_catalog_source_real.py"]
                if args.materials
                else []
            ),
            *(["tests/test_analysis_demands_postgres.py"] if args.demands else []),
            *(["tests/test_resolution_planner.py"] if args.planner else []),
            *(["tests/test_workspace_builds.py"] if args.workspace_builds else []),
            *(["tests/test_workspace_policies.py"] if args.workspace_policies else []),
            *(
                ["tests/test_workspace_module_roles_api.py"]
                if args.workspace_policies
                else []
            ),
            *(["tests/test_frozen_run_adoption.py"] if args.workspace_policies else []),
            *(["tests/test_current_decisions.py"] if args.workspace_policies else []),
            *(
                ["tests/test_current_decisions_postgres.py"]
                if args.workspace_policies
                else []
            ),
            *(
                ["-k", "not native_failure_reports"]
                if args.workspace_policies and os.getenv("QAI_NATIVE_FAILURE_COMPARISON") != "1"
                else []
            ),
            f"--junitxml={junit}",
        ]
        report["command"] = command
        report["test_timeout_seconds"] = (
            1200
            if args.scenario == "source-failures"
            else
            3600
            if args.review_browser or args.correction_browser or args.expiry_browser or args.role_browser or args.cross_module_browser or args.demand_restart_browser
            else 7200
            if args.large_automatic or args.large_late_pair
            else 600
            if args.native_source
            else 360
            if args.workspace_builds or args.workspace_policies or args.materials
            else 180
        )
        # Stream to a retained log so a timeout still identifies the last test.
        with (OUT / f"{prefix}.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(
                command,
                cwd=ROOT / "platform",
                env=dict(
                    os.environ,
                    CRASHCAP_QA_DEMAND_RESTART_BROWSER="1" if args.demand_restart_browser else "0",
                    CRASHCAP_QA_REVIEW_BROWSER="1" if args.review_browser else "0",
                    CRASHCAP_QA_EXPIRY_BROWSER="1" if args.expiry_browser else "0",
                    CRASHCAP_QA_ROLE_BROWSER="1" if args.role_browser else "0",
                    CRASHCAP_QA_CORRECTION_BROWSER="1" if args.correction_browser else "0",
                    CRASHCAP_QA_REVIEW_DROP_RESPONSE="1" if args.review_browser_drop_response else "0",
                    QAI_CATALOG_DATABASE_URL=url,
                    QAI_CATALOG_RECEIPT_OUTPUT=str(catalog_receipt),
                    QAI_IMPORT_REAL="1",
                    QAI_HISTORY_REAL="1",
                    QAI_MATERIAL_REAL="1",
                    QAI_MATERIAL_RUN_TOKEN=token,
                    QAI_AUTOMATIC_WORKSPACES="201" if args.large_automatic else "4",
                    QAI_LATE_PAIR_WORKSPACES="201" if args.large_late_pair else "2",
                    QAI_AUTOMATIC_RESIDENT_RESTART="1"
                    if args.resident_restart
                    else "0",
                    QAI_DEMAND_REAL="1",
                    QAI_PLANNER_REAL="1",
                    QAI_PLANNER_RUN_TOKEN=token,
                    QAI_DELIVERY_RUN_TOKEN=token,
                ),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=report["test_timeout_seconds"],
                check=False,
            )
        report.update(command=command, exit_code=result.returncode)
        if result.returncode:
            raise RuntimeError(f"PostgreSQL qualification failed; inspect {prefix}.log")
        suites = ET.parse(junit).getroot()
        expected = (
            (14 if args.history else 10 if args.imports else 4)
            + (
                5
                if args.scenario == "source-failures"
                else 2
                if args.cross_module
                else 1
                if args.late_pair or args.resident_restart or args.legacy_current or args.native_demand_restart
                else 6
                if args.native_source
                else 13
                if args.materials
                else 0
            )
            + (26 if args.demands else 0)
            + (11 if args.planner else 0)
            + (18 if args.workspace_builds else 0)
            + (
                55 + int(os.getenv("QAI_NATIVE_FAILURE_COMPARISON") == "1")
                if args.workspace_policies else 0
            )
            + (2 if args.delivery else 0)
            + (1 if args.submissions else 0)
            + (5 if args.reviews else 0)
        )
        if len(suites.findall(".//testcase")) != expected or suites.findall(
            ".//skipped"
        ):
            raise RuntimeError(
                f"All {expected} real PostgreSQL checks must execute without skips"
            )
        report["status"] = "PASS"
    except Exception as error:  # noqa: BLE001 - retain failure receipts and finish owned-resource cleanup
        report.update(status="FAIL", error=f"{type(error).__name__}: {error}")
        if isinstance(error, subprocess.CalledProcessError):
            report["command_stderr"] = str(error.stderr or "")[-4000:]
        if container is not None:
            with suppress(subprocess.CalledProcessError):
                logs = docker("logs", container)
                report["owned_postgres_log"] = (logs.stdout + logs.stderr)[-12000:]
    finally:
        if args.delivery or args.materials:
            try:
                owned = docker(
                    "ps", "-aq", "--filter", "label=crashcap.qai.delivery.run=" + token
                ).stdout.split()
                for child in owned:
                    owner = docker(
                        "inspect",
                        child,
                        "--format",
                        '{{index .Config.Labels "crashcap.qai.delivery.run"}}',
                    ).stdout.strip()
                    if owner != token:
                        raise RuntimeError(
                            "Refusing delivery cleanup: ownership changed"
                        )
                    docker("rm", "-f", "-v", child)
                report["owned_redis_containers_removed"] = True
                report["redis_image_id"] = json.loads(
                    docker("image", "inspect", "redis:7.4.5-bookworm").stdout
                )[0]["Id"]
            except Exception as error:  # noqa: BLE001 - retain failure receipts and finish owned-resource cleanup
                report.update(status="FAIL", delivery_cleanup_error=str(error))
        if args.materials:
            try:
                owned = docker(
                    "ps", "-aq", "--filter", "label=crashcap.qai.material.run=" + token
                ).stdout.split()
                for child in owned:
                    owner = docker(
                        "inspect",
                        child,
                        "--format",
                        '{{index .Config.Labels "crashcap.qai.material.run"}}',
                    ).stdout.strip()
                    if owner != token:
                        raise RuntimeError(
                            "Refusing material cleanup: ownership changed"
                        )
                    docker("rm", "-f", "-v", child)
                report["owned_material_containers_removed"] = True
                report["material_fallback_cleanup"] = owned
            except Exception as error:  # noqa: BLE001 - retain failure receipts and finish owned-resource cleanup
                report.update(status="FAIL", material_cleanup_error=str(error))
        if container is not None:
            try:
                owner = docker(
                    "inspect",
                    container,
                    "--format",
                    '{{index .Config.Labels "crashcap.qai.catalog"}}',
                ).stdout.strip()
                if owner != token:
                    raise RuntimeError("Refusing cleanup: ownership changed")
                docker("rm", "-f", "-v", container)
                report["owned_container_and_volume_removed"] = True
            except Exception as error:  # noqa: BLE001 - retain failure receipts and finish owned-resource cleanup
                report.update(status="FAIL", cleanup_error=str(error))
        paths = [
            Path(__file__).resolve(),
            ROOT / "platform/api/crashcap_api/models.py",
            ROOT / "platform/api/crashcap_api/services/symbol_catalog.py",
            ROOT / "platform/api/crashcap_api/services/artifact_blob_backfill.py",
            ROOT / "platform/api/crashcap_api/services/artifact_payload_backfill.py",
            ROOT / "platform/api/crashcap_api/storage.py",
            ROOT / "platform/worker/crashcap_worker/catalog_validation.py",
            ROOT / "platform/worker/crashcap_worker/core_runner.py",
            ROOT / "platform/migrations/versions/0012_global_symbol_catalog.py",
            ROOT / "platform/tests/test_symbol_catalog.py",
            ROOT / "platform/tests/test_symbol_catalog_postgres.py",
            OUT / f"{prefix}.xml",
            OUT / f"{prefix}.log",
            catalog_receipt,
        ]
        if args.imports:
            paths.extend(
                ROOT / path
                for path in (
                    "platform/api/crashcap_api/services/symbol_imports.py",
                    "platform/api/crashcap_api/routes_symbol_imports.py",
                    "platform/api/crashcap_api/task_handoff.py",
                    "platform/api/crashcap_api/task_reconciliation.py",
                    "platform/api/crashcap_api/contracts.py",
                    "platform/api/crashcap_api/config.py",
                    "platform/worker/crashcap_worker/symbol_imports.py",
                    "platform/worker/crashcap_worker/relay_main.py",
                    "platform/migrations/versions/0013_symbol_imports.py",
                    "platform/tests/test_symbol_imports.py",
                    "platform/tests/test_symbol_imports_postgres.py",
                )
            )
            paths.extend(
                (OUT / f"{prefix}.xml", OUT / f"{prefix}.log", OUT / "import-real.json")
            )
        if args.history:
            paths.extend(
                ROOT / path
                for path in (
                    "platform/api/crashcap_api/services/catalog_backfill.py",
                    "platform/api/crashcap_api/services/artifact_payloads.py",
                    "platform/cli/crashcap_cli/main.py",
                    "platform/migrations/versions/0014_catalog_backfill.py",
                    "platform/tests/test_catalog_backfill.py",
                    "platform/tests/test_catalog_backfill_postgres.py",
                    "target/qa-symbol-import/history-real.json",
                )
            )
        if args.materials:
            paths.extend(
                ROOT / path
                for path in (
                    "platform/api/crashcap_api/services/catalog_materials.py",
                    "platform/api/crashcap_api/catalog_source.py",
                    "platform/api/crashcap_api/symbol_source.py",
                    "platform/api/crashcap_api/config.py",
                    "platform/worker/crashcap_worker/frozen_core.py",
                    "platform/tests/test_catalog_source.py",
                    "platform/tests/test_catalog_source_real.py",
                    "platform/tests/test_native_source_failures.py",
                    "platform/tests/test_historical_current_native.py",
                    "scripts/qa_symbol_import/replay_legacy_snapshot.py",
                    "scripts/qa_symbol_import/snapshot_legacy_current.py",
                    "platform/tests/native_publication_roles.py",
                    "platform/tests/fixture_source.py",
                    "platform/tests/catalog_restore.py",
                    "platform/tests/restored_replay.py",
                    "platform/tests/restored_symbolicator.py",
                    "platform/tests/test_fixture_source.py",
                    "platform/tests/native_publication_analysis.py",
                    "platform/tests/native_unknown_fault.py",
                    "platform/tests/cross_module_browser.py",
                )
            )
            paths.extend((OUT / "material-source" / token).rglob("*.json"))
            paths.extend((OUT / f"{prefix}.xml", OUT / f"{prefix}.log"))
            report["material_artifacts"] = str(OUT / "material-source" / token)
        if args.demands:
            paths.extend(
                ROOT / path
                for path in (
                    "platform/api/crashcap_api/services/analysis_demands.py",
                    "platform/api/crashcap_api/services/analysis_scheduler.py",
                    "platform/migrations/versions/0020_frozen_grouping.py",
                    "platform/api/crashcap_api/frozen_inputs.py",
                    "platform/worker/crashcap_worker/demand_inspection.py",
                    "platform/tests/demand_restart_browser.py",
                    "platform/tests/test_native_demand_restart.py",
                    "platform/tests/test_demand_restart_api.py",
                    "platform/api/crashcap_api/routes_demands.py",
                    "platform/worker/crashcap_worker/automatic_analysis.py",
                    "platform/worker/crashcap_worker/automatic_main.py",
                    "platform/pyproject.toml",
                    "platform/migrations/versions/0015_analysis_demands.py",
                    "platform/migrations/versions/0019_analysis_scheduler.py",
                    "platform/tests/test_analysis_demands.py",
                    "platform/tests/test_analysis_demands_postgres.py",
                    "platform/tests/test_manual_demand_restart.py",
                    "platform/tests/test_demand_restart_api.py",
                    "platform/api/crashcap_api/routes_demands.py",
                    "platform/api/crashcap_api/services/demand_queries.py",
                    "platform/migrations/versions/0023_demand_restarts.py",
                    "platform/tests/test_analysis_scheduler.py",
                    "fixtures/p0-b01-null-read/generated/pe-metadata.json",
                    "fixtures/p0-b01-null-read/generated/null-read.dmp",
                )
            )
            paths.extend((OUT / f"{prefix}.xml", OUT / f"{prefix}.log"))
        if args.planner:
            paths.extend(
                ROOT / path
                for path in (
                    "platform/api/crashcap_api/services/resolution_planning.py",
                    "platform/api/crashcap_api/services/catalog_materials.py",
                    "platform/api/crashcap_api/services/analysis_demands.py",
                    "platform/worker/crashcap_worker/resolution_planner.py",
                    "platform/tests/test_resolution_planner.py",
                )
            )
            paths.extend((OUT / "planner" / token).rglob("*.json"))
            paths.extend((OUT / f"{prefix}.xml", OUT / f"{prefix}.log"))
            report["planner_artifacts"] = str(OUT / "planner" / token)
        if args.workspace_builds or args.workspace_policies or args.materials:
            paths.extend(
                ROOT / path
                for path in (
                    "platform/api/crashcap_api/services/workspace_builds.py",
                    "platform/tests/test_workspace_builds.py",
                )
            )
            paths.extend((OUT / f"{prefix}.xml", OUT / f"{prefix}.log"))
        if args.workspace_policies or args.materials:
            paths.extend(
                ROOT / path
                for path in (
                    "platform/api/crashcap_api/services/workspace_policies.py",
                    "platform/migrations/versions/0016_workspace_module_roles.py",
                    "platform/migrations/versions/0017_frozen_analysis_runs.py",
                    "platform/api/crashcap_api/frozen_inputs.py",
                    "platform/api/crashcap_api/services/frozen_runs.py",
                    "platform/api/crashcap_api/config.py",
                    "platform/tests/test_workspace_policies.py",
                    "platform/tests/test_workspace_module_roles_api.py",
                    "platform/tests/test_frozen_run_adoption.py",
                    "platform/api/crashcap_api/services/analysis_recovery.py",
                    "platform/worker/crashcap_worker/automatic_main.py",
                    "platform/api/crashcap_api/task_reconciliation.py",
                    "platform/api/crashcap_api/services/current_decisions.py",
                    "platform/api/crashcap_api/services/current_projection.py",
                    "platform/api/crashcap_api/services/result_reviews.py",
                    "platform/api/crashcap_api/routes_result_reviews.py",
                    "platform/tests/result_review_browser.py",
                    "platform/tests/result_review_native_correction.py",
                    "platform/tests/result_review_native_role.py",
                    "platform/tests/result_review_native_dependency.py",
                    "platform/tests/result_review_role_browser.py",
                    "platform/tests/result_review_native_expiry.py",
                    "platform/tests/result_review_expiry_browser.py",
                    "platform/api/crashcap_api/services/demand_queries.py",
                    "platform/api/crashcap_api/routes_demands.py",
                    "platform/frontend/src/components/AnalysisDemandStatus.tsx",
                    "platform/frontend/src/components/ResultReviewBasisPicker.tsx",
                    "platform/frontend/src/components/ResultReviewForm.tsx",
                    "platform/frontend/src/components/ResultReviews.tsx",
                    "platform/frontend/src/components/AnalysisHistory.tsx",
                    "platform/frontend/src/api/reviewReport.ts",
                    "platform/frontend/src/api/client.ts",
                    "platform/frontend/src/generated/openapi.ts",
                    "contracts/drafts/qa-symbol-import/result-review-request-v1.schema.json",
                    "contracts/drafts/qa-symbol-import/result-review-audit-v1.schema.json",
                    "platform/migrations/versions/0018_current_decisions.py",
                    "platform/migrations/versions/0022_result_reviews.py",
                    "platform/tests/test_current_decisions.py",
                    "platform/tests/test_current_decisions_postgres.py",
                    "platform/api/crashcap_api/routes_v2.py",
                    "platform/api/crashcap_api/app.py",
                    "platform/api/crashcap_api/contracts.py",
                    "platform/api/crashcap_api/task_handoff.py",
                    "platform/api/crashcap_api/queueing.py",
                    "platform/worker/crashcap_worker/tasks.py",
                    "platform/worker/crashcap_worker/processor.py",
                    "contracts/drafts/qa-symbol-import/task-message-v1.2.schema.json",
                )
            )
            paths.extend((OUT / f"{prefix}.xml", OUT / f"{prefix}.log"))
        if args.materials:
            paths.extend(
                ROOT / path
                for path in (
                    "Cargo.lock",
                    "core/Cargo.toml",
                    "core/src/frozen_source.rs",
                    "core/src/frozen_cli.rs",
                    "core/src/analysis_context.rs",
                    "platform/worker/crashcap_worker/source_bundle.py",
                    "platform/api/crashcap_api/services/analysis_demands.py",
                    "platform/api/crashcap_api/services/resolution_planning.py",
                    "platform/worker/crashcap_worker/demand_inspection.py",
                    "platform/worker/crashcap_worker/resolution_planner.py",
                )
            )
        if args.delivery or args.materials:
            paths.extend(
                ROOT / path
                for path in (
                    "platform/tests/test_frozen_delivery_redis.py",
                    "platform/worker/crashcap_worker/tasks.py",
                    "platform/worker/crashcap_worker/broker.py",
                    "platform/worker/crashcap_worker/runtime.py",
                    "platform/worker/crashcap_worker/automatic_analysis.py",
                    "platform/api/crashcap_api/services/frozen_runs.py",
                    "platform/api/crashcap_api/services/analysis_scheduler.py",
                    "platform/tests/test_frozen_run_adoption.py",
                    "platform/api/crashcap_api/config.py",
                    "platform/api/crashcap_api/queueing.py",
                    "platform/api/crashcap_api/task_handoff.py",
                    "platform/api/crashcap_api/services/analysis_recovery.py",
                    "platform/api/crashcap_api/services/analysis_demands.py",
                    "platform/worker/crashcap_worker/outbox_relay.py",
                    "platform/worker/crashcap_worker/processor.py",
                )
            )
            paths.extend((OUT / f"{prefix}.xml", OUT / f"{prefix}.log"))
        if args.reviews or args.late_pair:
            paths.extend(
                ROOT / path
                for path in (
                    "platform/api/crashcap_api/routes_catalog_review.py",
                    "platform/api/crashcap_api/services/symbol_catalog.py",
                    "platform/api/crashcap_api/config.py",
                    "platform/api/crashcap_api/app.py",
                    "platform/api/crashcap_api/routes_v2.py",
                    "platform/tests/test_catalog_review_api.py",
                    "platform/tests/test_catalog_review_postgres.py",
                    "scripts/qa_symbol_import/owned_browser_storage.py",
                )
            )
            paths.extend((OUT / f"{prefix}.xml", OUT / f"{prefix}.log"))
        if args.submissions:
            paths.extend(
                ROOT / path
                for path in (
                    "platform/api/crashcap_api/models.py",
                    "platform/api/crashcap_api/app.py",
                    "platform/api/crashcap_api/routes_submissions.py",
                    "platform/api/crashcap_api/routes.py",
                    "platform/api/crashcap_api/routes_v2.py",
                    "platform/api/crashcap_api/services/occurrence_queries.py",
                    "platform/api/crashcap_api/services/occurrence_submissions.py",
                    "platform/worker/crashcap_worker/processor.py",
                    "platform/migrations/versions/0021_occurrence_submissions.py",
                    "platform/tests/test_occurrence_submissions_postgres.py",
                    "platform/tests/test_upload_analysis_demand.py",
                )
            )
            paths.extend((OUT / f"{prefix}.xml", OUT / f"{prefix}.log"))
        if args.native_source:
            paths.append(ROOT / "fixtures/p0-b01-null-read/generated/manifest.json")
            paths.append(ROOT / "scripts/fixtures/build_p0_b01.ps1")
        if args.cross_module:
            paths.extend(ROOT / "fixtures/qai-c08-cross-module/generated" / name for name in (
                "null_read_target.exe", "null_read_target.pdb", "unknown_fault.dll",
                "unknown_fault.pdb", "null-read.dmp", "manifest.json",
            ))
            paths.extend(ROOT / "scripts/fixtures" / name for name in (
                "build_p0_b01.ps1", "null_read_target.cpp", "unknown_fault.cpp",
            ))
        if args.scenario == "source-failures":
            for fixture_id in ("p0-b01-null-read", "qai-q16-system-wait"):
                paths.extend(ROOT / "fixtures" / fixture_id / "generated" / name for name in (
                    "null_read_target.exe", "null_read_target.pdb", "null-read.dmp",
                    "pe-metadata.json", "manifest.json",
                ))
            paths.extend(ROOT / "scripts/fixtures" / name for name in (
                "build_p0_b01.ps1", "null_read_target.cpp",
            ))
        report["hashes"] = {
            p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths
            if p.is_file()
        }
        receipt.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "receipt": str(receipt),
                "error": report.get("error"),
            }
        )
    )
    raise SystemExit(0 if report["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
