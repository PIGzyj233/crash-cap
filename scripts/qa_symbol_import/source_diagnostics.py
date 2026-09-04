"""S1 structured adapter. Unknown download failures remain unknown without evidence."""

from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlsplit


def source_outcomes(module, events):
    groups = defaultdict(list)
    for candidate in module.get("candidates", []):
        path = urlsplit(candidate["location"]).path
        leaf = path.rsplit("/", 1)[-1]
        stage = "download_pe" if leaf.startswith("executabl") else "download_pdb"
        groups[(candidate["source"], stage)].append((candidate, path))
    results = []
    for (source_id, stage), candidates in sorted(groups.items()):
        statuses = {
            c.get("download", {}).get("status", "unknown") for c, _ in candidates
        }
        paths = {p for _, p in candidates}
        correlated = [e for e in events if e["path"] in paths]
        if "ok" in statuses:
            outcome, failure_class, reason = "found", "none", "downloaded"
        elif statuses == {"notfound"}:
            outcome, failure_class, reason = "missing", "permanent", "source_missing"
        elif "malformed" in statuses:
            outcome, failure_class, reason = "failed", "permanent", "malformed"
        elif "error" in statuses:
            errors = [e for e in correlated if e["status"] not in (200, 404)]
            classes = {e.get("failure_class", "unknown") for e in errors}
            failure_class = next(iter(classes)) if len(classes) == 1 else "unknown"
            if failure_class not in ("transient", "permanent"):
                failure_class = "unknown"
            reasons = {e.get("reason", "unclassified_failure") for e in errors}
            reason = (
                next(iter(reasons)) if len(reasons) == 1 else "unclassified_failure"
            )
            outcome = "failed"
        else:
            outcome, failure_class, reason = (
                "unknown",
                "unknown",
                "diagnostics_incomplete",
            )
        results.append(
            {
                "source_id": source_id,
                "stage": stage,
                "outcome": outcome,
                "failure_class": failure_class,
                "reason": reason,
                "correlated_event_count": len(correlated),
            }
        )
    # A successful download does not imply a valid PDB or complete line info.
    if module.get("debug_status") in ("malformed", "unsupported"):
        results.append(
            {
                "source_id": "symbolicator",
                "stage": "symbolicate",
                "outcome": "failed",
                "failure_class": "permanent",
                "reason": module["debug_status"],
                "correlated_event_count": 0,
            }
        )
    return results
