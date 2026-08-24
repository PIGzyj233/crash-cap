from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any

import crashcap_api.services.symbol_projection as projection_module
import pytest
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.ids import new_id
from crashcap_api.models import (
    AnalysisRun,
    Build,
    BuildModule,
    DumpBlob,
    MissingSymbol,
    MissingSymbolOccurrence,
    Occurrence,
    OperationLog,
    SymbolProjectionState,
    Workspace,
    utcnow,
)
from crashcap_api.services.analysis_lifecycle import promote_current_analysis
from crashcap_api.services.symbol_projection import (
    SymbolProjectionError,
    compare_workspace_projection,
    current_missing_occurrences,
    missing_symbol_rows,
    projection_invariant_counts,
    symbol_health_rows,
    symbol_identity_key,
    update_symbol_health_for_promotion,
    workspace_projection_snapshot,
)
from sqlalchemy import event, select, update
from sqlalchemy.orm import Session

from .conftest import Phase1Harness, dump_bytes


def _run(occurrence_id: str, status: str = "PARTIAL") -> AnalysisRun:
    run_id = new_id("run")
    return AnalysisRun(
        id=run_id,
        occurrence_id=occurrence_id,
        run_spec={"run_id": run_id},
        resolution_method="unresolved",
        core_version="test",
        core_image_digest="sha256:" + "0" * 64,
        symbolicator_version="test",
        symbol_inventory_version=0,
        idempotency_key=hashlib.sha256(run_id.encode()).hexdigest(),
        status=status,
    )


def _seed_workspace(session: Session, name: str) -> Workspace:
    workspace = Workspace(id=new_id("wsp"), name=name)
    session.add(workspace)
    session.flush()
    return workspace


def _seed_occurrence(
    session: Session, workspace: Workspace, seed: int
) -> tuple[Occurrence, AnalysisRun]:
    timestamp = utcnow() + timedelta(seconds=seed)
    blob = DumpBlob(
        id=new_id("blob"),
        workspace_id=workspace.id,
        sha256=f"{seed:064x}"[-64:],
        size=seed + 1,
        object_key=f"dumps/{workspace.id}/{seed}.dmp",
        verification_status="ACCEPTED",
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
    return occurrence, run


def _module(
    code_file: str,
    debug_file: str | None,
    *,
    code_id: str | None = None,
    debug_id: str | None = None,
    status: str = "missing_pdb",
) -> dict[str, Any]:
    return {
        "code_file": code_file,
        "debug_file": debug_file,
        "code_id": code_id,
        "debug_id": debug_id,
        "status": status,
    }


def _canonical(
    workspace: Workspace,
    occurrence: Occurrence,
    run: AnalysisRun,
    modules: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "workspace_id": workspace.id,
        "occurrence_id": occurrence.id,
        "analysis_id": run.id,
        "modules": modules,
    }


@pytest.fixture
def database(tmp_path: Any) -> Database:
    value = Database(Settings.for_test(tmp_path))
    try:
        yield value
    finally:
        value.dispose()


def test_symbol_identity_splits_double_null_and_merges_normalized_ids() -> None:
    assert symbol_identity_key(
        _module(r"C:\bin\APP.EXE", r"C:\symbols\APP.PDB", code_id="ABC", debug_id="DEF")
    ) == symbol_identity_key(_module("renamed.exe", "renamed.pdb", code_id=" abc ", debug_id="def"))
    assert symbol_identity_key(_module(r"C:\bin\APP.EXE", r"C:\sym\APP.PDB")) == (
        symbol_identity_key(_module("app.exe", "app.pdb"))
    )
    assert symbol_identity_key(_module("app.exe", "app.pdb")) != symbol_identity_key(
        _module("helper.exe", "helper.pdb")
    )
    assert symbol_identity_key(_module("same.dll", "a.pdb", debug_id="A")) != (
        symbol_identity_key(_module("same.dll", "b.pdb", debug_id="B"))
    )


def test_projection_transitions_preserve_ignored_and_ignore_historical_runs(
    database: Database,
) -> None:
    with database.sessions() as session:
        workspace = _seed_workspace(session, "symbol-transitions")
        occurrence, first = _seed_occurrence(session, workspace, 1)
        module_a = _module("a.exe", "a.pdb")
        update_symbol_health_for_promotion(
            session,
            mode="strict-writer",
            occurrence=occurrence,
            run=first,
            canonical=_canonical(workspace, occurrence, first, [module_a]),
        )
        session.commit()

        key_a = symbol_identity_key(module_a)
        session.execute(
            update(MissingSymbol)
            .where(MissingSymbol.workspace_id == workspace.id, MissingSymbol.identity_key == key_a)
            .values(status="ignored")
        )
        second = _run(occurrence.id)
        session.add(second)
        session.flush()
        occurrence.current_run_id = second.id
        module_b = _module("b.exe", "b.pdb", status="missing_pe")
        update_symbol_health_for_promotion(
            session,
            mode="strict-writer",
            occurrence=occurrence,
            run=second,
            canonical=_canonical(workspace, occurrence, second, [module_b]),
        )
        session.commit()

        rows = {
            row.identity_key: row
            for row in session.scalars(
                select(MissingSymbol).where(MissingSymbol.workspace_id == workspace.id)
            )
        }
        assert rows[key_a].affected_occurrence_count == 0
        assert rows[key_a].status == "ignored"
        assert rows[symbol_identity_key(module_b)].affected_occurrence_count == 1

        failed = _run(occurrence.id, "FAILED")
        session.add(failed)
        session.flush()
        rejected = promote_current_analysis(session, occurrence, failed)
        older = promote_current_analysis(session, occurrence, first)
        session.commit()
        assert rejected.reason == "candidate_not_eligible"
        assert older.reason == "older_than_current"
        assert occurrence.current_run_id == second.id
        assert current_missing_occurrences(session, workspace.id, "projection-read") == {
            symbol_identity_key(module_b): {occurrence.id}
        }
        assert projection_invariant_counts(session) == {
            "backfill_remaining": 0,
            "stale_relations": 0,
            "aggregate_count_mismatches": 0,
        }


def test_projection_handles_double_null_merge_and_workspace_isolation(database: Database) -> None:
    with database.sessions() as session:
        first_workspace = _seed_workspace(session, "symbol-identity-first")
        second_workspace = _seed_workspace(session, "symbol-identity-second")
        first_occurrence, first_run = _seed_occurrence(session, first_workspace, 11)
        second_occurrence, second_run = _seed_occurrence(session, first_workspace, 12)
        other_occurrence, other_run = _seed_occurrence(session, second_workspace, 13)
        modules = [
            _module("app.exe", "app.pdb"),
            _module("helper.exe", "helper.pdb"),
            _module("old-name.exe", "old-name.pdb", code_id="CODE", debug_id="DEBUG"),
            _module("new-name.exe", "new-name.pdb", code_id="code", debug_id="debug"),
        ]
        update_symbol_health_for_promotion(
            session,
            mode="strict-writer",
            occurrence=first_occurrence,
            run=first_run,
            canonical=_canonical(first_workspace, first_occurrence, first_run, modules),
        )
        update_symbol_health_for_promotion(
            session,
            mode="strict-writer",
            occurrence=second_occurrence,
            run=second_run,
            canonical=_canonical(first_workspace, second_occurrence, second_run, [modules[2]]),
        )
        update_symbol_health_for_promotion(
            session,
            mode="strict-writer",
            occurrence=other_occurrence,
            run=other_run,
            canonical=_canonical(second_workspace, other_occurrence, other_run, [modules[2]]),
        )
        session.commit()

        first_rows = list(
            session.scalars(
                select(MissingSymbol).where(MissingSymbol.workspace_id == first_workspace.id)
            )
        )
        assert len(first_rows) == 3
        merged = next(row for row in first_rows if row.debug_id is not None)
        assert merged.affected_occurrence_count == 2
        assert current_missing_occurrences(session, second_workspace.id, "projection-read") == {
            symbol_identity_key(modules[2]): {other_occurrence.id}
        }
        assert compare_workspace_projection(session, first_workspace.id).matches is True


def test_shadow_soft_failure_keeps_legacy_and_strict_failure_rolls_back(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    with database.sessions() as session:
        workspace = _seed_workspace(session, "symbol-write-modes")
        occurrence, first = _seed_occurrence(session, workspace, 21)
        module_a = _module("a.exe", "a.pdb")
        update_symbol_health_for_promotion(
            session,
            mode="strict-writer",
            occurrence=occurrence,
            run=first,
            canonical=_canonical(workspace, occurrence, first, [module_a]),
        )
        session.commit()

        original = projection_module.replace_current_symbol_projection

        def fail_projection(*_args: object, **_kwargs: object) -> Any:
            raise SymbolProjectionError("injected projection failure")

        monkeypatch.setattr(projection_module, "replace_current_symbol_projection", fail_projection)
        second = _run(occurrence.id)
        session.add(second)
        session.flush()
        occurrence.current_run_id = second.id
        module_b = _module("b.exe", "b.pdb")
        comparison = update_symbol_health_for_promotion(
            session,
            mode="shadow-soft",
            occurrence=occurrence,
            run=second,
            canonical=_canonical(workspace, occurrence, second, [module_b]),
        )
        session.commit()
        assert comparison is not None and comparison.matches is False
        assert current_missing_occurrences(session, workspace.id, "legacy") == {
            symbol_identity_key(module_b): {occurrence.id}
        }
        state = session.get(SymbolProjectionState, occurrence.id)
        assert state is not None and state.analysis_run_id == first.id

        third = _run(occurrence.id)
        session.add(third)
        session.flush()
        occurrence.current_run_id = third.id
        with pytest.raises(SymbolProjectionError, match="injected"):
            update_symbol_health_for_promotion(
                session,
                mode="strict-writer",
                occurrence=occurrence,
                run=third,
                canonical=_canonical(workspace, occurrence, third, [module_a]),
            )
        session.rollback()
        assert session.get(Occurrence, occurrence.id).current_run_id == second.id
        assert session.get(SymbolProjectionState, occurrence.id).analysis_run_id == first.id
        monkeypatch.setattr(projection_module, "replace_current_symbol_projection", original)


def test_full_shadow_compare_detects_relation_and_external_json_mismatch(
    database: Database,
) -> None:
    with database.sessions() as session:
        workspace = _seed_workspace(session, "symbol-full-shadow")
        build = Build(id=new_id("bld"), workspace_id=workspace.id, version="1.0")
        module = BuildModule(
            id=new_id("mod"),
            build_id=build.id,
            code_file="app.exe",
            debug_file="app.pdb",
            role="entrypoint",
        )
        session.add(build)
        session.flush()
        session.add(module)
        occurrence, run = _seed_occurrence(session, workspace, 31)
        canonical_module = _module("app.exe", "app.pdb")
        update_symbol_health_for_promotion(
            session,
            mode="strict-writer",
            occurrence=occurrence,
            run=run,
            canonical=_canonical(workspace, occurrence, run, [canonical_module]),
        )
        session.commit()
        assert compare_workspace_projection(session, workspace.id).matches is True
        baseline = workspace_projection_snapshot(session, workspace.id, "projection-read")
        assert baseline["identities"][0]["winner_runs"][0]["analysis_run_id"] == run.id

        relation = session.scalar(
            select(MissingSymbolOccurrence).where(
                MissingSymbolOccurrence.occurrence_id == occurrence.id
            )
        )
        assert relation is not None
        session.delete(relation)
        session.flush()
        mismatch = compare_workspace_projection(session, workspace.id)
        assert mismatch.matches is False
        assert {item["section"] for item in mismatch.differences} >= {
            "identities",
            "missing_symbols",
            "symbol_health",
        }


def test_projection_reads_do_not_scan_operation_log_and_query_count_is_constant(
    database: Database,
) -> None:
    with database.sessions() as session:
        small = _seed_workspace(session, "symbol-query-small")
        large = _seed_workspace(session, "symbol-query-large")
        for workspace, count, seed in ((small, 1, 41), (large, 30, 42)):
            build = Build(id=new_id("bld"), workspace_id=workspace.id, version="1.0")
            session.add(build)
            session.flush()
            modules: list[dict[str, Any]] = []
            for index in range(count):
                code_file = f"module-{index}.dll"
                debug_file = f"module-{index}.pdb"
                session.add(
                    BuildModule(
                        id=new_id("mod"),
                        build_id=build.id,
                        code_file=code_file,
                        debug_file=debug_file,
                        role="owned",
                    )
                )
                modules.append(_module(code_file, debug_file))
            occurrence, run = _seed_occurrence(session, workspace, seed)
            update_symbol_health_for_promotion(
                session,
                mode="strict-writer",
                occurrence=occurrence,
                run=run,
                canonical=_canonical(workspace, occurrence, run, modules),
            )
        session.commit()

        statements: list[str] = []

        def record_sql(
            _connection: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            statements.append(statement.lower())

        event.listen(database.engine, "before_cursor_execute", record_sql)
        try:
            statements.clear()
            small_rows = symbol_health_rows(session, small.id, "projection-read")
            small_count = len(statements)
            assert len(small_rows) == 1
            assert not any("operation_logs" in statement for statement in statements)

            statements.clear()
            large_rows = symbol_health_rows(session, large.id, "projection-read")
            large_count = len(statements)
            assert len(large_rows) == 30
            assert not any("operation_logs" in statement for statement in statements)
            assert large_count == small_count

            statements.clear()
            assert len(missing_symbol_rows(session, large.id, "projection-read")) == 30
            assert not any("operation_logs" in statement for statement in statements)
        finally:
            event.remove(database.engine, "before_cursor_execute", record_sql)

        assert session.scalar(select(OperationLog.id).limit(1)) is not None


def test_http_symbol_build_and_batch_paths_cut_over_as_one_snapshot(
    harness: Phase1Harness,
) -> None:
    harness.settings.symbol_projection_mode = "projection-read"
    workspace = harness.create_workspace("symbol-http-cutover")
    build = harness.create_build(workspace["id"])
    build_view = harness.put_manifest(build["id"])
    module_id = build_view["modules"][0]["id"]
    completed = harness.upload_dump(workspace["id"], dump_bytes(731), reported_build_id=build["id"])
    occurrence_id = completed["occurrence_id"]
    assert occurrence_id

    harness.settings.symbol_projection_mode = "legacy"
    legacy_health = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/symbols/health"
    ).json()
    legacy_missing = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/symbols/missing"
    ).json()
    legacy_build = harness.client.get(f"/api/v1/builds/{build['id']}").json()

    statements: list[str] = []

    def record_sql(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement.lower())

    event.listen(harness.app.state.database.engine, "before_cursor_execute", record_sql)
    harness.settings.symbol_projection_mode = "projection-read"
    try:
        projection_health = harness.client.get(
            f"/api/v1/workspaces/{workspace['id']}/symbols/health"
        ).json()
        projection_missing = harness.client.get(
            f"/api/v1/workspaces/{workspace['id']}/symbols/missing"
        ).json()
        projection_build = harness.client.get(f"/api/v1/builds/{build['id']}").json()
        reprocess = harness.client.post(
            f"/api/v1/workspaces/{workspace['id']}/symbols/reprocess",
            json={"module_id": module_id},
        )
    finally:
        event.remove(harness.app.state.database.engine, "before_cursor_execute", record_sql)

    assert projection_health == legacy_health
    assert projection_missing == legacy_missing
    assert projection_build == legacy_build
    assert reprocess.status_code == 202
    assert reprocess.json()["occurrence_ids"] == [occurrence_id]
    assert not any(
        statement.lstrip().startswith("select") and "operation_logs" in statement
        for statement in statements
    )


def test_business_paths_do_not_reference_legacy_replay() -> None:
    repository_root = Path(__file__).resolve().parents[2]
    for relative in (
        "platform/api/crashcap_api/routes.py",
        "platform/worker/crashcap_worker/processor.py",
    ):
        source = (repository_root / relative).read_text(encoding="utf-8")
        assert "active_missing_occurrences" not in source
