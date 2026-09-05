"""Exercise a supplied v3 deployment using real, uniquely identified fixture binaries.

Creates only explicitly prefixed test Workspaces; never deletes or resets resources.
The null-read fixture is built by scripts/fixtures/build_p0_b01.ps1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import urlparse


def unique_fixture(source: Path, destination: Path) -> tuple[Path, Path, Path]:
    """Change one matching GUID in real PE/PDB/DMP without changing code or stacks."""
    pe = bytearray((source / "null_read_target.exe").read_bytes())
    pdb = bytearray((source / "null_read_target.pdb").read_bytes())
    dump = (source / "null-read.dmp").read_bytes()
    assert pe.count(b"RSDS") == 1
    at = pe.index(b"RSDS")
    old, new = bytes(pe[at + 4 : at + 20]), uuid.uuid4().bytes_le
    signature = bytes(pe[at : at + 24])
    assert dump.count(signature) == 1
    pe[at + 4 : at + 20] = new
    dump = dump.replace(signature, signature[:4] + new + signature[20:])
    block_size, directory_size, block_map = (
        struct.unpack_from("<I", pdb, i)[0] for i in (32, 44, 52)
    )
    count = (directory_size + block_size - 1) // block_size
    blocks = struct.unpack_from("<" + "I" * count, pdb, block_map * block_size)
    directory = b"".join(pdb[b * block_size : (b + 1) * block_size] for b in blocks)[
        :directory_size
    ]
    streams = struct.unpack_from("<I", directory)[0]
    sizes = struct.unpack_from("<" + "I" * streams, directory, 4)
    cursor = 4 + 4 * streams
    stream_zero_blocks = 0 if sizes[0] == 0xFFFFFFFF else (sizes[0] + block_size - 1) // block_size
    info_block = struct.unpack_from("<I", directory, cursor + 4 * stream_zero_blocks)[0]
    guid_at = info_block * block_size + 12
    assert bytes(pdb[guid_at : guid_at + 16]) == old
    pdb[guid_at : guid_at + 16] = new
    paths = (
        destination / "renamed.exe",
        destination / "unrelated-name.pdb",
        destination / "crash.dmp",
    )
    for path, data in zip(paths, (pe, pdb, dump), strict=True):
        path.write_bytes(data)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workspace-prefix", default="v3-acceptance")
    args = parser.parse_args()
    api_url = args.api_url.rstrip("/")
    if urlparse(api_url).scheme not in {"http", "https"}:
        parser.error("--api-url must be HTTP or HTTPS")
    args.output.mkdir(parents=True, exist_ok=True)
    pe, pdb, dump = unique_fixture(args.fixture_dir, args.output)
    evidence = {"status": "RUNNING", "api_url": api_url, "checks": [], "workspaces": {}}

    def save():
        (args.output / "result.json").write_text(
            json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
        )

    def check(name, passed):
        assert passed, name
        evidence["checks"].append(name)
        save()

    def api(path, body=None):
        request = urllib.request.Request(  # noqa: S310 - validated HTTP API URL
            api_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return json.load(response)

    suffix = uuid.uuid4().hex[:8]
    for key in ("a", "b", "c"):
        evidence["workspaces"][key] = api(
            "/workspaces", {"name": f"{args.workspace_prefix}-{suffix}-{key}"}
        )["id"]
    save()
    serial = 0

    def upload(scope, *paths, version=None):
        nonlocal serial
        serial += 1
        receipt = args.output / f"upload-{serial}.json"
        command = [
            str(args.cli.resolve()),
            "upload",
            *map(str, paths),
            "--api-url",
            api_url,
            "--json",
            "--receipt",
            str(receipt),
        ]
        command += ["--public"] if scope is None else ["--workspace", evidence["workspaces"][scope]]
        if version:
            command += ["--build-version", version]
        result = subprocess.run(  # noqa: S603 - explicitly supplied CLI under test
            command, capture_output=True, text=True, encoding="utf-8", timeout=180
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(receipt.read_text(encoding="utf-8"))["files"]

    def report(oid, predicate=lambda value: True):
        until = time.monotonic() + 240
        while time.monotonic() < until:
            detail = api("/occurrences/" + oid)
            if detail["current_analysis"]:
                result = api("/occurrences/" + oid + "/analysis")
                target = next(
                    m
                    for m in result["modules"]
                    if m.get("debug_id") and m.get("code_file", "").endswith("null_read_target.exe")
                )
                if predicate(target):
                    return detail, result, target
            time.sleep(2)
        raise AssertionError(f"Report did not reach the required state: {detail}")

    # Private halves in different spaces must not combine.
    check(
        "PDB accepted before PE",
        upload("a", pdb)[0]["result"]["availability"] == "waiting_for_pair",
    )
    check(
        "cross-private halves remain unpaired",
        upload("b", pe)[0]["result"]["availability"] == "waiting_for_pair",
    )
    a_dump = upload("a", dump, version="initial")[0]["result"]["occurrence_id"]
    before, old_report, old_module = report(a_dump)
    check("foreign private PE excluded", old_module["selection"]["state"] == "none")
    upload("a", pe)
    after, new_report, new_module = report(
        a_dump,
        lambda m: (
            m["status"] == "matched"
            and any(
                s["stage"] == "symbolicate" and s["outcome"] == "found"
                for s in m["source_outcomes"]
            )
        ),
    )
    check(
        "late pair updates Current",
        before["current_analysis"]["id"] != after["current_analysis"]["id"],
    )
    check("local default owned", new_module["role"] == "owned")
    check(
        "native exact function and line",
        any(
            "trigger_null_read" in (f.get("function") or "") and f.get("line") == 76
            for t in new_report["threads"]
            for f in t["frames"]
        ),
    )
    check(
        "immutable old analysis",
        old_report == api("/runs/" + before["current_analysis"]["id"] + "/analysis"),
    )
    duplicate = upload("a", dump, version="different")[0]["result"]
    check(
        "DMP identity and existing label preserved",
        duplicate["occurrence_id"] == a_dump
        and duplicate["version_conflict"]
        and duplicate["current_version"] == "initial",
    )
    # Shared native caches are warm for this exact new GUID, but C has no files.
    c_dump = upload("c", dump)[0]["result"]["occurrence_id"]
    _, cold_report, cold_module = report(c_dump)
    check(
        "warm cache cannot introduce private symbols",
        cold_module["selection"]["state"] == "none"
        and cold_module["status"] != "matched"
        and not any(
            "trigger_null_read" in (f.get("function") or "")
            for t in cold_report["threads"]
            for f in t["frames"]
        ),
    )
    upload(None, pe)
    check(
        "public PE plus local PDB",
        api(
            "/uploads/"
            + json.loads((args.output / "upload-1.json").read_text())["files"][0]["upload_id"]
        )["availability"]
        == "symbols_available",
    )
    upload(None, pdb)
    _, public_report, public_module = report(
        c_dump,
        lambda m: (
            m["status"] == "matched"
            and any(
                s["stage"] == "symbolicate" and s["outcome"] == "found"
                for s in m["source_outcomes"]
            )
        ),
    )
    check("public pair usable in previously empty Workspace", public_module["role"] == "dependency")
    c_history_path = (
        f"/workspaces/{evidence['workspaces']['c']}/occurrences/{c_dump}/analysis-history"
    )
    c_history = api(c_history_path)
    a_previous = api("/occurrences/" + a_dump)["latest_attempt"]["id"]
    conflicting = args.output / "conflict.exe"
    conflicting.write_bytes(pe.read_bytes() + b"different valid overlay")
    check(
        "local-public identity conflict",
        upload("a", conflicting)[0]["result"]["availability"] == "identity_conflict",
    )
    until = time.monotonic() + 240
    while time.monotonic() < until:
        attempt = api("/occurrences/" + a_dump)["latest_attempt"]
        if attempt["id"] != a_previous and attempt["status"] in {"COMPLETE", "PARTIAL"}:
            conflict_report = api("/runs/" + attempt["id"] + "/analysis")
            if any(m["selection"]["state"] == "conflict" for m in conflict_report["modules"]):
                break
        time.sleep(2)
    else:
        raise AssertionError("Local conflict did not produce a bounded reanalysis")
    check(
        "conflict keeps previous Current",
        api("/occurrences/" + a_dump)["current_analysis"]["id"] != attempt["id"],
    )
    check(
        "conflict remains local",
        api(c_history_path) == c_history,
    )
    # The opposite public/private combination has its own fresh identity.
    mixed_dir = args.output / "mixed"
    mixed_dir.mkdir()
    mixed_pe, mixed_pdb, mixed_dump = unique_fixture(args.fixture_dir, mixed_dir)
    check(
        "PE accepted before PDB",
        upload("b", mixed_pe)[0]["result"]["availability"] == "waiting_for_pair",
    )
    upload(None, mixed_pdb)
    mixed_oid = upload("b", mixed_dump)[0]["result"]["occurrence_id"]
    _, mixed_report, mixed_module = report(mixed_oid, lambda m: m["status"] == "matched")
    check(
        "private PE plus public PDB",
        mixed_module["role"] == "owned"
        and any(
            s["stage"] == "symbolicate" and s["outcome"] == "found"
            for s in mixed_module["source_outcomes"]
        ),
    )
    for name, value in (
        ("before", old_report),
        ("paired", new_report),
        ("cache-excluded", cold_report),
        ("public", public_report),
        ("conflict", conflict_report),
        ("mixed", mixed_report),
    ):
        (args.output / f"{name}.json").write_text(json.dumps(value, indent=2), encoding="utf-8")
    evidence.update(
        status="PASS",
        occurrences={"a": a_dump, "c": c_dump, "mixed": mixed_oid},
        dump_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),
    )
    save()
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
