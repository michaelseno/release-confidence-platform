# Bug Report

## 1. Summary
During HITL validation, synchronous `rcp audit run` reached the deployed dev orchestrator but failed in the backend with `STORAGE_ERROR: S3 existence check failed`. Repository evidence points to the backend Lambda S3 `HeadObject` existence check, most likely the raw-result duplicate preflight, returning a non-404 `ClientError` that the backend package storage client collapses to a generic storage error.

## 2. Investigation Context
- Source of report: HITL validation.
- Branch context: `feature/profile_driven_config_init` remains the active correction branch.
- Related feature/workflow: Enhanced `rcp config init` default profile system; manual `audit create` / `audit run` against deployed dev resources.
- User command:

```bash
rcp audit run \
  --client-id client_layer_1_validation_client_b5817642 \
  --audit-id audit_20260524_ec3f2d9b \
  --scenario-type repeated_stability \
  --stage dev
```

- Known dev context from HITL:
  - `RCP_AWS_PROFILE=rk-reliability`
  - `RCP_CONFIG_BUCKET=release-confidence-platform-dev-raw-results`
  - `RCP_AUDIT_METADATA_TABLE=release-confidence-platform-dev-metadata`
  - `RCP_AWS_REGION=us-east-1`
  - `RCP_ORCHESTRATOR_FUNCTION_NAME=release-confidence-platform-dev-coreEngineOrchestrator`

## 3. Observed Symptoms
Observed CLI output after redeploy:

```text
FAILED: audit run
stage: dev
client_id: client_layer_1_validation_client_b5817642
audit_id: audit_20260524_ec3f2d9b
summary: orchestrator execution failed
run_id: baadf751-19ac-4923-b502-9d137d7e8d8e
scenario_type: repeated_stability
handler_status: FAILED
error_code: STORAGE_ERROR
failure_type: STORAGE_ERROR
failure_message: S3 existence check failed
next_step: address STORAGE_ERROR, rerun with --output json for structured invocation details, and inspect CloudWatch orchestrator logs for stage dev run_id baadf751-19ac-4923-b502-9d137d7e8d8e
```

Expected behavior: a new manual run should either complete and write raw results/metadata, or fail with a safe actionable storage diagnostic that identifies whether the failure was permission, missing bucket, region mismatch, or another S3 `HeadObject` condition.

Actual behavior: the backend returned only generic `STORAGE_ERROR: S3 existence check failed`, with no AWS error code, operation context, key prefix, or required permission.

## 4. Evidence Collected
Files inspected:
- `apps/backend/orchestrator/service.py`
- `apps/backend/handlers/orchestrator_handler.py`
- `apps/backend/handlers/scheduled_execution_handler.py`
- `packages/storage/s3_client.py`
- `src/release_confidence_platform/storage/s3_client.py`
- `packages/config/loaders.py`
- `packages/core/constants/engine.py`
- `packages/data_generation/data_pools.py`
- `src/release_confidence_platform/core/manual_run_service.py`
- `src/release_confidence_platform/storage/lambda_client.py`
- `infra/serverless.yml`
- `config/stages/dev.json`
- `docs/backend/s3_storage_error_guidance_implementation_report.md`

Key evidence:
- Backend handler uses Lambda environment variables `RAW_RESULTS_BUCKET` and `METADATA_TABLE`, not local CLI `RCP_CONFIG_BUCKET` / `RCP_AUDIT_METADATA_TABLE` (`apps/backend/handlers/orchestrator_handler.py:39-41`). Serverless sets these to `${resourcePrefix}-${stage}-raw-results` and `${resourcePrefix}-${stage}-metadata` (`infra/serverless.yml:16-20`, `63-65`). This matches the known dev bucket/table names, so missing CLI env overrides are not the leading explanation.
- `CoreEngineOrchestrator.run()` builds a raw result key and immediately checks for duplicates before writing STARTED metadata (`apps/backend/orchestrator/service.py:49-55`). The duplicate check calls `self.s3_storage.object_exists(raw_result_key)` first (`service.py:149-152`).
- Raw result key template is `raw-results/{client_id}/{audit_id}/{run_id}/results.json` (`packages/core/constants/engine.py:42`). For this run, the exact raw key is:
  - `raw-results/client_layer_1_validation_client_b5817642/audit_20260524_ec3f2d9b/baadf751-19ac-4923-b502-9d137d7e8d8e/results.json`
- The same raw key is checked again immediately before final raw result write (`packages/storage/s3_client.py:57-59`, called by `service.py:103`).
- Config loading uses `read_json()`, not `object_exists()`, for:
  - `configs/{client_id}/client_config.json`
  - `configs/{client_id}/audits/{audit_id}/audit_config.json`
  - `configs/{client_id}/audits/{audit_id}/endpoints.json`
  (`packages/config/loaders.py:12-37`, `packages/core/constants/engine.py:43-45`). A config load failure would return `CONFIG_LOAD_ERROR: Config object could not be loaded`, not the observed `S3 existence check failed`.
- Backend package storage implementation raises the exact observed message on non-404 `HeadObject` errors: `raise StorageError("S3 existence check failed", "STORAGE_ERROR")` (`packages/storage/s3_client.py:30-37`).
- CLI/source storage diagnostics were improved, but backend package storage was not. `src/release_confidence_platform/storage/s3_client.py:78-87` maps `HeadObject` `ClientError` through `_storage_error_from_s3_client_error()` with sanitized `aws_error_code`, `operation=head_object`, and `key_prefix`. `packages/storage/s3_client.py:30-37` still swallows the AWS error code and always emits generic `STORAGE_ERROR` for non-404 errors.
- Implementation report confirms prior S3 diagnostic changes were made only under `src/release_confidence_platform/storage/s3_client.py` and CLI rendering (`docs/backend/s3_storage_error_guidance_implementation_report.md:6-10`).
- Serverless grants object-level `s3:GetObject`, `s3:HeadObject`, and `s3:PutObject` on `arn:aws:s3:::${rawResultsBucketName}/*` (`infra/serverless.yml:32-38`), but no bucket-level `s3:ListBucket` grant is present. S3 `HeadObject` against a missing key can return `403 Forbidden` instead of `404 Not Found` when the caller lacks `s3:ListBucket`; the backend treats that `403` as a storage failure instead of “object does not exist”.
- A true raw-result key collision would produce `DuplicateRunIdError` / duplicate failure, not `STORAGE_ERROR`, because `object_exists()` would return `True` only if `HeadObject` succeeded (`packages/storage/s3_client.py:30-37`, `apps/backend/orchestrator/service.py:149-161`).

## 5. Execution Path / Failure Trace
Likely path for this run:
1. CLI invokes `release-confidence-platform-dev-coreEngineOrchestrator` synchronously with manual payload including `client_id`, `audit_id`, `scenario_type`, `schedule_type=manual`, and `stage=dev` (`src/release_confidence_platform/core/manual_run_service.py:29-58`).
2. Lambda handler constructs `S3StorageClient(os.environ["RAW_RESULTS_BUCKET"], boto3.client("s3"))` and DynamoDB metadata client (`apps/backend/handlers/orchestrator_handler.py:37-47`).
3. Orchestrator validates the event and generates `run_id=baadf751-19ac-4923-b502-9d137d7e8d8e`.
4. Orchestrator builds the raw result key: `raw-results/client_layer_1_validation_client_b5817642/audit_20260524_ec3f2d9b/baadf751-19ac-4923-b502-9d137d7e8d8e/results.json`.
5. `_fail_if_duplicate()` calls `object_exists(raw_result_key)` before metadata STARTED write.
6. Backend S3 client calls `HeadObject` on the raw-result key. For a new run, the key should not exist.
7. If Lambda role lacks bucket-level `s3:ListBucket`, S3 can return `403 Forbidden` for a missing key rather than `404`. Other non-404 causes include bucket policy/SCP deny, region redirect/mismatch, or wrong bucket.
8. `packages/storage/s3_client.py` converts that non-404 `ClientError` to generic `StorageError("S3 existence check failed", "STORAGE_ERROR")`.
9. Orchestrator catches the `EngineError` and returns a sanitized handler response with `status=FAILED`, which the improved CLI now surfaces.

## 6. Failure Classification
- Primary classification: Environment / Configuration Issue.
- Contributing classification: Application Bug, because backend package storage hides the S3 `ClientError` details and does not map common `HeadObject` permission/config cases to actionable error types.
- Severity: Blocker.

Justification: HITL validation of the core manual audit execution path is blocked. The run fails before raw results are written, and likely before STARTED metadata is written if the failure is the initial duplicate preflight.

## 7. Root Cause Analysis
Confidence label: Most Likely Root Cause.

Immediate failure point:
- `packages/storage/s3_client.py:S3StorageClient.object_exists()` raised `StorageError("S3 existence check failed", "STORAGE_ERROR")` while performing `HeadObject` on an S3 key.

Most likely underlying root cause:
- The Lambda execution role lacks bucket-level `s3:ListBucket` permission for the dev raw/config bucket prefixes used by existence checks. For a new raw result key that does not exist, S3 can return `403 Forbidden` to `HeadObject` when `s3:ListBucket` is not allowed. The backend package storage client treats this as a hard storage failure and masks the underlying AWS error code.

Supporting evidence:
- Observed failure message exactly matches `packages/storage/s3_client.py:37`.
- First audit-run S3 existence check is the raw-result duplicate preflight at `apps/backend/orchestrator/service.py:50-53` and `149-152`.
- Serverless IAM grants only object-level S3 actions on `bucket/*` and does not include bucket-level `s3:ListBucket` (`infra/serverless.yml:32-38`).
- Raw result key is expected to be new because no user-supplied `--run-id` was provided; a true existing key would become duplicate, not `STORAGE_ERROR`.

Less likely explanations from current evidence:
- Lambda missing bucket/table environment variables: would fail in handler setup via `os.environ[...]` before `CoreEngineOrchestrator.run()` and would likely surface as a Lambda handler error / generic orchestration failure, not the exact backend storage message.
- CLI using placeholder local stage config: the CLI successfully invoked the configured deployed Lambda and known env overrides point to the real dev resources; the observed failure occurred inside the Lambda handler.
- Region/bucket mismatch: possible, but less supported because Serverless derives `RAW_RESULTS_BUCKET=release-confidence-platform-dev-raw-results`, matching the known dev bucket. Needs AWS error code to rule out completely.
- Raw result key collision: unlikely; collision path should produce duplicate-run failure, not `S3 existence check failed`.
- Config object load failure: unlikely for this exact message; config reads use `read_json()` and would emit `CONFIG_LOAD_ERROR`.

## 8. Confidence Level
Medium-high.

The exact failing code path is strongly indicated by the unique message in `packages/storage/s3_client.py`. The precise AWS cause cannot be confirmed without CloudWatch logs or direct AWS CLI/STS policy simulation output because backend storage currently suppresses the `ClientError` code. IAM missing `s3:ListBucket` is the best-supported root cause based on the serverless policy and S3 `HeadObject` missing-key semantics.

## 9. Recommended Fix
Likely owner: backend / infrastructure, with a small backend storage diagnostics change.

Concrete fix guidance:
1. Update `infra/serverless.yml` Lambda role S3 policy to include bucket-level `s3:ListBucket` on `arn:aws:s3:::${self:custom.rawResultsBucketName}` with least-privilege prefix conditions for prefixes the backend must check/read/write:
   - `raw-results/*`
   - `configs/*`
   - `data-pools/*` if data-pool payloads are supported in Lambda execution.
2. Keep object-level permissions for:
   - `s3:GetObject` on config/data-pool/raw objects needed for reads and `HeadObject` on existing objects.
   - `s3:PutObject` on `raw-results/*` for audit run results.
   - If the same Lambda/package also writes config objects in a backend path, include `s3:PutObject` on `configs/*`; otherwise do not broaden unnecessarily.
3. Remove `s3:HeadObject` from IAM policy if desired; S3 IAM authorization for `HeadObject` is covered by `s3:GetObject`, while the missing-key 403/404 distinction requires `s3:ListBucket`.
4. Port the safe S3 `ClientError` mapping from `src/release_confidence_platform/storage/s3_client.py` to `packages/storage/s3_client.py`, especially for `object_exists()` and raw-result `put_object`, so Lambda handler responses include safe context such as:
   - `aws_error_code=AccessDenied|Forbidden|NoSuchBucket|PermanentRedirect|...`
   - `operation=head_object`
   - `key_prefix=raw-results|configs|data-pools`
   - required permission guidance (`s3:GetObject`, `s3:ListBucket`, or `s3:PutObject` depending on operation).
5. Add backend tests for `packages/storage/s3_client.py` covering:
   - `HeadObject` 404/NoSuchKey/NotFound returns `False`.
   - `HeadObject` AccessDenied/Forbidden maps to `STORAGE_PERMISSION_ERROR` with `operation=head_object` and `key_prefix`.
   - raw result `put_object` `ClientError` maps to sanitized storage error instead of leaking or escaping unwrapped.

Cautions:
- Do not log full client/audit-specific keys in user-facing messages unless approved; top-level key prefix is enough for safe diagnostics.
- Do not expose endpoint payloads, request headers, secret refs, or AWS credentials.

## 10. Suggested Validation Steps
After infrastructure/storage fix:
1. Deploy dev backend without changing branches.
2. Rerun the same manual command.
3. Expected result: initial raw-result `HeadObject` for the new key returns not found/false rather than generic `STORAGE_ERROR`; the run proceeds to config load and endpoint execution.
4. Confirm CloudWatch contains `run_started` for `run_id=baadf751-19ac-4923-b502-9d137d7e8d8e` or a new generated run id.
5. Confirm DynamoDB metadata item exists with `PK=CLIENT#client_layer_1_validation_client_b5817642`, `SK=AUDIT#audit_20260524_ec3f2d9b#RUN#<run_id>`.
6. Confirm S3 raw results exist at `raw-results/client_layer_1_validation_client_b5817642/audit_20260524_ec3f2d9b/<run_id>/results.json`.
7. Regression-check config reads for the three config keys and any `data-pools/` keys used by endpoints.

Immediate safe user diagnostics:

```bash
export AWS_PROFILE=rk-reliability
export AWS_REGION=us-east-1
export BUCKET=release-confidence-platform-dev-raw-results
export FUNCTION=release-confidence-platform-dev-coreEngineOrchestrator
export RUN_ID=baadf751-19ac-4923-b502-9d137d7e8d8e
export CLIENT_ID=client_layer_1_validation_client_b5817642
export AUDIT_ID=audit_20260524_ec3f2d9b
export RAW_KEY="raw-results/${CLIENT_ID}/${AUDIT_ID}/${RUN_ID}/results.json"

# Verify bucket region from the operator profile.
aws s3api get-bucket-location --bucket "$BUCKET" --profile "$AWS_PROFILE" --region "$AWS_REGION"

# Check whether the raw result exists. For a failed preflight it is expected to be missing.
aws s3api head-object --bucket "$BUCKET" --key "$RAW_KEY" --profile "$AWS_PROFILE" --region "$AWS_REGION"

# Check required config artifacts are readable by the operator profile.
aws s3api head-object --bucket "$BUCKET" --key "configs/${CLIENT_ID}/client_config.json" --profile "$AWS_PROFILE" --region "$AWS_REGION"
aws s3api head-object --bucket "$BUCKET" --key "configs/${CLIENT_ID}/audits/${AUDIT_ID}/audit_config.json" --profile "$AWS_PROFILE" --region "$AWS_REGION"
aws s3api head-object --bucket "$BUCKET" --key "configs/${CLIENT_ID}/audits/${AUDIT_ID}/endpoints.json" --profile "$AWS_PROFILE" --region "$AWS_REGION"

# Check ListBucket behavior for the missing/new raw-result prefix.
aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "raw-results/${CLIENT_ID}/${AUDIT_ID}/${RUN_ID}/" --max-items 1 --profile "$AWS_PROFILE" --region "$AWS_REGION"

# Inspect Lambda environment bucket/table values without printing secrets.
aws lambda get-function-configuration --function-name "$FUNCTION" --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --query '{FunctionName:FunctionName,Runtime:Runtime,Environment:Environment.Variables,Role:Role}'

# Filter CloudWatch logs for the generated run_id.
aws logs filter-log-events --log-group-name "/aws/lambda/${FUNCTION}" --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --filter-pattern '"baadf751-19ac-4923-b502-9d137d7e8d8e"' \
  --query 'events[].{timestamp:timestamp,message:message}'

# Also filter for S3/storage failure markers if the run_id was not logged before failure.
aws logs filter-log-events --log-group-name "/aws/lambda/${FUNCTION}" --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --filter-pattern '"S3 existence check failed"' \
  --query 'events[].{timestamp:timestamp,message:message}'
```

If the Lambda execution role ARN is returned by `get-function-configuration`, use IAM simulation to test the role policy directly. Replace `<role-arn>` with the returned role ARN:

```bash
export ROLE_ARN='<role-arn>'
aws iam simulate-principal-policy --policy-source-arn "$ROLE_ARN" --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --action-names s3:GetObject s3:PutObject \
  --resource-arns "arn:aws:s3:::${BUCKET}/${RAW_KEY}"

aws iam simulate-principal-policy --policy-source-arn "$ROLE_ARN" --profile "$AWS_PROFILE" --region "$AWS_REGION" \
  --action-names s3:ListBucket \
  --resource-arns "arn:aws:s3:::${BUCKET}" \
  --context-entries ContextKeyName=s3:prefix,ContextKeyType=string,ContextKeyValues="raw-results/${CLIENT_ID}/${AUDIT_ID}/${RUN_ID}/results.json"
```

## 11. Open Questions / Missing Evidence
- Need the CloudWatch log excerpt for `run_id=baadf751-19ac-4923-b502-9d137d7e8d8e` to confirm whether the failure occurred at the initial duplicate preflight or the final raw-result write preflight.
- Need the actual AWS `ClientError` code from Lambda runtime (`AccessDenied`, `Forbidden`, `NoSuchBucket`, region redirect, etc.). Current backend code suppresses it.
- Need the deployed Lambda execution role policy or IAM simulation result to confirm `s3:ListBucket` is denied.
- Need confirmation whether endpoints use `payload_strategy=data_pool`, which would add `data-pools/<client_id>/<pool_name>.json` read requirements.

## 12. Final Investigator Decision
Ready for developer fix.

Primary action should be a least-privilege Lambda S3 IAM update for missing-key existence checks plus porting S3 diagnostic mapping from CLI storage to backend package storage. More user info is useful to confirm the exact AWS error code but is not required to begin the targeted fix because repository evidence already identifies a concrete policy gap and diagnostic defect.
