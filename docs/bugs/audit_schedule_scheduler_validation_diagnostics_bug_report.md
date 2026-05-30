# Bug Report

## 1. Summary
HITL validation reports that `audit schedule` failures caused by EventBridge Scheduler `ValidationException` are not actionable. The CLI currently surfaces only `aws_error_code=ValidationException` for `SCHEDULE_CONFIG_ERROR`, while suppressing the sanitized AWS validation message and the sanitized create request shape needed to identify malformed schedule fields.

## 2. Investigation Context
- source of report: HITL validation / user runtime report
- related feature or workflow: Phase 3 audit scheduling lifecycle diagnostics
- branch context: `feature/profile_driven_config_init` remains the active HITL correction branch
- relevant command/workflow: `rcp audit schedule ...` when `EventBridgeSchedulerClient.create_schedule()` calls EventBridge Scheduler `create_schedule`
- current observed CLI output per user: scheduler config errors only show `aws_error_code=ValidationException`
- expected diagnostic improvement: include sanitized `ClientError.response["Error"]["Message"]` and sanitized create request shape fields for `SCHEDULE_CONFIG_ERROR`

## 3. Observed Symptoms
- Failing workflow: live scheduler create during `audit schedule`.
- Exact reported current message: only `aws_error_code=ValidationException` is visible for Scheduler config errors.
- Expected behavior: `SCHEDULE_CONFIG_ERROR` should identify the provider validation reason, e.g. invalid `ScheduleExpression`, invalid `ScheduleExpressionTimezone`, missing `FlexibleTimeWindow`, invalid `Target.Input` JSON string, invalid/past `StartDate`/`EndDate`, or overlong generated schedule name.
- Actual behavior in code: Scheduler `ClientError` messages are intentionally not copied into the project error message. The only provider detail retained for validation-style failures is `aws_error_code`.

Relevant failure mapping excerpt:

```py
# src/release_confidence_platform/storage/eventbridge_scheduler_client.py
if aws_code in {"ValidationException", "InvalidParameterValue", "ConflictException"}:
    raise StorageError(
        "EventBridge Scheduler rejected the request; verify scheduler stage configuration "
        f"(operation={operation}, aws_error_code={aws_code})",
        "SCHEDULE_CONFIG_ERROR",
    ) from exc
```

## 4. Evidence Collected
Files inspected:
- `src/release_confidence_platform/storage/eventbridge_scheduler_client.py`
- `packages/storage/eventbridge_scheduler_client.py`
- `src/release_confidence_platform/operator_cli/result.py`
- `packages/operator_cli/result.py`
- `src/release_confidence_platform/operator_cli/main.py`
- `src/release_confidence_platform/sanitization/sanitizer.py`
- `src/release_confidence_platform/audit_scheduling/builders.py`
- `tests/unit/test_operator_cli_rcp.py`
- `docs/backend/audit_schedule_scheduler_error_handling_implementation_report.md`
- `docs/qa/audit_schedule_scheduler_error_handling_test_report.md`

Key findings:
- `src/.../storage/eventbridge_scheduler_client.py:31-47` and `packages/.../storage/eventbridge_scheduler_client.py:31-47` build the create payload with `Name`, `ScheduleExpression`, `FlexibleTimeWindow`, optional `GroupName`, and optional `Target` containing `Arn`, `RoleArn`, and JSON serialized sanitized `Input`.
- `src/.../storage/eventbridge_scheduler_client.py:51-52` catches `ClientError` and calls `_raise_scheduler_error("create_schedule", exc, ...)` without passing the payload/request shape.
- `src/.../storage/eventbridge_scheduler_client.py:107-126` and the packages mirror extract only `Error.Code`; `Error.Message` is suppressed for all mapped Scheduler `ClientError`s.
- `docs/backend/audit_schedule_scheduler_error_handling_implementation_report.md:28-35` confirms this was intentional in the prior implementation: provider messages were not copied and no logging was added.
- `tests/unit/test_operator_cli_rcp.py:701-732` only asserts that provider messages like `token=secret` do not leak and that `aws_error_code` is present; no test requires a sanitized provider message or create request shape.
- `src/.../operator_cli/result.py:332-348` renders only the sanitized `EngineError.message` plus generic next steps. Therefore any Scheduler-specific detail must be included in the raised `StorageError.message` or added to the error payload contract before `render_error()` is called.
- `packages/operator_cli/result.py:67-97` is not in parity with the src CLI renderer and has only a generic next step, so any mirrored CLI behavior may also need update if packages are still used by tests/runtime.
- `src/.../sanitization/sanitizer.py:77-90` recursively redacts sensitive keys and common token/PII patterns, but the safer request-shape requirement is to avoid raw `Target.Input` values entirely and expose only input keys.
- `src/.../audit_scheduling/builders.py:30` enforces AWS Scheduler name max length at 64 and `schedule_name()` hashes/truncates long generated names, so overlong name should normally be prevented unless a custom path or future change bypasses this builder.

## 5. Execution Path / Failure Trace
1. `rcp audit schedule` dispatches through `src/release_confidence_platform/operator_cli/main.py:149-150` into scheduling services.
2. Scheduling service builds `ScheduleDefinition` objects via `ScheduleBuilder` and calls `scheduler_client.create_schedule(definition)`.
3. `EventBridgeSchedulerClient.create_schedule()` builds the EventBridge Scheduler payload and calls `self._call("create_schedule", **payload)`.
4. AWS rejects the create request with `ClientError`/`ValidationException`.
5. `_raise_scheduler_error()` maps `ValidationException` to `SCHEDULE_CONFIG_ERROR` but only includes `operation` and `aws_error_code` in the error message.
6. CLI `main()` catches `EngineError` and `render_error()` prints the sanitized message, so the operator sees `aws_error_code=ValidationException` without the actionable AWS message or create request shape.

## 6. Failure Classification
- Primary classification: Application Bug
- Severity: High

Justification: This blocks HITL diagnosis of live scheduler creation failures. The scheduling core can fail for multiple configuration/request-shape reasons, and the current diagnostic omits the only field (`ClientError.response["Error"]["Message"]`) that usually identifies which request field was rejected.

## 7. Root Cause Analysis
Root cause confidence: Confirmed Root Cause

Immediate failure point:
- `_raise_scheduler_error()` maps `ValidationException` to `SCHEDULE_CONFIG_ERROR` without including the sanitized provider message or request shape.

Underlying root cause:
- The Scheduler client error boundary intentionally suppresses `ClientError.response["Error"]["Message"]` and is not passed the create payload, so it cannot include sanitized request-shape context. CLI rendering only displays the resulting `EngineError.message`, making the suppression visible to operators.

Supporting evidence:
- `src/.../storage/eventbridge_scheduler_client.py:107-126` extracts `aws_code` only and ignores `Error.Message`.
- `src/.../storage/eventbridge_scheduler_client.py:51-52` discards local `payload` context when calling `_raise_scheduler_error()`.
- Prior implementation report states: “Provider messages are not copied into scheduler error messages; only operation names and AWS error codes are included.”

Contributing factors:
- Current tests enforce non-leakage of raw provider messages but do not verify sanitized provider messages or safe create request shape diagnostics.
- Packages mirror has the same Scheduler client suppression and a less detailed CLI renderer than src.

## 8. Confidence Level
High. The reported symptom exactly matches the Scheduler error mapping in both src and packages mirrors, and the rendering path confirms no later layer can add the missing AWS message/request shape because it is never propagated.

## 9. Recommended Fix
Likely owner: backend/full-stack CLI owner.

Recommended implementation scope:
- Update both mirrors:
  - `src/release_confidence_platform/storage/eventbridge_scheduler_client.py`
  - `packages/storage/eventbridge_scheduler_client.py`
  - CLI rendering/tests in `src/release_confidence_platform/operator_cli/result.py`, `packages/operator_cli/result.py` if packages remains supported, and `tests/unit/test_operator_cli_rcp.py`.

Concrete fix approach:
1. In `create_schedule()`, build a safe diagnostic shape before calling AWS and pass it into `_raise_scheduler_error()` on exceptions.
2. Extend `_raise_scheduler_error(operation, exc, default_message, request_shape=None)` to include, for validation/config-style `ClientError`s, a sanitized provider message from `exc.response.get("Error", {}).get("Message")`.
3. Use the central `sanitize()` function on the provider message, but do not include raw AWS exception objects or raw payload values.
4. Add a helper such as `_create_schedule_request_shape(payload)` that returns only approved fields:
   - `operation=create_schedule`
   - `schedule_name` from `payload["Name"]`
   - `group_name` from `payload.get("GroupName")`
   - `schedule_expression` from `payload.get("ScheduleExpression")`
   - `schedule_expression_timezone` from `payload.get("ScheduleExpressionTimezone")`
   - `start_date` from `payload.get("StartDate")`
   - `end_date` from `payload.get("EndDate")`
   - `target_arn` from `payload.get("Target", {}).get("Arn")`
   - `role_arn` from `payload.get("Target", {}).get("RoleArn")`
   - `input_keys` from parsed `Target.Input` JSON object keys only, sorted for stable output; use `[]` or `None` if absent/unparseable, never values.
5. Include the safe shape in the `StorageError.message` in a structured, grep-friendly format or JSON fragment after sanitization. If CLI error payloads are expanded instead, ensure text and JSON outputs both expose the same safe diagnostics.
6. Preserve existing behavior for permission and provider errors unless requirements explicitly ask to include the message there; the requested gap is `SCHEDULE_CONFIG_ERROR` diagnostics for validation/config failures.

Cautions/constraints:
- Do not log/include full `Target.Input`.
- Do not include tokens, credentials, auth headers, raw payload values, or raw ClientError object contents.
- Keep src/packages mirrors in parity.
- Preserve existing sanitization tests that ensure strings like `token=secret` are redacted.

Safe vs unsafe fields:
- Safe to include after sanitization: operation, schedule name, group name, schedule expression, schedule expression timezone, start/end dates, target Lambda ARN, scheduler role ARN, and target input key names.
- Unsafe to include: full `Target.Input` JSON string, target payload values, tokens/secrets/passwords/API keys, credentials, bearer tokens, cookies/auth headers, raw AWS exception object, raw request payload dump, and raw user/client PII values.

## 10. Suggested Validation Steps
Targeted tests needed:
- Unit test `ValidationException` with `Error.Message` such as `Invalid ScheduleExpression` and assert `SCHEDULE_CONFIG_ERROR` message includes sanitized provider message.
- Unit test provider message containing `token=secret` or bearer token and assert redaction while retaining useful non-secret text.
- Unit test request shape diagnostics include the approved fields for `create_schedule`.
- Unit test `Target.Input` diagnostics expose only `input_keys` and never input values.
- Unit test malformed/unparseable `Target.Input` handling does not crash diagnostics and does not include raw input.
- Unit test both text and JSON CLI error output include the new diagnostics if diagnostics are emitted through CLI rendering.
- Mirror/parity tests or direct assertions for `packages/storage/eventbridge_scheduler_client.py` if packages remains part of the supported import surface.

Edge cases to validate:
- Invalid `ScheduleExpression`.
- Invalid `ScheduleExpressionTimezone` when timezone support is added/passed through.
- Missing or malformed `FlexibleTimeWindow`.
- Invalid `Target.Input` JSON string.
- Invalid `StartDate`/`EndDate` and start/end in the past when those fields are present.
- Generated schedule name length at/over AWS limit, despite current builder truncation/hashing.
- Missing `Target`, missing `RoleArn`, or missing target ARN.
- ValidationException with absent/empty `Error.Message` should still produce current `aws_error_code` and request shape.

## 11. Open Questions / Missing Evidence
- The exact live AWS `ValidationException` message was not provided, only the current CLI symptom. The code path nevertheless confirms why it is suppressed.
- Current `ScheduleDefinition` does not expose timezone/start/end fields, and `create_schedule()` does not set `ScheduleExpressionTimezone`, `StartDate`, or `EndDate`. If requirements expect those to be sent, a separate implementation decision is needed beyond diagnostics.
- It is unclear whether `packages/operator_cli/result.py` is still a runtime surface or only a legacy mirror, but the Scheduler client mirror definitely contains the same suppression.

## 12. Final Investigator Decision
Ready for developer fix.
