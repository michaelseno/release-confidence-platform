# Test Plan

## 1. Feature Overview
Validate the HITL scheduler config diagnostics enhancement for `rcp audit schedule` EventBridge Scheduler create failures. Scope covers sanitized `SCHEDULE_CONFIG_ERROR` provider diagnostics, allowlisted create request-shape diagnostics, `Target.Input` non-disclosure, malformed input resilience, CLI text/JSON rendering, and regression coverage for prior scheduler fixes.

## 2. Acceptance Criteria Mapping
- AC1: Validation/config-style Scheduler `ClientError` maps to `SCHEDULE_CONFIG_ERROR` and includes sanitized `ClientError.response["Error"]["Message"]`. Covered by `test_scheduler_validation_error_includes_sanitized_provider_message_and_request_shape` and `test_packages_scheduler_mirror_includes_sanitized_validation_diagnostics`.
- AC2: Request shape contains only allowlisted fields: `operation`, `schedule_name`, `group_name`, `schedule_expression`, `schedule_expression_timezone`, `start_date`, `end_date`, `target_arn`, `role_arn`, and `input_keys`. Covered by scheduler diagnostics request-shape tests and code inspection of `_create_schedule_request_shape`.
- AC3: Raw `Target.Input` JSON and values are never exposed; only top-level `input_keys` are surfaced. Covered by `test_scheduler_validation_error_includes_sanitized_provider_message_and_request_shape` and `test_scheduler_request_shape_exposes_input_keys_only_and_handles_malformed_input`.
- AC4: Malformed `Target.Input` does not crash diagnostics and returns safe empty `input_keys`. Covered by `test_scheduler_request_shape_exposes_input_keys_only_and_handles_malformed_input`.
- AC5: Provider messages redact token/secret/password/api-key/bearer/cookie/auth-like content. Covered by `test_scheduler_validation_provider_message_redacts_auth_like_content`.
- AC6: CLI text and JSON outputs expose safe diagnostic context for operators. Covered by `test_scheduler_config_error_rendering_includes_safe_diagnostics_text_and_json`.
- AC7: Prior scheduler fixes still pass: `Target.Input` JSON string, structured scheduler errors, placeholder validation, stage-info scheduler fields/env guidance, and lifecycle diagnostics. Covered by targeted scheduler tests, stage-info tests, phase 3 lifecycle regressions, and full pytest.
- AC8: Quality gates must pass: `.venv/bin/python -m ruff check .` and `.venv/bin/python -m ruff format --check .`.
- AC9: Full pytest should run if feasible. Covered by `.venv/bin/python -m pytest`.

## 3. Test Scenarios
- Raise Scheduler `ValidationException` during create and validate error code, provider message, and request-shape diagnostic output.
- Verify request-shape JSON key set exactly matches the allowlist and includes `input_keys` only, with no raw `Target.Input` values.
- Verify malformed `Target.Input` is handled without exception and reports `input_keys=[]`.
- Verify auth-like provider details are redacted while non-secret validation context remains visible.
- Verify CLI text and JSON rendering preserve safe diagnostic message context and scheduler next-step guidance.
- Verify package mirror behavior remains aligned with the source scheduler client.
- Verify prior scheduler regressions and lifecycle behavior with local mocked boundaries only.
- Execute static quality gates and full regression suite.

## 4. Edge Cases
- Provider message contains token assignment, bearer token, cookie, API key, and password.
- Target payload contains sensitive values that must not appear in diagnostics.
- Request shape contains optional Scheduler fields that may be absent and should render safely as `null`/`None` in serialized diagnostics.
- Malformed/non-object `Target.Input` must not fail diagnostics.
- Placeholder scheduler config must be rejected before live AWS mutation.

## 5. Test Types Covered
- Unit tests
- Integration tests with mocked/local boundaries
- API/security regression tests through full pytest
- CLI rendering tests
- Static quality gates via Ruff
- Code inspection for allowlist conformance

## 6. Coverage Justification
Coverage directly validates the EventBridge Scheduler wrapper boundary, sanitization logic, CLI error renderer, package mirror, and phase 3 scheduler/lifecycle regression paths. Live AWS validation and live schedule creation were intentionally excluded per instruction.
