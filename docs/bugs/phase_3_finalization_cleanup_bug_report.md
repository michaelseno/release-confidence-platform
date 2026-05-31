# Bug Report

## 1. Summary

Phase 3 finalization does invoke the deployed `auditFinalization` Lambda and records finalization metadata, but successful nonzero audits remain in `FINALIZING` and all related EventBridge Scheduler schedules remain `ENABLED` after their `at(...)` times. The schedule persistence issue is caused by schedule creation omitting `ActionAfterCompletion=DELETE`; the lifecycle completion issue is caused by the current finalization handler intentionally stopping at `FINALIZING` for nonzero executions.

## 2. Investigation Context

- Source of report: HITL / dev AWS validation follow-up.
- Branch context: `bugfix/phase_3_finalization_cleanup_rca`.
- Scope: Phase 3 finalization and schedule cleanup only; Phase 4 out of scope.
- Environment: AWS dev, `us-east-1`, profile `rk-reliability`.
- Fresh validation audit: `client_layer_1_schedule_validation_client_7331df81` / `audit_20260531_5f6409d1`.
- Older audit: `client_layer_1_validation_client_b5817642` / `audit_20260524_ec3f2d9b`.

## 3. Observed Symptoms

- Fresh audit produced scheduled execution raw-result objects in S3.
- Fresh audit finalization schedule targeted `auditFinalization` and invoked it.
- Fresh audit lifecycle is `FINALIZING`, not `COMPLETED`.
- Fresh audit schedules remain `ENABLED` after their one-time `at(...)` fire times.
- Older audit also remains `FINALIZING`; its finalization and execution schedules remain `ENABLED`.
- Lambda resource policy read returned `ResourceNotFoundException`, but the scheduler invocation IAM role has `lambda:InvokeFunction` permission for both scheduler target Lambdas.

## 4. Evidence Collected

### Repository evidence

- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py:39-56` builds the Scheduler `create_schedule` payload with `Name`, `ScheduleExpression`, `FlexibleTimeWindow`, optional `GroupName`, `ScheduleExpressionTimezone`, and `Target`; it does **not** set `ActionAfterCompletion`.
- `src/release_confidence_platform/audit_scheduling/builders.py:269-302` builds the finalization schedule as a one-time `at(...)` schedule with `event_type=audit_finalization`, `target_handler=audit_finalization_handler`, and payload fields for `client_id`, `audit_id`, `schedule_name`, and `schedule_occurrence_id`.
- `apps/backend/handlers/audit_finalization_handler.py:27-92` validates the finalization event, transitions current audits to `FINALIZING`, records `finalization`, fails zero-execution audits, and returns `status=finalizing` for nonzero execution audits. It does not instantiate a scheduler client, delete/disable schedules, or transition to `COMPLETED`.
- `src/release_confidence_platform/audit_lifecycle/cancellation.py:17-132` contains schedule cleanup logic only for cancellation flows.
- `src/release_confidence_platform/audit_lifecycle/constants.py:50-52` allows `FINALIZING -> ANALYZING -> REPORTING -> COMPLETED`, but not direct `FINALIZING -> COMPLETED`.
- `infra/resources/scheduler.yml:7-31` defines `release-confidence-platform-dev-scheduler-invoke` trusted by `scheduler.amazonaws.com` and grants `lambda:InvokeFunction` on both `ScheduledExecutionLambdaFunction` and `AuditFinalizationLambdaFunction`.
- `infra/serverless.yml:114-120` deploys `scheduledExecution` and `auditFinalization` Lambda functions.
- `tests/integration/test_phase3_cancellation_finalization.py:65-70` asserts nonzero finalization remains `FINALIZING`; `:83-102` treats `FINALIZING` finalization events as duplicate/skipped.
- `docs/release/scheduled_execution_orchestration_rca_pr.md:63-68` states the current Phase 3 design preserves successful nonzero finalization at `FINALIZING` and explicitly does not implement `FINALIZING -> COMPLETED`.

### AWS read-only evidence

- CloudFormation outputs include:
  - `SchedulerGroupName=rcp-dev-schedules`
  - `SchedulerInvocationRoleArn=arn:aws:iam::463470948609:role/release-confidence-platform-dev-scheduler-invoke`
  - `ScheduledExecutionTargetArn=arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-scheduledExecution`
  - `AuditFinalizationTargetArn=arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-auditFinalization`
  - `MetadataTableName=release-confidence-platform-dev-metadata`
  - `RawResultsBucketName=release-confidence-platform-dev-raw-results`
- Fresh finalization schedule `rcp-dev-client_layer_1_schedule_validation_client_733-c8e86b0120`:
  - `State=ENABLED`
  - `ScheduleExpression=at(2026-05-31T15:51:43)`
  - `ActionAfterCompletion=NONE`
  - `TargetArn=arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-auditFinalization`
  - `RoleArn=arn:aws:iam::463470948609:role/release-confidence-platform-dev-scheduler-invoke`
  - `Input` contains `event_type=audit_finalization`, `audit_id=audit_20260531_5f6409d1`, and the expected client ID.
- Fresh schedule list found 14 schedules for the validation client; all were `ENABLED`, including 13 scheduled-execution targets and 1 finalization target.
- Older finalization schedule `rcp-dev-client_layer_1_validation_client_b5817642-aud-be82fc68e5`:
  - `State=ENABLED`
  - `ScheduleExpression=at(2026-05-30T21:19:38)`
  - `ActionAfterCompletion=NONE`
  - `TargetArn=...:function:release-confidence-platform-dev-auditFinalization`
- Older repeated schedule `rcp-dev-client_layer_1_validation_client_b5817642-aud-d30897b965`:
  - `State=ENABLED`
  - `ScheduleExpression=at(2026-05-30T20:19:38)`
  - `ActionAfterCompletion=NONE`
  - `TargetArn=...:function:release-confidence-platform-dev-scheduledExecution`
- Scheduler invocation role inline policy `invoke-backend-scheduler-targets` allows `lambda:InvokeFunction` on both deployed scheduler target Lambdas.
- `aws lambda get-policy --function-name release-confidence-platform-dev-auditFinalization` returned `ResourceNotFoundException`, meaning no Lambda resource-based policy exists; this is not the active permission path for EventBridge Scheduler because the schedule uses a target `RoleArn`.
- `auditFinalization` Lambda config is `Active`, handler `apps.backend.handlers.audit_finalization_handler.handler`, log group `/aws/lambda/release-confidence-platform-dev-auditFinalization`.
- Finalization CloudWatch log stream `2026/05/31/[$LATEST]a5470267d83b4508b07eda3c6009b5e5` contains `START`, `END`, and `REPORT` for request `f46a1be8-8f13-421d-afeb-544b3888bc7f`, proving invocation. No application-level log lines are emitted by the handler.
- Fresh DynamoDB item shows:
  - `lifecycle_state=FINALIZING`
  - `execution_counters.total_completed=11`
  - `finalization.triggered_at=2026-05-31T07:51:46.138947Z`
  - `finalization.execution_count=11`
  - lifecycle history transition `RUNNING -> FINALIZING`, reason `finalization_trigger`, actor `finalization_handler`.
- Older DynamoDB item shows:
  - `lifecycle_state=FINALIZING`
  - `execution_counters.total_completed=1`
  - `finalization.triggered_at=2026-05-30T13:19:47.243931Z`
  - lifecycle history transition `RUNNING -> FINALIZING`, reason `finalization_trigger`, actor `finalization_handler`.
- Fresh S3 raw-result prefix `raw-results/client_layer_1_schedule_validation_client_7331df81/audit_20260531_5f6409d1/` contains multiple `results.json` keys, confirming scheduled execution results exist.

## 5. Execution Path / Failure Trace

1. Scheduling creates baseline/repeated/finalization `ScheduleDefinition` objects.
2. `EventBridgeSchedulerClient.create_schedule()` sends `create_schedule` without `ActionAfterCompletion`; EventBridge Scheduler defaults/records this as `NONE`.
3. EventBridge Scheduler invokes scheduled execution and finalization targets using the configured `Target.RoleArn`.
4. `auditFinalization` handler receives the finalization event and transitions nonzero audits from `RUNNING` to `FINALIZING`.
5. The handler records finalization metadata and returns without deleting/disabling schedules and without transitioning to `COMPLETED`.
6. Because one-time schedules were created with `ActionAfterCompletion=NONE`, EventBridge Scheduler retains them as `ENABLED` after completion.

## 6. Failure Classification

- Primary classification: Application Bug.
- Contributing classification: Requirements / architecture mismatch for lifecycle completion because prior branch documentation and tests intentionally preserve `FINALIZING`, while the current user-confirmed intended behavior requires `COMPLETED` after successful finalization.
- Severity: High. The affected audit lifecycle never reaches the now-confirmed terminal success state, and scheduler resources accumulate as enabled stale schedules after audit windows. This does not currently prove data loss or security impact, so not classified as Blocker by evidence alone.

## 7. Root Cause Analysis

### Confirmed Root Cause 1: One-time schedules persist because `ActionAfterCompletion` is omitted.

- Immediate failure point: EventBridge schedules for both fresh and older audits are still `ENABLED` with `ActionAfterCompletion=NONE` after their `at(...)` times.
- Underlying cause: `EventBridgeSchedulerClient.create_schedule()` does not set `ActionAfterCompletion=DELETE` for one-time schedules.
- Supporting evidence: code lines `eventbridge_scheduler_client.py:39-56`; AWS `get-schedule` output for fresh and older schedules shows `ActionAfterCompletion=NONE` and `State=ENABLED`.

### Confirmed Root Cause 2: Successful nonzero finalization intentionally stops at `FINALIZING`.

- Immediate failure point: DynamoDB lifecycle state remains `FINALIZING` after finalization metadata is recorded.
- Underlying cause: `AuditFinalizationHandler.handle()` returns `status=finalizing` and `lifecycle_state=FINALIZING` for `execution_count > 0`; it has no `COMPLETED` transition path.
- Supporting evidence: handler lines `53-91`; test `test_finalization_with_executions_remains_finalizing`; release PR note says current Phase 3 design preserves `FINALIZING`.

### Confirmed Root Cause 3: Finalization handler has no schedule cleanup responsibility in current implementation.

- Immediate failure point: schedules remain after finalization.
- Underlying cause: finalization handler only records lifecycle/finalization metadata. Cleanup exists in cancellation service only, not in finalization.
- Supporting evidence: finalization handler lines `22-98`; cancellation cleanup lines `17-132`.

## 8. Confidence Level

High. Live AWS state, DynamoDB lifecycle/finalization metadata, CloudWatch invocation logs, IAM policy evidence, and repository code all align on the same execution path. The only remaining uncertainty is whether product wants direct `FINALIZING -> COMPLETED` in Phase 3 or a minimal `FINALIZING -> ANALYZING -> REPORTING -> COMPLETED` closeout path to respect existing transition rules.

## 9. Recommended Fix

Likely owner: backend / full-stack platform.

Required fixes pending HITL approval:

1. Add Scheduler one-time auto-delete behavior.
   - Likely file: `src/release_confidence_platform/storage/eventbridge_scheduler_client.py` and mirrored package copy if this repository requires both trees to stay synchronized.
   - Expected correction: set `ActionAfterCompletion="DELETE"` for one-time `at(...)` schedules. Since Phase 3 now uses bounded discrete `at(...)` schedules for baseline/repeated/finalization, this should apply to those definitions; avoid applying blindly if future recurring schedules are supported.
   - Add/adjust unit tests to assert `create_schedule` includes `ActionAfterCompletion=DELETE` for `at(...)` schedules.

2. Implement final Phase 3 closeout to a terminal success state.
   - Likely file: `apps/backend/handlers/audit_finalization_handler.py` and lifecycle tests.
   - Expected correction: after successful nonzero finalization, transition audit to `COMPLETED` according to an approved transition path. Existing lifecycle constants do not allow direct `FINALIZING -> COMPLETED`; either update the transition contract with architecture/product approval or perform the existing staged path (`FINALIZING -> ANALYZING -> REPORTING -> COMPLETED`) if acceptable for Phase 3 closeout.
   - Preserve zero-execution behavior (`FAILED`) and duplicate/idempotent behavior for already finalizing/terminal audits.

3. Define successful-finalization schedule cleanup responsibility.
   - If `ActionAfterCompletion=DELETE` is adopted for all one-time schedules, the handler may not need to delete schedules during normal success.
   - If explicit cleanup is required by product, inject/configure a scheduler client in finalization and delete/disable persisted schedules after finalization with failure recording analogous to cancellation cleanup. This requires IAM review because the finalization Lambda role would need Scheduler delete/update permissions.

Recommendations:

- Add a separate operator cleanup tool for stale schedules from older failed/previous audits. It should support dry-run, filter by client/audit or age, verify DynamoDB audit ownership before cleanup, and require explicit confirmation for destructive actions.
- Add application-level logging in `auditFinalization` for received event, lifecycle decision, execution count, and final state. CloudWatch currently only proves invocation via platform `START/END/REPORT` lines.

## 10. Suggested Validation Steps

After implementation and deployment approval:

1. Unit/integration tests:
   - Assert schedule creation payload includes `ActionAfterCompletion=DELETE` for baseline/repeated/finalization `at(...)` schedules.
   - Assert nonzero finalization reaches the approved terminal success state.
   - Assert zero-execution finalization still transitions to `FAILED`.
   - Assert duplicate finalization delivery remains idempotent for terminal states.
   - If handler cleanup is implemented, assert cleanup iterates all persisted schedules and records cleanup warnings without hiding lifecycle outcome.
2. Read-only AWS validation on a new dev audit:
   - Confirm scheduled execution writes S3 raw results.
   - Confirm finalization Lambda log stream has invocation and application-level closeout log lines.
   - Confirm DynamoDB final lifecycle is `COMPLETED` after successful finalization.
   - Confirm EventBridge schedules are deleted automatically after completion, or are disabled/deleted by the approved cleanup path.
3. Stale cleanup tooling validation:
   - Run dry-run only first against the older audit and verify it identifies the expected stale schedules without mutating resources.

## 11. Open Questions / Missing Evidence

- Product/architecture approval is needed for the lifecycle path: direct `FINALIZING -> COMPLETED` vs existing staged `FINALIZING -> ANALYZING -> REPORTING -> COMPLETED`.
- Security/architecture review is needed if finalization handler itself is given Scheduler delete/update permissions; using `ActionAfterCompletion=DELETE` avoids expanding Lambda permissions for normal one-time schedule cleanup.
- No destructive cleanup was performed; stale schedules remain in dev by design of this RCA-only investigation.

## 12. Final Investigator Decision

Ready for developer fix after HITL approval of the lifecycle transition approach and cleanup responsibility.
