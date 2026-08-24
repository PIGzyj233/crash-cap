from __future__ import annotations

import zipfile
from pathlib import Path
from typing import Any

import pytest
from crashcap_api.canonical_semantics import (
    CanonicalSemanticError,
    canonical_parity_differences,
    validate_canonical_semantics,
)
from crashcap_api.models import AnalysisRun, OperationLog
from crashcap_worker import processor as processor_module
from crashcap_worker.core_runner import CoreOutput
from sqlalchemy import select

from .conftest import Phase1Harness, dump_bytes, pdb_bytes, pe_bytes
from .test_phase1_pipeline import prepared_build

DEBUG_ID = "d" * 32 + "1"


def test_core_final_mode_persists_core_owned_identity_and_context(
    harness: Phase1Harness,
) -> None:
    harness.settings.canonical_assembly_mode = "core-final"
    workspace = harness.create_workspace("canonical-core-final")
    build = prepared_build(harness, workspace["id"], debug_id=DEBUG_ID)

    completed = harness.upload_dump(
        workspace["id"],
        dump_bytes(220),
        reported_build_id=build["id"],
    )
    occurrence_id = completed["occurrence_id"]
    canonical = harness.client.get(f"/api/v1/occurrences/{occurrence_id}/analysis").json()
    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    run_id = detail["current_analysis"]["id"]

    assert canonical["workspace_id"] == workspace["id"]
    assert canonical["occurrence_id"] == occurrence_id
    assert canonical["analysis_id"] == run_id
    assert canonical["dump"]["blob_id"] == completed["blob_id"]
    with harness.app.state.database.sessions() as session:
        run = session.get(AnalysisRun, run_id)
        assert run is not None
        assert run.assembly_mode == "core-final"
        assert run.analysis_context["schema_version"] == "analysis-context-v1"
        assert run.analysis_context["inspect"]["sha256"]
        assert run.result_object_key is not None
        assert "/g/" in run.result_object_key
        legacy_key = f"{run.raw_object_prefix}legacy-canonical.json"
    assert harness.app.state.store.head(legacy_key).size > 0


def test_shadow_mode_keeps_legacy_primary_and_records_zero_parity_diff(
    harness: Phase1Harness,
) -> None:
    harness.settings.canonical_assembly_mode = "shadow"
    workspace = harness.create_workspace("canonical-shadow")
    build = prepared_build(harness, workspace["id"], debug_id=DEBUG_ID)
    completed = harness.upload_dump(
        workspace["id"],
        dump_bytes(221),
        reported_build_id=build["id"],
    )
    detail = harness.client.get(f"/api/v1/occurrences/{completed['occurrence_id']}").json()
    run_id = detail["current_analysis"]["id"]
    with harness.app.state.database.sessions() as session:
        log = session.scalar(
            select(OperationLog)
            .where(OperationLog.action == "analysis.complete", OperationLog.target_id == run_id)
            .order_by(OperationLog.occurred_at.desc())
        )
        run = session.get(AnalysisRun, run_id)
        assert log is not None and run is not None
        assert log.details["assembly_mode"] == "shadow"
        assert log.details["canonical_shadow_mismatch_count"] == 0
        shadow_key = f"{run.raw_object_prefix}core-final-shadow.json"
    assert harness.app.state.store.head(shadow_key).size > 0


def test_core_final_source_bundle_is_staged_and_enriched_by_fake_core(
    harness: Phase1Harness,
    tmp_path: Path,
) -> None:
    harness.settings.canonical_assembly_mode = "core-final"
    workspace = harness.create_workspace("canonical-source")
    build = harness.create_build(workspace["id"], "2.0.0")
    manifest = {
        "schema_version": "2.0",
        "product": "Canonical source",
        "version": "2.0.0",
        "architecture": "x86_64",
        "compiler": "msvc",
        "toolchain": "msvc-19.40",
        "modules": [
            {"code_file": "app.exe", "debug_file": "app.pdb", "role": "entrypoint"}
        ],
        "source_bundle": {
            "schema_version": "1.0",
            "archive": "source-bundle.zip",
            "source_root": "C:/agent/_work/product",
            "strip_prefixes": [],
            "context_lines": 1,
        },
    }
    response = harness.client.put(f"/api/v1/builds/{build['id']}/manifest", json=manifest)
    assert response.status_code == 200, response.text
    harness.upload_artifact(build["id"], "pe", "app.exe", pe_bytes(DEBUG_ID))
    harness.upload_artifact(build["id"], "pdb", "app.pdb", pdb_bytes(DEBUG_ID))
    archive = tmp_path / "source-bundle.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr(
            "fake.cpp",
            "\n".join(f"source line {line}" for line in range(1, 60)),
        )
    harness.upload_artifact(build["id"], "source_bundle", archive.name, archive.read_bytes())

    completed = harness.upload_dump(
        workspace["id"],
        dump_bytes(222),
        reported_build_id=build["id"],
    )
    canonical = harness.client.get(
        f"/api/v1/occurrences/{completed['occurrence_id']}/analysis"
    ).json()
    assert canonical["threads"][0]["frames"][0]["source_context"] == {
        "pre": ["source line 41"],
        "line": "source line 42",
        "post": ["source line 43"],
    }


def test_semantic_validator_rejects_schema_valid_wrong_identity_and_engine() -> None:
    context: dict[str, Any] = {
        "schema_version": "analysis-context-v1",
        "identity": {
            "workspace_id": "wsp_expected",
            "occurrence_id": "occ_expected",
            "analysis_id": "run_expected",
        },
        "dump": {
            "blob_id": "blob_expected",
            "sha256": "a" * 64,
            "kind": "user_minidump",
            "size": 1,
            "dump_timestamp": None,
            "reported_at": None,
            "uploaded_at": "2025-01-01T00:00:00+00:00",
            "occurred_at": "2025-01-01T00:00:00+00:00",
            "time_source": "uploaded",
        },
        "engine": {
            "core_image_digest": "sha256:" + "0" * 64,
            "symbolicator_version": "expected",
            "grouping_version": "group-v1.0",
            "normalization_version": "norm-v1.0",
        },
        "inputs": {"build_ids": []},
    }
    canonical = {
        "schema_version": "1.0",
        "workspace_id": "wsp_wrong",
        "occurrence_id": "occ_expected",
        "analysis_id": "run_expected",
    }
    with pytest.raises(CanonicalSemanticError, match="workspace_id"):
        validate_canonical_semantics(canonical, context)


def test_new_run_can_roll_back_to_legacy_without_reinterpreting_old_run(
    harness: Phase1Harness,
) -> None:
    first_digest = "sha256:" + "1" * 64
    second_digest = "sha256:" + "2" * 64
    harness.settings.canonical_assembly_mode = "core-final"
    harness.settings.core_image_digest = first_digest
    workspace = harness.create_workspace("canonical-rollback")
    build = prepared_build(harness, workspace["id"], debug_id=DEBUG_ID)
    completed = harness.upload_dump(
        workspace["id"],
        dump_bytes(223),
        reported_build_id=build["id"],
    )
    occurrence_id = completed["occurrence_id"]
    before = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    old_run_id = before["current_analysis"]["id"]
    old_canonical = harness.client.get(
        f"/api/v1/occurrences/{occurrence_id}/analysis",
        params={"run_id": old_run_id},
    ).json()

    harness.settings.canonical_assembly_mode = "legacy"
    harness.settings.core_image_digest = second_digest
    requested = harness.client.post(
        f"/api/v1/occurrences/{occurrence_id}/reprocess",
        json={"force": True},
    )
    assert requested.status_code == 202, requested.text
    harness.drain()
    after = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    new_run_id = after["current_analysis"]["id"]
    assert new_run_id != old_run_id

    with harness.app.state.database.sessions() as session:
        old_run = session.get(AnalysisRun, old_run_id)
        new_run = session.get(AnalysisRun, new_run_id)
        assert old_run is not None and new_run is not None
        assert (old_run.assembly_mode, old_run.core_image_digest) == (
            "core-final",
            first_digest,
        )
        assert (new_run.assembly_mode, new_run.core_image_digest) == (
            "legacy",
            second_digest,
        )
        assert old_run.analysis_context["dump"] == new_run.analysis_context["dump"]
    reread_old = harness.client.get(
        f"/api/v1/occurrences/{occurrence_id}/analysis",
        params={"run_id": old_run_id},
    ).json()
    assert reread_old == old_canonical


def test_core_final_semantic_mismatch_fails_without_current_promotion(
    harness: Phase1Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness.settings.canonical_assembly_mode = "core-final"
    workspace = harness.create_workspace("canonical-semantic-fence")
    build = prepared_build(harness, workspace["id"], debug_id=DEBUG_ID)
    core = harness.app.state.processor.core
    original = core.analyze_prepared

    def wrong_identity(task_dir: Path, run_spec: dict[str, Any]) -> CoreOutput:
        output = original(task_dir, run_spec)
        output.canonical["workspace_id"] = "wsp_semantically_wrong"
        return output

    monkeypatch.setattr(core, "analyze_prepared", wrong_identity)
    initialized = harness.initialize_dump(
        workspace["id"],
        dump_bytes(224),
        reported_build_id=build["id"],
    )
    harness.drain()
    terminal = harness.client.get(f"/api/v1/uploads/{initialized['upload_id']}").json()
    occurrence_id = terminal["occurrence_id"]
    with harness.app.state.database.sessions() as session:
        run = session.scalar(select(AnalysisRun).where(AnalysisRun.occurrence_id == occurrence_id))
        assert run is not None
        assert run.status == "FAILED"
        assert run.error_code == "CANONICAL_SEMANTIC_MISMATCH"
    detail = harness.client.get(f"/api/v1/occurrences/{occurrence_id}").json()
    assert detail["current_analysis"] is None


def test_shadow_diff_reports_precise_paths_and_core_final_branch_has_no_legacy_mutator() -> None:
    assert canonical_parity_differences(
        {"dump": {"time_source": "uploaded"}, "threads": []},
        {"dump": {"time_source": "dump"}, "threads": []},
    ) == ["/dump/time_source"]
    source = Path(processor_module.__file__).read_text(encoding="utf-8")
    core_final_block = source.split('elif assembly_mode == "shadow":', maxsplit=1)[1].split(
        "detached =", maxsplit=1
    )[0]
    assert "bind_legacy_canonical" in core_final_block
    assert 'assembly_mode == "core-final"' not in source
    assert "_bind_platform_identity" not in source
