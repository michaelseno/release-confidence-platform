# ADR: Execution Evidence as Canonical Source of Truth for Audit Lifecycle

## Status

Accepted

## Date

2026-06-11

## Context

During Phase 4 validation, audit `audit_20260609_b18fee6a` transitioned to `COMPLETED` while one orphaned `STARTED` RUN record still existed in DynamoDB. The root cause was a sanitizer boundary defect: the shared `sanitize()` function in `src/release_confidence_platform/sanitization/sanitizer.py` treated the numeric segment `2475004829` within run UUID `48a87626-e2f9-4f81-82ff-2475004829ec` as phone-like PII and mutated the persisted DynamoDB `SK` and `run_id` to `48a87626-e2f9-4f81-82ff-[REDACTED]ec`. The subsequent terminal metadata update in `src/release_confidence_platform/storage/dynamodb_client.py:update_terminal(...)` used the unsanitized key, which did not match the persisted sanitized key, causing `ConditionalCheckFailedException` for both the `COMPLETED` and `FAILED` terminal update attempts. Raw S3 evidence was successfully written under the unsanitized path before the terminal update failed, leaving an S3 object with no corresponding terminal RUN record.

Separately, the finalization handler in `apps/backend/handlers/audit_finalization_handler.py` reads `execution_counters.total_completed` from the audit metadata item and uses that value — not the count of terminal DynamoDB RUN records or S3 raw evidence objects — as the basis for the `FINALIZING -> COMPLETED` lifecycle transition. The scheduled execution handler in `apps/backend/handlers/scheduled_execution_handler.py` unconditionally increments `total_started` and `total_completed` on the normal handler return path regardless of whether the orchestrator returned `status=FAILED`. This means the counter reached its expected terminal value of `25` while one RUN record remained permanently `STARTED`, and finalization proceeded to `COMPLETED` with unresolved persisted evidence.

The incident is fully documented in `docs/bugs/phase_3_phase_4_execution_integrity_rca.md`.

## Problem

The following defects contributed to the invariant violation. Each is a separate concern, but together they expose a systemic trust-boundary gap:

- Operational counters (`completedCount`, `failedCount`, `total_started`, `total_completed`) are incremented in-process by the scheduled execution handler. They are not derived from, nor durably reconciled against, the persisted RUN records in DynamoDB or the raw evidence objects in S3.
- No gate exists between `FINALIZING` and `COMPLETED` that queries persisted RUN records and verifies their terminal states before allowing the lifecycle transition.
- A RUN record can remain in `STARTED` state permanently if the terminal metadata update fails, even though the orchestrator completed its execution and wrote raw S3 evidence.
- S3 raw evidence can exist without a corresponding terminal RUN record, or a RUN record can exist in a terminal state without a corresponding S3 raw evidence object, with no mechanism to detect or block lifecycle completion in either case.
- Counter values can reach their expected terminal totals before all RUN records have been written to terminal states, because counters count scheduler occurrence handler completions — not terminal RUN record writes.
- The Phase 4 aggregation integrity gate in `src/release_confidence_platform/aggregation/integrity.py` would have detected the count mismatch (`finalization.execution_count=25` vs `len(completed_runs)=28`) but was not deployed in the target dev environment at the time of the incident. Regardless, Phase 4 is too late: the lifecycle state `COMPLETED` is externally meaningful and was already written before any downstream phase could block it.

## Decision

Persisted execution evidence — DynamoDB RUN records and S3 raw evidence objects — is the canonical source of truth for audit lifecycle state transitions. Operational counters (`completedCount`, `failedCount`, `total_starts`, `total_completed`, and any equivalent fields) are derived observability metadata only. They must never be the sole basis for any lifecycle decision, including and especially the `FINALIZING -> COMPLETED` transition.

The finalization service must evaluate a finalization integrity gate before allowing any `FINALIZING -> COMPLETED` transition. The gate is defined in detail in `docs/architecture/finalization_integrity_gate_design.md`. The gate reads persisted DynamoDB RUN records and S3 raw evidence for the target audit, evaluates all required checks, and either permits the transition or returns a structured failure report. Gate failure must block the transition; the audit must remain in `FINALIZING` until the gate passes or an explicit administrative recovery procedure is completed.

## Rationale

DynamoDB and S3 are durable, independently observable storage systems. A write that reaches these systems is verifiable by any process with read access, including administrative tools, reconciliation jobs, and downstream phases. An in-process counter is ephemeral: it is lost on process crash, subject to race conditions when multiple handler invocations run concurrently, dependent on the correctness of every counter-increment code path, and not independently auditable without replaying the execution log.

Treating persisted evidence as canonical rather than counters as authoritative provides the following properties:

- **Determinism.** The same DynamoDB query over the same data produces the same gate result regardless of which process runs it.
- **Independence.** Any observer with appropriate read permissions can validate the gate result without access to Lambda execution state.
- **Auditability.** Persisted RUN records and S3 objects produce a verifiable evidence trail. Counter values do not.
- **Crash safety.** A process crash after raw S3 write but before counter increment produces a detectable inconsistency in persisted evidence. The gate will fail; an in-process counter scheme has no record of the failure.
- **Alignment with existing platform design.** The platform already treats raw S3 evidence as the upstream input for Phase 4 aggregation. The Phase 4 integrity gate in `src/release_confidence_platform/aggregation/integrity.py` already validates `finalization.execution_count == len(completed_runs) == len(records)` before any aggregation write. This decision extends that principle upstream to the lifecycle transition boundary where it has the most impact.

This decision also aligns with write-ahead and event-sourcing principles: the event (persisted RUN record in terminal state + corresponding S3 evidence) must exist before the lifecycle state that depends on it is written.

## Consequences

### Positive

- The invariant established below is mechanically enforceable before any `COMPLETED` lifecycle write.
- Evidence inconsistencies that were previously invisible to the finalization path become explicit, structured gate failures with actionable detail.
- Administrative recovery is given a well-defined starting point: the gate failure report identifies exactly which checks failed and what evidence is inconsistent.
- Phase 4 aggregation can rely on the lifecycle state `COMPLETED` as a stronger upstream guarantee than the current implementation provides.
- Counter values remain useful for CloudWatch metrics, dashboards, and execution rate observability but are explicitly non-authoritative for lifecycle decisions.

### Constraints introduced

- Finalization must perform DynamoDB and S3 read operations as part of the `FINALIZING -> COMPLETED` transition. These reads add latency to the finalization path. At MVP audit sizes this is acceptable; large audits with thousands of run records will require pagination support in the gate implementation.
- The finalization integrity gate must be implemented as a separate pure function so it can be unit-tested in isolation from the lifecycle state machine and invoked identically in production, tests, and administrative tooling.
- Administrative reconciliation procedures that resolve orphaned STARTED records or orphaned S3 evidence must be privileged (not reachable through the normal scheduled execution or operator CLI paths), fully logged, deterministic, and non-destructive. The recovery procedure is defined in `docs/architecture/finalization_integrity_gate_design.md`.
- The sanitizer boundary defect (applying `sanitize()` to DynamoDB primary-key material and canonical identifiers) must be corrected as a prerequisite fix. Until it is corrected, gate failure will surface the symptom (orphaned STARTED records) rather than prevent it. The gate is a detection and blocking mechanism; it does not substitute for fixing the root cause.
- **Check 1 expected count derivation:** `finalization.execution_count` must be set at finalization trigger time from `len(terminal_run_records)` — the count of persisted terminal RUN records queried at that moment — not from `execution_counters.total_completed`. For audits with a repeated schedule, one occurrence produces multiple RUN records; `total_completed` counts occurrence handler completions, not RUN record writes. Using `total_completed` as the Check 1 denominator would cause spurious gate failures on every clean repeated-schedule audit. The RUN record count is the evidence-derived expected value; the counter is informational only. See the corresponding correction in `docs/architecture/finalization_integrity_gate_design.md`, Check 1.

## Invariant

The following invariant must never be violated. It is the operative constraint enforced by the finalization integrity gate:

> An audit SHALL NEVER transition to COMPLETED while any execution evidence remains unresolved. Unresolved evidence includes: any RUN record in STARTED state, any terminal RUN record without a corresponding raw S3 evidence object, and any raw S3 evidence object without a corresponding terminal RUN record.

Code paths that produce `COMPLETED` lifecycle transitions must prove compliance with this invariant through the gate defined in `docs/architecture/finalization_integrity_gate_design.md`. No other proof is sufficient.

## Alternatives Considered

### Treat operational counters as authoritative for lifecycle transitions

Rejected. Counters are incremented by handler code that runs after orchestrator return, not by DynamoDB writes. They count scheduler occurrence handler paths, not terminal RUN record writes. The incident directly demonstrates that counters can reach their expected terminal value while RUN records remain unresolved. Counters are also not independently auditable.

### Treat DynamoDB RUN records as the sole authority, ignoring S3 evidence consistency

Rejected. RUN records record `raw_result_s3_key` as part of terminal state. A terminal RUN record with a null or stale `raw_result_s3_key` is incomplete evidence. S3 raw evidence is the upstream input for Phase 4 aggregation; a terminal RUN record pointing to a missing S3 object would cause downstream aggregation failure. Both layers must be consistent.

### Treat S3 raw evidence as the sole authority, ignoring RUN record terminal state

Rejected. S3 objects are written before the terminal RUN metadata update. An S3 object that exists without a corresponding terminal RUN record is exactly the failure mode this decision is designed to detect and block. S3 alone cannot establish the intended terminal status (COMPLETED, FAILED, ERROR) of the run.

### Enforce the invariant only in Phase 4 aggregation

Rejected. The lifecycle state `COMPLETED` is externally observable and meaningful to downstream consumers before Phase 4 runs. The incident confirms that Phase 4 was not deployed in the target dev environment, meaning lifecycle completion had no downstream gating. Even when Phase 4 is deployed, an audit reaching `COMPLETED` with unresolved evidence produces a misleading release-confidence signal before any Phase 4 check executes. The enforcement boundary must be at the lifecycle transition itself.

### Add a post-completion reconciliation job instead of a pre-transition gate

Rejected. Post-completion reconciliation cannot unwrite the `COMPLETED` lifecycle transition. Once the lifecycle state is durably written, downstream consumers may have already acted on it. Prevention at the transition boundary is the only approach that preserves the invariant.

## References

- RCA: `docs/bugs/phase_3_phase_4_execution_integrity_rca.md`
- Gate design: `docs/architecture/finalization_integrity_gate_design.md`
- Phase 4 evidence lineage ADR: `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
- Phase 3 finalization cleanup ADR: `docs/architecture/adr_phase_3_finalization_completion_cleanup.md`
- Finalization handler: `apps/backend/handlers/audit_finalization_handler.py`
- Scheduled execution handler: `apps/backend/handlers/scheduled_execution_handler.py`
- DynamoDB metadata client: `src/release_confidence_platform/storage/dynamodb_client.py`
- Phase 4 integrity gate: `src/release_confidence_platform/aggregation/integrity.py`
- Sanitizer: `src/release_confidence_platform/sanitization/sanitizer.py`
