# Bug Report

## 1. Summary

During HITL validation on `feature/profile_driven_config_init`, non-dry-run `rcp audit create --stage dev` now gets past local validation, AWS profile setup, and S3 config writes, then fails with generic `UNEXPECTED_ERROR`.

Most likely root cause: `audit create` uses a low-level boto3 DynamoDB client (`session.client("dynamodb")`) but `AuditMetadataRepository` sends plain Python dictionaries for `Key`, `Item`, and `ExpressionAttributeValues`. The low-level DynamoDB client requires DynamoDB AttributeValue maps. Botocore raises a parameter validation/serialization exception that is not a `ClientError` and not an `EngineError`, so `operator_cli.main` wraps it as `UNEXPECTED_ERROR`.

## 2. Investigation Context

- Source of report: HITL manual validation.
- Branch context: current active HITL correction branch is `feature/profile_driven_config_init`; no new branch should be created.
- Related workflow: Enhanced `rcp config init` Default Profile System -> generated local config bundle -> non-dry-run `rcp audit create`.
- User-provided deployed dev resource context:
  - `RCP_AWS_PROFILE=rk-reliability`
  - `RCP_CONFIG_BUCKET=release-confidence-platform-dev-raw-results`
  - `RCP_AUDIT_METADATA_TABLE=release-confidence-platform-dev-metadata`
  - `RCP_AWS_REGION=us-east-1`
  - AWS CLI `head-bucket` succeeds.
  - DynamoDB table status is `ACTIVE`.
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
code: UNEXPECTED_ERROR
message: Unexpected operator CLI failure
next_step: correct the error and retry
```

Expected behavior:

- If DynamoDB metadata creation fails due to schema/serialization, missing table, permission, or condition conflicts, the CLI should return a structured platform error with actionable guidance.
- With valid S3 and DynamoDB dev resources and sufficient permissions, `audit create` should write three config artifacts and create one DRAFT audit metadata item.

Actual behavior:

- After prior S3/profile blockers were cleared, the CLI still emits a generic wrapper without exposing whether DynamoDB serialization, table name, IAM permission, or conditional write failed.

## 4. Evidence Collected

Files inspected:

- `src/release_confidence_platform/operator_cli/main.py`
- `src/release_confidence_platform/operator_cli/services.py`
- `src/release_confidence_platform/core/audit_creation_service.py`
- `src/release_confidence_platform/storage/aws_client_factory.py`
- `src/release_confidence_platform/storage/audit_metadata_client.py`
- `src/release_confidence_platform/storage/s3_client.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `src/release_confidence_platform/config/stage_config.py`
- `infra/resources/dynamodb.yml`
- `pyproject.toml`
- Existing HITL bug reports under `docs/bugs/`

Key evidence:

- `audit create` path in `services.create_command()` validates local files, builds `AwsClientFactory`, then passes `factory.s3_storage()` and `factory.audit_metadata_repository()` into `AuditCreationService`: `src/release_confidence_platform/operator_cli/services.py:179-201`.
- `AwsClientFactory.audit_metadata_repository()` constructs a low-level DynamoDB client via `self._session.client("dynamodb")`: `src/release_confidence_platform/storage/aws_client_factory.py:35-40`.
- `AuditCreationService.create_from_files()` writes all S3 config objects first, then calls `repository.put_audit_metadata_once(metadata)`: `src/release_confidence_platform/core/audit_creation_service.py:93-103`.
- No scheduler or Lambda calls occur in `audit create`; scheduler is only used by `schedule_command()` and Lambda only by `run_command()`: `src/release_confidence_platform/operator_cli/services.py:213-257`.
- Metadata keys are plain strings: `AuditMetadataRepository.audit_keys()` returns `{"PK": "CLIENT#...", "SK": "AUDIT#..."}` at `src/release_confidence_platform/storage/audit_metadata_client.py:25-26`.
- DynamoDB `put_item` receives `Item=sanitize(item)` where `item` is a plain Python metadata dictionary, not AttributeValue maps: `src/release_confidence_platform/storage/audit_metadata_client.py:276-282`.
- DynamoDB `get_item`, `update_item`, occurrence updates, and lifecycle updates also use plain Python `Key` / `ExpressionAttributeValues`: `src/release_confidence_platform/storage/audit_metadata_client.py:36-40`, `:168-183`, `:194-212`, `:247-253`, `:267-274`.
- `_put_conditional()` catches only `botocore.exceptions.ClientError`; botocore parameter validation/serialization errors from malformed low-level request shapes are not caught and therefore bubble: `src/release_confidence_platform/storage/audit_metadata_client.py:276-286`.
- `_call()` only retries without `TableName` on `TypeError`; it does not convert or map botocore validation errors: `src/release_confidence_platform/storage/audit_metadata_client.py:288-293`.
- `main.main()` catches only `EngineError` as structured output; every other exception is rendered as `UNEXPECTED_ERROR`: `src/release_confidence_platform/operator_cli/main.py:164-187`.
- Existing unit fakes accept plain dictionaries, so tests do not exercise the real low-level boto3 DynamoDB request contract: `tests/unit/test_operator_cli_rcp.py:47-68`, `:506-530`.
- The deployed table key schema is `PK`/`SK` string attributes, so the logical key names match; the likely mismatch is client request serialization, not table schema: `infra/resources/dynamodb.yml:7-16`.

Local reproduction status:

- Direct boto3/botocore reproduction was blocked in this investigation shell because `python3` cannot import `boto3` (`ModuleNotFoundError`).
- Code-level reproduction with the available source is sufficient to identify the likely failure class: the installed CLI depends on `boto3>=1.34,<2` and uses a low-level DynamoDB client, whose API contract requires AttributeValue dictionaries for `Key`, `Item`, and `ExpressionAttributeValues`.

## 5. Execution Path / Failure Trace

Likely path for the reported command:

1. `rcp audit create` dispatches to `services.create_command()`.
2. `StageConfigLoader().load("dev")` resolves the exported dev bucket/table/profile/region.
3. Local config validation succeeds.
4. `AwsClientFactory` creates S3 and DynamoDB low-level clients.
5. `AuditCreationService.create_from_files()` checks for existing metadata. `get_audit_metadata()` likely sends plain `Key={"PK": "CLIENT#...", "SK": "AUDIT#..."}` to the low-level client. Any exception here is swallowed as `existing_metadata = None` by `core/audit_creation_service.py:70-76`, which can hide early DynamoDB request-shape failures.
6. `AuditCreationService` checks/writes S3 objects under `configs/<client_id>/...`. The user report indicates the workflow got past prior bucket/profile blockers, so this likely succeeds.
7. `AuditCreationService` calls `put_audit_metadata_once(metadata)`.
8. `AuditMetadataRepository._put_conditional()` calls low-level `put_item(TableName=..., Item=<plain dict>, ConditionExpression=...)`.
9. Botocore rejects the request shape before/while serializing the service request, likely as `ParamValidationError` or a related botocore serialization error.
10. Because `_put_conditional()` catches only `ClientError`, the exception escapes to `main.main()` and is rendered as `UNEXPECTED_ERROR`.

## 6. Failure Classification

- Primary classification: Application Bug.
- Contributing classification: Contract Mismatch between repository implementation/tests and boto3 low-level DynamoDB API.
- Severity: Blocker for current HITL validation; High product severity for non-dry-run onboarding.

Severity justification: the issue blocks HITL completion of the advertised config-init -> audit-create workflow after valid AWS resources are configured. It also leaves S3 config artifacts written before metadata creation fails, creating partial state that may affect retries.

## 7. Root Cause Analysis

Confidence label: Most Likely Root Cause

Immediate failure point:

- A non-`EngineError`, non-`ClientError` exception escapes from the post-S3 DynamoDB metadata creation path and is caught by the generic `except Exception` in `operator_cli.main.main()`.

Underlying root cause:

- `AuditMetadataRepository` is written as if its `dynamodb_client` accepted resource/table-style plain Python items, but `AwsClientFactory` supplies a low-level boto3 DynamoDB client. Low-level DynamoDB methods require AttributeValue-encoded request values, e.g. `{"S": "CLIENT#..."}`, `{"M": ...}`, `{"L": ...}`. This mismatch is expected to raise botocore parameter validation/serialization errors during `get_item` and especially `put_item`.

Supporting evidence:

- Low-level client construction: `src/release_confidence_platform/storage/aws_client_factory.py:35-40`.
- Plain key/item writes: `src/release_confidence_platform/storage/audit_metadata_client.py:25-26`, `:276-282`.
- Generic wrapper for non-`EngineError`: `src/release_confidence_platform/operator_cli/main.py:177-187`.
- The user verified the table exists and S3/profile issues are cleared, making a post-S3 repository-layer failure the most consistent remaining path.

Plausible contributing factors:

- `AuditCreationService` suppresses all exceptions during the pre-write metadata lookup (`except Exception: existing_metadata = None`), which can hide the first DynamoDB contract failure and allow partial S3 writes before the later metadata write fails.
- Tests use permissive fakes that accept plain dictionaries, so they do not catch boto3 low-level request-shape defects.
- DynamoDB errors are less actionable than S3 errors: `StorageError("DynamoDB put failed", "STORAGE_ERROR")` lacks safe AWS error code/action guidance, and non-`ClientError` botocore exceptions are unmapped.

## 8. Confidence Level

High for affected code path and API contract mismatch; medium-high that this is the exact hidden exception in the user run.

The code directly proves `audit create` reaches DynamoDB after S3 writes and that the repository sends plain Python values to a low-level client. Direct user traceback is still needed to confirm the precise exception class/message (`ParamValidationError` vs related botocore serialization exception vs IAM/table ClientError).

## 9. Recommended Fix

Likely owner: backend/operator CLI storage layer.

Recommended developer fix:

1. Fix the DynamoDB client contract in `src/release_confidence_platform/storage/audit_metadata_client.py` for all low-level client calls:
   - Either use `boto3.dynamodb.types.TypeSerializer` to serialize `Key`, `Item`, and `ExpressionAttributeValues` before calling low-level `get_item`, `put_item`, and `update_item`, and use `TypeDeserializer` on returned `Item`/`Items`.
   - Or change `AwsClientFactory.audit_metadata_repository()` to provide a DynamoDB resource/table adapter that accepts plain Python dictionaries, and update repository methods to call table-style APIs consistently.
2. Apply the same decision consistently to `src/release_confidence_platform/storage/dynamodb_client.py`, which has the same low-level/plain-dict pattern for run metadata.
3. Replace broad metadata-existence suppression in `AuditCreationService.create_from_files()` with targeted handling:
   - Treat only `StorageError` with `error_type == "AUDIT_NOT_FOUND"` as absent metadata.
   - Let DynamoDB serialization, table, or permission failures abort before any S3 writes when possible, or perform a structured preflight check.
4. Map known DynamoDB/botocore failures to structured `StorageError` values:
   - `ParamValidationError` / serialization request-shape errors -> `DYNAMODB_REQUEST_ERROR` or `STORAGE_CONFIG_ERROR` with safe guidance.
   - `ResourceNotFoundException` -> `STORAGE_CONFIG_ERROR` naming `RCP_AUDIT_METADATA_TABLE`.
   - `AccessDeniedException` / IAM denial codes -> `STORAGE_PERMISSION_ERROR` naming required DynamoDB permissions.
   - `ConditionalCheckFailedException` remains `AUDIT_EXISTS` / force lifecycle conflict as appropriate.
5. Add regression tests using botocore `Stubber` or a strict fake that rejects non-AttributeValue low-level request shapes. Include a test where `audit create` fails during metadata creation and verifies the CLI returns structured output, not `UNEXPECTED_ERROR`.
6. Consider changing operation ordering or adding compensating cleanup so S3 config objects are not left orphaned when metadata creation fails.

Cautions:

- Do not weaken config validation or create audits with invalid endpoint/config content.
- Do not print credentials or raw boto exception messages that may contain sensitive data; include only sanitized AWS error code, operation, table name/stage, and required permission guidance.
- Preserve the current active HITL branch; no new branch is needed.

## 10. Suggested Validation Steps

After fixing:

- Run unit coverage for `AuditMetadataRepository.put_audit_metadata_once()` against a strict low-level DynamoDB stub and verify AttributeValue request shapes.
- Run `rcp audit create --dry-run` with the same generated files; expected: validation passes and no AWS calls are made.
- Run non-dry `rcp audit create --stage dev` with exported `RCP_*` values; expected: `SUCCESS: audit create`, `lifecycle_state: DRAFT`, three config S3 keys, and one metadata item in `release-confidence-platform-dev-metadata`.
- Run a duplicate create without `--force`; expected: structured `CONFIG_OBJECT_EXISTS` or `AUDIT_EXISTS`, not `UNEXPECTED_ERROR`.
- Run with a deliberately wrong DynamoDB table name; expected: structured storage config error mentioning `RCP_AUDIT_METADATA_TABLE` / table existence.
- Run with a profile lacking DynamoDB write permissions; expected: structured storage permission error naming required DynamoDB permissions.

## 11. Open Questions / Missing Evidence

- Need the exact hidden traceback from the user's environment to confirm the precise exception class/message.
- Need to know whether the user’s generated endpoints included sample/real endpoints; however, local validation and S3 writes were reached, so this is not likely the current blocker.
- Need confirmation whether S3 config objects now exist from the failed attempt; retries may hit `CONFIG_OBJECT_EXISTS` unless `--force` or cleanup is used after the metadata fix.

Immediate user diagnostic command to reveal the hidden exception:

```bash
export RCP_AWS_PROFILE=rk-reliability
export RCP_CONFIG_BUCKET=release-confidence-platform-dev-raw-results
export RCP_AUDIT_METADATA_TABLE=release-confidence-platform-dev-metadata
export RCP_AWS_REGION=us-east-1

python - <<'PY'
from release_confidence_platform.operator_cli.main import build_parser, dispatch

argv = [
    "audit", "create",
    "--client-config", ".local-configs/client_layer_1_validation_client_b5817642/client_config.json",
    "--audit-config", ".local-configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/audit_config.json",
    "--endpoints-config", ".local-configs/client_layer_1_validation_client_b5817642/audits/audit_20260524_ec3f2d9b/endpoints.json",
    "--stage", "dev",
]

args = build_parser().parse_args(argv)
dispatch(args)  # bypasses main() generic UNEXPECTED_ERROR wrapper and should print the real traceback
PY
```

If `python` is not the interpreter used by the installed `rcp`, run the same snippet with that interpreter. This may attempt another S3 write before failing; if objects already exist, add `--force` only if it is safe to overwrite the draft config artifacts.

## 12. Final Investigator Decision

Ready for developer fix.

The post-S3 failure path is sufficiently identified. More user traceback would confirm the exact hidden exception, but the low-level DynamoDB/plain-dict mismatch and generic exception wrapping are enough to drive a targeted storage-layer fix.
