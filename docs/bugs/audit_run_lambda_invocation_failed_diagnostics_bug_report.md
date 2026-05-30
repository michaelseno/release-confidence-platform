# Bug Report

## 1. Summary
During HITL validation of Enhanced `rcp config init` Default Profile System, `rcp audit run` fails with only the generic CLI error `LAMBDA_INVOCATION_FAILED`. The most likely immediate cause is that the effective dev stage config is still resolving `orchestrator_function_name` to the committed placeholder unless `RCP_ORCHESTRATOR_FUNCTION_NAME` is exported. The CLI currently swallows the underlying Lambda/AWS diagnostic details, so the user cannot tell whether this is a missing function/config override, IAM permission error, or Lambda-side failure.

## 2. Investigation Context
- Source of report: HITL validation.
- Active branch: `feature/profile_driven_config_init`.
- Related workflow: manual audit execution after successful/partially reconciled `rcp audit create` against real dev AWS resources.
- Reported command:

```bash
rcp audit run \
  --client-id client_layer_1_validation_client_b5817642 \
  --audit-id audit_20260524_ec3f2d9b \
  --scenario-type baseline_health \
  --stage dev
```

- Observed output:

```text
ERROR: audit run failed
stage: dev
code: LAMBDA_INVOCATION_FAILED
message: Lambda invocation failed
next_step: correct the error and retry
```

Known user-provided deployed dev resources:
- AWS profile: `rk-reliability`
- Region: `us-east-1`
- Config bucket: `release-confidence-platform-dev-raw-results`
- Metadata table: `release-confidence-platform-dev-metadata`
- Orchestrator Lambda qualified ARN: `arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-coreEngineOrchestrator:1`
- Scheduler group: `rcp-dev-schedules`

## 3. Observed Symptoms
- Failing workflow: `audit run` manual Lambda invocation.
- Exact CLI error: `code: LAMBDA_INVOCATION_FAILED`, `message: Lambda invocation failed`.
- Expected behavior: CLI invokes the deployed dev core engine orchestrator Lambda and either reports invocation acceptance/success metadata or returns a diagnostic that identifies the failing AWS/Lambda condition.
- Actual behavior: CLI reports a generic error with no function name, AWS error code, AWS message, `StatusCode`, `FunctionError`, request id, or response payload.

## 4. Evidence Collected
Files inspected:
- `config/stages/dev.json`
- `src/release_confidence_platform/config/stage_config.py`
- `src/release_confidence_platform/core/manual_run_service.py`
- `src/release_confidence_platform/storage/lambda_client.py`
- `src/release_confidence_platform/operator_cli/services.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `src/release_confidence_platform/storage/aws_client_factory.py`
- `apps/backend/handlers/orchestrator_handler.py`
- `apps/backend/orchestrator/service.py`
- `infra/serverless.yml`

Key findings:
- `config/stages/dev.json` still contains placeholders for the dev operator config:
  - `aws_profile`: `rcp-dev`
  - `config_bucket`: `rcp-dev-config-placeholder`
  - `audit_metadata_table`: `rcp-dev-audit-metadata-placeholder`
  - `orchestrator_function_name`: `rcp-dev-orchestrator-placeholder`
  - scheduler ARNs use account `000000000000`.
- `StageConfigLoader` only replaces the orchestrator target if `RCP_ORCHESTRATOR_FUNCTION_NAME` is present in the environment (`stage_config.py` lines 26-36, 84-91). It does not infer the orchestrator function from deployed outputs or scheduler target ARNs.
- `ManualRunInvocationService.run()` builds a valid-looking payload with `client_id`, `audit_id`, `scenario_type`, and `triggered_by: manual`, then invokes `self.stage_config.orchestrator_function_name` (`manual_run_service.py` lines 29-53).
- `LambdaInvocationClient.invoke()` catches every exception from `lambda_client.invoke(...)` and remaps it to `StorageError("Lambda invocation failed", "LAMBDA_INVOCATION_FAILED")` (`lambda_client.py` lines 19-27). The underlying `ClientError` code/message is not exposed.
- The wrapper uses `InvocationType="Event"` by default (`lambda_client.py` line 17). For async Lambda invocation, Lambda-side handler failures are not returned synchronously as `FunctionError`; the CLI generally only receives an invoke API status such as `202` if the invoke API call is accepted.
- Successful `audit create` against real resources proves the user likely has some effective overrides for profile/bucket/table, but it does not prove `RCP_ORCHESTRATOR_FUNCTION_NAME` is set because `audit create` does not use Lambda invocation.
- `render_error()` has no Lambda-specific next-step branch, so the user sees only `next_step: correct the error and retry` (`result.py` lines 288-344).

## 5. Execution Path / Failure Trace
1. CLI dispatches `audit run` through `src/release_confidence_platform/operator_cli/main.py` to `services.run_command()`.
2. `services.run_command()` loads dev stage config and constructs an AWS Lambda client from `AwsClientFactory`.
3. `ManualRunInvocationService.run()` validates the IDs/scenario and constructs:

```json
{
  "client_id": "client_layer_1_validation_client_b5817642",
  "audit_id": "audit_20260524_ec3f2d9b",
  "scenario_type": "baseline_health",
  "triggered_by": "manual"
}
```

4. The service invokes `stage_config.orchestrator_function_name`.
5. If `RCP_ORCHESTRATOR_FUNCTION_NAME` is not exported, that target is the placeholder `rcp-dev-orchestrator-placeholder` from `config/stages/dev.json`.
6. A Lambda API failure such as `ResourceNotFoundException` for that placeholder, `AccessDeniedException`, malformed target, or similar `ClientError` is caught by `LambdaInvocationClient.invoke()` and collapsed to `LAMBDA_INVOCATION_FAILED`.
7. CLI error rendering strips the exception cause, so no AWS diagnostic reaches the user.

## 6. Failure Classification
- Primary category: Environment / Configuration Issue.
- Contributing category: Application Bug, because Lambda invocation error mapping is too generic and blocks diagnosis.
- Severity: Blocker.

Severity justification: This blocks HITL validation of `audit run` against real dev resources and provides insufficient diagnostics to self-correct the active validation environment.

## 7. Root Cause Analysis
Confidence label: Most Likely Root Cause.

Immediate failure point:
- `src/release_confidence_platform/storage/lambda_client.py` catches the exception thrown by `boto3` Lambda `invoke()` and raises `StorageError("Lambda invocation failed", "LAMBDA_INVOCATION_FAILED")`.

Most likely underlying root cause:
- The effective `dev` stage config likely does not include a real orchestrator Lambda function target, because committed `config/stages/dev.json` has `orchestrator_function_name: "rcp-dev-orchestrator-placeholder"` and only `RCP_ORCHESTRATOR_FUNCTION_NAME` can override it. Prior successful `audit create` usage only validates S3/DynamoDB/profile overrides, not this Lambda-specific override.

Supporting evidence:
- Placeholder value is present in `config/stages/dev.json` line 6.
- Required environment override name is `RCP_ORCHESTRATOR_FUNCTION_NAME` in `stage_config.py` line 31.
- `audit run --dry-run` would report this exact resolved `function_name` from `ManualRunInvocationService` lines 43-49 without invoking AWS.
- Lambda wrapper swallows the AWS error details, preventing confirmation from the CLI output alone (`lambda_client.py` lines 25-27).

Less likely alternatives based on current evidence:
- Lambda function handler error: less likely to produce this CLI error because the wrapper invokes asynchronously with `InvocationType="Event"`; handler failures should usually be logged in Lambda/CloudWatch after an accepted `202`, not returned as `LAMBDA_INVOCATION_FAILED` by the invoke API.
- Missing audit metadata/config in S3/DynamoDB: also less likely to cause the observed CLI-side error for async invocation. Those failures occur inside the orchestrator after Lambda accepts the event and should be visible in Lambda logs/run metadata, not as a synchronous invoke API exception.
- Bad payload schema: current CLI payload shape matches `CoreEngineOrchestrator` scheduled/manual expectations (`client_id`, `audit_id`, `scenario_type`, `triggered_by`); no evidence of a schema mismatch in the CLI path.
- AWS permission issue: plausible if the function target is correct but the profile lacks `lambda:InvokeFunction`; currently indistinguishable because the `ClientError` code/message is swallowed.

## 8. Confidence Level
Medium.

The repository evidence strongly supports the placeholder/missing override diagnosis, but live confirmation requires the user's effective environment (`rcp config stage-info` / `audit run --dry-run`) or the underlying boto3 `ClientError` details. The current CLI intentionally hides those details.

## 9. Recommended Fix
Likely owner: backend/operator CLI.

Recommended developer fix:
1. In `src/release_confidence_platform/storage/lambda_client.py`, map Lambda `ClientError` exceptions to structured, sanitized errors that preserve actionable diagnostics:
   - include AWS error code such as `ResourceNotFoundException`, `AccessDeniedException`, `InvalidParameterValueException`, `TooManyRequestsException`;
   - include sanitized AWS message;
   - include sanitized `function_name`;
   - avoid exposing payload secrets.
2. Add a specific error/next-step branch in `src/release_confidence_platform/operator_cli/result.py` for Lambda invocation/config failures. It should tell users to check `config/stages/<stage>.json orchestrator_function_name` or export `RCP_ORCHESTRATOR_FUNCTION_NAME=<deployed-function-name-or-arn>` and verify `lambda:InvokeFunction` permission.
3. Add pre-invocation placeholder validation for `orchestrator_function_name` in the `audit run` path (or central stage-config resource validation) so committed placeholder values fail with a config-focused error before calling AWS.
4. Consider adding `function_name` to the non-dry-run success response and dry-run text output already exposes it via `ManualRunInvocationService`.
5. Optional but useful: support/validate deployed Serverless output names in docs/config init output so dev users know to set `RCP_ORCHESTRATOR_FUNCTION_NAME=release-confidence-platform-dev-coreEngineOrchestrator` or its ARN.

Cautions:
- Do not include raw request payloads in exception messages unless sanitized.
- If retaining async `InvocationType="Event"`, do not imply Lambda handler success; an accepted async invocation only proves the invoke API accepted the event.

## 10. Suggested Validation Steps
After the fix:
1. Unit test `LambdaInvocationClient.invoke()` with a fake/botocore-style `ClientError(ResourceNotFoundException)` and assert the rendered CLI output includes a sanitized function target and Lambda error code.
2. Unit test `AccessDeniedException` mapping to a permission-focused next step.
3. Unit test `audit run --dry-run --output json` with placeholder and real `RCP_ORCHESTRATOR_FUNCTION_NAME` values to confirm the effective function target is visible.
4. Manual HITL validation:
   - export real dev `RCP_*` overrides including `RCP_ORCHESTRATOR_FUNCTION_NAME`;
   - run `rcp audit run ... --dry-run --output json` and verify the real orchestrator target;
   - run AWS Lambda `DryRun` invocation with the same profile/region and target to verify `lambda:InvokeFunction` permission;
   - run `rcp audit run ...` and confirm CLI reports accepted invocation or a specific diagnostic.

## 11. Open Questions / Missing Evidence
- What is the user's effective `RCP_ORCHESTRATOR_FUNCTION_NAME` value, if any?
- Does `rcp audit run --dry-run --output json` currently show `rcp-dev-orchestrator-placeholder` or the real deployed orchestrator function?
- If the target is real, what is the underlying AWS `ClientError` code/message (`AccessDeniedException`, `ResourceNotFoundException`, etc.)?
- Are there CloudWatch logs for `release-confidence-platform-dev-coreEngineOrchestrator` at the time of the failed command? Absence of logs would support a pre-handler invoke API failure.

## 12. Final Investigator Decision
Ready for developer fix.

The likely user-side correction is to export/verify `RCP_ORCHESTRATOR_FUNCTION_NAME`, but the code also needs a developer fix because it swallows the underlying AWS Lambda error details and does not detect placeholder stage targets before invocation.
