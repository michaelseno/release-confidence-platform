# Test Plan

## 1. Feature Overview
Validate the HITL blocker fix for failed `rcp audit run --scenario-type repeated_stability` diagnostics. The fix must promote safe synchronous orchestrator handler failure details into CLI result data and render actionable text/JSON output without exposing secrets, raw payloads, or tracebacks by default.

## 2. Acceptance Criteria Mapping
| Acceptance Criterion | Test Coverage |
| --- | --- |
| Promote handler failure response details from synchronous `handler_response` into CLI result data. | `test_manual_run_promotes_safe_handler_failure_details`; `test_cli_run_result_distinguishes_handler_failure_from_invoke_acceptance` |
| Failed `audit run` text includes `run_id`, `scenario_type`, `handler_status`, error/failure type, failure message, and actionable non-`none` next step. | `test_audit_run_failure_text_renders_actionable_handler_details` |
| JSON output includes structured failure details. | `test_audit_run_failure_json_includes_structured_details_without_secret_leak` |
| Secret-like values are redacted; no full raw event payload/raw traceback/secrets exposed by default. | Failure-detail tests above plus sanitizer/security regressions in `test_phase1_qa_contracts.py`, Lambda diagnostics tests in `test_operator_cli_rcp.py` |
| Success path remains unchanged. | `test_audit_run_success_text_remains_without_failure_fields`; full pytest regression suite |
| Prior HITL fixes still pass: config-init, stage-info, audit-create structured errors, Lambda packaging diagnostics, orchestrator handler logs/event contract. | Focused HITL regression subset and full pytest suite |
| Ruff/format gates and full pytest pass. | `ruff format --check`, `ruff check`, `pytest` execution gates |

## 3. Test Scenarios
1. Synchronous Lambda handler returns `FAILED` with `failure_summary`; CLI service promotes run/scenario/error/message fields.
2. `audit run` command converts handler failure into failed `CommandResult` with exit code `1` while preserving invocation payload under structured data.
3. Text renderer displays safe actionable diagnostics and does not print `next_step: none` for handler failure.
4. JSON renderer emits structured `failure_details` and sanitized nested invocation response.
5. Success text output remains unchanged and does not add failure-only fields.
6. Regression suite covers config-init default profiles/no-AWS behavior, stage-info guidance, audit-create/storage structured errors, Lambda invocation/dependency diagnostics, and orchestrator event/log contracts.
7. Quality gates verify formatting, linting, and complete automated test suite health.

## 4. Edge Cases
- Handler status casing differences (`FAILED` vs `failed`).
- Missing or partial `failure_summary` fallback fields.
- Secret-like fragments in handler messages (`token=...`, `Bearer ...`) and sensitive keys in nested response objects.
- Config validation/load failures that require config-specific next-step guidance.
- Generic orchestration failures that require JSON/CloudWatch next-step guidance.

## 5. Test Types Covered
- Unit tests for promotion and rendering behavior.
- API/security regression tests for config-init, storage guidance, and sanitization.
- Integration/regression tests through the full pytest suite.
- Static quality gates with Ruff format and lint checks.

## 6. Coverage Justification
The planned coverage directly maps every bug-report requirement to automated assertions and includes broad regression protection for the prior HITL fixes named in the validation request. Live AWS HITL execution was not performed in this local QA pass; validation is based on deterministic unit/API/security/integration tests and static gates available in the repository.
