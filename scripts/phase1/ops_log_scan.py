#!/usr/bin/env python3
"""Scan operational logs for common Phase 1 credential/data leakage patterns.

The scanner reports only file, line and a category; it never echoes the
matching log line. It is suitable for a post-deploy smoke check and CI fixture
test. It does not prove that arbitrary binary memory contents were absent.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PATTERNS = (
    (
        "presigned-query",
        re.compile(r"(?i)(?:x-amz-signature|x-amz-credential|x-amz-security-token)="),
    ),
    ("bearer-token", re.compile(r"(?i)authorization\s*:\s*bearer\s+\S+")),
    (
        "cloud-secret",
        re.compile(
            r"(?i)(?:aws_secret_access_key|secret_key|access_key)\s*[:=]\s*[^\s,;]+"
        ),
    ),
    ("password-value", re.compile(r"(?i)(?:password|passwd)\s*[:=]\s*[^\s,;]+")),
    ("private-key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    (
        "source-body",
        re.compile(
            r"(?i)(?:source|source_code|memory|registers?)\s*(?:bytes?)?\s*[:=]\s*\S+"
        ),
    ),
)


def scan(content: str) -> list[tuple[int, str]]:
    findings: list[tuple[int, str]] = []
    for line_number, line in enumerate(content.splitlines(), 1):
        for category, pattern in PATTERNS:
            if pattern.search(line):
                findings.append((line_number, category))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args()
    findings: list[tuple[str, int, str]] = []
    if not args.paths:
        findings.extend(
            ("<stdin>", line, category) for line, category in scan(sys.stdin.read())
        )
    for path in args.paths:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"ERROR: cannot read {path}: {exc}", file=sys.stderr)
            return 2
        findings.extend((str(path), line, category) for line, category in scan(content))
    if findings:
        print(f"Log leakage scan: FAIL ({len(findings)} finding(s))")
        for path, line, category in findings:
            print(f"  {path}:{line}: {category}")
        print("Matching content was intentionally suppressed.")
        return 1
    print("Log leakage scan: PASS (no configured credential/token/source patterns)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
