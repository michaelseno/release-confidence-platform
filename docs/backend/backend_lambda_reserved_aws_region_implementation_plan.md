# Implementation Plan

## 1. Feature Overview
Fix the backend Serverless deployment blocker caused by configuring Lambda-reserved `AWS_REGION` as a user-defined environment variable.

## 2. Technical Scope
Remove `AWS_REGION` from backend Lambda environment configuration, preserve existing runtime behavior by relying on Lambda-provided region context, preserve operator-side `RCP_AWS_REGION`, and add a regression check for reserved Lambda environment keys.

## 3. Source Inputs
- `docs/bugs/backend_lambda_reserved_aws_region_bug_report.md`
- Existing `infra/serverless.yml`
- Existing backend deployment and QA docs
- Existing `tests/unit/test_infra_configuration.py`

## 4. API Contracts Affected
No API contract changes.

## 5. Data Models / Storage Affected
No data model or storage changes.

## 6. Files Expected to Change
- `infra/serverless.yml`
- `tests/unit/test_infra_configuration.py`
- `docs/backend/backend_deployment.md`
- `docs/backend/backend_lambda_reserved_aws_region_implementation_plan.md`
- `docs/backend/backend_lambda_reserved_aws_region_implementation_report.md`
- Relevant QA artifacts that referenced Serverless-defined `AWS_REGION`

## 7. Security / Authorization Considerations
No authorization behavior changes. The fix removes a disallowed user-defined Lambda env var and avoids hardcoding or logging secrets. Operator-side `RCP_AWS_REGION` remains untouched because it is not a Lambda runtime env var.

## 8. Dependencies / Constraints
No new dependencies. Serverless Framework local validation is expected to run from `infra/`. Mock API deployment config must remain unchanged.

## 9. Assumptions
- Backend Lambda handlers do not require a user-defined region variable because AWS Lambda supplies `AWS_REGION` at runtime and boto3 can use the runtime region provider chain.
- Static reserved-key regression coverage is sufficient for local unit validation; generated Serverless print/package output will also be inspected.

## 10. Validation Plan
- `python3 -m pytest tests/unit/test_infra_configuration.py`
- `serverless print --stage dev`, `staging`, and `prod` from `infra/`
- `serverless package --stage dev`, `staging`, and `prod` from `infra/`
- Inspect generated Serverless config/CloudFormation for `coreEngineOrchestrator`, `scheduledExecution`, and `auditFinalization` to confirm `AWS_REGION` is absent from user-defined Lambda env vars.
