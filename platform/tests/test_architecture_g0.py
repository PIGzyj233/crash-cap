from __future__ import annotations

import ast
import json
from pathlib import Path

from crashcap_api.contracts import validate_task_message

from .conftest import Phase1Harness

ROOT = Path(__file__).resolve().parents[2]


def test_route_inventory_covers_every_api_v3_operation(harness: Phase1Harness) -> None:
    inventory = json.loads(
        (ROOT / "docs" / "architecture" / "http-route-inventory.json").read_text(encoding="utf-8")
    )["routes"]
    actual = {
        f"{method.upper()} {path}"
        for path, operations in harness.app.openapi()["paths"].items()
        for method in operations
        if path.startswith("/api/v3")
        and method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    assert set(inventory) == actual
    assert all(
        path.startswith("/api/v3")
        for path in harness.app.openapi()["paths"]
        if path.startswith("/api/")
    )
    assert all(item["consumers"] and item["wave"] in {1, 2, 3} for item in inventory.values())


def test_golden_index_names_unique_fixtures_with_committed_metadata() -> None:
    fixture_index = json.loads((ROOT / "fixtures" / "index.json").read_text(encoding="utf-8"))
    golden = fixture_index["golden"]
    selected = set(fixture_index["fixtures"]) - set(golden["exclude_from_golden"])
    assert golden["expected_count"] == 21
    assert len(selected) == 21
    assert len(fixture_index["fixtures"]) == len(set(fixture_index["fixtures"]))
    assert set().union(*map(set, golden["categories"].values())) == selected
    for fixture_id in selected:
        fixture = ROOT / "fixtures" / fixture_id
        metadata = json.loads((fixture / "fixture.json").read_text(encoding="utf-8"))
        assert metadata["fixture_id"] == fixture_id
        assert (fixture / "expected.json").is_file()


def test_only_current_task_shapes_are_valid() -> None:
    import pytest
    from crashcap_api.errors import ApiError

    messages = [
        dict(
            schema_version="1.0",
            task_type="verify_upload",
            upload_id="upl_one",
            attempt_id="att_one",
            queue="verify",
        ),
        dict(
            schema_version="1.2",
            task_type="dispatch_workspace_role",
            workspace_id="wsp_one",
            role_version=1,
            attempt_id="att_two",
            queue="ingest",
        ),
        dict(
            schema_version="1.2",
            task_type="analyze_frozen_run",
            run_id="run_one",
            attempt_id="att_three",
            queue="dump-small",
        ),
    ]
    for message in messages:
        validate_task_message(message, ROOT / "contracts")
    for retired in ("ingest_artifact", "reindex_symbols", "analyze_occurrence"):
        with pytest.raises(ApiError):
            validate_task_message({**messages[0], "task_type": retired}, ROOT / "contracts")


def test_analysis_status_has_one_production_write_authority() -> None:
    production_roots = (ROOT / "platform" / "api", ROOT / "platform" / "worker")
    authority = ROOT / "platform" / "api" / "crashcap_api" / "services" / "analysis_lifecycle.py"
    violations: list[str] = []
    for production_root in production_roots:
        for path in production_root.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "_advance_to_analyzing" not in source
            if path == authority:
                continue
            tree = ast.parse(source, filename=str(path))
            for node in ast.walk(tree):
                targets: list[ast.expr] = []
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                    raw_targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    targets.extend(raw_targets)
                for target in targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr == "status"
                        and isinstance(target.value, ast.Name)
                        and target.value.id in {"run", "analysis_run", "current_run"}
                    ):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []
