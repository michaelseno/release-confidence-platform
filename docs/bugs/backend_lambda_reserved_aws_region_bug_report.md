# Bug Report

## 1. Summary

HITL deployment validation is blocked because `infra/serverless.yml` configures `AWS_REGION` as a user-defined Lambda environment variable. AWS Lambda reserves `AWS_REGION`, so CloudFormation fails while creating Lambda functions during `serverless deploy --stage dev`.

## 2. Investigation Context

- Source of report: HITL validation after QA sign-off.
- Branch context: active branch `bugfix/backend_serverless_deploy_config`; no branch switch performed.
- Related workflow: backend Serverless Framework deployment from `infra/`.
- User action: added npm deploy scripts to `infra/package.json`, then ran `serverless deploy --stage dev` from `infra`.
- Failing resource reported by AWS: `ScheduledExecutionLambdaFunction` (`AWS::Lambda::Function`).

## 3. Observed Symptoms

Failing command/workflow:

```text
serverless deploy --stage dev
```

User-reported deployment error:

```text
Deploying release-confidence-platform to stage dev (us-east-1)

✖ Stack release-confidence-platform-dev failed to deploy (101s)
Error:
CREATE_FAILED: ScheduledExecutionLambdaFunction (AWS::Lambda::Function)
Resource handler returned message: "Lambda was unable to configure your environment variables because the environment variables you have provided contains reserved keys that are currently not supported for modification. Reserved keys used in this request: AWS_REGION (Service: Lambda, Status Code: 400, Request ID: 251b5ed6-afa6-409d-a310-4f9e857e4a6b) (SDK Attempt Count: 1)"
```

Expected behavior: `serverless deploy --stage dev` should create/update the backend stack successfully.

Actual behavior: CloudFormation create fails when Lambda rejects the environment variable set containing reserved key `AWS_REGION`.

## 4. Evidence Collected

Files inspected:

- `infra/serverless.yml`
- `infra/package.json`
- `docs/qa/backend_serverless_deploy_config_test_plan.md`
- `docs/qa/backend_serverless_deploy_config_test_report.md`
- `docs/backend/backend_deployment.md`
- `docs/backend/backend_serverless_deploy_config_implementation_report.md`
- `tests/unit/test_infra_configuration.py`
- Backend handler env usage under `apps/backend/handlers/`

Key evidence:

- `infra/serverless.yml:15-21` defines provider-level Lambda environment variables, including `AWS_REGION` at line 17:

```yaml
provider:
  environment:
    STAGE: ${self:provider.stage}
    AWS_REGION: ${self:provider.region}
    RAW_RESULTS_BUCKET: ${self:custom.rawResultsBucketName}
    METADATA_TABLE: ${self:custom.metadataTableName}
    SCHEDULER_GROUP_NAME: ${self:custom.schedulerGroupName}
    LOG_LEVEL: INFO
```

- `infra/serverless.yml:88-100` defines three Lambda functions: `coreEngineOrchestrator`, `scheduledExecution`, and `auditFinalization`.
- Because the reserved key is configured at `provider.environment`, Serverless applies it to all functions unless overridden. The reported failure surfaced first on `ScheduledExecutionLambdaFunction`, but the same invalid env var would affect all backend Lambda functions generated from this provider-level environment block.
- Backend handlers do not read `AWS_REGION` directly:
  - `apps/backend/handlers/orchestrator_handler.py:17-20` reads `RAW_RESULTS_BUCKET` and `METADATA_TABLE`, then creates default-region boto3 clients/resources.
  - `apps/backend/handlers/scheduled_execution_handler.py:148-154` reads `METADATA_TABLE` and `RAW_RESULTS_BUCKET`, then creates default-region boto3 clients/resources.
  - `apps/backend/handlers/audit_finalization_handler.py:96-97` reads `METADATA_TABLE`.
- `packages/storage/aws_client_factory.py:19` uses `stage_config.region` for operator-side AWS clients, not Lambda runtime env `AWS_REGION`.
- QA artifacts incorrectly treated user-defined `AWS_REGION` as expected:
  - `docs/qa/backend_serverless_deploy_config_test_plan.md:38-42` expected `STAGE`, `AWS_REGION`, `RAW_RESULTS_BUCKET`, `METADATA_TABLE`, `SCHEDULER_GROUP_NAME`, and `LOG_LEVEL`.
  - `docs/qa/backend_serverless_deploy_config_test_report.md:16-23` marked provider env var inspection and package validation as passing.
- Deployment docs also list `AWS_REGION` as a Serverless-defined Lambda env var in `docs/backend/backend_deployment.md:35-44`.
- Current working tree status shows user package script edits that should be preserved:

```text
## bugfix/backend_serverless_deploy_config
 M infra/package.json
?? docs/bugs/backend_serverless_deploy_config_bug_report.md
?? docs/qa/backend_serverless_deploy_config_test_plan.md
?? docs/qa/backend_serverless_deploy_config_test_report.md
```

- `infra/package.json` diff adds deploy scripts only:

```diff
+    "deploy:dev": "serverless deploy --stage dev",
+    "deploy:staging": "serverless deploy --stage staging",
+    "deploy:prod": "serverless deploy --stage prod"
```

These package changes are unrelated to the Lambda reserved environment variable failure and should not be overwritten.

## 5. Execution Path / Failure Trace

1. HITL runs `serverless deploy --stage dev` from `infra/`.
2. Serverless resolves `infra/serverless.yml` for service `release-confidence-platform` and stage `dev`.
3. Provider-level environment variables are attached to generated Lambda functions.
4. The generated `ScheduledExecutionLambdaFunction` request includes user-defined environment key `AWS_REGION`.
5. AWS Lambda rejects the create request because `AWS_REGION` is a reserved Lambda-provided environment variable.
6. CloudFormation marks `ScheduledExecutionLambdaFunction` as `CREATE_FAILED`, causing stack deployment failure.

## 6. Failure Classification

- Primary classification: Application Bug.
- Severity: Blocker.

Justification: HITL cannot complete a non-production backend deployment after QA approval. The failing configuration is in the deployable infrastructure artifact and blocks CloudFormation stack creation before runtime validation can proceed.

## 7. Root Cause Analysis

### Confirmed Root Cause

Immediate failure point: AWS Lambda rejects the generated Lambda function create request because `AWS_REGION` is included in user-defined environment variables.

Underlying root cause: `infra/serverless.yml:15-21` defines `AWS_REGION: ${self:provider.region}` under provider-level `environment`. `AWS_REGION` is reserved by AWS Lambda and is automatically supplied by the Lambda runtime; it cannot be set or modified by deployment configuration.

Supporting evidence:

- AWS error explicitly names the reserved key: `Reserved keys used in this request: AWS_REGION`.
- `infra/serverless.yml:17` directly sets `AWS_REGION` in Lambda environment variables.
- The environment block is provider-level, so all three backend functions inherit the invalid key. The reported `ScheduledExecutionLambdaFunction` is the first observed create failure, not necessarily the only affected function.

Plausible contributing factors:

- QA validation covered `serverless print` and `serverless package`, but did not include a real CloudFormation deploy. These pre-deploy checks can render/package invalid Lambda reserved environment keys without contacting AWS Lambda.
- QA/test/docs explicitly expected `AWS_REGION` as a user-defined runtime env var, so the invalid configuration was accepted during review.

## 8. Confidence Level

High. The reported AWS error directly identifies `AWS_REGION` as the rejected reserved key, and the exact key is present in `infra/serverless.yml` provider-level Lambda environment configuration.

## 9. Recommended Fix

Likely owner: dev-backend / infrastructure.

Recommended scoped correction:

1. Remove `AWS_REGION` from user-defined Lambda environment variables in `infra/serverless.yml`.
2. Do not replace it with another user-defined region variable unless application code actually requires it. Current backend Lambda handlers do not read `AWS_REGION`; boto3 can use Lambda's runtime-provided region context.
3. If future Lambda runtime code requires explicit region access, read Lambda-provided `AWS_REGION` from `os.environ` without configuring it in Serverless, or use a non-reserved app-specific key such as `APP_AWS_REGION` only after confirming a real runtime need.
4. Update QA artifacts and docs that currently list user-defined `AWS_REGION` as expected:
   - `docs/qa/backend_serverless_deploy_config_test_plan.md`
   - `docs/qa/backend_serverless_deploy_config_test_report.md`
   - `docs/backend/backend_deployment.md`
   - any implementation report/checklist that claims `AWS_REGION` is configured by Serverless.
5. Add or update infra validation coverage so reserved Lambda env var names are not accepted in `provider.environment` or function-level environments. `tests/unit/test_infra_configuration.py` is the likely location for a static regression check.
6. Preserve the user-added deploy scripts in `infra/package.json`; they are useful for deployment and are not the root cause.

Cautions/constraints:

- Do not remove operator-side `RCP_AWS_REGION` configuration. That is separate from Lambda runtime env and is used by stage config/operator AWS clients.
- Do not remove Lambda-provided `AWS_REGION` usage if future code reads it; only remove the Serverless attempt to define it.

## 10. Suggested Validation Steps

After the fix:

1. Inspect `infra/serverless.yml` and generated Serverless output to confirm no user-defined Lambda environment contains `AWS_REGION`.
2. Run `serverless print --stage dev`, `serverless print --stage staging`, and `serverless print --stage prod` from `infra/`; verify remaining env vars include `STAGE`, `RAW_RESULTS_BUCKET`, `METADATA_TABLE`, `SCHEDULER_GROUP_NAME`, and `LOG_LEVEL`.
3. Run `serverless package --stage dev` from `infra/`; inspect generated CloudFormation for all three Lambda functions and confirm `AWS_REGION` is absent from their `Environment.Variables` blocks.
4. Run the targeted infra/unit regression test that rejects reserved Lambda env vars.
5. Re-run `serverless deploy --stage dev` from `infra/` or via the preserved `npm run deploy:dev` script and confirm CloudFormation proceeds past Lambda function creation.
6. If deploy succeeds, smoke-check stack outputs and the three function resources: `CoreEngineOrchestratorLambdaFunction`, `ScheduledExecutionLambdaFunction`, and `AuditFinalizationLambdaFunction`.

## 11. Open Questions / Missing Evidence

- Full generated CloudFormation from the failed deploy was not available in the workspace; `.serverless/` artifacts were not present during this investigation.
- Only the first CloudFormation failure was reported. Because the invalid env var is provider-level, all three functions are considered affected by configuration inheritance even though only `ScheduledExecutionLambdaFunction` appeared in the observed error.

## 12. Final Investigator Decision

Ready for developer fix.
