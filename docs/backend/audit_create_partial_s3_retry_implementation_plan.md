# Implementation Plan

## 1. Feature Overview
Fix `rcp audit create` retry behavior when an earlier attempt uploaded deterministic S3 config artifacts but failed before DynamoDB audit metadata was created.

## 2. Technical Scope
Add partial-create reconciliation in `AuditCreationService.create_from_files()` for the metadata-absent/S3-present state. Matching existing artifacts will be adopted by creating missing `DRAFT` metadata. Partial or mismatched artifacts will fail with a structured actionable error. Improve CLI next-step rendering for config-object and partial-state errors.

## 3. Source Inputs
- `docs/bugs/audit_create_partial_s3_upload_retry_blocker_bug_report.md`
- `docs/architecture/operator_cli_rcp_technical_design.md`
- `docs/architecture/enhanced_config_init_default_profile_system_technical_design.md`
- Existing audit create, storage, and CLI result patterns.

## 4. API Contracts Affected
No CLI command arguments change. `audit create` non-force behavior is refined only for metadata-absent partial S3 state:
- all expected S3 artifacts exist and match current validated payloads: create missing `DRAFT` metadata and return existing success response shape.
- partial or mismatched S3 artifacts: fail with `PARTIAL_AUDIT_CREATE_EXISTS` and key-level diagnostics in the sanitized message.
- existing metadata handling and `--force` lifecycle guardrails remain unchanged.

## 5. Data Models / Storage Affected
No schema changes. The fix reads existing deterministic S3 config objects and may create the same `DRAFT` audit metadata item that a clean create would have created.

## 6. Files Expected to Change
- `src/release_confidence_platform/core/audit_creation_service.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `tests/unit/test_operator_cli_rcp.py`
- `docs/backend/audit_create_partial_s3_retry_implementation_report.md`

## 7. Security / Authorization Considerations
Read and compare only deterministic config keys for the requested client/audit IDs. Do not log or expose config payloads, secrets, tokens, bucket names, or raw AWS errors. Diagnostics are limited to safe artifact labels and deterministic S3 keys.

## 8. Dependencies / Constraints
Use Python standard library only. No live AWS cleanup. Do not change branch, commit, push, or create PR.

## 9. Assumptions
- Deterministic JSON comparison after existing sanitization is safe for config equivalence and does not alter external behavior.
- Rollback deletion is not added because the existing S3 storage abstraction has no delete method in scope; idempotent reconciliation covers the reported metadata-failure retry mode.
- The HITL bug report supersedes the older technical design's strict non-force duplicate-S3 failure rule for the metadata-absent partial-create state.

## 10. Validation Plan
- Run targeted unit tests for audit create partial retry and CLI rendering.
- Run full operator CLI unit regression if time permits.
