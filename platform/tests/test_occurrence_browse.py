from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from crashcap_api.models import AnalysisRun, GroupMembership, Occurrence
from crashcap_worker.core_runner import CoreExecutionError
from sqlalchemy import event, func, select

from .conftest import Phase1Harness, dump_bytes, pdb_bytes, pe_bytes

DEBUG_ID = "b" * 32 + "1"


def _fail_core(_task_dir: Any, _run_spec: dict[str, Any]) -> None:
    raise CoreExecutionError("CORE_FAILED", "browse gate forced failure")


def _create_symbolized_build(harness: Phase1Harness, workspace_id: str) -> dict[str, Any]:
    build = harness.create_build(workspace_id, "browse-1.0")
    harness.put_manifest(build["id"], version="browse-1.0")
    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_ID))
    harness.upload_artifact(build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_ID))
    return build


def test_empty_occurrence_collection_and_platform_home_are_legal_states(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("browse-empty")
    response = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences",
        headers={"X-Request-ID": "req_browse_empty"},
    )
    assert response.status_code == 200, response.text
    assert response.headers["X-Request-ID"] == "req_browse_empty"
    assert response.json() == {"items": [], "next_cursor": None}

    overview = harness.client.get("/api/v1/platform/overview")
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert body["workspace_count"] == 1
    assert body["attention"] == {
        "in_progress": 0,
        "latest_attempt_failed": 0,
        "unclassified_crashes": 0,
        "symbol_affected_occurrences": 0,
    }
    assert len(body["workspaces"]) == 1
    assert body["workspaces"][0]["workspace"]["id"] == workspace["id"]
    assert body["workspaces"][0]["occurrence_count"] == 0
    assert body["workspaces"][0]["attention_count"] == 0
    assert body["workspaces"][0]["last_occurrence_at"] is None
    assert body["recent_occurrences"] == []


def test_current_analysis_and_failed_latest_attempt_remain_independent(
    harness: Phase1Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = harness.create_workspace("browse-current-latest")
    completed = harness.upload_dump(workspace["id"], dump_bytes(601))
    occurrence_id = completed["occurrence_id"]
    before = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    current_id = before["current_analysis"]["id"]

    monkeypatch.setattr(harness.app.state.processor.core, "analyze", _fail_core)
    requested = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": True}
    )
    assert requested.status_code == 202, requested.text
    failed_id = requested.json()["id"]
    harness.drain()

    response = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences"
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["id"] == occurrence_id
    assert item["current_analysis"]["id"] == current_id
    assert item["current_analysis"]["status"] in {"COMPLETE", "PARTIAL"}
    assert item["latest_attempt"]["id"] == failed_id
    assert item["latest_attempt"]["status"] == "FAILED"
    assert item["summary"] is not None
    assert item["summary"]["crash_type"] == "crash"
    assert "blob" not in item
    serialized = json.dumps(item).lower()
    for forbidden in ("object_key", "sha256", "presigned", "top_source_file"):
        assert forbidden not in serialized

    filtered = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences",
        params={"latest_status": "FAILED"},
    )
    assert [row["id"] for row in filtered.json()["items"]] == [occurrence_id]

    overview = harness.client.get("/api/v1/platform/overview").json()
    assert overview["attention"]["latest_attempt_failed"] == 1
    assert overview["workspaces"][0]["occurrence_count"] == 1
    assert overview["workspaces"][0]["attention_count"] == 1
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(Occurrence)) == 1
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 2


def test_no_current_occurrence_is_visible_and_workspace_scoped(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("browse-no-current")
    other = harness.create_workspace("browse-no-current-other")
    upload = harness.initialize_dump(workspace["id"], dump_bytes(602))
    assert harness.app.state.dispatcher.drain(limit=1) == 1
    accepted = harness.client.get(f"/api/v1/uploads/{upload['upload_id']}").json()
    occurrence_id = accepted["occurrence_id"]

    page = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences",
        params={"crash_type": "no_current"},
    )
    assert page.status_code == 200, page.text
    assert page.json()["items"] == [
        {
            "id": occurrence_id,
            "workspace_id": workspace["id"],
            "occurred_at": page.json()["items"][0]["occurred_at"],
            "uploaded_at": page.json()["items"][0]["uploaded_at"],
            "time_source": "uploaded",
            "current_analysis": None,
            "latest_attempt": page.json()["items"][0]["latest_attempt"],
            "summary": None,
            "group": None,
        }
    ]
    assert page.json()["items"][0]["latest_attempt"]["status"] == "UPLOADED"
    assert (
        harness.client.get(
            f"/api/v1/workspaces/{other['id']}/occurrences"
        ).json()["items"]
        == []
    )
    assert (
        harness.client.get(
            f"/api/v1/workspaces/{workspace['id']}/occurrences",
            params={"grouping": "no_current"},
        ).json()["items"][0]["id"]
        == occurrence_id
    )


def test_cursor_is_stable_filter_bound_and_literal_search_is_escaped(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("browse-cursor")
    occurrence_ids = [
        harness.upload_dump(workspace["id"], dump_bytes(seed))["occurrence_id"]
        for seed in range(610, 615)
    ]
    base = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    for index, occurrence_id in enumerate(occurrence_ids):
        corrected = harness.client.patch(
            f"/api/v1/occurrences/{occurrence_id}/time",
            json={"occurred_at": (base + timedelta(minutes=index)).isoformat()},
        )
        assert corrected.status_code == 200, corrected.text

    first = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences", params={"limit": 2}
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert len(first_body["items"]) == 2
    assert first_body["next_cursor"]

    inserted = harness.upload_dump(workspace["id"], dump_bytes(615))["occurrence_id"]
    harness.client.patch(
        f"/api/v1/occurrences/{inserted}/time",
        json={"occurred_at": (base + timedelta(hours=1)).isoformat()},
    )
    second = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences",
        params={"limit": 2, "cursor": first_body["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    first_ids = {item["id"] for item in first_body["items"]}
    second_ids = {item["id"] for item in second.json()["items"]}
    assert first_ids.isdisjoint(second_ids)
    assert inserted not in second_ids

    mismatched = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences",
        params={
            "limit": 2,
            "cursor": first_body["next_cursor"],
            "crash_type": "crash",
        },
    )
    assert mismatched.status_code == 422, mismatched.text
    assert mismatched.json()["error"]["code"] == "INVALID_CURSOR"
    assert mismatched.headers["X-Request-ID"]

    tampered_cursor = f"{first_body['next_cursor'][:-1]}!"
    tampered = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences",
        params={"cursor": tampered_cursor},
    )
    assert tampered.status_code == 422, tampered.text
    assert tampered.json()["error"]["code"] == "INVALID_CURSOR"

    literal_percent = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences", params={"q": "%"}
    )
    assert literal_percent.status_code == 200, literal_percent.text
    assert literal_percent.json() == {"items": [], "next_cursor": None}
    overlong = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences",
        params={"q": "x" * 129},
    )
    assert overlong.status_code == 422, overlong.text


def test_group_projection_requires_membership_for_current_analysis(
    harness: Phase1Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = harness.create_workspace("browse-current-membership")
    build = _create_symbolized_build(harness, workspace["id"])
    completed = harness.upload_dump(
        workspace["id"], dump_bytes(620), reported_build_id=build["id"]
    )
    occurrence_id = completed["occurrence_id"]
    original = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert original["group"] is not None

    monkeypatch.setattr(harness.app.state.processor.core, "analyze", _fail_core)
    failed = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": True}
    ).json()
    harness.drain()
    with harness.app.state.database.sessions() as session:
        membership = session.get(GroupMembership, occurrence_id)
        assert membership is not None
        membership.analysis_run_id = failed["id"]
        session.commit()

    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert detail["current_analysis"]["id"] == original["current_analysis"]["id"]
    assert detail["group"] is None
    page = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences"
    ).json()
    assert page["items"][0]["group"] is None
    assert (
        harness.client.get(
            f"/api/v1/workspaces/{workspace['id']}/occurrences",
            params={"grouping": "unclassified"},
        ).json()["items"][0]["id"]
        == occurrence_id
    )


def test_list_query_count_is_constant_and_time_windows_are_bounded(
    harness: Phase1Harness,
) -> None:
    workspace = harness.create_workspace("browse-query-count")
    for seed in range(630, 635):
        harness.upload_dump(workspace["id"], dump_bytes(seed))

    statements: list[str] = []

    def capture_statement(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement)

    engine = harness.app.state.database.engine
    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        response = harness.client.get(
            f"/api/v1/workspaces/{workspace['id']}/occurrences", params={"limit": 50}
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)
    assert response.status_code == 200, response.text
    assert len(response.json()["items"]) == 5
    assert len(statements) == 2

    too_wide_list = harness.client.get(
        f"/api/v1/workspaces/{workspace['id']}/occurrences",
        params={
            "from": "2020-01-01T00:00:00Z",
            "to": "2022-01-02T00:00:00Z",
        },
    )
    assert too_wide_list.status_code == 422
    too_wide_home = harness.client.get(
        "/api/v1/platform/overview",
        params={
            "from": "2026-01-01T00:00:00Z",
            "to": "2026-08-01T00:00:00Z",
        },
    )
    assert too_wide_home.status_code == 422
