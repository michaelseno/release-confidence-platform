# Bug Report

## 1. Summary

During HITL validation of Enhanced `rcp config init` Default Profile System, live `rcp audit run` now enters the Lambda handler and emits the first-line `orchestrator_handler_started` log, but CloudWatch then shows only Lambda platform `END`/`REPORT` and no additional app-level orchestrator logs.

Repository inspection indicates the most likely explanation for the missing logs is an observability defect in the orchestrator: most normal progress logs are either absent or INFO-level Python logger calls that may be suppressed in Lambda, and several important milestones have no logs at all. The latest CLI synchronous handler response is required to determine whether this invocation completed, returned a sanitized failure, or produced artifacts despite sparse CloudWatch logging.

## 2. Investigation Context

- Source of report: HITL validation.
- Branch context: `feature/profile_driven_config_init` is the active correction branch; do not create a new branch.
- Related feature/workflow: Enhanced `rcp config init` Default Profile System followed by live `rcp audit run`.
- Runtime component: backend Lambda handler `apps.backend.handlers.orchestrator_handler.handler`.
- Latest reported CloudWatch sequence:
  - `INIT_START`
  - `START`
  - `orchestrator_handler_started`
  - `END`
  - `REPORT`
  - no other app-level logs
- Latest first-line handler log confirms direct manual event shape with keys: `client_id`, `audit_id`, `scenario_type`, `triggered_by`, `schedule_type`, `stage`.
- Important missing context: latest CLI output was not provided. Prior CLI output had surfaced `STORAGE_ERROR: S3 existence check failed`, but this may have changed after the IAM redeploy.

## 3. Observed Symptoms

- Failing workflow: live manual audit run via `rcp audit run`.
- Observed CloudWatch behavior: handler start log appears, then no orchestrator progress/failure/completion logs before Lambda `END`/`REPORT`.
- Observed duration: approximately 2769 ms.
- User-visible symptom: “seems the orchestration started but thats it.”
- Expected behavior:
  - CLI should surface the synchronous handler result for `rcp audit run`.
  - CloudWatch should show sanitized milestone logs for event validation, duplicate checks, config load, endpoint execution, raw-result write, metadata terminal update, and final success/failure.
  - If persistence/config/runtime fails, CloudWatch should contain a safe failure log and CLI `--output json` should expose the sanitized `handler_response.failure_summary`.

Exact latest CLI output is missing, so this investigation cannot confirm whether the handler returned `completed`, `failed`, or an unexpected success-shaped response.

## 4. Evidence Collected

### Handler entry and logging

- `apps/backend/handlers/orchestrator_handler.py:19` calls `logging.basicConfig(level=logging.INFO)`.
- `apps/backend/handlers/orchestrator_handler.py:22-34` emits `orchestrator_handler_started` with `print(json.dumps(...))`, which matches the CloudWatch log the user observed.
- `apps/backend/handlers/orchestrator_handler.py:37-47` then constructs S3/DynamoDB/Secrets clients and returns `CoreEngineOrchestrator(...).run(event)`.

### Orchestrator control flow after handler start

- `apps/backend/orchestrator/service.py:45-147` is the main `CoreEngineOrchestrator.run()` path.
- Control flow after handler start:
  1. validate event (`service.py:49`, `packages/core/validators.py:52-63`),
  2. build raw result key (`service.py:50-52`),
  3. duplicate preflight via S3 `object_exists` and DynamoDB `metadata_exists` (`service.py:53`, `149-161`),
  4. write started metadata (`service.py:54-55`),
  5. log `run_started` (`service.py:56-63`),
  6. load/validate configs (`service.py:78`, `163-170`),
  7. execute endpoints (`service.py:80-93`),
  8. write raw results (`service.py:103`),
  9. update terminal metadata (`service.py:105-115`),
  10. log `run_completed` (`service.py:116-124`),
  11. return sanitized completed payload (`service.py:125-133`).

### Existing app-level logs and missing milestones

Current orchestrator logs:

- `duplicate_run_id` only when duplicate preflight detects existing artifacts (`service.py:153-160`).
- `run_started` after started metadata is written (`service.py:56-63`).
- `run_completed` after raw result write and terminal metadata update (`service.py:116-124`).
- `run_failure_metadata_update_failed` if the failure metadata update itself fails (`service.py:227-236`).
- `run_failed` for sanitized failure responses (`service.py:242-249`).

Missing milestone logs:

- no event validation started/completed log;
- no raw result key computed log;
- no duplicate preflight started/completed log;
- no started metadata write attempted/succeeded log before `run_started`;
- no config load started/completed/failure log for client/audit/endpoints configs (`service.py:163-170`, `packages/config/loaders.py:12-37`);
- no endpoint execution started/completed log around `ApiRunner.execute()` (`service.py:80-93`, `apps/backend/runner/api_runner.py:49-152`);
- no raw result write attempted/succeeded log before/after `write_raw_results_once()` (`service.py:103`);
- no terminal metadata update attempted/succeeded log before/after `update_terminal()` (`service.py:105-115`);
- no explicit handler-level log of final returned status.

### Python logging behavior risk

- `packages/core/logging.py:34-66` implements `StructuredLogger` via `logging.getLogger("release-confidence-platform")` and `logger.log(...)`.
- Normal progress logs (`run_started`, `run_completed`) are INFO-level by default.
- In AWS Lambda, `logging.basicConfig(level=INFO)` may not affect the effective root logger when Lambda has already installed logging handlers. The first-line handler log is visible because it uses `print()`, not the service logger.
- If INFO is suppressed, successful runs would show `orchestrator_handler_started` but not `run_started` or `run_completed`.

### Synchronous CLI response handling exists but latest output is missing

- `src/release_confidence_platform/core/manual_run_service.py:53-58` validates the function name and invokes Lambda with `invocation_type="RequestResponse"`.
- `src/release_confidence_platform/storage/lambda_client.py:50-64` decodes sanitized handler payload for synchronous invocation and records `handler_response`, `handler_status`, and `handler_succeeded`.
- `src/release_confidence_platform/core/manual_run_service.py:59-65` maps handler status `failed` to CLI failure details.
- `src/release_confidence_platform/operator_cli/services.py:258-274` exits nonzero only when `data.status == "failed"` and otherwise reports execution/invocation completion.
- Therefore the latest `rcp audit run --output json` result should contain the most important evidence, but it was not included in the report.

### Persistence path failure visibility

- S3 duplicate check: `packages/storage/s3_client.py:31-40` converts `head_object` `ClientError` into `StorageError` with operation, key prefix, and required permission.
- Raw-result write: `packages/storage/s3_client.py:62-76` checks duplicate and writes S3 object.
- DynamoDB metadata existence: `packages/storage/dynamodb_client.py:22-24` calls `get_item` through `_call()`.
- DynamoDB `_call()` (`packages/storage/dynamodb_client.py:55-60`) does not convert `ClientError` to a sanitized `StorageError`; it only catches `TypeError` for fake/local clients. A live DynamoDB `ClientError` during `metadata_exists`, `put_started_once`, or `update_terminal` can be caught by the orchestrator broad `Exception` handler and returned as generic `ORCHESTRATION_ERROR`, losing actionable DynamoDB context.
- If a failure occurs before `started_item` is written, `_failure_response()` cannot persist terminal failure metadata because `event and started_item` is false (`service.py:217`).

## 5. Execution Path / Failure Trace

Likely path for the latest observed CloudWatch sequence:

1. Lambda runtime starts and enters `apps.backend.handlers.orchestrator_handler.handler`.
2. `_emit_handler_started(event)` prints a sanitized JSON record, visible in CloudWatch.
3. Handler constructs storage/secrets clients and calls `CoreEngineOrchestrator.run(event)`.
4. The orchestrator either:
   - completes or reaches later milestones, but INFO logs are suppressed and there are no milestone logs for much of the work; or
   - returns a sanitized failure response from an early storage/config/runtime error, with limited CloudWatch detail if the relevant log is absent/suppressed/missed.
5. Lambda returns normally, so CloudWatch shows `END`/`REPORT` without a runtime stack trace.

The absence of a stack trace makes a top-level unhandled exception in the handler less likely. The absence of `run_failed` makes a logged failure response less obvious, but not enough to prove success because the latest CLI synchronous response was not provided.

## 6. Failure Classification

- Primary classification: Application Bug.
- Contributing classification: Environment / Configuration Issue remains possible for the underlying audit failure because prior output reported S3 storage failure and latest CLI output is missing.
- Severity: Blocker.

Severity justification: HITL validation cannot confirm whether the core manual audit workflow completed, failed storage/config checks, wrote artifacts, or returned a sanitized failure. This blocks release validation of the profile-driven config initialization workflow.

## 7. Root Cause Analysis

### Most Likely Root Cause

The missing post-handler CloudWatch logs are most likely caused by inadequate orchestrator observability: normal progress uses INFO-level `StructuredLogger` logs that may not be emitted by the Lambda logging configuration, while key execution milestones have no logs at all.

Supporting evidence:

- The visible handler-start record is emitted with `print()` (`orchestrator_handler.py:22-34`), not `StructuredLogger`.
- `run_started` and `run_completed` are INFO-level service logger events (`service.py:56-63`, `116-124`).
- `StructuredLogger` delegates to Python logging (`packages/core/logging.py:63-65`).
- No logs exist around config load, endpoint execution, raw result write attempt/success, or terminal metadata write attempt/success.

### Plausible Contributing Factors

- An early persistence/config failure may still be occurring and returning a sanitized handler failure that is only visible in the CLI synchronous response. Prior CLI output reportedly showed `STORAGE_ERROR: S3 existence check failed`; the latest post-IAM output is unknown.
- DynamoDB storage failures can lose actionable context because `DynamoDBMetadataClient._call()` does not translate live `ClientError` into a sanitized `StorageError`.
- Failure before `put_started_once()` leaves no metadata artifact by design; failure metadata is only updated when both `event` and `started_item` exist (`service.py:217-226`).

## 8. Confidence Level

Medium.

Confidence is high that handler entry is confirmed and that orchestrator milestone logging is insufficient. Confidence is medium for the underlying execution outcome because the latest synchronous CLI output, raw handler payload, RequestId, and artifact checks were not provided.

## 9. Recommended Fix

Likely owner: backend/full-stack.

Recommended developer fix:

1. Configure Lambda-visible structured logging consistently:
   - In `apps/backend/handlers/orchestrator_handler.py`, set the root and `release-confidence-platform` logger levels from `LOG_LEVEL`, or use a Lambda-safe logging setup that guarantees INFO JSON records are emitted.
   - Keep the first-line `print()` handler-start log as a defensive fallback.
2. Add sanitized milestone logs in `apps/backend/orchestrator/service.py`:
   - `event_validation_started` / `event_validation_completed`;
   - `duplicate_check_started` / `duplicate_check_completed`;
   - `metadata_started_write_started` / `metadata_started_write_completed`;
   - `config_load_started` / `config_load_completed` with config type only, not config content;
   - `endpoint_execution_started` / `endpoint_execution_completed` with endpoint_id, method, iteration, failure_type/status only;
   - `raw_result_write_started` / `raw_result_write_completed` with safe key prefix/run identifiers;
   - `terminal_metadata_update_started` / `terminal_metadata_update_completed`;
   - handler/orchestrator final `run_returning` status log.
3. Improve persistence error diagnostics:
   - In `packages/storage/dynamodb_client.py`, convert `ClientError` in `_call()` or each public method into sanitized `StorageError` with operation, table name context, AWS error code, and required DynamoDB permission.
   - Preserve existing duplicate handling for `ConditionalCheckFailedException`.
4. Ensure every `_failure_response()` path logs at ERROR with safe failure summary and correlation fields when available.
5. Keep CLI synchronous response handling and ensure `rcp audit run --output json` includes sanitized `handler_response`, `handler_status`, run_id, and failure summary.

Cautions:

- Do not log full event payloads, headers, secrets, request bodies, raw responses, or config contents.
- Use safe identifiers, endpoint IDs, operation names, error codes, and key prefixes only.

## 10. Suggested Validation Steps

After the fix:

1. Run live `rcp audit run --output json` for a known valid audit.
2. Confirm CLI JSON includes `invocation.handler_response.status == "completed"` and a `raw_result_s3_key`, or a clear sanitized failure summary if it fails.
3. Query CloudWatch by RequestId and run_id and verify logs include handler start plus all major milestones through completion/failure.
4. Confirm S3 raw result exists under the returned `raw_result_s3_key`.
5. Confirm DynamoDB run metadata exists with terminal status `COMPLETED` or `FAILED`.
6. Regression-test failure cases:
   - invalid event shape;
   - missing config object;
   - S3 permission denied/head-object failure;
   - DynamoDB permission denied/get-item or put-item failure.
7. Verify malformed/failing cases return sanitized CLI failures and emit ERROR logs without leaking secrets.

## 11. Open Questions / Missing Evidence

- Latest exact CLI output for the post-IAM redeploy invocation, preferably `--output json`.
- CloudWatch RequestId for the invocation that showed only handler start and platform logs.
- Whether S3 raw result and DynamoDB metadata artifacts were checked for the generated/latest run_id.
- Exact stage, function name, and AWS profile used by the latest CLI command.
- Whether the deployed artifact exactly matches the current branch after the most recent fixes.

Immediate safe user diagnostics to request:

```bash
rcp audit run --stage <stage> --client-id <client_id> --audit-id <audit_id> --scenario-type <scenario_type> --output json
```

If a specific run_id was used or returned, query CloudWatch for it and/or the Lambda RequestId:

```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/release-confidence-platform-<stage>-coreEngineOrchestrator \
  --filter-pattern '"<run_id>"'
```

If only RequestId is known:

```bash
aws logs filter-log-events \
  --log-group-name /aws/lambda/release-confidence-platform-<stage>-coreEngineOrchestrator \
  --filter-pattern '"<request_id>"'
```

## 12. Final Investigator Decision

Ready for developer fix, with one important caveat: the observability/logging defect is ready to fix now, but the exact runtime failure/result for the latest invocation requires the latest CLI `--output json` or handler response payload.
