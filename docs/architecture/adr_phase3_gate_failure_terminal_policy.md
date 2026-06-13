# ADR: Gate Failure Produces FAILED Terminal State (Phase 3 Finalization)

**Status:** Accepted
**Date:** 2026-06-13
**Branch:** bugfix/phase3-running-after-window-rca-v2

## Context

The Phase 3 finalization handler uses a one-time EventBridge Scheduler `at()` expression
to trigger lifecycle finalization at audit window end. The finalization integrity gate
(`finalization_integrity_gate()`) must pass before the audit transitions to COMPLETED.

When the gate fails (due to STARTED run records, missing S3 evidence, or counter
mismatches), prior to this fix the handler returned a `gate_failure` response and left
the audit in `FINALIZING` permanently — since the one-time schedule is deleted after the
first invocation (`ActionAfterCompletion=DELETE`) and no component re-triggers finalization.

Three options were evaluated (documented in `docs/bugs/phase3_lifecycle_determinism_rca.md`):

- **Option A**: Auto-timeout STARTED runs before the gate. Rejected: requires a run-record
  write method that does not exist on `AuditMetadataRepository`, and the finalization
  handler does not own run record state (the scheduled execution handler does).
- **Option B**: Transition to FAILED on gate failure. Accepted (this ADR).
- **Option C**: Add a repair re-invocation mechanism. Rejected: disproportionate
  infrastructure scope for this defect.

## Decision

On any finalization integrity gate failure, the handler transitions the audit from
`FINALIZING` to `FAILED` (a terminal state) via the existing `FINALIZING → FAILED`
state machine transition. The `gate_failure` status is preserved in the response for
observability, but `lifecycle_state` is always a terminal state after gate failure.

This applies uniformly to all gate failure causes including `NO_ORPHANED_STARTED_RECORDS`,
`EVERY_TERMINAL_RUN_HAS_EVIDENCE`, `TERMINAL_COUNT_MATCHES_EXPECTED`,
`COUNTER_RECONCILIATION`, and any combination.

## Consequences

**Positive:**
- Lifecycle is deterministic: audits always exit `FINALIZING` to either `COMPLETED` or
  `FAILED`. The permanent-stuck `FINALIZING` state is eliminated.
- No new infrastructure dependencies, no new constants, no new repository methods.
- Idempotent: re-invocation after `FAILED` returns `skipped` via the terminal state check.

**Negative / Trade-offs:**
- `FAILED` is a terminal state with no automated recovery. An audit where a single run
  was genuinely in-flight at window close will be marked `FAILED` even if the run
  completed successfully seconds later. Operators must create a new audit to re-execute.
- If partial-completion semantics are ever required, this ADR must be revisited and
  Option A re-evaluated with a run record update method added to the repository.

## LifecycleConflictError Safety Note

`AuditMetadataRepository.append_lifecycle_transition()` raises `LifecycleConflictError`
exclusively for DynamoDB `ConditionalCheckFailedException` (state mismatch). All other
`ClientError` types propagate as `StorageError`. This means if a concurrent invocation
already advanced the state, `LifecycleConflictError` propagates from
`_fail_gate_failure_finalization()` — which is correct (the concurrent invocation won
the race and the state is already advanced).
