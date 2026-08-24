from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from typing import Any

import pytest
from alembic import command
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.ids import new_id
from crashcap_api.migrate import migration_config
from crashcap_api.models import (
    AnalysisRun,
    Build,
    BuildModule,
    DumpBlob,
    MissingSymbol,
    MissingSymbolOccurrence,
    Occurrence,
    SymbolProjectionGap,
    Workspace,
    utcnow,
)
from crashcap_api.services.symbol_backfill import backfill_symbol_projection
from crashcap_api.services.symbol_projection import (
    compare_workspace_projection,
    update_symbol_health_for_promotion,
)
from crashcap_api.storage import LocalObjectStore
from sqlalchemy import select, text


def _postgres_database(tmp_path: Path) -> Database:
    url = os.environ.get("CRASH_CAP_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set CRASH_CAP_TEST_DATABASE_URL for PostgreSQL Symbol projection testing")
    command.upgrade(migration_config(database_url=url), "head")
    return Database(Settings.for_test(tmp_path, database_url=url))


def _run(occurrence_id: str, *, context: dict[str, Any] | None = None) -> AnalysisRun:
    run_id = new_id("run")
    return AnalysisRun(
        id=run_id,
        occurrence_id=occurrence_id,
        run_spec={},
        resolution_method="unresolved",
        core_version="test",
        core_image_digest="sha256:" + "0" * 64,
        symbolicator_version="test",
        symbol_inventory_version=0,
        idempotency_key=hashlib.sha256(run_id.encode()).hexdigest(),
        status="PARTIAL",
        analysis_context=context,
    )


def _occurrence(
    session: Any, workspace: Workspace, seed: int
) -> tuple[Occurrence, AnalysisRun, DumpBlob]:
    timestamp = utcnow()
    blob = DumpBlob(
        id=new_id("blob"),
        workspace_id=workspace.id,
        sha256=f"{seed:064x}"[-64:],
        size=seed,
        object_key=f"dumps/{workspace.id}/{seed}.dmp",
        verification_status="ACCEPTED",
        uploaded_at=timestamp,
    )
    occurrence = Occurrence(
        id=new_id("occ"),
        workspace_id=workspace.id,
        dump_blob_id=blob.id,
        uploaded_at=timestamp,
        occurred_at=timestamp,
        time_source="uploaded",
    )
    session.add(blob)
    session.flush()
    session.add(occurrence)
    session.flush()
    run = _run(occurrence.id)
    session.add(run)
    session.flush()
    occurrence.current_run_id = run.id
    session.flush()
    return occurrence, run, blob


def _projection_canonical(workspace_id: str, occurrence_id: str, run_id: str) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "occurrence_id": occurrence_id,
        "analysis_id": run_id,
        "modules": [
            {
                "code_file": "app.exe",
                "debug_file": "app.pdb",
                "code_id": "CODE-1",
                "debug_id": "DEBUG-1",
                "status": "missing_pdb",
            }
        ],
    }


@pytest.mark.integration
def test_postgres_concurrent_projection_external_parity_and_explain(tmp_path: Path) -> None:
    database = _postgres_database(tmp_path)
    try:
        with database.sessions() as session:
            workspace = Workspace(id=new_id("wsp"), name=f"symbol-pg-{new_id('run')}")
            session.add(workspace)
            session.flush()
            build = Build(id=new_id("bld"), workspace_id=workspace.id, version="1.0")
            session.add(build)
            session.flush()
            session.add(
                BuildModule(
                    id=new_id("mod"),
                    build_id=build.id,
                    code_file="app.exe",
                    debug_file="app.pdb",
                    role="entrypoint",
                    code_id="CODE-1",
                    debug_id="DEBUG-1",
                )
            )
            first, first_run, _ = _occurrence(session, workspace, 801)
            second, second_run, _ = _occurrence(session, workspace, 802)
            workspace_id = workspace.id
            pairs = ((first.id, first_run.id), (second.id, second_run.id))
            session.commit()

        barrier = Barrier(2)

        def project(pair: tuple[str, str]) -> None:
            occurrence_id, run_id = pair
            with database.sessions() as session:
                occurrence = session.scalar(
                    select(Occurrence).where(Occurrence.id == occurrence_id).with_for_update()
                )
                run = session.get(AnalysisRun, run_id)
                assert occurrence is not None and run is not None
                barrier.wait(timeout=10)
                update_symbol_health_for_promotion(
                    session,
                    mode="strict-writer",
                    occurrence=occurrence,
                    run=run,
                    canonical=_projection_canonical(workspace_id, occurrence.id, run.id),
                )
                session.commit()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(project, pair) for pair in pairs]
            for future in futures:
                future.result(timeout=30)

        with database.sessions() as session:
            row = session.scalar(
                select(MissingSymbol).where(MissingSymbol.workspace_id == workspace_id)
            )
            assert row is not None
            assert row.affected_occurrence_count == 2
            relations = list(
                session.scalars(
                    select(MissingSymbolOccurrence).where(
                        MissingSymbolOccurrence.workspace_id == workspace_id
                    )
                )
            )
            assert {relation.occurrence_id for relation in relations} == {
                first.id,
                second.id,
            }
            assert compare_workspace_projection(session, workspace_id).matches is True

            session.execute(text("SET LOCAL enable_seqscan = off"))
            plan = session.scalar(
                text(
                    "EXPLAIN (FORMAT JSON) "
                    "SELECT occurrence_id FROM missing_symbol_occurrences "
                    "WHERE workspace_id = :workspace_id AND missing_symbol_id = :symbol_id"
                ),
                {"workspace_id": workspace_id, "symbol_id": row.id},
            )
            rendered_plan = json.dumps(plan, sort_keys=True)
            assert "ix_missing_symbol_occurrences_workspace_symbol_occurrence" in rendered_plan
    finally:
        database.dispose()


class _BlockingStore:
    def __init__(self, delegate: LocalObjectStore, started: Event, release: Event) -> None:
        self.delegate = delegate
        self.started = started
        self.release = release

    def stream(self, key: str, chunk_size: int = 1024 * 1024) -> Any:
        payload = list(self.delegate.stream(key, chunk_size))
        self.started.set()
        assert self.release.wait(timeout=20)
        yield from payload

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)


@pytest.mark.integration
def test_postgres_backfill_rechecks_pointer_after_object_read(tmp_path: Path) -> None:
    database = _postgres_database(tmp_path)
    store = LocalObjectStore(tmp_path / "pg-symbol-objects")
    started = Event()
    release = Event()
    blocking_store = _BlockingStore(store, started, release)
    try:
        with database.sessions() as session:
            workspace = Workspace(id=new_id("wsp"), name=f"symbol-pg-race-{new_id('run')}")
            session.add(workspace)
            session.flush()
            occurrence, old_run, blob = _occurrence(session, workspace, 811)
            context = _analysis_context(workspace.id, occurrence, old_run, blob)
            canonical = _full_canonical(workspace.id, occurrence, old_run, blob)
            old_run.analysis_context = context
            old_run.result_object_key = f"analysis/{workspace.id}/{occurrence.id}/{old_run.id}.json"
            store.put_bytes(
                old_run.result_object_key,
                json.dumps(canonical, separators=(",", ":")).encode(),
                "application/json",
            )
            occurrence_id = occurrence.id
            old_run_id = old_run.id
            session.commit()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                backfill_symbol_projection,
                database.sessions,
                blocking_store,
                Settings.for_test(tmp_path).schema_root,
                apply=True,
                after=None,
                limit=10_000,
            )
            assert started.wait(timeout=20)
            with database.sessions() as session:
                occurrence = session.scalar(
                    select(Occurrence).where(Occurrence.id == occurrence_id).with_for_update()
                )
                assert occurrence is not None
                newer = _run(occurrence.id)
                session.add(newer)
                session.flush()
                occurrence.current_run_id = newer.id
                session.commit()
            release.set()
            report = future.result(timeout=30)

        matching_case = next(
            case for case in report["cases"] if case["current_run_id"] == old_run_id
        )
        assert matching_case["outcome"] == "gap"
        assert matching_case["gap_reason"] == "pointer_changed"
        with database.sessions() as session:
            gap = session.get(SymbolProjectionGap, occurrence_id)
            assert gap is not None and gap.reason == "pointer_changed"
    finally:
        release.set()
        database.dispose()


def _analysis_context(
    workspace_id: str, occurrence: Occurrence, run: AnalysisRun, blob: DumpBlob
) -> dict[str, Any]:
    uploaded_at = occurrence.uploaded_at.isoformat()
    occurred_at = occurrence.occurred_at.isoformat()
    return {
        "schema_version": "analysis-context-v1",
        "identity": {
            "workspace_id": workspace_id,
            "occurrence_id": occurrence.id,
            "analysis_id": run.id,
        },
        "dump": {
            "blob_id": blob.id,
            "sha256": blob.sha256,
            "kind": "user_minidump",
            "size": blob.size,
            "dump_timestamp": None,
            "reported_at": None,
            "uploaded_at": uploaded_at,
            "occurred_at": occurred_at,
            "time_source": "uploaded",
        },
        "engine": {
            "core_image_digest": run.core_image_digest,
            "symbolicator_version": run.symbolicator_version,
            "grouping_version": run.grouping_version,
            "normalization_version": run.normalization_version,
        },
        "policy": {
            "symbol_inventory_version": 0,
            "in_app_rule_version": 0,
            "source_bundle_policy_version": "source-bundle-v1.0",
        },
        "inspect": {"object_key": "inspect.json", "sha256": "0" * 64},
        "inputs": {"artifact_ids": [], "build_ids": [], "source_bundles": []},
    }


def _full_canonical(
    workspace_id: str, occurrence: Occurrence, run: AnalysisRun, blob: DumpBlob
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "workspace_id": workspace_id,
        "occurrence_id": occurrence.id,
        "analysis_id": run.id,
        "engine": {
            "core_version": run.core_version,
            "core_image_digest": run.core_image_digest,
            "symbolicator_version": run.symbolicator_version,
            "grouping_version": run.grouping_version,
            "normalization_version": run.normalization_version,
        },
        "build_resolution": {
            "reported_build_id": None,
            "resolved_build_id": None,
            "resolution_method": "unresolved",
            "evidence": {
                "candidate_build_ids": [],
                "matched_entrypoints": [],
                "matched_owned_modules": [],
                "conflicting_modules": [],
            },
        },
        "dump": {
            "blob_id": blob.id,
            "sha256": blob.sha256,
            "kind": "user_minidump",
            "size": blob.size,
            "dump_timestamp": None,
            "reported_at": None,
            "uploaded_at": occurrence.uploaded_at.isoformat(),
            "occurred_at": occurrence.occurred_at.isoformat(),
            "time_source": "uploaded",
        },
        "process": {"pid": None, "architecture": "x86_64", "os": "windows"},
        "crash": {"type": "unknown", "type_evidence": "insufficient"},
        "threads": [],
        "modules": [
            {
                "code_file": "app.exe",
                "code_id": None,
                "debug_file": "app.pdb",
                "debug_id": None,
                "role": "entrypoint",
                "in_app": True,
                "artifact_ids": [],
                "status": "missing_pdb",
            }
        ],
        "quality": {
            "score": 0.5,
            "symbol_coverage": 0.0,
            "unwind_reliability": 0.5,
            "artifact_completeness": 0.0,
            "warnings": [],
        },
        "fingerprints": {"exact": None, "family": None, "algorithm": "exact-v1.0"},
    }
