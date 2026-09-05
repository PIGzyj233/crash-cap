---
status: accepted
---

# Select Analysis Inputs Before Materializing Artifact Bytes

An Analysis Run freezes the complete Workspace Build and Artifact inventory, but after Dump inspection the Worker materializes only a reported Build, exact `code_id`/`debug_id` candidate modules, their PE/PDB pairs, and candidate source bundles. Shared Artifact Blobs are copied once by Workspace-scoped SHA-256, while `dmp-core` remains the sole authority for final `reported`, `auto_unique`, `ambiguous`, or `unresolved` Build Resolution. This keeps a Build hint optional, preserves reproducibility and byte verification, and prevents Workspace history from making one analysis perform unbounded artifact I/O; filename, Version, publication order, and “latest Build” are never selection evidence.

> 2026-09-05: Build, complete-batch pairing, unconditional global sharing and corresponding Canonical rules are superseded by [ADR-0022](0022-upload-files-with-scoped-symbol-availability.md). Retained identity, freezing and Current protections follow [the current design](../design.md).
