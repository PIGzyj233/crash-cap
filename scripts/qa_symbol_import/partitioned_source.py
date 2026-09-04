"""S1 prototype: freeze each Symbolicator request to one selected content pair.

This is not a deployed gateway. Blocked modules produce no request, including to
public sources. One input physical frame per trace preserves inline expansion
without guessing original frame order from the returned function names.
"""

from __future__ import annotations

import copy
from collections import OrderedDict


def plan_requests(payload, selections, managed_sources, public_sources=()):
    if len(payload["modules"]) != len(selections):
        raise ValueError("every captured module must have exactly one selection")
    groups = OrderedDict()
    blocked = []
    for index, selection in enumerate(selections):
        state = selection["state"]
        pair = selection.get("selected_pair_id")
        if state == "unique":
            if pair is None or pair not in managed_sources:
                raise ValueError("selected content source missing")
            key = pair
            sources = [managed_sources[pair]]
        elif state == "none" and public_sources:
            key = "public"
            sources = list(public_sources)
        elif state in ("none", "conflict", "unavailable", "indeterminate"):
            blocked.append(index)
            continue
        else:
            raise ValueError("unknown selection state")
        group = groups.setdefault(key, {"module_indexes": [], "sources": sources})
        group["module_indexes"].append(index)
    indexes = set(range(len(selections)))
    frame_modules = []
    for ti, thread in enumerate(payload["stacktraces"]):
        for fi, frame in enumerate(thread["frames"]):
            address = (
                int(frame["instruction_addr"], 0)
                if isinstance(frame["instruction_addr"], str)
                else frame["instruction_addr"]
            )
            matches = [
                i
                for i, module in enumerate(payload["modules"])
                if int(str(module["image_addr"]), 0)
                <= address
                < int(str(module["image_addr"]), 0) + module["image_size"]
            ]
            if len(matches) > 1:
                raise ValueError("ambiguous captured module ranges")
            frame_modules.append((ti, fi, matches[0] if matches else None, frame))
    requests = []
    for key, group in groups.items():
        selected = set(group["module_indexes"])
        if not selected <= indexes:
            raise ValueError("unknown module index")
        frames = [
            (ti, fi, mi, frame) for ti, fi, mi, frame in frame_modules if mi in selected
        ]
        if not frames:
            continue
        request = {
            "platform": payload.get("platform", "native"),
            "modules": [
                copy.deepcopy(payload["modules"][i]) for i in group["module_indexes"]
            ],
            "stacktraces": [
                {"frames": [copy.deepcopy(frame)]} for _, _, _, frame in frames
            ],
            "options": {"dif_candidates": True, "apply_source_context": False},
            "sources": copy.deepcopy(group["sources"]),
        }
        requests.append(
            {
                "key": key,
                "module_indexes": group["module_indexes"],
                "frame_refs": [(ti, fi, mi) for ti, fi, mi, _ in frames],
                "request": request,
            }
        )
    return requests, blocked


def collect_partition(job, result):
    traces = result.get("stacktraces", [])
    if len(traces) != len(job["frame_refs"]):
        raise ValueError("source response changed trace cardinality")
    output = []
    for ref, trace in zip(job["frame_refs"], traces, strict=True):
        frames = trace.get("frames", [])
        if any(frame.get("original_index", 0) != 0 for frame in frames):
            raise ValueError("unexpected original frame provenance")
        request_trace = job["request"]["stacktraces"][len(output)]
        expected_pc = int(str(request_trace["frames"][0]["instruction_addr"]), 0)
        if any(
            int(str(frame.get("instruction_addr", "-1")), 0) != expected_pc
            for frame in frames
        ):
            raise ValueError("source response changed the physical instruction address")
        output.append(
            {
                "thread_index": ref[0],
                "frame_index": ref[1],
                "module_index": ref[2],
                "pair_id": job["key"],
                "symbols": frames,
            }
        )
    return output
