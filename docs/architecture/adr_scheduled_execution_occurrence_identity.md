# ADR: Scheduled Execution Occurrence Identity

## Status

Accepted

## Context

The scheduled execution RCA (`docs/bugs/scheduled_execution_orchestration_rca.md`) found that recurring EventBridge Scheduler `rate(...)` baseline schedules invoke `scheduledExecution` with a static target payload. Because the payload includes a static `schedule_occurrence_id`, every recurring fire for the same schedule attempts to claim the same DynamoDB occurrence key:

`PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#OCCURRENCE#{schedule_occurrence_id}`

After the first claim exists, later intended baseline executions are classified as duplicate deliveries and return `duplicate_skipped` before `CoreEngineOrchestrator.run(...)`. Manual `rcp audit run` uses a separate direct orchestration path and works; this decision must not change manual execution behavior.

The approved fix direction is to replace recurring baseline `rate(...)` scheduling with bounded one-time `at(...)` schedules, one per intended occurrence in the audit window, and to generate deterministic occurrence identity per intended occurrence.

## Decision

Baseline scheduling will use discrete bounded EventBridge Scheduler `at(...)` schedules for each intended baseline occurrence within the audit window instead of one recurring `rate(...)` schedule.

For each generated baseline occurrence schedule:

- `scheduled_at` identifies the intended UTC occurrence time.
- `schedule_occurrence_id` identifies the intended occurrence, not the schedule definition.
- The occurrence ID must be deterministic for the same client, audit, schedule type, scenario type, and intended scheduled time.
- Recommended clear-text format is `{client_id}:{audit_id}:{schedule_type}:{scenario_type}:{scheduled_at_iso}`. If this exceeds validation or storage constraints, use a deterministic hashed equivalent over the same canonical fields.
- EventBridge retries or duplicate deliveries for the same one-time schedule must reuse the exact same `schedule_occurrence_id` and therefore hit the same occurrence claim.
- Distinct intended occurrences must have distinct `schedule_occurrence_id` values and therefore distinct occurrence claim keys.

Schedule names for discrete baseline occurrences must also be deterministic and collision-resistant. Use the existing naming/truncation pattern, extended with occurrence identity input. A practical shape is:

`rcp-{stage}-{client_id}-{audit_id}-{schedule_type}-{scenario_type}-{occurrence_token}`

where `occurrence_token` is derived from `scheduled_at` in UTC (compact timestamp or deterministic hash). If the full name exceeds the AWS Scheduler name limit, keep the existing deterministic hash-suffix truncation behavior and include the occurrence fields in the hash input.

Cancellation and rollback cleanup must iterate every persisted schedule metadata entry, including every discrete baseline occurrence schedule. Cleanup remains delete-first, disable-fallback, bounded-retry, sanitized-error recording.

Scheduled execution observability must be made Lambda-visible and must include these log event names on the relevant paths:

- `scheduled_execution_handler_started`
- `event_contract_validated`
- `occurrence_claim_attempted`
- `occurrence_claim_created`
- `duplicate_occurrence_skipped`
- `orchestrator_execution_started`
- `orchestrator_execution_completed`
- `raw_results_written`
- `run_metadata_written`
- `scheduled_execution_failed`

## Alternatives Considered

### Keep `rate(...)` and static occurrence ID

Rejected. This is the proven root cause: all recurring fires reuse the same occurrence key, so later intended executions are skipped as duplicates.

### Keep `rate(...)` and derive occurrence ID in the handler from Lambda wall-clock time

Rejected for the current fix. Handler-side wall-clock bucketing adds ambiguity for retries near bucket boundaries, delayed deliveries, scheduler jitter, and Lambda clock/current-time differences. It would require careful tolerance rules to decide whether a retry belongs to the original occurrence or a new bucket. That complexity is unnecessary for the bounded 48-hour audit window.

### Use discrete `at(...)` schedules per intended occurrence

Selected. This moves occurrence identity to schedule creation time, where the intended occurrence time is known and deterministic. It preserves simple conditional-write idempotency and makes retries naturally reuse the same payload.

Tradeoff: this creates more EventBridge Scheduler resources per audit. The current MVP audit window is bounded at 48 hours and baseline cadence defaults to 15 minutes, so the resource count is finite and predictable. Scheduling validation and cleanup must account for the expanded schedule set.

## Consequences

Benefits:

- Distinct intended baseline occurrences can each start orchestration.
- EventBridge duplicate delivery protection remains intact through the existing occurrence claim model.
- Occurrence identity is deterministic, auditable, and independent of Lambda wall-clock timing.
- Manual `rcp audit run` remains unchanged because this decision only changes scheduled baseline schedule generation and scheduled handler observability.

Costs and implementation impacts:

- Baseline schedule creation now produces multiple `ScheduleDefinition` records instead of one recurring definition.
- Audit schedule metadata may contain many baseline entries; cancellation/rollback must process all of them.
- Tests and existing assumptions expecting a single `rate(15 minutes)` baseline definition must be updated.
- AWS Scheduler quotas and per-audit schedule-count caps must be considered during schedule validation.

Risks:

- Partial schedule creation failures are more likely because more resources are created; rollback behavior must remain robust.
- Schedule name truncation must include occurrence fields in its stable hash input to avoid collisions between occurrences.
- Cleanup/reporting code that assumed one baseline schedule per audit may miss discrete occurrence schedules unless it iterates persisted metadata.

## Traceability

- RCA: `docs/bugs/scheduled_execution_orchestration_rca.md`
- Technical design: `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- Approved fix direction: replace recurring `rate(...)` baseline scheduling with bounded `at(...)` schedules and deterministic per-occurrence `schedule_occurrence_id` values.
- Required validation coverage: distinct occurrence IDs for distinct baseline occurrences, duplicate delivery skip for the same occurrence, scheduled handler orchestration call, raw result and run metadata side effects, required logs, and cleanup across multiple discrete schedules.
