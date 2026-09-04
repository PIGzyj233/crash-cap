---
status: superseded
---

# Share Components through Explicit Workspace References

Superseded on 2026-09-03 by [ADR-0018](0018-search-uploaded-symbol-pairs-platform-wide.md). The user clarified that symbols should be searchable across the whole platform while owned/dependency roles remain local to each Workspace. Explicit sharing and consumer references are therefore removed from the current direction. The historical decision below was superseded before implementation; independent Workspace roles remain part of the new direction.

A common component may be needed by several product Workspaces. On 2026-09-03 the user initially accepted this direction: import complete pairs into an owning Workspace, mark the component as shareable, and let consumers enable a Shared Component Reference. Q14 confirmed automatic availability of newly shared identities. This historical proposal was superseded before implementation; current rules are in ADR-0018 and the [implementation design](../qa-symbol-import-implementation-design.md).

The owning Workspace retains the verified bytes and their provenance. Consumers use the declared shared component through their references rather than independently uploading its large PDBs. Making a component shareable does not expose every artifact or Build of its owning Workspace, and sharing symbol evidence does not associate the consumer's DMP with the provider's Build or release version.

An active reference includes the component's existing and subsequently published complete, verified, explicitly shared symbol pairs. A newly available identity automatically enters the consumer's analysis candidates and triggers reanalysis only for affected DMPs. Older pairs are retained, and every DMP selects by its own exact identity evidence; the newest component version never substitutes for an older captured binary. [ADR-0017](0017-keep-symbol-identity-conflicts-explicit-until-verified-recovery.md) governs unresolved conflicts among matching byte variants.

Each consuming Workspace maintains its own business-role declaration. The browser visibly defaults ordinary product imports to an owned module and shared-component references to a dependency, and permits a local override or an unknown classification. The role controls business-frame interpretation and grouping; it does not replace binary/PDB identity verification. The same component can therefore be business code in one Workspace and a dependency in another.

This explicitly qualifies ADR-0011's original prohibition on cross-Workspace reuse for designated shared components. Blob ownership and Workspace-scoped SHA identity remain intact, ordinary private imports remain scoped, and this decision introduces neither global SHA deduplication nor automatic scanning of other Workspaces. Existing Build Manifest, expectation, Artifact binding, and sealing guarantees remain intact.

The existing deployment-level company-sdk Symbolicator source is not an implementation of this decision. The analysis path must carry the reference and exact verified PE/PDB evidence into input selection, local unwind, symbol retrieval, and the immutable Analysis Run record. Matching evidence and business roles must use the consuming Workspace's scope.

The trade-off is explicit ownership and reference management instead of repeated large uploads or implicit deployment-wide symbol discovery. Reference snapshots, input selection, and symbol retrieval still need implementation and validation. The default scope of migrating an existing owned module into a shared component is a separate pending product decision.
