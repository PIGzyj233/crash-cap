---
status: accepted
---

# Identify Builds by Content and Track Publications by Origin

A Build represents one exact Manifest and PE/PDB byte set. For new publications the API computes `build-content-v1` from canonical JSON for the stable Build Manifest plus the sorted tuple `(kind, logical_name, size, sha256)` for every expected PE/PDB. Client-supplied identities are hints only. The Workspace, fingerprint version and content fingerprint are unique, so concurrent and cross-origin submissions of identical content converge on one Build while any Manifest, role, filename, size or byte change creates a different Build.

A Build Publication records one idempotent `local` or `ci` publishing act and points to the resulting Build. Publication origin is deliberately separate from Artifact Producer: `local` and `ci` describe how bytes arrived, while `msvc` describes the artifact format and validation capability. A repeated `(Workspace, origin, client_publication_id)` must resolve to the same content or fail as an idempotency conflict.

Every content-identified Build stores an exact Expected Artifact inventory. Upload initialization may address only an expected logical name and must agree with its declared size and SHA-256. Worker verification uses the received bytes, not client hints. A Build becomes Ready and is sealed only when every expected PE/PDB has a verified matching Artifact; after sealing its Manifest and Artifact set cannot change. Browser upload remains a recovery mechanism for missing expected files, never a way to extend the set.

Existing Builds remain `legacy`. We do not derive fingerprints or invent Publications from historical logs or Artifacts because the original declaration and exact publication act cannot be proven. Stable legacy Manifest, CI status and browser-upload HTTP entry points remain readable and operational. The rollout is additive and feature-gated; rollback disables new registration and UI entry points without deleting schema or content Builds, and database downgrade after content Builds exist is unsupported.

> 2026-09-05: Build, complete-batch pairing, unconditional global sharing and corresponding Canonical rules are superseded by [ADR-0022](0022-upload-files-with-scoped-symbol-availability.md). Retained identity, freezing and Current protections follow [the current design](../design.md).
