import pytest
from crashcap_api.models import AnalysisRun, GroupMembership, GroupMembershipHistory, Occurrence
from crashcap_api.services.current_projection import update_group_projection
from sqlalchemy import select

from .conftest import dump_bytes
from .test_phase1_api_contracts import _complete_dump, _prepared_build


@pytest.mark.parametrize("algorithm", ["exact-v1.0", "exact-v1.1"])
def test_group_audit_uses_report_algorithm_for_assignment_and_unclassification(harness, algorithm):
    workspace = harness.create_workspace("projection-algorithm")
    build = _prepared_build(harness, workspace["id"])
    completed = _complete_dump(
        harness, workspace["id"], dump_bytes(31), reported_build_id=build["id"]
    )
    with harness.app.state.database.sessions.begin() as session:
        occurrence = session.get(Occurrence, completed["occurrence_id"])
        run = session.get(AnalysisRun, occurrence.current_run_id)
        # Exercise the projection boundary; no stored Canonical is rewritten.
        update_group_projection(
            session, occurrence, run, {"fingerprints": {"exact": "f" * 64, "algorithm": algorithm}}
        )
        assert (
            session.get(GroupMembership, occurrence.id).grouping_evidence_json["algorithm"]
            == algorithm
        )
        update_group_projection(
            session, occurrence, run, {"fingerprints": {"exact": None, "algorithm": algorithm}}
        )
        history = session.scalars(
            select(GroupMembershipHistory)
            .where(GroupMembershipHistory.occurrence_id == occurrence.id)
            .order_by(GroupMembershipHistory.id)
        ).all()
        assert [row.grouping_evidence_json["algorithm"] for row in history[-2:]] == [
            algorithm,
            algorithm,
        ]
        assert history[-1].action == "unclassify"
