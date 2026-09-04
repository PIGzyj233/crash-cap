from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from crashcap_api.contracts import load_validator
from crashcap_api.ids import new_id
from crashcap_api.models import AnalysisRun, Occurrence
from crashcap_api.services.analysis_lifecycle import promote_current_analysis
from jsonschema import Draft202012Validator

from .conftest import Phase1Harness, dump_bytes


def seed_new_result(harness: Phase1Harness) -> tuple[str, str, str, bytes, bytes]:
    """Synthetic 1.1 reader fixture; never presented as native Core evidence."""
    workspace = harness.create_workspace("dual-reader")
    completed = harness.upload_dump(workspace["id"], dump_bytes(91))
    occurrence_id = completed["occurrence_id"]
    old_bytes = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/analysis").content
    canonical = json.loads(old_bytes)
    old_id = canonical["analysis_id"]
    new_id_value = new_id("run")
    canonical["schema_version"] = "1.1"
    canonical["analysis_id"] = new_id_value
    canonical["symbol_resolution"] = {
        "selection_version": "pair-selection-v1",
        "resolution_evidence_fingerprint": "a" * 64,
        "manifest": {"object_key": "fixture/manifest", "sha256": "b" * 64},
        "inspect_sha256": "c" * 64,
        "context_sha256": "d" * 64,
    }
    for index, module in enumerate(canonical["modules"]):
        module["module_index"] = index
        module["source_outcomes"] = []
        module["selection"] = {
            "module_index": index,
            "identity": {"code_id": None, "debug_id": None, "architecture": "x86_64"},
            "state": "indeterminate",
            "candidates_complete": False,
            "candidate_pair_ids": [],
            "unavailable_pair_ids": [],
            "selected_pair_id": None,
            "reason": "incomplete_identity",
            "candidate_evidence": {"object_key": "fixture/candidates", "sha256": "e" * 64},
            "review_refs": [],
        }
        module["status"] = "symbol_indeterminate"
    for thread in canonical["threads"]:
        for index, frame in enumerate(thread["frames"]):
            frame.update(module_index=None, physical_frame_index=index, unwind_method="unknown")
    new_bytes = (json.dumps(canonical, indent=3) + "\n").encode()
    schema = harness.settings.schema_root / "analysis-result-v1.1.schema.json"
    load_validator(str(schema)).validate(canonical)
    assert not load_validator(
        str(harness.settings.schema_root / "analysis-result-v1.schema.json")
    ).is_valid(canonical)
    key = f"fixture/{new_id_value}/canonical.json"
    harness.app.state.store.put_bytes(key, new_bytes, "application/json")
    with harness.app.state.database.sessions() as session:
        old = session.get(AnalysisRun, old_id)
        assert old is not None
        candidate = AnalysisRun(
            id=new_id_value,
            occurrence_id=occurrence_id,
            run_spec={},
            core_version=old.core_version,
            core_image_digest=old.core_image_digest,
            symbolicator_version=old.symbolicator_version,
            schema_version="1.1",
            symbol_inventory_version=0,
            idempotency_key="9" * 64,
            status="PARTIAL",
            result_object_key=key,
        )
        session.add(candidate)
        session.flush()
        occurrence = session.get(Occurrence, occurrence_id)
        assert occurrence is not None
        # Isolated reader fixture only; product promotion is independently blocked.
        occurrence.current_run_id = candidate.id
        session.commit()
    return occurrence_id, old_id, new_id_value, old_bytes, new_bytes


def test_v2_returns_original_bytes_and_v1_rejects_new_current(harness: Phase1Harness) -> None:
    occurrence_id, old_id, new_id_value, old_bytes, new_bytes = seed_new_result(harness)
    for endpoint in (
        f"/api/v2/occurrences/{occurrence_id}/analysis",
        f"/api/v2/runs/{new_id_value}/analysis",
    ):
        response = harness.client.get(endpoint)
        assert response.status_code == 200, response.text
        assert response.content == new_bytes
    for section in ("analysis", "threads", "modules"):
        response = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/{section}")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CANONICAL_VERSION_UNSUPPORTED"
    for section in ("threads", "modules"):
        response = harness.client.get(f"/api/v2/occurrences/{occurrence_id}/{section}")
        assert response.status_code == 200
        assert response.json() == json.loads(new_bytes)[section]
    for version in ("v1", "v2"):
        response = harness.client.get(
            f"/api/{version}/occurrences/{occurrence_id}/analysis", params={"run_id": old_id}
        )
        assert response.status_code == 200
        assert response.content == old_bytes
    capabilities = harness.client.get("/api/v2/capabilities").json()
    assert capabilities["reader_versions"] == ["1.0", "1.1"]
    assert capabilities["enabled_writes"] == []


def test_legacy_reprocess_cannot_replace_a_new_protocol_occurrence(harness: Phase1Harness) -> None:
    occurrence_id, _, new_id_value, _, _ = seed_new_result(harness)
    response = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess", json={"force": True}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CLIENT_UPGRADE_REQUIRED"
    with harness.app.state.database.sessions() as session:
        occurrence = session.get(Occurrence, occurrence_id)
        current = session.get(AnalysisRun, new_id_value)
        assert occurrence is not None and current is not None
        candidate = AnalysisRun(
            id="run_ZZZZZZZZZZZZZZZZZZZZZZZZZZ",
            occurrence_id=occurrence_id,
            schema_version="1.0",
            status="PARTIAL",
        )
        assert promote_current_analysis(session, occurrence, candidate).promoted is False
        assert occurrence.current_run_id == new_id_value


def test_v2_history_cannot_cross_occurrence(harness: Phase1Harness) -> None:
    _, old_id, _, _, _ = seed_new_result(harness)
    workspace = harness.create_workspace("other-reader")
    other = harness.upload_dump(workspace["id"], dump_bytes(92))
    response = harness.client.get(
        f"/api/v2/occurrences/{other['occurrence_id']}/analysis", params={"run_id": old_id}
    )
    assert response.status_code == 404


def test_openapi_keeps_old_defs_separate_from_v11(harness: Phase1Harness) -> None:
    document = harness.client.get("/openapi.json").json()
    schemas = document["components"]["schemas"]
    assert "symbol_resolution" not in schemas["CanonicalAnalysisResult"]["properties"]
    assert schemas["Canonical11AnalysisResult"]["properties"]["schema_version"] == {"const": "1.1"}
    assert "unwind_method" not in schemas["CanonicalFrame"]["properties"]
    assert "unwind_method" in schemas["Canonical11Frame"]["properties"]
    response = document["paths"]["/api/v2/occurrences/{occurrence_id}/analysis"]["get"][
        "responses"
    ]["200"]
    assert len(response["content"]["application/json"]["schema"]["oneOf"]) == 2
    section = document["paths"]["/api/v2/occurrences/{occurrence_id}/threads"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    # Empty frames are valid in both versions, so a section cannot use an
    # exclusive union without falsely rejecting this legitimate payload.
    Draft202012Validator({**section, "components": {"schemas": schemas}}).validate(
        [{"id": 1, "name": None, "is_crashing": False, "frames": []}]
    )


def test_additive_constraint_upgrade_and_safe_downgrade() -> None:
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0011_canonical_dual_reader.py"
    spec = importlib.util.spec_from_file_location("canonical_dual_reader_migration", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE analysis_runs (id TEXT PRIMARY KEY, "
                "schema_version TEXT NOT NULL DEFAULT '1.0', "
                "CONSTRAINT ck_analysis_runs_schema_version CHECK (schema_version = '1.0'))"
            )
        )
        connection.execute(sa.text("INSERT INTO analysis_runs (id) VALUES ('old')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            connection.execute(sa.text("INSERT INTO analysis_runs VALUES ('new', '1.1')"))
            with pytest.raises(RuntimeError, match="retain a compatible reader"):
                migration.downgrade()
            assert connection.execute(
                sa.text("SELECT schema_version FROM analysis_runs ORDER BY id")
            ).scalars().all() == ["1.1", "1.0"]
            connection.execute(sa.text("DELETE FROM analysis_runs WHERE id='new'"))
            migration.downgrade()
        assert (
            connection.execute(sa.text("SELECT schema_version FROM analysis_runs")).scalar_one()
            == "1.0"
        )
    engine.dispose()
