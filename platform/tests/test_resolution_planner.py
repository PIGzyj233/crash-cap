from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from crashcap_api.config import Settings
from crashcap_api.db import Database
from crashcap_api.models import AnalysisDemand, AnalysisDemandTarget, CatalogPair
from crashcap_api.services.analysis_demands import DemandError, freeze_target, register_inspection
from crashcap_api.services.resolution_planning import PlanningLimits, snapshot_resolution
from crashcap_api.services.symbol_catalog import mark_location_unavailable, review_pair
from crashcap_api.storage import create_object_store
from crashcap_worker.core_runner import CoreExecutionError, CoreExecutor
from crashcap_worker.demand_inspection import prepare_inspection
from crashcap_worker.resolution_planner import prepare_resolution
from sqlalchemy import func, select

from . import test_symbol_catalog_postgres as catalog_tests
from .catalog_fixtures import admit_pair, origin, prepare_catalog_pair
from .test_analysis_demands import NOW, SCHEMAS, seed

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures/p0-b01-null-read/generated"
pg = catalog_tests.pg
pytestmark = pytest.mark.skipif(
    not os.getenv("QAI_PLANNER_REAL"), reason="requires real catalog planning qualification"
)


@pytest.fixture
def planner(request):
    output = (
        ROOT
        / "target/qa-symbol-import/planner"
        / os.getenv("QAI_PLANNER_RUN_TOKEN", "local")
        / uuid.uuid4().hex
    )
    settings = Settings.for_test(output).model_copy(
        update={
            "core_executor": "local",
            "core_command": str(ROOT / "target/debug/dmp-core.exe"),
        }
    )
    db = None
    if os.getenv("QAI_CATALOG_DATABASE_URL"):
        _, sessions, _ = request.getfixturevalue("pg")
    else:
        db = Database(settings)
        sessions = db.sessions
    core, store = CoreExecutor(settings), create_object_store(settings)
    dump = FIXTURE / "null-read.dmp"
    sha, size = hashlib.sha256(dump.read_bytes()).hexdigest(), dump.stat().st_size
    with sessions.begin() as session:
        demand, blob = seed(session, sha=sha, size=size)
    store.put_file(blob.object_key, dump, "application/octet-stream")
    evidence = prepare_inspection(
        core,
        store,
        workspace_id=blob.workspace_id,
        dump_key=blob.object_key,
        dump_sha256=sha,
        dump_size=size,
    )
    with sessions.begin() as session:
        register_inspection(session, demand.id, evidence, now=NOW)
    try:
        yield {
            "sessions": sessions,
            "core": core,
            "store": store,
            "settings": settings,
            "demand_id": demand.id,
            "output": output,
            "inspection": evidence,
        }
    finally:
        if db:
            db.dispose()


def add_pair(planner, variant="", *, admit=True):
    pe = FIXTURE / "null_read_target.exe"
    if variant:
        pe = planner["output"] / f"variant-{variant}.exe"
        pe.write_bytes((FIXTURE / "null_read_target.exe").read_bytes() + variant.encode())
    prepared = prepare_catalog_pair(
        planner["core"],
        planner["store"],
        pe,
        FIXTURE / "null_read_target.pdb",
        payload_encoding="zstd-v1",
    )
    if not admit:
        return prepared
    with planner["sessions"].begin() as session:
        pair_id = admit_pair(
            session, prepared.pe, prepared.pdb, prepared.locations, origin(variant or "first")
        ).id
    return pair_id, prepared


def plan(planner, limits=None):
    with planner["sessions"].begin() as session:
        snapshot = snapshot_resolution(session, planner["demand_id"], limits=limits)
    return prepare_resolution(planner["core"], planner["store"], snapshot)


def adopt(planner, prepared):
    with planner["sessions"].begin() as session:
        return freeze_target(
            session,
            prepared.demand_id,
            expected_sequence=prepared.change_sequence,
            manifest=prepared.manifest,
            manifest_object_key=prepared.manifest_object_key,
            context_sha256="f" * 64,
            cause="symbol_refresh",
            schema_root=SCHEMAS,
            now=NOW,
        )


def first_module(prepared):
    return prepared.manifest["modules"][0]


def test_actual_missing_unique_conflict_recovery_and_stable_origin(planner):
    absent = plan(planner)
    assert first_module(absent)["state"] == "none"
    assert adopt(planner, absent).generation == 1
    a, prepared_a = add_pair(planner)
    unique = plan(planner)
    assert first_module(unique)["selected_pair_id"] == a
    first_target = adopt(planner, unique)
    assert first_target.generation == 2
    with planner["sessions"].begin() as session:
        admit_pair(
            session, prepared_a.pe, prepared_a.pdb, prepared_a.locations, origin("another-origin")
        )
    stable = plan(planner)
    assert stable.resolution_fingerprint == unique.resolution_fingerprint
    assert stable.manifest_sha256 != unique.manifest_sha256
    assert adopt(planner, stable).manifest_sha256 == first_target.manifest_sha256
    b, _ = add_pair(planner, "valid-overlay")
    conflict = plan(planner, replace(PlanningLimits(), page_size=1))
    assert first_module(conflict)["state"] == "conflict"
    assert first_module(conflict)["candidate_pair_ids"] == sorted([a, b])
    assert adopt(planner, conflict).generation == 3
    with planner["sessions"].begin() as session:
        review = review_pair(
            session,
            b,
            state="withdrawn",
            expected_version=1,
            idempotency_key="withdraw-b",
            reason="qualification recovery",
            evidence_object_key="unit/review",
            evidence_sha256="e" * 64,
        )
    recovery = plan(planner)
    assert first_module(recovery)["selected_pair_id"] == a
    assert first_module(recovery)["unavailable_pair_ids"] == [b]
    assert first_module(recovery)["review_refs"] == [review.id]
    assert adopt(planner, recovery).generation == 4
    with planner["sessions"]() as session:
        assert (
            session.get(AnalysisDemandTarget, (planner["demand_id"], 2)).manifest_sha256
            == unique.manifest_sha256
        )
    assert not list(planner["settings"].task_tmp_root.iterdir())


@pytest.mark.parametrize("budget", ["candidates_per_module", "total_candidates", "validations"])
def test_incomplete_budget_never_becomes_unique(planner, budget):
    add_pair(planner)
    add_pair(planner, "second-valid-content")
    result = plan(planner, replace(PlanningLimits(), **{budget: 1}))
    selected = first_module(result)
    assert selected["state"] == "indeterminate" and not selected["candidates_complete"]
    assert selected["selected_pair_id"] is None
    assert selected["reason"] == (
        "validation_incomplete" if budget == "validations" else "enumeration_failed"
    )
    adopt(planner, result)


def test_exact_candidate_budget_with_complete_enumeration_is_unique(planner):
    pair_id, _ = add_pair(planner)
    result = plan(
        planner,
        PlanningLimits(page_size=1, candidates_per_module=1, total_candidates=1, validations=1),
    )
    assert first_module(result)["selected_pair_id"] == pair_id


def test_corrupt_material_does_not_hide_competing_candidate(planner):
    _, pair = add_pair(planner)
    add_pair(planner, "valid-second")
    planner["store"].put_bytes(
        pair.locations["pe"][0].object_key, b"corrupt", "application/octet-stream"
    )
    result = plan(planner)
    assert first_module(result)["state"] == "indeterminate"
    assert first_module(result)["selected_pair_id"] is None
    assert len(first_module(result)["candidate_pair_ids"]) == 1
    evidence = first_module(result)["candidate_evidence"]
    receipt = json.loads(b"".join(planner["store"].stream(evidence["object_key"])))
    assert any(c.get("error") == "CATALOG_PAYLOAD_HASH_MISMATCH" for c in receipt["candidates"])


def test_validator_output_mismatch_does_not_exclude_competing_content(planner, monkeypatch):
    _, prepared = add_pair(planner)
    add_pair(planner, "other-valid-pair")
    identify = planner["core"].identify_artifact

    def inconsistent(path, kind):
        report = identify(path, kind)
        if kind == "pe" and report["sha256"] == prepared.pe.raw_sha256:
            report["sha256"] = "0" * 64
        return report

    monkeypatch.setattr(planner["core"], "identify_artifact", inconsistent)
    result = plan(planner)
    assert first_module(result)["state"] == "indeterminate"
    assert len(first_module(result)["candidate_pair_ids"]) == 1
    assert first_module(result)["selected_pair_id"] is None


def test_logically_unavailable_location_is_not_silently_restored(planner):
    pair_id, _ = add_pair(planner)
    with planner["sessions"].begin() as session:
        snapshot = snapshot_resolution(session, planner["demand_id"])
        location = snapshot.pairs[pair_id].pe.locations[0]
        mark_location_unavailable(
            session,
            location.id,
            reason="qualification missing replica",
            evidence_object_key="unit/location-failure",
            evidence_sha256="f" * 64,
        )
    result = plan(planner)
    assert first_module(result)["state"] == "unavailable"
    assert first_module(result)["reason"] == "location_unavailable"


def test_catalog_change_during_material_io_commits_and_stale_adoption_is_rejected(
    planner, monkeypatch
):
    _, first = add_pair(planner)
    pending = add_pair(planner, "concurrent", admit=False)
    stream = planner["store"].stream
    changed = False

    def interleave(key, chunk_size=1024 * 1024):
        nonlocal changed
        if key == first.locations["pe"][0].object_key and not changed:
            changed = True
            with planner["sessions"].begin() as session:
                admit_pair(
                    session, pending.pe, pending.pdb, pending.locations, origin("concurrent")
                )
        return stream(key, chunk_size)

    monkeypatch.setattr(planner["store"], "stream", interleave)
    stale = plan(planner)
    assert changed and first_module(stale)["state"] == "unique"
    with pytest.raises(DemandError, match="CATALOG_SNAPSHOT_CHANGED"):
        adopt(planner, stale)
    with planner["sessions"]() as session:
        assert session.scalar(select(func.count()).select_from(CatalogPair)) == 2
        assert session.get(AnalysisDemand, planner["demand_id"]).generation == 0
    assert first_module(plan(planner))["state"] == "conflict"


@pytest.mark.parametrize("target", ["inspect", "manifest"])
def test_inspect_and_manifest_readback_integrity(planner, monkeypatch, target):
    if target == "inspect":
        planner["store"].put_bytes(planner["inspection"].object_key, b"{}", "application/json")
    else:
        put = planner["store"].put_bytes

        def corrupt(key, data, content_type):
            return put(
                key, b"{}" if key.endswith("resolution-manifest.json") else data, content_type
            )

        monkeypatch.setattr(planner["store"], "put_bytes", corrupt)
    with pytest.raises(CoreExecutionError) as caught:
        plan(planner)
    assert caught.value.code == "PLANNER_OBJECT_HASH_MISMATCH"
    with planner["sessions"]() as session:
        assert session.get(AnalysisDemand, planner["demand_id"]).generation == 0
