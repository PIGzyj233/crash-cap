#!/usr/bin/env python3
"""Build and smoke-test the P0-A04 dmp-core OCI image.

The script is deliberately Docker-CLI based so the same checks can be run by
an engineer on Docker Desktop or by a Linux CI runner.  It never receives or
prints credentials; the only host bind mount is a generated, minimal MDMP
fixture used by the inspect smoke test.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shlex
import struct
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "deploy" / "core" / "Dockerfile"
DEFAULT_IMAGE = "crash-cap/dmp-core:p0-a04"
MEMORY_LIMIT_BYTES = 512 * 1024 * 1024
PIDS_LIMIT = 64
NANO_CPUS = 1_000_000_000


def sandbox_args() -> list[str]:
    return [
        "--read-only",
        "--memory",
        str(MEMORY_LIMIT_BYTES),
        "--memory-swap",
        str(MEMORY_LIMIT_BYTES),
        "--pids-limit",
        str(PIDS_LIMIT),
        "--cpus",
        "1",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=16m",
        "--network",
        "none",
    ]
JSON_EVIDENCE = ROOT / "docs" / "evidence" / "core-oci.json"
MARKDOWN_EVIDENCE = ROOT / "docs" / "evidence" / "core-oci.md"
PINNED_DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def command_text(argv: list[str]) -> str:
    return shlex.join(argv)


def run_command(argv: list[str], *, cwd: Path = ROOT) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return {
            "command": command_text(argv),
            "argv": argv,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except OSError as error:
        return {
            "command": command_text(argv),
            "argv": argv,
            "exit_code": 127,
            "stdout": "",
            "stderr": f"{type(error).__name__}: {error}",
        }


def tail(value: str, limit: int = 2400) -> str:
    return value if len(value) <= limit else value[-limit:]


def result_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "command": result["command"],
        "exit_code": result["exit_code"],
        "stdout_tail": tail(result["stdout"]),
        "stderr_tail": tail(result["stderr"]),
    }


def json_from_stdout(result: dict[str, Any]) -> Any | None:
    try:
        return json.loads(result["stdout"])
    except (TypeError, json.JSONDecodeError):
        return None


def put_u16(buffer: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<H", buffer, offset, value)


def put_u32(buffer: bytearray, offset: int, value: int) -> None:
    struct.pack_into("<I", buffer, offset, value)


def minimal_x64_dump() -> bytes:
    """Return the smallest valid x64 MDMP accepted by dmp-core inspect."""

    directory_rva = 32
    system_rva = 44
    data = bytearray(system_rva + 56)
    put_u32(data, 0, 0x504D444D)  # MDMP
    put_u32(data, 8, 1)  # NumberOfStreams
    put_u32(data, 12, directory_rva)
    put_u32(data, directory_rva, 7)  # SystemInfoStream
    put_u32(data, directory_rva + 4, 56)
    put_u32(data, directory_rva + 8, system_rva)
    put_u16(data, system_rva, 9)  # PROCESSOR_ARCHITECTURE_AMD64
    data[system_rva + 6] = 1
    put_u32(data, system_rva + 8, 10)
    put_u32(data, system_rva + 16, 22631)
    put_u32(data, system_rva + 20, 2)
    return bytes(data)


def base_image_references() -> list[dict[str, str]]:
    references: list[dict[str, str]] = []
    for line in DOCKERFILE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^FROM\s+([^\s]+)(?:\s+AS\s+(\S+))?", line, re.IGNORECASE)
        if not match:
            continue
        reference = match.group(1)
        stage = match.group(2) or "runtime"
        digest = reference.rsplit("@", 1)[-1] if "@" in reference else ""
        references.append({"stage": stage, "reference": reference, "digest": digest})
    return references


def inspect_base_images(references: list[dict[str, str]]) -> None:
    for image in references:
        result = run_command(["docker", "image", "inspect", image["reference"]])
        image["inspect"] = result_summary(result)
        value = json_from_stdout(result)
        if not isinstance(value, list) or not value or not isinstance(value[0], dict):
            image["status"] = "FAIL"
            continue
        metadata = value[0]
        image["status"] = "PASS" if PINNED_DIGEST.search(image["reference"]) else "FAIL"
        image["source"] = image["reference"].split("@", 1)[0]
        image["local_id"] = str(metadata.get("Id", ""))
        image["os"] = str(metadata.get("Os", ""))
        image["architecture"] = str(metadata.get("Architecture", ""))
        image["repo_digests"] = metadata.get("RepoDigests", [])


def inspect_runtime(image: str) -> tuple[dict[str, Any], dict[str, Any]]:
    result = run_command(["docker", "image", "inspect", image])
    summary = result_summary(result)
    value = json_from_stdout(result)
    if not isinstance(value, list) or not value or not isinstance(value[0], dict):
        return summary, {"status": "FAIL", "reason": "docker image inspect returned no image"}

    metadata = value[0]
    config = metadata.get("Config") or {}
    runtime_user = str(config.get("User", ""))
    image_id = str(metadata.get("Id", ""))
    repo_digests = metadata.get("RepoDigests") or []
    runtime = {
        "status": "PASS" if image_id and runtime_user not in {"", "0", "root", "0:0"} else "FAIL",
        "local_image_id": image_id,
        "repo_digests": repo_digests,
        "os": metadata.get("Os"),
        "architecture": metadata.get("Architecture"),
        "user": runtime_user,
        "entrypoint": config.get("Entrypoint"),
        "cmd": config.get("Cmd"),
        "rootfs_layer_count": len((metadata.get("RootFS") or {}).get("Layers") or []),
    }
    return summary, runtime


def inspect_exported_runtime(image: str, temp_dir: Path) -> dict[str, Any]:
    created = run_command(["docker", "create", image, "version"])
    container_id = created["stdout"].strip()
    report: dict[str, Any] = {"create": result_summary(created)}
    if created["exit_code"] != 0 or not container_id:
        report.update({"status": "FAIL", "reason": "unable to create image container"})
        return report

    archive = temp_dir / "runtime.tar"
    try:
        exported = run_command(["docker", "export", "--output", str(archive), container_id])
        report["export"] = result_summary(exported)
        if exported["exit_code"] != 0 or not archive.is_file():
            report.update({"status": "FAIL", "reason": "unable to export runtime filesystem"})
            return report
        with tarfile.open(archive, "r") as handle:
            names = sorted(member.name.lstrip("./") for member in handle.getmembers())
        required = "usr/local/bin/dmp-core"
        forbidden_prefixes = (
            "src/",
            "workspace/",
            "target/",
            "usr/local/cargo/",
            "root/.cargo/",
        )
        forbidden = [
            name
            for name in names
            if name == "usr/bin/cargo"
            or name == "usr/bin/rustc"
            or name.startswith(forbidden_prefixes)
        ]
        report.update(
            {
                "status": "PASS" if required in names and not forbidden else "FAIL",
                "file_count": len(names),
                "required_binary": required,
                "required_binary_present": required in names,
                "forbidden_build_files": forbidden[:50],
                "top_level_entries": sorted({name.split("/", 1)[0] for name in names})[:50],
            }
        )
        return report
    except (OSError, tarfile.TarError) as error:
        report.update({"status": "FAIL", "reason": f"runtime archive inspection failed: {error}"})
        return report
    finally:
        run_command(["docker", "rm", "--force", container_id])


def readonly_create_inspection(image: str, user: str, platform: str) -> dict[str, Any]:
    user_arg = user if ":" in user else f"{user}:{user}" if user.isdigit() else user
    created = run_command(
        [
            "docker",
            "create",
            "--platform",
            platform,
            *sandbox_args(),
            "--user",
            user_arg,
            image,
            "version",
        ]
    )
    report: dict[str, Any] = {"create": result_summary(created)}
    container_id = created["stdout"].strip()
    if created["exit_code"] != 0 or not container_id:
        report.update({"status": "FAIL", "reason": "unable to create read-only smoke container"})
        return report
    try:
        inspected = run_command(["docker", "inspect", container_id])
        value = json_from_stdout(inspected)
        host_config = value[0].get("HostConfig", {}) if isinstance(value, list) and value else {}
        readonly = bool(host_config.get("ReadonlyRootfs"))
        memory = int(host_config.get("Memory") or 0)
        memory_swap = int(host_config.get("MemorySwap") or 0)
        pids_limit = int(host_config.get("PidsLimit") or 0)
        nano_cpus = int(host_config.get("NanoCpus") or 0)
        network_mode = str(host_config.get("NetworkMode") or "")
        tmpfs = host_config.get("Tmpfs") or {}
        limits_ok = (
            memory == MEMORY_LIMIT_BYTES
            and memory_swap == MEMORY_LIMIT_BYTES
            and pids_limit == PIDS_LIMIT
            and nano_cpus == NANO_CPUS
            and network_mode == "none"
            and "/tmp" in tmpfs
        )
        report["inspect"] = result_summary(inspected)
        report["readonly_rootfs"] = readonly
        report["resource_limits"] = {
            "memory_bytes": memory,
            "memory_swap_bytes": memory_swap,
            "pids_limit": pids_limit,
            "nano_cpus": nano_cpus,
            "network_mode": network_mode,
            "tmpfs": tmpfs,
        }
        report["status"] = "PASS" if readonly and limits_ok else "FAIL"
        return report
    finally:
        run_command(["docker", "rm", "--force", container_id])


def smoke_version(image: str, user: str, platform: str) -> dict[str, Any]:
    user_arg = user if ":" in user else f"{user}:{user}" if user.isdigit() else user
    result = run_command(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            platform,
            *sandbox_args(),
            "--user",
            user_arg,
            image,
            "version",
        ]
    )
    return {"status": "PASS" if result["exit_code"] == 0 else "FAIL", **result_summary(result)}


def smoke_inspect(image: str, user: str, platform: str, dump: Path) -> dict[str, Any]:
    user_arg = user if ":" in user else f"{user}:{user}" if user.isdigit() else user
    result = run_command(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            platform,
            *sandbox_args(),
            "--user",
            user_arg,
            "--mount",
            f"type=bind,source={dump},target=/input.dmp,readonly",
            image,
            "inspect",
            "--dump",
            "/input.dmp",
            "--output",
            "-",
        ]
    )
    parsed = json_from_stdout(result)
    report: dict[str, Any] = {
        "status": "PASS" if result["exit_code"] == 0 and isinstance(parsed, dict) else "FAIL",
        **result_summary(result),
        "parsed_json": parsed,
    }
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# P0-A04 Core OCI evidence",
        "",
        f"- Overall status: **{report['status']}**",
        f"- Checked (UTC): `{report['checked_at_utc']}`",
        f"- Image: `{report['image']}`",
        f"- Remote CI executed: **no** (local Docker CLI only)",
        "",
        "## Base images",
        "",
        "| Stage | Pinned reference | OS/arch | Local ID | Status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in report.get("base_images", []):
        lines.append(
            f"| `{item.get('stage', '')}` | `{item.get('reference', '')}` | "
            f"`{item.get('os', '?')}/{item.get('architecture', '?')}` | "
            f"`{item.get('local_id', '?')}` | {item.get('status', 'FAIL')} |"
        )
    lines += [
        "",
        "## Build and image identity",
        "",
        f"- Build status: **{report['build']['status']}**",
        f"- Build command: `{report['build']['command']}`",
        f"- Local image ID: `{report.get('runtime', {}).get('local_image_id', 'not available')}`",
        f"- Runtime user: `{report.get('runtime', {}).get('user', 'not available')}`",
        f"- Runtime filesystem check: **{report.get('runtime_files', {}).get('status', 'SKIP')}**",
        f"- Runtime files: `{report.get('runtime_files', {}).get('file_count', 'not available')}`; "
        f"required binary present: `{report.get('runtime_files', {}).get('required_binary_present', 'not available')}`",
        "",
        "## Smoke checks",
        "",
        f"- Read-only root configuration: **{report.get('readonly_rootfs', {}).get('status', 'SKIP')}**",
        f"- Runtime limits: `{report.get('readonly_rootfs', {}).get('resource_limits', {})}`",
        f"- `dmp-core version` in read-only container: **{report.get('version_smoke', {}).get('status', 'SKIP')}**",
        f"- `dmp-core inspect` in read-only container: **{report.get('inspect_smoke', {}).get('status', 'SKIP')}**",
        "",
        "Exact command/output tails and the parsed inspect JSON are kept in `core-oci.json`.",
        "",
        "## Boundary",
        "",
        "This is a local Docker Desktop verification. It does not prove Windows DMP generation, "
        "remote CI execution, production registry provenance, or a full Symbolicator analysis.",
        "",
    ]
    return "\n".join(lines)


def write_evidence(report: dict[str, Any]) -> None:
    JSON_EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    JSON_EVIDENCE.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    MARKDOWN_EVIDENCE.write_text(render_markdown(report), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default=DEFAULT_IMAGE)
    parser.add_argument("--platform", default="linux/amd64")
    parser.add_argument("--no-build", action="store_true", help="reuse an existing local image")
    args = parser.parse_args()

    report: dict[str, Any] = {
        "schema_version": "core-oci-evidence-v0",
        "checked_at_utc": utc_now(),
        "image": args.image,
        "platform": args.platform,
        "dockerfile": str(DOCKERFILE.relative_to(ROOT)).replace("\\", "/"),
        "status": "FAIL",
    }
    references = base_image_references()
    report["base_images"] = references
    missing_pins = [item["reference"] for item in references if not PINNED_DIGEST.search(item["reference"])]
    if missing_pins:
        report["build"] = {
            "status": "FAIL",
            "command": "not run",
            "exit_code": 2,
            "stdout_tail": "",
            "stderr_tail": f"base image references are not digest-pinned: {missing_pins}",
        }
        write_evidence(report)
        return 1

    inspect_base_images(references)
    if any(item.get("status") != "PASS" for item in references):
        report["build"] = {
            "status": "FAIL",
            "command": "docker image inspect <pinned base images>",
            "exit_code": 1,
            "stdout_tail": "",
            "stderr_tail": "one or more pinned base images are unavailable locally",
        }
        write_evidence(report)
        return 1

    if args.no_build:
        build = {
            "status": "SKIP",
            "command": "not run (--no-build)",
            "exit_code": 0,
            "stdout_tail": "",
            "stderr_tail": "",
        }
    else:
        build_result = run_command(
            [
                "docker",
                "build",
                "--pull",
                "--platform",
                args.platform,
                "--file",
                str(DOCKERFILE),
                "--tag",
                args.image,
                ".",
            ]
        )
        build = {"status": "PASS" if build_result["exit_code"] == 0 else "FAIL", **result_summary(build_result)}
    report["build"] = build

    if build["status"] == "FAIL":
        write_evidence(report)
        return 1

    inspect_result, runtime = inspect_runtime(args.image)
    report["image_inspect"] = inspect_result
    report["runtime"] = runtime
    if runtime.get("status") != "PASS":
        report["status"] = "FAIL"
        write_evidence(report)
        return 1

    with tempfile.TemporaryDirectory(prefix="crash-cap-core-oci-") as temp_name:
        temp_dir = Path(temp_name)
        dump = temp_dir / "minimal-x64.dmp"
        dump.write_bytes(minimal_x64_dump())
        report["runtime_files"] = inspect_exported_runtime(args.image, temp_dir)
        user = str(runtime["user"])
        report["readonly_rootfs"] = readonly_create_inspection(args.image, user, args.platform)
        report["version_smoke"] = smoke_version(args.image, user, args.platform)
        report["inspect_smoke"] = smoke_inspect(args.image, user, args.platform, dump)

    checks = [
        report["runtime_files"].get("status"),
        report["readonly_rootfs"].get("status"),
        report["version_smoke"].get("status"),
        report["inspect_smoke"].get("status"),
    ]
    report["status"] = "PASS" if all(value == "PASS" for value in checks) else "FAIL"
    write_evidence(report)
    print(json.dumps({"status": report["status"], "json": str(JSON_EVIDENCE)}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
