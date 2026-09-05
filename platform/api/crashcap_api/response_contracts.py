from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from .response_models import ErrorEnvelopeResponse

CANONICAL_COMPONENT = "CanonicalAnalysisResult"
CANONICAL_DEFINITION_COMPONENTS = {
    "nullableTimestamp": "CanonicalNullableTimestamp",
    "hexAddr": "CanonicalHexAddr",
    "trust": "CanonicalTrust",
    "moduleRole": "CanonicalModuleRole",
    "qualityWarning": "CanonicalQualityWarning",
    "thread": "CanonicalThread",
    "frame": "CanonicalFrame",
    "module": "CanonicalModule",
}


class EventStreamResponse(StreamingResponse):
    media_type = "text/event-stream"


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {
        "description": "Crash-Cap error envelope",
        "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/ErrorEnvelopeResponse"}}
        },
    }
    for status in (400, 403, 404, 409, 410, 413, 422, 500, 501)
}

CANONICAL_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Stable Canonical Analysis Result v2.0",
        "content": {
            "application/json": {"schema": {"$ref": f"#/components/schemas/{CANONICAL_COMPONENT}"}}
        },
    }
}

CANONICAL_V2_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Original immutable Canonical 2.0 bytes",
        "content": {
            "application/json": {"schema": {"$ref": "#/components/schemas/CanonicalAnalysisResult"}}
        },
    }
}

CANONICAL_THREADS_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Threads from the selected stable Canonical Analysis Result",
        "content": {
            "application/json": {
                "schema": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/CanonicalThread"},
                }
            }
        },
    }
}

CANONICAL_MODULES_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Modules from the selected stable Canonical Analysis Result",
        "content": {
            "application/json": {
                "schema": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/CanonicalModule"},
                }
            }
        },
    }
}


def canonical_section_v2_response(section: str) -> dict[int | str, dict[str, Any]]:
    return {
        200: {
            "description": "Selected Canonical section (2.0)",
            "content": {
                "application/json": {
                    "schema": {
                        "type": "array",
                        "items": {"$ref": f"#/components/schemas/Canonical{section}"},
                    }
                }
            },
        }
    }


SSE_RESPONSE: dict[int | str, dict[str, Any]] = {
    200: {
        "description": "Analysis progress Server-Sent Events stream",
        "content": {
            "text/event-stream": {
                "schema": {"type": "string"},
                "examples": {
                    "progress": {
                        "summary": "Analysis state transition",
                        "value": (
                            "id: run_example:ANALYZING\n"
                            "event: analysis-progress\n"
                            'data: {"occurrence_id":"occ_example","run":{"id":"run_example",'
                            '"status":"ANALYZING"},"current_run_id":null}\n\n'
                        ),
                    }
                },
            }
        },
    }
}


def _namespace_local_refs(value: Any, components: dict[str, str] | None = None) -> Any:
    names = components or CANONICAL_DEFINITION_COMPONENTS
    if isinstance(value, dict):
        result = {key: _namespace_local_refs(item, names) for key, item in value.items()}
        reference = result.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            definition = reference.removeprefix("#/$defs/")
            result["$ref"] = f"#/components/schemas/{names[definition]}"
        return result
    if isinstance(value, list):
        return [_namespace_local_refs(item, names) for item in value]
    return value


def install_canonical_openapi_contract(app: FastAPI, schema_root: Path) -> None:
    """Embed the stable JSON Schema once and make route responses reference it."""

    canonical_path = schema_root / "analysis-result-v2.0.schema.json"
    # Git stores this text contract with LF endings. Editors on Windows may
    # write CRLF before staging; fingerprint the same repository representation
    # so generated OpenAPI does not vary between worktrees and CI.
    canonical_bytes = canonical_path.read_bytes().replace(b"\r\n", b"\n")
    canonical_document = json.loads(canonical_bytes)
    canonical_definitions = canonical_document.pop("$defs")
    canonical_schema = _namespace_local_refs(canonical_document)
    canonical_schema["x-crashcap-source-contract"] = canonical_path.name
    canonical_schema["x-crashcap-source-sha256"] = hashlib.sha256(canonical_bytes).hexdigest()
    error_schema = ErrorEnvelopeResponse.model_json_schema(
        ref_template="#/components/schemas/{model}"
    )
    error_definitions = error_schema.pop("$defs", {})
    original_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            document = original_openapi()
            components = document.setdefault("components", {}).setdefault("schemas", {})
            components["ErrorEnvelopeResponse"] = error_schema
            components.update(error_definitions)
            components[CANONICAL_COMPONENT] = copy.deepcopy(canonical_schema)
            for definition, component in CANONICAL_DEFINITION_COMPONENTS.items():
                components[component] = _namespace_local_refs(
                    copy.deepcopy(canonical_definitions[definition])
                )
            app.openapi_schema = document
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
