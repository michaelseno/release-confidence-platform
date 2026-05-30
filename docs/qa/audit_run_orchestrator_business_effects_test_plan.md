# Test Plan

## 1. Feature Overview

Validate the HITL blocker fix for `rcp audit run` where Lambda invocation succeeded at the API layer but produced no observable orchestrator business effects. QA scope is local/unit/static only; no AWS deployment or live CloudWatch/S3/DynamoDB validation is performed.

## 2. Acceptance Criteria Mapping

| AC | Requirement | Validation |
| --- | --- | --- |
| AC1 | Serverless handler path points to the real orchestrator handler and calls `CoreEngineOrchestrator.run(event)` | Static inspection of `infra/serverless.yml` and `apps/backend/handlers/orchestrator_handler.py`; covered by handler monkeypatch unit test. |
| AC2 | First-line handler log is guaranteed and sanitized with `event_type=orchestrator_handler_started` and `event_keys` only | `tests/unit/test_phase1_core_engine.py::test_handler_first_line_log_contains_only_event_keys`. |
| AC3 | Manual run payload includes `client_id`, `audit_id`, `scenario_type`, `schedule_type=manual`, `triggered_by=manual`, and `stage` | `tests/unit/test_operator_cli_rcp.py::test_run_dry_run_and_invalid_run_id` and sync invocation test. |
| AC4 | Direct manual event contract is accepted | `tests/unit/test_phase1_core_engine.py::test_direct_manual_event_is_accepted_without_schedule_occurrence_id`. |
| AC5 | EventBridge `detail` wrapper is accepted | `tests/unit/test_phase1_core_engine.py::test_eventbridge_detail_wrapper_is_accepted_without_schedule_occurrence_id`. |
| AC6 | Manual runs do not require `schedule_occurrence_id` | Direct and EventBridge validator tests omit `schedule_occurrence_id`. |
| AC7 | Exceptions are not swallowed silently; sanitized structured log and failure response are produced | `tests/unit/test_phase1_core_engine.py::test_failure_metadata_update_error_is_logged_safely` plus failure response tests. |
| AC8 | `rcp audit run` distinguishes Lambda invoke API success from orchestrator execution result | Lambda client and CLI tests in `tests/unit/test_operator_cli_rcp.py`. |
| AC9 | Lambda packaging fix remains intact | Static infra tests in `tests/unit/test_infra_configuration.py`; package artifact absent so artifact ZIP inspection is skipped by design. |
| AC10 | Prior HITL fixes and original config-init criteria still pass | Full pytest plus targeted config-init/profile/security regression tests. |
| AC11 | Ruff/format quality gates and full pytest pass | Execute Ruff lint, Ruff format check, and full pytest. |

## 3. Test Scenarios

1. Static serverless handler mapping review.
2. Handler start log emits before AWS client construction and does not include event payload values.
3. Manual payload dry-run and synchronous invocation include full manual contract.
4. Backend validator accepts direct manual events without scheduled occurrence metadata.
5. Backend validator accepts EventBridge `detail` wrapper events without scheduled occurrence metadata.
6. Lambda synchronous response decoding exposes sanitized handler success/failure fields.
7. CLI returns failed command status/exit code when handler payload reports failure.
8. Runtime/import dependency Lambda errors remain sanitized and actionable.
9. Serverless packaging configuration includes backend requirements and dependency plugin.
10. Enhanced config-init default profile regressions remain passing.
11. Full repository regression suite remains passing.
12. Ruff lint and format quality gates remain passing.

## 4. Edge Cases

- Malformed/non-secret event values must not be logged as full payload.
- EventBridge wrapper with no `schedule_occurrence_id` must still normalize successfully.
- Handler failure payload from synchronous Lambda response must not be confused with Lambda API success.
- Import/runtime failures must redact token/secret-like diagnostic values.
- Missing local package artifact must not block static packaging validation when no artifact exists.

## 5. Test Types Covered

- Static configuration review
- Unit tests
- API/contract tests
- Security/sanitization regression tests
- Integration regression tests via full pytest
- Quality gates: Ruff lint and Ruff format check

## 6. Coverage Justification

The suite covers the corrected local contracts that can be proven without AWS deployment: handler mapping, sanitized first-line observability, manual event contract, direct/EventBridge event validation, synchronous invocation result handling, packaging configuration, and config-init regression scope. Live verification of CloudWatch logs and actual S3/DynamoDB business artifacts remains a separate redeploy/HITL activity.
