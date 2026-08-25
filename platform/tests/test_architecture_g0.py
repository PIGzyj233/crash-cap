from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

from crashcap_api.contracts import validate_task_message

from .conftest import Phase1Harness

ROOT = Path(__file__).resolve().parents[2]


def test_route_inventory_covers_every_api_v1_operation(harness: Phase1Harness) -> None:
    inventory = json.loads(
        (ROOT / "docs" / "architecture" / "http-route-inventory.json").read_text(encoding="utf-8")
    )["routes"]
    actual = {
        f"{method.upper()} {path}"
        for path, operations in harness.app.openapi()["paths"].items()
        for method in operations
        if path.startswith("/api/v1")
        and method.upper() in {"GET", "POST", "PUT", "PATCH", "DELETE"}
    }
    assert set(inventory) == actual
    assert len(actual) == 40
    assert all(item["consumers"] and item["wave"] in {1, 2, 3} for item in inventory.values())


def test_golden_baseline_still_names_exactly_21_fixtures() -> None:
    fixture_index = json.loads((ROOT / "fixtures" / "index.json").read_text(encoding="utf-8"))
    golden = fixture_index["golden"]
    selected = set(fixture_index["fixtures"]) - set(golden["exclude_from_golden"])
    evidence = json.loads(
        (ROOT / "docs" / "evidence" / "phase0-golden-results.json").read_text(encoding="utf-8")
    )
    assert golden["expected_count"] == 21
    assert len(selected) == 21
    assert evidence["status"] == "PASS"
    assert evidence["counts"] == {"PASS": 21}


def test_all_four_stable_task_shapes_remain_valid() -> None:
    messages: list[dict[str, Any]] = [
        {
            "schema_version": "1.0",
            "task_type": "verify_upload",
            "upload_id": "upl_baseline",
            "attempt_id": "att_baseline_verify",
            "queue": "verify",
        },
        {
            "schema_version": "1.0",
            "task_type": "ingest_artifact",
            "artifact_id": "art_baseline",
            "attempt_id": "att_baseline_ingest",
            "queue": "ingest",
        },
        {
            "schema_version": "1.0",
            "task_type": "reindex_symbols",
            "workspace_id": "wsp_baseline",
            "build_id": "bld_baseline",
            "attempt_id": "att_baseline_reindex",
            "queue": "ingest",
        },
        {
            "schema_version": "1.0",
            "task_type": "analyze_occurrence",
            "run_id": "run_baseline",
            "attempt_id": "att_baseline_analyze",
            "queue": "dump-small",
        },
    ]
    for message in messages:
        validate_task_message(message, ROOT / "contracts")


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
