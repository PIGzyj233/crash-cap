#!/usr/bin/env python3
"""Create deterministic unique DMP payloads and an external upload manifest.

The input must be a valid, already-authorized minidump fixture.  Each generated
file preserves that fixture and appends a unique marker.  Large samples use a
sparse logical tail, so the resulting object has the requested byte length
without requiring a temporary in-memory buffer.  The files and manifest must
be written outside the repository and are never deleted by this tool.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

SMALL_MAX_BYTES = 64 * 1024 * 1024
DEFAULT_SMALL_COUNT = 80
DEFAULT_LARGE_COUNT = 20
DEFAULT_LARGE_SIZE = SMALL_MAX_BYTES + 1


def create_variant(
    template: Path, destination: Path, *, target_size: int | None, marker: bytes
) -> int:
    template_size = template.stat().st_size
    minimum_size = template_size + len(marker)
    if target_size is not None and target_size < minimum_size:
        raise ValueError(
            "target size is smaller than the fixture plus its unique marker"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        with template.open("rb") as source:
            shutil.copyfileobj(source, output, length=8 * 1024 * 1024)
        output.write(marker)
        if target_size is not None:
            output.truncate(target_size)
    return destination.stat().st_size


def generate_fixture_manifest(
    *,
    template: Path,
    output_dir: Path,
    manifest_path: Path,
    workspace_id: str,
    build_id: str | None,
    small_count: int,
    large_count: int,
    large_size_bytes: int,
) -> dict[str, Any]:
    if not template.is_file():
        raise ValueError("template must reference an existing DMP file")
    with template.open("rb") as source:
        if source.read(4) != b"MDMP":
            raise ValueError("template must start with the minidump MDMP signature")
    if small_count <= 0 or large_count <= 0 or small_count + large_count != 100:
        raise ValueError("small-count and large-count must be positive and sum to 100")
    if large_size_bytes <= SMALL_MAX_BYTES or large_size_bytes > 256 * 1024 * 1024:
        raise ValueError("large-size-bytes must be in (64MiB, 256MiB]")
    if template.stat().st_size >= SMALL_MAX_BYTES:
        raise ValueError("template must be smaller than the <=64MiB bucket")

    output_dir.mkdir(parents=True, exist_ok=True)
    tasks: list[dict[str, Any]] = []
    for index in range(1, small_count + 1):
        marker = (
            f"\nCRASHCAP_CAPACITY_FIXTURE=v1;bucket=small;index={index:04d}\n".encode()
        )
        destination = output_dir / f"small-{index:04d}.dmp"
        size_bytes = create_variant(
            template, destination, target_size=None, marker=marker
        )
        tasks.append(
            {
                "task_id": f"small-{index:04d}",
                "workspace_id": workspace_id,
                "reported_build_id": build_id,
                "payload_path": str(destination.resolve()),
                "size_bytes": size_bytes,
                "capture_profile": "rich-crash",
            }
        )
    for index in range(1, large_count + 1):
        marker = (
            f"\nCRASHCAP_CAPACITY_FIXTURE=v1;bucket=large;index={index:04d}\n".encode()
        )
        destination = output_dir / f"large-{index:04d}.dmp"
        size_bytes = create_variant(
            template,
            destination,
            target_size=large_size_bytes,
            marker=marker,
        )
        tasks.append(
            {
                "task_id": f"large-{index:04d}",
                "workspace_id": workspace_id,
                "reported_build_id": build_id,
                "payload_path": str(destination.resolve()),
                "size_bytes": size_bytes,
                "capture_profile": "rich-crash",
            }
        )

    manifest = {
        "schema_version": "phase1.capacity-fixture.v1",
        "template": str(template.resolve()),
        "small_count": small_count,
        "large_count": large_count,
        "large_size_bytes": large_size_bytes,
        "tasks": tasks,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--build-id")
    parser.add_argument("--small-count", type=int, default=DEFAULT_SMALL_COUNT)
    parser.add_argument("--large-count", type=int, default=DEFAULT_LARGE_COUNT)
    parser.add_argument("--large-size-bytes", type=int, default=DEFAULT_LARGE_SIZE)
    args = parser.parse_args()
    manifest_path = args.manifest or args.output_dir / "manifest-100.json"
    try:
        manifest = generate_fixture_manifest(
            template=args.template.resolve(),
            output_dir=args.output_dir.resolve(),
            manifest_path=manifest_path.resolve(),
            workspace_id=args.workspace_id,
            build_id=args.build_id,
            small_count=args.small_count,
            large_count=args.large_count,
            large_size_bytes=args.large_size_bytes,
        )
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        f"Generated {len(manifest['tasks'])} unique DMP payloads and manifest "
        f"at {manifest_path.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
