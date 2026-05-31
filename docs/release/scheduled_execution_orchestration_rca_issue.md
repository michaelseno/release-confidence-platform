# Issue: Scheduled Execution Orchestration RCA

## Summary
Recurring `rate(...)` schedules reused a static `schedule_occurrence_id`, causing duplicate-prevention to skip later scheduled executions before orchestration.

## Root Cause
The baseline recurring schedule identity was not unique per occurrence. Duplicate-prevention treated later scheduled deliveries as already processed and prevented orchestration from running.

## Scope
- Replace baseline recurring `rate(...)` schedules with bounded discrete `at(...)` schedules.
- Generate deterministic per-occurrence `schedule_occurrence_id` values.
- Preserve duplicate-prevention semantics.
- Add scheduled handler observability logs.
- Fix HITL audit list behavior so only canonical audit metadata rows are returned.
- Improve `FORCE_RECREATE_BLOCKED` guidance.
- Add duplicate finalization idempotency coverage.

## Environment Recovery Finding
`SCHEDULER_CONFIG_ERROR` was caused by operator environment configuration and was resolved by exporting deployed scheduler outputs. No application code change was required for that issue.

## Validation Evidence
- Focused scheduling suite: passed.
- HITL blocker focused tests: passed.
- Final focused finalization/duplicate/scheduled execution: `16 passed in 0.22s`.
- Final full suite: `354 passed, 1 skipped in 0.86s`.
- Live HITL validation successful for client `client_layer_1_schedule_validation_client_7331df81` and audit `audit_20260531_5f6409d1`.
