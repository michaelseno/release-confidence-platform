# Architecture Review: FinalizationGateError Top-Level Handling

**Date:** 2026-06-13
**Reviewer:** Architecture Reviewer
**Related ADR:** `adr_phase_3_finalization_completion_cleanup.md`
**Related Design:** `finalization_integrity_gate_design.md`
**Bug Report:** `docs/bugs/phase3_running_after_window_rca_v2.md`

---

## Status

Approved with Concerns

---

## Decision

Approved: wrap the `_complete_finalization()` call in `AuditFinalizationHandler.handle()` with a `try/except FinalizationGateError` block that returns a structured `{"status": "gate_failure", "lifecycle_state": "FINALIZING"}` response via `self._response()` rather than re-raising.

The same catch must be applied in `_handle_finalizing_retry()`, which also calls `_complete_finalization()` on the same code path and is identically exposed to the gap.

---

## Rationale

**On contract correctness (returning success vs. re-raising):**
A `FinalizationGateError` is a deterministic, non-transient condition — the evidence is inconsistent and will remain so until manual recovery is performed. Re-raising the exception signals to EventBridge Scheduler that the invocation failed transiently and should be retried. Because the gate evaluates the same DynamoDB and S3 state on every retry, and that state has not changed, every retry will re-raise the same error. The retry loop terminates only when the EventBridge schedule's retry policy is exhausted, not when the problem is resolved. The condition is not retryable without human intervention.

Returning a structured non-exception response causes EventBridge to record the invocation as successful. `ActionAfterCompletion="DELETE"` then fires, the schedule is removed, and no further automatic retries occur. The gate failure is fully recorded in CloudWatch via the direct-JSON `logging.getLogger(__name__).error(json.dumps(failure_payload))` call already present in `_complete_finalization()` before `raise`. The operational semantics are correct: the Lambda communicated a known, deterministic failure; EventBridge's retry mechanism is reserved for infrastructure failures.

**On ADR compliance:**
`adr_phase_3_finalization_completion_cleanup.md` states: "Require the finalization handler to use `AuditLifecycleService.transition(...)` for both success and failure closeout." A gate failure is not a closeout — no terminal state is reached. The audit remains in `FINALIZING`, which is an intermediate lifecycle state. No new transition is issued because no transition is appropriate: there is no valid `FINALIZING -> ???` path for a gate-blocked audit under the current TRANSITIONS contract. Issuing `FINALIZING -> FAILED` would be incorrect because the audit is not terminally failed; it is awaiting evidence reconciliation. The ADR clause applies to successful and zero-execution paths, both of which already issue transitions to `COMPLETED` or `FAILED`. Gate-blocked finalization does not fall within the ADR's closeout intent. No ADR violation.

**On response sanitization:**
The proposed response passes through `self._response()`, which calls `sanitize()`. The fields `"status": "gate_failure"` and `"lifecycle_state": "FINALIZING"` are safe: neither is a run ID, S3 key, UUID, or phone-pattern identifier that `sanitize()` would mutate. The gate failure payload details (failed checks, run IDs, S3 keys) must NOT appear in the response; they belong only in the CloudWatch log via direct JSON. This is already the design.

**On downstream consumers:**
The Lambda is invoked asynchronously by EventBridge Scheduler. No synchronous caller inspects the response body. The only behavioral difference between re-raise and structured return is EventBridge's retry decision and CloudWatch error metric recording. A structured return does not suppress visibility; it shifts the signal from a Lambda invocation error metric to a CloudWatch log-based alert on `FINALIZATION_INTEGRITY_GATE_FAILURE`. A CloudWatch alarm on that log event is the correct monitoring surface.

---

## Consequences

**What changes:**
- Gate failures no longer produce Lambda invocation errors. They produce structured log entries and a `gate_failure` response.
- EventBridge schedules are deleted on gate failure (same as on success), preventing infinite retry.
- The audit remains in `FINALIZING` state, requiring manual recovery per `finalization_integrity_gate_design.md` section 12.

**Manual recovery path after schedule deletion:**
When EventBridge deletes the schedule after a gate-failure response, the automatic re-invocation path is gone. Manual recovery (section 12, Step 4) requires the operator to re-invoke the finalization Lambda directly with a correctly formed finalization event payload. This is acceptable because gate failures require human review before re-invocation in any case. The operator must not bypass the gate; they must fix the evidence and re-run the handler via direct Lambda invocation or an approved operator CLI recovery command. This path must be documented in the recovery runbook. An operator CLI `rcp audit finalize --audit-id <id>` command is the preferred recovery surface; direct Lambda invocation is the fallback.

**Risk remaining:**
`_complete_finalization()` can also raise `ValueError` for structurally invalid gate inputs (programming error, not a gate failure). The `try/except FinalizationGateError` block must not catch `ValueError` or any other exception class. The catch must be typed precisely to `FinalizationGateError`. A broad `except Exception` would suppress programming errors that should propagate.

---

## Deployment Gate Process Note

**Required process addition:**

The root cause of the incident (`audit_20260612_ba23618d` stuck in `RUNNING`) is that the execution integrity fix was merged to `main` but the `auditFinalization` Lambda was not redeployed to the dev AWS environment before the affected audit's finalization window fired.

The following prerequisite must be added to the finalization handler ADR and the team's release workflow:

> After any commit that modifies code in `apps/backend/handlers/` is merged to main, the corresponding Lambda(s) must be deployed to the target environment and the deployment confirmed (via `aws lambda get-function LastModified` or a successful CloudWatch structured log entry from the fixed code path) before the fix cycle is considered closed. WS-E (deployment validation) is in scope for all QA cycles that touch Lambda handler code.

This is a process addition, not a code change. It applies to all future handler fixes.

---

## Implementation Contract for Backend

The backend developer must implement the following, and nothing more:

1. In `AuditFinalizationHandler.handle()`, wrap lines 129-136 (`_complete_finalization(...)` and `_trigger_aggregation_after_finalization(...)`) in a `try/except FinalizationGateError` block. On catch: return `self._response(validated, status="gate_failure", lifecycle_state=LIFECYCLE_STATE_FINALIZING)`. Do not re-raise. Do not log inside the except block — logging is already done inside `_complete_finalization()` before the raise.

2. Apply the identical `try/except FinalizationGateError` wrap to the `_complete_finalization()` call at lines 146-156 in `_handle_finalizing_retry()`, with the same return: `self._response(event, status="gate_failure", lifecycle_state=LIFECYCLE_STATE_FINALIZING)`.

3. The catch must be `except FinalizationGateError` — not `except Exception`, not `except BaseException`. Other exception types (including `ValueError` from structural gate input errors) must propagate.

4. The response fields `"status": "gate_failure"` and `"lifecycle_state": "FINALIZING"` pass through `sanitize()` via `self._response()`. No gate failure payload fields (check names, run IDs, S3 keys) may appear in the response dict.

5. No lifecycle transition is issued on gate failure. The audit remains in `FINALIZING`. This is correct and does not violate the ADR.
