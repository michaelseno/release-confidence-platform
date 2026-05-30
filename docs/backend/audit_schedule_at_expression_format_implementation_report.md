# Implementation Report

## 1. Summary of Changes
Implemented valid EventBridge Scheduler `at()` expression formatting for audit one-time schedules. Burst, repeated, and finalization schedule definitions now emit `at(YYYY-MM-DDTHH:MM:SS)` without fractional seconds, `Z`, or offsets, while carrying timezone separately for AWS Scheduler.

## 2. Files Modified
- `packages/audit_scheduling/builders.py`: added Scheduler `at()` formatter, schedule timezone metadata, and updated burst/repeated/finalization expressions.
- `src/release_confidence_platform/audit_scheduling/builders.py`: mirrored scheduling changes.
- `packages/storage/eventbridge_scheduler_client.py`: sends `ScheduleExpressionTimezone` when present on a definition or metadata.
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py`: mirrored scheduler client change.
- `tests/unit/test_phase3_schedule_builders.py`: added UTC, Asia/Hong_Kong, finalization, burst, and repeated expression formatting coverage.
- `tests/unit/test_operator_cli_rcp.py`: updated invalid `at(...Z)` fixture and added Scheduler timezone payload coverage.
- `docs/backend/audit_schedule_at_expression_format_implementation_plan.md`: implementation plan.
- `docs/backend/audit_schedule_at_expression_format_implementation_report.md`: this report.

## 3. API Contract Implementation
No public API changed. Internal schedule definitions now optionally expose `schedule_expression_timezone`; EventBridge Scheduler create payloads include AWS `ScheduleExpressionTimezone` when set.

## 4. Data / Persistence Implementation
No storage schema changes. Schedule metadata includes `schedule_expression_timezone` for planned/created one-time schedule metadata.

## 5. Key Logic Implemented
- Added a dedicated formatter that strips microseconds and omits timezone suffixes from Scheduler `at()` timestamps.
- Burst, repeated, and finalization expressions use the formatter only for provider expressions.
- Target payload fields such as `scheduled_at`, `burst.window_start`, `burst.window_end`, and `audit_window_end` remain unchanged.
- One-time schedules use audit window timezone when configured, otherwise `UTC`, as separate Scheduler timezone metadata.

## 6. Security / Authorization Implemented
No auth changes. Existing target input sanitization remains in place. No secrets or raw target payloads are logged by the change.

## 7. Error Handling Implemented
Existing datetime parsing validation remains in force for invalid schedule timestamps. Scheduler provider errors continue through the existing sanitized `StorageError` mapping.

## 8. Observability / Logging
Existing Scheduler diagnostics now include `schedule_expression_timezone` in request shape when present. No new logging was added.

## 9. Assumptions Made
- Explicit `ScheduleExpressionTimezone="UTC"` is safe and desirable for UTC one-time schedules; configured audit window timezones such as `Asia/Hong_Kong` are set explicitly.
- Internal/audit evidence timestamps should not be reformatted as part of the provider-expression fix.

## 10. Validation Performed
- `.venv/bin/python -m pytest tests/unit/test_phase3_schedule_builders.py tests/unit/test_operator_cli_rcp.py -q` → `74 passed`.
- `.venv/bin/python -m ruff check packages/audit_scheduling/builders.py src/release_confidence_platform/audit_scheduling/builders.py packages/storage/eventbridge_scheduler_client.py src/release_confidence_platform/storage/eventbridge_scheduler_client.py tests/unit/test_phase3_schedule_builders.py tests/unit/test_operator_cli_rcp.py` → `All checks passed!`.
- Combined rerun of the ruff command above plus `.venv/bin/python -m pytest tests/unit/test_phase3_schedule_builders.py tests/unit/test_operator_cli_rcp.py -q` → `All checks passed!`; `74 passed`.
- `.venv/bin/python -m pytest tests/integration/test_phase3_scheduling_lifecycle.py tests/integration/test_phase3_scheduled_execution.py -q` → `7 passed`.

## 11. Known Limitations / Follow-Ups
- No live EventBridge validation was performed per constraint. HITL/live validation should retry `rcp audit schedule` against EventBridge Scheduler to confirm provider acceptance.

## 12. Commit Status
No commit created per user constraint.
