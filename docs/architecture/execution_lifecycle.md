# Execution Lifecycle

## Lifecycle States

An audit progresses through the following lifecycle states:

```
DRAFT → SCHEDULED → RUNNING → FINALIZING → COMPLETED
                                         ↘ FAILED
```

State transitions are persisted to the audit metadata item with actor, reason, and timestamp recorded in `lifecycle_history`.

## Completion Invariant

**An audit SHALL NEVER transition to `COMPLETED` while any execution evidence remains unresolved or internally inconsistent.**

This invariant is enforced mechanically by the finalization integrity gate before every `FINALIZING → COMPLETED` transition. The gate checks:

1. No `RUN` records remain in `STARTED` state
2. Every terminal `RUN` record has a non-null `raw_result_s3_key`
3. Every S3 evidence object maps to exactly one terminal `RUN` record
4. Counter values are consistent with persisted evidence

Any gate failure blocks the `COMPLETED` transition. The audit remains in `FINALIZING` and requires administrative recovery before completion can proceed.

See `docs/architecture/finalization_integrity_gate_design.md` for the full gate specification.

## Evidence Source of Truth

Persisted execution evidence is the canonical source of truth for all lifecycle, aggregation, and release-confidence decisions:

- **DynamoDB `RUN` records** — authoritative for execution status, terminal metadata, and evidence linkage
- **S3 raw result objects** — authoritative for raw endpoint execution evidence
- **Audit lifecycle state** — derived from reconciled evidence, not from operational counters

Operational counters (`execution_counters.total_completed`, etc.) are observability metadata only. They must never be used as the sole authority for lifecycle transitions, aggregation eligibility, or release-confidence conclusions.

See `docs/architecture/adr_execution_evidence_source_of_truth.md` for the full decision record.

## Traceability

All lifecycle and execution artifacts are traceable by these canonical identifiers:

- `client_id`
- `audit_id`
- `run_id`
- `endpoint_id`
- `scenario_id`
- `raw_result_version`

Canonical identifiers are generated at the system boundary and must remain immutable through all persistence, logging, and processing steps. They must not be passed through PII redaction layers before DynamoDB writes or S3 key construction.

See `docs/architecture/adr_sanitization_boundary.md` for the sanitization boundary decision.

## Execution Order

Audit execution preserves this order:

1. Resolve approved client/audit/endpoint configuration.
2. Create a run context with an immutable `run_id`.
3. Persist `RUN` record as `STARTED` using the unsanitized canonical key.
4. Execute endpoint scenarios deterministically.
5. Persist raw evidence to S3 under the canonical `run_id` path.
6. Update `RUN` record to terminal state (`COMPLETED` or `FAILED`) with `raw_result_s3_key`.
7. Update occurrence claim and execution counters based on the terminal `RUN` status.

Steps 5 and 6 are ordered intentionally: raw evidence is written before the terminal metadata update. If the metadata update fails after step 5, the raw evidence is preserved and the `RUN` record remains `STARTED` — this is detectable by the finalization integrity gate.

## Finalization

Finalization is triggered by an EventBridge schedule at the end of the audit window. Before `FINALIZING → COMPLETED`, the finalization integrity gate reconciles all persisted evidence. `finalization.execution_count` is set from the count of terminal `RUN` records at gate evaluation time — not from `execution_counters.total_completed`.

## Phase 0 Note

Phase 0 did not implement audit execution. The lifecycle and invariants above were established during Phase 3/4 implementation and hardened through the execution integrity remediation (`bugfix/execution-integrity-remediation`).
