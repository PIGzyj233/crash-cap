---
status: accepted
---

# Select Analysis Inputs Before Materializing Artifact Bytes

An Analysis Run freezes the complete Workspace Build and Artifact inventory, but after Dump inspection the Worker materializes only a reported Build, exact `code_id`/`debug_id` candidate modules, their PE/PDB pairs, and candidate source bundles. Shared Artifact Blobs are copied once by Workspace-scoped SHA-256, while `dmp-core` remains the sole authority for final `reported`, `auto_unique`, `ambiguous`, or `unresolved` Build Resolution. This keeps a Build hint optional, preserves reproducibility and byte verification, and prevents Workspace history from making one analysis perform unbounded artifact I/O; filename, Version, publication order, and “latest Build” are never selection evidence.
