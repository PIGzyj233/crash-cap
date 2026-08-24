---
status: accepted
---

# Project Symbol Health from Current Analysis

Current Analysis advances monotonically by Analysis Run creation order among COMPLETE/PARTIAL runs: an older successful run may fill an empty pointer or survive a newer failure, but it may never replace a later successful run. Symbol Health is a durable relation derived from each Occurrence's Current Analysis winner, with OperationLog retained only as append-only audit.

Identity is frozen as `symbol-identity-v2`:

- if either `debug_id` or `code_id` exists, trim, Unicode-normalize and case-fold both IDs; filenames do not split that identity;
- only when both IDs are absent, trim, Unicode-normalize, take the Windows basename and case-fold `debug_file` and `code_file` as the fallback identity;
- duplicate Canonical modules with one identity collapse deterministically, preferring mismatch reasons before missing reasons and then a stable lexical representation;
- the aggregate row ID is a deterministic hash of Workspace plus identity, so Workspaces never share a row.

Each replacement records the winning Analysis Run on every relation and writes a projection-state marker even when the missing set is empty. `first_seen`/`last_seen` use Occurrence time and never shrink when a relation clears. Manual `ignored` triage is orthogonal to the affected-occurrence count and must not be overwritten by either compatibility or projection writes.

`shadow-soft` keeps the compatibility writer authoritative and rolls back only the projection savepoint on failure. `strict-writer` and `projection-read` require compatibility audit, relation replacement, Current Analysis, Group and winner changes to commit together; a mismatch or projection failure rolls back the finalize transaction. All four public consumers (`/symbols/health`, `/symbols/missing`, Build view and batch reprocess) select one mode together. No projection read or backfill may derive current state from OperationLog.

Backfill reads the Current Analysis pointer and Canonical object, validates v1 schema plus frozen semantic context, locks the Occurrence, rechecks the pointer and then performs an idempotent replacement. Missing, corrupt or invalid objects become durable gaps. The old ID-only unique constraint is removed because it cannot represent multiple double-null filename identities. Production rollback is compatible code plus the `legacy` mode; database downgrade after split identities exist is unsupported.
