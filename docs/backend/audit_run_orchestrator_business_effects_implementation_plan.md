# Implementation Plan

## 1. Feature Overview
Fix `rcp audit run` observability and execution-result reporting so manual Lambda invocations expose sanitized handler execution status instead of only Lambda API acceptance.

## 2. Technical Scope
- Add a guaranteed sanitized first-line orchestrator handler log before AWS client setup.
- Configure backend handler logging for INFO visibility while preserving JSON/sanitized output.
- Normalize orchestrator events for direct payloads and EventBridge `detail` wrappers.
- Strengthen sanitized failure logging in orchestrator exception paths.
- Send complete manual run event contract from the CLI service.
- Use synchronous Lambda invocation for manual runs and decode safe handler responses.

## 3. Source Inputs
- `docs/bugs/audit_run_orchestrator_no_business_effects_bug_report.md`
- `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- `docs/architecture/structured_logging.md`
- Existing backend/orchestrator, CLI, and Lambda client tests.

## 4. API Contracts Affected
No HTTP API contract changes.

CLI/backend invocation contract affected:
- Manual Lambda payload includes `client_id`, `audit_id`, `scenario_type`, `triggered_by: manual`, `schedule_type: manual`, `stage`, and optional `run_id`.
- `rcp audit run` uses `InvocationType=RequestResponse` and surfaces sanitized handler status/response metadata.

## 5. Data Models / Storage Affected
No data model or storage schema changes.

## 6. Files Expected to Change
- `apps/backend/handlers/orchestrator_handler.py`
- `apps/backend/orchestrator/service.py`
- `packages/core/validators.py`
- `src/release_confidence_platform/core/manual_run_service.py`
- `src/release_confidence_platform/storage/lambda_client.py`
- `src/release_confidence_platform/operator_cli/services.py`
- Tests under `tests/unit/`
- Backend plan/report docs under `docs/backend/`

## 7. Security / Authorization Considerations
- Do not log full events or payloads.
- First-line handler log includes only event keys and safe event type metadata.
- Lambda payload/response decoding is sanitized and truncated.
- Failure logs avoid raw exception messages that may contain secrets.

## 8. Dependencies / Constraints
No new dependencies. No AWS deployment, branch change, commit, push, or PR.

## 9. Assumptions
- Synchronous manual invocation is acceptable for `rcp audit run` per bug guidance.
- EventBridge `detail` wrapper support is limited to extracting a dict `detail` object before existing validation.

## 10. Validation Plan
- Run targeted unit tests for core engine validators/orchestrator logging and CLI/Lambda behavior.
- Run existing packaging/diagnostic and operator CLI regression tests where practical.
