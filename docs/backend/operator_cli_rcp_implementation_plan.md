# Implementation Plan

## 1. Feature Overview
Implement and stabilize the internal `rcp` operator CLI for audit validation, creation, scheduling, manual invocation, and cancellation. This update specifically fixes QA-blocking Operator CLI contract defects for stage config validation and persisted schedule source-of-truth behavior.

## 2. Technical Scope
Add a thin CLI package and script entry point, shared stage configuration loading, shared audit config validation, creation, persisted scheduling, manual run, cancellation orchestration, and mockable AWS wrapper extensions.

QA defect fix scope:
- Reject whitespace-only `RCP_*` environment overrides and whitespace-only resolved required stage config values before AWS client construction.
- Ensure Operator CLI scheduling from persisted `audit_config.json` does not infer a `finalization_schedule` block when it is absent.

## 3. Source Inputs
- `docs/architecture/operator_cli_rcp_technical_design.md`
- `docs/product/operator_cli_rcp_spec.md`
- `docs/uiux/operator_cli_rcp_design_spec.md`
- `docs/qa/operator_cli_rcp_test_plan.md`
- `docs/qa/operator_cli_rcp_test_report.md`
- `docs/bugs/operator_cli_rcp_qa_failures_bug_report.md`
- `docs/release/operator_cli_rcp_issue.md`
- `tests/api/test_operator_cli_rcp_contract.py`
- Existing Phase 1/2/3 validators, lifecycle, scheduling, storage, and sanitization modules.

## 4. API Contracts Affected
No public HTTP API contract changes. Internal CLI commands affected:
- `rcp audit validate --client-config --audit-config --endpoints-config --stage [--output]`
- `rcp audit create --client-config --audit-config --endpoints-config --stage [--dry-run] [--force] [--output]`
- `rcp audit schedule --client-id --audit-id --stage [--dry-run] [--allow-production] [--output]`
- `rcp audit run --client-id --audit-id --scenario-type --stage [--run-id] [--schedule-type] [--dry-run] [--output]`
- `rcp audit cancel --client-id --audit-id --stage [--reason] [--dry-run] [--output]`

Internal service contract corrections:
- `StageConfigLoader.load` rejects explicit overrides whose value is blank after `.strip()` and rejects any resolved required field that is not a non-blank string.
- `AuditSchedulingService.schedule_from_persisted_audit` schedules only persisted, enabled blocks; absent `finalization_schedule` is treated as disabled.

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

QA defect fix files:
- `packages/config/stage_config.py`
- `packages/audit_scheduling/service.py`
- `tests/unit/test_operator_cli_rcp.py`
- `docs/backend/operator_cli_rcp_implementation_plan.md`
- `docs/backend/operator_cli_rcp_implementation_report.md`

## 7. Security / Authorization Considerations
CLI is trusted-internal and has no RBAC. Implementation must validate identifiers, never store or print literal secrets, sanitize provider failures, enforce production/destructive operation flags, and avoid hardcoded AWS resource names in command handlers.

The stage config fix strengthens fail-fast validation so whitespace-only AWS resource settings cannot proceed to client construction. Scheduling remains scoped to trusted operator use and now honors persisted config ownership/source-of-truth boundaries by not creating hidden finalization schedules.

## 8. Dependencies / Constraints
No new runtime dependencies planned. AWS calls stay behind existing boto3-compatible wrappers and are mocked in tests.

## 9. Assumptions
- Existing config shapes are permissive; validation accepts both Phase 3 existing names and product-spec schedule block aliases where safe.
- Stage config files use non-secret placeholder resource names suitable for tests and local dry-run usage.
- Existing legacy `ScheduleBuilder.build_all` default behavior is left unchanged; Operator CLI persisted-config semantics are enforced in the service normalization adapter by explicitly setting missing `finalization_schedule` to disabled.

## 10. Validation Plan
- `python -m pytest tests/unit/test_operator_cli_rcp.py`
- Targeted existing Phase 3 tests where relevant if time permits.
- `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-venv311/bin/python -m pytest tests/api/test_operator_cli_rcp_contract.py`
- `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-venv311/bin/python -m pytest tests/unit/test_operator_cli_rcp.py`
- `/var/folders/7y/zdp6qp9n4dz00dn9f5c3n9lr0000gn/T/opencode/rcp-venv311/bin/python -m pytest tests/unit`
