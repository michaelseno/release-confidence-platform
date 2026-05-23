# Backend Deployment

The backend Serverless Framework deployment lives at `infra/serverless.yml`. The mock target API deployment at `apps/mock-target-api/serverless.yml` is separate and is not used for backend runtime deployment.

## Runtime Model

The backend is event-driven. The Serverless config deploys Lambda handlers only and does not create API Gateway routes.

Deployed handlers:

- `apps.backend.handlers.orchestrator_handler.handler`
- `apps.backend.handlers.scheduled_execution_handler.handler`
- `apps.backend.handlers.audit_finalization_handler.handler`

## Stages

Supported stages are:

- `dev`
- `staging`
- `prod`

The stage guard plugin rejects other stage names.

## Deployed Resources

For each stage, the backend deployment provisions:

- raw results/config S3 bucket: `release-confidence-platform-<stage>-raw-results`
- metadata DynamoDB table: `release-confidence-platform-<stage>-metadata` with keys `PK` and `SK`
- EventBridge Scheduler group: `rcp-<stage>-schedules`
- Scheduler invocation IAM role trusted by `scheduler.amazonaws.com`
- three backend Lambda functions

## Required Runtime Environment Variables

Serverless defines these Lambda environment variables:

- `STAGE`
- `RAW_RESULTS_BUCKET`
- `METADATA_TABLE`
- `SCHEDULER_GROUP_NAME`
- `LOG_LEVEL`

`AWS_REGION` is intentionally not configured in Serverless because it is a reserved Lambda-provided environment variable. Runtime code should rely on the Lambda-provided value if region discovery is needed.

## Scheduler Operator Configuration

Dynamic schedule creation requires the Scheduler target ARNs and role ARN from the deployed stack outputs:

- `ScheduledExecutionTargetArn`
- `AuditFinalizationTargetArn`
- `SchedulerInvocationRoleArn`
- `SchedulerGroupName`

Populate the corresponding operator stage config values or environment overrides:

- `RCP_SCHEDULER_EXECUTION_TARGET_ARN`
- `RCP_SCHEDULER_FINALIZATION_TARGET_ARN`
- `RCP_SCHEDULER_ROLE_ARN`
- `RCP_SCHEDULER_GROUP_NAME`

Baseline, burst, and repeated schedules target the scheduled execution Lambda. Finalization schedules target the audit finalization Lambda.

## Validate Configuration

From the repository root:

```bash
python -m pytest tests/unit/test_operator_cli_rcp.py tests/api/test_operator_cli_rcp_contract.py
```

If Serverless Framework is installed, validate generated config/package from `infra/`:

```bash
serverless print --stage dev
serverless print --stage staging
serverless print --stage prod
serverless package --stage dev
```

Confirm generated CloudFormation contains three Lambda functions, no API Gateway resources, DynamoDB `PK`/`SK` keys, Scheduler group/role resources, and scoped S3/DynamoDB/Secrets Manager IAM statements.

## Deploy

From `infra/`:

```bash
serverless deploy --stage dev
serverless deploy --stage staging
serverless deploy --stage prod
```

Use `--region` if deploying outside the default `us-east-1` region.

After deployment, copy stack outputs into the operator stage config or provide them via the `RCP_*` environment overrides before creating schedules.
