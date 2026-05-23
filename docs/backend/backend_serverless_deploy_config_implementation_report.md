# Implementation Report

## 1. Summary of Changes
Updated the backend Serverless deployment configuration to deploy all current event-driven backend runtime handlers, define required environment variables, provision stage-aware storage and scheduler resources, and wire scheduler target selection for separate execution and finalization Lambdas.

## 2. Files Modified
- `infra/serverless.yml` — added all three backend Lambda functions, stage-aware env vars/log retention, IAM statements, and corrected handler module paths.
- `infra/resources/dynamodb.yml` — aligned table key schema to runtime `PK`/`SK` keys.
- `infra/resources/s3.yml` — clarified runtime bucket outputs.
- `infra/resources/iam.yml` — replaced stale placeholder output with runtime IAM scope documentation output.
- `infra/resources/scheduler.yml` — added Scheduler group, Scheduler invocation role, and target/role outputs.
- `packages/config/stage_config.py`, `src/release_confidence_platform/config/stage_config.py` — added required scheduler target and role config fields plus environment overrides.
- `packages/storage/aws_client_factory.py`, `src/release_confidence_platform/storage/aws_client_factory.py` — pass schedule-type target ARN mapping and Scheduler role ARN to Scheduler clients.
- `packages/storage/eventbridge_scheduler_client.py`, `src/release_confidence_platform/storage/eventbridge_scheduler_client.py` — select Scheduler target ARN by existing schedule definition type.
- `config/stages/dev.json`, `config/stages/staging.json`, `config/stages/prod.json` — added scheduler target/role config fields with placeholders to document required stage config shape.
- `tests/unit/test_operator_cli_rcp.py`, `tests/api/test_operator_cli_rcp_contract.py` — updated stage config fixtures and added scheduler target-selection coverage.
- `docs/backend/backend_deployment.md` — documented validation, deployment, outputs, and scheduler operator configuration.
- `docs/backend/backend_serverless_deploy_config_implementation_plan.md` — recorded implementation plan.

## 3. API Contract Implementation
No API contract changes. No API Gateway or HTTP events were added. Backend deployment remains Lambda/event-driven only.

## 4. Data / Persistence Implementation
The deployed metadata table now uses the runtime-compatible DynamoDB key schema:

- hash key: `PK`
- range key: `SK`

The stage-specific S3 bucket remains the configured `RAW_RESULTS_BUCKET`; it is also documented as the runtime config bucket because existing runtime handlers expose only this bucket variable.

## 5. Key Logic Implemented
- Serverless now deploys:
  - `coreEngineOrchestrator`
  - `scheduledExecution`
  - `auditFinalization`
- Scheduler integration now exposes a schedule group and invocation role.
- Dynamic schedule creation can select the scheduled execution Lambda for `baseline`, `burst`, and `repeated` definitions, and the finalization Lambda for `finalization` definitions.
- Handler logic was not changed. Only deployment config and scheduler client wiring/configuration were updated.

## 6. Security / Authorization Implemented
- Lambda role permissions are scoped to stage-specific CloudWatch Logs, S3 object access for the runtime bucket, the deployed metadata table ARN, and stage-prefixed Secrets Manager secrets.
- Scheduler invocation role trusts only `scheduler.amazonaws.com`.
- Scheduler invocation role permits `lambda:InvokeFunction` only on scheduled execution and audit finalization Lambda ARNs.
- No public HTTP exposure was added.

## 7. Error Handling Implemented
No handler error behavior was changed. Scheduler client behavior remains backward-compatible: if no target ARN/role is configured, it omits the target as before; when configured, it selects the target by schedule type.

## 8. Observability / Logging
Serverless log retention is now stage-aware: 14 days for `dev`, 30 days for `staging`, and 90 days for `prod`. Existing handler structured logging remains unchanged.

## 9. Assumptions Made
- The existing `RAW_RESULTS_BUCKET` is also used for runtime config objects because current handlers do not expose a separate config bucket environment variable.
- Stage secrets are expected under `release-confidence-platform/<stage>/...` for IAM scoping unless deployment operators adjust the Serverless custom value before deploy.
- Schedule-type target mapping is deployment wiring, not product behavior, because schedule definitions already carry the approved schedule type and target-handler metadata.

## 10. Validation Performed
- `python -m pytest tests/unit/test_operator_cli_rcp.py tests/api/test_operator_cli_rcp_contract.py` — failed locally because `python` is not installed on PATH.
- `python3 -m pytest tests/unit/test_operator_cli_rcp.py tests/api/test_operator_cli_rcp_contract.py` — failed locally because `pytest` is not installed in the active Python environment.
- `serverless --version` from `infra/` — passed; local Serverless Framework 3.40.0 is available.
- `serverless print --stage dev` from `infra/` — passed and showed all three Lambda functions, no events/API Gateway, runtime env vars, `PK`/`SK` DynamoDB schema, Scheduler resources, and IAM statements.
- `serverless print --stage staging` from `infra/` — passed with stage-specific names/env.
- `serverless print --stage prod` from `infra/` — passed with stage-specific names/env.
- `serverless package --stage dev` from `infra/` — passed.
- Packaged artifact inspection confirmed the ZIP includes all three handler modules plus `packages/storage/eventbridge_scheduler_client.py`, and Serverless state contains `auditFinalization`, `coreEngineOrchestrator`, and `scheduledExecution`.
- `python3 -m py_compile ...` for changed Python modules and tests — passed.

## 11. Known Limitations / Follow-Ups
- Local pytest execution could not run because pytest is not installed in the active environment.
- Stage config JSON files contain placeholder AWS account IDs for scheduler outputs; operators must replace them with deployed stack outputs or use the documented `RCP_*` environment overrides.
- Secrets Manager scope uses the stage-prefixed naming convention documented above; if production secrets use a different prefix, deployment config must be adjusted before deploy.

## 12. Commit Status
Implementation commit created: `657716b` (`fix(backend): update serverless deploy config`).
