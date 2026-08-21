"""Start and verify the pinned Phase 0 Symbolicator deployment."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "deploy" / "compose" / "symbolicator.yml"
BASE_URL = "http://127.0.0.1:3021"


def run(*args: str) -> str:
    process = subprocess.run(args, cwd=ROOT, text=True, capture_output=True, check=False)
    if process.returncode:
        raise RuntimeError(
            f"command failed ({process.returncode}): {' '.join(args)}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return process.stdout.strip()


def request(path: str, payload: dict | None = None) -> tuple[int, bytes]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if data is None else {"Content-Type": "application/json"}
    req = urllib.request.Request(BASE_URL + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="optional JSON evidence output")
    parser.add_argument("--keep", action="store_true", help="leave the Compose stack running")
    args = parser.parse_args()

    compose = ("docker", "compose", "-f", str(COMPOSE_FILE))
    # Compose 5.3.0 on Docker Desktop 4.80 can lose the container ID while
    # `--wait` observes a dependency-driven recreate. Start deterministically
    # and use the HTTP readiness loop below as the authoritative wait instead.
    run(*compose, "up", "-d", "--build")
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                health_status, health_body = request("/healthcheck")
                if health_status == 200:
                    break
            except OSError:
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError("gateway healthcheck did not become ready")
            time.sleep(1)

        version = run(*compose, "exec", "-T", "symbolicator", "/bin/symbolicator", "--version")
        container_id = run(*compose, "ps", "-q", "symbolicator")
        image_id = run("docker", "inspect", "--format", "{{.Image}}", container_id)

        forbidden_status, forbidden_body = request(
            "/symbolicate?scope=wsp_p0test&timeout=1",
            {
                "platform": "native",
                "stacktraces": [],
                "modules": [],
                "sources": [
                    {"type": "http", "id": "untrusted", "url": "https://example.invalid/symbols"}
                ],
            },
        )
        forbidden = json.loads(forbidden_body)
        if forbidden_status != 400 or forbidden.get("error", {}).get("code") != "REQUEST_SOURCES_FORBIDDEN":
            raise RuntimeError("request-owned symbol source was not rejected")

        allowed_status, allowed_body = request(
            "/symbolicate?scope=wsp_p0test&timeout=5",
            {
                "platform": "native",
                "stacktraces": [],
                "modules": [],
                "options": {"dif_candidates": True, "apply_source_context": False},
            },
        )
        if allowed_status != 200:
            raise RuntimeError(f"symbolication smoke request failed: {allowed_status}: {allowed_body!r}")

        evidence = {
            "symbolicator_version": version.splitlines(),
            "configured_image": "ghcr.io/getsentry/symbolicator@sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959",
            "running_image_id": image_id,
            "healthcheck": {"status": health_status, "body": health_body.decode("utf-8", "replace")},
            "request_source_policy": {
                "status": forbidden_status,
                "error_code": forbidden["error"]["code"],
            },
            "empty_symbolication_smoke": {
                "status": allowed_status,
                "response": json.loads(allowed_body),
            },
        }
        rendered = json.dumps(evidence, indent=2, sort_keys=True)
        print(rendered)
        if args.output:
            output = args.output if args.output.is_absolute() else ROOT / args.output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
    finally:
        if not args.keep:
            run(*compose, "down")


if __name__ == "__main__":
    main()
