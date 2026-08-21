#!/usr/bin/env python3
"""Export the FastAPI application's OpenAPI document without starting a server."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _load_application() -> Any:
    """Import the platform application directly from the repository sources."""

    platform_root = REPOSITORY_ROOT / "platform"
    for source_root in (
        platform_root / "api",
        platform_root / "worker",
        platform_root / "cli",
    ):
        sys.path.insert(0, str(source_root))

    from crashcap_api.app import create_app
    from crashcap_api.config import Settings

    return create_app, Settings


def build_schema() -> dict[str, Any]:
    """Build the current FastAPI schema using only local test-safe services."""

    create_app, settings_type = _load_application()
    with tempfile.TemporaryDirectory(prefix="crashcap-openapi-") as temporary_root:
        settings = settings_type.for_test(Path(temporary_root))
        app = create_app(settings)
        return app.openapi()


def render_schema(schema: dict[str, Any]) -> str:
    """Render a stable, reviewable JSON representation for source control."""

    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "platform" / "frontend" / "openapi.json",
        help="Path to the checked-in OpenAPI JSON document.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the existing output is not the current local FastAPI schema.",
    )
    arguments = parser.parse_args()
    output_path = arguments.output.resolve()
    rendered = render_schema(build_schema())

    if arguments.check:
        if not output_path.is_file():
            print(f"OpenAPI document is missing: {output_path}", file=sys.stderr)
            return 1
        current = output_path.read_text(encoding="utf-8")
        if current != rendered:
            print(
                "OpenAPI document is stale; run the frontend openapi:generate script.",
                file=sys.stderr,
            )
            return 1
        print(f"OpenAPI schema is current: {output_path}")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8", newline="\n")
    print(f"Exported OpenAPI schema: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
