"""Real pinned-Symbolicator qualification in a disposable, loopback-only stack.

Never connects to the product database or gateway. The diagnostic HTTP source is
local to this experiment. A result is FAIL/NOT_PROVEN unless every assertion ran.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import platform
import subprocess
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from protocol import pair_id
from source_diagnostics import source_outcomes

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "ghcr.io/getsentry/symbolicator@sha256:9709445e143059f35812a3999370e2354e3a99ef194068ffa4f87bbd491cb959"
PROJECT = "crash-cap-qai-source-qualification"
BASE_URL = "http://127.0.0.1:3031"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def run(args, *, check=True):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=180)
    if check and result.returncode:
        raise RuntimeError(f"command {args!r} failed: {result.stderr}")
    return result


def request(method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE_URL + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        body = response.read()
    if path == "/healthcheck":
        return {"status": "healthy"}
    return json.loads(body) if body else {}


def symbolicate(payload):
    body = request("POST", "/symbolicate?timeout=30", payload)
    deadline = time.monotonic() + 90
    while body.get("status") == "pending" and time.monotonic() < deadline:
        time.sleep(0.25)
        body = request("GET", "/requests/" + body["request_id"])
    if body.get("status") != "completed":
        raise RuntimeError(f"not completed: {body}")
    return body


def functions(result):
    return [
        frame.get("function", "")
        for stack in result.get("stacktraces", [])
        for frame in stack.get("frames", [])
    ]


def source(source_id, prefix):
    return {
        "id": source_id,
        "type": "http",
        "url": f"http://host.docker.internal:3032/{prefix}/",
        "layout": {"type": "unified", "casing": "lowercase"},
        "filters": {"filetypes": ["pe", "pdb"]},
        "is_public": False,
    }


class SourceServer(ThreadingHTTPServer):
    request_queue_size = 1024
    daemon_threads = True

    def __init__(self):
        super().__init__(("0.0.0.0", 3032), SourceHandler)
        self.routes = {}
        self.events = []
        self.modes = {}
        self.failure_overrides = {}


class SourceHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        prefix = self.path.strip("/").split("/")[0]
        status = self.server.modes.get(prefix, 200)
        body = self.server.routes.get(self.path)
        if status == 200 and body is None:
            status = 404
        content = body if status == 200 else b""
        self.server.events.append(
            {
                "path": self.path,
                "status": status,
                "sha256": sha(content) if content else None,
                "failure_class": self.server.failure_overrides.get(prefix, {}).get(
                    "failure_class",
                    "none"
                    if status == 200
                    else "transient"
                    if status == 503
                    else "permanent"
                    if status == 404
                    else "unknown",
                ),
                "reason": self.server.failure_overrides.get(prefix, {}).get(
                    "reason",
                    "downloaded"
                    if status == 200
                    else "upstream_unavailable"
                    if status == 503
                    else "source_missing"
                    if status == 404
                    else "unclassified_failure",
                ),
            }
        )
        self.send_response(status)
        self.send_header("Content-Length", str(len(content or b"")))
        self.end_headers()
        self.wfile.write(content or b"")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "target/qa-symbol-import/source-qualification.json",
    )
    parser.add_argument("--source-counts", default="1,16,64,200")
    parser.add_argument("--partition-count", type=int, default=0)
    parser.add_argument("--diagnostic-extended", action="store_true")
    parser.add_argument(
        "--core",
        type=Path,
        default=ROOT
        / "target/debug"
        / ("dmp-core.exe" if platform.system() == "Windows" else "dmp-core"),
    )
    args = parser.parse_args()
    try:
        counts = [int(n) for n in args.source_counts.split(",")]
    except ValueError:
        parser.error("source counts must be comma-separated integers")
    if not counts or any(n < 1 or n > 200 for n in counts):
        parser.error("source counts must be between 1 and 200")
    if args.partition_count not in (0, 2) and not 3 <= args.partition_count <= 200:
        parser.error("partition count must be zero or between 2 and 200")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    evidence = {
        "schema_version": "qai-source-qualification-v1",
        "status": "NOT_PROVEN",
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "head": run(["git", "rev-parse", "HEAD"]).stdout.strip(),
        "script_sha256": sha(Path(__file__).read_bytes()),
        "protocol_sha256": sha((Path(__file__).parent / "protocol.py").read_bytes()),
        "diagnostic_adapter_sha256": sha(
            (Path(__file__).parent / "source_diagnostics.py").read_bytes()
        ),
        "core_binary_sha256": sha(args.core.read_bytes()),
        "source_counts": counts,
        "partition_count": args.partition_count,
        "image": IMAGE,
        "environment": "isolated local Docker; no product catalog, unwind integration, remote CI or target proof",
        "cases": [],
        "raw_results": {},
    }
    compose_path = args.output.parent / "source-compose.json"
    config_path = args.output.parent / "source-config.yml"
    config_path.write_text(
        "bind: 0.0.0.0:3021\ncache_dir: /data\nconnect_to_reserved_ips: true\nmax_concurrent_requests: 8\nsources: []\n",
        encoding="utf-8",
    )
    compose_path.write_text(
        json.dumps(
            {
                "services": {
                    "symbolicator": {
                        "image": IMAGE,
                        "command": ["run", "-c", "/etc/symbolicator/config.yml"],
                        "ports": ["127.0.0.1:3031:3021"],
                        "volumes": [
                            f"{config_path.resolve().as_posix()}:/etc/symbolicator/config.yml:ro",
                            "qai-cache:/data",
                        ],
                    }
                },
                "volumes": {"qai-cache": {}},
            }
        ),
        encoding="utf-8",
    )
    compose_args = ["docker", "compose", "-p", PROJECT, "-f", str(compose_path)]
    server = None
    started = False

    def check(case_id, condition, detail):
        evidence["cases"].append(
            {"id": case_id, "status": "PASS" if condition else "FAIL", "detail": detail}
        )
        # Continue collecting independent comparisons; final exit remains nonzero.

    try:
        run(["docker", "info", "--format", "{{.ServerVersion}}"])
        fixture = ROOT / "fixtures/p0-b01-null-read/generated"
        pe = (fixture / "null_read_target.exe").read_bytes()
        pdb = (fixture / "null_read_target.pdb").read_bytes()
        changed_pdb = pdb.replace(b"trigger_null_read", b"trigger_fake_read")
        if changed_pdb == pdb:
            raise RuntimeError(
                "fixture PDB does not contain the expected same-length symbol token"
            )
        changed_pe = pe + b"QAI same identity alternate content\0"
        identity = json.loads(
            run(
                [
                    str(args.core),
                    "identify",
                    "--kind",
                    "pe",
                    "--artifact",
                    str(fixture / "null_read_target.exe"),
                    "--output",
                    "-",
                ]
            ).stdout
        )
        debug_id = identity["debug_id"]
        unified = debug_id[:2] + "/" + debug_id[2:]
        aid, bid = (
            pair_id(sha(pe), sha(pdb)),
            pair_id(sha(changed_pe), sha(changed_pdb)),
        )
        evidence["pairs"] = {
            "A": {"pair_id": aid, "pe_sha256": sha(pe), "pdb_sha256": sha(pdb)},
            "B": {
                "pair_id": bid,
                "pe_sha256": sha(changed_pe),
                "pdb_sha256": sha(changed_pdb),
            },
        }
        evidence["identity"] = identity
        for kind, data in [("pe", changed_pe), ("pdb", changed_pdb)]:
            path = args.output.parent / f"alternate.{kind}"
            path.write_bytes(data)
            actual = json.loads(
                run(
                    [
                        str(args.core),
                        "identify",
                        "--kind",
                        kind,
                        "--artifact",
                        str(path),
                        "--output",
                        "-",
                    ]
                ).stdout
            )
            check(
                f"alternate_{kind}_same_identity",
                actual["debug_id"] == debug_id
                and (kind == "pdb" or actual["code_id"] == identity["code_id"]),
                actual,
            )
        server = SourceServer()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        for prefix, binary, symbols in [
            (aid, pe, pdb),
            (bid, changed_pe, changed_pdb),
            ("manifest-a", pe, pdb),
            ("manifest-b", changed_pe, changed_pdb),
        ]:
            server.routes[f"/{prefix}/{unified}/executable"] = binary
            server.routes[f"/{prefix}/{unified}/debuginfo"] = symbols
        # Remove only this dedicated stack/cache; never product resources.
        run(compose_args + ["down", "--volumes"], check=False)
        started = True
        run(compose_args + ["up", "-d"])
        deadline = time.monotonic() + 60
        while True:
            try:
                request("GET", "/healthcheck")
                break
            except (OSError, ValueError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)
        container = run(compose_args + ["ps", "-q", "symbolicator"]).stdout.strip()
        evidence["running_image_id"] = run(
            ["docker", "inspect", "--format", "{{.Image}}", container]
        ).stdout.strip()
        evidence["version"] = run(
            compose_args
            + ["exec", "-T", "symbolicator", "/bin/symbolicator", "--version"]
        ).stdout.strip()
        payload = json.loads(
            (ROOT / "tests/symbolicator/http-source-request.json").read_text()
        )
        # Derive identities from the actual fixture; do not trust a historical request's ID.
        payload["modules"][0].update(
            {"code_id": identity["code_id"].lower(), "debug_id": debug_id}
        )
        inspect = json.loads(
            run(
                [
                    str(args.core),
                    "inspect",
                    "--dump",
                    str(fixture / "null-read.dmp"),
                    "--output",
                    "-",
                ]
            ).stdout
        )
        module = next(m for m in inspect["modules"] if m.get("debug_id") == debug_id)
        payload["modules"][0].update(
            {
                "image_addr": int(module["image_base"], 16),
                "image_size": module["image_size"],
            }
        )
        payload["stacktraces"] = [
            {"frames": [{"instruction_addr": inspect["exception"]["address"]}]}
        ]

        def execute(label, sources):
            req = copy.deepcopy(payload)
            req["sources"] = sources
            before = len(server.events)
            began = time.monotonic()
            result = symbolicate(req)
            evidence["raw_results"][label] = result
            return result, server.events[before:], round(time.monotonic() - began, 3)

        sa, sb = (
            source(f"crash-cap:pair:{aid}:http-v2", aid),
            source(f"crash-cap:pair:{bid}:http-v2", bid),
        )
        cold, events, elapsed = execute("pair_a_cold", [sa])
        check(
            "pair_a_cold",
            any("trigger_null_read" in f for f in functions(cold))
            and any(e["status"] == 200 for e in events),
            {"events": events, "seconds": elapsed},
        )
        hot, events, elapsed = execute("pair_a_other_workspace_hot", [sa])
        check(
            "content_cache_reuse",
            functions(cold) == functions(hot) and not events,
            {
                "events": events,
                "seconds": elapsed,
                "scope": "Workspace deliberately absent from internal source identity and request",
            },
        )
        alternate, events, elapsed = execute("pair_b_after_a", [sb])
        check(
            "same_identity_different_content",
            any("trigger_fake_read" in f for f in functions(alternate))
            and not any("trigger_null_read" in f for f in functions(alternate)),
            {"events": events, "seconds": elapsed},
        )
        restored, _, _ = execute("pair_a_restored", [sa])
        check("pair_a_restored", functions(restored) == functions(cold), {})
        conflict, events, _ = execute("blocked_no_sources_hot", [])
        check(
            "no_source_hot_cache_cannot_bypass",
            not any("trigger_" in f for f in functions(conflict)) and not events,
            {
                "events": events,
                "boundary": "Symbolicator source exclusion only; production per-module gateway and Core unwind blocking remain G4",
            },
        )
        missing, missing_events, _ = execute(
            "missing_before_import", [source("crash-cap:manifest:missing", "missing")]
        )
        filled, _, _ = execute("pair_after_negative_cache", [sa])
        check(
            "negative_then_unique",
            not any("trigger_" in f for f in functions(missing))
            and functions(filled) == functions(cold),
            {"missing_events": missing_events},
        )
        for suffix, expected in [
            ("a", "trigger_null_read"),
            ("b", "trigger_fake_read"),
        ]:
            result, events, elapsed = execute(
                f"manifest_{suffix}",
                [source(f"crash-cap:manifest:{suffix}:http-v1", f"manifest-{suffix}")],
            )
            check(
                f"manifest_{suffix}_isolation",
                any(expected in f for f in functions(result)),
                {"events": events, "seconds": elapsed},
            )
        if args.partition_count:
            from qualify_partitioned import qualify

            evidence["partition_script_sha256"] = sha(
                (Path(__file__).parent / "qualify_partitioned.py").read_bytes()
            )
            evidence["partition_planner_sha256"] = sha(
                (Path(__file__).parent / "partitioned_source.py").read_bytes()
            )
            qualify(
                check=check,
                payload=payload,
                server=server,
                evidence=evidence,
                args=args,
                pe=pe,
                pdb=pdb,
                changed_pdb=changed_pdb,
                identity=identity,
                source=source,
                symbolicate=symbolicate,
                run=run,
                sha=sha,
                count=args.partition_count,
            )
        for count in counts:
            sources = [
                source(f"crash-cap:empty:{count}:{i}", f"empty-{count}-{i}")
                for i in range(count - 1)
            ] + [sa]
            result, events, elapsed = execute(f"source_count_{count}", sources)
            errors = [
                c
                for m in result.get("modules", [])
                for c in m.get("candidates", [])
                if c.get("download", {}).get("status") == "error"
            ]
            check(
                f"source_count_{count}",
                functions(result) == functions(cold) and elapsed < 30 and not errors,
                {
                    "requests": len(events),
                    "seconds": elapsed,
                    "limit_seconds": 30,
                    "download_errors": errors,
                },
            )
        if args.diagnostic_extended:
            server.routes[f"/malformed/{unified}/executable"] = pe
            server.routes[f"/malformed/{unified}/debuginfo"] = (
                b"not a PDB or any supported debug file"
            )
            malformed, events, _ = execute(
                "diagnostic_malformed",
                [source("crash-cap:diagnostic:malformed", "malformed")],
            )
            diagnostic = [
                o for m in malformed["modules"] for o in source_outcomes(m, events)
            ]
            check(
                "diagnostic_malformed",
                any(
                    o["failure_class"] == "permanent"
                    and o["reason"] in ("malformed", "unsupported")
                    for o in diagnostic
                ),
                {
                    "source_outcomes": diagnostic,
                    "module_response": malformed["modules"],
                    "events": events,
                },
            )
            server.modes["integrity"] = 503
            server.failure_overrides["integrity"] = {
                "failure_class": "permanent",
                "reason": "integrity_failed",
            }
            failed, events, _ = execute(
                "diagnostic_integrity",
                [source("crash-cap:diagnostic:integrity", "integrity")],
            )
            diagnostic = [
                o for m in failed["modules"] for o in source_outcomes(m, events)
            ]
            check(
                "diagnostic_integrity",
                bool(diagnostic)
                and all(o["failure_class"] == "permanent" for o in diagnostic),
                {"source_outcomes": diagnostic, "events": events},
            )
        for mode, http in [("permanent", 404), ("transient", 503)]:
            server.modes[mode] = http
            result, events, _ = execute(
                f"diagnostic_{mode}", [source(f"crash-cap:diagnostic:{mode}", mode)]
            )
            diagnostic = [
                o for m in result["modules"] for o in source_outcomes(m, events)
            ]
            check(
                f"diagnostic_{mode}",
                bool(events)
                and all(e["status"] == http for e in events)
                and bool(diagnostic)
                and all(o["failure_class"] == mode for o in diagnostic),
                {
                    "events": events,
                    "source_outcomes": diagnostic,
                    "module_response": result.get("modules"),
                    "classification_authority": "correlated diagnostic HTTP source log; upstream module summary alone is not authoritative",
                },
            )
            if mode == "transient":
                unknown = [o for m in result["modules"] for o in source_outcomes(m, [])]
                check(
                    "diagnostic_uncorrelated_failure_stays_unknown",
                    bool(unknown)
                    and all(o["failure_class"] == "unknown" for o in unknown),
                    {"source_outcomes": unknown},
                )
        evidence["source_events"] = server.events
        evidence["status"] = (
            "PASS" if all(c["status"] == "PASS" for c in evidence["cases"]) else "FAIL"
        )
    except Exception as error:
        evidence["status"] = "FAIL" if evidence["cases"] else "NOT_PROVEN"
        evidence["error"] = f"{type(error).__name__}: {error}"
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if started:
            evidence["cleanup"] = run(
                compose_args + ["down", "--volumes"], check=False
            ).returncode
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": evidence["status"],
                "cases": len(evidence["cases"]),
                "output": str(args.output),
                "error": evidence.get("error"),
            }
        )
    )
    raise SystemExit(0 if evidence["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
