#!/usr/bin/env python3
"""Run the lightweight Phase 0 checks and aggregate honest outcomes.

The default run is deliberately safe for ordinary CI: no Windows SDK build,
no Docker daemon, no Symbolicator container and no RustFS service are started.
Use ``--run-s3``, ``--run-docker`` or ``--run-windows-fixture`` only from an
explicitly provisioned/manual environment.  Every check reports PASS, FAIL or
SKIP; PARTIAL means the runnable checks passed but an external lane was not run.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[2]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tail(value: str, limit: int = 3000) -> str:
    value = value.strip()
    return value if len(value) <= limit else "..." + value[-limit:]


@dataclass
class CheckResult:
    name: str
    status: str
    command: list[str] = field(default_factory=list)
    duration_ms: int = 0
    returncode: int | None = None
    reason: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    stdout_tail: str = ""
    stderr_tail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "command": self.command,
            "duration_ms": self.duration_ms,
            "returncode": self.returncode,
            "reason": self.reason,
            "details": self.details,
            "stdout_tail": self.stdout_tail,
            "stderr_tail": self.stderr_tail,
        }


def command_text(command: list[str]) -> str:
    return shlex.join(command)


def run_command(
    name: str,
    command: list[str],
    *,
    timeout: int,
    details: dict[str, Any] | None = None,
    parser: Callable[[subprocess.CompletedProcess[str]], tuple[str, str | None, dict[str, Any]]] | None = None,
) -> CheckResult:
    started = time.perf_counter()
    base_details = dict(details or {})
    executable = command[0] if command else ""
    if executable and not Path(executable).is_absolute() and shutil.which(executable) is None:
        return CheckResult(
            name=name,
            status="SKIP",
            command=command,
            duration_ms=int((time.perf_counter() - started) * 1000),
            reason=f"required executable is unavailable: {executable}",
            details=base_details,
        )
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
            env=os.environ.copy(),
        )
    except FileNotFoundError:
        return CheckResult(
            name=name,
            status="SKIP",
            command=command,
            duration_ms=int((time.perf_counter() - started) * 1000),
            reason=f"required executable is unavailable: {executable}",
            details=base_details,
        )
    except subprocess.TimeoutExpired as exc:
        return CheckResult(
            name=name,
            status="FAIL",
            command=command,
            duration_ms=int((time.perf_counter() - started) * 1000),
            returncode=None,
            reason=f"timed out after {timeout}s",
            details=base_details,
            stdout_tail=tail(str(exc.stdout or "")),
            stderr_tail=tail(str(exc.stderr or "")),
        )

    status = "PASS" if completed.returncode == 0 else "FAIL"
    reason = None if status == "PASS" else f"command exited with {completed.returncode}"
    parsed_details = dict(base_details)
    if parser is not None:
        try:
            status, parser_reason, parser_details = parser(completed)
            reason = parser_reason
            parsed_details.update(parser_details)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            status = "FAIL"
            reason = f"could not parse check output: {exc}"
    return CheckResult(
        name=name,
        status=status,
        command=command,
        duration_ms=int((time.perf_counter() - started) * 1000),
        returncode=completed.returncode,
        reason=reason,
        details=parsed_details,
        stdout_tail=tail(completed.stdout),
        stderr_tail=tail(completed.stderr),
    )


def json_output_parser(completed: subprocess.CompletedProcess[str]) -> tuple[str, str | None, dict[str, Any]]:
    payload = json.loads(completed.stdout)
    if completed.returncode != 0:
        return "FAIL", f"check reported {payload.get('status', 'FAIL')}", payload
    if payload.get("status") == "PASS":
        return "PASS", None, payload
    return "FAIL", "check output did not report PASS", payload


def fixture_parser(completed: subprocess.CompletedProcess[str]) -> tuple[str, str | None, dict[str, Any]]:
    payload = json.loads(completed.stdout)
    totals = payload.get("totals", {})
    if completed.returncode != 0 or totals.get("failed", 0):
        return "FAIL", "fixture metadata harness reported a failure", {"harness": payload}
    if totals.get("skipped", 0):
        return "SKIP", "some fixture execution requires Windows-generated artifacts", {"harness": payload}
    return "PASS", None, {"harness": payload}


def golden_parser(completed: subprocess.CompletedProcess[str]) -> tuple[str, str | None, dict[str, Any]]:
    payload = json.loads(completed.stdout)
    status = payload.get("status")
    if status == "SKIP":
        return "SKIP", payload.get("reason"), payload
    return ("PASS", None, payload) if status == "PASS" else ("FAIL", "unexpected Golden runner status", payload)


def add_optional_result(
    results: list[CheckResult],
    name: str,
    command: list[str],
    *,
    enabled: bool,
    reason: str,
    timeout: int,
    parser: Callable[[subprocess.CompletedProcess[str]], tuple[str, str | None, dict[str, Any]]] | None = None,
) -> None:
    if not enabled:
        results.append(CheckResult(name=name, status="SKIP", command=command, reason=reason))
        return
    results.append(run_command(name, command, timeout=timeout, parser=parser))


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 0 QA/OPS Verification",
        "",
        f"- Overall: **{payload['overall_status']}**",
        f"- Required CI checks passed: **{payload['required_ci_checks_passed']}**",
        f"- Started: `{payload['started_at']}`",
        f"- Finished: `{payload['finished_at']}`",
        f"- Phase 0 gate eligible from this run: **{payload['phase0_gate_eligible']}**",
        "",
        "## Checks",
        "",
        "| Check | Status | Duration | Reason |",
        "| --- | --- | ---: | --- |",
    ]
    for check in payload["checks"]:
        reason = check.get("reason") or "-"
        lines.append(f"| `{check['name']}` | **{check['status']}** | {check['duration_ms']} ms | {reason} |")
    failures = [check for check in payload["checks"] if check["status"] == "FAIL"]
    if failures:
        lines.extend(["", "## Failure details", ""])
        for check in failures:
            diagnostic = check.get("stderr_tail") or check.get("stdout_tail") or "no command output"
            lines.extend(
                [
                    f"### `{check['name']}`",
                    "",
                    f"{check.get('reason') or 'check failed'}.",
                    "",
                    "```text",
                    diagnostic[-2000:],
                    "```",
                    "",
                ]
            )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `PASS` means the check was executed and passed in this local run.",
            "- `FAIL` means the check was attempted and failed; it is not downgraded to a skip.",
            "- `SKIP` marks an external or not-yet-wired lane that was intentionally not attempted.",
            "- The default aggregator does not start Windows SDK builds, Docker Compose stacks, RustFS, or Symbolicator containers.",
            "- A successful local aggregator is not evidence that a remote GitHub Actions run completed.",
            "",
            "## Reproduce",
            "",
            "```bash",
            "python scripts/phase0/verify.py --output docs/evidence/ci-phase0-verification.json",
            "```",
            "",
            "Optional/manual lanes:",
            "",
            "```bash",
            "python scripts/phase0/verify.py --run-s3 --run-docker --run-windows-fixture",
            "```",
            "",
            "Evidence JSON: `docs/evidence/ci-phase0-verification.json`",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/evidence/ci-phase0-verification.json"))
    parser.add_argument("--run-s3", action="store_true", help="run the Docker-backed RustFS qualification lane")
    parser.add_argument("--run-docker", action="store_true", help="run the Docker-backed Symbolicator smoke lane")
    parser.add_argument("--run-golden", action="store_true", help="run the full local Core/Symbolicator Golden lane")
    parser.add_argument("--core", default="target/release/dmp-core.exe", help="dmp-core executable for --run-golden")
    parser.add_argument("--symbolicator-url", default="http://127.0.0.1:3021")
    parser.add_argument("--symbolicator-version", default="26.7.2")
    parser.add_argument("--core-image-digest", help="audited sha256 OCI image ID for --run-golden")
    parser.add_argument(
        "--run-windows-fixture",
        action="store_true",
        help="run the Windows SDK fixture generation lane when PowerShell is available",
    )
    args = parser.parse_args()
    output = args.output if args.output.is_absolute() else ROOT / args.output
    started_at = utc_now()
    results: list[CheckResult] = []

    with tempfile.TemporaryDirectory(prefix="crash-cap-phase0-") as temporary:
        temp = Path(temporary)
        results.append(
            run_command(
                "markdown_links",
                [sys.executable, "scripts/ci/check_markdown_links.py", "--root", ".", "--output", str(temp / "links.json")],
                timeout=60,
                parser=json_output_parser,
            )
        )
        results.append(
            run_command(
                "schema_draft_2020_12",
                ["cargo", "test", "-p", "crash-cap-schema-tests"],
                timeout=180,
                details={"validator": "Rust jsonschema::validator_for (Draft 2020-12)"},
            )
        )
        results.append(run_command("cargo_fmt", ["cargo", "fmt", "--all", "--", "--check"], timeout=120))
        results.append(
            run_command(
                "cargo_clippy",
                ["cargo", "clippy", "--workspace", "--all-targets", "--all-features", "--", "-D", "warnings"],
                timeout=240,
            )
        )
        results.append(run_command("cargo_test", ["cargo", "test", "--workspace", "--all-targets"], timeout=240))
        results.append(
            run_command(
                "fixture_metadata_contract",
                [
                    sys.executable,
                    "scripts/fixtures/harness.py",
                    "--metadata-only",
                    "--output",
                    str(temp / "fixtures.json"),
                ],
                timeout=60,
                parser=fixture_parser,
            )
        )
        results.append(
            run_command(
                "symbolicator_gateway_unit",
                [sys.executable, "-m", "unittest", "discover", "-s", "tests/symbolicator", "-p", "test_*.py"],
                timeout=60,
            )
        )
        results.append(
            run_command(
                "s3_adapter_offline",
                [sys.executable, "scripts/ci/test_s3_adapter_offline.py"],
                timeout=60,
            )
        )
        golden_command = [
            sys.executable,
            "scripts/phase0/golden_runner.py",
            "--core",
            args.core,
            "--symbolicator",
            args.symbolicator_url,
            "--version",
            args.symbolicator_version,
            "--output-json",
            str(temp / "golden.json"),
            "--output-md",
            str(temp / "golden.md"),
        ]
        if args.core_image_digest:
            golden_command.extend(["--core-image-digest", args.core_image_digest])
        add_optional_result(
            results,
            "golden_runner",
            golden_command,
            enabled=args.run_golden,
            reason="generated binaries and a running Symbolicator are required; use --run-golden with --core-image-digest",
            timeout=600,
            parser=golden_parser,
        )

        s3_command = ["bash", "qualification/s3/run.sh"]
        add_optional_result(
            results,
            "s3_qualification",
            s3_command,
            enabled=args.run_s3,
            reason="Docker-backed RustFS qualification is an explicit/manual lane; use --run-s3",
            timeout=240,
        )
        docker_command = [sys.executable, "scripts/symbolicator/verify.py", "--output", str(temp / "symbolicator.json")]
        add_optional_result(
            results,
            "symbolicator_container_smoke",
            docker_command,
            enabled=args.run_docker,
            reason="Docker-backed Symbolicator smoke is an explicit/manual lane; use --run-docker",
            timeout=240,
        )
        windows_command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts/fixtures/build_p0_b01.ps1"]
        add_optional_result(
            results,
            "windows_fixture_generation",
            windows_command,
            enabled=args.run_windows_fixture,
            reason="Windows SDK/CDB fixture generation is an explicit/manual lane; use --run-windows-fixture",
            timeout=600,
        )

    failed = [result for result in results if result.status == "FAIL"]
    skipped = [result for result in results if result.status == "SKIP"]
    if failed:
        overall = "FAIL"
    elif skipped:
        overall = "PARTIAL"
    else:
        overall = "PASS"
    required_ci_checks_passed = not failed
    payload = {
        "schema_version": "phase0-qa-ops-verification-v0.1",
        "overall_status": overall,
        "required_ci_checks_passed": required_ci_checks_passed,
        "phase0_gate_eligible": overall == "PASS",
        "started_at": started_at,
        "finished_at": utc_now(),
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "root": str(ROOT),
        },
        "checks": [result.as_dict() for result in results],
        "summary": {
            "total": len(results),
            "pass": sum(result.status == "PASS" for result in results),
            "fail": len(failed),
            "skip": len(skipped),
        },
        "remote_ci_executed": False,
        "notes": [
            "This is a local verification aggregation; it does not assert that a remote CI workflow ran.",
            "The full Golden lane is opt-in because generated binaries are intentionally excluded from source control.",
            "RustFS and Symbolicator container checks remain explicit/manual to keep default CI lightweight and privilege-safe.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    markdown = output.with_suffix(".md")
    markdown.write_text(render_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # A default CI run is intentionally PARTIAL because Docker and Windows
    # lanes are opt-in.  Those explicit skips must not make the lightweight
    # regression job fail; an attempted check that fails still returns 1.
    return 0 if required_ci_checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
