"""Collect reproducible local evidence, without opening application secrets or mutating DBs."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def command(args):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=90)
    return {
        "command": args,
        "exit_code": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output", type=Path, default=ROOT / "target/qa-symbol-import/baseline.json"
    )
    parser.add_argument(
        "--core",
        type=Path,
        default=ROOT
        / "target/debug"
        / ("dmp-core.exe" if platform.system() == "Windows" else "dmp-core"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fixture = ROOT / "fixtures/p0-b01-null-read/generated"
    files = [
        ROOT / p
        for p in [
            "Cargo.lock",
            "platform/uv.lock",
            "platform/frontend/pnpm-lock.yaml",
            "deploy/compose/symbolicator.yml",
            "deploy/symbolicator/config.yml",
            "deploy/symbolicator/gateway.py",
        ]
    ]
    files += sorted((ROOT / "contracts").glob("*.schema.json"))
    files += sorted((ROOT / "platform/migrations/versions").glob("*.py"))
    files += [
        fixture / name
        for name in [
            "null-read.dmp",
            "null_read_target.exe",
            "null_read_target.pdb",
            "manifest.json",
        ]
    ]
    status = command(["git", "status", "--porcelain=v1", "--untracked-files=all"])
    changed = command(["git", "diff", "--name-only"])["stdout"].splitlines()
    untracked = command(["git", "ls-files", "--others", "--exclude-standard"])[
        "stdout"
    ].splitlines()
    differences = [
        {"path": p, "sha256": sha(ROOT / p)}
        for p in sorted(set(changed + untracked))
        if (ROOT / p).is_file()
        and (ROOT / p).resolve() != args.output.resolve()
        and not (
            p.startswith("docs/evidence/qa-symbol-import/") and p.endswith(".json")
        )
    ]
    evidence = {
        "schema_version": "qai-baseline-v1",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "environment": "local Windows development checkout",
        "head": command(["git", "rev-parse", "HEAD"])["stdout"],
        "git_status": status["stdout"],
        "workspace_files": differences,
        "platform": platform.platform(),
        "files": [
            {
                "path": str(p.relative_to(ROOT)),
                "sha256": sha(p),
                "size": p.stat().st_size,
            }
            if p.is_file()
            else {
                "path": str(p.relative_to(ROOT)),
                "status": "NOT_PROVEN",
                "reason": "file absent",
            }
            for p in files
        ],
        "docker": command(["docker", "version", "--format", "{{.Server.Version}}"]),
        "data_health": {
            "status": "NOT_PROVEN",
            "reason": "No target database selected. Isolated database and target health must be recorded separately; no implicit default database probe.",
        },
        "commands": [],
    }
    if args.core.is_file():
        evidence["core_binary"] = {"sha256": sha(args.core), "path": str(args.core)}
        for kind, name in [
            ("pe", "null_read_target.exe"),
            ("pdb", "null_read_target.pdb"),
        ]:
            evidence["commands"].append(
                command(
                    [
                        str(args.core),
                        "identify",
                        "--kind",
                        kind,
                        "--artifact",
                        str(fixture / name),
                        "--output",
                        "-",
                    ]
                )
            )
        for verb in ("inspect", "analyze"):
            out = args.output.parent / (
                "baseline-inspect.json"
                if verb == "inspect"
                else "baseline-canonical-1.0.json"
            )
            cmd = [
                str(args.core),
                verb,
                "--dump",
                str(fixture / "null-read.dmp"),
                "--output",
                str(out),
            ]
            if verb == "analyze":
                cmd += ["--raw-dir", str(args.output.parent / "baseline-raw")]
            evidence["commands"].append(command(cmd))
            if out.exists():
                evidence.setdefault("outputs", []).append(
                    {"path": str(out), "sha256": sha(out)}
                )
    else:
        evidence["core_binary"] = {
            "status": "NOT_PROVEN",
            "reason": "build dmp-core first",
        }
    evidence["status"] = (
        "PASS"
        if evidence["commands"]
        and all(c["exit_code"] == 0 for c in evidence["commands"])
        and all("sha256" in f for f in evidence["files"])
        else "FAIL"
    )
    evidence["scope"] = (
        "Local source/fixture baseline only; data-health and deployment are not included in PASS."
    )
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "output": str(args.output),
                "data_health": "NOT_PROVEN",
            }
        )
    )
    raise SystemExit(0 if evidence["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
