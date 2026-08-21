from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from crashcap_api.models import (
    AnalysisRun,
    Artifact,
    Build,
    DumpBlob,
    GroupMembershipHistory,
    Occurrence,
    OperationLog,
    Upload,
    Workspace,
)
from sqlalchemy import func, select

from .conftest import Phase1Harness, dump_bytes, pdb_bytes, pe_bytes

DEBUG_A = "a" * 32 + "1"
DEBUG_B = "b" * 32 + "1"


def prepared_build(
    harness: Phase1Harness,
    workspace_id: str,
    *,
    version: str = "1.0.0",
    debug_id: str = DEBUG_A,
    include_pe: bool = True,
    include_pdb: bool = True,
) -> dict[str, Any]:
    build = harness.create_build(workspace_id, version)
    harness.put_manifest(build["id"], version=version)
    if include_pe:
        harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(debug_id))
    if include_pdb:
        harness.upload_artifact(build["id"], "pdb", "app.pdb", pdb_bytes(debug_id))
    return harness.client.get(f"/api/v1/builds/{build['id']}").json()


def test_correct_pe_pdb_dump_runs_end_to_end(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("correct-flow")
    build = prepared_build(harness, workspace["id"])

    completed = harness.upload_dump(workspace["id"], dump_bytes(1), reported_build_id=build["id"])
    occurrence_id = completed["occurrence_id"]
    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert detail["blob"]["verification_status"] == "accepted"
    assert detail["current_analysis"]["status"] == "COMPLETE"
    assert detail["current_analysis"]["resolution_method"] == "reported"
    assert detail["latest_attempt"]["id"] == detail["current_analysis"]["id"]

    response = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/analysis")
    assert response.status_code == 200
    canonical = response.json()
    frame = canonical["threads"][0]["frames"][0]
    assert (frame["function"], frame["file"], frame["line"]) == (
        "crashcap::fake_crash",
        "fake.cpp",
        42,
    )
    assert canonical["modules"][0]["status"] == "matched"
    assert canonical["fingerprints"]["exact"]
    assert detail["group"]["occurrence_count"] == 1

    threads = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/threads").json()
    modules = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/modules").json()
    assert threads == canonical["threads"]
    assert modules == canonical["modules"]
    assert harness.client.get(f"/api/v1/occurrences/{occurrence_id}/download").status_code == 403

    with harness.app.state.database.sessions() as session:
        run = session.get(AnalysisRun, detail["current_analysis"]["id"])
        assert run is not None
        assert run.run_spec["blob"]["sha256"] == detail["blob"]["sha256"]
        assert {item["kind"] for item in run.run_spec["artifacts"]} == {"pe", "pdb"}
        assert session.scalar(select(func.count()).select_from(OperationLog)) >= 8
        assert set(session.scalars(select(OperationLog.actor))) == {"anonymous"}


def test_wrong_pdb_is_explicit_and_never_symbolicates(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("wrong-pdb")
    build = harness.create_build(workspace["id"], "1.0.0")
    harness.put_manifest(build["id"])
    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_A))
    bad_pdb = harness.upload_artifact(build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_B))
    assert bad_pdb["verification_status"] == "pdb_mismatch"

    completed = harness.upload_dump(workspace["id"], dump_bytes(2), reported_build_id=build["id"])
    occurrence_id = completed["occurrence_id"]
    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    canonical = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/analysis").json()
    assert detail["current_analysis"]["status"] == "PARTIAL"
    assert canonical["modules"][0]["status"] == "missing_pdb"
    assert canonical["threads"][0]["frames"][0]["function"] is None
    assert canonical["fingerprints"]["exact"] is None
    assert detail["group"] is None


def test_pdb_without_pe_is_partial_and_unclassified(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("pdb-only")
    build = prepared_build(harness, workspace["id"], include_pe=False, include_pdb=True)
    completed = harness.upload_dump(workspace["id"], dump_bytes(3))
    occurrence_id = completed["occurrence_id"]
    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    canonical = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/analysis").json()

    assert detail["current_analysis"]["status"] == "PARTIAL"
    assert detail["current_analysis"]["resolved_build_id"] == build["id"]
    assert canonical["modules"][0]["status"] == "missing_pe"
    assert canonical["threads"][0]["frames"][0]["trust"] == "scan"
    assert canonical["quality"]["unwind_reliability"] < 0.5
    assert canonical["fingerprints"]["exact"] is None
    assert detail["group"] is None


def test_late_symbol_reprocess_preserves_history_and_total(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("late-symbol")
    build = prepared_build(harness, workspace["id"], include_pe=False, include_pdb=True)
    first = harness.upload_dump(workspace["id"], dump_bytes(4))
    occurrence_id = first["occurrence_id"]
    before = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    old_run_id = before["current_analysis"]["id"]

    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_A))
    requested = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": False}
    )
    assert requested.status_code == 202, requested.text
    assert requested.json()["created"] is True
    harness.drain()

    after = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert after["current_analysis"]["id"] != old_run_id
    assert after["current_analysis"]["status"] == "COMPLETE"
    assert after["group"]["occurrence_count"] == 1
    old = harness.client.get(
        f"/api/v1/occurrences/{occurrence_id}/analysis", params={"run_id": old_run_id}
    )
    assert old.status_code == 200
    assert old.json()["modules"][0]["status"] == "missing_pe"

    overview = harness.client.get(f"/api/v1/workspaces/{workspace['id']}/overview").json()
    assert overview["crash_occurrences"] == 1
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Occurrence)) == 1
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 2
        assert session.scalar(select(func.count()).select_from(GroupMembershipHistory)) == 1


def test_dedupe_is_workspace_scoped(harness: Phase1Harness) -> None:
    first_workspace = harness.create_workspace("dedupe-one")
    second_workspace = harness.create_workspace("dedupe-two")
    payload = dump_bytes(5)

    first = harness.upload_dump(first_workspace["id"], payload)
    repeated = harness.upload_dump(first_workspace["id"], payload)
    other = harness.upload_dump(second_workspace["id"], payload)
    assert repeated["duplicate"] is True
    assert first["blob_id"] == repeated["blob_id"]
    assert first["occurrence_id"] == repeated["occurrence_id"]
    assert other["blob_id"] != first["blob_id"]
    assert other["occurrence_id"] != first["occurrence_id"]

    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(DumpBlob)) == 2
        assert session.scalar(select(func.count()).select_from(Occurrence)) == 2


def test_build_resolution_is_ambiguous_without_guessing_version(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("ambiguous-build")
    first = prepared_build(harness, workspace["id"], version="same")
    second = prepared_build(harness, workspace["id"], version="same")
    assert first["id"] != second["id"]

    completed = harness.upload_dump(workspace["id"], dump_bytes(6))
    detail = harness.client.get(f"/api/v1/occurrences/{completed['occurrence_id']}").json()
    canonical = harness.client.get(
        f"/api/v1/occurrences/{completed['occurrence_id']}/analysis"
    ).json()
    assert detail["current_analysis"]["resolution_method"] == "ambiguous"
    assert detail["current_analysis"]["resolved_build_id"] is None
    assert set(canonical["build_resolution"]["evidence"]["candidate_build_ids"]) == {
        first["id"],
        second["id"],
    }


def test_large_or_full_memory_dump_rejected_before_queue(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("large-boundary")
    dispatcher = harness.app.state.dispatcher
    before = len(dispatcher.snapshot())
    too_large = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/dumps/uploads:init",
        json={"filename": "huge.dmp", "size": 256 * 1024 * 1024 + 1},
    )
    assert too_large.status_code == 413
    assert too_large.json()["error"]["code"] == "DUMP_TOO_LARGE"
    full_memory = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/dumps/uploads:init",
        json={
            "filename": "full.dmp",
            "size": 1024,
            "capture_profile": "full-memory",
        },
    )
    assert full_memory.status_code == 422
    assert full_memory.json()["error"]["code"] == "UNSUPPORTED_DUMP"
    assert len(dispatcher.snapshot()) == before
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Upload)) == 0


def test_hang_and_rejected_upload_do_not_inflate_crash_count(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("statistics")
    build = prepared_build(harness, workspace["id"])
    harness.upload_dump(
        workspace["id"],
        dump_bytes(7),
        reported_build_id=build["id"],
        capture_profile="rich-crash",
    )
    harness.upload_dump(
        workspace["id"],
        dump_bytes(8),
        reported_build_id=build["id"],
        capture_profile="hang",
    )

    initialized = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/dumps/uploads:init",
        json={"filename": "bad.dmp", "size": len(b"not-a-minidump!!")},
    ).json()
    harness._seed_upload(initialized["upload_id"], b"not-a-minidump!!")
    harness.client.post(f"/api/v1/uploads/{initialized['upload_id']}/complete", json={})
    harness.drain()

    overview = harness.client.get(f"/api/v1/workspaces/{workspace['id']}/overview").json()
    assert overview["crash_occurrences"] == 1
    assert overview["hang_captures"] == 1
    assert overview["rejected_uploads"] == 1
    assert sum(item["count"] for item in overview["versions"]) == 1


def test_workspace_symbol_namespaces_are_distinct(harness: Phase1Harness) -> None:
    first_workspace = harness.create_workspace("symbols-one")
    second_workspace = harness.create_workspace("symbols-two")
    first = prepared_build(harness, first_workspace["id"], debug_id=DEBUG_A)
    second = prepared_build(harness, second_workspace["id"], debug_id=DEBUG_B)
    assert first["artifacts"][1]["logical_name"] == second["artifacts"][1]["logical_name"]
    assert first["artifacts"][1]["debug_id"] != second["artifacts"][1]["debug_id"]
    with harness.app.state.database.sessions() as session:
        pairs = session.execute(
            select(Artifact.object_key, Build.workspace_id).join(
                Build, Build.id == Artifact.build_id
            )
        ).all()
    assert all(workspace_id in key for key, workspace_id in pairs)
    assert {workspace_id for _, workspace_id in pairs} == {
        first_workspace["id"],
        second_workspace["id"],
    }


def test_duplicate_ingest_delivery_increments_inventory_only_once(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("ingest-delivery-idempotency")
    build = prepared_build(harness, workspace["id"], include_pdb=False)
    artifact_id = build["artifacts"][0]["id"]
    with harness.app.state.database.sessions() as session:
        before = session.get(Workspace, workspace["id"])
        assert before is not None
        inventory_version = before.symbol_inventory_version

    harness.app.state.processor.ingest_artifact(
        {
            "schema_version": "1.0",
            "task_type": "ingest_artifact",
            "artifact_id": artifact_id,
            "attempt_id": "att_duplicate_delivery",
            "queue": "ingest",
        }
    )

    with harness.app.state.database.sessions() as session:
        after = session.get(Workspace, workspace["id"])
        assert after is not None
        assert after.symbol_inventory_version == inventory_version


def test_minidump_header_time_overrides_reported_time_and_manual_time_wins(
    harness: Phase1Harness,
    monkeypatch: Any,
) -> None:
    workspace = harness.create_workspace("dump-time-priority")
    reported = datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
    dumped = datetime(2025, 2, 3, 4, 5, 6, tzinfo=UTC)
    initialized = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/dumps/uploads:init",
        json={
            "filename": "timed.dmp",
            "size": len(dump_bytes(40)),
            "capture_profile": "rich-crash",
            "reported_at": reported.isoformat(),
        },
    ).json()
    harness._seed_upload(initialized["upload_id"], dump_bytes(40))
    completed = harness.client.post(f"/api/v1/uploads/{initialized['upload_id']}/complete", json={})
    assert completed.status_code == 200, completed.text

    original = harness.app.state.processor.core.analyze

    def analyze_with_header_time(task_dir: Any, run_spec: dict[str, Any]) -> Any:
        output = original(task_dir, run_spec)
        output.inspect.setdefault("dump", {})["timestamp"] = dumped.isoformat().replace(
            "+00:00", "Z"
        )
        return output

    monkeypatch.setattr(harness.app.state.processor.core, "analyze", analyze_with_header_time)
    harness.drain()
    terminal = harness.client.get(f"/api/v1/uploads/{initialized['upload_id']}").json()
    occurrence_id = terminal["occurrence_id"]
    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert datetime.fromisoformat(detail["dump_timestamp"]).replace(tzinfo=UTC) == dumped
    assert datetime.fromisoformat(detail["occurred_at"]).replace(tzinfo=UTC) == dumped
    assert detail["time_source"] == "dump"

    manual = datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)
    corrected = harness.client.patch(
        f"/api/v1/occurrences/{occurrence_id}/time",
        json={"occurred_at": manual.isoformat()},
    )
    assert corrected.status_code == 200, corrected.text
    requested = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": True}
    )
    assert requested.status_code == 202, requested.text
    harness.drain()
    final = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert datetime.fromisoformat(final["occurred_at"]).replace(tzinfo=UTC) == manual
    assert final["time_source"] == "manual"
