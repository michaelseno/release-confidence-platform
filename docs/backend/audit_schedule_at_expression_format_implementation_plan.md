# Implementation Plan

## 1. Feature Overview
Fix EventBridge Scheduler one-time `at()` schedule expression formatting for audit scheduling so provider expressions use `at(YYYY-MM-DDTHH:MM:SS)` without fractional seconds or timezone suffixes.

## 2. Technical Scope
- Add a dedicated Scheduler `at()` datetime formatter in both scheduling mirrors.
- Use the formatter for burst, repeated, and finalization schedule definition expressions only.
- Carry optional `schedule_expression_timezone` metadata on schedule definitions.
- Send AWS `ScheduleExpressionTimezone` from EventBridge Scheduler client mirrors when present.
- Preserve existing internal scheduler target payload timestamps.

## 3. Source Inputs
- `docs/architecture/phase_3_audit_scheduling_lifecycle_technical_design.md`
- `docs/bugs/audit_schedule_at_expression_format_bug_report.md`
- Existing schedule builder and EventBridge Scheduler client tests.

## 4. API Contracts Affected
No public API contract changes. Internal EventBridge Scheduler definitions now carry optional `schedule_expression_timezone`; AWS create-schedule payloads include `ScheduleExpressionTimezone` when supplied.

## 5. Data Models / Storage Affected
No data model or storage changes. Schedule metadata may include `schedule_expression_timezone` for created/planned schedules.

## 6. Files Expected to Change
- `packages/audit_scheduling/builders.py`
- `src/release_confidence_platform/audit_scheduling/builders.py`
- `packages/storage/eventbridge_scheduler_client.py`
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py`
- `tests/unit/test_phase3_schedule_builders.py`
- `tests/unit/test_operator_cli_rcp.py`
- `docs/backend/audit_schedule_at_expression_format_implementation_report.md`

## 7. Security / Authorization Considerations
No authentication or authorization behavior changes. Target payload sanitization remains unchanged. The fix avoids leaking timezone suffixes into provider expressions but preserves audit evidence timestamps in target payloads.

## 8. Dependencies / Constraints
No new dependencies. Uses Python standard-library `datetime` and `zoneinfo`. No live schedules, deployment, commit, push, or PR are in scope for this HITL correction.

## 9. Assumptions
- For one-time schedules, explicit Scheduler timezone should be set to the audit window timezone when configured, otherwise `UTC`.
- Existing target payload timestamps remain the audit/runtime evidence contract and should not be changed solely for provider expression syntax.

## 10. Validation Plan
- `.venv/bin/python -m pytest tests/unit/test_phase3_schedule_builders.py tests/unit/test_operator_cli_rcp.py -q`
- `.venv/bin/python -m ruff check packages/audit_scheduling/builders.py src/release_confidence_platform/audit_scheduling/builders.py packages/storage/eventbridge_scheduler_client.py src/release_confidence_platform/storage/eventbridge_scheduler_client.py tests/unit/test_phase3_schedule_builders.py tests/unit/test_operator_cli_rcp.py`
