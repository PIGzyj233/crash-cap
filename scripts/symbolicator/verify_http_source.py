"""Verify the pinned Symbolicator against an isolated internal HTTP Unified source."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASE_COMPOSE = ROOT / "deploy" / "compose" / "symbolicator.yml"
OVERLAY_COMPOSE = ROOT / "deploy" / "compose" / "symbolicator-http-source-spike.yml"
REQUEST_FIXTURE = ROOT / "tests" / "symbolicator" / "http-source-request.json"
PROJECT = "crash-cap-symbolicator-http-spike"
BASE_URL = "http://127.0.0.1:3021"
SYMBOLICATOR_IMAGE = (
    "ghcr.io/getsentry/symbolicator@"
    "sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959"
)
SOURCE_REQUEST_RE = re.compile(r'"(GET|HEAD) ([^ ]+) HTTP/[0-9.]+"')


def run(*args: str, check: bool = True) -> str:
    process = subprocess.run(  # noqa: S603 - arguments are fixed local Docker commands
        args, cwd=ROOT, text=True, capture_output=True, check=False
    )
    if check and process.returncode:
        raise RuntimeError(
            f"command failed ({process.returncode}): {' '.join(args)}\n"
            f"stdout:\n{process.stdout}\nstderr:\n{process.stderr}"
        )
    return process.stdout.strip()


def compose(*args: str, check: bool = True) -> str:
    return run(
        "docker",
        "compose",
        "-p",
        PROJECT,
        "-f",
        str(BASE_COMPOSE),
        "-f",
        str(OVERLAY_COMPOSE),
        *args,
        check=check,
    )


def request(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if data is None else {"Content-Type": "application/json"}
    operation = urllib.request.Request(  # noqa: S310 - URL is fixed to loopback above
        BASE_URL + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(  # noqa: S310 - URL is fixed to loopback above
            operation, timeout=45
        ) as response:
            body = response.read()
            return response.status, _decode_response(body)
    except urllib.error.HTTPError as error:
        body = error.read()
        return error.code, _decode_response(body)


def _decode_response(body: bytes) -> Any:
    if not body:
        return None
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return body.decode("utf-8", "replace")


def wait_ready() -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            status, _body = request("GET", "/healthcheck")
            if status == 200:
                return
        except OSError:
            pass
        time.sleep(1)
    raise RuntimeError("HTTP-source spike gateway did not become ready")


def symbolicate(payload: dict[str, Any]) -> dict[str, Any]:
    endpoint = "/symbolicate?scope=wsp_p0test&inventory=0&timeout=30"
    for _post in range(3):
        status, body = request("POST", endpoint, payload)
        if status != 200 or not isinstance(body, dict):
            raise RuntimeError(f"symbolication POST failed: {status}: {body!r}")
        if body.get("status") != "pending":
            return body
        request_id = str(body.get("request_id") or body.get("id") or "").removeprefix(
            "/requests/"
        )
        if not request_id:
            raise RuntimeError("pending Symbolicator response omitted request id")
        for _poll in range(120):
            poll_status, poll_body = request("GET", f"/requests/{request_id}")
            if poll_status == 404:
                break
            if poll_status != 200 or not isinstance(poll_body, dict):
                raise RuntimeError(f"symbolication poll failed: {poll_status}: {poll_body!r}")
            if poll_body.get("status") != "pending":
                return poll_body
            time.sleep(0.25)
    raise RuntimeError("Symbolicator HTTP-source request did not complete")


def source_requests() -> list[dict[str, str]]:
    logs = compose("logs", "--no-color", "symbol-http-source")
    return [
        {"method": match.group(1), "path": match.group(2)}
        for match in SOURCE_REQUEST_RE.finditer(logs)
    ]


def business_frames(response: dict[str, Any]) -> list[dict[str, Any]]:
    traces = response.get("stacktraces")
    if not isinstance(traces, list) or not traces:
        return []
    frames = traces[0].get("frames") if isinstance(traces[0], dict) else None
    if not isinstance(frames, list):
        return []
    return [
        {
            "function": frame.get("function"),
            "filename": frame.get("filename"),
            "lineno": frame.get("lineno"),
            "status": frame.get("status"),
        }
        for frame in frames
        if isinstance(frame, dict)
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="optional JSON evidence output")
    parser.add_argument("--keep", action="store_true", help="leave the isolated stack running")
    args = parser.parse_args()

    payload = json.loads(REQUEST_FIXTURE.read_text(encoding="utf-8"))
    # This project name is dedicated to the spike. Removing only its own resources
    # guarantees that the first request exercises an empty downloaded/derived cache.
    compose("down", "--volumes", "--remove-orphans", check=False)
    compose("up", "-d", "--build")
    try:
        wait_ready()
        version = compose("exec", "-T", "symbolicator", "/bin/symbolicator", "--version")
        container_id = compose("ps", "-q", "symbolicator")
        image_id = run("docker", "inspect", "--format", "{{.Image}}", container_id)

        cold_started = time.monotonic()
        cold = symbolicate(payload)
        cold_seconds = time.monotonic() - cold_started
        cold_requests = source_requests()

        hot_started = time.monotonic()
        hot = symbolicate(payload)
        hot_seconds = time.monotonic() - hot_started
        after_hot_requests = source_requests()
        additional_hot_requests = after_hot_requests[len(cold_requests) :]

        cold_frames = business_frames(cold)
        hot_frames = business_frames(hot)
        functions = [str(frame.get("function") or "") for frame in cold_frames]
        if cold.get("status") != "completed" or hot.get("status") != "completed":
            raise RuntimeError("cold/hot HTTP-source symbolication did not complete")
        if not any("trigger_null_read" in name for name in functions):
            raise RuntimeError("HTTP source did not resolve the target business function")
        if cold_frames != hot_frames:
            raise RuntimeError("cold and hot HTTP-source semantic frames differ")
        if not cold_requests:
            raise RuntimeError("cold request did not reach the HTTP Unified source")
        if additional_hot_requests:
            raise RuntimeError("hot request unexpectedly refetched the HTTP source")

        evidence = {
            "schema_version": "symbolicator-http-source-spike-v1",
            "status": "PASS",
            "scope": "isolated local Docker Desktop spike; not target intranet UAT",
            "symbolicator_version": version.splitlines(),
            "configured_image": SYMBOLICATOR_IMAGE,
            "running_image_id": image_id,
            "source": {"type": "http", "layout": "unified", "workspace": "wsp_p0test"},
            "cold": {
                "seconds": round(cold_seconds, 6),
                "source_requests": cold_requests,
                "business_frames": cold_frames,
            },
            "hot": {
                "seconds": round(hot_seconds, 6),
                "additional_source_requests": additional_hot_requests,
                "business_frames": hot_frames,
            },
            "not_proven": [
                "Crash-Cap database-backed zstd symbol source in Compose",
                "real lightstreamer DMP equivalence",
                "target intranet network and cache performance",
            ],
        }
        rendered = json.dumps(evidence, indent=2, sort_keys=True)
        print(rendered)
        if args.output:
            output = args.output if args.output.is_absolute() else ROOT / args.output
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(rendered + "\n", encoding="utf-8")
    finally:
        if not args.keep:
            compose("down", "--volumes", "--remove-orphans", check=False)


if __name__ == "__main__":
    main()
