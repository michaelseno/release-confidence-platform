# Bug Report

## 1. Summary

During HITL validation on `feature/profile_driven_config_init`, `rcp audit create --stage dev` still fails at the S3 config upload step with `STORAGE_CONFIG_ERROR` / `aws_error_code=NoSuchBucket` even after the user verified the real deployed dev S3 bucket and DynamoDB metadata table with AWS CLI.

The code reads the expected env var names and passes them into the S3/DynamoDB clients when they are present in the Python process environment. Given the user could reference `$RCP_CONFIG_BUCKET` in shell commands but `rcp audit create` appears to write to a nonexistent bucket, the most likely cause is that the `RCP_*` values used for AWS CLI verification are not exported into the process environment that launches `rcp`, so `StageConfigLoader` falls back to placeholder values from `config/stages/dev.json`.

## 2. Investigation Context

- Source of report: HITL manual validation.
- Branch context: current active HITL correction branch is `feature/profile_driven_config_init`; no new branch should be created.
- Related workflow: Enhanced `rcp config init` Default Profile System -> generated local config bundle -> non-dry-run `rcp audit create --stage dev`.
- Confirmed deployed dev outputs supplied by user:
  - `RawResultsBucketName`: `release-confidence-platform-dev-raw-results`
  - `MetadataTableName`: `release-confidence-platform-dev-metadata`
  - region: `us-east-1`
  - AWS profile known to work with AWS CLI: `rk-reliability`
- User verified AWS resources outside the CLI:
  - `aws s3api head-bucket --bucket "$RCP_CONFIG_BUCKET" --region us-east-1 --profile "$RCP_AWS_PROFILE"` returned `BucketRegion us-east-1`.
  - `aws dynamodb describe-table --table-name "$RCP_AUDIT_METADATA_TABLE" --region us-east-1 --profile "$RCP_AWS_PROFILE" --query 'Table.TableStatus'` returned `ACTIVE`.
- Reported command:

```bash
rcp audit create \
  --client-config .local-configs/client_layer_1_validation_client_b5817642/client_config.json \
  --audit-config .local-configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/audit_config.json \
  --endpoints-config .local-configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/endpoints.json \
  --stage dev
```

## 3. Observed Symptoms

Observed output:

```text
ERROR: audit create failed
stage: dev
code: STORAGE_CONFIG_ERROR
message: S3 config bucket not found for stage (aws_error_code=NoSuchBucket; operation=put_object; key_prefix=configs)
next_step: check config/stages/dev.json config_bucket or set RCP_CONFIG_BUCKET=<real-dev-bucket>; confirm the bucket exists in the configured region and the selected AWS profile has s3:PutObject and s3:HeadObject permissions for the configs/<client_id>/* prefix
```

Expected behavior:

- With `RCP_CONFIG_BUCKET=release-confidence-platform-dev-raw-results`, `RCP_AUDIT_METADATA_TABLE=release-confidence-platform-dev-metadata`, `RCP_AWS_PROFILE=rk-reliability`, and region `us-east-1` available to the `rcp` process, `audit create` should write config objects under `configs/<client_id>/...` and create DRAFT metadata.
- If the CLI is not using those effective values, it should expose safe diagnostic information showing the resolved stage resources before mutation or in failure output.

Actual behavior:

- S3 `put_object` receives a bucket that S3 reports as nonexistent (`NoSuchBucket`).
- The real bucket is proven to exist in `us-east-1` for the supplied AWS CLI profile, so the failing `rcp` process is almost certainly not using that same effective bucket/profile/region tuple.

## 4. Evidence Collected

Files inspected:

- `src/release_confidence_platform/config/stage_config.py`
- `src/release_confidence_platform/operator_cli/services.py`
- `src/release_confidence_platform/storage/aws_client_factory.py`
- `src/release_confidence_platform/storage/s3_client.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `src/release_confidence_platform/core/audit_creation_service.py`
- `src/release_confidence_platform/operator_cli/main.py`
- `config/stages/dev.json`
- `pyproject.toml`
- legacy duplicate `packages/config/stage_config.py` and `packages/storage/aws_client_factory.py`

Key evidence:

- `StageConfigLoader` supports exactly these environment override names: `RCP_AWS_REGION`, `RCP_AWS_PROFILE`, `RCP_CONFIG_BUCKET`, and `RCP_AUDIT_METADATA_TABLE`: `src/release_confidence_platform/config/stage_config.py:26-37`.
- Overrides are read from `os.environ` only when `env` is not explicitly passed: `src/release_confidence_platform/config/stage_config.py:70-91`. Shell variables that are not exported are not visible here.
- The repo `dev` stage config contains placeholders:
  - `aws_profile`: `rcp-dev`
  - `config_bucket`: `rcp-dev-config-placeholder`
  - `audit_metadata_table`: `rcp-dev-audit-metadata-placeholder`
  Evidence: `config/stages/dev.json:2-5`.
- `audit create` loads stage config before AWS setup and passes the loaded object through the create path: `src/release_confidence_platform/operator_cli/services.py:152-168`.
- `AwsClientFactory` constructs `boto3.Session(profile_name=stage_config.aws_profile, region_name=stage_config.region)`: `src/release_confidence_platform/storage/aws_client_factory.py:20-24`.
- The S3 storage client is instantiated with `stage_config.config_bucket`: `src/release_confidence_platform/storage/aws_client_factory.py:28-33`.
- DynamoDB repository is instantiated with `stage_config.audit_metadata_table`: `src/release_confidence_platform/storage/aws_client_factory.py:35-40`.
- The S3 write error now comes from `S3StorageClient.write_json()` mapping a botocore `ClientError` with AWS code `NoSuchBucket` to `STORAGE_CONFIG_ERROR`: `src/release_confidence_platform/storage/s3_client.py:91-104` and `:136-145`.
- `audit create` writes config keys under `configs/{client_id}/...`: `src/release_confidence_platform/core/audit_creation_service.py:19-24` and `:94-103`.
- CLI renderer has storage-specific next-step guidance, but it does not print the resolved bucket/profile/region: `src/release_confidence_platform/operator_cli/result.py:277-293`.
- Console entry point points to the `src/release_confidence_platform` CLI, not the legacy `packages` tree: `pyproject.toml:15-16`.
- The observed output includes the newly implemented `STORAGE_CONFIG_ERROR` and `aws_error_code=NoSuchBucket` guidance, proving the user is running a CLI version that includes the recent S3 guidance change. That makes a completely stale pre-fix CLI unlikely.

## 5. Execution Path / Failure Trace

Likely path for the reported command:

1. `rcp audit create` dispatches to `services.create_command()`.
2. `StageConfigLoader().load("dev")` reads `config/stages/dev.json` and applies only env values present in `os.environ`.
3. Local config validation succeeds, because the command reaches AWS storage writes.
4. `AwsClientFactory(stage_config)` creates a boto3 session from the resolved `aws_profile` and `region`.
5. `factory.s3_storage()` creates `S3StorageClient(stage_config.config_bucket, s3_client)`.
6. `AuditCreationService.create_from_files()` computes `configs/<client_id>/...` keys and calls `write_json()`.
7. `S3StorageClient.write_json()` calls `put_object(Bucket=<resolved config_bucket>, Key=configs/...)`.
8. AWS returns `NoSuchBucket`; the CLI renders `STORAGE_CONFIG_ERROR`.

Because the user independently verified `release-confidence-platform-dev-raw-results` exists in `us-east-1` with `rk-reliability`, the failure trace implies the resolved `config_bucket` in step 5 is probably not `release-confidence-platform-dev-raw-results`.

## 6. Failure Classification

- Primary classification: Environment / Configuration Issue.
- Contributing classification: Application Bug / insufficient safe diagnostic visibility for effective stage resource resolution.
- Severity: Blocker for current HITL validation; Medium product severity.

Severity justification: The failure blocks HITL completion of non-dry-run `audit create`. Product behavior is recoverable through environment correction, but the CLI does not currently reveal enough effective resource context for users to confirm whether the command used their intended overrides.

## 7. Root Cause Analysis

Confidence label: Most Likely Root Cause

Immediate failure point:

- `S3StorageClient.write_json()` receives a botocore `ClientError` with `Error.Code == NoSuchBucket` during `put_object` and raises `STORAGE_CONFIG_ERROR`.

Most likely underlying root cause:

- The `RCP_CONFIG_BUCKET` override is not present in the `rcp` process environment, so `StageConfigLoader` uses `config/stages/dev.json` placeholder `rcp-dev-config-placeholder`. That placeholder bucket does not exist, causing `NoSuchBucket`.

Supporting evidence:

- Code reads the correct env var names from `os.environ`: `src/release_confidence_platform/config/stage_config.py:26-37`, `:70-91`.
- The fallback bucket is a placeholder: `config/stages/dev.json:4`.
- The user's AWS CLI `head-bucket` verification proves the intended bucket exists, but shell expansion of `$RCP_CONFIG_BUCKET` in an `aws ... --bucket "$RCP_CONFIG_BUCKET"` command does not prove the variable is exported to child processes. Non-exported shell variables are visible to the current shell for expansion but invisible to Python `os.environ`.
- The observed `NoSuchBucket` is more consistent with writing to `rcp-dev-config-placeholder` than with writing to `release-confidence-platform-dev-raw-results`, which was just verified by `head-bucket`.

Less likely alternatives:

- Wrong env var names expected by code: unlikely. Code expects `RCP_CONFIG_BUCKET`, `RCP_AUDIT_METADATA_TABLE`, `RCP_AWS_PROFILE`, and `RCP_AWS_REGION`, matching the user/requested names except region must be `RCP_AWS_REGION` if overridden.
- Stage config placeholder used despite exported overrides: no evidence in the code; exported overrides should replace placeholders.
- Wrong installed CLI version: unlikely as the observed error includes the newly implemented S3 guidance and sanitized AWS code.
- Incorrect bucket used by storage client due to implementation defect: no direct evidence; `AwsClientFactory.s3_storage()` passes `stage_config.config_bucket` directly.
- Region mismatch: less likely for this exact report because the real bucket was verified in `us-east-1`, `dev.json` also uses `us-east-1`, and the AWS code would more commonly be a redirect/authorization-region error that current code maps separately.

Plausible contributing factor:

- The CLI has no `--debug-stage-config` / `--show-effective-stage` command and failure output does not include the resolved bucket/profile/region. That makes it hard to distinguish unexported env vars from a real AWS-side storage problem.

## 8. Confidence Level

Medium-high.

The code path and env override behavior are direct evidence. The most likely root cause cannot be confirmed without seeing `os.environ` from the same process context that invokes `rcp` or adding diagnostic output. However, the combination of a verified real bucket plus `NoSuchBucket` from `rcp` strongly indicates the process is not using the intended `RCP_CONFIG_BUCKET` value.

## 9. Recommended Fix

Likely owner: full-stack/backend operator CLI.

Recommended user diagnostic before code changes:

```bash
export RCP_CONFIG_BUCKET=release-confidence-platform-dev-raw-results
export RCP_AUDIT_METADATA_TABLE=release-confidence-platform-dev-metadata
export RCP_AWS_PROFILE=rk-reliability
export RCP_AWS_REGION=us-east-1

python - <<'PY'
import os
from release_confidence_platform.config.stage_config import StageConfigLoader
cfg = StageConfigLoader().load('dev')
print('module_root_config_bucket=', cfg.config_bucket)
print('module_root_metadata_table=', cfg.audit_metadata_table)
print('module_root_aws_profile=', cfg.aws_profile)
print('module_root_region=', cfg.region)
print('env_RCP_CONFIG_BUCKET=', os.environ.get('RCP_CONFIG_BUCKET'))
print('env_RCP_AWS_PROFILE=', os.environ.get('RCP_AWS_PROFILE'))
PY
```

Expected diagnostic output should show:

- `module_root_config_bucket=release-confidence-platform-dev-raw-results`
- `module_root_metadata_table=release-confidence-platform-dev-metadata`
- `module_root_aws_profile=rk-reliability`
- `module_root_region=us-east-1`

Then rerun `rcp audit create` from the same shell.

Recommended developer fix / enhancement:

1. Add safe effective-stage diagnostic visibility for operator commands, without printing secrets:
   - Option A: new command such as `rcp config stage-info --stage dev --output text|json`.
   - Option B: optional flag such as `--show-effective-stage` / `--debug-stage-config` on mutating commands that prints resolved `stage`, `region`, `aws_profile`, `config_bucket`, and `audit_metadata_table` before mutation.
2. If adding diagnostics to failure output, include sanitized effective resource context for storage config errors, e.g. resolved `region`, `aws_profile`, `config_bucket`, and operation/key prefix. These are stage resource identifiers, not credentials.
3. Keep the existing env var names and override semantics; no evidence suggests they are wrong.
4. Consider documenting that `RCP_*` values must be exported, not merely assigned as shell variables, before running `rcp`.

Cautions:

- Do not print AWS secret/access keys or credential file content.
- If bucket/table names are considered sensitive in some environments, gate them behind an explicit diagnostic flag rather than unconditional normal output.
- Preserve local validation-before-AWS behavior in `services.create_command()`.

## 10. Suggested Validation Steps

- From a clean shell, set non-exported shell variables only and confirm `StageConfigLoader().load('dev')` falls back to placeholders; then export the same variables and confirm overrides apply.
- Run the diagnostic above from the exact shell used for `rcp audit create`; expected effective values must match deployed dev outputs.
- Rerun non-dry-run `rcp audit create` with exported `RCP_*` values; expected next behavior is either `SUCCESS: audit create` with `lifecycle_state: DRAFT` or a different AWS error if IAM/DynamoDB permissions are still incomplete.
- Add unit coverage for a safe effective-stage diagnostic command/flag if implemented.
- Regression-check existing storage error guidance remains for `NoSuchBucket`, `AccessDenied`, and region mismatch.

## 11. Open Questions / Missing Evidence

- Were `RCP_CONFIG_BUCKET`, `RCP_AUDIT_METADATA_TABLE`, `RCP_AWS_PROFILE`, and `RCP_AWS_REGION` exported in the same shell that launched `rcp audit create`?
- What does `StageConfigLoader().load('dev')` print from the same shell/process context after exports?
- What executable is being invoked by `rcp` (`command -v rcp`), and is it an editable install from this repository? This is less likely to be the root cause but useful to verify.
- If exported values are confirmed and the error persists, capture safe diagnostic evidence for resolved bucket/profile/region and the exact installed module path.

## 12. Final Investigator Decision

Ready for developer fix for diagnostic visibility/documentation; likely user environment correction for immediate HITL unblock.

The current implementation appears to read and apply the documented env vars correctly when exported. The most likely cause of the observed `NoSuchBucket` despite verified AWS resources is that the `RCP_*` overrides were available for shell expansion during AWS CLI checks but not exported to the `rcp` child process, causing fallback to placeholder stage config values.
