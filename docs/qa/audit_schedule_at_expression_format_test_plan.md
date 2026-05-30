# Test Plan

## 1. Feature Overview
Validate the EventBridge Scheduler one-time `at()` expression formatting fix for `rcp audit schedule`. The fix must emit Scheduler expressions exactly as `at(YYYY-MM-DDTHH:MM:SS)`, keep timezone outside the expression via `ScheduleExpressionTimezone`, and preserve prior scheduler diagnostics/sanitization behavior. No AWS deployment or live schedule creation is in scope.

## 2. Acceptance Criteria Mapping
- AC1: All one-time EventBridge Scheduler expressions are formatted as `at(YYYY-MM-DDTHH:MM:SS)`.
- AC2: Fractional seconds are removed from Scheduler expressions.
- AC3: Trailing `Z` and timezone offsets are removed from Scheduler expressions.
- AC4: `ScheduleExpressionTimezone` is set separately when applicable, including UTC and configured non-UTC audit timezones.
- AC5: UTC schedule formatting tests pass.
- AC6: Asia/Hong_Kong schedule formatting tests pass.
- AC7: Burst, repeated, and finalization builders use the dedicated formatter.
- AC8: Scheduler client payload includes `ScheduleExpressionTimezone` when carried on the definition or metadata.
- AC9: Existing scheduler diagnostics and sanitization tests still pass.
- AC10: Prior HITL/scheduler lifecycle regressions still pass where practical without live AWS.
- AC11: Ruff lint/format gates and full pytest pass.

## 3. Test Scenarios
- Inspect source and package mirror builders for dedicated formatter usage in burst, repeated, and finalization schedule definitions.
- Inspect Scheduler client payload construction for `ScheduleExpressionTimezone` propagation and sanitized diagnostics request shape.
- Run targeted builder and operator CLI/Scheduler client unit tests.
- Run targeted phase 3 scheduler/lifecycle/safeguard integration and unit regression tests.
- Run repository-wide pytest regression suite.
- Run Ruff lint and Ruff format check gates.
- Search source, package mirror, and test code for invalid `at(...Z)`, `at(...+00:00)`, or fractional-second `at(...)` literals.

## 4. Edge Cases
- Source timestamp with microseconds and `Z`: `2026-05-30T12:03:37.080790Z`.
- Source timestamp with `Z` and no microseconds.
- Source timestamp with explicit `+00:00` offset.
- Source timestamp with no timezone suffix.
- Configured non-UTC audit timezone: `Asia/Hong_Kong`.
- Finalization audit end timestamp retains internal payload timestamp while expression is provider-formatted.

## 5. Test Types Covered
- Functional: builder output, Scheduler client payload fields.
- Negative/regression: invalid expression literal search and scheduler diagnostics redaction tests.
- Edge case: microseconds, `Z`, offset, and non-UTC timezone formatting.
- Integration: phase 3 scheduling lifecycle and scheduled execution tests.
- Quality gates: Ruff lint and format checks.

## 6. Coverage Justification
The plan directly maps every acceptance criterion to either code inspection, targeted automated tests, repository-wide regression tests, or static invalid-pattern search. Live AWS provider validation is intentionally excluded per constraint and remains a separate HITL activity.
