# Test Report

## 1. Execution Summary
- total tests: 11 targeted scheduler diagnostics tests, 4 targeted stage-info tests, 24 phase 3 scheduler/lifecycle regression tests, 329 full pytest tests, and 2 Ruff quality gates
- passed: 11 targeted scheduler diagnostics tests, 4 targeted stage-info tests, 24 phase 3 scheduler/lifecycle regression tests, 329 full pytest tests, and 2 Ruff quality gates
- failed: 0

## 2. Detailed Results
- `git branch --show-current && git status --short`: active branch confirmed as `feature/profile_driven_config_init`; no branch changes performed. Existing working tree had many pre-existing modified/untracked files.
- Code inspection: `src/release_confidence_platform/storage/eventbridge_scheduler_client.py` and `packages/storage/eventbridge_scheduler_client.py` include `provider_message=` from sanitized Scheduler `ClientError.response["Error"]["Message"]` for validation/config errors and construct request shape with only `operation`, `schedule_name`, `group_name`, `schedule_expression`, `schedule_expression_timezone`, `start_date`, `end_date`, `target_arn`, `role_arn`, and `input_keys`.
- `.venv/bin/python -m ruff check .`: PASSED; output `All checks passed!`.
- `.venv/bin/python -m ruff format --check .`: PASSED; output `189 files already formatted`.
- `.venv/bin/python -m pytest tests/unit/test_operator_cli_rcp.py -k 'scheduler_validation_error_includes_sanitized_provider_message_and_request_shape or scheduler_validation_provider_message_redacts_auth_like_content or scheduler_request_shape_exposes_input_keys_only_and_handles_malformed_input or scheduler_config_error_rendering_includes_safe_diagnostics_text_and_json or packages_scheduler_mirror_includes_sanitized_validation_diagnostics or scheduler_client_errors_map_to_actionable_errors or scheduler_param_validation_maps_to_structured_error or scheduler_client_serializes_sanitized_target_input_json or scheduler_client_selects_target_by_schedule_type or schedule_command_rejects_placeholder_scheduler_config_before_factory or schedule_config_error_rendering_points_to_stage_info'`: PASSED; `11 passed, 50 deselected in 0.19s`.
- `.venv/bin/python -m pytest tests/unit/test_config_init_cli.py -k 'stage_info'`: PASSED; `4 passed, 10 deselected in 0.13s`.
- `.venv/bin/python -m pytest tests/integration/test_phase3_scheduling_lifecycle.py tests/integration/test_phase3_scheduled_execution.py tests/integration/test_phase3_cancellation_finalization.py tests/unit/test_phase3_safeguards.py tests/unit/test_phase3_schedule_builders.py tests/unit/test_phase3_lifecycle_state_machine.py`: PASSED; `24 passed in 0.20s`.
- `.venv/bin/python -m pytest`: PASSED; `329 passed in 0.86s`.
- No AWS deployment was performed and no live schedules were created.

## 3. Failed Tests
- None.

## 4. Failure Classification
- No failures observed in this validation cycle.

## 5. Observations
- Functional diagnostics acceptance remains satisfied: sanitized provider message is present, allowlisted request shape is present, raw `Target.Input` values are absent, malformed input is safe, provider auth-like content is redacted, and CLI text/JSON messages preserve safe diagnostics.
- Package mirror diagnostics are also covered by targeted tests.
- No flaky pytest behavior observed in this run.
- Prior Ruff import ordering/format blockers are resolved.

## 6. Regression Check
- Full pytest passed across API, integration, security, and unit suites: `329 passed in 0.86s`.
- Prior scheduler fixes passed through targeted and regression coverage: JSON string target input, structured scheduler errors, placeholder preflight validation, stage-info scheduler fields/env guidance, and lifecycle diagnostics.
- Regression status: no functional regression detected by pytest or Ruff quality gates.

## 7. QA Decision
[QA SIGN-OFF APPROVED]

Reason: Required Ruff quality gates, targeted scheduler diagnostics tests, stage-info/scheduler regression tests, and full pytest all passed. Functional scheduler diagnostics acceptance remains satisfied with no blocking defects or regressions observed.
