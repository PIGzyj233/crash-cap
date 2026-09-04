"""Conservative S1 legacy evidence qualification, independent of Current mutation.

It can establish old physical anchors, never invent an old selected global pair,
new context digest, or an unfolded CFI method. Insufficient evidence has a durable
review/recompute route rather than pretending to be a comparable symbol refresh.
"""

from __future__ import annotations

from protocol import normalize_identity

KNOWN_METHODS = {"context": "context", "frame_pointer": "frame_pointer", "scan": "scan"}


def address(value):
    if isinstance(value, int):
        return value
    return int(value, 0)


def qualify_legacy(canonical, inspect, raw, *, dump_available, basis_withdrawn=False):
    missing = []
    anchors = []
    fault = None
    if not isinstance(canonical, dict) or canonical.get("schema_version") != "1.0":
        missing.append("legacy_canonical_unavailable")
    if not isinstance(inspect, dict):
        missing.append("inspect_unavailable")
    if not isinstance(raw, dict) or not isinstance(raw.get("threads"), list):
        missing.append("raw_unwind_unavailable")
    if not missing:
        exception = inspect.get("exception")
        if exception and canonical.get("crash", {}).get("type") == "crash":
            instruction = address(exception["address"])
            modules = inspect["modules"]
            matches = [
                i
                for i, module in enumerate(modules)
                if address(module["image_base"])
                <= instruction
                < address(module["image_base"]) + module["image_size"]
            ]
            if len(matches) != 1:
                missing.append("fault_module_instance_ambiguous")
            elif (
                address(canonical["crash"]["address"]) != instruction
                or canonical["crash"].get("thread_id") != exception["thread_id"]
                or (canonical["crash"].get("exception_code") or "").lower()
                != exception["code"].lower()
                or canonical["crash"].get("access_type") != exception.get("access_type")
            ):
                missing.append("fault_anchor_mismatch")
            else:
                fault = {
                    "module_index": matches[0],
                    "rva": hex(
                        instruction - address(modules[matches[0]]["image_base"])
                    ),
                    "thread_id": exception["thread_id"],
                    "exception_code": exception["code"],
                    "access_type": exception.get("access_type"),
                    "fault_address": exception.get("fault_address"),
                }
        else:
            missing.append("legacy_noncrash_transition_requires_review")
        crashing = [t for t in canonical.get("threads", []) if t.get("is_crashing")]
        if len(crashing) != 1:
            missing.append("crashing_thread_ambiguous")
        else:
            thread = crashing[0]
            raws = [t for t in raw["threads"] if t["id"] == thread["id"]]
            physical = [f for f in thread["frames"] if not f.get("inline", False)]
            if len(raws) != 1 or len(physical) != len(raws[0]["frames"]):
                missing.append("physical_frame_alignment_unproven")
            else:
                for old, engine in zip(physical, raws[0]["frames"], strict=True):
                    if (
                        address(old["instruction_addr"]) != engine["instruction"]
                        or old["trust"] != engine["trust"]
                    ):
                        missing.append("physical_frame_alignment_mismatch")
                        continue
                    if not old.get("in_app") or old["trust"] in ("scan", "unknown"):
                        continue
                    method = engine.get("unwind_method")
                    if method is None:
                        method = KNOWN_METHODS.get(engine["trust"])
                    elif {
                        "context": "context",
                        "call_frame_info": "cfi",
                        "cfi_scan": "cfi",
                        "frame_pointer": "frame_pointer",
                        "scan": "scan",
                        "prewalked": "unknown",
                        "unknown": "unknown",
                    }.get(method) != engine["trust"]:
                        missing.append("raw_unwind_provenance_mismatch")
                        continue
                    if method == "cfi_scan":
                        # Explicit CFI scan is known non-reliable evidence, not
                        # an absent method to fill in as true CFI.
                        continue
                    if method not in ("context", "frame_pointer", "call_frame_info"):
                        missing.append("legacy_unwind_provenance_missing")
                        continue
                    pc = engine["instruction"]
                    module_indexes = [
                        i
                        for i, m in enumerate(inspect["modules"])
                        if address(m["image_base"])
                        <= pc
                        < address(m["image_base"]) + m["image_size"]
                    ]
                    if len(module_indexes) != 1:
                        missing.append("business_module_instance_ambiguous")
                        continue
                    index = module_indexes[0]
                    module = inspect["modules"][index]
                    anchors.append(
                        {
                            "module_index": index,
                            "identity": normalize_identity(
                                {
                                    "code_id": module.get("code_id"),
                                    "debug_id": module.get("debug_id"),
                                    "architecture": inspect["process"]["architecture"],
                                }
                            ),
                            "rva": hex(pc - address(module["image_base"])),
                            "unwind_method": method,
                            "function": old.get("function"),
                            "file": old.get("file"),
                            "line": old.get("line"),
                        }
                    )
    if basis_withdrawn and not dump_available:
        route = "basis_withdrawn_cannot_recompute"
    elif missing and dump_available:
        route = "explicit_engine_upgrade_or_review"
    elif missing:
        route = "needs_review_cannot_recompute"
    else:
        route = "verify_context_and_pair_evidence_before_comparison"
    return {
        "version": "legacy-continuity-v1",
        "anchor_status": "incomparable" if missing else "verified",
        "reasons": sorted(set(missing)),
        "fault_anchor": fault,
        "business_anchors": anchors,
        "route": route,
        "dump_available": dump_available,
        "basis_withdrawn": basis_withdrawn,
        "automatic_promotion": False,
        "context_and_global_pair_evidence": "not_reconstructed_from_legacy",
    }
