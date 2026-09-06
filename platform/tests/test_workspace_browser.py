"""Workspace navigation queries; fixture metadata is not native analysis evidence."""

from dataclasses import replace

from crashcap_api.models import (
    AnalysisDemand,
    ArtifactEntry,
    MissingSymbol,
    MissingSymbolOccurrence,
    Occurrence,
    utcnow,
)
from crashcap_api.services.artifact_catalog import refresh_availability
from crashcap_api.services.symbol_projection import symbol_row_id
from sqlalchemy import select

from .catalog_fixtures import admit_pair, origin, pair_evidence
from .conftest import dump_bytes
from .occurrence_fixtures import seed_report


def issue(harness, workspace, reports, *, code="123456789", debug="2" * 32 + "1"):
    identity = symbol_row_id(workspace, f"{code}:{debug}")
    with harness.app.state.database.sessions.begin() as session:
        session.add(
            MissingSymbol(
                id=identity,
                workspace_id=workspace,
                identity_key=identity,
                code_file="fixture.exe",
                debug_file="fixture.pdb",
                code_id=code,
                debug_id=debug,
                first_seen=utcnow(),
                last_seen=utcnow(),
            )
        )
        session.flush()
        for occurrence, run, reason in reports:
            session.add(
                MissingSymbolOccurrence(
                    missing_symbol_id=identity,
                    workspace_id=workspace,
                    occurrence_id=occurrence,
                    analysis_run_id=run,
                    reason=reason,
                    code_file="fixture.exe",
                    debug_file="fixture.pdb",
                    observed_at=utcnow(),
                )
            )
    return identity


def test_attention_cards_match_drilldowns_and_null_duration(harness):
    workspace = harness.create_workspace("attention")["id"]
    empty = harness.client.get(f"/api/v3/workspaces/{workspace}/overview").json()
    assert empty["average_analysis_duration_ms"] is None
    assert empty["total_occurrences"] == 0
    occ = harness.upload_dump(workspace, dump_bytes(20))["occurrence_id"]
    current = seed_report(harness, occ)
    failed = seed_report(harness, occ, current=False, status="FAILED")
    with harness.app.state.database.sessions.begin() as session:
        session.scalar(
            select(AnalysisDemand).where(AnalysisDemand.occurrence_id == occ)
        ).state = "needs_review"
    issue(harness, workspace, [(occ, current, "missing_pdb")])
    issue(harness, workspace, [(occ, current, "pdb_mismatch")], debug="3" * 32 + "1")
    overview = harness.client.get(f"/api/v3/workspaces/{workspace}/overview").json()
    assert overview["attention"]["latest_attempt_failed"] == 1
    assert overview["attention"]["symbol_affected_occurrences"] == 1
    for view in ("latest_attempt_failed", "symbol_affected", "unclassified"):
        page = harness.client.get(
            f"/api/v3/workspaces/{workspace}/occurrences",
            params={
                "attention": view,
                "from": overview["window_start"],
                "to": overview["window_end"],
            },
        ).json()
        assert [row["id"] for row in page["items"]] == [occ]
        assert page["items"][0]["current_analysis"]["id"] == current
        assert page["items"][0]["latest_attempt"]["id"] == failed
        assert page["items"][0]["analysis_update_state"] == "needs_review"
    assert (
        len(
            harness.client.get(
                f"/api/v3/workspaces/{workspace}/occurrences",
                params={
                    "version_unset": True,
                },
            ).json()["items"]
        )
        == 1
    )
    harness.client.patch(f"/api/v3/occurrences/{occ}/version", json={"version": "1.2"})
    assert (
        harness.client.get(
            f"/api/v3/workspaces/{workspace}/occurrences",
            params={
                "version_unset": True,
            },
        ).json()["items"]
        == []
    )


def test_issues_report_actual_reasons_and_scope_pagination(harness):
    workspace = harness.create_workspace("issues")["id"]
    other = harness.create_workspace("other")["id"]
    occ = harness.upload_dump(workspace, dump_bytes(21))["occurrence_id"]
    run = seed_report(harness, occ)
    first = issue(harness, workspace, [(occ, run, "pdb_mismatch")])
    second = issue(harness, workspace, [(occ, run, "missing_pe")], debug="4" * 32 + "1")
    base = f"/api/v3/workspaces/{workspace}/symbol-issues"
    page = harness.client.get(base, params={"limit": 1}).json()
    assert page["total"] == 2 and page["affected_occurrence_count"] == 1
    next_page = harness.client.get(base, params={"cursor": page["next_cursor"]}).json()
    assert {page["items"][0]["id"], next_page["items"][0]["id"]} == {first, second}
    assert (
        harness.client.get(base, params={"cursor": page["next_cursor"], "q": "changed"}).status_code
        == 422
    )
    detail = harness.client.get(f"{base}/{first}").json()
    assert detail["issue"]["reasons"] == {"pdb_mismatch": 1}
    assert (
        harness.client.get(f"/api/v3/workspaces/{other}/symbol-issues/{first}").status_code == 404
    )
    assert (
        harness.client.get(
            f"/api/v3/workspaces/{other}/occurrences",
            params={
                "symbol_issue_id": first,
            },
        ).status_code
        == 404
    )
    assert (
        harness.client.get(
            f"/api/v3/workspaces/{workspace}/occurrences",
            params={
                "symbol_issue_id": first,
            },
        ).json()["items"][0]["id"]
        == occ
    )
    # A stale historical relation cannot keep an issue active.
    newer = seed_report(harness, occ, current=False)
    with harness.app.state.database.sessions.begin() as session:
        session.get(Occurrence, occ).current_run_id = newer
    assert harness.client.get(base).json()["items"] == []
    assert harness.client.get(f"{base}/{first}").json()["issue"]["affected_occurrence_count"] == 0
    result = harness.client.post(
        f"/api/v3/workspaces/{workspace}/symbols/reprocess",
        json={
            "symbol_issue_id": first,
        },
    )
    assert result.status_code == 202 and result.json()["affected_occurrence_count"] == 0


def test_consumer_files_pair_public_and_local_without_exposing_other_spaces(harness):
    workspace = harness.create_workspace("files")["id"]
    other = harness.create_workspace("other-files")["id"]
    with harness.app.state.database.sessions.begin() as session:
        pair = admit_pair(session, *pair_evidence(), origin())
        pe = session.scalar(select(ArtifactEntry).where(ArtifactEntry.file_id == pair.pe_file_id))
        pdb = session.scalar(select(ArtifactEntry).where(ArtifactEntry.file_id == pair.pdb_file_id))
        pdb.workspace_id = workspace
        pe_id, pdb_id = pe.id, pdb.id
        session.flush()
        refresh_availability(session, pair.debug_id)
        # Other-space content with the same identity must not cause a conflict here.
        admit_pair(
            session,
            *pair_evidence("c" * 64, "d" * 64),
            replace(
                origin("other"),
                source_workspace_id=other,
            ),
        )
    path = f"/api/v3/workspaces/{workspace}/artifacts"
    result = harness.client.get(path)
    assert result.status_code == 200, result.text
    assert {row["id"] for row in result.json()["items"]} == {pe_id, pdb_id}
    assert {row["availability"] for row in result.json()["items"]} == {"symbols_available"}
    public = harness.client.get("/api/v3/public/artifacts").json()["items"]
    assert len(public) == 1 and public[0]["availability"] == "waiting_for_pair"
    detail = harness.client.get(f"{path}/{pe_id}").json()
    assert detail["pairs"][0]["pdb"][0]["id"] == pdb_id
    assert harness.client.get(f"/api/v3/public/artifacts/{pdb_id}").status_code == 404
    assert harness.client.get(f"/api/v3/workspaces/{other}/artifacts/{pdb_id}").status_code == 404
    filtered = harness.client.get(
        path, params={"availability": "symbols_available", "limit": 1}
    ).json()
    assert filtered["next_cursor"]
    assert (
        harness.client.get(
            path, params={"availability": "symbols_available", "cursor": filtered["next_cursor"]}
        ).json()["items"][0]["id"]
        != filtered["items"][0]["id"]
    )
    assert harness.client.get(path, params={"origin": "public"}).json()["items"][0]["id"] == pe_id


def test_ready_pdb_for_another_code_identity_does_not_claim_issue_is_ready(harness):
    workspace = harness.create_workspace("exact-readiness")["id"]
    with harness.app.state.database.sessions.begin() as session:
        admit_pair(session, *pair_evidence(), replace(origin(), source_workspace_id=workspace))
    occ = harness.upload_dump(workspace, dump_bytes(22))["occurrence_id"]
    run = seed_report(harness, occ)
    identity = issue(harness, workspace, [(occ, run, "missing_pe")], code="other-code")
    response = harness.client.get(f"/api/v3/workspaces/{workspace}/symbol-issues/{identity}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["availability"] == "waiting_for_pair"
    assert body["files"]["items"][0]["availability"] == "symbols_available"
    assert body["issue"]["affected_occurrence_count"] == 1
