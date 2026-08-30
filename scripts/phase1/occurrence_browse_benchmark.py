#!/usr/bin/env python3
"""Benchmark the P0X occurrence browse paths on a disposable PostgreSQL database.

The runner fails closed unless the generated database name starts with
``crashcap_p0x_perf_``. It never prints the database URL or credentials and
removes the generated database after collecting the report.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.orm import Session

DATABASE_NAME = re.compile(r"^crashcap_p0x_perf_[a-z0-9_]+$")
WORKSPACE_ID = "wsp_perf_001"
OCCURRENCE_COUNT = 100_000
WORKSPACE_COUNT = 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-name",
        default=f"crashcap_p0x_perf_{datetime.now(UTC):%Y%m%d_%H%M%S}",
    )
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--port", type=int, default=18080)
    return parser.parse_args()


def percentile(values: list[float], value: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * value / 100
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def database_url(base_url: str, database_name: str) -> str:
    parsed = make_url(base_url)
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError("the occurrence browse benchmark requires PostgreSQL")
    return parsed.set(database=database_name).render_as_string(hide_password=False)


def admin_engine(base_url: str) -> Engine:
    return create_engine(database_url(base_url, "postgres"), isolation_level="AUTOCOMMIT")


def create_database(engine: Engine, database_name: str) -> None:
    with engine.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": database_name},
        ).scalar_one_or_none()
        if exists:
            raise RuntimeError("refusing to reuse an existing benchmark database")
        connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')


def drop_database(engine: Engine, database_name: str) -> None:
    with engine.connect() as connection:
        connection.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": database_name},
        )
        connection.exec_driver_sql(f'DROP DATABASE IF EXISTS "{database_name}"')


def migrate(target_url: str) -> None:
    environment = os.environ.copy()
    environment["CRASHCAP_DATABASE_URL"] = target_url
    executable = shutil.which("crashcap-migrate")
    if executable is None:
        raise RuntimeError("crashcap-migrate is not available")
    subprocess.run(  # noqa: S603 - executable resolved from the trusted image PATH
        [executable],
        env=environment,
        check=True,
        stdout=subprocess.DEVNULL,
    )


def seed(engine: Engine) -> None:
    statements = [
        """
        INSERT INTO workspaces (
          id, name, display_name, platform, default_architecture, retention_days,
          symbol_inventory_version, in_app_rules, in_app_rule_version, created_at
        )
        SELECT
          'wsp_perf_' || lpad(g::text, 3, '0'),
          'perf-' || lpad(g::text, 3, '0'),
          'Performance ' || lpad(g::text, 3, '0'),
          'windows', 'x86_64', 180, 1,
          '{"include_modules":[],"exclude_modules":[]}'::jsonb, 0,
          clock_timestamp()
        FROM generate_series(1, 100) AS g
        """,
        """
        INSERT INTO dump_blobs (
          id, workspace_id, sha256, size, object_key, dump_kind, architecture,
          verification_status, uploaded_at
        )
        SELECT
          'blob_perf_' || lpad(g::text, 6, '0'), :workspace_id,
          repeat(md5(g::text), 2), 196608,
          'perf/dumps/' || lpad(g::text, 6, '0') || '.dmp',
          'user_minidump', 'x86_64', 'ACCEPTED',
          clock_timestamp() - (g * interval '1 second')
        FROM generate_series(1, 100000) AS g
        """,
        """
        INSERT INTO occurrences (
          id, workspace_id, dump_blob_id, current_run_id, dump_timestamp,
          uploaded_at, occurred_at, time_source, created_at
        )
        SELECT
          'occ_perf_' || lpad(g::text, 6, '0'), :workspace_id,
          'blob_perf_' || lpad(g::text, 6, '0'), NULL,
          clock_timestamp() - (g * interval '1 second'),
          clock_timestamp() - (g * interval '1 second'),
          clock_timestamp() - (g * interval '1 second'), 'dump',
          clock_timestamp() - (g * interval '1 second')
        FROM generate_series(1, 100000) AS g
        """,
        """
        INSERT INTO analysis_runs (
          id, occurrence_id, run_spec, resolution_method, resolution_evidence,
          core_version, core_image_digest, symbolicator_version, schema_version,
          grouping_version, normalization_version, symbol_inventory_version,
          idempotency_key, status, quality_score, assembly_mode, started_at, finished_at
        )
        SELECT
          'run_perf_a_' || lpad(g::text, 6, '0'),
          'occ_perf_' || lpad(g::text, 6, '0'), '{}'::jsonb,
          CASE WHEN g % 4 = 0 THEN 'auto_unique' ELSE 'unresolved' END,
          '{}'::jsonb, 'perf-core', 'sha256:' || repeat('0', 64),
          'perf-symbolicator', '1.0', 'group-v1.0', 'norm-v1.0', 1,
          repeat(md5('current-' || g::text), 2), 'PARTIAL', 0.85,
          'legacy', clock_timestamp() - interval '30 seconds', clock_timestamp()
        FROM generate_series(1, 100000) AS g
        WHERE g % 10 <> 0
        """,
        """
        INSERT INTO analysis_runs (
          id, occurrence_id, run_spec, resolution_method, resolution_evidence,
          core_version, core_image_digest, symbolicator_version, schema_version,
          grouping_version, normalization_version, symbol_inventory_version,
          idempotency_key, status, quality_score, assembly_mode, started_at
        )
        SELECT
          'run_perf_z_' || lpad(g::text, 6, '0'),
          'occ_perf_' || lpad(g::text, 6, '0'), '{}'::jsonb, 'unresolved',
          '{}'::jsonb, 'perf-core', 'sha256:' || repeat('0', 64),
          'perf-symbolicator', '1.0', 'group-v1.0', 'norm-v1.0', 1,
          repeat(md5('pending-' || g::text), 2), 'ANALYZING', NULL,
          'legacy', clock_timestamp() - interval '5 seconds'
        FROM generate_series(1, 100000) AS g
        WHERE g % 10 = 0
        """,
        """
        INSERT INTO analysis_runs (
          id, occurrence_id, run_spec, resolution_method, resolution_evidence,
          core_version, core_image_digest, symbolicator_version, schema_version,
          grouping_version, normalization_version, symbol_inventory_version,
          idempotency_key, status, quality_score, assembly_mode, started_at,
          finished_at, error_code, error_detail
        )
        SELECT
          'run_perf_z_' || lpad(g::text, 6, '0'),
          'occ_perf_' || lpad(g::text, 6, '0'), '{}'::jsonb, 'unresolved',
          '{}'::jsonb, 'perf-core', 'sha256:' || repeat('0', 64),
          'perf-symbolicator', '1.0', 'group-v1.0', 'norm-v1.0', 1,
          repeat(md5('failed-' || g::text), 2), 'FAILED', NULL,
          'legacy', clock_timestamp() - interval '5 seconds', clock_timestamp(),
          'PERF_FAILURE', 'generated benchmark retry failure'
        FROM generate_series(1, 100000) AS g
        WHERE g % 20 = 1
        """,
        """
        UPDATE occurrences
        SET current_run_id = 'run_perf_a_' || right(id, 6)
        WHERE right(id, 6)::integer % 10 <> 0
        """,
        """
        INSERT INTO analysis_summaries (
          analysis_run_id, occurrence_id, version, exception_code,
          exception_name, access_type, crash_address, crashing_thread_id,
          fault_module, top_function, top_source_file, top_source_line,
          symbol_coverage, unwind_reliability, artifact_completeness,
          exact_fingerprint, family_fingerprint, crashing_frames, crash_type
        )
        SELECT
          'run_perf_a_' || lpad(g::text, 6, '0'),
          'occ_perf_' || lpad(g::text, 6, '0'), '10.0.' || (g % 20)::text,
          '0xc0000005', 'EXCEPTION_ACCESS_VIOLATION', 'read', '0x1', 7,
          'game.exe', 'CrashFunction' || (g % 100)::text, 'game.cpp', 42,
          0.9, 0.8, 0.7,
          CASE WHEN g % 10 = 2 THEN 'exact-' || (g % 5)::text ELSE NULL END,
          'family-' || (g % 20)::text, '[]'::jsonb,
          CASE WHEN g % 13 = 0 THEN 'hang' ELSE 'crash' END
        FROM generate_series(1, 100000) AS g
        WHERE g % 10 <> 0
        """,
        """
        INSERT INTO crash_groups (
          id, workspace_id, group_type, fingerprint, title, status, first_seen,
          last_seen, occurrence_count
        ) VALUES (
          'grp_perf_001', :workspace_id, 'exact', 'perf-exact-001',
          'Generated exact group', 'open', clock_timestamp() - interval '2 days',
          clock_timestamp(), 10000
        )
        """,
        """
        INSERT INTO group_memberships (
          occurrence_id, group_id, analysis_run_id, similarity,
          grouping_evidence_json, assigned_at
        )
        SELECT
          'occ_perf_' || lpad(g::text, 6, '0'), 'grp_perf_001',
          'run_perf_a_' || lpad(g::text, 6, '0'), 1.0,
          '{"kind":"generated"}'::jsonb, clock_timestamp()
        FROM generate_series(1, 100000) AS g
        WHERE g % 10 = 2
        """,
        "ANALYZE workspaces",
        "ANALYZE dump_blobs",
        "ANALYZE occurrences",
        "ANALYZE analysis_runs",
        "ANALYZE analysis_summaries",
        "ANALYZE crash_groups",
        "ANALYZE group_memberships",
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement), {"workspace_id": WORKSPACE_ID})


def server_environment(target_url: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "CRASHCAP_DATABASE_URL": target_url,
            "CRASHCAP_ENVIRONMENT": "test",
            "CRASHCAP_CREATE_SCHEMA": "false",
            "CRASHCAP_QUEUE_MODE": "memory",
            "CRASHCAP_TASK_HANDOFF_MODE": "legacy",
            "CRASHCAP_TASK_RECEIPT_MODE": "compat",
            "CRASHCAP_OBJECT_STORE_BACKEND": "local",
            "CRASHCAP_OBJECT_STORE_LOCAL_ROOT": os.path.join(
                tempfile.gettempdir(), "crashcap-p0x-perf-objects"
            ),
        }
    )
    return environment


def wait_for_server(base_url: str, process: subprocess.Popen[bytes]) -> None:
    for _attempt in range(100):
        if process.poll() is not None:
            raise RuntimeError("benchmark API failed to start")
        try:
            with urlopen(f"{base_url}/healthz", timeout=1) as response:  # noqa: S310
                if response.status == 200:
                    return
        except URLError:
            time.sleep(0.1)
    raise RuntimeError("benchmark API did not become healthy")


def request(base_url: str, path: str) -> tuple[float, int, int]:
    started = time.perf_counter()
    with urlopen(f"{base_url}{path}", timeout=30) as response:  # noqa: S310
        payload = response.read()
        status = response.status
    return (time.perf_counter() - started) * 1000, len(payload), status


def measure_http(base_url: str, path: str, samples: int) -> dict[str, Any]:
    for _attempt in range(5):
        request(base_url, path)
    timings: list[float] = []
    sizes: list[int] = []
    statuses: set[int] = set()
    for _attempt in range(samples):
        elapsed, size, status = request(base_url, path)
        timings.append(elapsed)
        sizes.append(size)
        statuses.add(status)
    return {
        "samples": samples,
        "p50_ms": round(percentile(timings, 50), 2),
        "p95_ms": round(percentile(timings, 95), 2),
        "p99_ms": round(percentile(timings, 99), 2),
        "max_bytes": max(sizes),
        "statuses": sorted(statuses),
    }


def capture_queries(engine: Engine, operation: Callable[[Session], None]) -> list[tuple[str, Any]]:
    captured: list[tuple[str, Any]] = []

    def before_cursor_execute(
        _connection: Connection,
        _cursor: object,
        statement: str,
        parameters: Any,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            captured.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        with Session(engine) as session:
            operation(session)
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return captured


def explain(engine: Engine, statement: str, parameters: Any) -> dict[str, Any]:
    with engine.connect() as connection:
        payload = connection.exec_driver_sql(
            f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {statement}", parameters
        ).scalar_one()
    if isinstance(payload, str):
        payload = json.loads(payload)
    document = payload[0]
    plan = document["Plan"]
    return {
        "node": plan["Node Type"],
        "planning_ms": round(float(document["Planning Time"]), 3),
        "execution_ms": round(float(document["Execution Time"]), 3),
        "actual_rows": int(plan["Actual Rows"]),
        "shared_hit_blocks": int(plan.get("Shared Hit Blocks", 0)),
        "shared_read_blocks": int(plan.get("Shared Read Blocks", 0)),
        "temp_read_blocks": int(plan.get("Temp Read Blocks", 0)),
        "temp_written_blocks": int(plan.get("Temp Written Blocks", 0)),
    }


def query_evidence(engine: Engine) -> dict[str, Any]:
    from crashcap_api.models import Workspace
    from crashcap_api.services.occurrence_queries import (
        OccurrenceFilters,
        aggregate_occurrences,
        list_occurrence_projections,
    )

    counts: dict[str, int] = {}
    default_queries: list[tuple[str, Any]] = []
    for limit in (1, 50, 200):
        captured = capture_queries(
            engine,
            lambda session, selected_limit=limit: list_occurrence_projections(
                session,
                OccurrenceFilters(workspace_id=WORKSPACE_ID),
                limit=selected_limit,
            ),
        )
        counts[f"inbox_limit_{limit}"] = len(captured)
        if limit == 50:
            default_queries = captured

    now = datetime.now(UTC)

    def platform_operation(session: Session) -> None:
        session.scalars(select(Workspace).order_by(Workspace.created_at, Workspace.id)).all()
        aggregate_occurrences(
            session,
            window_start=now - timedelta(days=7),
            window_end=now,
        )
        list_occurrence_projections(
            session,
            OccurrenceFilters(from_=now - timedelta(days=7), to=now),
            limit=10,
        )

    platform_queries = capture_queries(engine, platform_operation)
    counts["platform_overview"] = len(platform_queries)
    return {
        "counts": counts,
        "explain": {
            "inbox_default": explain(engine, *default_queries[0]),
            "platform_workspace_list": explain(engine, *platform_queries[0]),
            "platform_aggregate": explain(engine, *platform_queries[1]),
            "platform_recent": explain(engine, *platform_queries[2]),
        },
    }


def status_for(measurement: dict[str, Any], *, p95_ms: float, max_bytes: int) -> str:
    return (
        "PASS"
        if measurement["statuses"] == [200]
        and measurement["p95_ms"] <= p95_ms
        and measurement["max_bytes"] <= max_bytes
        else "FAIL"
    )


def main() -> int:
    args = parse_args()
    if not DATABASE_NAME.fullmatch(args.database_name):
        raise RuntimeError("benchmark database name must match crashcap_p0x_perf_[a-z0-9_]+")
    if args.samples < 20:
        raise RuntimeError("at least 20 samples are required for a p95 gate")
    base_database_url = os.environ.get("CRASHCAP_DATABASE_URL")
    if not base_database_url:
        raise RuntimeError("CRASHCAP_DATABASE_URL is required")

    admin = admin_engine(base_database_url)
    target_url = database_url(base_database_url, args.database_name)
    target: Engine | None = None
    server: subprocess.Popen[bytes] | None = None
    created = False
    try:
        create_database(admin, args.database_name)
        created = True
        migrate(target_url)
        target = create_engine(target_url, pool_pre_ping=True)
        seed(target)

        environment = server_environment(target_url)
        server = subprocess.Popen(  # noqa: S603 - fixed interpreter and module
            [
                sys.executable,
                "-m",
                "uvicorn",
                "crashcap_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
                "--log-level",
                "warning",
                "--no-access-log",
            ],
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        base_url = f"http://127.0.0.1:{args.port}"
        wait_for_server(base_url, server)
        paths = {
            "inbox_default": f"/api/v1/workspaces/{WORKSPACE_ID}/occurrences?limit=50",
            "inbox_enum_filter": (
                f"/api/v1/workspaces/{WORKSPACE_ID}/occurrences?limit=50&latest_status=FAILED"
            ),
            "inbox_text_search": (
                f"/api/v1/workspaces/{WORKSPACE_ID}/occurrences?limit=50&q=Exception"
            ),
            "platform_overview": "/api/v1/platform/overview",
        }
        measurements = {
            name: measure_http(base_url, path, args.samples) for name, path in paths.items()
        }
        measurements["inbox_default"]["status"] = status_for(
            measurements["inbox_default"], p95_ms=300, max_bytes=256 * 1024
        )
        measurements["inbox_enum_filter"]["status"] = status_for(
            measurements["inbox_enum_filter"], p95_ms=400, max_bytes=256 * 1024
        )
        measurements["inbox_text_search"]["status"] = status_for(
            measurements["inbox_text_search"], p95_ms=1000, max_bytes=256 * 1024
        )
        measurements["platform_overview"]["status"] = status_for(
            measurements["platform_overview"], p95_ms=500, max_bytes=256 * 1024
        )
        query_details = query_evidence(target)
        fixed_queries = query_details["counts"] == {
            "inbox_limit_1": 1,
            "inbox_limit_50": 1,
            "inbox_limit_200": 1,
            "platform_overview": 3,
        }
        with target.connect() as connection:
            server_version = connection.execute(text("SHOW server_version")).scalar_one()
        result = {
            "schema_version": "frontend-p0x-postgres-performance-v1",
            "executed_at": datetime.now(UTC).isoformat(),
            "environment": "local Compose PostgreSQL; target-like preflight only",
            "target_intranet_status": "NOT_PROVEN",
            "postgres_version": server_version,
            "dataset": {
                "workspaces": WORKSPACE_COUNT,
                "occurrences": OCCURRENCE_COUNT,
                "workspace_with_100k": WORKSPACE_ID,
                "mix": (
                    "90k Current PARTIAL; 10k no Current + ANALYZING latest; "
                    "5k failed retry; 10k exact group"
                ),
            },
            "measurements": measurements,
            "query_evidence": query_details,
            "fixed_query_count_status": "PASS" if fixed_queries else "FAIL",
        }
        result["local_target_like_status"] = (
            "PASS"
            if fixed_queries
            and all(item["status"] == "PASS" for item in measurements.values())
            else "FAIL"
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["local_target_like_status"] == "PASS" else 1
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        if target is not None:
            target.dispose()
        if created:
            drop_database(admin, args.database_name)
        admin.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
