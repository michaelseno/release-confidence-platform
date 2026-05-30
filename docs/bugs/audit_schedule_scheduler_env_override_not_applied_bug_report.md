# Bug Report

## 1. Summary
During HITL validation, `rcp audit schedule --stage dev` still rejects all scheduler fields as placeholders after the user reportedly exported the documented scheduler environment variables. Repository code shows the documented env var names match `StageConfigLoader`, and `audit schedule` validates the resolved `StageConfig`, not raw JSON. The most likely cause is that the `rcp` subprocess did not see those exported variables, or the invoked `rcp` entry point is not using the current branch/worktree code.

## 2. Investigation Context
- Source of report: HITL validation after QA-approved audit schedule fix.
- Active branch: `feature/profile_driven_config_init` (must remain active correction branch).
- Workflow: schedule existing dev audit.
- Command reported by user:
  ```bash
  rcp audit schedule \
    --client-id client_layer_1_validation_client_b5817642 \
    --audit-id audit_20260524_ec3f2d9b \
    --stage dev
  ```
- User reportedly exported:
  - `RCP_SCHEDULER_GROUP_NAME=rcp-dev-schedules`
  - `RCP_SCHEDULER_EXECUTION_TARGET_ARN=arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-scheduledExecution`
  - `RCP_SCHEDULER_FINALIZATION_TARGET_ARN=arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-auditFinalization`
  - `RCP_SCHEDULER_ROLE_ARN=arn:aws:iam::463470948609:role/release-confidence-platform-dev-scheduler-invoke`
  - optional `RCP_SCHEDULE_NAME_PREFIX=rcp-dev`

## 3. Observed Symptoms
- CLI output:
  ```text
  ERROR: audit schedule failed
  stage: dev
  code: SCHEDULER_CONFIG_ERROR
  message: Stage scheduler configuration contains placeholder or missing deployed resources: scheduler_group_name, scheduler_role_arn, scheduler_execution_target_arn, scheduler_finalization_target_arn. Export RCP_SCHEDULER_GROUP_NAME, RCP_SCHEDULER_EXECUTION_TARGET_ARN, RCP_SCHEDULER_FINALIZATION_TARGET_ARN, and RCP_SCHEDULER_ROLE_ARN from deployed scheduler outputs before running rcp audit schedule.
  ```
- Expected behavior: after exported real scheduler values are visible to the CLI subprocess, placeholder validation should pass and scheduling should proceed to AWS/profile/metadata/scheduler validation.
- Actual behavior: all four scheduler fields are still reported invalid, matching unresolved `config/stages/dev.json` placeholder values.

## 4. Evidence Collected
- `src/release_confidence_platform/config/stage_config.py:26-37` maps scheduler fields to the documented env vars:
  - `scheduler_group_name` -> `RCP_SCHEDULER_GROUP_NAME`
  - `schedule_name_prefix` -> `RCP_SCHEDULE_NAME_PREFIX`
  - `scheduler_execution_target_arn` -> `RCP_SCHEDULER_EXECUTION_TARGET_ARN`
  - `scheduler_finalization_target_arn` -> `RCP_SCHEDULER_FINALIZATION_TARGET_ARN`
  - `scheduler_role_arn` -> `RCP_SCHEDULER_ROLE_ARN`
- `packages/config/stage_config.py:26-37` has the same scheduler env override mapping.
- `src/release_confidence_platform/config/stage_config.py:76-108` loads `config/stages/<stage>.json`, applies env overrides into `resolved`, and returns a `StageConfig` object.
- `src/release_confidence_platform/config/stage_config.py:123-149` validates the `StageConfig` object passed to `validate_scheduler_config()`. It does not re-read raw JSON.
- `packages/config/stage_config.py:65-97` and `packages/config/stage_config.py:100-126` have the same load-then-validate pattern.
- `src/release_confidence_platform/operator_cli/services.py:38-39` uses `StageConfigLoader().load(args.stage)` for all stage-aware commands.
- `src/release_confidence_platform/operator_cli/services.py:132-175` implements `config stage-info` through the same `_stage(args)` helper.
- `src/release_confidence_platform/operator_cli/services.py:232-236` implements `audit schedule` through the same `_stage(args)` helper and calls `stage_config.validate_scheduler_config()` before constructing `AwsClientFactory` for non-dry-run scheduling.
- `packages/operator_cli/services.py:33-34` and `packages/operator_cli/services.py:79-83` mirror the same schedule path for package imports.
- `config/stages/dev.json:7-11` contains placeholders/account `000000000000` for all scheduler fields. If env overrides are absent, the reported invalid fields exactly match these committed values.
- `tests/unit/test_config_init_cli.py:102-146` and `tests/unit/test_config_init_cli.py:149-186` assert that `config stage-info` resolves the documented scheduler env vars in text and JSON output.
- Current git branch confirmed by `git status --short --branch`: `## feature/profile_driven_config_init`.

## 5. Execution Path / Failure Trace
1. CLI dispatches `audit schedule` to `services.schedule_command()`.
2. `schedule_command()` calls `_stage(args)`.
3. `_stage(args)` calls `StageConfigLoader().load(args.stage)`.
4. `StageConfigLoader.load()` reads `config/stages/dev.json`, then overrides fields only for env vars visible in `os.environ` of the `rcp` process.
5. `schedule_command()` calls `stage_config.validate_scheduler_config()` on the resolved `StageConfig` before any AWS factory/client construction.
6. The reported `SCHEDULER_CONFIG_ERROR` listing all four scheduler fields means the resolved `StageConfig` still had placeholder scheduler values or placeholder account IDs for all four fields.

## 6. Failure Classification
- Primary classification: Environment / Configuration Issue.
- Severity: Blocker for HITL scheduling validation because non-dry-run scheduling cannot proceed while scheduler fields resolve to placeholders.

## 7. Root Cause Analysis
- Confidence label: Most Likely Root Cause.
- Immediate failure point: `StageConfig.validate_scheduler_config()` rejects `scheduler_group_name`, `scheduler_role_arn`, `scheduler_execution_target_arn`, and `scheduler_finalization_target_arn` before AWS calls.
- Underlying likely cause: the invoked `rcp` subprocess is not seeing the exported scheduler env vars, or the shell is invoking a stale/different `rcp` installation not tied to the current worktree.
- Supporting evidence:
  - There is no naming mismatch in either mirror; the documented `RCP_SCHEDULER_*` names match `ENV_OVERRIDES` exactly.
  - `audit schedule` and `config stage-info` share the same source loader in `src/.../operator_cli/services.py`.
  - Placeholder validation runs against the resolved `StageConfig`, not the raw file values.
  - The error names all four scheduler fields, which is consistent with no scheduler env overrides being visible and `config/stages/dev.json` placeholders remaining in effect.
- Not supported by current evidence: a code defect where placeholder validation checks original config after successful override resolution.

## 8. Confidence Level
Medium-high. The code path directly rules out env-var naming mismatch and raw-config validation. Full confirmation requires the user's same-shell diagnostic output showing whether `rcp` sees the variables and which `rcp` executable/module path is being invoked.

## 9. Recommended Fix
- Likely owner: release/infrastructure or operator environment, unless diagnostics prove `stage-info` resolves real values while `audit schedule` still fails.
- Code fix currently not indicated by repository evidence.
- Immediate user diagnostics to run in the same terminal/session immediately before retrying schedule:
  ```bash
  env | sort | grep '^RCP_SCHEDULER\|^RCP_SCHEDULE_NAME_PREFIX'
  command -v rcp
  rcp config stage-info --stage dev --output json
  python -c 'import release_confidence_platform, release_confidence_platform.config.stage_config as s; print(release_confidence_platform.__file__); print(s.__file__)'
  ```
- Expected diagnostic result if env is correct: `stage-info` JSON shows:
  - `scheduler_group_name: rcp-dev-schedules`
  - `scheduler_execution_target_arn` account `463470948609`
  - `scheduler_finalization_target_arn` account `463470948609`
  - `scheduler_role_arn` account `463470948609`
- If `stage-info` still shows placeholders, re-export in the same shell and ensure no command wrapper clears env. Use inline env assignment as a proof command if needed:
  ```bash
  RCP_SCHEDULER_GROUP_NAME=rcp-dev-schedules \
  RCP_SCHEDULER_EXECUTION_TARGET_ARN=arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-scheduledExecution \
  RCP_SCHEDULER_FINALIZATION_TARGET_ARN=arn:aws:lambda:us-east-1:463470948609:function:release-confidence-platform-dev-auditFinalization \
  RCP_SCHEDULER_ROLE_ARN=arn:aws:iam::463470948609:role/release-confidence-platform-dev-scheduler-invoke \
  RCP_SCHEDULE_NAME_PREFIX=rcp-dev \
  rcp config stage-info --stage dev --output json
  ```
- If `stage-info` resolves real values but `audit schedule` still reports the same placeholder fields, escalate as an application bug with both command outputs; that would contradict the inspected shared loader path.

## 10. Suggested Validation Steps
1. Confirm `git status --short --branch` remains on `feature/profile_driven_config_init`.
2. Run the same-shell env and `stage-info` diagnostics above.
3. Retry `rcp audit schedule ... --stage dev` only after `stage-info` shows no scheduler placeholders and no account `000000000000` in scheduler fields.
4. If scheduling proceeds beyond config validation, validate the next result separately: AWS profile/credentials, DynamoDB/S3 access, EventBridge Scheduler permissions, and created schedules in group `rcp-dev-schedules`.

## 11. Open Questions / Missing Evidence
- Output of `env | sort | grep '^RCP_SCHEDULER\|^RCP_SCHEDULE_NAME_PREFIX'` from the same shell that runs `rcp`.
- Output of `rcp config stage-info --stage dev --output json` after the exports.
- Path/version of the `rcp` executable actually invoked (`command -v rcp`) and imported module path.
- Whether the command was run through a wrapper, IDE task, subshell, sudo, or process manager that could drop exported env vars.

## 12. Final Investigator Decision
Likely test/environment issue, not application fix.
