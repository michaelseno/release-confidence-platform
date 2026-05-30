# Bug Report

## 1. Summary
`rcp audit schedule` fails during HITL validation with a generic `UNEXPECTED_ERROR` instead of an actionable scheduler/config error. The most likely immediate exception is an EventBridge Scheduler request serialization/shape failure because `Target.Input` is passed as a Python dict, while the AWS Scheduler API expects a JSON string.

## 2. Investigation Context
- Source of report: HITL validation.
- Active branch: `feature/profile_driven_config_init`.
- Workflow: schedule an existing persisted audit in dev.
- Command:
  ```bash
  rcp audit schedule \
    --client-id client_layer_1_validation_client_b5817642 \
    --audit-id audit_20260524_ec3f2d9b \
    --stage dev
  ```
- Observed live/dev environment from prior HITL:
  - `RCP_AWS_PROFILE=rk-reliability`
  - `RCP_CONFIG_BUCKET=release-confidence-platform-dev-raw-results`
  - `RCP_AUDIT_METADATA_TABLE=release-confidence-platform-dev-metadata`
  - `RCP_AWS_REGION=us-east-1`
  - `RCP_ORCHESTRATOR_FUNCTION_NAME=release-confidence-platform-dev-coreEngineOrchestrator`
  - Scheduler CloudFormation outputs reportedly include group `rcp-dev-schedules` and an invocation role ARN.

## 3. Observed Symptoms
- CLI output:
  ```text
  ERROR: audit schedule failed
  stage: dev
  code: UNEXPECTED_ERROR
  message: Unexpected operator CLI failure
  next_step: correct the error and retry
  ```
- Expected behavior:
  - If schedule creation succeeds, create EventBridge schedules and transition audit from `DRAFT` to `SCHEDULED`.
  - If scheduler resources/config/permissions are wrong, return a structured, actionable `EngineError` such as scheduler config, permission, validation, or create failure details.
- Actual behavior: a non-`EngineError` escapes the command path and is caught by the generic `except Exception` in `operator_cli/main.py`.

## 4. Evidence Collected
- `src/release_confidence_platform/operator_cli/main.py:164-184` catches `EngineError` as structured output, but maps all other exceptions to `UNEXPECTED_ERROR` with no diagnostic detail.
- `src/release_confidence_platform/operator_cli/services.py:217-238` wires `audit schedule` through `StageConfigLoader`, `AwsClientFactory`, `AuditSchedulingService.schedule_from_persisted_audit`, S3 config loading, DynamoDB metadata, and EventBridge Scheduler.
- `src/release_confidence_platform/audit_scheduling/service.py:51-72` loads audit metadata and persisted audit config, normalizes/validates schedule config, and builds schedule definitions.
- `src/release_confidence_platform/audit_scheduling/service.py:88-119` catches schedule creation exceptions, rolls back any created schedules, writes schedules/cleanup metadata, transitions audit to `FAILED`, then re-raises the original exception.
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py:30-51` builds the AWS `create_schedule` payload and catches only `ClientError`.
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py:41-45` sets:
  ```python
  "Input": sanitize(definition.target_payload)
  ```
  This is a dict, not a JSON string. EventBridge Scheduler `Target.Input` is a string field. Botocore should raise `ParamValidationError` before sending the request.
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py:50-51` catches only `ClientError`, so `ParamValidationError` is not converted to `StorageError` and reaches CLI generic handling.
- `packages/storage/eventbridge_scheduler_client.py:30-51` contains the same implementation, so packaged/backend import paths have the same defect.
- `config/stages/dev.json:7-11` still contains placeholder scheduler values:
  - `scheduler_group_name`: `rcp-dev-schedules-placeholder`
  - `scheduler_execution_target_arn`: account `000000000000`
  - `scheduler_finalization_target_arn`: account `000000000000`
  - `scheduler_role_arn`: account `000000000000`
- `src/release_confidence_platform/config/stage_config.py:26-37` supports scheduler env overrides:
  - `RCP_SCHEDULER_GROUP_NAME`
  - `RCP_SCHEDULE_NAME_PREFIX`
  - `RCP_SCHEDULER_EXECUTION_TARGET_ARN`
  - `RCP_SCHEDULER_FINALIZATION_TARGET_ARN`
  - `RCP_SCHEDULER_ROLE_ARN`
- Reported HITL environment did not include the scheduler-specific overrides above.
- `src/release_confidence_platform/operator_cli/services.py:132-160` and `operator_cli/result.py:201-227` expose only `scheduler_group` in `config stage-info`; target ARNs and scheduler role are omitted, making the missing overrides hard to diagnose.
- `infra/serverless.yml:83-84` defines deployed scheduler names as `rcp-${stage}-schedules` and `rcp-${stage}`.
- `infra/resources/scheduler.yml:32-53` outputs `SchedulerGroupName`, `SchedulerInvocationRoleArn`, `ScheduledExecutionTargetArn`, and `AuditFinalizationTargetArn`.

## 5. Execution Path / Failure Trace
1. CLI parser dispatches `audit schedule` to `services.schedule_command`.
2. `StageConfigLoader.load("dev")` reads `config/stages/dev.json` and applies exported `RCP_*` env overrides.
3. Because only bucket/table/profile/region/orchestrator overrides are known, scheduler fields likely remain placeholder values from `config/stages/dev.json`.
4. `AwsClientFactory.scheduler()` constructs `EventBridgeSchedulerClient` with group/target/role from stage config.
5. `AuditSchedulingService.schedule_from_persisted_audit()` reads DynamoDB audit metadata and S3 audit config, validates it, and builds schedule definitions.
6. `EventBridgeSchedulerClient.create_schedule()` calls boto3 `scheduler.create_schedule()` with `Target.Input` set to a dict.
7. Botocore likely raises `ParamValidationError` locally because `Target.Input` must be a string.
8. The scheduler client catches only `ClientError`, so the validation exception escapes as a generic exception.
9. The scheduling service marks the audit as `FAILED` on exception and re-raises.
10. CLI `main()` catches it in the generic `except Exception` path and renders `UNEXPECTED_ERROR`.

## 6. Failure Classification
- Primary classification: Application Bug.
- Contributing category: Environment / Configuration Issue, because dev scheduler fields are placeholders unless scheduler-specific env overrides are exported.
- Severity: Blocker. Scheduling cannot be validated in HITL, and the generic error prevents users from identifying whether the failure is request shape, missing scheduler config, missing resources, or permissions.

## 7. Root Cause Analysis
- Confidence label: Most Likely Root Cause.
- Immediate failure point: `EventBridgeSchedulerClient.create_schedule()` sends an invalid `Target.Input` value and does not catch `ParamValidationError`.
- Underlying root cause: scheduler AWS boundary lacks proper AWS API payload serialization and request-error mapping.
- Supporting evidence:
  - `Target.Input` is assigned a dict at `src/.../eventbridge_scheduler_client.py:41-45` and `packages/.../eventbridge_scheduler_client.py:41-45`.
  - Only `ClientError` is caught at `src/.../eventbridge_scheduler_client.py:50-51`; botocore request validation errors are not structured `EngineError`s.
  - CLI generic output matches `operator_cli/main.py:175-184`, which is only reached for non-`EngineError` exceptions.
- Plausible contributing factors:
  - `config/stages/dev.json` scheduler group/role/target ARNs are placeholders, and the known env list omits scheduler overrides. After fixing `Target.Input`, schedule creation may next fail with resource not found, validation, or access denied unless scheduler outputs are exported or stage config is updated.
  - `config stage-info` does not expose scheduler target ARNs or role ARN, obscuring this misconfiguration.

## 8. Confidence Level
High for the serialization/error-mapping diagnosis; medium for the scheduler placeholder contribution because the exact exported scheduler env vars from the failing shell were not captured. The code path directly explains why a low-level scheduler request problem becomes `UNEXPECTED_ERROR`.

## 9. Recommended Fix
- Likely owner: full-stack/backend platform.
- Files/modules:
  - `src/release_confidence_platform/storage/eventbridge_scheduler_client.py`
  - `packages/storage/eventbridge_scheduler_client.py`
  - `src/release_confidence_platform/config/stage_config.py` and `packages/config/stage_config.py`
  - `src/release_confidence_platform/operator_cli/services.py`
  - `src/release_confidence_platform/operator_cli/result.py`
  - unit/API tests around scheduler client and `config stage-info`.
- Expected correction:
  1. Serialize scheduler target input as JSON: `Input=json.dumps(sanitize(definition.target_payload), sort_keys=True)`.
  2. Catch botocore `ParamValidationError`/`BotoCoreError` in scheduler create/get/delete/update paths and raise sanitized `StorageError` with actionable scheduler request/config guidance.
  3. Add schedule-time stage config validation rejecting placeholder scheduler group, execution/finalization target ARNs, and role ARN before any mutation attempt.
  4. Extend `rcp config stage-info --output json` and text output to include `scheduler_group_name`, `schedule_name_prefix`, `scheduler_execution_target_arn`, `scheduler_finalization_target_arn`, and `scheduler_role_arn`, plus guidance for the env override names.
  5. Add test coverage that the AWS scheduler payload `Target.Input` is a string and that request validation errors are rendered as structured CLI errors, not `UNEXPECTED_ERROR`.
- Caution: `AuditSchedulingService.schedule_from_persisted_audit()` may have already transitioned the HITL audit to `FAILED` on the first attempt. Retesting may require a fresh audit or explicit lifecycle remediation.

## 10. Suggested Validation Steps
1. Unit test scheduler client payload generation: assert `Target.Input` is a JSON string and decodes to the expected schedule event.
2. Unit test a fake scheduler that raises `ParamValidationError`; verify CLI renders a structured scheduler/storage error.
3. Run `rcp config stage-info --stage dev --output json` and verify all scheduler fields resolve to deployed dev values, not placeholders/account `000000000000`.
4. Run `rcp audit schedule --dry-run ... --stage dev` on a fresh `DRAFT` audit; verify planned schedules render without scheduler AWS mutations.
5. Run `rcp audit schedule ... --stage dev` with scheduler env overrides exported; verify schedules are created in group `rcp-dev-schedules` and audit transitions to `SCHEDULED`.
6. Verify EventBridge Scheduler `get-schedule` returns created schedules with the expected target Lambda ARNs and role ARN.

## 11. Open Questions / Missing Evidence
- Exact traceback from the failing command was not available because CLI suppresses non-`EngineError` details.
- Need the output of `rcp config stage-info --stage dev --output json` from the same shell to confirm whether scheduler overrides were exported.
- Need CloudFormation scheduler output values to confirm target Lambda ARNs and role ARN.
- Need audit metadata after the failed attempt to confirm whether the audit was transitioned to `FAILED`.

## 12. Final Investigator Decision
Ready for developer fix.
