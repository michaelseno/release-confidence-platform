# Test Report

## 1. Execution Summary
- total tests: 251 full-suite tests plus 9 focused repeated-stability/scheduling tests
- passed: 260
- failed: 0
- quality gates: Ruff lint passed; Ruff format check passed

## 2. Detailed Results
- Branch verification: `feature/profile_driven_config_init` remained active.
- Canonical key scan: `competing_iterations_key_files= []` for app/config/test code scanned for literal `"iterations"` or `'iterations'` keys.
- Focused repeated tests: `9 passed, 22 deselected in 0.26s`.
- Full pytest regression: `251 passed in 0.83s`.
- Ruff: `All checks passed!` and `188 files already formatted`.

## 3. Failed Tests
None.

## 4. Failure Classification
No failures requiring classification.

## 5. Observations
- Initial Ruff format check reported `tests/unit/test_phase1_core_engine.py` would be reformatted. The test file was formatted with Ruff, then lint and format gates passed.
- No flakiness observed in focused or full-suite execution.
- No AWS deployment or live redeploy validation was performed per instruction.

## 6. Regression Check
Confirmed by full pytest coverage across config-init, audit-create/error handling, stage/config behavior, Lambda packaging-related infrastructure tests, orchestrator observability, S3/DynamoDB diagnostics, static GET duplicate bypass, scheduling, and core engine tests.

Commands executed:
- `git branch --show-current && git status --short`
- `python3.11 -m ruff check . && python3.11 -m ruff format --check .`
- `python3.11 -m ruff format tests/unit/test_phase1_core_engine.py`
- `python3.11 -m pytest tests/unit/test_phase1_core_engine.py -k 'repeated_stability or baseline_health or schedule_validation' tests/integration/test_phase3_scheduled_execution.py -q`
- `python3.11 -m pytest`
- Python static scan for competing `iterations` keys.

## 7. QA Decision
[QA SIGN-OFF APPROVED]
