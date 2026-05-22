# Implementation Plan

## 1. Feature Overview
Implement the internal `rcp` operator CLI for audit validation, creation, scheduling, manual invocation, and cancellation.

## 2. Technical Scope
Add a thin CLI package and script entry point, shared stage configuration loading, shared audit config validation, creation, persisted scheduling, manual run, cancellation orchestration, and mockable AWS wrapper extensions.

## 3. Source Inputs
- `docs/architecture/operator_cli_rcp_technical_design.md`
- `docs/product/operator_cli_rcp_spec.md`
- `docs/uiux/operator_cli_rcp_design_spec.md`
- `docs/qa/operator_cli_rcp_test_plan.md`
- `docs/release/operator_cli_rcp_issue.md`
- Existing Phase 1/2/3 validators, lifecycle, scheduling, storage, and sanitization modules.

## 4. API Contracts Affected
No public HTTP API contract changes. Internal CLI commands affected:
- `rcp audit validate --client-config --audit-config --endpoints-config --stage [--output]`
- `rcp audit create --client-config --audit-config --endpoints-config --stage [--dry-run] [--force] [--output]`
- `rcp audit schedule --client-id --audit-id --stage [--dry-run] [--allow-production] [--output]`
- `rcp audit run --client-id --audit-id --scenario-type --stage [--run-id] [--schedule-type] [--dry-run] [--output]`
- `rcp audit cancel --client-id --audit-id --stage [--reason] [--dry-run] [--output]`

## 5. Data Models / Storage Affected
- S3 config objects at deterministic keys under `configs/{client_id}/...`.
- DynamoDB audit metadata item `PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}` with lifecycle, config hashes, config keys, schedules, cleanup errors, and history.
- EventBridge Scheduler schedule metadata retained in DynamoDB.

## 6. Files Expected to Change
- `scripts/rcp.py`
- `packages/operator_cli/*`
- `packages/config/stage_config.py`, `packages/config/audit_validation_service.py`
- `packages/core/audit_creation_service.py`, `packages/core/manual_run_service.py`
- `packages/audit_scheduling/service.py`, `packages/audit_scheduling/builders.py`
- `packages/audit_lifecycle/cancellation.py`
- `packages/storage/*`
- `config/stages/*.json`
- `tests/unit/test_operator_cli_rcp.py`
- `docs/operator-cli/README.md`, `packages/operator_cli/README.md`

## 7. Security / Authorization Considerations
CLI is trusted-internal and has no RBAC. Implementation must validate identifiers, never store or print literal secrets, sanitize provider failures, enforce production/destructive operation flags, and avoid hardcoded AWS resource names in command handlers.

## 8. Dependencies / Constraints
No new runtime dependencies planned. AWS calls stay behind existing boto3-compatible wrappers and are mocked in tests.

## 9. Assumptions
- Existing config shapes are permissive; validation accepts both Phase 3 existing names and product-spec schedule block aliases where safe.
- Stage config files use non-secret placeholder resource names suitable for tests and local dry-run usage.

## 10. Validation Plan
- `python -m pytest tests/unit/test_operator_cli_rcp.py`
- Targeted existing Phase 3 tests where relevant if time permits.
