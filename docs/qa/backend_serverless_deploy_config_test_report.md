# Test Report

## 1. Execution Summary

- Total tests/checks: 13
- Passed: 13
- Failed: 0
- QA decision: **Approved**

Validation was rerun on active branch `bugfix/backend_serverless_deploy_config` after the backend package isolation fix.

## 2. Detailed Results

| ID | Acceptance criteria | Validation | Outcome | Evidence |
| --- | --- | --- | --- | --- |
| QA-01 | AC1 | Inspected `infra/serverless.yml` | Pass | File exists and defines `service: release-confidence-platform`. |
| QA-02 | AC2, AC10 | Inspected backend function definitions and generated output | Pass | Only `coreEngineOrchestrator`, `scheduledExecution`, and `auditFinalization` are configured, with handlers `apps.backend.handlers.orchestrator_handler.handler`, `apps.backend.handlers.scheduled_execution_handler.handler`, and `apps.backend.handlers.audit_finalization_handler.handler`. |
| QA-03 | AC3 | Inspected provider env vars in config and `serverless print` output | Pass | `STAGE`, `RAW_RESULTS_BUCKET`, `METADATA_TABLE`, `SCHEDULER_GROUP_NAME`, and `LOG_LEVEL` are defined for all supported stages. `AWS_REGION` is absent from user-defined Lambda env vars because Lambda reserves and supplies it. |
| QA-04 | AC4 | Inspected IAM statements and generated resources | Pass | CloudWatch Logs, S3 object get/head/put, DynamoDB get/put/update, Secrets Manager get, Scheduler group, and Scheduler invocation role/integration are present and stage-scoped. |
| QA-05 | AC5 | `serverless print --stage dev` | Pass | Rendered dev config successfully with dev resource names and 14-day log retention. |
| QA-06 | AC5 | `serverless print --stage staging` | Pass | Rendered staging config successfully with staging resource names and 30-day log retention. |
| QA-07 | AC5 | `serverless print --stage prod` | Pass | Rendered prod config successfully with prod resource names and 90-day log retention. |
| QA-08 | AC6 | `serverless package --stage dev`, `staging`, `prod` | Pass | All package commands completed with `✔ Service packaged`. |
| QA-09 | AC6, AC8 | Inspected generated backend ZIP for each supported stage | Pass | Required backend handlers and shared modules present; `mock_target_api_entries=0`; `pycache_or_pyc_entries=0`; `zip_entries=82` for dev/staging/prod. |
| QA-10 | AC7 | Inspected `docs/backend/backend_deployment.md` | Pass | Documentation explains config path, event-driven runtime, stages, resources, env vars, validation commands, deploy commands, and scheduler output/operator configuration. |
| QA-11 | AC8 | Inspected mock API Serverless config | Pass | `apps/mock-target-api/serverless.yml` remains a separate `service: mock-target-api` HTTP API config and is not included in backend package. |
| QA-12 | AC9 | Inspected generated functions/resources | Pass | Backend functions render with `events: []`; package state inspection found `api_gateway_resources=[]`. |
| QA-13 | AC10 | Checked handler files and relevant uncommitted diff | Pass | Existing backend handler files are `orchestrator_handler.py`, `scheduled_execution_handler.py`, and `audit_finalization_handler.py`; `git diff --name-status HEAD -- apps/backend/handlers infra/serverless.yml apps/mock-target-api/serverless.yml` produced no handler/mock API changes in the working tree. |

### Automated/regression execution evidence

Command:

```bash
python3.11 -m pytest tests
```

Result:

```text
collected 99 items
tests/api/test_operator_cli_discovery_contract.py ..
tests/api/test_operator_cli_rcp_contract.py ..
tests/api/test_phase2_payload_generation_qa.py ..
tests/integration/test_phase1_orchestrator_integration.py .
tests/integration/test_phase2_orchestrator_payloads.py .
tests/integration/test_phase3_cancellation_finalization.py ...
tests/integration/test_phase3_duplicate_delivery.py ...
tests/integration/test_phase3_scheduled_execution.py ..
tests/integration/test_phase3_scheduling_lifecycle.py ...
tests/security/test_phase1_qa_contracts.py .....
tests/unit/test_foundation_constants.py ....
tests/unit/test_infra_configuration.py ...
tests/unit/test_operator_cli_discovery.py ..............
tests/unit/test_operator_cli_rcp.py .............
tests/unit/test_phase0_structure.py ..
tests/unit/test_phase1_core_engine.py ........
tests/unit/test_phase2_payload_generation.py ..........
tests/unit/test_phase3_event_contracts.py ..
tests/unit/test_phase3_lifecycle_state_machine.py ...
tests/unit/test_phase3_occurrence_claims.py .
tests/unit/test_phase3_safeguards.py ......
tests/unit/test_phase3_schedule_builders.py ....
tests/unit/test_phase3_taxonomy.py ..
tests/unit/test_phase3_token_metadata.py .
tests/unit/test_sample_config_validation.py ..
99 passed in 3.20s
```

### Serverless execution evidence

Commands executed from `infra/`:

```bash
serverless --version
serverless print --stage dev
serverless print --stage staging
serverless print --stage prod
serverless package --stage dev
serverless package --stage staging
serverless package --stage prod
```

Version output:

```text
Framework Core: 3.40.0 (local)
Plugin: 7.2.3
SDK: 4.5.1
```

`serverless print` evidence for supported stages:

```text
dev: STAGE=dev, RAW_RESULTS_BUCKET=release-confidence-platform-dev-raw-results, METADATA_TABLE=release-confidence-platform-dev-metadata, SCHEDULER_GROUP_NAME=rcp-dev-schedules, LOG_LEVEL=INFO, no user-defined AWS_REGION, logRetentionInDays=14
staging: STAGE=staging, RAW_RESULTS_BUCKET=release-confidence-platform-staging-raw-results, METADATA_TABLE=release-confidence-platform-staging-metadata, SCHEDULER_GROUP_NAME=rcp-staging-schedules, LOG_LEVEL=INFO, no user-defined AWS_REGION, logRetentionInDays=30
prod: STAGE=prod, RAW_RESULTS_BUCKET=release-confidence-platform-prod-raw-results, METADATA_TABLE=release-confidence-platform-prod-metadata, SCHEDULER_GROUP_NAME=rcp-prod-schedules, LOG_LEVEL=INFO, no user-defined AWS_REGION, logRetentionInDays=90
functions for all stages: coreEngineOrchestrator, scheduledExecution, auditFinalization
function events for all stages: []
```

Package inspection output after each package command:

```text
stage=dev
state_stage= dev
functions= ['auditFinalization', 'coreEngineOrchestrator', 'scheduledExecution']
handlers= ['apps.backend.handlers.audit_finalization_handler.handler', 'apps.backend.handlers.orchestrator_handler.handler', 'apps.backend.handlers.scheduled_execution_handler.handler']
lambda_resources= ['AuditFinalizationLambdaFunction', 'CoreEngineOrchestratorLambdaFunction', 'ScheduledExecutionLambdaFunction']
api_gateway_resources= []
apps/backend/handlers/orchestrator_handler.py= True
apps/backend/handlers/scheduled_execution_handler.py= True
apps/backend/handlers/audit_finalization_handler.py= True
packages/storage/eventbridge_scheduler_client.py= True
packages/config/stage_config.py= True
mock_target_api_entries= 0
pycache_or_pyc_entries= 0
zip_entries= 82

stage=staging
state_stage= staging
functions= ['auditFinalization', 'coreEngineOrchestrator', 'scheduledExecution']
handlers= ['apps.backend.handlers.audit_finalization_handler.handler', 'apps.backend.handlers.orchestrator_handler.handler', 'apps.backend.handlers.scheduled_execution_handler.handler']
lambda_resources= ['AuditFinalizationLambdaFunction', 'CoreEngineOrchestratorLambdaFunction', 'ScheduledExecutionLambdaFunction']
api_gateway_resources= []
apps/backend/handlers/orchestrator_handler.py= True
apps/backend/handlers/scheduled_execution_handler.py= True
apps/backend/handlers/audit_finalization_handler.py= True
packages/storage/eventbridge_scheduler_client.py= True
packages/config/stage_config.py= True
mock_target_api_entries= 0
pycache_or_pyc_entries= 0
zip_entries= 82

stage=prod
state_stage= prod
functions= ['auditFinalization', 'coreEngineOrchestrator', 'scheduledExecution']
handlers= ['apps.backend.handlers.audit_finalization_handler.handler', 'apps.backend.handlers.orchestrator_handler.handler', 'apps.backend.handlers.scheduled_execution_handler.handler']
lambda_resources= ['AuditFinalizationLambdaFunction', 'CoreEngineOrchestratorLambdaFunction', 'ScheduledExecutionLambdaFunction']
api_gateway_resources= []
apps/backend/handlers/orchestrator_handler.py= True
apps/backend/handlers/scheduled_execution_handler.py= True
apps/backend/handlers/audit_finalization_handler.py= True
packages/storage/eventbridge_scheduler_client.py= True
packages/config/stage_config.py= True
mock_target_api_entries= 0
pycache_or_pyc_entries= 0
zip_entries= 82
```

Package pattern evidence from `infra/serverless.yml`:

```text
package.patterns begins with !../** and explicitly re-includes apps/__init__.py, apps/backend/**, packages/__init__.py, and required shared package directories only.
No broad ../apps/** or ../packages/** include remains.
```

## 3. Failed Tests

None.

The previous blocking defect is resolved: backend package inspection now reports `mock_target_api_entries=0` for dev, staging, and prod packages.

## 4. Failure Classification

No failures to classify.

## 5. Observations

- Serverless emitted Node `DEP0040` `punycode` deprecation warnings. This did not affect print/package execution.
- `git status --short` shows QA artifacts and the bug report are untracked locally: `docs/bugs/backend_serverless_deploy_config_bug_report.md`, `docs/qa/backend_serverless_deploy_config_test_plan.md`, and `docs/qa/backend_serverless_deploy_config_test_report.md`. This is not a functional blocker but should be handled by the owner before merge if those artifacts are intended for version control.
- No flaky behavior observed. The full pytest suite passed in a single run.

## 6. Regression Check

Confirmed unchanged/working behaviors:

- Full automated regression suite passed: 99/99 tests.
- Backend deployment remains event-driven; no API Gateway or HTTP API resources are generated.
- Mock target API remains a separate Serverless service with HTTP API routes and is excluded from backend deployment packages.
- Backend package contains required backend handlers and shared modules only, with no mock target API entries and no Python cache artifacts.
- No backend handler business logic changes were detected in the working tree during this rerun.

## 7. QA Decision

**Approved.**

All acceptance criteria passed with direct Serverless print/package evidence, package isolation evidence for dev/staging/prod, documentation inspection, and full automated regression coverage. No blocking defects or major regressions remain.
