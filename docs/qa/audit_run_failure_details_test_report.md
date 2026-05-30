# Test Report

## 1. Execution Summary
- Total automated tests executed: 289 pytest executions plus 2 Ruff gates.
- Passed: 289 pytest executions plus 2 Ruff gates.
- Failed: 0.
- QA status: approved. Previously blocking Ruff format/lint failures in `manual_run_service.py` are resolved, and functional/regression coverage remains passing.

## 2. Detailed Results
| Command | Result | Evidence |
| --- | --- | --- |
| `git branch --show-current` | Passed | Active branch confirmed: `feature/profile_driven_config_init` |
| `./.venv/bin/python -m ruff check .` | Passed | `All checks passed!` |
| `./.venv/bin/python -m ruff format --check .` | Passed | `186 files already formatted` |
| `./.venv/bin/python -m pytest tests/unit/test_operator_cli_rcp.py::test_manual_run_promotes_safe_handler_failure_details tests/unit/test_operator_cli_rcp.py::test_cli_run_result_distinguishes_handler_failure_from_invoke_acceptance tests/unit/test_operator_cli_rcp.py::test_audit_run_failure_text_renders_actionable_handler_details tests/unit/test_operator_cli_rcp.py::test_audit_run_failure_json_includes_structured_details_without_secret_leak tests/unit/test_operator_cli_rcp.py::test_audit_run_success_text_remains_without_failure_fields` | Passed | `5 passed in 0.19s` |
| `./.venv/bin/python -m pytest tests/unit/test_operator_cli_rcp.py tests/security/test_phase1_qa_contracts.py tests/api/test_config_init_profiles.py tests/unit/test_config_init_cli.py tests/security/test_config_init_no_aws.py` | Passed | `82 passed in 0.38s` |
| `./.venv/bin/python -m pytest` | Passed | `202 passed in 0.74s` |

## 3. Failed Tests
None.

## 4. Failure Classification
No failures to classify in this rerun.

## 5. Observations
- Functional acceptance coverage for the bug fix is present and passed in the focused audit-run failure-details suite.
- Quality gates now pass using the requested repository virtualenv commands.
- Full pytest passed with 202 tests, including prior HITL regression coverage for config-init, storage guidance, Lambda diagnostics, and orchestrator contracts.
- No flaky tests were observed in this execution.
- Live AWS `rcp audit run --scenario-type repeated_stability` was not executed during this local QA pass.

## 6. Regression Check
- Focused audit-run failure-details command passed: `5 passed in 0.19s`.
- Focused HITL regression command passed: `82 passed in 0.38s`.
- Full pytest regression suite passed: `202 passed in 0.74s`.
- Success-path rendering regression is covered by `test_audit_run_success_text_remains_without_failure_fields` within the passing focused suite.

## 7. QA Decision
[QA SIGN-OFF APPROVED]

Reason: requested Ruff lint/format gates, focused audit-run failure details coverage, focused HITL regression coverage, and full pytest regression suite all passed with no unresolved failures or observed regressions.
