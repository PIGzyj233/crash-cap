---
status: accepted
---

# Promote Current Analysis by Versioned Evidence

Q21 was accepted on 2026-09-03. Use a versioned evidence-v1 decision rule for automatic symbol refresh, retaining the platform's single Current Analysis authority and creation-order invariant from ADR-0009. Compare compatible immutable analysis contexts, precise fault and business-frame anchors, unwind provenance, and function/file/line evidence. Aggregate quality scores, frame counts, and folded trust weights cannot substitute for this comparison. Implementation and qualification remain pending.

Apply Q7/Q16 from ADR-0015: preserve the previous useful Current when identified temporary failures remove key business evidence; permit a new result with strict business improvements and preserved key evidence when its remaining losses are only explicitly temporary system-symbol information. Retain the diagnostic Run and use bounded retries. Incomparable candidates retain the previous Current, the new candidate, and an explicit difference/reason; they are not guessed into a winner or retried indefinitely.

Verified contradictory evidence, identity conflicts, or withdrawal of supporting pairs use an auditable Evidence Correction path. A lower-scoring reliable interpretation may replace the earlier one. If expired raw DMP evidence prevents recomputation, visibly identify the withdrawn basis and inability to recompute while preserving history. Protection from temporary service failures must not present disproved evidence as still verified.

The comparator returns its version, decision, reason, and evidence differences. Under the Occurrence lock and execution fencing, recheck the Current pointer and commit promotion, Group, Symbol Health, and audit consistently; recompare if the pointer changed. Role changes and engine or contract transitions have explicit causes and compatibility rules rather than being silently treated as symbol refresh. The [implementation design](../qa-symbol-import-implementation-design.md) defines anchors and outcome branches; the [implementation guide](../qa-symbol-import-guide.md) maintains required legacy-continuity, concurrency, and rollout gates.

The trade-off is conservative retention and visible review for incomparable evidence instead of always promoting the newest COMPLETE/PARTIAL Run. Historical Runs remain immutable, and each displayed report contains one Run's evidence.
