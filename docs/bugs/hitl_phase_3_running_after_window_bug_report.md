# Bug Report

## 1. Summary
HITL validation found audit `audit_20260603_4616c9ff` for client `client_phase_3_validation_v1_58fcdc12` still in `RUNNING` more than 24 hours after its audit window. Live read-only inspection shows the finalization schedule did invoke `auditFinalization`, but the Lambda failed before lifecycle transition because structured logging attempted to JSON-serialize a DynamoDB `Decimal` execution counter.

## 2. Investigation Context
- Source of report: HITL release validation blocker.
- Branch context: current active branch `bugfix/phase_3_finalization_cleanup_rca`; no branch changes made.
- Stage/region/profile: `dev`, `us-east-1`, `rk-reliability`.
- Related workflow: Phase 3 scheduled audit finalization after audit window end.
- Affected audit:
  - client_id: `client_phase_3_validation_v1_58fcdc12`
  - audit_id: `audit_20260603_4616c9ff`
  - reported audit window end: `2026-06-03T15:45:14.582278Z`
  - observed lifecycle from user: `RUNNING`

## 3. Observed Symptoms
- User command:
  - `rcp audit list --client-id client_phase_3_validation_v1_58fcdc12 --stage dev --output json`
- Observed behavior:
  - Audit remained `RUNNING`; `updated_at` stayed at `2026-06-03T15:43:30.743898Z`.
- Expected behavior:
  - Finalization should move nonzero execution audits `RUNNING -> FINALIZING -> COMPLETED`.
- CloudWatch finalization failure:
  - Log group: `/aws/lambda/release-confidence-platform-dev-auditFinalization`
  - First finalization invocation: `2026-06-03T15:47:47.717Z`
  - Error at `2026-06-03T15:47:49.194Z`:
    - `TypeError: Object of type Decimal is not JSON serializable`
    - traceback: `apps/backend/handlers/audit_finalization_handler.py`, line 64 `_log_finalization(...)`; `packages/core/logging.py`, line 64 `json.dumps(record, sort_keys=True)`.
  - Retries failed with the same error at approximately `2026-06-03T15:48:44.435Z` and `2026-06-03T15:50:50.811Z`.

## 4. Evidence Collected
- DynamoDB audit metadata item in `release-confidence-platform-dev-metadata`:
  - `lifecycle_state = RUNNING`.
  - `execution_counters.total_started = 13`, `execution_counters.total_completed = 13`.
  - `lifecycle_history` contains only `DRAFT -> SCHEDULED` and `SCHEDULED -> RUNNING`; no `FINALIZING` or `COMPLETED` entry.
  - No `finalization` field was recorded.
  - `schedules` contains a finalization schedule:
    - `schedule_name = rcp-dev-client_phase_3_validation_v1_58fcdc12-audit_2-737b964f16`
    - `schedule_type = finalization`
    - `schedule_group = rcp-dev-schedules`
    - `schedule_expression_summary = at(2026-06-03T23:47:45)`
    - `schedule_expression_timezone = Asia/Hong_Kong`
    - `target_handler = audit_finalization_handler`
    - `status = created`
- EventBridge Scheduler read-only lookup:
  - `get-schedule` for `rcp-dev-client_phase_3_validation_v1_58fcdc12-audit_2-737b964f16` returned `ResourceNotFoundException`.
  - `list-schedules` for group `rcp-dev-schedules` did not include the affected schedule.
  - Given CloudWatch invocation occurred, this is consistent with one-time schedule completion/auto-delete, but post-hoc `ActionAfterCompletion` cannot be directly retrieved.
- Lambda configuration:
  - `release-confidence-platform-dev-auditFinalization` handler is `apps.backend.handlers.audit_finalization_handler.handler`.
  - `LastModified = 2026-06-03T14:28:26.000+0000`, before the affected audit was created (`2026-06-03T14:45:16.986896Z`).
- S3 raw results:
  - `s3://release-confidence-platform-dev-raw-results/raw-results/client_phase_3_validation_v1_58fcdc12/audit_20260603_4616c9ff/` contains raw results objects, including the final baseline result at `2026-06-03T15:43:31Z`.
- DynamoDB occurrence metadata:
  - Query for `AUDIT#audit_20260603_4616c9ff#OCCURRENCE#` returned `Count = 13`, matching `total_completed = 13`.
- Source files inspected:
  - `apps/backend/handlers/audit_finalization_handler.py:51-64` reads `execution_counters.total_completed` from DynamoDB-backed metadata and logs it before lifecycle transition.
  - `apps/backend/handlers/audit_finalization_handler.py:73-101` would transition to `FINALIZING`, record finalization, then complete to `COMPLETED`, but this path is not reached.
  - `packages/core/logging.py:52-64` sanitizes records but then calls `json.dumps(...)` without a Decimal-safe serializer.
  - `packages/sanitization/sanitizer.py:71-84` returns unknown scalar values unchanged, so `Decimal` remains a `Decimal`.
  - `apps/backend/handlers/audit_finalization_handler.py:238-240` uses `boto3.resource(...).Table(...)`; DynamoDB numeric attributes are returned as `Decimal`.
  - `packages/storage/eventbridge_scheduler_client.py:45-46` and `src/release_confidence_platform/storage/eventbridge_scheduler_client.py:45-46` set `ActionAfterCompletion="DELETE"` for one-time `at(...)` expressions.

## 5. Execution Path / Failure Trace
1. Operator created the audit and schedules. DynamoDB recorded 14 schedules, including the finalization schedule.
2. Scheduled executions ran successfully. DynamoDB counters reached `total_completed = 13`; S3 raw results and occurrence metadata exist.
3. EventBridge Scheduler invoked `release-confidence-platform-dev-auditFinalization` at about `2026-06-03T15:47:47Z`, matching the finalization schedule summary `at(2026-06-03T23:47:45)` with `Asia/Hong_Kong` timezone.
4. The handler loaded the audit metadata and read `execution_counters.total_completed` from DynamoDB as a `Decimal`.
5. Before calling `AuditLifecycleService.transition(...)`, the new observability log path attempted to emit `execution_count=Decimal(...)`.
6. `StructuredLogger.log(...)` called `json.dumps(record, sort_keys=True)` and raised `TypeError: Object of type Decimal is not JSON serializable`.
7. Lambda failed before `RUNNING -> FINALIZING`; retries failed the same way.
8. The schedule is no longer retrievable, consistent with one-time schedule completion/delete behavior; the audit remains stuck in `RUNNING` with no finalization metadata.

## 6. Failure Classification
- Primary classification: Application Bug.
- Severity: Blocker.
- Severity justification: This blocks HITL release validation and prevents successful Phase 3 audit completion for a normal nonzero-execution audit.
- Reproducibility: Reproduced once in live HITL evidence; deterministic for DynamoDB-backed finalization where numeric execution counters are returned as `Decimal` and logged before conversion.

## 7. Root Cause Analysis
### Confirmed Root Cause
The deployed `auditFinalization` handler fails before lifecycle transition because the new observability log emits `execution_count` directly from DynamoDB metadata. DynamoDB returns numeric fields as `Decimal`, and `StructuredLogger.log(...)` cannot JSON-serialize `Decimal` values.

Supporting evidence:
- CloudWatch traceback directly identifies `audit_finalization_handler.py:64` `_log_finalization(...)` and `packages/core/logging.py:64` `json.dumps(...)`.
- Error message is `TypeError: Object of type Decimal is not JSON serializable`.
- DynamoDB metadata has numeric `execution_counters.total_completed = 13`.
- No lifecycle/finalization writes occurred after the log failure.

### Plausible Contributing Factors
- Existing tests use fake repositories with Python `int` counters, so they did not cover DynamoDB `Decimal` numeric behavior.
- The new observability logging was added before the first lifecycle transition, making logging serialization a hard blocker for finalization.

## 8. Confidence Level
High. The live stack trace, DynamoDB item state, and source execution order all point to the same failure boundary. The only uncertainty is the exact historical `ActionAfterCompletion` value because the one-time schedule is no longer retrievable after execution.

## 9. Recommended Fix
- Likely owner: backend.
- Likely files/modules:
  - `apps/backend/handlers/audit_finalization_handler.py`
  - possibly `packages/core/logging.py` / `packages/sanitization/sanitizer.py`
  - tests under `tests/integration/test_phase3_cancellation_finalization.py` or a focused logger/finalization test.
- Expected correction:
  - Convert DynamoDB numeric values used in finalization logging and lifecycle metadata to JSON-safe primitives before logging/writing, especially `execution_count`.
  - Prefer a boundary-safe approach that prevents any `Decimal` from breaking structured logs, either by normalizing finalization `execution_count` to `int` after reading metadata or by making `StructuredLogger`/sanitizer Decimal-safe.
  - Add a regression test where repository metadata returns `Decimal("13")` for `execution_counters.total_completed`; expected result should complete finalization and emit logs without serialization failure.
- Cautions:
  - Do not remove the observability logs; make them serialization-safe.
  - Preserve zero-execution behavior and `FINALIZING` retry semantics.
  - Avoid mutating the affected live audit during investigation; any remediation/replay should be release-manager/user approved.

## 10. Suggested Validation Steps
1. Unit/integration regression:
   - Finalization with DynamoDB-like `Decimal("13")` execution counter returns `status="completed"`, lifecycle `COMPLETED`, and appends `FINALIZING -> COMPLETED`.
   - Zero-execution with `Decimal("0")` still fails to `FAILED`.
   - Retry from `FINALIZING` with Decimal finalization metadata remains safe if applicable.
2. Logger regression:
   - `StructuredLogger.log(...)` can handle sanitized records containing Decimal values, or finalization guarantees no Decimal is passed to logger.
3. Deployment/HITL validation:
   - Deploy the backend fix to `dev` before rerunning HITL validation.
   - Create a fresh validation audit and wait for finalization.
   - Verify `auditFinalization_*` logs appear without `TypeError`.
   - Verify lifecycle reaches `COMPLETED` and finalization metadata is recorded.
   - Verify the finalization one-time schedule is absent post execution if `ActionAfterCompletion="DELETE"` is expected.

## 11. Open Questions / Missing Evidence
- The finalization schedule was auto-removed before inspection, so the live schedule's exact `ActionAfterCompletion`, `Target.Input`, and `State` cannot be retrieved post-hoc.
- No manual replay/remediation was performed. A recovery procedure for the already stuck audit requires explicit release-manager/user direction.
- Need confirmation whether backend should also add a safe replay/repair path for audits stuck in `RUNNING` after finalization Lambda failure, or whether rerunning a fresh validation audit is sufficient.

## 12. Final Investigator Decision
Ready for developer fix.

Backend implementation should be routed now. Release-manager/user action is also needed after the code fix to deploy to `dev` and decide whether to replay/remediate the affected stuck audit or run a fresh HITL validation audit.
