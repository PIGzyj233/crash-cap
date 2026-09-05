"""Execute the real deployer offline; no Docker daemon or host ACLs are touched."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_SCRIPT = ROOT / "scripts/phase1/deploy_linux.sh"
# Every Docker invocation is intercepted. Unknown operations fail closed so a
# new deployer code path cannot accidentally contact a real daemon in tests.
STUB = r"""
import json, os, re, stat, sys
from pathlib import Path
name = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path(os.environ["DEPLOY_TEST_ROOT"])
with (root / "calls.jsonl").open("a") as out:
    out.write(json.dumps({"tool": name, "args": args,
        "env": {key: value for key, value in os.environ.items()
            if key.startswith(("PHASE1_", "CRASHCAP_")) or key in
            ("POSTGRES_USER", "POSTGRES_DB", "DOCKER_SOCKET_PATH", "DOCKER_GID")}}) + "\n")
def fail(message):
    print(message, file=sys.stderr)
    sys.exit(19)
if name == "uname":
    print("Linux" if args == ["-s"] else "x86_64")
elif name == "stat":
    info = Path(args[-1]).stat()
    print({"%a": oct(stat.S_IMODE(info.st_mode))[2:], "%g": str(info.st_gid),
           "%u": str(info.st_uid)}[args[-2]])
elif name == "realpath":
    print(Path(args[-1]).resolve(strict=True))
elif name == "getfacl":
    print("user::rw-\nuser:10001:r--\ngroup::---\nmask::r--\nother::---")
elif name == "setfacl":
    pass
elif name == "curl":
    pass
elif name == "docker":
    if args[0] == "info":
        if "--format" in args:
            print("linux")
    elif args[0] == "context":
        print("unix://" + os.environ["DOCKER_SOCKET_PATH"])
    elif args[:2] == ["volume", "inspect"]:
        sys.exit(1)
    elif args[0] == "build":
        (root / "core-built").write_text(args[args.index("--tag") + 1])
    elif args[:2] == ["image", "inspect"]:
        assert args[-1] == (root / "core-built").read_text()
        print("sha256:" + "a" * 64)
    elif args[0] == "run":
        expected = os.environ.get("CRASHCAP_WORKER_IMAGE", "crash-cap/worker:upload-v3")
        if expected not in args:
            fail("static gate must use the configured worker image: " + expected)
    elif args[0] == "inspect":
        service = args[-1].removeprefix("container-")
        initializers = {"storage-init", "cache-init", "migrate"}
        if "ExitCode" in args[args.index("--format") + 1]:
            print("1" if service == os.environ.get("DEPLOY_TEST_FAIL_INIT") else "0")
        elif "Health" in args[args.index("--format") + 1]:
            print("healthy")
        else:
            print("exited" if service in initializers else "running")
    elif args[0] == "compose":
        values = args[1:]
        env_file = None
        while values and values[0] in ("--project-name", "--file", "--env-file"):
            if values[0] == "--env-file":
                env_file = values[1]
                assert Path(env_file).is_file()
            values = values[2:]
        operation, *options = values
        compose = Path(os.environ["DEPLOY_TEST_COMPOSE"]).read_text()
        section = compose.split("\nservices:\n", 1)[1].split("\nnetworks:\n", 1)[0]
        services = set(re.findall(r"^  ([a-z][a-z0-9-]*):$", section, re.M))
        if operation in ("build", "pull"):
            selected = [option for option in options if not option.startswith("--")]
        elif operation == "run":
            selected = [options[options.index("--entrypoint") + 2]]
        elif operation == "ps":
            selected = [option for option in options if not option.startswith("--")]
        elif operation in ("version", "config", "up", "restart", "logs"):
            selected = []
        else:
            fail("unexpected compose operation: " + operation)
        if set(selected) - services:
            fail("unknown Compose services: " + ", ".join(sorted(set(selected) - services)))
        if operation == "ps" and "--quiet" in options:
            print("container-" + selected[0])
    else:
        fail("unexpected docker operation: " + repr(args))
else:
    fail("unexpected test stub: " + name)
"""


class Deployment:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.state = root / "state"
        self.bin = root / "bin"
        self.bin.mkdir()
        stub = self.bin / "stub"
        stub.write_text(f"#!{sys.executable}\n{STUB}", encoding="utf-8")
        stub.chmod(0o755)
        for command in ("docker", "curl", "uname", "stat", "realpath", "getfacl", "setfacl"):
            (self.bin / command).symlink_to(stub)
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.bind(str(root / "docker.sock"))
        self.env = {
            "PATH": str(self.bin) + os.pathsep + os.environ["PATH"],
            "HOME": str(root),
            "TMPDIR": str(root),
            "DOCKER_SOCKET_PATH": str(root / "docker.sock"),
            "CRASHCAP_DEPLOY_STATE_DIR": str(self.state),
            "DEPLOY_TEST_ROOT": str(root),
            "DEPLOY_TEST_COMPOSE": str(ROOT / "deploy/compose/phase1.yml"),
        }

    def run(self, *args: str, **overrides: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603
            [shutil.which("bash") or "/bin/bash", str(DEPLOY_SCRIPT), *args],
            cwd=self.root,
            env=self.env | overrides,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def calls(self, tool: str = "docker") -> list[dict]:
        return [
            call
            for line in (self.root / "calls.jsonl").read_text().splitlines()
            if (call := json.loads(line))["tool"] == tool
        ]

    def clear_calls(self) -> None:
        (self.root / "calls.jsonl").write_text("")

    def assert_no_credentials(self, result: subprocess.CompletedProcess[str]) -> None:
        output = result.stdout + result.stderr
        for name in (
            "postgres_password",
            "redis_password",
            "rustfs_access_key",
            "rustfs_secret_key",
        ):
            secret = (self.state / name).read_text().strip()
            assert secret not in output


@pytest.fixture
def deployment() -> Iterator[Deployment]:
    # A short, repo-external path also stays below macOS's Unix socket path limit.
    with tempfile.TemporaryDirectory(prefix="cc-deploy-") as directory:
        harness = Deployment(Path(directory))
        try:
            yield harness
        finally:
            harness.socket.close()


def assert_success(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def test_deploy_current_services_and_reuse_state(deployment: Deployment) -> None:
    first = deployment.run()
    assert_success(first)
    assert "Crash-Cap is ready." in first.stdout
    deployment.assert_no_credentials(first)
    assert (deployment.state / "compose.env").stat().st_mode & 0o777 == 0o600
    assert (deployment.state / "runtime.env").stat().st_mode & 0o777 == 0o600
    with (deployment.state / "runtime.env").open("a") as runtime:
        runtime.write("CRASHCAP_LOG_LEVEL=DEBUG\n")
    original = {path.name: path.read_bytes() for path in deployment.state.iterdir()}
    inspected = [call["args"][-1] for call in deployment.calls() if call["args"][0] == "inspect"]
    assert "container-cache-init" in inspected
    assert "container-symbolicator-cleanup" in inspected
    second = deployment.run()
    assert_success(second)
    deployment.assert_no_credentials(second)
    for name, contents in original.items():
        assert (deployment.state / name).read_bytes() == contents


def test_custom_build_options_database_and_compose_reuse(deployment: Deployment) -> None:
    first = deployment.run(
        CRASHCAP_WORKER_IMAGE="local/custom-worker:testing",
        CRASHCAP_CORE_IMAGE="local/custom-core:testing",
        CRASHCAP_BUILD_PULL="0",
        CRASHCAP_BUILD_NO_CACHE="1",
        CRASHCAP_PULL_EXTERNAL_IMAGES="0",
        POSTGRES_USER="operator@tenant",
        POSTGRES_DB="crash reports",
        PHASE1_API_PORT="18080",
    )
    assert_success(first)
    deployment.assert_no_credentials(first)
    password = (deployment.state / "postgres_password").read_text().strip()
    expected = (
        f"postgresql+psycopg://operator%40tenant:{quote(password, safe='')}"
        "@postgres:5432/crash%20reports"
    )
    assert expected in (deployment.state / "runtime.env").read_text()
    commands = [call["args"] for call in deployment.calls()]
    builds = [command for command in commands if "build" in command]
    assert len(builds) == 2
    assert all("--no-cache" in command and "--pull" not in command for command in builds)
    gate = next(command for command in commands if command[0] == "run")
    assert "local/custom-worker:testing" in gate
    assert not any("pull" in command for command in commands)
    deployment.clear_calls()
    followup = deployment.run("--compose", "ps", "--all")
    assert_success(followup)
    commands = deployment.calls()
    assert not any(call["args"][0] in ("build", "run", "volume") for call in commands)
    operation = next(call for call in commands if "ps" in call["args"])
    assert operation["args"][-2:] == ["ps", "--all"]
    assert "--env-file" in operation["args"]
    assert str(deployment.state / "compose.env") in operation["args"]
    assert deployment.calls("getfacl") == []
    deployment.clear_calls()
    second = deployment.run()
    assert_success(second)
    assert "http://127.0.0.1:18080" in second.stdout
    gate = next(call for call in deployment.calls() if call["args"][0] == "run")
    assert "local/custom-worker:testing" in gate["args"]
    assert gate["env"]["CRASHCAP_CORE_IMAGE"] == "local/custom-core:testing"
    assert gate["env"]["POSTGRES_USER"] == "operator@tenant"
    assert gate["env"]["POSTGRES_DB"] == "crash reports"
    assert expected in (deployment.state / "runtime.env").read_text()


@pytest.mark.parametrize("initializer", ["cache-init", "storage-init", "migrate"])
def test_failed_initialization_never_reports_ready(
    deployment: Deployment, initializer: str
) -> None:
    result = deployment.run(DEPLOY_TEST_FAIL_INIT=initializer)
    assert result.returncode != 0
    assert initializer in result.stderr
    assert "Crash-Cap is ready." not in result.stdout
    assert deployment.calls("curl") == []
    deployment.assert_no_credentials(result)
