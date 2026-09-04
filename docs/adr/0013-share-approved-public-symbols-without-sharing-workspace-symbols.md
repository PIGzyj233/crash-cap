---
status: accepted
---

# Share approved public symbols without sharing Workspace symbols

Crash-Cap uses one Symbolicator request ordered as Workspace-private, company-approved, then Microsoft public sources. The Gateway consumes the Workspace scope to select a private source whose stable identity includes the Workspace and inventory version, but does not forward that scope into Symbolicator's global cache namespace; the Microsoft source keeps one deployment-owned stable source ID. This lets Microsoft downloads and derived caches be reused across Workspaces while private lookups remain separated by source identity, avoids a second symbolication request, and keeps request-owned source URLs forbidden. Terminal Canonical warnings must be reconciled with Symbolicator's final module status so a successfully found or unused public symbol is never reported as pending or missing.

## Accepted amendment, implementation pending

[ADR-0018](0018-search-uploaded-symbol-pairs-platform-wide.md) replaces the uploaded-symbol lookup boundary with a platform-wide catalog. Its source identity, inventory version, HTTP lookup, and filesystem representation must consistently represent that catalog, including invalidating stale misses when verified pairs become available. Microsoft public caching retains its stable deployment-owned source identity, and request-owned source URLs remain forbidden. Source bundles, Workspace business records, and external publication of uploaded bytes are outside this expansion. The implementation still uses the original Workspace-private source path described above.
