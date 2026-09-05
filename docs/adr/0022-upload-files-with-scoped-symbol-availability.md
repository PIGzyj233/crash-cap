---
status: accepted
---

# Upload Individual Files into a Workspace or the Public Area

On 2026-09-05 the user chose to replace the Build publication model with individual file uploads and optional version labels. A caller supplies files and their destination; no Build, Manifest, repository, role inventory or sealed publication is required. PE and PDB files may arrive in different submissions. Server-verified content identity still determines whether they can be used together.

Every Workspace consumes its own files plus public files. Both halves of a pair must be visible to that consumer. Public/private mixed pairs are usable only in the private half's Workspace; two private halves in different Workspaces cannot be combined. Physical content reuse does not grant availability. Distinct valid content under the same captured identity remains an explicit conflict, including conflicts between public and Workspace candidates.

A version is a user-declared label. Artifact labels organize uploaded files; an Occurrence's label determines its version filters and statistics. They do not infer one another. Repeated submissions preserve the existing nonempty Occurrence label, record differing submissions, and permit explicit audited edits without reanalysis. An empty label can be filled by the first nonempty submission. Workspace-plus-dump-content deduplication remains unchanged.

Workspace uploads provide the default owned classification; public-only inputs default to dependency. Explicit Workspace declarations take precedence, system exclusions remain in force, and absent evidence remains unknown. Classification and symbol-selection changes produce new immutable analyses. Version-label changes do not affect analysis inputs.

This decision supersedes ADR-0010's Build lifecycle, ADR-0011's Workspace-bound artifact model, ADR-0015's same-submission pair requirement and ADR-0018's unconditional global availability. It also replaces the corresponding Build-specific input and Canonical rules in ADR-0012, ADR-0019 and ADR-0020. The retained principles are exact identity selection before materialization, frozen analysis evidence, fenced task execution and evidence-based Current promotion.

The HTTP interface becomes v3 and Canonical becomes 2.0 without Build resolution. Deployment starts from a new empty database after retaining project data and old images for whole-version rollback. There is no old-client, old-data or mixed-image compatibility layer. Source bundles are outside this upload model.
