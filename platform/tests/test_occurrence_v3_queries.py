import json
from pathlib import Path

from crashcap_api.ids import new_id
from crashcap_api.models import (
    AnalysisRun,
    AnalysisSummary,
    CrashGroup,
    GroupMembership,
    Occurrence,
    OccurrenceVersionAudit,
    utcnow,
)
from sqlalchemy import event, func, select

from .conftest import dump_bytes
from .occurrence_fixtures import seed_report


def test_current_latest_and_unanalyzed_labels_are_independent(harness):
    workspace = harness.create_workspace("query")["id"]
    other = harness.create_workspace("other")["id"]
    first = harness.upload_dump(workspace, dump_bytes(1))["occurrence_id"]
    pending = harness.upload_dump(workspace, dump_bytes(2))["occurrence_id"]
    current = seed_report(harness, first)
    failed = seed_report(harness, first, current=False, status="FAILED")
    for occurrence in (first, pending):
        assert (
            harness.client.patch(
                f"/api/v3/occurrences/{occurrence}/version", json={"version": "v1"}
            ).status_code
            == 200
        )
    result = harness.client.get(
        f"/api/v3/workspaces/{workspace}/occurrences", params={"version": "v1"}
    )
    assert result.status_code == 200, result.text
    items = {i["id"]: i for i in result.json()["items"]}
    assert items[first]["current_analysis"]["id"] == current
    assert items[first]["latest_attempt"]["id"] == failed
    assert items[pending]["version"] == "v1" and items[pending]["current_analysis"] is None
    assert harness.client.get(f"/api/v3/workspaces/{other}/occurrences").json()["items"] == []
    assert (
        harness.client.get(
            f"/api/v3/workspaces/{workspace}/occurrences", params={"crash_type": "no_current"}
        ).json()["items"][0]["id"]
        == pending
    )


def test_version_edit_updates_group_and_overview_without_analysis(harness):
    workspace = harness.create_workspace("versions")["id"]
    ids = [harness.upload_dump(workspace, dump_bytes(i))["occurrence_id"] for i in (3, 4)]
    runs = [seed_report(harness, occ) for occ in ids]
    group_id = new_id("grp")
    with harness.app.state.database.sessions.begin() as session:
        # Exercise the actual Canonical 2.0 frame shape, including provenance.
        canonical = json.loads(
            (
                Path(__file__).resolve().parents[2] / "contracts/fixtures/canonical-v2.json"
            ).read_text(encoding="utf-8")
        )
        frames = next(t["frames"] for t in canonical["threads"] if t["frames"])
        session.get(AnalysisSummary, runs[0]).crashing_frames = frames
        session.add(
            CrashGroup(
                id=group_id,
                workspace_id=workspace,
                fingerprint="f" * 64,
                title="fixture group",
                first_seen=utcnow(),
                last_seen=utcnow(),
                occurrence_count=2,
                representative_run_id=runs[0],
            )
        )
        session.flush()
        for occ, run in zip(ids, runs, strict=True):
            session.add(
                GroupMembership(
                    occurrence_id=occ,
                    group_id=group_id,
                    analysis_run_id=run,
                    similarity=1.0,
                    grouping_evidence_json={},
                )
            )
    harness.client.patch(f"/api/v3/occurrences/{ids[0]}/version", json={"version": "hotfix"})
    group = harness.client.get(f"/api/v3/groups/{group_id}").json()
    assert group["representative_stack"] == frames
    assert {i["version"]: i["count"] for i in group["version_distribution"]} == {
        None: 1,
        "hotfix": 1,
    }
    overview = harness.client.get(f"/api/v3/workspaces/{workspace}/overview").json()
    assert {i["version"]: i["count"] for i in overview["versions"]} == {None: 1, "hotfix": 1}
    with harness.app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(AnalysisRun)) == 2
        assert session.scalar(select(func.count()).select_from(OccurrenceVersionAudit)) == 1
        assert session.get(Occurrence, ids[0]).current_run_id == runs[0]
        assert not hasattr(session.get(AnalysisSummary, runs[0]), "version")


def test_cursor_scopes_filters_and_query_count_remain_bounded(harness):
    workspace = harness.create_workspace("pagination")["id"]
    for i in range(5):
        harness.upload_dump(workspace, dump_bytes(100 + i))
    path = f"/api/v3/workspaces/{workspace}/occurrences"
    first = harness.client.get(path, params={"limit": 2}).json()
    inserted = harness.upload_dump(workspace, dump_bytes(999))["occurrence_id"]
    second = harness.client.get(path, params={"limit": 2, "cursor": first["next_cursor"]})
    assert second.status_code == 200, second.text
    assert {i["id"] for i in first["items"]}.isdisjoint(i["id"] for i in second.json()["items"])
    assert inserted not in {i["id"] for i in second.json()["items"]}
    assert (
        harness.client.get(
            path, params={"cursor": first["next_cursor"], "version": "changed"}
        ).status_code
        == 422
    )
    assert harness.client.get(path, params={"q": "%"}).json()["items"] == []
    assert (
        harness.client.get(
            path, params={"from": "2020-01-01T00:00:00Z", "to": "2022-01-02T00:00:00Z"}
        ).status_code
        == 422
    )
    statements = []

    def capture(_c, _cursor, statement, _parameters, _context, _many):
        if statement.lstrip().lower().startswith("select"):
            statements.append(statement)

    engine = harness.app.state.database.engine
    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = harness.client.get(path, params={"limit": 50})
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(result.json()["items"]) == 6 and len(statements) == 2
