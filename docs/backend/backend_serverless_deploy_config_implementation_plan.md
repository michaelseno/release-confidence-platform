# Implementation Plan

## 1. Feature Overview
Fix the backend Serverless Framework deployment configuration so the event-driven backend runtime can be packaged and deployed for `dev`, `staging`, and `prod`.

## 2. Technical Scope
Update the existing backend deployment configuration under `infra/` to deploy the orchestrator, scheduled execution, and audit finalization Lambda handlers; define required runtime environment variables; add least-privilege AWS access for runtime storage and secret reads; add EventBridge Scheduler group and invocation role resources; align the deployed DynamoDB table schema with runtime `PK`/`SK` access patterns; scope backend deployment packaging to backend runtime code/shared Python packages only; and document backend deployment validation/deploy steps.

## 3. Source Inputs
- `docs/bugs/backend_serverless_deploy_config_bug_report.md`
- `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- QA rejection for backend package contamination by `apps/mock-target-api/**`
- Existing backend handlers under `apps/backend/handlers/`
- Existing storage and scheduling clients under `packages/` and `src/release_confidence_platform/`
- Existing Serverless config under `infra/serverless.yml`

## 4. API Contracts Affected
No API contract changes. The backend remains event-driven and no API Gateway or HTTP routes will be added.

## 5. Data Models / Storage Affected
- `infra/resources/dynamodb.yml` table schema will be changed from stale `client_id`/`audit_id` keys to runtime-compatible `PK` hash key and `SK` range key.
- `infra/resources/s3.yml` remains the raw results/config bucket resource, with outputs updated for deployment clarity.

## 6. Files Expected to Change
- `infra/serverless.yml`
- `infra/resources/dynamodb.yml`
- `infra/resources/iam.yml`
- `infra/resources/scheduler.yml`
- `infra/resources/s3.yml`
- `packages/config/stage_config.py`
- `src/release_confidence_platform/config/stage_config.py`
- `packages/storage/aws_client_factory.py`
- `src/release_confidence_platform/storage/aws_client_factory.py`
- `packages/storage/eventbridge_scheduler_client.py`
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py`
- `config/stages/*.json`
- Targeted tests for stage config and scheduler target mapping, if needed
- `docs/backend/backend_deployment.md`
- `docs/backend/backend_serverless_deploy_config_implementation_report.md`

## 7. Security / Authorization Considerations
- No public API exposure will be added.
- Lambda IAM permissions will be scoped to stage-specific S3 bucket, DynamoDB metadata table, and stage-prefixed Secrets Manager secrets.
- Scheduler invocation role will trust only `scheduler.amazonaws.com` and allow `lambda:InvokeFunction` only on scheduled execution and audit finalization Lambdas.
- Scheduler target payloads continue to be sanitized before being sent to AWS.
- Backend deployment packages must not include mock target API code, mock Serverless artifacts, or mock Node dependencies.

## 8. Dependencies / Constraints
- No new dependencies are planned.
- Serverless Framework must be available locally to run `serverless print`/`package`; if unavailable, validation will be documented.
- The mock API deployment file at `apps/mock-target-api/serverless.yml` must remain untouched.

## 9. Assumptions
- The single configured raw results bucket also stores runtime config objects read by the existing orchestrator because the current runtime exposes only `RAW_RESULTS_BUCKET`.
- Stage secret names are expected under `release-confidence-platform/<stage>/...` unless operators override the IAM pattern in Serverless custom config before deployment.
- Updating scheduler clients to select the target Lambda by existing schedule definition type is a non-business deployment wiring change required to support separate scheduled execution and finalization handlers.

## 10. Validation Plan
- Run targeted Python tests for operator stage config and scheduler client behavior.
- Run `serverless print` or `serverless package` from `infra/` for `dev`, `staging`, and `prod` if Serverless Framework is installed.
- Inspect generated Serverless/CloudFormation output for three Lambda functions, no API Gateway events, DynamoDB `PK`/`SK`, Scheduler group/role, and IAM statements.
- Inspect generated backend ZIP package to confirm backend handlers are included and `apps/mock-target-api/**` is excluded.
