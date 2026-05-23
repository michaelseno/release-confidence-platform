# Test Report

## 1. Execution Summary

- Total tests/checks: 21
- Passed: 21
- Failed: 0
- QA decision: **Approved**

QA was rerun on the current active branch after the HITL deployment blocker fix for `docs/bugs/backend_lambda_reserved_aws_region_bug_report.md`, then updated again for final cleanup validation after user-reported successful deployment and HITL validation. No branch switch, cloud deploy, push, commit, or PR was performed.

## 2. Detailed Results

| ID | Acceptance criteria | Validation | Outcome | Evidence |
| --- | --- | --- | --- | --- |
| QA-01 | Backend Serverless config exists | Inspected `infra/serverless.yml` | Pass | File exists and defines `service: release-confidence-platform`. |
| QA-02 | Reserved Lambda env fix | Inspected `infra/serverless.yml` provider env | Pass | User-defined env vars are `STAGE`, `RAW_RESULTS_BUCKET`, `METADATA_TABLE`, `SCHEDULER_GROUP_NAME`, `LOG_LEVEL`; `AWS_REGION` is absent. |
| QA-03 | Packaged CloudFormation excludes reserved key | Ran package for `dev`, `staging`, `prod` and inspected generated templates | Pass | `CoreEngineOrchestratorLambdaFunction`, `ScheduledExecutionLambdaFunction`, and `AuditFinalizationLambdaFunction` all have env keys `LOG_LEVEL`, `METADATA_TABLE`, `RAW_RESULTS_BUCKET`, `SCHEDULER_GROUP_NAME`, `STAGE`; `aws_region_present=False` for every function/stage. |
| QA-04 | All three backend handlers configured | Inspected Serverless state/templates | Pass | Functions are `coreEngineOrchestrator`, `scheduledExecution`, `auditFinalization` with existing backend handlers. |
| QA-05 | Required non-reserved env vars remain | Generated CloudFormation inspection | Pass | Required env set is present for all three Lambdas in dev/staging/prod. |
| QA-06 | IAM/S3/DynamoDB/Secrets Manager/CloudWatch/Scheduler resources remain | Static and generated template inspection | Pass | `RawResultsBucket`, `MetadataTable`, `BackendSchedulerGroup`, `BackendSchedulerInvocationRole`, Lambda execution IAM role, and Lambda log groups are generated; IAM statements include logs, S3, DynamoDB, Secrets Manager, and Scheduler invoke permissions. |
| QA-07 | Stage support works | `npx serverless print --stage dev/staging/prod` | Pass | All supported stages rendered successfully. |
| QA-08 | Package validates | `npx serverless package --stage dev/staging/prod` | Pass | All package commands completed with `✔ Service packaged`. |
| QA-09 | Package excludes mock target API content | ZIP inspection for dev/staging/prod | Pass | `mock_entries=0`, `pycache_pyc_entries=0`, required backend handler files present, `zip_entries=82`. |
| QA-10 | Mock API config unaffected | Inspected `apps/mock-target-api/serverless.yml` | Pass | Separate `service: mock-target-api` HTTP API config remains unchanged and independent. |
| QA-11 | No API Gateway introduced | Generated CloudFormation inspection | Pass | `api_gateway_resources=[]` for dev/staging/prod backend packages. |
| QA-12 | User deploy scripts preserved | Inspected `infra/package.json` | Pass | `deploy:dev`, `deploy:staging`, and `deploy:prod` scripts remain present. |
| QA-13 | Regression/unit coverage | `python3.11 -m pytest tests/unit/test_infra_configuration.py` and full suite | Pass | Infra reserved-key regression test included; full suite passed. |
| QA-14 | Deployment docs updated | Inspected `docs/backend/backend_deployment.md` | Pass | Docs state `AWS_REGION` is intentionally not configured because it is Lambda-reserved; `RCP_*` operator config remains documented. |
| QA-15 | Duplicate cleanup path removed | Filesystem check for `config/stages 2` | Pass | `PASS: config/stages 2 absent`. |
| QA-16 | Real runtime stage configs intact | Filesystem and file-content inspection for `config/stages/dev.json`, `staging.json`, `prod.json` | Pass | All three files remain present and non-empty; each retains region/profile/resource placeholder settings. |
| QA-17 | No stale duplicate-path references | Repository content search for `config/stages 2\|stages 2` | Pass | Search result: `No files found`. |
| QA-18 | Minimal backend deploy-config regression after cleanup | `npm run package:dev` from `infra/` | Pass | Serverless packaged dev stage successfully: `✔ Service packaged (2s)`. |
| QA-19 | Reserved Lambda env var remains absent after cleanup | Inspected `infra/serverless.yml` and generated `.serverless/serverless-state.json` after dev package | Pass | Generated provider env keys are `LOG_LEVEL`, `METADATA_TABLE`, `RAW_RESULTS_BUCKET`, `SCHEDULER_GROUP_NAME`, `STAGE`; `aws_region_in_provider_env=False`. |
| QA-20 | Backend package still excludes mock API after cleanup | ZIP inspection of `infra/.serverless/release-confidence-platform.zip` | Pass | `mock_entries=0`; required backend handler files present; `zip_entries=82`. |
| QA-21 | Mock API config remains unaffected after cleanup | Inspected `apps/mock-target-api/serverless.yml` | Pass | Separate `service: mock-target-api`, HTTP API routes, and mock env vars remain present. |

### Execution evidence

Serverless version:

```text
Framework Core: 3.40.0 (local)
Plugin: 7.2.3
SDK: 4.5.1
```

Commands executed from `infra/`:

```bash
npx serverless print --stage dev
npx serverless print --stage staging
npx serverless print --stage prod
npx serverless package --stage dev
npx serverless package --stage staging
npx serverless package --stage prod
```

Package result:

```text
Packaging release-confidence-platform for stage dev (us-east-1)
✔ Service packaged (2s)
Packaging release-confidence-platform for stage staging (us-east-1)
✔ Service packaged (2s)
Packaging release-confidence-platform for stage prod (us-east-1)
✔ Service packaged (2s)
```

Generated CloudFormation/package inspection:

```text
stage=dev: functions=['auditFinalization', 'coreEngineOrchestrator', 'scheduledExecution']; all three Lambda env key sets=['LOG_LEVEL', 'METADATA_TABLE', 'RAW_RESULTS_BUCKET', 'SCHEDULER_GROUP_NAME', 'STAGE']; aws_region_present=False; api_gateway_resources=[]; mock_entries=0; zip_entries=82
stage=staging: functions=['auditFinalization', 'coreEngineOrchestrator', 'scheduledExecution']; all three Lambda env key sets=['LOG_LEVEL', 'METADATA_TABLE', 'RAW_RESULTS_BUCKET', 'SCHEDULER_GROUP_NAME', 'STAGE']; aws_region_present=False; api_gateway_resources=[]; mock_entries=0; zip_entries=82
stage=prod: functions=['auditFinalization', 'coreEngineOrchestrator', 'scheduledExecution']; all three Lambda env key sets=['LOG_LEVEL', 'METADATA_TABLE', 'RAW_RESULTS_BUCKET', 'SCHEDULER_GROUP_NAME', 'STAGE']; aws_region_present=False; api_gateway_resources=[]; mock_entries=0; zip_entries=82
```

Automated regression evidence:

```text
python3.11 -m pytest tests/unit/test_infra_configuration.py
4 passed in 1.60s

python3.11 -m pytest tests
100 passed in 0.43s
```

Final cleanup validation evidence, executed after duplicate directory deletion:

```text
if [ -d "config/stages 2" ]; then ...; fi && for f in "config/stages/dev.json" "config/stages/staging.json" "config/stages/prod.json"; do ...; done
PASS: config/stages 2 absent
PASS: config/stages/dev.json present and non-empty
PASS: config/stages/staging.json present and non-empty
PASS: config/stages/prod.json present and non-empty

Repository content search: config/stages 2|stages 2
No files found
```

Backend Serverless dev package after cleanup:

```text
npm run package:dev

> release-confidence-platform-infra@0.0.0 package:dev
> serverless package --stage dev

(node:8186) [DEP0040] DeprecationWarning: The `punycode` module is deprecated. Please use a userland alternative instead.

Packaging release-confidence-platform for stage dev (us-east-1)

✔ Service packaged (2s)
```

Generated backend package/config inspection after cleanup:

```text
provider_env_keys=LOG_LEVEL,METADATA_TABLE,RAW_RESULTS_BUCKET,SCHEDULER_GROUP_NAME,STAGE
aws_region_in_provider_env=False
functions=auditFinalization,coreEngineOrchestrator,scheduledExecution
auditFinalization_handler=apps.backend.handlers.audit_finalization_handler.handler
coreEngineOrchestrator_handler=apps.backend.handlers.orchestrator_handler.handler
scheduledExecution_handler=apps.backend.handlers.scheduled_execution_handler.handler
zip_entries=82
mock_entries=0
required_backend_handlers_missing=
```

Regression execution after cleanup:

```text
python3.11 -m pytest tests/unit/test_infra_configuration.py
4 passed in 0.01s

python3.11 -m pytest tests
100 passed in 0.46s
```

## 3. Failed Tests

None.

## 4. Failure Classification

No failures to classify.

## 5. Observations

- Serverless emitted Node `DEP0040` `punycode` deprecation warnings during local validation. This is non-blocking and did not affect print/package results.
- Cloud deploy was not run, per instruction that local validation is sufficient unless explicitly safe/configured.
- Final cleanup validation was limited to local filesystem/config/package/regression checks because user already reported successful deployment and HITL validation.

## 6. Regression Check

Confirmed unchanged/working behaviors:

- Full automated test suite passed: 100/100.
- Backend deployment remains event-driven with no API Gateway resources.
- Mock target API remains separate and excluded from backend packages.
- Duplicate `config/stages 2` path is absent and has no stale references.
- Real runtime config directory `config/stages/` remains intact with dev/staging/prod configs.
- Required S3, DynamoDB, IAM, CloudWatch Logs, Secrets Manager permission, and Scheduler resources/permissions remain present.
- User-added `infra/package.json` deployment scripts remain present.

## 7. QA Decision

**Approved.** The HITL blocker remains resolved, and final duplicate directory cleanup is validated: `config/stages 2` is removed, `config/stages/` remains intact, no stale references exist, backend dev packaging succeeds, reserved `AWS_REGION` remains absent from user-defined Lambda environment, mock API config remains unaffected, and regression tests pass.

[QA SIGN-OFF APPROVED]

Final post-cleanup approval context: validation verified unused `config/stages 2` was removed, `config/stages/` remains intact, no references to `stages 2` remain, and backend Serverless deploy/package criteria remain unaffected. User deployment was successful and HITL validation was provided after QA approval.
