# Test Report

## 1. Execution Summary
- total tests/checks: 12 targeted scheduler builder tests, 91 targeted scheduler/HITL-adjacent regression tests, 338 full pytest tests, 1 Ruff lint gate, 1 Ruff format gate, static invalid-expression searches, branch verification, and code inspection.
- passed: 12 targeted scheduler builder tests, 91 targeted scheduler/HITL-adjacent regression tests, 338 full pytest tests, Ruff lint gate, Ruff format gate, static invalid-expression searches, branch verification, and code inspection.
- failed: 0.

## 2. Detailed Results
- `git branch --show-current`: PASSED; active branch confirmed as `feature/profile_driven_config_init`; no branch created.
- `git status --short`: observed existing modified/untracked files in the working tree, including this QA report path; QA did not commit, push, or create a PR.
- Code inspection: `src/release_confidence_platform/audit_scheduling/builders.py` and `packages/audit_scheduling/builders.py` define `eventbridge_scheduler_at_datetime(...)`, strip microseconds, format `%Y-%m-%dT%H:%M:%S`, and use it for burst, repeated, and finalization `at(...)` expressions.
- Code inspection: builder metadata and dataclass carry `schedule_expression_timezone`; `_schedule_expression_timezone()` defaults to `UTC` or uses the configured audit window timezone.
- Code inspection: `src/release_confidence_platform/storage/eventbridge_scheduler_client.py` adds `ScheduleExpressionTimezone` to the AWS create payload when present on the definition or metadata, and includes `schedule_expression_timezone` in sanitized request shape diagnostics. Package mirror has matching implementation.
- Static invalid-expression search in `src` and `packages`: PASSED; no invalid `at(...)` literals containing fractional seconds, trailing `Z`, or timezone offsets were found.
- `.venv/bin/python -m ruff check .`: PASSED; output `All checks passed!`.
- `.venv/bin/python -m ruff format --check .`: PASSED; output `189 files already formatted`.
- `.venv/bin/python -m pytest tests/unit/test_phase3_schedule_builders.py -q`: PASSED; `12 passed in 0.03s`.
- `.venv/bin/python -m pytest tests/unit/test_phase3_schedule_builders.py tests/unit/test_operator_cli_rcp.py tests/integration/test_phase3_scheduling_lifecycle.py tests/integration/test_phase3_scheduled_execution.py tests/integration/test_phase3_cancellation_finalization.py tests/unit/test_phase3_safeguards.py -q`: PASSED; `91 passed in 0.35s`.
- `.venv/bin/python -m pytest -q`: PASSED; `338 passed in 0.78s`.
- No deployment was performed and no live EventBridge schedules were created.

## 3. Failed Tests
- None.

## 4. Failure Classification
- No failures to classify.

## 5. Observations
- Functional acceptance for Scheduler expression formatting remains satisfied and is covered by targeted automated tests: UTC microseconds/Z stripping, Asia/Hong_Kong timezone handling, burst expression formatting, finalization expression formatting, and repeated schedule timestamp forms.
- Scheduler client payload coverage passed for timezone propagation from both definition attribute and metadata.
- Existing scheduler diagnostics/sanitization tests passed through `tests/unit/test_operator_cli_rcp.py` and the full pytest run.
- No flaky pytest behavior was observed in this run.
- The prior rejection reason is resolved: Ruff format check now passes with `189 files already formatted`.

## 6. Regression Check
- Full pytest passed across unit, integration, API, and security-style test directories: `338 passed in 0.78s`.
- Prior scheduler/HITL-adjacent regression coverage passed where practical without AWS: lifecycle scheduling, scheduled execution, cancellation/finalization, safeguards, scheduler diagnostics, and sanitization.
- Live HITL validation remains separate and was not executed per instruction.

## 7. QA Decision
[QA SIGN-OFF APPROVED]

Reason: Required Ruff gates, targeted scheduler builder tests, scheduler/HITL-adjacent regression subset, and full pytest all passed. EventBridge Scheduler `at()` expression functional acceptance remains satisfied: expressions are emitted as `at(YYYY-MM-DDTHH:MM:SS)` without fractional seconds, trailing `Z`, or timezone offsets, while timezone is propagated separately through `ScheduleExpressionTimezone`.
