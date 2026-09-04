"""Extended real S1 checks, called inside the isolated qualification stack."""

from __future__ import annotations

import copy
import json
import struct
import time

from partitioned_source import collect_partition, plan_requests
from protocol import pair_id


def qualify(
    *,
    check,
    payload,
    server,
    evidence,
    args,
    pe,
    pdb,
    changed_pdb,
    identity,
    source,
    symbolicate,
    run,
    sha,
    count,
):
    root = args.output.parent
    debug_id = identity["debug_id"]
    unified = debug_id[:2] + "/" + debug_id[2:]
    pe_offset = struct.unpack_from("<I", pe, 0x3C)[0]
    original_timestamp = struct.unpack_from("<I", pe, pe_offset + 8)[0]
    pairs = []
    modules = []
    selections = []
    sources = {}
    original = payload["modules"][0]
    base = int(str(original["image_addr"]), 0)
    rva = int(payload["stacktraces"][0]["frames"][0]["instruction_addr"], 0) - base
    for index in range(count):
        binary = bytearray(pe)
        struct.pack_into("<I", binary, pe_offset + 8, original_timestamp + index + 1)
        binary = bytes(binary)
        symbols = pdb if index % 2 == 0 else changed_pdb
        key = pair_id(sha(binary), sha(symbols))
        artifact_path = root / "partition-probe.exe"
        artifact_path.write_bytes(binary)
        actual = json.loads(
            run(
                [
                    str(args.core),
                    "identify",
                    "--kind",
                    "pe",
                    "--artifact",
                    str(artifact_path),
                    "--output",
                    "-",
                ]
            ).stdout
        )
        if actual["debug_id"] != debug_id or actual["code_id"] == identity["code_id"]:
            raise ValueError(
                "fixture mutation failed to preserve Debug ID and change Code ID"
            )
        module = {
            **original,
            "code_id": actual["code_id"].lower(),
            "image_addr": base + index * 0x1000000,
        }
        modules.append(module)
        pairs.append(
            {
                "pair_id": key,
                "pe_sha256": sha(binary),
                "pdb_sha256": sha(symbols),
                "code_id": actual["code_id"],
                "debug_id": debug_id,
            }
        )
        sources[key] = source("crash-cap:pair:" + key + ":http-v2", key)
        selections.append({"state": "unique", "selected_pair_id": key})
        server.routes[f"/{key}/{unified}/executable"] = binary
        server.routes[f"/{key}/{unified}/debuginfo"] = symbols
    evidence["partition_pairs"] = pairs
    many = {
        **payload,
        "modules": modules,
        "stacktraces": [
            {
                "frames": [
                    {"instruction_addr": hex(m["image_addr"] + rva)} for m in modules
                ]
            }
        ],
    }
    mixed = {
        **many,
        "modules": modules[:2],
        "stacktraces": [{"frames": many["stacktraces"][0]["frames"][:2]}],
        "sources": [sources[pairs[0]["pair_id"]], sources[pairs[1]["pair_id"]]],
    }
    # Deliberately unsafe control. Its correctness is observed, never relied upon.
    evidence["raw_results"]["whole_request_two_sources_control"] = symbolicate(mixed)
    jobs, blocked = plan_requests(many, selections, sources)
    check(
        "partition_count_is_not_truncated",
        len(jobs) == count and not blocked,
        {"modules": count, "requests": len(jobs), "private_sources_per_request": 1},
    )
    started = time.monotonic()
    outputs = []
    failures = []
    for i, job in enumerate(jobs):
        before = len(server.events)
        result = symbolicate(job["request"])
        parsed = collect_partition(job, result)
        expected = "trigger_null_read" if i % 2 == 0 else "trigger_fake_read"
        functions = [f.get("function", "") for item in parsed for f in item["symbols"]]
        errors = [
            c
            for module in result.get("modules", [])
            for c in module.get("candidates", [])
            if c.get("download", {}).get("status") == "error"
        ]
        if not any(expected in f for f in functions) or errors:
            failures.append({"module": i, "functions": functions, "errors": errors})
        outputs.extend(parsed)
        evidence["raw_results"][f"partition_{i}"] = result
        if (i + 1) % 25 == 0:
            print(
                json.dumps(
                    {
                        "qualification": "partitioned_source",
                        "completed": i + 1,
                        "total": count,
                        "seconds": round(time.monotonic() - started, 2),
                        "last_http_requests": len(server.events) - before,
                    }
                ),
                flush=True,
            )
    check(
        "all_partitioned_modules_use_frozen_bytes",
        len(outputs) == count and not failures,
        {
            "modules": count,
            "failures": failures,
            "seconds": round(time.monotonic() - started, 3),
            "concurrency": 1,
        },
    )
    for blocked_state in ("conflict", "unavailable", "indeterminate"):
        states = copy.deepcopy(selections[:2])
        states[0] = {"state": blocked_state, "selected_pair_id": None}
        jobs, blocked = plan_requests(
            {**mixed, "sources": []},
            states,
            sources,
            public_sources=[source("crash-cap:public-probe", pairs[0]["pair_id"])],
        )
        before = len(server.events)
        result = symbolicate(jobs[0]["request"])
        mapped = collect_partition(jobs[0], result)
        check(
            "blocked_" + blocked_state + "_public_and_hot_cache",
            blocked == [0]
            and len(jobs) == 1
            and len(mapped) == 1
            and mapped[0]["module_index"] == 1
            and all(
                "trigger_fake_read" in f.get("function", "")
                for f in mapped[0]["symbols"]
                if f.get("status") == "symbolicated"
            )
            and not any(
                e["path"].startswith("/" + pairs[0]["pair_id"] + "/")
                for e in server.events[before:]
            ),
            {
                "blocked_modules": blocked,
                "request_module_count": len(jobs[0]["request"]["modules"]),
                "events": server.events[before:],
            },
        )
    hot, _ = plan_requests(many, selections, sources)
    before = len(server.events)
    restored = collect_partition(hot[0], symbolicate(hot[0]["request"]))
    check(
        "partition_restored_pair_hot_reuse",
        any(
            "trigger_null_read" in f.get("function", "") for f in restored[0]["symbols"]
        )
        and len(server.events) == before,
        {"events": server.events[before:]},
    )
