# Bug Report

# Scheduled Execution Orchestration RCA

Date: 2026-05-31

## 1. Summary

EventBridge Scheduler is invoking `release-confidence-platform-dev-scheduledExecution`, but recurring scheduled invocations can return successfully without starting orchestration because the scheduled target payload contains a static `schedule_occurrence_id`. For a `rate(...)` schedule, every delivery reuses the same occurrence key, so after the first claim exists, `scheduled_execution_handler` treats later deliveries as duplicate deliveries and returns `duplicate_skipped` before calling `CoreEngineOrchestrator.run`.

CloudWatch shows only START/END/REPORT because `scheduled_execution_handler` does not configure Lambda-visible INFO logging and does not emit a handler-started `print` log. Its duplicate-skip log uses `StructuredLogger` at INFO, which is not made visible in this Lambda entrypoint.

## 2. Investigation Context

- Source of report: user-reported dev runtime / CloudWatch observation.
- Environment: `stage=dev`, `region=us-east-1`, AWS profile `rk-reliability`.
- Lambda: `release-confidence-platform-dev-scheduledExecution`.
- Schedule group: `rcp-dev-schedules`.
- Related workflow: EventBridge Scheduler scheduled audit execution.
- Branch context: `bugfix/scheduled_execution_orchestration_rca`, base commit `fd2ff5925dee521676155f7a10001ad89ba25d0b`.
- Observed command/workflow: EventBridge Scheduler fires every 5 minutes and invokes the scheduled execution Lambda.
- Verified working comparison path: manual CLI `rcp audit run --client-id client_layer_1_validation_client_b5817642 --audit-id audit_20260524_ec3f2d9b --scenario-type baseline_health --stage dev` and additional manual scenarios (`baseline_health`, `repeated_stability`, `burst_stability`, `response_consistency`) produce S3 raw results and DynamoDB run metadata.

## 3. Observed Symptoms

- Failing workflow: scheduled EventBridge invocation of `scheduledExecution`.
- Actual behavior:
  - CloudWatch log group `/aws/lambda/release-confidence-platform-dev-scheduledExecution` shows only Lambda platform START/END/REPORT lines.
  - Duration is short, approximately 145-164 ms.
  - No application logs are visible.
  - No expected S3 raw result appears under `raw-results/<client_id>/<audit_id>/<run_id>/results.json`.
  - No expected DynamoDB run metadata item appears with `PK=CLIENT#<client_id>` and `SK=AUDIT#<audit_id>#RUN#<run_id>`.
- Expected behavior:
  - `scheduledExecution` should enter the same core orchestration path as manual `rcp audit run`.
  - Expected logs include `scheduled_execution_handler_started`, occurrence claim / duplicate prevention, orchestrator execution, endpoint execution.
  - Expected side effects include raw result write and run metadata write.
- Exact runtime error: none reported. Lambda invocation completes successfully.

## 4. Evidence Collected

### Scheduled handler entrypoint

- `apps/backend/handlers/scheduled_execution_handler.py:150-159` is the Lambda entrypoint. It constructs `AuditMetadataRepository`, `DynamoDBMetadataClient`, `S3StorageClient`, `SecretsManagerClient`, and `CoreEngineOrchestrator`, then calls `ScheduledExecutionHandler.handle(event)`.
- `apps/backend/handlers/scheduled_execution_handler.py:40-42` validates the event and loads audit metadata before claiming occurrence.
- `apps/backend/handlers/scheduled_execution_handler.py:43-63` derives occurrence keys from `schedule_occurrence_id` and calls `repository.claim_occurrence(...)`.
- `apps/backend/handlers/scheduled_execution_handler.py:64-77` catches `DuplicateOccurrenceClaimError`, logs `audit_schedule_duplicate_delivery`, and returns `{status: "duplicate_skipped", run_id: None}` without invoking the orchestrator.
- `apps/backend/handlers/scheduled_execution_handler.py:78-123` only invokes orchestration after a successful occurrence claim and execution-allowed checks.
- `apps/backend/handlers/scheduled_execution_handler.py` contains no `configure_logging()` call and no handler-started `print` emission.

### EventBridge target input shape

- `packages/audit_scheduling/builders.py:273-299` builds the scheduled execution payload with required handler fields:
  - `event_type=audit_schedule_execution`
  - `schema_version=phase3.schedule_event.v1`
  - `client_id`, `audit_id`, `schedule_name`, `schedule_type`, `scenario_type`, `triggered_by`, `schedule_occurrence_id`, `scheduled_at`
  - `burst: None`, `repeated: None`
- `packages/audit_scheduling/events.py:21-58` validates exactly those required scheduled-event fields and rejects scheduled events containing `run_id`.
- `packages/storage/eventbridge_scheduler_client.py:52-56` sends the target input as `json.dumps(sanitize(definition.target_payload), sort_keys=True)`.
- Therefore the configured target input shape matches `validate_scheduled_execution_event(...)` for baseline/burst/repeated execution payloads.

### Static occurrence id for recurring schedules

- `packages/audit_scheduling/builders.py:130-139` sets baseline `scheduled_at = audit_window["start_time"]` and creates a `rate(<interval> minutes)` schedule.
- `packages/audit_scheduling/builders.py:283-296` sets `schedule_occurrence_id = f"{schedule_type}#{scheduled_at}"` and includes that static value in the target payload.
- Because `packages/storage/eventbridge_scheduler_client.py:55` stores this payload as the EventBridge Scheduler target `Input`, every invocation of a recurring `rate(...)` schedule receives the same `schedule_occurrence_id`.
- `packages/storage/audit_metadata_client.py:28-34` maps that value to DynamoDB key `SK=AUDIT#<audit_id>#OCCURRENCE#<schedule_occurrence_id>`.
- `packages/storage/audit_metadata_client.py:145-147` claims occurrence with conditional put.
- `packages/storage/audit_metadata_client.py:187-197` raises `DuplicateOccurrenceClaimError` when the occurrence item already exists.
- `tests/integration/test_phase3_duplicate_delivery.py:14-20` codifies current behavior: duplicate delivery returns `duplicate_skipped` and `orch.events == []`.

### Manual CLI / orchestrator path

- `src/release_confidence_platform/core/manual_run_service.py:29-44` builds the manual run payload with `client_id`, `audit_id`, `scenario_type`, `triggered_by=manual`, and `schedule_type=manual` unless overridden.
- `src/release_confidence_platform/core/manual_run_service.py:53-58` invokes the configured orchestrator Lambda directly.
- `apps/backend/handlers/orchestrator_handler.py:55-66` configures logging, emits `orchestrator_handler_started`, constructs `CoreEngineOrchestrator`, and calls `.run(event)`.
- `apps/backend/orchestrator/service.py:74-220` starts core orchestration by validating the event, duplicate preflight, metadata started write, endpoint execution, and raw-result write.

### Scheduled handler orchestration path

- `apps/backend/handlers/scheduled_execution_handler.py:98-108` calls `self.orchestrator.run(...)` for non-repeated scheduled events.
- `packages/audit_scheduling/repeated.py:21-35` calls `self.orchestrator.run(...)` once per repeated iteration.
- The scheduled handler uses the same core service class (`CoreEngineOrchestrator`) as manual execution, but it bypasses `orchestrator_handler.handler`, so it also bypasses `orchestrator_handler.configure_logging()` and `_emit_handler_started(...)`.

### Logging configuration

- `apps/backend/handlers/orchestrator_handler.py:20-37` configures root/app logger levels and calls this at import time.
- `apps/backend/handlers/orchestrator_handler.py:40-52` emits `orchestrator_handler_started` using `print(...)`, which is always Lambda-visible.
- `packages/core/logging.py:34-65` emits structured logs through Python logging at the requested level, default INFO.
- `apps/backend/handlers/scheduled_execution_handler.py` does not call the orchestrator handler logging setup and does not emit any explicit `scheduled_execution_handler_started` log.
- `infra/serverless.yml:16-22` sets `LOG_LEVEL=INFO`, but this only has effect where code applies it; `scheduled_execution_handler` does not.

## 5. Execution Path / Failure Trace

1. `rcp audit schedule` or equivalent scheduling flow creates a baseline schedule using `ScheduleBuilder.build_baseline(...)`.
2. For baseline schedules, the schedule expression is recurring (`rate(<interval> minutes)`), but the target payload is static.
3. The static target payload contains `schedule_occurrence_id = baseline#<audit_window.start_time>` and `scheduled_at = <audit_window.start_time>`.
4. EventBridge Scheduler invokes `release-confidence-platform-dev-scheduledExecution` every 5 minutes with the same target input.
5. `scheduled_execution_handler.handler(...)` constructs dependencies and calls `ScheduledExecutionHandler.handle(event)`.
6. `handle(...)` validates the event and computes the same occurrence key on each invocation.
7. If the occurrence key already exists, `repository.claim_occurrence(...)` raises `DuplicateOccurrenceClaimError`.
8. The handler catches the duplicate, logs `audit_schedule_duplicate_delivery` at INFO, returns `duplicate_skipped`, and never calls `CoreEngineOrchestrator.run(...)`.
9. Because scheduled handler logging is not configured for INFO and there is no `print`-based handler-started log, CloudWatch records only START/END/REPORT.

## 6. Failure Classification

- Primary classification: Application Bug.
- Contributing classification: Observability / logging implementation defect.
- Severity: High.

Severity justification: scheduled execution is a major release workflow and currently can return successful Lambda invocations while not producing orchestration side effects or application logs. Manual run remains available as a workaround, so this is not classified as Blocker from code evidence alone; it should be treated as release-blocking for scheduled execution validation until fixed.

## 7. Root Cause Analysis

### Confidence label: Most Likely Root Cause

Immediate failure point: `ScheduledExecutionHandler.handle(...)` returns from the `DuplicateOccurrenceClaimError` branch at `apps/backend/handlers/scheduled_execution_handler.py:64-77`, before `CoreEngineOrchestrator.run(...)` at lines 98-108.

Underlying root cause: recurring EventBridge schedule target input uses a static `schedule_occurrence_id` generated at schedule-creation time. For a recurring `rate(...)` baseline schedule, every invocation reuses the same occurrence id and therefore the same DynamoDB occurrence key. Once that occurrence item exists, duplicate prevention treats subsequent scheduler fires as duplicate deliveries rather than distinct scheduled occurrences.

Supporting evidence:
- Static occurrence generation: `packages/audit_scheduling/builders.py:283-296`.
- Recurring baseline schedule using static `scheduled_at`: `packages/audit_scheduling/builders.py:130-139`.
- Static target input persisted to Scheduler: `packages/storage/eventbridge_scheduler_client.py:52-56`.
- Duplicate claim behavior: `packages/storage/audit_metadata_client.py:145-147` and `187-197`.
- Early duplicate skip path: `apps/backend/handlers/scheduled_execution_handler.py:64-77`.
- Test confirms duplicate skip avoids orchestrator: `tests/integration/test_phase3_duplicate_delivery.py:14-20`.

Contributing factors:
- `scheduled_execution_handler` lacks Lambda-visible startup logging and does not call `configure_logging()`, so the duplicate-skip INFO log and orchestrator INFO logs are not visible in CloudWatch for this Lambda.
- Expected `scheduled_execution_handler_started` logging is not implemented in the inspected scheduled handler.
- The scheduled handler invokes `CoreEngineOrchestrator` directly instead of invoking/reusing `orchestrator_handler.handler`, so it does not inherit the manual path's handler-level logging setup.

## 8. Confidence Level

High.

The code directly proves the duplicate-skip branch returns success before orchestration, and the schedule builder/client code directly shows a static occurrence id in the target payload for recurring baseline schedules. Full confirmation would require inspecting the specific DynamoDB occurrence item for the reported audit and the actual EventBridge schedule target `Input`, but the code path matches all reported symptoms: short successful invocations, no downstream artifacts, and no application logs.

## 9. Recommended Fix

Likely owner: backend.

Recommended scoped fix plan:
1. Make each recurring schedule delivery produce a unique occurrence identity before `claim_occurrence(...)`.
   - Likely files: `packages/audit_scheduling/builders.py`, `packages/audit_scheduling/events.py`, `apps/backend/handlers/scheduled_execution_handler.py`, and related tests.
   - For `rate(...)` baseline schedules, do not rely on a static schedule-creation-time `schedule_occurrence_id` as the sole idempotency key. Derive or inject a per-fire occurrence key from an invocation-specific value. If EventBridge Scheduler cannot supply the actual fire time dynamically through target `Input`, consider scheduling discrete `at(...)` occurrences, or have the handler derive a bucketed occurrence id from invocation time plus schedule name with clear idempotency semantics.
   - Preserve duplicate prevention for true duplicate delivery of the same intended occurrence.
2. Add scheduled Lambda entrypoint observability.
   - Likely file: `apps/backend/handlers/scheduled_execution_handler.py`.
   - Add logging setup equivalent to `orchestrator_handler.configure_logging()` and emit a sanitized `scheduled_execution_handler_started` record before validation/claiming.
   - Emit explicit logs for occurrence claim attempted/completed/duplicate-skipped and blocked/failed paths.
3. Align scheduled and manual orchestration observability without changing the core orchestration service contract.
   - The scheduled handler already calls `CoreEngineOrchestrator.run(...)`; keep using the core service, but ensure logging is configured before the call.
   - Avoid adding `run_id` to scheduled target input because `validate_scheduled_execution_event(...)` intentionally rejects it; let the core orchestrator generate run ids.

Cautions:
- Do not remove duplicate occurrence protection entirely; it prevents double execution for true duplicate scheduler deliveries.
- Any handler-derived occurrence id must be deterministic enough for retries of the same occurrence but unique across distinct 5-minute fires.
- If using current wall-clock time in Lambda for occurrence id, define acceptable retry/idempotency behavior explicitly to avoid duplicate executions on retries crossing a bucket boundary.

## 10. Suggested Validation Steps

After implementation:

1. Unit/integration tests:
   - Add/adjust tests proving two distinct recurring baseline invocations do not reuse the same occurrence key and both can call the orchestrator.
   - Keep a test proving an actual duplicate delivery for the same occurrence still returns `duplicate_skipped` and does not call the orchestrator.
   - Add a test that `scheduled_execution_handler` emits `scheduled_execution_handler_started` and duplicate/claim logs at INFO with secrets sanitized.
2. Local/static contract checks:
   - Verify scheduled target input still matches `validate_scheduled_execution_event(...)` or update the validator and builder together.
   - Verify scheduled handler still omits `run_id` from scheduled target input and from the event passed into `CoreEngineOrchestrator.run(...)`.
3. Dev AWS validation:
   - Deploy to dev and inspect the actual schedule target `Input` for the relevant schedule in group `rcp-dev-schedules`.
   - Let the schedule fire twice.
   - Confirm CloudWatch shows `scheduled_execution_handler_started`, occurrence claim/duplicate prevention, orchestrator milestones, and endpoint execution logs.
   - Confirm each intended occurrence writes S3 raw results under `raw-results/<client_id>/<audit_id>/<run_id>/results.json`.
   - Confirm each intended occurrence writes DynamoDB run metadata with `PK=CLIENT#<client_id>` and `SK=AUDIT#<audit_id>#RUN#<run_id>`.
   - Confirm duplicate delivery/retry of the same occurrence does not create a second run.

## 11. Open Questions / Missing Evidence

- The exact deployed EventBridge schedule target `Input` for the reported schedule was not inspected during this RCA. Code evidence indicates the payload is static; AWS-side confirmation should be collected during validation.
- The exact DynamoDB occurrence item for `client_layer_1_validation_client_b5817642` / `audit_20260524_ec3f2d9b` was not inspected. Presence of `SK=AUDIT#audit_20260524_ec3f2d9b#OCCURRENCE#baseline#...` would confirm the duplicate-skip branch for current runtime.
- The report did not include the Lambda return payload. If available, `status=duplicate_skipped` would directly confirm the early-return path.
- EventBridge Scheduler support for dynamic target input fields should be verified before choosing the final fix strategy; if unsupported, use discrete schedules or handler-side deterministic bucketing.

## 12. Acceptance Criteria Answers

- Why EventBridge scheduled invocations return successfully but do not start orchestration: because `DuplicateOccurrenceClaimError` is caught and converted to a successful `duplicate_skipped` response before orchestrator invocation (`apps/backend/handlers/scheduled_execution_handler.py:64-77`).
- Why no application-level error appears in CloudWatch logs: no exception is thrown for duplicate skip, and INFO logs are not visible because `scheduled_execution_handler` does not configure logging or emit a `print`-based started log.
- Whether `scheduled_execution_handler` is returning early, parsing incorrectly, invoking the wrong path, or silently swallowing failures: the most likely path is an intentional early return on duplicate occurrence claim. Event parsing appears compatible with builder output. The handler invokes the right core service after a successful claim, but it bypasses the manual handler's logging setup. It catches `EngineError` and returns `blocked`, but the observed short success/no downstream effects most strongly matches duplicate skip.
- Exact code/config path responsible: `ScheduleBuilder.build_baseline(...)` and `_execution_payload(...)` in `packages/audit_scheduling/builders.py`, `EventBridgeSchedulerClient.create_schedule(...)` in `packages/storage/eventbridge_scheduler_client.py`, occurrence claim handling in `apps/backend/handlers/scheduled_execution_handler.py`, and conditional claim in `packages/storage/audit_metadata_client.py`.
- Whether EventBridge target input shape matches handler expectations: yes for the code-built target payload. `builders.py:286-299` supplies the fields required by `events.py:26-40`, and Scheduler client sends that payload as JSON.
- Whether occurrence claim / duplicate prevention is causing an early skip: most likely yes; the static occurrence id for recurring schedules causes repeated invocations to target the same claim key.
- Whether scheduled handler calls the same core orchestration service as manual `rcp audit run`: yes, both use `CoreEngineOrchestrator.run(...)`. Manual path invokes `orchestrator_handler.handler(...)`; scheduled path constructs `CoreEngineOrchestrator` directly and calls `.run(...)` after schedule-specific validation/claiming.
- Proposed fix plan: create per-occurrence idempotency for recurring scheduled fires while preserving duplicate protection, and add scheduled handler logging setup/start/claim logs.
- Validation steps: see Section 10.

## 13. Final Investigator Decision

Ready for developer fix.
