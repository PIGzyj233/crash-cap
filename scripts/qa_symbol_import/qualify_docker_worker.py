"""Build/use an isolated Core image, then qualify both real Worker executors.

Default builds a unique tag without touching application images. --image reuses
an explicitly named image; its actual ID is always inspected and pinned. The
image is retained for reproduction. The native runner owns service cleanup.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "target/qa-symbol-import"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", help="Explicit existing qualification Core image")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    receipt = OUT / "frozen-worker-docker-progress.json"
    evidence = {"status": "RUNNING", "recorded_at": datetime.now(UTC).isoformat()}
    receipt.write_text(json.dumps(evidence) + "\n", encoding="utf-8")
    try:
        docker = shutil.which("docker")
        if docker is None:
            raise RuntimeError("Docker executable is unavailable")
        tag = args.image or f"crash-cap/qai-frozen-core:{uuid.uuid4().hex}"
        evidence["core_image"] = tag
        if args.image is None:
            with (OUT / "frozen-worker-image.log").open("w", encoding="utf-8") as log:
                subprocess.run(  # noqa: S603 - fixed argv, no shell
                    [docker, "build", "-f", "deploy/core/Dockerfile", "-t", tag, "."],
                    cwd=ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=2400,
                )
        observed = subprocess.run(  # noqa: S603 - named image, no shell
            [docker, "image", "inspect", tag],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        info = json.loads(observed.stdout)[0]
        if (
            info["Os"] != "linux"
            or info["Architecture"] != "amd64"
            or info["Config"]["User"] != "65532:65532"
        ):
            raise RuntimeError("Core image must be the Linux x64 non-root build")
        evidence["core_image_digest"] = info["Id"]
        environment = os.environ.copy()
        environment.update(QAI_NATIVE_CORE_IMAGE=tag, QAI_NATIVE_CORE_IMAGE_DIGEST=info["Id"])
        with (OUT / "frozen-worker-docker-live.log").open("w", encoding="utf-8") as log:
            subprocess.run(  # noqa: S603 - repository-owned runner, no shell
                [sys.executable, str(ROOT / "scripts/qa_symbol_import/qualify_native_sources.py")],
                cwd=ROOT,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=1800,
            )
        native = json.loads((OUT / "native-source/progress.json").read_text(encoding="utf-8"))
        worker = native["docker_worker"]
        if (
            native["status"] != "PASS"
            or worker["status"] != "PASS"
            or worker["core_image_digest"] != info["Id"]
        ):
            raise RuntimeError("Native/Docker worker evidence did not pass")
        if not worker["task_resources_removed"]:
            raise RuntimeError("Docker task resources were not removed")
        evidence.update(
            status="PASS",
            docker_worker=worker,
            owned_service_cleanup=native["owned_container_and_volume_removed"],
            retained_core_image=True,
            not_proven=[
                "durable task and fencing",
                "catalog/planner",
                "object-store upload",
                "Current promotion",
                "target deployment",
            ],
        )
    except Exception as error:
        evidence.update(status="FAIL", error=f"{type(error).__name__}: {error}")
    paths = [
        Path(__file__).resolve(),
        ROOT / "deploy/core/Dockerfile",
        ROOT / "platform/api/crashcap_api/config.py",
        ROOT / "platform/worker/crashcap_worker/frozen_core.py",
        ROOT / "platform/worker/crashcap_worker/core_runner.py",
        ROOT / "platform/tests/test_frozen_core.py",
        ROOT / "platform/tests/test_frozen_core_real.py",
        OUT / "native-source/progress.json",
    ]
    evidence["files"] = {
        p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in paths
        if p.is_file()
    }
    receipt.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {"status": evidence["status"], "receipt": str(receipt), "error": evidence.get("error")}
        )
    )
    raise SystemExit(0 if evidence["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
