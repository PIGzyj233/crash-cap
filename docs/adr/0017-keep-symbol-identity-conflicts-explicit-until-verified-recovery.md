---
status: accepted
---

# Keep Symbol Identity Conflicts Explicit until Verified Recovery

Different byte streams can carry the same internal symbol-matching identity. On 2026-09-03 the user accepted Q15: when the available DMP identity evidence cannot select a unique binary/PDB pair and equivalence of the candidates is unproven, retain the candidates and their provenance, expose a Symbol Identity Conflict, and require verification by the artifact provider or engineering before restoring unambiguous use. Implementation is pending.

Q19–Q21 were subsequently accepted: [ADR-0019](0019-version-canonical-symbol-resolution-evidence.md) records Canonical 1.1 conflict evidence, [ADR-0020](0020-resolve-global-symbols-with-dump-relevant-evidence.md) records deterministic raw PE/PDB content grouping, and [ADR-0021](0021-promote-current-analysis-by-versioned-evidence.md) records Current evidence comparison and correction. The [implementation design](../design.md) retains the pending contract and qualification work. Accepted decisions do not indicate implemented behavior.

The first delivery isolates the affected module in new analyses: report its symbol conflict while other modules continue to produce useful evidence. Do not overwrite a candidate or select by upload order, the first candidate, or the latest version. QA users see the reason and a recovery path without having to judge byte equivalence. Different hashes alone do not prove corruption; automatically resolving equivalent byte variants is outside the first delivery. Identical verified binary/PDB bytes from multiple sources can represent the same evidence while retaining those sources and their Workspace ownership.

Recovery must establish and record the basis for a uniquely usable pair. Matching, unwind, symbol retrieval, and the immutable Analysis Run must agree on that exact pair under both filesystem and HTTP symbol-source modes. Historical Runs remain available, and later recovery is expressed through new analysis evidence. This policy preserves the exact Build bindings and sealed inventories in ADR-0010 and ADR-0011.

The trade-off is explicit partial results and provider involvement when identities are ambiguous, in exchange for avoiding a plausible-looking stack built from an arbitrary candidate. Normal coexistence of different internal identities remains supported under the platform-wide catalog in [ADR-0018](0018-search-uploaded-symbol-pairs-platform-wide.md). A Workspace source preference cannot resolve an otherwise ambiguous identity, and multiple copies of the same verified binary/PDB content are not themselves a conflict.
