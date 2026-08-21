#!/usr/bin/env python3
"""Check local relative Markdown links without requiring network access.

External URLs, anchors that stay in the current document, and links inside
fenced code blocks are intentionally not fetched.  This keeps the check
deterministic for CI while still catching moved or misspelled repository files.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


INLINE_LINK = re.compile(r"!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))")
REFERENCE_DEFINITION = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(?:<([^>]+)>|(\S+))")
REFERENCE_USE = re.compile(r"!?\[[^\]]+\]\[([^\]]*)\]")
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def local_target(raw: str) -> str | None:
    target = raw.strip()
    if not target or target.startswith("#") or target.startswith("//") or SCHEME.match(target):
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    return path or "."


def scan_file(path: Path, root: Path) -> tuple[list[dict[str, str]], int]:
    issues: list[dict[str, str]] = []
    checked = 0
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        return [{"file": path.relative_to(root).as_posix(), "target": "", "error": str(exc)}], 0

    definitions: dict[str, str] = {}
    definition_fence = False
    definition_token = ""
    for line in lines:
        fence = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            token = fence.group(1)[0]
            if not definition_fence:
                definition_fence = True
                definition_token = token
            elif token == definition_token:
                definition_fence = False
            continue
        if not definition_fence:
            definition = REFERENCE_DEFINITION.match(line)
            if definition:
                definitions[definition.group(1).strip().lower()] = definition.group(2) or definition.group(3)

    in_fence = False
    fence_token = ""
    for line_number, line in enumerate(lines, start=1):
        fence = re.match(r"^\s*(`{3,}|~{3,})", line)
        if fence:
            token = fence.group(1)[0]
            if not in_fence:
                in_fence = True
                fence_token = token
            elif token == fence_token:
                in_fence = False
            continue
        if in_fence:
            continue
        candidates = [match.group(1) or match.group(2) for match in INLINE_LINK.finditer(line)]
        for match in REFERENCE_USE.finditer(line):
            label = match.group(1).strip().lower()
            if label:
                candidates.append(definitions.get(label, ""))
        for raw in candidates:
            target = local_target(raw)
            if target is None:
                continue
            checked += 1
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                issues.append(
                    {
                        "file": path.relative_to(root).as_posix(),
                        "line": str(line_number),
                        "target": raw,
                        "resolved": str(resolved),
                        "error": "local target does not exist",
                    }
                )
    return issues, checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"root does not exist: {root}")

    ignored_parts = {".git", ".runtime", "target", "node_modules", "__pycache__"}
    files = sorted(
        path
        for path in root.rglob("*.md")
        if not any(part in ignored_parts for part in path.relative_to(root).parts)
    )
    issues: list[dict[str, str]] = []
    checked = 0
    for path in files:
        file_issues, file_checked = scan_file(path, root)
        issues.extend(file_issues)
        checked += file_checked
    result = {
        "status": "PASS" if not issues else "FAIL",
        "root": str(root),
        "files_scanned": len(files),
        "local_links_checked": checked,
        "broken_links": issues,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    sys.stdout.write(rendered)
    if args.output:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
