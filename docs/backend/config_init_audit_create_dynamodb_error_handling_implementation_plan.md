# Implementation Plan

## 1. Feature Overview
Fix HITL blocker where `rcp audit create` can surface DynamoDB metadata write failures as generic `UNEXPECTED_ERROR` after S3 config writes.

## 2. Technical Scope
Implement low-level DynamoDB AttributeValue serialization/deserialization for audit and run metadata clients, preserve table-style test adapter compatibility, stop broad metadata lookup exception suppression, and map DynamoDB/botocore failures to structured storage errors.

## 3. Source Inputs
- `docs/bugs/config_init_audit_create_dynamodb_unexpected_error_bug_report.md`
- `docs/architecture/enhanced_config_init_default_profile_system_technical_design.md`
- Existing storage and operator CLI error-handling patterns.

## 4. API Contracts Affected
No CLI command shape changes. Error rendering may now expose existing structured storage error codes instead of `UNEXPECTED_ERROR` for DynamoDB metadata failures.

## 5. Data Models / Storage Affected
No table schema changes. Low-level DynamoDB requests for `Key`, `Item`, and `ExpressionAttributeValues` will use AttributeValue-encoded shapes.

## 6. Files Expected to Change
- `src/release_confidence_platform/storage/audit_metadata_client.py`
- `src/release_confidence_platform/storage/dynamodb_client.py`
- `src/release_confidence_platform/core/audit_creation_service.py`
- `src/release_confidence_platform/operator_cli/result.py`
- DynamoDB regression tests under `tests/`

## 7. Security / Authorization Considerations
Map missing table and access denied to sanitized, actionable storage errors. Do not log or expose secrets or raw request payloads.

## 8. Dependencies / Constraints
Use existing `boto3`/`botocore` dependency only. No live AWS calls, no resource creation, no branch changes, no commit.

## 9. Assumptions
- Existing table-style unit fakes should remain supported via the repository fallback path.
- `AUDIT_NOT_FOUND` remains the only expected absence signal for pre-write metadata lookup.

## 10. Validation Plan
- Run targeted DynamoDB storage regression tests.
- Run targeted operator CLI audit create/config init tests.
- Run existing S3 storage guidance tests.
