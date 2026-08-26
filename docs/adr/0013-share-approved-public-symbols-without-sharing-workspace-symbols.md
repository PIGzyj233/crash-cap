---
status: accepted
---

# Share approved public symbols without sharing Workspace symbols

Crash-Cap uses one Symbolicator request ordered as Workspace-private, company-approved, then Microsoft public sources. The Gateway consumes the Workspace scope to select a private source whose stable identity includes the Workspace and inventory version, but does not forward that scope into Symbolicator's global cache namespace; the Microsoft source keeps one deployment-owned stable source ID. This lets Microsoft downloads and derived caches be reused across Workspaces while private lookups remain separated by source identity, avoids a second symbolication request, and keeps request-owned source URLs forbidden. Terminal Canonical warnings must be reconciled with Symbolicator's final module status so a successfully found or unused public symbol is never reported as pending or missing.
