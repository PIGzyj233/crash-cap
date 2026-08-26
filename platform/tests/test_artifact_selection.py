from __future__ import annotations

from pathlib import Path
from typing import Any

from crashcap_api.config import REPOSITORY_ROOT
from crashcap_api.contracts import validate_contract
from crashcap_worker.artifact_selection import plan_artifact_selection, selected_artifacts
from crashcap_worker.processor import _materialize_match_spec


def _artifact(
    index: int,
    *,
    build_id: str,
    module_id: str | None,
    kind: str,
    code_id: str | None,
    debug_id: str | None,
    sha256: str | None = None,
    object_key: str | None = None,
) -> dict[str, Any]:
    digest = sha256 or f"{index:064x}"
    return {
        "artifact_id": f"art_{index}",
        "build_id": build_id,
        "module_id": module_id,
        "kind": kind,
        "logical_name": f"module-{index}.{kind}",
        "sha256": digest,
        "size": 100 + index,
        "object_key": object_key or f"artifacts/{digest}",
        "code_id": code_id,
        "debug_id": debug_id,
        "role": "entrypoint",
        "code_file": f"module-{index}.exe",
        "debug_file": f"module-{index}.pdb",
        "in_app": True,
        "ingest_metadata": None,
        "source_bundle_config": None,
    }


def _run_spec(
    artifacts: list[dict[str, Any]],
    builds: list[dict[str, Any]],
    *,
    reported_build_id: str | None = None,
) -> dict[str, Any]:
    return {
        "workspace_id": "wsp_test",
        "run_id": "run_test",
        "reported_build_id": reported_build_id,
        "artifacts": artifacts,
        "builds": builds,
    }


def test_exact_dump_identity_selects_only_candidate_pair_from_large_inventory() -> None:
    artifacts: list[dict[str, Any]] = []
    builds: list[dict[str, Any]] = []
    for index in range(100):
        build_id = f"bld_{index}"
        module_id = f"mod_{index}"
        code_id = f"CODE{index:04d}"
        debug_id = f"{index:032x}1"
        builds.append(
            {
                "build_id": build_id,
                "modules": [
                    {
                        "module_id": module_id,
                        "code_id": code_id,
                        "debug_id": debug_id,
                    }
                ],
            }
        )
        artifacts.extend(
            [
                _artifact(
                    index * 2 + 1,
                    build_id=build_id,
                    module_id=module_id,
                    kind="pe",
                    code_id=code_id,
                    debug_id=debug_id,
                ),
                _artifact(
                    index * 2 + 2,
                    build_id=build_id,
                    module_id=module_id,
                    kind="pdb",
                    code_id=None,
                    debug_id=debug_id,
                ),
            ]
        )

    inspect = {"modules": [{"code_id": "code0042", "debug_id": f"{42:032x}1"}]}
    spec = _run_spec(artifacts, builds)
    selection = plan_artifact_selection(spec, inspect, mode="active")

    assert selection["candidate_build_ids"] == ["bld_42"]
    assert selection["matched_module_ids"] == ["mod_42"]
    assert selection["inventory_summary"]["artifact_count"] == 200
    assert selection["selection_summary"]["artifact_count"] == 2
    assert {item["kind"] for item in selection["selected_artifacts"]} == {"pe", "pdb"}
    assert len(selected_artifacts(spec, selection, mode="active")) == 2
    validate_contract(
        selection,
        REPOSITORY_ROOT / "contracts" / "artifact-selection-v1.schema.json",
        "artifact selection",
    )


def test_module_match_closes_pe_pdb_pair_and_candidate_source_bundle() -> None:
    build_id = "bld_pair"
    module_id = "mod_pair"
    pe = _artifact(
        1,
        build_id=build_id,
        module_id=module_id,
        kind="pe",
        code_id="ABC123",
        debug_id="d" * 32 + "1",
    )
    pdb = _artifact(
        2,
        build_id=build_id,
        module_id=module_id,
        kind="pdb",
        code_id=None,
        debug_id="d" * 32 + "1",
    )
    source = _artifact(
        3,
        build_id=build_id,
        module_id=None,
        kind="source_bundle",
        code_id=None,
        debug_id=None,
    )
    spec = _run_spec(
        [pe, pdb, source],
        [
            {
                "build_id": build_id,
                "modules": [
                    {
                        "module_id": module_id,
                        "code_id": "ABC123",
                        "debug_id": "d" * 32 + "1",
                    }
                ],
            }
        ],
    )

    selection = plan_artifact_selection(
        spec,
        {"modules": [{"code_id": "abc123", "debug_id": None}]},
        mode="active",
    )

    by_kind = {item["kind"]: item for item in selection["selected_artifacts"]}
    assert set(by_kind) == {"pe", "pdb", "source_bundle"}
    assert by_kind["pdb"]["selection_reasons"] == ["code_id", "paired_artifact"]
    assert by_kind["source_bundle"]["selection_reasons"] == ["candidate_source_bundle"]


def test_reported_build_remains_a_supported_explicit_input() -> None:
    selected = _artifact(
        1,
        build_id="bld_reported",
        module_id="mod_reported",
        kind="pe",
        code_id="A",
        debug_id="a" * 33,
    )
    unrelated = _artifact(
        2,
        build_id="bld_other",
        module_id="mod_other",
        kind="pe",
        code_id="B",
        debug_id="b" * 33,
    )
    spec = _run_spec(
        [selected, unrelated],
        [
            {"build_id": "bld_reported", "modules": []},
            {"build_id": "bld_other", "modules": []},
        ],
        reported_build_id="bld_reported",
    )

    selection = plan_artifact_selection(spec, {"modules": []}, mode="active")

    assert selection["candidate_build_ids"] == ["bld_reported"]
    assert [item["artifact_id"] for item in selection["selected_artifacts"]] == ["art_1"]
    assert selection["selected_artifacts"][0]["selection_reasons"] == ["reported_build"]


def test_no_identity_match_materializes_no_workspace_history() -> None:
    artifact = _artifact(
        1,
        build_id="bld_old",
        module_id="mod_old",
        kind="pe",
        code_id="OLD",
        debug_id="a" * 33,
    )
    spec = _run_spec(
        [artifact],
        [
            {
                "build_id": "bld_old",
                "modules": [
                    {"module_id": "mod_old", "code_id": "OLD", "debug_id": "a" * 33}
                ],
            }
        ],
    )

    selection = plan_artifact_selection(
        spec,
        {"modules": [{"code_id": "NEW", "debug_id": "b" * 33}]},
        mode="active",
    )

    assert selection["candidate_build_ids"] == []
    assert selection["selected_artifacts"] == []
    assert selected_artifacts(spec, selection, mode="active") == []


class _RecordingStore:
    def __init__(self) -> None:
        self.downloads: list[str] = []

    def download_file(self, key: str, destination: Path) -> None:
        self.downloads.append(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"verified")


def test_materialization_reuses_verified_sha256_across_build_bindings(tmp_path: Path) -> None:
    digest = "f" * 64
    first = _artifact(
        1,
        build_id="bld_one",
        module_id="mod_one",
        kind="pe",
        code_id="CODE",
        debug_id="a" * 33,
        sha256=digest,
        object_key="legacy/one",
    )
    second = _artifact(
        2,
        build_id="bld_two",
        module_id="mod_two",
        kind="pe",
        code_id="CODE",
        debug_id="a" * 33,
        sha256=digest,
        object_key="legacy/two",
    )
    spec = _run_spec([first, second], [])
    store = _RecordingStore()

    match = _materialize_match_spec(store, tmp_path, spec, [first, second])  # type: ignore[arg-type]

    assert store.downloads == ["legacy/one"]
    assert len(match["modules"]) == 2
    assert {item["pe_path"] for item in match["modules"]} == {
        f"artifacts/{digest}.pe"
    }
