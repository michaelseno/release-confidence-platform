# Implementation Plan

## 1. Feature Overview
Improve failed `rcp audit run` diagnostics by surfacing safe synchronous orchestrator handler failure details in CLI text and JSON output.

## 2. Technical Scope
- Extract bounded fields from `invocation.handler_response` when the synchronous handler status is failed.
- Promote safe fields into the audit-run `CommandResult.data` payload.
- Render failed audit-run text output with run/scenario/error details and an actionable next step.
- Preserve existing success-path text behavior.
- Preserve sanitization and avoid rendering raw events, headers, tokens, secrets, endpoint URLs, or tracebacks by default.

## 3. Source Inputs
- `docs/bugs/audit_run_repeated_stability_failure_details_bug_report.md`
- `docs/architecture/enhanced_config_init_default_profile_system_technical_design.md`
- Existing CLI/manual-run code and tests under `src/release_confidence_platform/` and `tests/unit/test_operator_cli_rcp.py`

## 4. API Contracts Affected
No HTTP API contract changes.

CLI output contract affected for failed `rcp audit run` only:
- Text output includes `run_id`, `scenario_type`, `handler_status`, `error_code`, `failure_type`, and `failure_message` when available.
- JSON output includes promoted top-level fields and structured `failure_details` when available.
- Failed audit runs render an actionable `next_step` instead of `none`.

## 5. Data Models / Storage Affected
No data model or storage changes.

## 6. Files Expected to Change
- `src/release_confidence_platform/core/manual_run_service.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `src/release_confidence_platform/sanitization/sanitizer.py`
- `tests/unit/test_operator_cli_rcp.py`
- `docs/backend/audit_run_failure_details_implementation_plan.md`
- `docs/backend/audit_run_failure_details_implementation_report.md`

## 7. Security / Authorization Considerations
- No authentication or authorization behavior changes.
- Only bounded, sanitized handler failure fields are promoted.
- Raw event payloads, headers, auth values, endpoint URLs, tokens, secrets, and tracebacks are not newly rendered by text output.
- Sanitization is strengthened for common `token=...`, `secret=...`, `api_key=...`, and `password=...` string fragments.

## 8. Dependencies / Constraints
- No new dependencies.
- No AWS deploy or live AWS invocation.
- Active branch must remain unchanged.
- No commit, push, or PR per HITL correction instructions.

## 9. Assumptions
- Handler `failure_summary.error_type` and `failure_summary.message` are already intended to be sanitized public diagnostics from the orchestrator.
- For missing explicit handler next-step hints, CLI-derived guidance to inspect `--output json` and CloudWatch by `run_id`/stage is safe and actionable.

## 10. Validation Plan
- Run targeted CLI/manual-run regression tests:
  `pytest tests/unit/test_operator_cli_rcp.py tests/api/test_config_init_profiles.py tests/unit/test_config_init_cli.py tests/security/test_config_init_no_aws.py`
- Run broader local test suite if time permits: `pytest`.
