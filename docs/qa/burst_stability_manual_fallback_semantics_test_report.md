# Test Report

## 1. Execution Summary

- Total tests executed: 314 full pytest tests, 8 targeted pytest tests, plus 2 Ruff quality gates
- Passed: 314 full pytest tests, 8 targeted pytest tests, Ruff lint, Ruff format
- Failed: 0 unresolved product or quality-gate failures
- Overall result: **Approved**

## 2. Detailed Results

| Check | Command | Outcome | Evidence |
| --- | --- | --- | --- |
| Branch/status verification | `git branch --show-current && git status --short` | Passed | Active branch remained `feature/profile_driven_config_init`; no branch, commit, push, or PR action performed |
| Ruff lint | `python3.11 -m ruff check .` | Passed | `All checks passed!` |
| Ruff format | `python3.11 -m ruff format --check .` | Passed | `189 files already formatted` |
| Targeted manual burst fallback tests | `python3.11 -m pytest tests/unit/test_phase1_core_engine.py::test_manual_burst_without_windows_uses_fallback_defaults_and_raw_evidence tests/unit/test_phase1_core_engine.py::test_manual_burst_caps_lower_than_defaults_clamp_effective_values tests/unit/test_phase1_core_engine.py::test_scheduled_burst_uses_window_metadata_and_ignores_manual_defaults tests/unit/test_phase1_core_engine.py::test_scheduled_burst_without_enabled_window_fails_before_outbound_requests tests/unit/test_phase1_core_engine.py::test_burst_request_count_is_total_and_endpoints_are_round_robin tests/unit/test_phase1_core_engine.py::test_burst_concurrency_is_global_cap tests/unit/test_config_init_generation.py::test_generators_emit_safe_defaults_and_no_secret_material tests/api/test_config_init_profiles.py::test_minimal_dev_generation_structure_validation_and_empty_endpoints` | Passed | `8 passed in 0.28s` |
| Full regression suite | `python3.11 -m pytest` | Passed | `314 passed in 0.79s` |

## 3. Failed Tests

No unresolved failures.

Note: an initial targeted pytest invocation used two stale node IDs and produced collection errors before execution. The selector issue was corrected immediately, and the intended targeted coverage passed (`8 passed`). This is classified as a resolved QA command-selection issue, not an application defect.

## 4. Failure Classification

- Application Bug: none
- Environment Issue: none
- Flaky Test: none observed
- Test Bug: resolved stale targeted node IDs in the first targeted invocation; corrected node IDs passed and full regression suite passed.

## 5. Observations

- Dev-backend's Ruff formatting change resolved the prior blocking format failure in `apps/backend/orchestrator/service.py`.
- Manual burst fallback acceptance remains satisfied: fallback defaults are used, effective caps clamp manual defaults, raw burst evidence contains expected metadata, scheduled burst remains strict, total request count is distributed round-robin, and concurrency is enforced globally.
- Config-init default burst profile coverage remains passing.
- No AWS deployment or live redeploy was performed.
- No flaky pytest behavior observed.

## 6. Regression Check

Confirmed via full pytest run:

- Config-init/profile behavior remains passing.
- Audit run/orchestrator observability remains passing.
- S3 and DynamoDB diagnostics tests remain passing.
- Static GET duplicate bypass regression tests remain passing.
- Repeated iteration metadata tests remain passing.
- Expected status code precedence tests remain passing.
- Lambda/serverless packaging configuration tests remain passing.
- Phase 1 core engine, Phase 2 payload generation, and Phase 3 scheduling safeguards remain passing.

## 7. QA Decision

[QA SIGN-OFF APPROVED]

All required quality gates, targeted manual burst fallback tests, and full pytest regression tests passed with evidence.
