from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .errors import ApiError


@lru_cache(maxsize=16)
def load_validator(path: str) -> Draft202012Validator:
    schema_path = Path(path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    registry = Registry()
    roots = [schema_path.parent]
    # Qualification contracts may reference already published contracts. Resolve
    # only the repository's local contract package; never fetch schema URLs.
    roots.extend(
        parent
        for parent in schema_path.parents
        if parent.name == "contracts"
        and parent != schema_path.parent
        and (parent / "analysis-result-v1.schema.json").is_file()
    )
    for candidate in (candidate for root in roots for candidate in root.glob("*.schema.json")):
        document = json.loads(candidate.read_text(encoding="utf-8"))
        identifier = document.get("$id")
        if isinstance(identifier, str):
            registry = registry.with_resource(identifier, Resource.from_contents(document))
            registry = registry.with_resource(candidate.name, Resource.from_contents(document))
    return Draft202012Validator(schema, registry=registry)


def validate_contract(payload: object, schema_path: Path, label: str) -> None:
    validator = load_validator(str(schema_path.resolve()))
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    if not errors:
        return
    first = errors[0]
    location = "/" + "/".join(str(part) for part in first.absolute_path)
    raise ApiError(
        "VALIDATION",
        f"{label} does not satisfy {schema_path.stem}",
        status_code=422,
        details={"path": location, "reason": first.message},
    )


def validate_task_message(payload: dict[str, Any], schema_root: Path) -> None:
    if payload.get("schema_version") == "1.2":
        # Only the implemented consumer is qualified. Published 1.0/1.1 stay frozen.
        if payload.get("task_type") not in {
            "verify_symbol_import_pair",
            "dispatch_workspace_role",
            "analyze_frozen_run",
        }:
            raise ApiError("VALIDATION", "Task 1.2 consumer is not implemented", status_code=422)
        validate_contract(
            payload,
            schema_root / "drafts/qa-symbol-import/task-message-v1.2.schema.json",
            "qualification task message",
        )
        return
    schema_name = (
        "task-message-v1.1.schema.json"
        if payload.get("schema_version") == "1.1"
        else "task-message-v1.schema.json"
    )
    validate_contract(payload, schema_root / schema_name, "task message")
