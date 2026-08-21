"""Fixed local/CI entry point for Draft 2020-12 contract tests.

The Rust schema-test package owns the validator and its positive/negative
examples. Keeping this command in the repository gives CI and developers one
stable invocation without depending on a globally installed Python validator.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema", type=Path, help="validate concrete JSON instances against this schema")
    parser.add_argument("--instance", type=Path, action="append", default=[], help="JSON instance to validate; repeatable")
    args = parser.parse_args()
    if args.schema or args.instance:
        if not args.schema or not args.instance:
            parser.error("--schema and at least one --instance must be supplied together")
        command = [
            "cargo",
            "run",
            "--quiet",
            "-p",
            "crash-cap-schema-tests",
            "--bin",
            "validate-instance",
            "--",
            str(args.schema),
            *(str(path) for path in args.instance),
        ]
        completed = subprocess.run(command, cwd=ROOT, check=False)
        return completed.returncode
    command = ["cargo", "test", "-p", "crash-cap-schema-tests"]
    completed = subprocess.run(command, cwd=ROOT, check=False)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
