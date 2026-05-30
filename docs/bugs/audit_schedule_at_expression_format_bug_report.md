# Bug Report

## 1. Summary
HITL validation for `rcp audit schedule` reports AWS EventBridge Scheduler rejecting one-time `at()` schedules such as `at(2026-05-30T12:03:37.080790Z)`. The schedule builders currently emit UTC ISO strings with fractional seconds and a trailing `Z` into `at()` expressions, but EventBridge Scheduler expects `at(YYYY-MM-DDTHH:MM:SS)` with timezone supplied separately via `ScheduleExpressionTimezone` when needed.

## 2. Investigation Context
- source of report: HITL validation / live provider error
- related feature or workflow: `rcp audit schedule` schedule creation on branch `feature/profile_driven_config_init`
- current branch remains the active HITL correction branch; no new branch should be created
- reported provider error: `Invalid Schedule Expression at(2026-05-30T12:03:37.080790Z)`
- required valid expression: `at(2026-05-30T12:03:37)`
- required behavior: remove fractional seconds, remove trailing `Z`, and set `ScheduleExpressionTimezone` separately when needed

## 3. Observed Symptoms
- Failing workflow: live EventBridge Scheduler `create_schedule` during `rcp audit schedule`.
- Exact provider error reported by user: `Invalid Schedule Expression at(2026-05-30T12:03:37.080790Z)`.
- Actual malformed expression contains:
  - fractional seconds: `.080790`
  - UTC suffix inside `at()`: `Z`
- Expected expression format: `at(YYYY-MM-DDTHH:MM:SS)`, e.g. `at(2026-05-30T12:03:37)`.
- Expected timezone handling: timezone should be sent as `ScheduleExpressionTimezone` outside the expression, not embedded as `Z` in the `at()` timestamp.

## 4. Evidence Collected
Files inspected:
- `src/release_confidence_platform/audit_scheduling/builders.py`
- `src/release_confidence_platform/audit_scheduling/safeguards.py`
- `src/release_confidence_platform/audit_scheduling/service.py`
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py`
- `packages/audit_scheduling/builders.py`
- `packages/audit_scheduling/safeguards.py`
- `packages/storage/eventbridge_scheduler_client.py`
- `tests/unit/test_phase3_schedule_builders.py`
- `tests/unit/test_operator_cli_rcp.py`

Key code evidence:
- `src/release_confidence_platform/audit_scheduling/safeguards.py:36-37` defines `isoformat_z(value)` as `value.astimezone(UTC).isoformat().replace("+00:00", "Z")`. `datetime.isoformat()` preserves microseconds when present, which can produce strings like `2026-05-30T12:03:37.080790Z`.
- `src/release_confidence_platform/audit_scheduling/safeguards.py:108-133` uses `datetime.now(UTC)` as the default audit start when no `start_time` is supplied, then returns `start_time` and `end_time` using `isoformat_z()`. This is the direct path for a generated current-time audit window containing microseconds.
- `src/release_confidence_platform/audit_scheduling/builders.py:168` emits burst one-time schedules as `f"at({isoformat_z(start)})"`.
- `src/release_confidence_platform/audit_scheduling/builders.py:181-204` emits repeated one-time schedules as `f"at({scheduled_at})"`, where `scheduled_at` defaults to `audit_window["start_time"]`.
- `src/release_confidence_platform/audit_scheduling/builders.py:228-232` emits finalization one-time schedules as `f"at({audit_window['end_time']})"`.
- `packages/audit_scheduling/builders.py:165`, `:178-201`, and `:225-229` contain the same burst/repeated/finalization expression generation in the packages mirror.
- `packages/audit_scheduling/safeguards.py:36-37` contains the same `isoformat_z()` implementation.
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py:39-44` creates the AWS payload with only `Name`, `ScheduleExpression`, and `FlexibleTimeWindow`; no `ScheduleExpressionTimezone` is set.
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py:185-193` includes `ScheduleExpressionTimezone` in diagnostics, but that field is absent from the actual payload unless another layer adds it, which current code does not.
- `tests/unit/test_phase3_schedule_builders.py:41-48` checks baseline rate schedules only; `tests/unit/test_phase3_schedule_builders.py:50-64` checks burst payload window formatting but does not assert the EventBridge `at()` expression format.
- `tests/unit/test_operator_cli_rcp.py:621-625` still uses a test definition expression of `at(2026-01-01T00:00:00Z)`, which reflects the invalid suffix pattern and does not guard against this provider rejection.

## 5. Execution Path / Failure Trace
1. `rcp audit schedule` loads and normalizes audit config in `AuditSchedulingService.schedule_from_persisted_audit()` or schedules directly through `AuditSchedulingService.schedule_audit()`.
2. `validate_audit_window()` returns normalized `audit_window["start_time"]` and `audit_window["end_time"]` using `isoformat_z()`.
3. If no explicit audit start/end is supplied, `validate_audit_window()` starts from `datetime.now(UTC)`, so microseconds are preserved by `datetime.isoformat()`.
4. `ScheduleBuilder.build_all()` creates one-time schedule definitions for burst, repeated, and finalization schedules.
5. One-time definitions embed the ISO string directly in `at(...)`:
   - burst: `at({isoformat_z(start)})`
   - repeated: `at({scheduled_at})`
   - finalization: `at({audit_window['end_time']})`
6. `EventBridgeSchedulerClient.create_schedule()` sends `definition.expression` as `ScheduleExpression` without setting `ScheduleExpressionTimezone`.
7. AWS EventBridge Scheduler rejects expressions like `at(2026-05-30T12:03:37.080790Z)` as invalid.

## 6. Failure Classification
- Primary classification: Application Bug
- Severity: Blocker

Justification: HITL validation is blocked by live provider rejection of scheduler creation. The defect prevents `rcp audit schedule` from creating one-time EventBridge Scheduler schedules when generated timestamps include fractional seconds and/or a trailing `Z`.

## 7. Root Cause Analysis
Root cause confidence: Confirmed Root Cause

Immediate failure point:
- EventBridge Scheduler rejects `ScheduleExpression` values that embed UTC ISO-8601 strings with microseconds and `Z` inside `at()`.

Underlying root cause:
- The one-time schedule builders reuse internal UTC/audit-window ISO strings directly as EventBridge `at()` expressions instead of formatting them to Scheduler's required wall-clock expression format. The storage client also lacks a way to send `ScheduleExpressionTimezone` from the schedule definition.

Supporting evidence:
- `isoformat_z()` explicitly adds `Z` and preserves microseconds via `datetime.isoformat()`.
- `validate_audit_window()` can source times from `datetime.now(UTC)`, which commonly contains microseconds.
- `build_burst()`, `build_repeated()`, and `build_finalization()` place those strings directly inside `at(...)`.
- `EventBridgeSchedulerClient.create_schedule()` does not include `ScheduleExpressionTimezone` in the payload.

Plausible contributing factors:
- Existing tests assert payload timestamps but not Scheduler expression syntax.
- Existing tests contain `at(...Z)` fixtures, so the invalid expression pattern was not caught.
- The code keeps internal event payload timestamps and provider schedule expression timestamps coupled, although they have different formatting requirements.

## 8. Confidence Level
High. The reported invalid expression exactly matches the builder output path: `datetime.now(UTC)`/`isoformat_z()` can produce `.080790Z`, and the builders embed that value directly in `at()` expressions. The AWS payload currently has no separate timezone field.

## 9. Recommended Fix
Likely owner: backend/full-stack scheduling owner.

Recommended implementation scope:
- Update both mirrors unless the project confirms only one import surface is active:
  - `src/release_confidence_platform/audit_scheduling/builders.py`
  - `packages/audit_scheduling/builders.py`
  - `src/release_confidence_platform/storage/eventbridge_scheduler_client.py`
  - `packages/storage/eventbridge_scheduler_client.py`
  - tests in `tests/unit/test_phase3_schedule_builders.py` and relevant Scheduler client tests in `tests/unit/test_operator_cli_rcp.py`

Concrete fix approach:
1. Add a dedicated formatter for EventBridge one-time `at()` expressions, e.g. `scheduler_at_expression_time(...)`, that returns exactly `%Y-%m-%dT%H:%M:%S` with no fractional seconds and no offset/Z suffix.
2. Do not change internal event payload timestamps solely to satisfy Scheduler syntax. Payload fields like `scheduled_at`, `window_start`, `window_end`, and `audit_window_end` may continue using internal UTC ISO format if that is the existing contract; only `ScheduleDefinition.expression` needs Scheduler syntax.
3. In `ScheduleBuilder.build_burst()`, use the new formatter for `definition.expression` instead of `isoformat_z(start)` inside `at(...)`.
4. In `ScheduleBuilder.build_repeated()`, parse/normalize `scheduled_at` and format only the expression with the new formatter.
5. In `ScheduleBuilder.build_finalization()`, parse/normalize `audit_window["end_time"]` and format only the expression with the new formatter.
6. Extend `ScheduleDefinition` to carry an optional expression timezone, or add metadata accepted by `EventBridgeSchedulerClient.create_schedule()`, so the client can set `payload["ScheduleExpressionTimezone"]` when needed.
7. For UTC schedules, send `ScheduleExpressionTimezone="UTC"` if the product requirement expects explicit timezone for one-time schedules; otherwise at minimum ensure non-UTC schedules such as `Asia/Hong_Kong` are sent separately as `ScheduleExpressionTimezone="Asia/Hong_Kong"`.
8. Keep timezone conversion semantics explicit: if `audit_window["timezone"]` is present and the configured one-time time is intended as local wall time, format the local wall-clock time and send that timezone; if the stored audit window remains UTC, convert to the selected timezone before formatting the expression.

Cautions/constraints:
- Do not append `Z`, `+00:00`, or any timezone offset inside `at()`.
- Do not include microseconds in `at()` even when source datetimes contain them.
- Keep source and packages mirrors in parity.
- Preserve Scheduler diagnostics and sanitization behavior added for provider validation errors.

## 10. Suggested Validation Steps
Targeted unit tests needed:
- UTC schedule formatting: source timestamp `2026-05-30T12:03:37.080790Z` produces `ScheduleExpression == "at(2026-05-30T12:03:37)"` and no `.080790` or `Z` appears inside the expression.
- Asia/Hong_Kong schedule formatting: configured timezone `Asia/Hong_Kong` produces an `at(YYYY-MM-DDTHH:MM:SS)` expression with no suffix and sets `ScheduleExpressionTimezone == "Asia/Hong_Kong"` in the AWS create payload.
- Finalization schedule: `build_finalization()` formats `audit_window["end_time"]` without fractional seconds or `Z`.
- Burst schedule: `build_burst()` formats the start expression without fractional seconds or `Z` while preserving existing payload `burst.window_start/window_end` contract if required.
- Repeated schedule: explicit `repeated["schedule_time"]` values with `.ffffffZ`, `Z`, `+00:00`, and no timezone all produce valid Scheduler expression strings.
- Scheduler client payload test: `EventBridgeSchedulerClient.create_schedule()` includes `ScheduleExpressionTimezone` when the definition carries one and leaves it out only when intentionally absent.

Regression checks:
- Existing lifecycle scheduling tests still pass.
- Existing provider diagnostics tests still include request shape and redact sensitive values.
- No test fixture should continue to assert or rely on `at(...Z)` expressions.

## 11. Open Questions / Missing Evidence
- The exact config that produced `2026-05-30T12:03:37.080790Z` was not provided, but the `validate_audit_window()` default `datetime.now(UTC)` path directly explains fractional seconds.
- Product semantics should confirm whether one-time schedules should always send `ScheduleExpressionTimezone="UTC"` or only when the configured timezone is non-UTC. The user requirement says set it separately when needed and explicitly asks for UTC and Asia/Hong_Kong tests.
- The desired local-time conversion behavior for `Asia/Hong_Kong` should be made explicit in tests: either convert UTC audit boundaries to Hong Kong wall time before formatting, or format already-local configured times unchanged while sending `ScheduleExpressionTimezone`.

## 12. Final Investigator Decision
Ready for developer fix.
