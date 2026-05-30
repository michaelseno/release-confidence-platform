# Test Plan

## 1. Feature Overview

Validate the backend fix for the audit-run orchestrator observability blocker where CloudWatch showed only the handler start fallback log and Lambda platform END/REPORT records. Scope is local QA only: no AWS deploy, no live CloudWatch/S3/DynamoDB validation.

## 2. Acceptance Criteria Mapping

| AC | Requirement | Test Coverage |
| --- | --- | --- |
| AC1 | Handler logging configuration enables INFO logs and preserves first-line print fallback | `tests/api/test_audit_run_orchestrator_observability.py::test_handler_logging_configuration_enables_info_and_preserves_print_fallback` |
| AC2 | Success path emits sanitized milestone logs for validation, duplicate preflight, started metadata write, config load, endpoint execution, raw-result write, terminal metadata update, and final return | `tests/api/test_audit_run_orchestrator_observability.py::test_success_path_emits_required_sanitized_milestone_logs` |
| AC3 | Validation, config-load, raw-result, and metadata failure paths emit ERROR logs and structured failed responses | `tests/api/test_audit_run_orchestrator_observability.py::test_validation_and_config_failures_emit_error_logs_and_structured_failure`; `test_raw_result_and_metadata_failures_emit_error_logs_and_structured_failure` |
| AC4 | Logs do not leak secret-like values, full event payloads, endpoint headers/tokens, or raw tracebacks by default | Success/failure sanitization assertions plus `test_structured_logs_do_not_leak_full_payloads_or_tracebacks` |
| AC5 | DynamoDB backend `ClientError` maps to sanitized actionable `StorageError` with operation/error-code/required permission context | `test_dynamodb_clienterror_maps_to_actionable_sanitized_storage_error` and existing DynamoDB guidance tests |
| AC6 | Prior HITL fixes still pass: config-init, audit-create, stage-info, Lambda packaging, sync response/failure detail rendering, backend S3 diagnostics/IAM tests | Focused HITL regression command plus full pytest |
| AC7 | Ruff lint, Ruff format, and full pytest gates pass | Executed quality gates and full pytest; Ruff gates currently fail |

## 3. Test Scenarios

1. Handler log configuration resets root/application logger levels to INFO when `LOG_LEVEL=INFO`.
2. Handler keeps the first-line `orchestrator_handler_started` print fallback and logs event keys without event values.
3. Successful orchestration emits the required ordered lifecycle milestones.
4. Successful orchestration logs remain sanitized when endpoint config includes secret-backed headers and token-like URL values.
5. Invalid event input returns a structured failed response and emits an ERROR validation log without full payload leakage.
6. Missing config returns a structured failed response and emits an ERROR config-load log.
7. Raw result write failures return a structured failed response and emit an ERROR raw-result log.
8. Started metadata write failures return a structured failed response and emit an ERROR metadata log.
9. Structured logger output does not contain secret values, `headers`, `payload`, or traceback text by default.
10. DynamoDB permission `ClientError` maps to `STORAGE_PERMISSION_ERROR` with safe operation, AWS error code, and required permission guidance.
11. Focused prior-HITL regression tests remain passing.
12. Full pytest remains passing.
13. Ruff lint and format gates are executed as release-blocking checks.

## 4. Edge Cases

- Malformed event before validation must expose only safe raw correlation fields.
- Secret-like strings embedded in token/query/header fields must not appear in logs.
- Failure before started metadata exists must still return a structured failure response.
- DynamoDB AWS raw error messages must not leak into actionable storage errors.
- Quality-gate failures are blocking even when functional pytest passes.

## 5. Test Types Covered

- API/contract regression tests
- Functional orchestration tests with faked storage/secrets/runner dependencies
- Negative/failure-path tests
- Security/sanitization tests
- Prior-HITL focused regression tests
- Full pytest regression suite
- Ruff lint and format quality gates

## 6. Coverage Justification

The local suite validates all fixable contracts without AWS deployment: Lambda handler logging behavior, milestone emission order, sanitized failure behavior, DynamoDB storage error mapping, and regression protection for prior HITL fixes. Live HITL CloudWatch/artifact proof remains out of scope until the backend is redeployed.
