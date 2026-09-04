"""Isolated QAI protocol draft. No production reader or writer imports this module.

Canonical JSON here is a deliberately restricted cross-language encoding: UTF-8,
sorted ASCII object keys, no floats, compact separators, no Unicode escaping.
Identity inputs are normalized before hashing; paths and labels never enter keys.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def canonical_bytes(value: Any) -> bytes:
    def check(item: Any) -> None:
        if item is None or isinstance(item, (bool, str)):
            return
        if isinstance(item, int) and -(2**53 - 1) <= item <= 2**53 - 1:
            return
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict) and all(
            isinstance(k, str) and k.isascii() for k in item
        ):
            for child in item.values():
                check(child)
            return
        raise ValueError(
            "hash encoding accepts only JSON strings, safe integers, lists and ASCII keys"
        )

    check(value)
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def raw_hash(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("raw SHA-256 must be 64 lowercase hex characters")
    return value


def pair_id(pe_sha256: str, pdb_sha256: str) -> str:
    return digest(["pair-v1", raw_hash(pe_sha256), raw_hash(pdb_sha256)])


def normalize_identity(value: dict[str, Any]) -> dict[str, Any]:
    code = value.get("code_id")
    debug = value.get("debug_id")
    if code is not None:
        code = code.lower()
        if not re.fullmatch(r"[0-9a-f]{9,24}", code):
            raise ValueError("invalid PE Code ID")
    if debug is not None:
        # Both symbolic's UUID-age display and Breakpad GUID+hex-age encoding.
        debug = debug.replace("-", "").lower()
        if not re.fullmatch(r"[0-9a-f]{33,40}", debug):
            raise ValueError("invalid PDB Debug ID")
        debug = debug[:32] + format(int(debug[32:], 16), "x")
    architecture = value.get("architecture", "unknown")
    if architecture not in ("x86_64", "x86", "arm64", "unknown"):
        raise ValueError("invalid architecture")
    return {"code_id": code, "debug_id": debug, "architecture": architecture}


def select_candidates(
    identity: dict[str, Any], candidates: list[dict[str, Any]], *, complete: bool
) -> dict[str, Any]:
    """Candidates must carry actual-byte validation, never upload claims alone.

    A missing candidate identity is not proof of compatibility. Incomplete
    validation blocks uniqueness; an explicit contradiction excludes a candidate.
    """
    identity = normalize_identity(identity)
    active: set[str] = set()
    unavailable: set[str] = set()
    uncertain = not complete or not (identity["code_id"] or identity["debug_id"])
    for candidate in candidates:
        if candidate["validation"] not in ("verified", "invalid", "pending"):
            raise ValueError("unknown validation state")
        if candidate["availability"] not in (
            "active",
            "withdrawn",
            "location_unavailable",
        ):
            raise ValueError("unknown availability state")
        actual = normalize_identity(candidate["identity"])
        fields = [k for k, v in identity.items() if v is not None and v != "unknown"]
        if any(actual[k] not in (None, "unknown", identity[k]) for k in fields):
            continue
        if candidate["validation"] == "invalid":
            continue
        if candidate["validation"] != "verified" or any(
            actual[k] in (None, "unknown") for k in fields
        ):
            uncertain = True
            continue
        key = pair_id(candidate["pe_raw_sha256"], candidate["pdb_raw_sha256"])
        (active if candidate["availability"] == "active" else unavailable).add(key)
    # Conflicting observations of one pair require a consistent snapshot, not active wins.
    uncertain |= bool(active & unavailable)
    if uncertain:
        state = "indeterminate"
    elif len(active) > 1:
        state = "conflict"
    elif active:
        state = "unique"
    elif unavailable:
        state = "unavailable"
    else:
        state = "none"
    return {
        "identity": identity,
        "state": state,
        "candidates_complete": not uncertain,
        "candidate_pair_ids": sorted(active),
        "unavailable_pair_ids": sorted(unavailable),
        "selected_pair_id": next(iter(active)) if state == "unique" else None,
    }


def validate_manifest(manifest: dict[str, Any]) -> None:
    """Semantic checks additional to the draft schema; never a substitute for byte validation."""
    raw_hash(manifest["dump_sha256"])
    raw_hash(manifest["inspect_sha256"])
    seen = set()
    reasons = {
        "none": {"missing"},
        "unique": {"unique"},
        "conflict": {"identity_conflict"},
        "unavailable": {"withdrawn", "location_unavailable"},
        "indeterminate": {
            "incomplete_identity",
            "enumeration_failed",
            "validation_incomplete",
        },
    }
    for item in manifest["modules"]:
        if item["module_index"] in seen:
            raise ValueError("duplicate module index")
        seen.add(item["module_index"])
        if item["identity"] != normalize_identity(item["identity"]):
            raise ValueError("identity is not normalized")
        if item["reason"] not in reasons[item["state"]]:
            raise ValueError("reason contradicts selection state")
        for key in ("candidate_pair_ids", "unavailable_pair_ids"):
            if item[key] != sorted(set(raw_hash(v) for v in item[key])):
                raise ValueError("candidate IDs must be sorted and unique")
        if item["state"] == "unique" and item["candidate_pair_ids"] != [
            item["selected_pair_id"]
        ]:
            raise ValueError("selected pair differs from unique candidate")
        if item["state"] == "unavailable" and not item["unavailable_pair_ids"]:
            raise ValueError("unavailable requires evidence of an unavailable pair")


def evidence_fingerprint(manifest: dict[str, Any]) -> str:
    fields = (
        "module_index",
        "identity",
        "state",
        "candidates_complete",
        "candidate_pair_ids",
        "unavailable_pair_ids",
        "selected_pair_id",
        "reason",
    )
    modules = []
    seen = set()
    for module in manifest["modules"]:
        if module["module_index"] in seen:
            raise ValueError("duplicate captured module index")
        seen.add(module["module_index"])
        item = {key: module[key] for key in fields}
        item["identity"] = normalize_identity(item["identity"])
        for key in ("candidate_pair_ids", "unavailable_pair_ids"):
            item[key] = sorted(set(raw_hash(v) for v in item[key]))
        modules.append(item)
    return digest(
        [
            "resolution-evidence-v1",
            manifest["dump_sha256"],
            manifest["inspector_version"],
            manifest["selection_version"],
            sorted(modules, key=lambda m: m["module_index"]),
        ]
    )


def run_key(
    *,
    occurrence_id: str,
    fingerprint: str,
    context_sha256: str,
    generation: int,
    attempt: int,
) -> str:
    if generation < 1 or attempt < 0:
        raise ValueError("generation starts at one; retry attempt starts at zero")
    return digest(
        [
            "qa-run-key-v1",
            occurrence_id,
            raw_hash(fingerprint),
            raw_hash(context_sha256),
            "1.1",
            "evidence-v1",
            generation,
            attempt,
        ]
    )


def advance_target(previous: str | None, target: str, generation: int) -> int:
    """Compare with the last *planned target*, not Current or historical Run keys."""
    return generation + int(previous != target)
