"""Own a disposable pinned service and exercise the actual native Core chain."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.request
import uuid
from datetime import UTC, datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

from protocol import normalize_identity, pair_id
from qualify_sources import IMAGE, SourceHandler, sha

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "target/qa-symbol-import/native-source"


class NativeSourceServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        # Docker Desktop reaches this fixture-only server through host.docker.internal.
        super().__init__(("0.0.0.0", 0), SourceHandler)  # noqa: S104
        self.routes = {}
        self.events = []
        self.modes = {}
        self.failure_overrides = {}


def run(args, *, env=None, timeout=240):
    # Callers below construct fixed argv; there is no shell or user command text.
    result = subprocess.run(  # noqa: S603
        args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError(
            f"command failed ({result.returncode}): {args!r}\n{result.stdout}\n{result.stderr}"
        )
    return result.stdout


def lane(name, args, *, env=None):
    result = subprocess.run(  # noqa: S603
        args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300
    )
    (OUT / name).write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"native lane failed: {name}")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ownership = uuid.uuid4().hex
    container = None
    server = None
    evidence = {
        "status": "NOT_PROVEN",
        "recorded_at": datetime.now(UTC).isoformat(),
        "scope": (
            "isolated native Core source/assembly qualification; no product DB or Current writes"
        ),
        "image": IMAGE,
        "ownership": ownership,
    }
    try:
        run(["docker", "info", "--format", "{{.ServerVersion}}"])
        lane(
            "prepare.log",
            [
                "cargo",
                "test",
                "-p",
                "dmp-core",
                "--locked",
                "--test",
                "canonical_v11",
                "--test",
                "frozen_unwind",
                "--test",
                "frozen_context",
                "--",
                "--ignored",
            ],
        )
        fixture = ROOT / "fixtures/p0-b01-null-read/generated"
        pe, pdb = (
            (fixture / "null_read_target.exe").read_bytes(),
            (fixture / "null_read_target.pdb").read_bytes(),
        )
        core = ROOT / "target/debug" / ("dmp-core.exe" if os.name == "nt" else "dmp-core")
        identities = {}
        for kind, name in (("pe", "null_read_target.exe"), ("pdb", "null_read_target.pdb")):
            identities[kind] = json.loads(
                run(
                    [
                        str(core),
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
        pe_identity, pdb_identity = (normalize_identity(identities[k]) for k in ("pe", "pdb"))
        if pe_identity["debug_id"] != pdb_identity["debug_id"] or pe_identity["debug_id"] is None:
            raise RuntimeError("fixture PE/PDB actual Debug IDs disagree")
        key = pair_id(sha(pe), sha(pdb))
        debug = pe_identity["debug_id"]
        server = NativeSourceServer()
        server.modes.update({"native-missing": 404, "native-unavailable": 503})
        server.routes[f"/{key}/{debug[:2]}/{debug[2:]}/executable"] = pe
        server.routes[f"/{key}/{debug[:2]}/{debug[2:]}/debuginfo"] = pdb
        threading.Thread(target=server.serve_forever, daemon=True).start()
        config = OUT / "symbolicator-config.yml"
        config.write_text(
            "bind: 0.0.0.0:3021\ncache_dir: /data\nconnect_to_reserved_ips: true\n"
            "max_concurrent_requests: 8\nsources: []\n",
            encoding="utf-8",
        )
        container = run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                f"qai-native-{ownership}",
                "--label",
                f"crashcap.qai.owner={ownership}",
                "-p",
                "127.0.0.1::3021",
                "--mount",
                f"type=bind,source={config.resolve().as_posix()},target=/etc/symbolicator/config.yml,readonly",
                "-v",
                "/data",
                IMAGE,
                "run",
                "-c",
                "/etc/symbolicator/config.yml",
            ]
        ).strip()
        evidence["container_id"] = container
        evidence["running_image_id"] = run(
            ["docker", "inspect", "--format", "{{.Image}}", container]
        ).strip()
        port = (
            run(["docker", "port", container, "3021/tcp"]).strip().splitlines()[0].rsplit(":", 1)[1]
        )
        port = int(port)
        if not 1 <= port <= 65535:
            raise RuntimeError("Docker returned an invalid mapped port")
        endpoint = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 45
        while True:
            try:
                # Scheme and loopback host are fixed above; only the port is discovered.
                with urllib.request.urlopen(  # noqa: S310
                    endpoint + "/healthcheck", timeout=3
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.5)
        observed_version = run(
            ["docker", "exec", container, "/bin/symbolicator", "--version"]
        ).strip()
        evidence["observed_version"] = observed_version
        version_line = observed_version.splitlines()[0]
        if not version_line.startswith("symbolicator version: "):
            raise RuntimeError("unexpected Symbolicator version response")
        engine_version = version_line.removeprefix("symbolicator version: ")
        environment = os.environ.copy()
        environment.update(
            {
                "QAI_NATIVE_SOURCE_ENDPOINT": endpoint,
                "QAI_NATIVE_SOURCE_ROOT": f"http://host.docker.internal:{server.server_port}",
                "QAI_NATIVE_SOURCE_VERSION": engine_version,
                "QAI_NATIVE_SOURCE_IMAGE_DIGEST": evidence["running_image_id"],
            }
        )
        lane(
            "live.log",
            [
                "cargo",
                "test",
                "-p",
                "dmp-core",
                "--locked",
                "--test",
                "frozen_source_native",
                "--test",
                "frozen_cli",
                "--",
                "--ignored",
            ],
            env=environment,
        )
        native = json.loads((OUT / "qualification.json").read_text(encoding="utf-8"))
        lane(
            "worker.log",
            [
                "uv",
                "run",
                "--directory",
                str(ROOT / "platform"),
                "pytest",
                "-q",
                "tests/test_frozen_core_real.py",
            ],
            env=environment,
        )
        worker = json.loads((OUT / "worker-qualification.json").read_text(encoding="utf-8"))
        if worker["status"] != "PASS" or worker["run_sha256"] != native["run_sha256"]:
            raise RuntimeError("Worker did not execute the same frozen Run")
        if environment.get("QAI_NATIVE_CORE_IMAGE"):
            docker_worker = json.loads(
                (OUT / "worker-docker-qualification.json").read_text(encoding="utf-8")
            )
            if (
                docker_worker["status"] != "PASS"
                or docker_worker["core_image_digest"] != environment["QAI_NATIVE_CORE_IMAGE_DIGEST"]
            ):
                raise RuntimeError("Docker Worker qualification or engine binding failed")
            evidence["docker_worker"] = docker_worker
        cli = json.loads((OUT / "cli-qualification.json").read_text(encoding="utf-8"))
        if cli["status"] != "PASS" or cli["run_sha256"] != native["run_sha256"]:
            raise RuntimeError("CLI did not execute the same frozen Run")
        if native["status"] != "PASS" or not any(e["status"] == 200 for e in server.events):
            raise RuntimeError("native execution did not prove actual source retrieval")
        for mode, status in (("native-missing", 404), ("native-unavailable", 503)):
            if not any(
                e["path"].startswith(f"/{mode}/") and e["status"] == status
                for e in server.events
            ):
                raise RuntimeError(f"native fault did not reach source: {mode}")
        evidence.update(
            status="PASS",
            native=native,
            cli=cli,
            worker=worker,
            actual_identities=identities,
            pair_id=key,
        )
    except Exception as error:
        evidence.update(status="FAIL", error=f"{type(error).__name__}: {error}")
    finally:
        if server is not None:
            evidence["source_events"] = server.events
            server.shutdown()
            server.server_close()
        if container is not None:
            try:
                owner = run(
                    [
                        "docker",
                        "inspect",
                        "--format",
                        '{{index .Config.Labels "crashcap.qai.owner"}}',
                        container,
                    ]
                ).strip()
                if owner != ownership:
                    raise RuntimeError("refusing cleanup: container ownership changed")
                run(["docker", "rm", "-f", "-v", container])
                evidence["owned_container_and_volume_removed"] = True
            except Exception as error:
                evidence.update(status="FAIL", cleanup_error=f"{type(error).__name__}: {error}")
        paths = [
            Path(__file__).resolve(),
            ROOT / "scripts/qa_symbol_import/qualify_sources.py",
            ROOT / "scripts/qa_symbol_import/protocol.py",
            ROOT / "core/src/frozen_symbolicator.rs",
            ROOT / "core/src/frozen_symbolicator_tests.rs",
            ROOT / "core/src/canonical_v11.rs",
            ROOT / "core/src/frozen_context.rs",
            ROOT / "core/src/frozen_cli.rs",
            ROOT / "platform/worker/crashcap_worker/frozen_core.py",
            ROOT / "platform/api/crashcap_api/config.py",
            ROOT / "platform/tests/test_frozen_core_real.py",
            ROOT / "core/src/cli.rs",
            ROOT / "core/tests/frozen_cli.rs",
            ROOT / "core/tests/frozen_context.rs",
            ROOT / "core/src/canonical.rs",
            ROOT / "core/src/unwind.rs",
            ROOT / "core/tests/frozen_source_native.rs",
        ]
        paths.extend(p for p in OUT.glob("*.json") if p.name != "progress.json")
        paths.extend(OUT.glob("*.log"))
        evidence["files"] = {p.relative_to(ROOT).as_posix(): sha(p.read_bytes()) for p in paths}
        (OUT / "progress.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "error": evidence.get("error"),
                "output": str(OUT / "progress.json"),
            }
        )
    )
    raise SystemExit(0 if evidence["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
