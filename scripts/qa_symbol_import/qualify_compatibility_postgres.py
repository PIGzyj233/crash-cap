"""Run the migration roundtrip against an owned, disposable local PostgreSQL.

No configured application DB URL is consumed. A cached image ID is pinned, an
ephemeral loopback port is allocated, and only this invocation's labeled
container/anonymous volume are removed on exit.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "target/qa-symbol-import"


def docker(*args):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    image = json.loads(docker("image", "inspect", args.image).stdout)[0]
    OUT.mkdir(parents=True, exist_ok=True)
    token = uuid.uuid4().hex
    label = "crashcap.qai.compatibility=" + token
    container = docker(
        "run",
        "--pull=never",
        "--rm",
        "-d",
        "--name",
        "qai-reader-pg-" + token[:12],
        "--label",
        label,
        "-e",
        "POSTGRES_PASSWORD=qai-local-fixture",
        "-e",
        "POSTGRES_DB=crashcap_qai_compat",
        "-p",
        "127.0.0.1::5432",
        image["Id"],
    ).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{64}", container) is None:
        raise RuntimeError("Docker did not return an exact owned container ID")
    report = {
        "schema_version": "qai-compatibility-postgres-v1",
        "time_utc": datetime.now(UTC).isoformat(),
        "status": "FAIL",
        "image_id": image["Id"],
        "repo_digests": image.get("RepoDigests", []),
        "container_id": container,
        "application_database_touched": False,
    }
    try:
        for _ in range(60):
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    container,
                    "pg_isready",
                    "-U",
                    "postgres",
                    "-d",
                    "crashcap_qai_compat",
                ],
                capture_output=True,
                check=False,
            )
            if result.returncode == 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError("Disposable PostgreSQL did not become ready")
        port = docker("port", container, "5432/tcp").stdout.strip()
        match = re.fullmatch(r"127\.0\.0\.1:(\d+)", port)
        if match is None:
            raise RuntimeError("Disposable database is not bound solely to loopback")
        version = docker(
            "exec",
            container,
            "psql",
            "-U",
            "postgres",
            "-d",
            "crashcap_qai_compat",
            "-Atc",
            "SHOW server_version",
        ).stdout.strip()
        url = f"postgresql+psycopg://postgres:qai-local-fixture@127.0.0.1:{match[1]}/crashcap_qai_compat"
        junit = OUT / "compatibility-postgres.xml"
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "migrations/tests/test_phase1_migration.py::test_phase1_can_upgrade_and_downgrade_postgresql",
            f"--junitxml={junit}",
        ]
        result = subprocess.run(
            command,
            cwd=ROOT / "platform",
            env=dict(os.environ, CRASH_CAP_TEST_DATABASE_URL=url),
            capture_output=True,
            text=True,
            check=False,
        )
        log = OUT / "compatibility-postgres.log"
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        report.update(command=command, exit_code=result.returncode, postgres_version=version)
        if result.returncode:
            raise RuntimeError(f"PostgreSQL compatibility check failed; see {log}")
        suites = ET.parse(junit).getroot()
        if len(suites.findall(".//testcase")) != 1 or suites.findall(".//skipped"):
            raise RuntimeError("The PostgreSQL roundtrip must execute without skips")
        report["status"] = "PASS"
        report["hashes"] = {
            path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in [
                junit,
                log,
                Path(__file__),
                *sorted((ROOT / "platform/migrations/versions").glob("*.py")),
                ROOT / "platform/migrations/env.py",
                ROOT / "platform/api/crashcap_api/models.py",
                ROOT / "platform/migrations/tests/test_phase1_migration.py",
            ]
        }
        report["boundary"] = (
            "Local fresh PostgreSQL migration roundtrip plus preserved 1.0 and blocked downgrade with 1.1. Not target upgrade, backup recovery or a mixed-container rollout."
        )
    finally:
        actual = docker(
            "inspect",
            container,
            "--format",
            '{{ index .Config.Labels "crashcap.qai.compatibility" }}',
        ).stdout.strip()
        if actual != token:
            raise RuntimeError("Container ownership label changed; refusing cleanup")
        docker("rm", "-f", "--volumes", container)
        report["owned_container_removed"] = True
        (OUT / "compatibility-postgres.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("status", "postgres_version", "image_id", "owned_container_removed")
            }
        )
    )


if __name__ == "__main__":
    main()
