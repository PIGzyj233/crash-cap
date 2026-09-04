"""Validate immutable v2 Run inputs before any global-symbol analysis executes.

No catalog queries, fallback lookup, or writes belong here. The caller supplies
the independently observed Dump digest/size and the exact stored object bytes.
The semantic context excludes Run IDs and physical source locations.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from .contracts import load_validator

MAX_SAFE_INTEGER = 2**53 - 1
INSPECTOR_VERSION = "inspect-v0.1"


class FrozenInputError(ValueError):
    """A frozen input is invalid or contradicts another immutable input."""


def canonical_bytes(value: Any) -> bytes:
    def check(item: Any) -> None:
        if item is None or isinstance(item, (bool, str)):
            return
        if isinstance(item, int) and -MAX_SAFE_INTEGER <= item <= MAX_SAFE_INTEGER:
            return
        if isinstance(item, list):
            for child in item:
                check(child)
            return
        if isinstance(item, dict) and all(isinstance(k, str) and k.isascii() for k in item):
            for child in item.values():
                check(child)
            return
        raise FrozenInputError("qai-json-v1 requires ASCII keys, safe integers and no floats")

    check(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def normalize_identity(value: dict[str, Any]) -> dict[str, Any]:
    code, debug = value.get("code_id"), value.get("debug_id")
    if code is not None:
        code = str(code).lower()
        if re.fullmatch(r"[0-9a-f]{9,24}", code) is None:
            raise FrozenInputError("invalid PE Code ID")
    if debug is not None:
        debug = str(debug).replace("-", "").lower()
        if re.fullmatch(r"[0-9a-f]{33,40}", debug) is None:
            raise FrozenInputError("invalid PDB Debug ID")
        debug = debug[:32] + format(int(debug[32:], 16), "x")
    architecture = value.get("architecture", "unknown")
    if architecture not in {"x86_64", "x86", "arm64", "unknown"}:
        raise FrozenInputError("invalid architecture")
    return {"code_id": code, "debug_id": debug, "architecture": architecture}


def resolution_fingerprint(manifest: dict[str, Any]) -> str:
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
    modules = [{key: module[key] for key in fields} for module in manifest["modules"]]
    return digest(
        [
            "resolution-evidence-v1",
            manifest["dump_sha256"],
            manifest["inspector_version"],
            manifest["selection_version"],
            sorted(modules, key=lambda m: m["module_index"]),
        ]
    )


def frozen_run_key(run: dict[str, Any]) -> str:
    return digest(
        [
            "qa-run-key-v1",
            run["occurrence_id"],
            run["resolution_evidence_fingerprint"],
            run["context_sha256"],
            "1.1",
            "evidence-v1",
            run["demand_generation"],
            run["retry_attempt"],
        ]
    )


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise FrozenInputError(reason)


def verify_selection(module: dict[str, Any]) -> None:
    """Semantic checks shared by target adoption and full Run verification.

    The caller must validate the resolution-manifest schema first.
    """
    for field in ("candidate_pair_ids", "unavailable_pair_ids"):
        _require(
            module[field] == sorted(set(module[field])), "candidate pair IDs are not canonical"
        )
    reasons = {
        "none": {"missing"},
        "unique": {"unique"},
        "conflict": {"identity_conflict"},
        "unavailable": {"withdrawn", "location_unavailable"},
        "indeterminate": {"incomplete_identity", "enumeration_failed", "validation_incomplete"},
    }
    _require(module["reason"] in reasons[module["state"]], "selection reason contradicts state")
    _require(
        module["state"] == "indeterminate"
        or not set(module["candidate_pair_ids"]) & set(module["unavailable_pair_ids"]),
        "one pair has contradictory availability observations",
    )
    if module["state"] == "none":
        _require(not module["unavailable_pair_ids"], "none selection has unavailable pairs")
    if module["state"] == "unique":
        _require(
            module["candidate_pair_ids"] == [module["selected_pair_id"]],
            "selected pair differs from candidate",
        )
    if module["state"] == "unavailable":
        _require(not module["candidate_pair_ids"], "unavailable selection has active pairs")
        _require(
            bool(module["unavailable_pair_ids"]), "unavailable selection lacks withdrawn evidence"
        )


def _valid_timestamp(value: str) -> bool:
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})[Tt]([0-2]\d):([0-5]\d):([0-5]\d|60)"
        r"(\.\d+)?([Zz]|[+-](?:[01]\d|2[0-3]):[0-5]\d)",
        value,
    )
    if match is None:
        return False
    date, hour, minute, second, fraction, offset = match.groups()
    # Python's datetime has no leap-second representation. Validate the date,
    # clock and offset using second 59 while retaining the original Run bytes.
    second = "59" if second == "60" else second
    offset = "+00:00" if offset in {"Z", "z"} else offset
    try:
        datetime.fromisoformat(f"{date}T{hour}:{minute}:{second}{fraction or ''}{offset}")
    except ValueError:
        return False
    return True


def _object(data: bytes, expected_sha256: str, label: str) -> dict[str, Any]:
    _require(hashlib.sha256(data).hexdigest() == expected_sha256, f"{label} object digest mismatch")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            _require(key not in result, f"{label} contains duplicate JSON keys")
            result[key] = value
        return result

    try:
        value = json.loads(data, object_pairs_hook=unique_object)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise FrozenInputError(f"{label} is not JSON") from error
    _require(isinstance(value, dict), f"{label} must be an object")
    return cast(dict[str, Any], value)


def verify_public_sources(sources: list[dict[str, Any]]) -> None:
    """Semantic checks after source schema validation, shared with the planner."""
    source_ids = [source["id"] for source in sources]
    _require(source_ids == sorted(set(source_ids)), "public sources must be sorted and unique")
    for source in sources:
        _require(not source["id"].startswith("crash-cap:pair:"), "reserved private source ID")
        try:
            url = urlsplit(source["url"])
            valid_port = url.port is None or 1 <= url.port <= 65535
            valid_url = (
                url.scheme in {"http", "https"}
                and bool(url.hostname)
                and valid_port
                and url.username is None
                and url.password is None
                and not url.query
                and not url.fragment
                and source["url"].isascii()
                and not any(
                    ord(char) <= 32 or ord(char) == 127 or char in '<>"{}|\\^`'
                    for char in source["url"]
                )
            )
        except ValueError:
            valid_url = False
        _require(valid_url, "public source URL must be credential-free HTTP(S)")
        for key in ("filetypes", "path_patterns"):
            values = source["filters"].get(key, [])
            _require(
                values == sorted(set(values)), "public source filters must be sorted and unique"
            )


def verify_frozen_run(
    run: dict[str, Any],
    *,
    manifest_bytes: bytes,
    inspect_bytes: bytes,
    observed_dump_sha256: str,
    observed_dump_size: int,
    schema_root: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return verified manifest/inspect; fail closed before materialization.

    `schema_root` is an explicit local contract package (the qualification draft
    package until its release). This does not enable any API or Worker write path.
    """
    validator = load_validator(str((schema_root / "analysis-run-v2.schema.json").resolve()))
    errors = list(validator.iter_errors(run))
    _require(not errors, "Run does not satisfy analysis-run-v2")
    manifest = _object(manifest_bytes, run["resolution_manifest"]["sha256"], "manifest")
    inspect = _object(inspect_bytes, run["inspect"]["sha256"], "inspect")
    validator = load_validator(str((schema_root / "resolution-manifest-v1.schema.json").resolve()))
    _require(not list(validator.iter_errors(manifest)), "manifest schema mismatch")
    context = run["context"]
    _require(
        manifest["inspect_sha256"] == run["inspect"]["sha256"], "manifest inspect digest mismatch"
    )
    _require(digest(context) == run["context_sha256"], "semantic context digest mismatch")
    _require(run["dump"]["sha256"] == observed_dump_sha256, "Dump digest mismatch")
    _require(run["dump"]["size"] == observed_dump_size, "Dump size mismatch")
    _require(manifest["dump_sha256"] == observed_dump_sha256, "manifest belongs to another Dump")
    for field in ("inspector_version", "selection_version"):
        _require(manifest[field] == context[field], f"{field} mismatch")
    facts = run["result_facts"]["dump"]
    for field in ("sha256", "size"):
        _require(facts[field] == run["dump"][field], f"result Dump {field} mismatch")
    inspected_dump = inspect.get("dump", {})
    for field, inspected_field in (
        ("size", "size"),
        ("kind", "kind"),
        ("dump_timestamp", "timestamp"),
    ):
        _require(
            facts[field] == inspected_dump.get(inspected_field), f"inspect Dump {field} mismatch"
        )
    _require(facts["capture_profile"] == context["capture_profile"], "capture profile mismatch")
    for key in ("dump_timestamp", "reported_at", "uploaded_at", "occurred_at"):
        _require(facts[key] is None or _valid_timestamp(facts[key]), "invalid frozen timestamp")
    time_field = {
        "dump": "dump_timestamp",
        "reported": "reported_at",
        "uploaded": "uploaded_at",
        "manual": "occurred_at",
    }[facts["time_source"]]
    _require(
        facts[time_field] is not None and facts["occurred_at"] == facts[time_field],
        "occurred_at contradicts time_source",
    )
    policies = run["policy_snapshots"]
    for key in ("build_snapshot", "role_policy", "source_policy"):
        _require(digest(policies[key]) == context[f"{key}_sha256"], f"{key} digest mismatch")
    verify_public_sources(policies["source_policy"]["public_sources"])
    _require(inspect.get("schema_version") == "0.1", "unsupported inspect version")
    captured = inspect.get("modules")
    if not isinstance(captured, list) or not all(isinstance(m, dict) for m in captured):
        raise FrozenInputError("inspect modules missing or invalid")
    process = inspect.get("process")
    if not isinstance(process, dict) or not isinstance(process.get("architecture"), str):
        raise FrozenInputError("inspect process architecture missing")
    roles = policies["role_policy"]["modules"]
    for label, modules in (("selection", manifest["modules"]), ("role policy", roles)):
        _require(
            [m["module_index"] for m in modules] == list(range(len(captured))),
            f"{label} must cover every captured module once in order",
        )
        for module, observed in zip(modules, captured, strict=True):
            identity = normalize_identity({**observed, "architecture": process["architecture"]})
            _require(module["identity"] == identity, f"{label} captured identity mismatch")
    for module in manifest["modules"]:
        verify_selection(module)
    for role in roles:
        _require(
            role["in_app"] == (role["role"] in {"entrypoint", "owned"}),
            "role and in_app contradict",
        )
    _require(
        resolution_fingerprint(manifest) == run["resolution_evidence_fingerprint"],
        "resolution fingerprint mismatch",
    )
    _require(frozen_run_key(run) == run["idempotency_key"], "Run key mismatch")
    builds = policies["build_snapshot"]["builds"]
    build_ids = [b["build_id"] for b in builds]
    _require(build_ids == sorted(set(build_ids)), "Build snapshot must be sorted and unique")
    for build in builds:
        _require(build["workspace_id"] == context["workspace_id"], "cross-Workspace Build snapshot")
        _require(
            build["manifest_sha256"] == digest(build["manifest"]), "Build manifest digest mismatch"
        )
        verified = build["verified_modules"]
        module_ids = [module["module_id"] for module in verified]
        _require(
            module_ids == sorted(set(module_ids)),
            "verified Build modules must be sorted and unique",
        )
        manifest_indexes = [module["manifest_module_index"] for module in verified]
        _require(
            len(manifest_indexes) == len(set(manifest_indexes)), "duplicate manifest module binding"
        )
        for module in verified:
            index = module["manifest_module_index"]
            declarations = build["manifest"]["modules"]
            _require(index < len(declarations), "verified Build module has no manifest declaration")
            _require(
                module["role"] == declarations[index]["role"],
                "verified Build role differs from manifest",
            )
            identity = module["identity"]
            _require(
                identity == normalize_identity(identity),
                "verified Build identity is not normalized",
            )
            for key in ("verified_pair_ids", "artifact_ids"):
                _require(
                    module[key] == sorted(set(module[key])),
                    "verified Build evidence must be sorted and unique",
                )
            if module["verified_pair_ids"]:
                _require(
                    identity["code_id"] is not None and identity["debug_id"] is not None,
                    "verified Build pair lacks an actual Code/Debug identity",
                )
    _require(
        context["reported_build_id"] is None or context["reported_build_id"] in build_ids,
        "reported Build missing from frozen snapshot",
    )
    bundles = policies["source_policy"]["bundles"]
    bundle_ids = [b["artifact_id"] for b in bundles]
    _require(bundle_ids == sorted(set(bundle_ids)), "source bundles must be sorted and unique")
    locations = run["source_bundle_locations"]
    _require(
        [item["artifact_id"] for item in locations] == bundle_ids,
        "source locations differ from frozen policy",
    )
    for bundle, location in zip(bundles, locations, strict=True):
        _require(bundle["build_id"] in build_ids, "source bundle outside frozen Workspace Builds")
        _require(
            bundle["sha256"] == location["content"]["sha256"], "source bundle content mismatch"
        )
    return manifest, inspect
