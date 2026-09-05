# Durable task failure matrix

Applies to the upload v3 task protocol and frozen Canonical 2.0 analysis.

The target transport is at-least-once. “Duplicate allowed” below means duplicate delivery is allowed; duplicate domain side effects are never allowed. `attempt_id` identifies one logical task attempt and a reclaim increments its execution generation.

## Common crash points

| Crash point | Expected durable state | Automatic recovery | Duplicate delivery | Stale output rule |
| --- | --- | --- | --- | --- |
| Before domain transaction commits | Neither domain change nor task intent exists. | Caller may retry with the same idempotency input. | No | No output is valid. |
| After domain change but before transaction commit | Neither change is visible. | Database rollback, then caller retry. | No | No output is valid. |
| After commit, before relay publish | Domain change and pending intent both exist. | Relay selects the due intent. | No | No owner exists. |
| After publish, before relay ack | Intent remains publishable and Redis may contain a message. | Relay republishes and fenced consumer absorbs duplicate. | Yes | Only a claimed current generation may act. |
| After relay ack, before Worker claim | Intent is published; no execution owner exists. | Redis redelivery or reconciliation. | Yes | No output is valid. |
| After claim, before long work | Current generation and lease exist. | Heartbeat or lease-expiry reclaim. | Yes | Prior generations are stale. |
| During Core, RustFS, or Symbolicator work | Current generation remains durable; no database lock is held. | Retry while lease is live, otherwise reclaim with generation +1. | Yes | Generation-scoped objects from stale owners become orphans. |
| After object write, before finalize | Generation-scoped object may exist but no winner reference exists. | Current owner retries finalize; orphan inventory later finds abandoned objects. | Yes | Object is unreadable through winner paths until fenced finalize. |
| After finalize commit, before broker ack | Terminal outcome and projections are committed. | Redelivery observes terminal/current outcome and no-ops. | Yes | No second side effect or follow-up intent. |
| Poison schema, task, or queue | Intent is marked DEAD with a permanent reason. | Operator repairs or supersedes it; no infinite retry. | No | No owner may execute unknown work. |

## Task-specific invariants

| Task type | Logical target/key | Finalize guard | Follow-up or projection atomically written | Recovery-specific rule |
| --- | --- | --- | --- | --- |
| `verify_upload` | Upload ID | Current generation and Upload still `VERIFYING`. | File acceptance and scope binding, or DumpBlob/Occurrence/Submission plus analysis demand. | Redelivery cannot create a second accepted binding or Occurrence. Missing a pair is successful file acceptance. |
| `dispatch_workspace_role` | Workspace + role version | Current task generation and persisted Workspace policy. | Bounded analysis demand for matching modules in that Workspace. | Redelivery coalesces the same policy change; other Workspaces are untouched. |
| `analyze_frozen_run` | Analysis Run ID | Current generation, immutable Run context, and semantic validator. | Winner object, summary, CurrentDecision, Group, Symbol projection, audit. | Old success/failure cannot overwrite a newer winner or move Current backward; evidence comparison decides promotion. |

## Lease calibration

Lease, heartbeat, backoff and orphan retention values must cover the configured workload and bounded I/O deadlines. Tests use injected clocks and short leases to exercise reclaim and stale-write fencing; they do not prescribe production durations.
