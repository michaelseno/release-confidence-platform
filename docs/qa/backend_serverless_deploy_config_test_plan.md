# Test Plan

## 1. Feature Overview

Validate the backend Serverless deployment configuration fix on branch `bugfix/backend_serverless_deploy_config` for bug report `docs/bugs/backend_serverless_deploy_config_bug_report.md`.

The backend deployment config is expected at `infra/serverless.yml`. The mock target API deployment config is expected at `apps/mock-target-api/serverless.yml` and must remain independent/unaffected.

## 2. Acceptance Criteria Mapping

| AC | Requirement | Validation approach |
| --- | --- | --- |
| 1 | Backend `serverless.yml` exists | File inspection: `infra/serverless.yml` |
| 2 | Deployable backend handlers configured | Inspect functions and generated Serverless output for orchestrator, scheduled execution, audit finalization handlers |
| 3 | Required environment variables defined without Lambda-reserved keys | Inspect `provider.environment` and generated Lambda environment variables |
| 4 | Required IAM permissions included, least privilege where practical | Inspect Serverless IAM statements and generated CloudFormation resources |
| 5 | Stage support works for `dev`, `staging`, `prod` | Run `serverless print --stage <stage>` and `serverless package --stage <stage>` |
| 6 | Deployment package can be validated | Run Serverless packaging and inspect `.serverless/release-confidence-platform.zip` |
| 7 | Documentation explains backend deployment | Inspect `docs/backend/backend_deployment.md` and implementation report |
| 8 | Mock API deployment remains unaffected | Inspect mock API Serverless config and backend package for accidental mock coupling |
| 9 | No API Gateway unless needed | Inspect backend functions/events and generated CloudFormation for API Gateway/HttpApi resources |
| 10 | No invented handlers or handler business logic changes unless called out | Compare branch changed files and handler definitions |

## 3. Test Scenarios

1. **Configuration presence and artifact traceability**
   - Purpose: Confirm required bug, implementation, deployment, and config artifacts exist.
   - Input: `docs/bugs/backend_serverless_deploy_config_bug_report.md`, `docs/backend/backend_deployment.md`, `docs/backend/backend_serverless_deploy_config_implementation_report.md`, `infra/serverless.yml`.
   - Expected output: All files exist and contain relevant deployment/fix details.
   - Validation logic: File inspection.

2. **Backend handler coverage**
   - Purpose: Confirm all deployable handlers are configured exactly once and no extra backend HTTP exposure exists.
   - Input: `infra/serverless.yml`, `serverless print` output, packaged Serverless state.
   - Expected output: `coreEngineOrchestrator`, `scheduledExecution`, and `auditFinalization` point to existing backend handler functions and have no HTTP/API Gateway events.
   - Validation logic: Static inspection and generated config inspection.

3. **Environment, storage, IAM, and Scheduler resources**
    - Purpose: Confirm runtime dependencies are configured.
    - Input: `infra/serverless.yml`, `infra/resources/*.yml`, generated CloudFormation.
    - Expected output: Serverless-defined Lambda env vars include `STAGE`, `RAW_RESULTS_BUCKET`, `METADATA_TABLE`, `SCHEDULER_GROUP_NAME`, and `LOG_LEVEL`; Lambda-reserved keys such as `AWS_REGION` are absent from user-defined env vars; S3/DynamoDB/Secrets Manager/Logs IAM; DynamoDB `PK`/`SK`; Scheduler group and invocation role.
    - Validation logic: Static inspection and Serverless generated output.

4. **Stage validation and packaging**
   - Purpose: Confirm dev/staging/prod generation succeeds.
   - Input: Serverless Framework CLI.
   - Expected output: `serverless print` and `serverless package` succeed for all supported stages.
   - Validation logic: Execute commands and capture output.

5. **Package composition and mock isolation**
   - Purpose: Confirm backend package contains expected backend code and avoids accidental mock API coupling.
   - Input: `.serverless/release-confidence-platform.zip` generated from `infra`.
   - Expected output: Expected backend handler modules present; mock API files absent from backend deployment artifact.
   - Validation logic: Python `zipfile` inspection.

6. **Regression tests**
   - Purpose: Confirm backend/operator scheduler behavior still passes targeted tests.
   - Input: Existing pytest suites.
   - Expected output: Relevant tests pass without regression.
   - Validation logic: Execute targeted pytest command with Python 3.11.

## 4. Edge Cases

- Stage-specific names/env/log retention differ correctly for `dev`, `staging`, and `prod`.
- No generated API Gateway/HTTP API resources for event-driven backend Lambdas.
- Scheduler invocation role only invokes scheduled execution and finalization Lambdas.
- Backend package does not include mock API `.serverless`, mock handlers, or mock `node_modules` content.
- Handler business logic files are not changed by this infrastructure fix.

## 5. Test Types Covered

- Functional: backend deployment config, handlers, env vars, docs.
- Negative: unsupported stage check attempted.
- Edge: stage-specific generation and package composition.
- Integration: generated Serverless/CloudFormation output inspection.
- Regression: targeted backend/operator pytest suites.

## 6. Coverage Justification

Coverage directly maps each acceptance criterion to static inspection, Serverless generated output, packaging validation, or automated regression execution. Package composition inspection is included because the fix must not accidentally couple backend deployment to the mock target API.
