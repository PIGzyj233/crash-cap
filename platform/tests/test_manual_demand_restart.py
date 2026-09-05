from datetime import timedelta

import pytest
from crashcap_api.config import Settings
from crashcap_api.models import AnalysisDemand, AnalysisDemandTarget, DumpBlob
from crashcap_api.services.analysis_demands import (
    DemandError,
    register_inspection,
    restart_exhausted_demand,
    settle_demand_after_execution_failure,
)

from . import test_analysis_demands as cases
from .test_analysis_demands import NOW, evidence, freeze, seed

demands = cases.demands


def test_repeated_manual_cycles_get_new_targets_but_retries_do_not(demands, tmp_path):
    settings = Settings.for_test(tmp_path).model_copy(
        update={"automatic_analysis_enabled": True, "analysis_max_attempts": 1}
    )
    with demands.begin() as session:
        demand, blob = seed(session)
        inspection = register_inspection(session, demand.id, evidence(blob), now=NOW)
        first = freeze(session, demand, inspection, cause="manual")
        old = (first.generation, first.manifest_sha256, first.resolution_fingerprint)
        for generation in (2, 3):
            settle_demand_after_execution_failure(
                demand,
                blob,
                cause="manual",
                error_code="CORE_TIMEOUT",
                retryable=True,
                settings=settings,
                now=NOW,
            )
            previous_sequence = demand.change_sequence
            session.flush()
            restart_exhausted_demand(
                session,
                settings,
                demand.id,
                workspace_id=demand.workspace_id,
                expected_generation=generation - 1,
                expected_sequence=previous_sequence,
                now=NOW,
            )
            assert demand.reason == "manual"
            assert demand.change_sequence == previous_sequence + 1
            target = freeze(session, demand, inspection, cause="manual")
            assert target.generation == generation
            assert demand.retry_attempt == 0
            demand.retry_attempt = 1
            session.flush()
            assert freeze(session, demand, inspection, cause="manual").generation == generation
            assert demand.retry_attempt == 1
        retained = session.get(AnalysisDemandTarget, (demand.id, old[0]))
        assert (
            retained.generation,
            retained.manifest_sha256,
            retained.resolution_fingerprint,
        ) == old


@pytest.mark.parametrize(
    "condition,reason",
    [
        ("disabled", "AUTOMATIC_ANALYSIS_DISABLED"),
        ("paused", "AUTOMATIC_ANALYSIS_PAUSED"),
        ("foreign", "DEMAND_NOT_FOUND"),
        ("stale", "STALE_DEMAND"),
        ("running", "DEMAND_NOT_EXHAUSTED"),
        ("expired", "DUMP_UNAVAILABLE"),
    ],
)
def test_restart_rejections_preserve_demand(demands, tmp_path, condition, reason):
    settings = Settings.for_test(tmp_path).model_copy(
        update={
            "automatic_analysis_enabled": condition != "disabled",
            "automatic_analysis_paused": condition == "paused",
        }
    )
    with demands.begin() as session:
        demand, blob = seed(session)
        demand.state = "running" if condition == "running" else "retry_exhausted"
        demand.reason = "execution_retry_exhausted:manual:CORE_TIMEOUT"
        demand.not_before = None
        if condition == "expired":
            blob.expires_at = NOW - timedelta(seconds=1)
        demand_id, blob_id = demand.id, blob.id
        before = (demand.state, demand.reason, demand.change_sequence, demand.retry_attempt)
    with demands.begin() as session, pytest.raises(DemandError, match=reason):
        restart_exhausted_demand(
            session,
            settings,
            demand_id,
            workspace_id="foreign" if condition == "foreign" else "wsp_a",
            expected_generation=1 if condition == "stale" else 0,
            expected_sequence=1,
            now=NOW,
        )
    with demands() as session:
        demand = session.get(AnalysisDemand, demand_id)
        assert (demand.state, demand.reason, demand.change_sequence, demand.retry_attempt) == before
        assert session.get(DumpBlob, blob_id).verification_status == "ACCEPTED"
