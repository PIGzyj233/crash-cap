from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .errors import ApiError


@lru_cache(maxsize=16)
def load_validator(path: str) -> Draft202012Validator:
    schema = json.loads(Path(path).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_contract(payload: object, schema_path: Path, label: str) -> None:
    validator = load_validator(str(schema_path.resolve()))
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    if not errors:
        return
    first = errors[0]
    location = "/" + "/".join(str(part) for part in first.absolute_path)
    raise ApiError(
        "VALIDATION",
        f"{label} does not satisfy the stable 1.0 contract",
        status_code=422,
        details={"path": location, "reason": first.message},
    )


def validate_task_message(payload: dict[str, Any], schema_root: Path) -> None:
    validate_contract(payload, schema_root / "task-message-v1.schema.json", "task message")
