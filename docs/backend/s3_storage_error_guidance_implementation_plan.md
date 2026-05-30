# Implementation Plan

## 1. Feature Overview
Improve S3 storage diagnostics and runtime permissions for deployed backend storage failures observed during HITL `rcp audit run` validation.

## 2. Technical Scope
Implement allowlisted `botocore.exceptions.ClientError` handling for backend package S3 existence checks and writes. Update Lambda IAM to allow least-privilege bucket-level listing for the runtime prefixes needed by S3 missing-object `HeadObject` semantics. Remove raw AWS error messages from backend runtime storage diagnostics because provider messages can contain bucket names, full keys, client/audit identifiers, or secret-like fragments.

## 3. Source Inputs
- `docs/architecture/enhanced_config_init_default_profile_system_technical_design.md`
- `docs/bugs/config_init_audit_create_s3_write_failure_bug_report.md`
- `docs/bugs/audit_run_s3_existence_check_storage_error_bug_report.md`
- Existing backend orchestrator failure response and storage client patterns.

## 4. API Contracts Affected
No API contract changes. Backend orchestrator failure responses continue to use the existing `failure_summary.error_type` and `failure_summary.message` fields, now with sanitized storage diagnostics.

## 5. Data Models / Storage Affected
No data model or storage schema changes. S3 read/write behavior remains unchanged except for IAM permissions needed for missing-object `HeadObject` semantics and error classification/sanitized diagnostics.

## 6. Files Expected to Change
- `packages/storage/s3_client.py`
- `infra/serverless.yml`
- `tests/unit/test_backend_s3_storage_client.py`
- `tests/unit/test_infra_configuration.py`
- `docs/backend/s3_storage_error_guidance_implementation_plan.md`
- `docs/backend/s3_storage_error_guidance_implementation_report.md`

## 7. Security / Authorization Considerations
Preserve no-secret behavior by not logging or rendering credentials. Expose only allowlisted AWS error code, operation, top-level key prefix/class, and required permission; do not expose raw AWS provider messages. Lambda IAM must add only bucket-level `s3:ListBucket` on the runtime bucket with `s3:prefix` restrictions for `raw-results/*`, `configs/*`, and `data-pools/*`; object permissions remain scoped to bucket objects.

## 8. Dependencies / Constraints
Uses existing `botocore` dependency already present through `boto3`. Do not add dependencies, deploy to AWS, perform live AWS cleanup, broaden IAM beyond required runtime prefixes, or change branch/commit/push.

## 9. Assumptions
- Backend orchestrator already safely propagates `EngineError.error_type` and sanitized message through its existing `failure_summary` response path, so no handler contract change is required.
- S3 diagnostics may expose top-level key prefixes (`raw-results`, `configs`, `data-pools`) because they are non-secret operational categories and avoid client/audit-specific keys.

## 10. Validation Plan
- Run targeted backend package storage tests.
- Run targeted infrastructure configuration tests.
- Run existing S3 storage error guidance tests and previously relevant config-init/HITL regression tests where local environment supports them.
