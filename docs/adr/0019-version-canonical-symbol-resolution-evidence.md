---
status: accepted
---

# Version Canonical Symbol Resolution Evidence

Q19 was accepted on 2026-09-03. Publish Canonical 1.1 to represent symbol-identity conflicts, frozen pair selection and candidate evidence, availability reasons, structured source outcomes, and the unwind provenance required for evidence comparison. These are analysis facts owned by Core under ADR-0007; translating a conflict into an old missing-symbol status would misstate the evidence. Implementation and contract qualification remain pending.

Preserve Canonical 1.0 schemas and historical objects. A new reader must understand both 1.0 and 1.1; an unchanged strict 1.0 reader is not expected to accept 1.1. Database constraints, Worker validation, semantic validation, API/OpenAPI, and frontend readers must be compatible before enabling new writes. Rollback disables new writes while retaining the compatible reader. Future directory actions and platform Current decisions remain separate from an immutable Run's Canonical facts.

The trade-off is a coordinated version transition instead of a UI-only workaround. The [implementation design](../design.md) defines the accepted evidence requirements; the [implementation guide](../upload-v3-guide.md) maintains rollout and pending gates, including actual per-module source diagnostics and continuity from historical Current results. Acceptance records the decision, not a published schema or passing compatibility test.

> 2026-09-05: Build, complete-batch pairing, unconditional global sharing and corresponding Canonical rules are superseded by [ADR-0022](0022-upload-files-with-scoped-symbol-availability.md). Retained identity, freezing and Current protections follow [the current design](../design.md).
