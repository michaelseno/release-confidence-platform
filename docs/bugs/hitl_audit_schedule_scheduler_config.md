# Bug Report

Title: HITL audit schedule blocked by unresolved scheduler stage configuration  
Date: 2026-05-31

## 1. Summary

During HITL validation on `bugfix/scheduled_execution_orchestration_rca`, `rcp audit schedule --stage dev` failed before any AWS scheduler call with `SCHEDULER_CONFIG_ERROR`. Repository evidence shows the CLI is rejecting the resolved local stage configuration because all four scheduler deployment values still resolve to committed placeholders or placeholder AWS account IDs. The leading hypothesis is operator environment/configuration setup: the scheduler deployment outputs have not been exported into the same shell/process that runs `rcp`, or the invoked `rcp` entry point is not seeing the current environment.

This is separate from the prior Lambda `get-policy` suspicion. The scheduler path uses EventBridge Scheduler `Target.RoleArn` with `lambda:InvokeFunction` permissions from the scheduler invocation role, not Lambda resource-based policy as the primary invocation mechanism.

Update after release-manager read-only inspection: the deployed dev CloudFormation stack and scheduler resources exist, and `rcp config stage-info --stage dev --output json` resolves successfully when run with `PYTHONPATH=src` and the deployed scheduler output values exported. This confirms the specific HITL failure was an operator environment recovery issue, not an application code defect.

## 2. Investigation Context

- Source of report: HITL validation blocker / regression handling.
- Active branch: `bugfix/scheduled_execution_orchestration_rca` confirmed by `git status --short --branch`.
- Related workflow: `init`, `validate`, and `create` succeeded for a new client/audit; `audit schedule` failed.
- Stage/region/profile context from prior validation: `stage=dev`, `region=us-east-1`, AWS profile `rk-reliability`.
- Expected scheduler group: `rcp-dev-schedules`.
- User-provided command:

```bash
rcp audit schedule \
  --client-id client_layer_1_schedule_validation_client_7331df81 \
  --audit-id audit_20260531_5f6409d1 \
  --stage dev
```

## 3. Observed Symptoms

- Failing workflow: `rcp audit schedule` for a newly created dev audit.
- Exact CLI output:

```text
ERROR: audit schedule failed
stage: dev
code: SCHEDULER_CONFIG_ERROR
message: Stage scheduler configuration contains placeholder or missing deployed resources: scheduler_group_name, scheduler_role_arn, scheduler_execution_target_arn, scheduler_finalization_target_arn. Export RCP_SCHEDULER_GROUP_NAME, RCP_SCHEDULER_EXECUTION_TARGET_ARN, RCP_SCHEDULER_FINALIZATION_TARGET_ARN, and RCP_SCHEDULER_ROLE_ARN from deployed scheduler outputs before running rcp audit schedule.
next_step: run rcp config stage-info --stage dev --output text and verify scheduler_group_name, scheduler_execution_target_arn, scheduler_finalization_target_arn, and scheduler_role_arn; export RCP_SCHEDULER_GROUP_NAME, RCP_SCHEDULER_EXECUTION_TARGET_ARN, RCP_SCHEDULER_FINALIZATION_TARGET_ARN, and RCP_SCHEDULER_ROLE_ARN from deployed scheduler outputs, then verify EventBridge Scheduler permissions and retry
```

- Expected behavior: when deployed scheduler output values are visible to the CLI, placeholder validation should pass and scheduling should proceed to metadata/config loading and EventBridge Scheduler schedule creation.
- Actual behavior: scheduling is stopped at local stage-config validation, before AWS profile/client construction or Scheduler API calls.

## 4. Evidence Collected

Files/code paths inspected:

- `config/stages/dev.json`
  - `scheduler_group_name` is `rcp-dev-schedules-placeholder`.
  - `scheduler_execution_target_arn` and `scheduler_finalization_target_arn` use AWS account `000000000000`.
  - `scheduler_role_arn` uses AWS account `000000000000`.
- `src/release_confidence_platform/config/stage_config.py`
  - `ENV_OVERRIDES` maps scheduler fields to the documented variables:
    - `scheduler_group_name` -> `RCP_SCHEDULER_GROUP_NAME`
    - `scheduler_execution_target_arn` -> `RCP_SCHEDULER_EXECUTION_TARGET_ARN`
    - `scheduler_finalization_target_arn` -> `RCP_SCHEDULER_FINALIZATION_TARGET_ARN`
    - `scheduler_role_arn` -> `RCP_SCHEDULER_ROLE_ARN`
  - `StageConfigLoader.load()` reads `config/stages/<stage>.json`, then applies environment overrides visible in `os.environ`.
  - `validate_scheduler_config()` rejects placeholders and ARNs containing `:000000000000:` and raises the exact observed `SCHEDULER_CONFIG_ERROR`.
- `src/release_confidence_platform/operator_cli/services.py`
  - `_stage(args)` calls `StageConfigLoader().load(args.stage)`.
  - `config_stage_info_command()` uses the same `_stage(args)` path and exposes scheduler fields and source guidance.
  - `schedule_command()` calls `_stage(args)` and then `stage_config.validate_scheduler_config()` for non-dry-run scheduling before constructing `AwsClientFactory`.
- `src/release_confidence_platform/operator_cli/result.py`
  - `render_error()` / `_error_next_step()` emits the observed `SCHEDULER_CONFIG_ERROR` next-step guidance.
  - `_render_config_stage_info_text()` includes scheduler fields in `rcp config stage-info` output.
- `infra/serverless.yml`
  - Defines Scheduler group naming as `custom.schedulerGroupName: rcp-${stage}-schedules`.
  - Defines functions `scheduledExecution` and `auditFinalization`.
- `infra/resources/scheduler.yml`
  - Defines `BackendSchedulerGroup` using `${self:custom.schedulerGroupName}`.
  - Defines `BackendSchedulerInvocationRole` trusted by `scheduler.amazonaws.com` and allowed `lambda:InvokeFunction` on `ScheduledExecutionLambdaFunction` and `AuditFinalizationLambdaFunction`.
  - Exports `SchedulerGroupName`, `SchedulerInvocationRoleArn`, `ScheduledExecutionTargetArn`, and `AuditFinalizationTargetArn`.
- Release-manager read-only deployed-environment evidence:
  - CloudFormation stack found: `release-confidence-platform-dev`.
  - Stack outputs found:
    - `SchedulerGroupName = rcp-dev-schedules`
    - `SchedulerInvocationRoleArn = arn:aws:iam::463470948609:role/release-confidence-platform-dev-scheduler-invoke`
    - `ScheduledExecutionTargetArn = arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-scheduledExecution`
    - `AuditFinalizationTargetArn = arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-auditFinalization`
  - Scheduler group `rcp-dev-schedules` exists and is `ACTIVE`.
  - Scheduled execution Lambda exists and is `Active`.
  - Audit finalization Lambda exists and is `Active`.
  - Scheduler invocation role exists.
  - With `PYTHONPATH=src` and exported scheduler environment variables, `rcp config stage-info --stage dev --output json` resolved successfully during release-manager inspection.

## 5. Execution Path / Failure Trace

1. CLI dispatches `audit schedule` to `services.schedule_command()`.
2. `schedule_command()` calls `_stage(args)`.
3. `_stage(args)` calls `StageConfigLoader().load("dev")`.
4. `StageConfigLoader.load()` reads `config/stages/dev.json` and applies only exported `RCP_*` environment variables visible to the `rcp` process.
5. For non-dry-run scheduling, `schedule_command()` calls `stage_config.validate_scheduler_config()` before `AwsClientFactory(stage_config)` and before any S3/DynamoDB/EventBridge Scheduler operation.
6. The validator sees placeholder scheduler values and raises `ConfigError(..., "SCHEDULER_CONFIG_ERROR")`.
7. `operator_cli.result.render_error()` renders the reported error and `stage-info` guidance.

## 6. Failure Classification

- Primary classification: **Environment / Configuration Issue** / operator environment recovery.
- Current status: **No application code fix indicated for this specific failure**. Deployed resources exist and the local CLI resolves successfully once the scheduler output environment variables are exported into the process environment.
- Contributing classification: **Application/Operations UX gap** only if operators are expected to run HITL scheduling without a documented script that exports the Serverless/CloudFormation scheduler outputs.
- Severity: **Blocker**.

Severity rationale: HITL validation cannot proceed to schedule creation for the new audit while scheduler config resolves to placeholders. This blocks the active scheduling validation workflow, although it fails safely before creating partial scheduler resources.

## 7. Root Cause Analysis

### Confirmed Root Cause

The failing `rcp` process resolved scheduler configuration from placeholder `config/stages/dev.json` values because deployed scheduler outputs were not exported into the same process environment used for HITL scheduling.

Supporting evidence:

- The exact invalid field list matches the placeholder fields in `config/stages/dev.json`.
- `validate_scheduler_config()` rejects `scheduler_group_name` containing `placeholder` and target/role ARNs containing account `000000000000`, matching the committed dev config.
- The documented env var names in the error message match `ENV_OVERRIDES`; no repository evidence shows an env-var naming mismatch.
- `config stage-info` and `audit schedule` share the same loader path, so `stage-info` from the same shell should reveal exactly what `audit schedule` will validate.
- The failure occurs before AWS calls; Lambda resource policies or EventBridge Scheduler target permissions cannot be the direct failure point for this specific error.
- Release-manager inspection confirmed the deployed stack outputs and AWS resources exist.
- Release-manager inspection confirmed `rcp config stage-info --stage dev --output json` resolves successfully when the scheduler output environment variables are exported with `PYTHONPATH=src`.

### Relation to Prior Scheduling Fix and Lambda-Permission Suspicion

- Prior scheduling RCA/fixes address runtime scheduled-execution orchestration behavior after schedules exist and fire.
- This blocker occurs earlier: local CLI stage-config validation prevents creating schedules at all.
- Prior Lambda `get-policy` findings are not direct evidence for this error. Inspected IaC and scheduler client design use EventBridge Scheduler `Target.RoleArn` with an IAM role that grants `lambda:InvokeFunction`; the relevant live permission check after config resolution is the scheduler invocation role and target ARN validity, not Lambda resource policy alone.

## 8. Confidence Level

High. The code directly explains why all four fields were rejected and proves the failure happens before AWS calls. The release-manager read-only evidence confirms the deployed stack/resources exist and that the CLI resolves successfully when the scheduler output environment variables are present.

## 9. Recommended Fix

- Likely owner for immediate next step: **user/operator / release-infrastructure environment recovery**.
- Likely owner if a productized fix is requested: **backend/dev-experience** for a script/command/docs to export or discover scheduler outputs.
- Implementation is not required for the immediate correction: export real scheduler outputs in the same shell that runs `rcp`.
- Do not change application scheduling logic for this specific error unless the exports below are present, `rcp config stage-info` resolves real values, and `rcp audit schedule` still fails with the same scheduler configuration error.

Concrete recovery plan:

1. In the same shell/process that will run `rcp audit schedule`, export the deployed dev scheduler outputs and AWS context:

```bash
export RCP_AWS_PROFILE=rk-reliability
export RCP_AWS_REGION=us-east-1
export RCP_SCHEDULER_GROUP_NAME=rcp-dev-schedules
export RCP_SCHEDULER_EXECUTION_TARGET_ARN=arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-scheduledExecution
export RCP_SCHEDULER_FINALIZATION_TARGET_ARN=arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-auditFinalization
export RCP_SCHEDULER_ROLE_ARN=arn:aws:iam::463470948609:role/release-confidence-platform-dev-scheduler-invoke
```

2. If running directly from the source checkout instead of an installed package, include `PYTHONPATH=src` in the command environment.
3. Run config validation from the same shell and verify no scheduler field contains `placeholder` or account `000000000000`:

```bash
PYTHONPATH=src rcp config stage-info --stage dev --output json
```

4. Retry the original `rcp audit schedule` command from the same shell.

Safe read-only diagnostic commands for the user/operator if more live evidence is needed:

```bash
PYTHONPATH=src rcp config stage-info --stage dev --output json
command -v rcp
python -c 'import release_confidence_platform, release_confidence_platform.config.stage_config as s; print(release_confidence_platform.__file__); print(s.__file__)'
aws cloudformation describe-stacks \
  --profile rk-reliability \
  --region us-east-1 \
  --stack-name release-confidence-platform-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`SchedulerGroupName` || OutputKey==`ScheduledExecutionTargetArn` || OutputKey==`AuditFinalizationTargetArn` || OutputKey==`SchedulerInvocationRoleArn`]'
```

Caution: `env` output can contain sensitive values; if sharing diagnostics, include only `RCP_SCHEDULER_*`, `RCP_SCHEDULE_NAME_PREFIX`, `RCP_AWS_PROFILE`, and `RCP_AWS_REGION`, and redact unrelated secrets.

## 10. Suggested Validation Steps

1. Same-shell config verification:
   - `PYTHONPATH=src rcp config stage-info --stage dev --output json` shows:
      - `scheduler_group_name: rcp-dev-schedules`
      - target/role ARNs with account `463470948609`, not `000000000000`
      - `schedule_name_prefix: rcp-dev`
2. Retry:

```bash
rcp audit schedule \
  --client-id client_layer_1_schedule_validation_client_7331df81 \
  --audit-id audit_20260531_5f6409d1 \
  --stage dev
```

3. If schedule creation succeeds, confirm audit lifecycle changes to `SCHEDULED` and schedules are recorded in metadata.
4. Read-only AWS validation:
   - Inspect EventBridge Scheduler group `rcp-dev-schedules` for schedules created for the new audit.
   - Verify each schedule target uses the expected Lambda target ARN and scheduler invocation role ARN.
5. If a new error appears after config validation, classify separately as AWS profile, metadata, scheduler request validation, lifecycle state, or permission issue.
6. Only reopen this as an application-code bug if the exact exports above are present, `stage-info` resolves the deployed values, and `audit schedule` still fails with `SCHEDULER_CONFIG_ERROR` for placeholder/missing scheduler resources.

## 11. Open Questions / Missing Evidence

- Remaining validation evidence after recovery: the user/operator should retry the original `audit schedule` command from the shell containing the exported values and report any new error separately.
- If scheduling still fails, capture same-shell `stage-info` output, `command -v rcp`, and the exact `audit schedule` output.

## 12. Final Investigator Decision

Likely test/environment issue, not application fix.

For the immediate HITL blocker, user/operator should export the confirmed deployed scheduler output values in the same shell and retry `rcp audit schedule`. No implementation or QA handoff is required for this specific failure unless the command still fails after the exports are present and `stage-info` resolves the deployed values.
