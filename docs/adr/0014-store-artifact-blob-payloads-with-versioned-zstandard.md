---
status: accepted
---

# Store Artifact Blob Payloads with Versioned Zstandard Encoding

## Context

ADR-0011 defines an Artifact Blob by `(workspace_id, server-verified raw SHA-256)` and keeps
every Build's exact Artifact expectations. The first implementation stores the canonical object as
uncompressed PE/PDB bytes. That removes cross-Build duplication inside one Workspace, but it leaves
large full PDBs uncompressed and requires every reader to understand the canonical object layout.

The storage encoding must not become the business identity. It must also remain possible to deploy
read support before write support, retain a bounded rollback window, and reject corrupt or oversized
payloads before they can reach symbol publication or analysis.

## Decision

`ArtifactBlob.sha256`, `size`, `kind`, `code_id`, and `debug_id` continue to describe the verified
raw PE/PDB bytes. Payload storage is an additive projection with these fields:

- `payload_format_version = artifact-blob-payload-v1`;
- `payload_encoding = identity | zstd-v1`;
- `payload_size` and `payload_sha256` describe the stored object bytes;
- `payload_object_key` identifies the stored object and is never returned by ordinary APIs;
- `payload_verified_at` records completion of stored-byte and raw-byte verification.

Existing rows are backfilled as `identity`; their current `object_key`, `size`, and `sha256` remain a
valid compatibility projection. New compressed objects use
`artifact-blobs-v2/{workspace_id}/{raw_sha256[0:2]}/{raw_sha256}/zstd-v1`. PostgreSQL is authoritative;
object metadata is recovery evidence only.

All readers use one `BlobMaterializer`. It verifies the stored size and SHA-256, decodes with a
bounded streaming codec into an atomic temporary file, then verifies the raw size and SHA-256 before
publishing the path. PE output is limited to 512 MiB and PDB output to 2 GiB. Truncated frames,
additional frames or trailing bytes, checksum failures, declared-size mismatches, output-limit
violations, and temporary-capacity failures are hard errors. A sealed Build is not unsealed when a
payload is missing or corrupt; the incident is reported and repaired from an explicitly retained
copy or backup.

`zstd-v1` is frozen to python-zstandard 0.25.x, Zstandard level 6, frame checksum enabled, content
size enabled, one compression thread, a 64 MiB decoder window limit, and 1 MiB streaming chunks.
Changing any profile attribute requires a new encoding name. The raw identity does not depend on
deterministic compressed bytes, but each stored payload is hashed and verified after writing.

Rollout order is mandatory:

1. additive migration and `identity|zstd-v1` readers;
2. identity Writer with reader observation;
3. compression shadow Writer that reads back but does not bind the zstd payload;
4. compression active for a bounded Workspace cohort while retaining raw rollback copies;
5. backfill and recovery drills;
6. exact, default-dry-run cleanup only after at least two release cycles and 14 days.

The compression switch is `off|shadow|active`. Returning it to `off` stops new compressed writes;
it never rewrites or deletes existing zstd payloads. Once a zstd-only Blob exists, database downgrade
and rollback to a reader without this ADR are unsupported.

The long-term symbol supply path is an internal, deployment-owned HTTP source scoped by Workspace
and published Blob-pair identity. It accepts neither arbitrary object keys nor caller-provided URLs.
Filesystem Unified symbols remain the rollback source until fixed Symbolicator 26.7.2 HTTP-source
UAT, Canonical equivalence, cache recovery, and the cleanup grace period all pass.

Terminal Upload payload cleanup is a separate lifecycle. It retains the Upload row and audit trail,
requires a verified downstream authoritative object, excludes any active transfer/task lease, uses
fenced claims, and defaults to dry-run. Accepted payloads are retained for 24 hours and rejected or
quarantined payloads for 7 days; both values are bounded configuration with deployment audit.

## Consequences

- Full PDB fidelity, Workspace isolation, immutable Build manifests, and Occurrence semantics do not
  change.
- Old clients and delivery-v1 remain compatible because wire encoding and canonical storage encoding
  are independent decisions.
- Direct reads of `Artifact.object_key` or `ArtifactBlob.object_key` are compatibility debt and must
  be removed before zstd-only cleanup.
- During rollout, compressed payload plus retained raw rollback data can temporarily consume more
  space; no cleanup Gate may treat that overlap as a failure.
- Raw canonical, Upload, Unified, and Symbolicator cache cleanup have independent eligibility and
  evidence. None may infer safety from a prefix or from Build `sealed_at` alone.
