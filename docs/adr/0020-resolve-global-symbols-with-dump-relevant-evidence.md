---
status: accepted
---

# Resolve Global Symbols with Dump-Relevant Evidence

Q20 was accepted on 2026-09-03. Add a Workspace-independent symbol catalog for complete imports and references to existing verified content, preserving legacy Workspace+SHA Blob identities and exact Build bindings. Group validated candidates by the raw PE/PDB hash combination: one compatible content group is selectable, multiple distinct groups are a conflict, and additional origins for identical content do not create ambiguity. Incomplete enumeration or validation cannot establish uniqueness. Implementation remains pending.

Use a Symbol Evidence Fingerprint for the selection evidence relevant to each DMP, separately from the global catalog revision and the complete immutable manifest digest. Unrelated uploads and healthy same-content origin additions do not change that fingerprint. Catalog revisions support consistent reads, event ordering, and reconciliation; they are not a universal Run-key dependency. Content-stable symbol sources must return the exact selected pair, consistently with Core matching and unwind.

Plan an Analysis Demand by inspecting the DMP and freezing a Symbol Resolution Manifest before creating its immutable Run. Use the relevant fingerprint, consuming Workspace context, versioned algorithms, and controlled demand generations and retry attempts for idempotency. A unique-to-conflict-to-unique transition may require a new Run even when its content fingerprint returns to an earlier value; returning an older non-promotable Run is insufficient. Workspace roles, Build candidates, and source-bundle policy remain local.

Dispatch affected Occurrences through an exact-identity index and durable demands. The accepted initial automatic concurrency defaults are two globally and one per Workspace, within actual deployment capacity. Excess work remains queued; the 30/60-second coalescing bounds exclude queue and execution time. Page sizes and concurrency are configurable and require load qualification. Symbols are retained long term; evidence-backed logical withdrawal and recovery retain bytes and audit history without introducing physical symbol deletion or automatic symbol GC.

The trade-off is an explicit catalog and planning lifecycle rather than broad Workspace-version invalidation or simply removing Workspace filters. Storage, idempotency, cache invalidation, source paths, input selection, immutable Runs, and affected-demand dispatch must agree at enablement. The [implementation design](../design.md) records the data model, deterministic algorithm, and defaults; the [implementation guide](../upload-v3-guide.md) maintains pending real-Symbolicator, concurrency, and rollout gates. Compatible stages may be delivered separately before enabling the complete feature.

> 2026-09-05: Build, complete-batch pairing, unconditional global sharing and corresponding Canonical rules are superseded by [ADR-0022](0022-upload-files-with-scoped-symbol-availability.md). Retained identity, freezing and Current protections follow [the current design](../design.md).
