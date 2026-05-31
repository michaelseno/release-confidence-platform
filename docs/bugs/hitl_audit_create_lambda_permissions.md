# Bug Report

Title: HITL audit create force recreate blocked by FINALIZING lifecycle and audit list child-record leakage  
Date: 2026-05-31

## 1. Summary

During HITL validation on `bugfix/scheduled_execution_orchestration_rca`, `rcp audit create --force` failed with `FORCE_RECREATE_BLOCKED` because the existing audit is in live lifecycle state `FINALIZING`. That force-recreate rejection is intended by the current contract, but the audit appears stuck in `FINALIZING` after finalization, and `rcp audit list` also incorrectly reports 18 audits by leaking child records under the audit partition/sort-key prefix.

Primary findings:

- `audit create --force` is blocked by the lifecycle guard because live metadata shows `lifecycle_state: FINALIZING`.
- Repository code intentionally leaves audits with completed executions in `FINALIZING`; no code path advances them to `ANALYZING`, `REPORTING`, or `COMPLETED`.
- `audit list` queries all `SK` values beginning with `AUDIT#` and only filters `#OCCURRENCE#`, so run metadata records such as `AUDIT#<audit_id>#RUN#<run_id>` are mapped as duplicate minimal audit entries.
- The earlier Lambda `get-policy` suspicion is not supported as the direct cause. EventBridge Scheduler invocation is configured through a scheduler invocation IAM role, not Lambda resource-based permissions, so absence of a Lambda resource policy may be expected.

## 2. Investigation Context

- Source of report: HITL validation blocker / regression handling.
- Active branch: `bugfix/scheduled_execution_orchestration_rca`.
- Related workflows:
  - `rcp audit create --force` for an existing audit after scheduled execution/finalization validation.
  - `rcp audit list` discovery output for the same client.
- User-provided failing command:

```bash
rcp audit create \
  --client-config .local-configs/client_layer_1_validation_client_b5817642/client_config.json \
  --audit-config .local-configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/audit_config.json \
  --endpoints-config .local-configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/endpoints.json \
  --stage dev \
  --force
```

- User-provided error:

```text
ERROR: audit create failed
stage: dev
code: FORCE_RECREATE_BLOCKED
message: Audit lifecycle is not eligible for force recreate
next_step: correct the error and retry
```

- New user-provided live evidence:

```bash
rcp audit list \
  --client-id client_layer_1_validation_client_b5817642 \
  --stage dev \
  --output json
```

```json
{
  "client_id": "client_layer_1_validation_client_b5817642",
  "command": "audit list",
  "count": 18,
  "items": [
    {
      "audit_id": "audit_20260524_ec3f2d9b",
      "audit_window": {
        "duration_hours": 1,
        "end_time": "2026-05-30T13:19:24.432480Z",
        "start_time": "2026-05-30T12:19:24.432480Z",
        "timezone": "Asia/Hong_Kong"
      },
      "config_hash": {
        "audit_config": "9ff446fbeeac26568a48dfa7d9b797d138a64b0a92458a35d74c59a31b47e6bd",
        "client_config": "5ad1086a70e49851a98d8ca558ae1a5d81e16ae9514ee1f418342d44aa70000e",
        "endpoints_config": "e570050730c1f962455a1a363e10172c905620718dcc04b914cf223573c22192"
      },
      "config_version": "v1",
      "created_at": "2026-05-25T15:24:30.784682Z",
      "lifecycle_state": "FINALIZING",
      "target_environment": "dev",
      "updated_at": "2026-05-30T13:19:47.282252Z"
    },
    {"audit_id": "audit_20260524_ec3f2d9b"},
    {"audit_id": "audit_20260524_ec3f2d9b"}
  ],
  "limit": 100,
  "stage": "dev",
  "status": "success",
  "summary": "found 18 audits",
  "truncated": false
}
```

## 3. Observed Symptoms

- `audit create --force` rejects the existing audit with `FORCE_RECREATE_BLOCKED`.
- Live `audit list` shows the canonical audit metadata row is `FINALIZING`.
- `audit list` reports `count: 18` but shows repeated minimal `{"audit_id": "audit_20260524_ec3f2d9b"}` entries for the same audit.
- Expected behavior:
  - `--force` should only recreate existing `DRAFT` or `FAILED` audits; `FINALIZING` should be rejected unless a separate product-approved recovery/reset workflow exists.
  - A finalized audit should have a defined path out of `FINALIZING` to `ANALYZING`/`REPORTING`/`COMPLETED` or `FAILED`.
  - `audit list` should list only canonical audit metadata records, not child run/occurrence records.
  - CLI recovery guidance should identify the lifecycle precondition and safe next steps.

## 4. Evidence Collected

Files/code paths inspected:

- `src/release_confidence_platform/core/audit_creation_service.py`
  - `create_from_files()` reads existing metadata before force processing (`lines 71-75`).
  - If `force=True` and `lifecycle_state` is not `DRAFT` or `FAILED`, it raises `StorageError("Audit lifecycle is not eligible for force recreate", "FORCE_RECREATE_BLOCKED")` (`lines 80-89`).
- `src/release_confidence_platform/storage/audit_metadata_client.py`
  - `list_audits_for_client()` queries `PK = CLIENT#<client_id>` and `begins_with(SK, "AUDIT#")` (`lines 48-72`). This includes canonical audit rows plus child rows under the same audit sort-key namespace.
  - `occurrence_keys()` uses `SK: AUDIT#<audit_id>#OCCURRENCE#<occurrence_id>` (`lines 34-40`).
  - `update_for_force_recreate()` has a second DynamoDB conditional guard `lifecycle_state IN (:draft, :failed)` (`lines 145-196`).
- `src/release_confidence_platform/storage/dynamodb_client.py`
  - Run metadata keys are `SK: AUDIT#<audit_id>#RUN#<run_id>` (`lines 20-27`). These match `begins_with(SK, "AUDIT#")` and are not filtered by audit discovery.
- `src/release_confidence_platform/operator_cli/discovery_service.py`
  - `list_audits()` only filters items whose `SK` contains `#OCCURRENCE#` (`lines 46-55`). It does not filter `#RUN#` or require `SK == AUDIT#<audit_id>`.
  - `_safe_audit()` derives `audit_id` from any `SK` starting with `AUDIT#` and returns minimal data when no audit metadata fields are present (`lines 184-207`). This explains repeated `{"audit_id": ...}` entries.
- `apps/backend/handlers/audit_finalization_handler.py`
  - `handle()` transitions non-terminal/non-finalizing audits to `FINALIZING` (`lines 27-64`).
  - If `execution_count == 0`, it transitions `FINALIZING -> FAILED` (`lines 65-84`).
  - If `execution_count > 0`, it records finalization and returns `status: finalizing`, `lifecycle_state: FINALIZING` without any further transition (`lines 85-91`).
- `tests/integration/test_phase3_cancellation_finalization.py`
  - `test_finalization_with_executions_remains_finalizing()` explicitly asserts this behavior (`lines 63-68`), making the stuck `FINALIZING` behavior intentional in current tests but incomplete for production lifecycle closure.
- `src/release_confidence_platform/audit_lifecycle/constants.py`
  - Valid transitions include `FINALIZING -> ANALYZING` and `FINALIZING -> FAILED` (`line 50`), then `ANALYZING -> REPORTING -> COMPLETED` (`lines 51-52`). No inspected handler performs these success-path transitions.
- `infra/serverless.yml` and `infra/resources/scheduler.yml`
  - Defines Lambda functions `scheduledExecution` and `auditFinalization` (`serverless.yml:114-121`).
  - Defines `BackendSchedulerInvocationRole` trusted by `scheduler.amazonaws.com` and allowed to `lambda:InvokeFunction` for `ScheduledExecutionLambdaFunction` and `AuditFinalizationLambdaFunction` (`scheduler.yml:7-31`).
- `infra/.serverless/serverless-state.json`
  - Compiled function names include `release-confidence-platform-dev-scheduledExecution` and `release-confidence-platform-dev-auditFinalization` (`lines 318-384`).
  - Compiled scheduler role grants `lambda:InvokeFunction` to both target Lambda ARNs (`lines 464-504`).
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py`
  - Schedule target payload uses `Target: {Arn, RoleArn, Input}` (`lines 39-56`), confirming Scheduler invocation depends on a role ARN rather than Lambda resource policy.

## 5. Execution Path / Failure Trace

### `audit create --force`

1. CLI dispatches `audit create` to `AuditCreationService.create_from_files(..., force=True)`.
2. The service reads existing metadata for `client_layer_1_validation_client_b5817642/audit_20260524_ec3f2d9b`.
3. Live metadata shows `lifecycle_state: FINALIZING`.
4. `FINALIZING` is not in the force allowlist `{DRAFT, FAILED}`.
5. The service raises `FORCE_RECREATE_BLOCKED` before config S3 writes or DynamoDB force-update mutation.
6. `operator_cli.result.render_error()` has no `FORCE_RECREATE_BLOCKED` next-step branch, so it emits generic `correct the error and retry`.

### Stuck `FINALIZING`

1. A scheduled execution moves the audit from `SCHEDULED` to `RUNNING` and increments `execution_counters.total_completed` after a successful run (`scheduled_execution_handler.py:117-167`).
2. The finalization schedule fires at audit-window end and invokes `AuditFinalizationHandler.handle()`.
3. Handler transitions the current state to `FINALIZING` and records finalization metadata.
4. If `execution_count > 0`, the handler returns while leaving the lifecycle state as `FINALIZING`.
5. Subsequent finalization deliveries skip because `current_state == FINALIZING` (`audit_finalization_handler.py:31-39`), so the audit can remain permanently `FINALIZING` without a separate analyzer/reporter/completion worker.

### `audit list` duplicate/minimal entries

1. `audit list` calls `AuditMetadataRepository.list_audits_for_client()`.
2. DynamoDB query selects every item under `PK=CLIENT#...` with `SK` beginning `AUDIT#`.
3. Canonical audit metadata row `AUDIT#audit_20260524_ec3f2d9b` is returned.
4. Run metadata child rows `AUDIT#audit_20260524_ec3f2d9b#RUN#...` also match the prefix.
5. `DiscoveryListService.list_audits()` filters only `#OCCURRENCE#`, not `#RUN#` or other child suffixes.
6. `_safe_audit()` derives the same audit ID from each child `SK`, but child rows lack fields like `lifecycle_state`, producing minimal duplicate objects.

## 6. Failure Classification

- Primary classification: **Application Bug**.
- Contributing classification: **Requirements Ambiguity** for success-path finalization semantics after `FINALIZING`.
- Severity: **High**.

Severity rationale: this blocks HITL recovery for the active audit ID, exposes misleading operator discovery output, and can leave finalized audits permanently in a non-terminal state after successful executions. The force guard itself is protective and expected, but the stuck state and list leakage affect core scheduling/finalization operations and validation confidence.

## 7. Root Cause Analysis

### Confirmed Root Cause: force recreate block

`audit create --force` is blocked because the existing audit metadata is in `FINALIZING`, and force recreate is intentionally allowed only for `DRAFT` or `FAILED`.

Supporting evidence:

- Live `audit list` output shows `"lifecycle_state": "FINALIZING"` for `audit_20260524_ec3f2d9b`.
- `AuditCreationService.create_from_files()` rejects any force recreate state outside `{DRAFT, FAILED}` with the exact observed message.
- `AuditMetadataRepository.update_for_force_recreate()` repeats the same allowlist as a DynamoDB condition.

### Most Likely Root Cause: audit remains stuck in FINALIZING after successful finalization

The finalization handler has no success-path transition beyond `FINALIZING` when `execution_count > 0`. This appears to be the direct reason the live audit is still `FINALIZING` after the audit window ended.

Supporting evidence:

- `audit_finalization_handler.py:85-91` returns `status: finalizing` and `lifecycle_state: FINALIZING` for nonzero executions.
- `test_finalization_with_executions_remains_finalizing()` codifies that behavior.
- Lifecycle constants define possible downstream states (`ANALYZING`, `REPORTING`, `COMPLETED`), but no inspected backend handler performs those transitions.
- Live `updated_at` is shortly after `end_time`, consistent with a finalization event having fired and left the item in `FINALIZING`.

Uncertainty: repository evidence proves the code can leave the audit stuck, but CloudWatch logs or a DynamoDB projection including `finalization` and `execution_counters` would confirm the exact live transition sequence.

### Confirmed Root Cause: `audit list` child-record leakage

`audit list` incorrectly includes child records under the audit sort-key namespace, especially run metadata rows.

Supporting evidence:

- Query uses `begins_with(SK, "AUDIT#")`, which includes `AUDIT#<audit_id>#RUN#<run_id>`.
- Discovery filters `#OCCURRENCE#` only.
- Run metadata client writes `#RUN#` child records.
- The user observed one full audit item plus repeated minimal items with the same `audit_id`, matching `_safe_audit()` behavior for child rows.

### Relation to Lambda get-policy/serverless suspicion

The earlier Lambda `get-policy` `ResourceNotFoundException` is not supported as the cause of `audit create --force` and is not strong evidence of finalization invocation failure by itself.

Evidence:

- `audit create` uses S3 and DynamoDB metadata paths, not Scheduler or Lambda invocation.
- EventBridge Scheduler target creation uses `RoleArn` in `EventBridgeSchedulerClient.create_schedule()`.
- Serverless IaC defines `BackendSchedulerInvocationRole` with `lambda:InvokeFunction` permission for both scheduled execution and audit finalization Lambdas.
- For this architecture, the relevant permission check is the scheduler invocation role and schedule target config, not necessarily Lambda resource-based `get-policy` output.

Remaining deployment risk: live AWS could still differ from checked-in/compiled IaC, or finalization Lambda could have runtime errors. That requires read-only AWS verification if the developer wants to confirm live deployment state before implementing recovery.

## 8. Confidence Level

**High** for:

- why `audit create --force` is blocked;
- why `audit list` has duplicate/minimal entries;
- the repository-level finalization success path leaving audits in `FINALIZING`.

**Medium** for the exact live cause of this specific audit remaining `FINALIZING`, because CloudWatch finalization logs and a direct DynamoDB projection of `finalization`, `execution_counters`, and `lifecycle_history` were not provided.

## 9. Recommended Fix

Likely owner: **backend / operator CLI**.

Proposed scoped fix plan:

1. Fix audit discovery filtering.
   - File: `src/release_confidence_platform/storage/audit_metadata_client.py` and/or `src/release_confidence_platform/operator_cli/discovery_service.py`.
   - Preferred behavior: return only canonical audit metadata rows where `SK` has shape `AUDIT#<audit_id>` with no additional suffix.
   - Do not rely only on excluding `#OCCURRENCE#`; also exclude `#RUN#` and any future child-record suffixes by requiring canonical SK equality/shape.
   - Consider adding a DynamoDB `FilterExpression` or post-query strict filter; post-query is simpler but may require pagination awareness if many child rows fill the page.

2. Define and implement finalization success semantics.
   - File: `apps/backend/handlers/audit_finalization_handler.py` plus mirrored package/source modules if applicable.
   - Product/architecture decision needed: should successful finalization transition immediately to `COMPLETED`, or should it enqueue/trigger `ANALYZING -> REPORTING -> COMPLETED` workers?
   - If no analyzer/reporter exists yet, a pragmatic dev/HITL fix may transition `FINALIZING -> COMPLETED` after `record_finalization()` when `execution_count > 0`, with lifecycle history reason such as `finalization_completed`.
   - Update tests that currently assert `FINALIZING` remains after successful finalization.

3. Improve `FORCE_RECREATE_BLOCKED` operator guidance.
   - File: `src/release_confidence_platform/operator_cli/result.py`.
   - Add a dedicated next-step branch explaining that force recreate is allowed only for `DRAFT`/`FAILED`, advising `rcp audit list` or direct metadata read, recommending a fresh audit ID as safest recovery, and warning that `CANCELLED`/`COMPLETED`/`FINALIZING` are not eligible.
   - Consider including sanitized `current_state` in `AuditCreationService` error messages.

4. Live recovery plan for this HITL audit.
   - Do not manually mutate DynamoDB until active schedules and finalization state are confirmed.
   - Safest immediate operator path: create/use a fresh audit ID/config bundle.
   - If same audit ID must be reused in dev, perform a controlled admin repair only after confirming no active EventBridge schedules/in-flight executions. A product-approved repair should set a safe terminal/eligible state and preserve history.

5. Serverless/Lambda verification.
   - No Lambda resource-policy fix is recommended from current evidence.
   - Verify live scheduler role/target config if finalization invocation is still suspected after code review.

## 10. Suggested Validation Steps

After fixing `audit list`:

1. Add a unit/API test where repository returns:
   - `SK=AUDIT#audit1` canonical row,
   - `SK=AUDIT#audit1#RUN#run1`,
   - `SK=AUDIT#audit1#OCCURRENCE#occ1`.
2. Assert `rcp audit list` returns exactly one audit item and `count: 1`.
3. Validate with live HITL command that repeated minimal entries disappear.

After fixing finalization lifecycle:

1. Update `tests/integration/test_phase3_cancellation_finalization.py::test_finalization_with_executions_remains_finalizing` to the approved final state.
2. Add assertions for lifecycle history entries after successful finalization.
3. Manually trigger/observe finalization for a dev audit with at least one completed execution and confirm it transitions out of `FINALIZING`.
4. Confirm zero-execution finalization still transitions to `FAILED`.
5. Confirm duplicate finalization delivery is idempotent for terminal/success state.

After improving force guidance:

1. Unit test `render_error("audit create", "dev", "FORCE_RECREATE_BLOCKED", ...)` includes lifecycle allowlist and recovery guidance.
2. Regression test `audit create --force` still succeeds only from `DRAFT` and `FAILED` and does not mutate S3/metadata for `FINALIZING`.

Recommended read-only AWS diagnostics before live recovery, if available:

```bash
aws dynamodb get-item \
  --profile rk-reliability \
  --region us-east-1 \
  --table-name release-confidence-platform-dev-metadata \
  --key '{"PK":{"S":"CLIENT#client_layer_1_validation_client_b5817642"},"SK":{"S":"AUDIT#audit_20260524_ec3f2d9b"}}' \
  --projection-expression 'client_id,audit_id,lifecycle_state,lifecycle_history,execution_counters,finalization,schedules,cleanup_errors,updated_at'
```

```bash
aws scheduler list-schedules \
  --profile rk-reliability \
  --region us-east-1 \
  --group-name rcp-dev-schedules \
  --query 'Schedules[?contains(Name, `audit_20260524_ec3f2d9b`)]'
```

```bash
aws lambda get-function \
  --profile rk-reliability \
  --region us-east-1 \
  --function-name release-confidence-platform-dev-auditFinalization
```

```bash
aws logs filter-log-events \
  --profile rk-reliability \
  --region us-east-1 \
  --log-group-name /aws/lambda/release-confidence-platform-dev-auditFinalization \
  --filter-pattern 'audit_20260524_ec3f2d9b'
```

## 11. Open Questions / Missing Evidence

- Does live DynamoDB `lifecycle_history` show `RUNNING -> FINALIZING` and no later transition for this audit?
- What are live `execution_counters` and `finalization` metadata for this audit?
- Are any EventBridge schedules still active for this audit ID?
- Did the finalization Lambda produce successful logs or runtime errors at `2026-05-30T13:19:47Z`?
- Product decision: should nonzero-execution finalization transition directly to `COMPLETED`, or should `ANALYZING`/`REPORTING` states be implemented before completion?

## 12. Final Investigator Decision

**Ready for developer fix** for:

- `audit list` canonical-row filtering;
- `FORCE_RECREATE_BLOCKED` guidance;
- repository/test alignment around finalization success-path lifecycle once product confirms the intended terminal path.

**Additional read-only AWS evidence recommended before live recovery of this specific audit ID**, but not required to start the code fixes above. Do not create a new branch, and do not manually mutate DynamoDB or delete schedules without confirming active schedule/in-flight execution state.
