# Test Plan

## 1. Feature Overview

Validate the scheduled execution orchestration RCA fix on branch `bugfix/scheduled_execution_orchestration_rca`.

The fix replaces recurring baseline `rate(...)` schedules with bounded discrete `at(...)` schedules, gives each intended baseline occurrence a deterministic occurrence identity, preserves duplicate delivery protection, and adds scheduled handler observability while keeping manual `rcp audit run` behavior unchanged.

## 2. Acceptance Criteria Mapping

| ID | Acceptance criterion | Planned validation |
| --- | --- | --- |
| AC1 | EventBridge scheduled invocations no longer silently skip orchestration due to static occurrence ID reuse. | Inspect baseline schedule builder and tests proving discrete `at(...)` occurrences with distinct `schedule_occurrence_id` values. Execute schedule builder and scheduled handler tests. |
| AC2 | EventBridge target input shape matches `scheduled_execution_handler` expectations. | Inspect payload builder and scheduled event validation coverage. Execute event contract/handler tests. |
| AC3 | Occurrence claim / duplicate prevention skips only true duplicate deliveries, not distinct scheduled baseline occurrences. | Verify distinct baseline occurrence IDs and duplicate delivery skip tests. |
| AC4 | Scheduled handler calls the same core orchestration service as manual `rcp audit run`, specifically `CoreEngineOrchestrator.run(...)`. | Inspect Lambda entrypoint construction and handler `.run(...)` call path; execute scheduled handler tests asserting orchestrator invocation. |
| AC5 | Manual `rcp audit run` behavior unchanged. | Execute existing CLI unit/contract tests for operator CLI manual run behavior. |
| AC6 | Required logs emitted by handler path. | Inspect scheduled handler logging and execute log capture tests for startup/claim/orchestration/raw-result/metadata milestones. |
| AC7 | S3 raw result and DynamoDB run metadata behavior covered by tests/mocks. | Verify scheduled execution tests assert raw result and metadata log behavior from mocked orchestrator result. Execute focused tests. |
| AC8 | Schedule cleanup/cancel handles multiple discrete schedules. | Inspect cancellation service and execute cancellation/finalization integration tests covering multiple baseline schedules. |

## 3. Test Scenarios

1. Build a short baseline audit window and assert two discrete `at(...)` schedules with two deterministic, distinct occurrence IDs.
2. Build a full 48-hour baseline audit window and assert 192 baseline schedules, each represented as `at(...)`.
3. Send a valid scheduled baseline event through `ScheduledExecutionHandler` and assert occurrence is claimed before orchestrator invocation, `run_id` is omitted from the orchestrator input, and the claim is completed with the generated run ID.
4. Send a duplicate delivery of the same occurrence and assert `duplicate_skipped` with no orchestrator invocation.
5. Verify scheduled handler logs: event contract validation, claim attempted, claim created, orchestration start/completion, raw results written, run metadata written, and Lambda-visible startup log.
6. Verify malformed scheduled event containing `run_id` is rejected before occurrence claim.
7. Verify cancellation cleanup iterates all persisted schedules, including multiple discrete baseline schedules.
8. Execute existing manual CLI contract/unit coverage to guard `rcp audit run` behavior.

## 4. Edge Cases

- Invalid or non-positive baseline interval is rejected.
- Baseline occurrence cap of 192 is enforced.
- Empty audit windows are rejected by schedule builder.
- Duplicate occurrence claims are handled as idempotent duplicate deliveries.
- Expired audit window blocks after claim and before orchestrator invocation.
- Cleanup records warnings if scheduler delete/disable both fail.

## 5. Test Types Covered

- Static implementation inspection.
- Unit tests for schedule builders and CLI contracts.
- Integration-style handler tests with deterministic fakes/mocks.
- Regression tests for manual CLI behavior.
- Lifecycle/cancellation integration tests.

## 6. Coverage Justification

The planned tests map directly to the failure mode from the RCA: static occurrence identity on recurring schedules. The key regression protections are distinct per-occurrence IDs, preserved duplicate skip semantics for true duplicate deliveries, and proof that accepted scheduled events enter the same `CoreEngineOrchestrator.run(...)` path used by manual execution. Manual CLI coverage and cancellation coverage provide regression protection outside the immediate handler path.
