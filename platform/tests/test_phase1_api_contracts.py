"""Phase 1 API gate contracts.

This module deliberately stays at the HTTP boundary (with read-only database
inspection for audit/projection assertions).  It is an independent gate for
the P1-B/P1-D/P1-E contracts in ``docs/design.md`` and the implementation
roadmap; it must not make the API more permissive to get a green test run.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from crashcap_api.models import (
    AnalysisRun,
    GroupMembership,
    GroupMembershipHistory,
    Occurrence,
    OperationLog,
)
from crashcap_worker.core_runner import CoreExecutionError, CoreOutput
from sqlalchemy import func, select

from .conftest import Phase1Harness, dump_bytes, pdb_bytes, pe_bytes

DEBUG_ID = "a" * 32 + "1"


def _manifest(*, role: str = "entrypoint") -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "product": "Phase 1 API gate",
        "version": "1.0.0",
        "architecture": "x86_64",
        "modules": [
            {"code_file": "app.exe", "debug_file": "app.pdb", "role": role},
        ],
    }


def _complete_dump(
    harness: Phase1Harness,
    workspace_id: str,
    payload: bytes,
    *,
    reported_at: datetime | None = None,
    reported_build_id: str | None = None,
    capture_profile: str | None = "rich-crash",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "filename": "crash.dmp",
        "size": len(payload),
    }
    if capture_profile is not None:
        body["capture_profile"] = capture_profile
    if reported_at is not None:
        body["reported_at"] = reported_at.isoformat()
    if reported_build_id is not None:
        body["reported_build_id"] = reported_build_id

    initialized = harness.client.post(
        f"/api/v1/workspaces/{workspace_id}/dumps/uploads:init", json=body
    )
    assert initialized.status_code == 201, initialized.text
    upload = initialized.json()
    harness._seed_upload(upload["upload_id"], payload)
    completed = harness.client.post(f"/api/v1/uploads/{upload['upload_id']}/complete", json={})
    assert completed.status_code == 200, completed.text
    harness.drain()
    terminal = harness.client.get(f"/api/v1/uploads/{upload['upload_id']}")
    assert terminal.status_code == 200, terminal.text
    assert terminal.json()["verification_status"] == "ACCEPTED"
    return terminal.json()


def _prepared_build(
    harness: Phase1Harness,
    workspace_id: str,
    *,
    version: str = "1.0.0",
    include_pe: bool = True,
    include_pdb: bool = True,
) -> dict[str, Any]:
    build = harness.create_build(workspace_id, version)
    manifest = _manifest()
    manifest["version"] = version
    response = harness.client.put(f"/api/v1/builds/{build['id']}/manifest", json=manifest)
    assert response.status_code == 200, response.text
    if include_pe:
        harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_ID))
    if include_pdb:
        harness.upload_artifact(build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_ID))
    return harness.client.get(f"/api/v1/builds/{build['id']}").json()


def test_build_version_is_display_only_and_build_queries_are_workspace_scoped(
    harness: Phase1Harness,
) -> None:
    first_workspace = harness.create_workspace("api-gate-builds-one")
    second_workspace = harness.create_workspace("api-gate-builds-two")

    first = harness.create_build(first_workspace["id"], "same-version")
    second = harness.create_build(first_workspace["id"], "same-version")
    other = harness.create_build(second_workspace["id"], "same-version")

    assert first["id"] != second["id"]
    same_workspace = harness.client.get(
        f"/api/v1/workspaces/{first_workspace['id']}/builds",
        params={"version": "same-version"},
    )
    assert same_workspace.status_code == 200, same_workspace.text
    assert {item["id"] for item in same_workspace.json()} == {first["id"], second["id"]}

    other_workspace = harness.client.get(
        f"/api/v1/workspaces/{second_workspace['id']}/builds",
        params={"version": "same-version"},
    )
    assert other_workspace.status_code == 200, other_workspace.text
    assert [item["id"] for item in other_workspace.json()] == [other["id"]]


def test_manifest_rejects_invalid_roles_missing_entrypoint_and_cross_workspace_builds(
    harness: Phase1Harness,
) -> None:
    first_workspace = harness.create_workspace("api-gate-manifest-one")
    second_workspace = harness.create_workspace("api-gate-manifest-two")
    first_build = harness.create_build(first_workspace["id"])
    second_build = harness.create_build(second_workspace["id"])

    invalid_role = harness.client.put(
        f"/api/v1/builds/{first_build['id']}/manifest",
        json=_manifest(role="not-a-role"),
    )
    assert invalid_role.status_code == 422, invalid_role.text
    assert invalid_role.json()["error"]["code"] == "VALIDATION"

    missing_entrypoint = harness.client.put(
        f"/api/v1/builds/{first_build['id']}/manifest",
        json=_manifest(role="owned"),
    )
    assert missing_entrypoint.status_code == 422, missing_entrypoint.text
    assert missing_entrypoint.json()["error"]["code"] == "VALIDATION"

    # A Build from another Workspace cannot be used as the reported Build for
    # a dump, nor as the build filter of a Workspace-scoped symbols operation.
    cross_report = harness.client.post(
        f"/api/v1/workspaces/{first_workspace['id']}/dumps/uploads:init",
        json={
            "filename": "cross-workspace.dmp",
            "size": len(dump_bytes(20)),
            "reported_build_id": second_build["id"],
        },
    )
    assert cross_report.status_code == 422, cross_report.text
    assert cross_report.json()["error"]["code"] == "VALIDATION"

    cross_reindex = harness.client.post(
        f"/api/v1/workspaces/{first_workspace['id']}/symbols/reindex",
        json={"build_id": second_build["id"]},
    )
    assert cross_reindex.status_code == 422, cross_reindex.text
    assert cross_reindex.json()["error"]["code"] == "VALIDATION"

    valid_manifest = harness.client.put(
        f"/api/v1/builds/{first_build['id']}/manifest", json=_manifest()
    )
    assert valid_manifest.status_code == 200, valid_manifest.text
    assert harness.client.get(f"/api/v1/builds/{second_build['id']}").json()["modules"] == []


def test_symbols_reindex_is_idempotent_for_one_inventory_snapshot(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("api-gate-reindex-idempotency")
    build = harness.create_build(workspace["id"])
    first = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/symbols/reindex",
        json={"build_id": build["id"]},
    )
    replay = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/symbols/reindex",
        json={"build_id": build["id"]},
    )
    assert first.status_code == 202, first.text
    assert replay.status_code == 202, replay.text
    assert first.json()["created"] is True
    assert replay.json()["created"] is False
    assert replay.json()["attempt_id"] == first.json()["attempt_id"]
    assert len(harness.app.state.dispatcher.snapshot()) == 1

    harness.drain()
    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_ID))
    changed = harness.client.post(
        f"/api/v1/workspaces/{workspace['id']}/symbols/reindex",
        json={"build_id": build["id"]},
    )
    assert changed.status_code == 202, changed.text
    assert changed.json()["created"] is True
    assert changed.json()["attempt_id"] != first.json()["attempt_id"]


def test_occurrence_time_source_precedence_and_manual_correction_audit(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("api-gate-time")
    reported_at = datetime(2025, 1, 2, 3, 4, 5, 678901, tzinfo=UTC)
    completed = _complete_dump(
        harness,
        workspace["id"],
        dump_bytes(21),
        reported_at=reported_at,
    )
    occurrence_id = completed["occurrence_id"]
    reported = harness.client.get(f"/api/v1/occurrences/{occurrence_id}")
    assert reported.status_code == 200, reported.text
    reported_view = reported.json()
    assert reported_view["time_source"] == "reported"
    reported_value = datetime.fromisoformat(reported_view["occurred_at"])
    assert reported_value.replace(tzinfo=UTC) == reported_at

    manual_at = datetime(2025, 2, 3, 4, 5, 6, 789012, tzinfo=UTC)
    corrected = harness.client.patch(
        f"/api/v1/occurrences/{occurrence_id}/time",
        headers={"X-Request-ID": "api-gate-manual-time"},
        json={"occurred_at": manual_at.isoformat()},
    )
    assert corrected.status_code == 200, corrected.text
    corrected_view = corrected.json()
    assert corrected_view["time_source"] == "manual"
    manual_value = datetime.fromisoformat(corrected_view["occurred_at"])
    assert manual_value.replace(tzinfo=UTC) == manual_at

    uploaded_fallback = _complete_dump(harness, workspace["id"], dump_bytes(22))
    fallback_view = harness.client.get(
        f"/api/v1/occurrences/{uploaded_fallback['occurrence_id']}"
    ).json()
    assert fallback_view["time_source"] == "uploaded"
    assert fallback_view["occurred_at"] == fallback_view["uploaded_at"]

    with harness.app.state.database.sessions() as session:
        audit = session.scalar(
            select(OperationLog)
            .where(
                OperationLog.action == "occurrence.time.correct",
                OperationLog.target_id == occurrence_id,
            )
            .order_by(OperationLog.id.desc())
        )
        assert audit is not None
        assert audit.actor == "anonymous"
        assert audit.request_id == "api-gate-manual-time"
        assert audit.details == {
            "previous": reported_view["occurred_at"],
            "current": corrected_view["occurred_at"],
        }


def test_analysis_reprocess_is_idempotent_unless_forced(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("api-gate-idempotency")
    completed = _complete_dump(harness, workspace["id"], dump_bytes(23))
    occurrence_id = completed["occurrence_id"]
    initial = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    initial_run_id = initial["current_analysis"]["id"]

    replay = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": False}
    )
    replay_again = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": False}
    )
    assert replay.status_code == 202, replay.text
    assert replay_again.status_code == 202, replay_again.text
    assert replay.json()["created"] is False
    assert replay_again.json()["created"] is False
    assert replay.json()["id"] == replay_again.json()["id"] == initial_run_id

    forced = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": True}
    )
    forced_again = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": True}
    )
    assert forced.status_code == 202, forced.text
    assert forced_again.status_code == 202, forced_again.text
    assert forced.json()["created"] is True
    assert forced_again.json()["created"] is True
    assert forced.json()["id"] != forced_again.json()["id"]
    assert forced.json()["id"] != initial_run_id
    harness.drain()

    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Occurrence)) == 1
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 3


def test_current_analysis_never_switches_to_failed_timeout_or_oom(
    harness: Phase1Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = harness.create_workspace("api-gate-current-status")
    completed = _complete_dump(harness, workspace["id"], dump_bytes(24))
    occurrence_id = completed["occurrence_id"]
    initial_run_id = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()[
        "current_analysis"
    ]["id"]

    failures = [("CORE_FAILED", "FAILED"), ("TIMEOUT", "TIMEOUT"), ("OOM", "OOM")]
    failed_run_ids: list[str] = []
    for error_code, expected_status in failures:

        def fail(_task_dir: Any, _run_spec: dict[str, Any], code: str = error_code) -> None:
            raise CoreExecutionError(code, f"gate fixture: {code}")

        monkeypatch.setattr(harness.app.state.processor.core, "analyze", fail)
        requested = harness.client.post(
            f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": True}
        )
        assert requested.status_code == 202, requested.text
        assert requested.json()["created"] is True
        failed_run_ids.append(requested.json()["id"])
        harness.drain()

        run_view = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
        assert run_view["current_analysis"]["id"] == initial_run_id
        with harness.app.state.database.sessions() as session:
            failed = session.get(AnalysisRun, requested.json()["id"])
            assert failed is not None
            assert failed.status == expected_status

    assert len(set(failed_run_ids)) == len(failures)


def test_group_patch_is_non_destructive_and_merge_split_are_phase3(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("api-gate-groups")
    build = _prepared_build(harness, workspace["id"])
    completed = _complete_dump(
        harness,
        workspace["id"],
        dump_bytes(25),
        reported_build_id=build["id"],
    )
    occurrence_id = completed["occurrence_id"]
    before = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert before["group"] is not None
    group_id = before["group"]["id"]
    group_before = harness.client.get(f"/api/v1/groups/{group_id}").json()

    patched = harness.client.patch(
        f"/api/v1/groups/{group_id}",
        json={
            "status": "investigating",
            "owner": "qa-gate",
            "title": "Reviewed exact crash",
            "issue_url": "https://tracker.example.invalid/issues/25",
        },
    )
    assert patched.status_code == 200, patched.text
    group_after = patched.json()
    assert group_after["id"] == group_before["id"]
    assert group_after["fingerprint"] == group_before["fingerprint"]
    assert group_after["occurrence_count"] == group_before["occurrence_count"] == 1
    assert group_after["occurrence_ids"] == group_before["occurrence_ids"] == [occurrence_id]
    assert group_after["status"] == "investigating"
    assert group_after["owner"] == "qa-gate"

    for operation in ("merge", "split"):
        response = harness.client.post(f"/api/v1/groups/{group_id}/{operation}", json={})
        assert response.status_code == 501, response.text
        assert response.json()["error"]["code"] == "NOT_IMPLEMENTED"

    with harness.app.state.database.sessions() as session:
        membership = session.get(GroupMembership, occurrence_id)
        assert membership is not None
        assert membership.group_id == group_id
        patch_log = session.scalar(
            select(OperationLog)
            .where(
                OperationLog.action == "group.patch",
                OperationLog.target_id == group_id,
            )
            .order_by(OperationLog.id.desc())
        )
        assert patch_log is not None
        assert patch_log.details == {"fields": ["issue_url", "owner", "status", "title"]}


def test_unclassified_occurrence_never_creates_a_pseudo_group(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("api-gate-unclassified")
    build = _prepared_build(harness, workspace["id"], include_pe=False, include_pdb=True)
    completed = _complete_dump(
        harness,
        workspace["id"],
        dump_bytes(26),
        reported_build_id=build["id"],
    )
    occurrence_id = completed["occurrence_id"]
    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert detail["current_analysis"]["status"] == "PARTIAL"
    assert detail["group"] is None

    groups = harness.client.get(f"/api/v1/workspaces/{workspace['id']}/groups")
    assert groups.status_code == 200, groups.text
    assert groups.json() == []
    overview = harness.client.get(f"/api/v1/workspaces/{workspace['id']}/overview").json()
    assert overview["crash_occurrences"] == 1
    assert overview["unclassified"] == 1
    assert overview["exact_groups"] == 0


def test_statistics_join_current_only_and_reprocess_preserves_occurrence_total(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("api-gate-current-statistics")
    build = _prepared_build(harness, workspace["id"], include_pe=False, include_pdb=True)
    first = _complete_dump(harness, workspace["id"], dump_bytes(27))
    occurrence_id = first["occurrence_id"]
    before = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    old_run_id = before["current_analysis"]["id"]
    assert before["current_analysis"]["status"] == "PARTIAL"

    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_ID))
    reprocessed = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": False}
    )
    assert reprocessed.status_code == 202, reprocessed.text
    assert reprocessed.json()["created"] is True
    harness.drain()

    after = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert after["current_analysis"]["id"] != old_run_id
    assert after["current_analysis"]["status"] == "COMPLETE"
    old_result = harness.client.get(
        f"/api/v1/occurrences/{occurrence_id}/analysis", params={"run_id": old_run_id}
    )
    assert old_result.status_code == 200, old_result.text
    assert old_result.json()["modules"][0]["status"] == "missing_pe"

    overview = harness.client.get(f"/api/v1/workspaces/{workspace['id']}/overview").json()
    assert overview["crash_occurrences"] == 1
    assert sum(item["count"] for item in overview["versions"]) == 1
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Occurrence)) == 1
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 2


def test_overview_groups_and_failure_rate_use_window_current_projection(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("api-gate-window-projection")
    build = _prepared_build(harness, workspace["id"])
    old = _complete_dump(
        harness,
        workspace["id"],
        dump_bytes(28),
        reported_build_id=build["id"],
    )
    recent = _complete_dump(
        harness,
        workspace["id"],
        dump_bytes(29),
        reported_build_id=build["id"],
    )

    old_at = datetime(2020, 1, 1, tzinfo=UTC)
    corrected = harness.client.patch(
        f"/api/v1/occurrences/{old['occurrence_id']}/time",
        json={"occurred_at": old_at.isoformat()},
    )
    assert corrected.status_code == 200, corrected.text

    overview = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/overview",
        params={
            "from": "2024-01-01T00:00:00Z",
            "to": "2030-01-01T00:00:00Z",
        },
    )
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["crash_occurrences"] == 1
    assert body["exact_groups"] == 1
    assert body["top_groups"][0]["occurrence_count"] == 1
    assert body["unclassified"] == 0
    assert sum(item["count"] for item in body["versions"]) == 1
    assert body["failure_rate"] == 0.0

    # A historical run for the same occurrence must not affect the denominator
    # after a current run is selected.
    with harness.app.state.database.sessions() as session:
        current = session.get(Occurrence, recent["occurrence_id"])
        assert current is not None
        current_run = session.get(AnalysisRun, current.current_run_id)
        assert current_run is not None
        current_run.status = "FAILED"
        session.commit()
    current_only = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/overview",
        params={
            "from": "2024-01-01T00:00:00Z",
            "to": "2030-01-01T00:00:00Z",
        },
    ).json()
    assert current_only["failure_rate"] == 1.0


def test_symbol_health_handles_null_safe_module_identity(harness: Phase1Harness) -> None:
    workspace = harness.create_workspace("api-gate-symbol-null-safe")
    build = harness.create_build(workspace["id"])
    harness.put_manifest(build["id"])
    completed = _complete_dump(harness, workspace["id"], dump_bytes(30))
    occurrence_id = completed["occurrence_id"]

    health = harness.client.get(f"/api/v1/workspaces/{workspace['id']}/symbols/health")
    assert health.status_code == 200, health.text
    row = next(item for item in health.json() if item["code_file"] == "app.exe")
    assert row["code_id"] is None
    assert row["debug_id"] is None
    assert row["status"] == "missing"
    assert row["affected_occurrence_count"] == 1
    assert row["occurrence_ids"] == [occurrence_id]


def test_overview_preserves_unknown_and_aggregates_build_versions(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("api-gate-version-aggregation")
    first = _prepared_build(harness, workspace["id"], version="same-version")
    second = _prepared_build(harness, workspace["id"], version="same-version")
    _complete_dump(harness, workspace["id"], dump_bytes(32), reported_build_id=first["id"])
    _complete_dump(harness, workspace["id"], dump_bytes(33), reported_build_id=second["id"])
    ambiguous = _complete_dump(harness, workspace["id"], dump_bytes(34))
    ambiguous_detail = harness.client.get(
        f"/api/v1/occurrences/{ambiguous['occurrence_id']}"
    ).json()
    assert ambiguous_detail["current_analysis"]["resolution_method"] == "ambiguous"

    overview = harness.client.get(f"/api/v1/workspaces/{workspace['id']}/overview").json()
    assert overview["versions"] == [
        {"version": None, "count": 1},
        {"version": "same-version", "count": 2},
    ]


def test_reprocess_moves_and_unclassifies_membership_projection(
    harness: Phase1Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = harness.create_workspace("api-gate-membership-projection")
    build = _prepared_build(harness, workspace["id"])
    completed = _complete_dump(
        harness,
        workspace["id"],
        dump_bytes(31),
        reported_build_id=build["id"],
    )
    occurrence_id = completed["occurrence_id"]
    before = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    old_group_id = before["group"]["id"]
    original_core = harness.app.state.processor.core
    original_analyze = original_core.analyze

    def changed_fingerprint(task_dir: Any, run_spec: dict[str, Any]) -> CoreOutput:
        output = original_analyze(task_dir, run_spec)
        canonical = json.loads(json.dumps(output.canonical))
        canonical["fingerprints"]["exact"] = "f" * 64
        return CoreOutput(inspect=output.inspect, canonical=canonical, raw=output.raw)

    monkeypatch.setattr(original_core, "analyze", changed_fingerprint)
    moved = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": True}
    )
    assert moved.status_code == 202, moved.text
    harness.drain()
    moved_view = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    moved_group_id = moved_view["group"]["id"]
    assert moved_group_id != old_group_id

    def unclassified(task_dir: Any, run_spec: dict[str, Any]) -> CoreOutput:
        output = original_analyze(task_dir, run_spec)
        canonical = json.loads(json.dumps(output.canonical))
        canonical["fingerprints"]["exact"] = None
        return CoreOutput(inspect=output.inspect, canonical=canonical, raw=output.raw)

    monkeypatch.setattr(original_core, "analyze", unclassified)
    removed = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": True}
    )
    assert removed.status_code == 202, removed.text
    harness.drain()
    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert detail["group"] is None

    groups = harness.client.get(f"/api/v1/workspaces/{workspace['id']}/groups").json()
    assert len(groups) == 2
    assert {group["occurrence_count"] for group in groups} == {0}
    overview = harness.client.get(f"/api/v1/workspaces/{workspace['id']}/overview").json()
    assert overview["exact_groups"] == 0
    assert overview["unclassified"] == 1

    with harness.app.state.database.sessions() as session:
        history = session.scalars(
            select(GroupMembershipHistory)
            .where(GroupMembershipHistory.occurrence_id == occurrence_id)
            .order_by(GroupMembershipHistory.id)
        ).all()
        assert [row.action for row in history] == ["assign", "move", "unclassify"]
        assert session.scalar(select(func.count()).select_from(GroupMembership)) == 0
