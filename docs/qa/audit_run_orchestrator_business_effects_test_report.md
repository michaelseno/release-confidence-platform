# Test Report

## 1. Execution Summary

- total tests: 198 full regression tests plus focused targeted reruns
- passed: 198 full regression tests; 63 targeted orchestrator/no-business-effects tests; 90 focused HITL regression tests
- failed: 0
- quality gates: Ruff lint passed; Ruff format check passed

## 2. Detailed Results

| Validation | Evidence | Outcome |
| --- | --- | --- |
| Active branch preserved | `git branch --show-current` returned `feature/profile_driven_config_init` | Pass |
| Ruff lint quality gate | `./.venv/bin/python -m ruff check .` => `All checks passed!` | Pass |
| Ruff format quality gate | `./.venv/bin/python -m ruff format --check .` => `186 files already formatted` | Pass |
| Targeted orchestrator/no-business-effects tests | `./.venv/bin/python -m pytest tests/unit/test_phase1_core_engine.py tests/unit/test_operator_cli_rcp.py tests/unit/test_infra_configuration.py tests/integration/test_phase1_orchestrator_integration.py tests/integration/test_phase2_orchestrator_payloads.py` => `63 passed in 0.32s` | Pass |
| Focused HITL regression tests | `./.venv/bin/python -m pytest tests/api/test_config_init_profiles.py tests/unit/test_config_init_cli.py tests/security/test_config_init_no_aws.py tests/api/test_dynamodb_storage_error_guidance.py tests/api/test_s3_storage_error_guidance.py tests/unit/test_operator_cli_rcp.py tests/unit/test_infra_configuration.py` => `90 passed in 0.43s` | Pass |
| Full pytest regression suite | `./.venv/bin/python -m pytest` => `198 passed in 0.61s` | Pass |
| Prior functional acceptance | Handler mapping, first-line sanitized logging, manual payload contract, direct/EventBridge manual event acceptance without `schedule_occurrence_id`, sanitized failure response/logging, Lambda invoke-vs-handler-result distinction, and packaging static checks remain covered by passing targeted and full suites | Pass |

## 3. Failed Tests

None.

## 4. Failure Classification

No failures observed. Previous Ruff `I001` import-order blockers are resolved by the current rerun evidence.

## 5. Observations

- No flaky behavior observed across the targeted, HITL-focused, and full regression reruns.
- Validation remained local/unit/static; no AWS deployment or live CloudWatch/S3/DynamoDB verification was performed.
- Local Lambda package artifact inspection was not performed; packaging confidence remains based on static infra tests and full regression coverage.

## 6. Regression Check

Confirmed unchanged behaviors through full pytest and targeted/focused reruns:

- Orchestrator handler invocation and manual run contracts remain passing.
- Enhanced `rcp config init` default profile behavior remains passing.
- AWS/profile/storage error guidance regressions remain passing.
- Prior Lambda dependency packaging/static infrastructure checks remain passing.
- Phase 1/2/3 core regression suites remain passing.

## 7. QA Decision

Approved. All requested quality gates and regression suites pass, and prior functional acceptance for the orchestrator no-business-effects fix remains satisfied.
