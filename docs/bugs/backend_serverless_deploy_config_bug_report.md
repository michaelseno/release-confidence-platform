# Bug Report

## 1. Summary

Backend Serverless deployment configuration exists at `infra/serverless.yml`, but it is Phase 0/Phase 1-era and incomplete for the currently deployable backend runtime handlers after PR 14. It deploys only `orchestrator_handler`, leaves scheduler and IAM resources as Phase 0 placeholders, uses a DynamoDB key schema that does not match current backend code, and does not configure EventBridge Scheduler targets/roles for the Phase 3 scheduled execution and finalization handlers.

## 2. Investigation Context

- Source of report: user review on active branch `bugfix/backend_serverless_deploy_config` after PR 14 merge.
- Related workflow: backend AWS Lambda deployment via Serverless Framework.
- User-observed gap: only the mock API `serverless.yml` was obvious; backend deploy config was missing or not discoverable/complete.
- Relevant configs:
  - Backend: `infra/serverless.yml`
  - Mock API: `apps/mock-target-api/serverless.yml`

## 3. Observed Symptoms

- `apps/mock-target-api/serverless.yml` is a mock REST/HTTP API deployment config with five `httpApi` routes (`healthFast`, `healthSlow`, `healthFlaky`, `healthInconsistent`, `healthTimeout`). It is not the backend runtime config.
- `infra/serverless.yml` is the backend service config, but it defines only one backend Lambda function:
  - `coreEngineOrchestrator` -> `../apps/backend/handlers/orchestrator_handler.handler` (`infra/serverless.yml:36-40`).
- Current backend runtime handlers also include:
  - `apps/backend/handlers/scheduled_execution_handler.py:147`
  - `apps/backend/handlers/audit_finalization_handler.py:95`
- Scheduler and IAM resource files are placeholders:
  - `infra/resources/scheduler.yml:1-5` says scheduler runtime logic is intentionally not implemented.
  - `infra/resources/iam.yml:1-5` says IAM permissions are intentionally not expanded because no runtime functions are implemented.
- Packaged state confirms only one Lambda function and only default CloudWatch Logs IAM permissions (`infra/.serverless/serverless-state.json:398-410`, `99-160`).

Expected behavior: backend deployment config should deploy all existing backend runtime handlers intended for AWS Lambda, wire EventBridge Scheduler where applicable, and grant least-privilege S3/DynamoDB/Secrets Manager/CloudWatch permissions without adding API Gateway unless a current backend handler requires HTTP exposure.

Actual behavior: backend deployment config is present but incomplete and stale relative to Phase 3 backend code.

## 4. Evidence Collected

### Serverless configs

- `apps/mock-target-api/serverless.yml:1-52` is `service: mock-target-api` and defines HTTP API health endpoints only.
- `infra/serverless.yml:1-46` is `service: release-confidence-platform`; it sets Python 3.11, stage/region, env vars, package patterns, resources, and only `coreEngineOrchestrator`.

### Backend runtime handlers discovered

- `apps/backend/handlers/orchestrator_handler.py:16-25`: Lambda entry point for Phase 1 core engine; reads `RAW_RESULTS_BUCKET` and `METADATA_TABLE`; uses S3, DynamoDB, Secrets Manager.
- `apps/backend/handlers/scheduled_execution_handler.py:147-156`: Lambda entry point for EventBridge scheduled execution; reads `METADATA_TABLE` and `RAW_RESULTS_BUCKET`; uses DynamoDB, S3, Secrets Manager, and invokes `CoreEngineOrchestrator` in-process.
- `apps/backend/handlers/audit_finalization_handler.py:95-98`: Lambda entry point for finalization events; reads `METADATA_TABLE`; uses DynamoDB.

### EventBridge Scheduler requirements

- Phase 3 design requires EventBridge Scheduler for `baseline`, `burst`, `repeated`, and `finalization` schedule types (`docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md:16-18`, `39-44`).
- Runtime flow expects Scheduler to invoke scheduled execution handler (`docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md:110-120`) and finalization handler (`122-128`).
- `packages/audit_scheduling/builders.py:81-95` builds schedule definitions for baseline, burst, repeated, and finalization.
- `packages/audit_scheduling/builders.py:247-259` builds execution events with `event_type: audit_schedule_execution`.
- `packages/audit_scheduling/builders.py:214-223` builds finalization events with `event_type: audit_finalization`.
- `packages/storage/eventbridge_scheduler_client.py:36-41` only includes a Scheduler `Target` if both `target_arn` and `role_arn` are configured. Current `AwsClientFactory.scheduler()` passes only `group_name` (`src/release_confidence_platform/storage/aws_client_factory.py:32-35`), so dynamic schedule creation lacks configured target/role wiring.
- Current `EventBridgeSchedulerClient` has only one `target_arn`, but the repo has two distinct scheduler target handlers (`scheduled_execution_handler` and `audit_finalization_handler`). This creates a deployment/configuration mismatch unless implementation adds schedule-type-aware target mapping or an existing-handler-compatible dispatch approach.

### Required environment variables and AWS permissions from code

- Environment variables used by deployed handlers:
  - `RAW_RESULTS_BUCKET`: `orchestrator_handler.py:17`, `scheduled_execution_handler.py:152`.
  - `METADATA_TABLE`: `orchestrator_handler.py:18-19`, `scheduled_execution_handler.py:148-150`, `audit_finalization_handler.py:96-97`.
  - Existing config also sets `STAGE`, `AWS_REGION`, `LOG_LEVEL` (`infra/serverless.yml:14-19`).
- S3 operations used by backend runtime through `packages/storage/s3_client.py` and `CoreEngineOrchestrator`:
  - `get_object` (`s3_client.py:20-28`, config loading in `orchestrator/service.py:163-170`)
  - `head_object` (`s3_client.py:30-39`, duplicate checks in `orchestrator/service.py:149-152`)
  - `put_object` (`s3_client.py:57-66`, raw results write in `orchestrator/service.py:103`)
- DynamoDB operations used by backend runtime:
  - `get_item`, `put_item`, `update_item` in `packages/storage/dynamodb_client.py:22-58`.
  - `get_item`, conditional `put_item`, and `update_item` in `packages/storage/audit_metadata_client.py:36-204`.
- Secrets Manager operation used by backend runtime:
  - `get_secret_value` in `packages/storage/secrets_client.py:14-22` when resolving endpoint header secret references (`apps/backend/orchestrator/service.py:172-177`).
- CloudWatch Logs:
  - Serverless generated default log permissions in packaged state (`infra/.serverless/serverless-state.json:133-156`), but custom least-privilege IAM resources are currently placeholders.

### Resource/schema mismatch

- Runtime code writes DynamoDB items with keys named `PK` and `SK`:
  - Run metadata: `packages/storage/dynamodb_client.py:19-20`.
  - Audit metadata and occurrence claims: `packages/storage/audit_metadata_client.py:25-34`.
- Current deployed DynamoDB table schema uses attributes `client_id` and `audit_id` as the hash/range keys (`infra/resources/dynamodb.yml:7-16`), which is incompatible with the runtime key shape.

## 5. Execution Path / Failure Trace

1. Operator/backend deployment uses `infra/serverless.yml`.
2. Serverless deploy/package creates only `coreEngineOrchestrator`; `scheduled_execution_handler` and `audit_finalization_handler` are not deployed.
3. Phase 3 scheduling code can build schedule definitions, but current Scheduler client wiring does not provide target Lambda ARN or Scheduler invocation role.
4. Even if the orchestrator Lambda deploys, its DynamoDB reads/writes use `PK`/`SK`, while the deployed table schema expects `client_id`/`audit_id`, causing persistence failures at runtime.
5. Lambda execution role receives only default logs permissions from Serverless unless IAM is expanded; runtime S3, DynamoDB, and Secrets Manager calls will be denied.

## 6. Failure Classification

- Primary classification: Application Bug.
- Contributing classification: Contract Mismatch between backend runtime code/Phase 3 architecture and infrastructure deployment config.
- Severity: Blocker.

Justification: release/deployment of backend runtime is blocked because current config does not deploy all existing runtime handlers, does not wire Scheduler, does not grant required permissions, and provisions an incompatible DynamoDB table schema.

## 7. Root Cause Analysis

### Most Likely Root Cause

The backend Serverless config under `infra/` was not updated after Phase 3/PR 14 introduced scheduled execution and finalization runtime handlers and new DynamoDB key contracts. The infra files still contain Phase 0 placeholders and deploy only the Phase 1 orchestrator.

Immediate failure points:
- Missing Lambda function definitions for `scheduled_execution_handler` and `audit_finalization_handler` in `infra/serverless.yml`.
- Placeholder Scheduler and IAM resources in `infra/resources/scheduler.yml` and `infra/resources/iam.yml`.
- DynamoDB table schema mismatch in `infra/resources/dynamodb.yml`.

Supporting evidence:
- Phase 3 implementation report lists the scheduled execution and finalization handlers as implemented (`docs/backend/phase_3_audit_scheduling_lifecycle_implementation_report.md:13-14`) and notes EventBridge target ARNs/roles were wrapper parameters only, with no live deployment (`lines 68-70`).
- `infra/serverless.yml:36-40` includes only `coreEngineOrchestrator`.
- `infra/resources/iam.yml:1-5` and `infra/resources/scheduler.yml:1-5` are explicit placeholders.

## 8. Confidence Level

High. The missing/incomplete deployment config is directly visible in `infra/serverless.yml` and resource files, and the required runtime handlers/env/IAM needs are directly referenced by existing code.

## 9. Recommended Fix

Likely owner: backend / infrastructure.

Concrete implementation guidance:

1. Treat `infra/serverless.yml` as the backend Serverless config and make it discoverable in release/deploy docs. Do not modify `apps/mock-target-api/serverless.yml` except as a reference.
2. Add backend Lambda function definitions for all current runtime handlers:
   - `apps/backend/handlers/orchestrator_handler.py::handler`
   - `apps/backend/handlers/scheduled_execution_handler.py::handler`
   - `apps/backend/handlers/audit_finalization_handler.py::handler`
3. Do not add API Gateway events unless a current backend handler explicitly requires HTTP exposure; none found during this investigation.
4. Replace Phase 0 placeholder IAM with least-privilege permissions for Lambda execution:
   - CloudWatch Logs for backend function log groups.
   - S3 read/head/write access scoped to the configured raw/config bucket used by runtime (`RAW_RESULTS_BUCKET`; confirm whether config and raw results share the same bucket in deployment).
   - DynamoDB `GetItem`, `PutItem`, `UpdateItem` scoped to the metadata table.
   - Secrets Manager `GetSecretValue` scoped to approved runtime secret ARNs/prefixes.
5. Fix DynamoDB table schema to match runtime code (`PK` hash key, `SK` range key), or update runtime code only if a different approved schema exists. Current evidence supports changing infra, not handler logic.
6. Add EventBridge Scheduler infrastructure:
   - Schedule group matching stage naming.
   - Scheduler invocation role trusted by `scheduler.amazonaws.com` with `lambda:InvokeFunction` only on the scheduled execution and finalization Lambda ARNs.
   - Outputs/env/config values needed by operator scheduling code.
7. Resolve Scheduler target mapping before deploy acceptance:
   - Current client supports only one `target_arn`, while existing runtime has separate execution and finalization handlers. Implement schedule-type-aware target ARN selection or another existing-handler-compatible routing strategy. Do not invent new handlers unless product/architecture approves it.
8. Review handler/package import paths. The packaged state currently preserves handler value `../apps/backend/handlers/orchestrator_handler.handler`; ensure deployed Lambda handler strings and ZIP layout can import `apps.*` and `packages.*` modules reliably. If handler logic/path changes are required solely for packaging/imports, document them in the implementation report.

## 10. Suggested Validation Steps

- From `infra/`, run Serverless package validation for `dev`, `staging`, and `prod`; inspect generated CloudFormation for all three backend Lambdas, Scheduler resources, IAM statements, and correct DynamoDB `PK`/`SK` schema.
- Confirm package artifact contains importable `apps/` and `packages/` modules and handler strings resolve to existing `handler` functions.
- Verify no HTTP/API Gateway resources are generated for backend functions unless explicitly required.
- Validate Scheduler target role trust and `lambda:InvokeFunction` resources are scoped to scheduled execution/finalization functions only.
- Run targeted backend tests covering Phase 1 orchestrator and Phase 3 scheduling/finalization after implementation.
- If possible, perform a non-prod deploy smoke test:
  - Invoke orchestrator Lambda manually with a safe test event.
  - Create a test EventBridge schedule for execution and finalization paths.
  - Confirm DynamoDB metadata writes use `PK`/`SK` and S3 raw result writes succeed.

## 11. Open Questions / Missing Evidence

- Whether deployment should use one bucket for both configs and raw results or separate config/raw buckets. Current backend handlers expose only `RAW_RESULTS_BUCKET`, but operator stage config names `config_bucket`.
- Exact approved Secrets Manager ARN scope/prefix for least-privilege `GetSecretValue`.
- Whether Scheduler target mapping should be solved by enhancing the existing Scheduler client with per-schedule target ARNs or by routing finalization through an existing handler. Current code does not fully define this.
- Whether `../apps/...` handler paths are accepted by the intended Serverless/Lambda packaging workflow; generated CloudFormation retaining `../` is a deployment risk that needs package/import validation.

## 12. Final Investigator Decision

Ready for developer fix.
