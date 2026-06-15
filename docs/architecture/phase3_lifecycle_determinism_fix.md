# Technical Design: Phase 3 Lifecycle Determinism Fix

**Feature:** Phase 3 Finalization Gate Failure — Deterministic Terminal Transition
**Branch:** `bugfix/phase3-running-after-window-rca-v2`
**Date:** 2026-06-13
**Status:** Ready for implementation
**Owner:** Backend developer

---

## 1. Feature Overview

The Phase 3 finalization handler (`AuditFinalizationHandler`) contains a lifecycle determinism defect: when the finalization integrity gate (`finalization_integrity_gate()`) returns `passed=False`, the handler catches `FinalizationGateError` and returns a `gate_failure` response without advancing the audit lifecycle to any terminal state. Because the finalization schedule is a one-time EventBridge `at()` expression with `ActionAfterCompletion=DELETE`, the schedule is permanently deleted after the first invocation. No component re-triggers the finalization handler after a gate failure. The audit remains in `FINALIZING` indefinitely — a non-terminal, non-recovering state.

This document specifies the fix: on any gate failure, the handler must transition the audit from `FINALIZING` to `FAILED` using the existing `FINALIZING → FAILED` state machine path. This makes lifecycle termination deterministic under all run completion scenarios, including audits with STARTED (in-flight) run records at finalization time.

---

## 2. Product Requirements Summary

The following requirements are derived from the established architecture invariant and the escalation that produced this bug report.

- R-01: An audit must never remain permanently in a non-terminal, non-recovering state after `audit_window.end_time` has passed.
- R-02: Lifecycle termination must be deterministic regardless of individual run anomalies (crashed executions, in-flight runs at window close, S3 evidence gaps).
- R-03: Evidence integrity must not be bypassed: gate checks must still execute and gate failures must be recorded.
- R-04: Lifecycle transitions must be auditable: every state advance must write a lifecycle history entry with reason and actor.
- R-05: The handler must remain idempotent: re-invocation with a terminal state (COMPLETED, FAILED, CANCELLED) must return `skipped` without further state changes.
- R-06: Run record ownership stays with the scheduled execution handler. The finalization handler must not write run records.
- R-07: No dashboard, reporting, aggregation, or intelligence changes are in scope.

---

## 3. Requirement-to-Architecture Mapping

| Requirement | Architectural Decision |
|---|---|
| R-01: No permanent non-terminal state | `except FinalizationGateError` blocks transition to `FAILED` in both `handle()` and `_handle_finalizing_retry()` |
| R-02: Deterministic termination | `FINALIZING → FAILED` is the single invariant outcome on gate failure; no conditional branching on failure type |
| R-03: Evidence integrity preserved | Gate still executes before any FAILED transition; gate payload is logged before transition |
| R-04: Lifecycle auditability | `_fail_gate_failure_finalization()` calls `self.lifecycle.transition()` which writes a history entry via `append_lifecycle_transition()` |
| R-05: Idempotency preserved | Terminal state check at lines 66-76 returns `skipped` before any gate or transition logic; FAILED is in `TERMINAL_STATES` |
| R-06: Run record ownership | Fix makes no calls to any run record write method; `list_run_records()` read access unchanged |
| R-07: Scope discipline | No changes outside `audit_finalization_handler.py` and the two test files |

---

## 4. Technical Scope

### Current Technical Scope

- File: `apps/backend/handlers/audit_finalization_handler.py`
  - Modify the `except FinalizationGateError` block in `handle()` (currently lines 137-140)
  - Modify the `except FinalizationGateError` block in `_handle_finalizing_retry()` (currently lines 159-162)
  - Add private method `_fail_gate_failure_finalization()`
- File: `tests/integration/test_phase3_cancellation_finalization.py`
  - Update two existing tests whose assertions reflect the old (incorrect) behavior
  - Add three new tests covering the gate failure determinism fix

### Out of Scope

- `src/release_confidence_platform/core/constants/engine.py` — do not add `TIMEOUT` status or modify `RUN_STATUSES`
- `packages/storage/audit_metadata_client.py` — do not add `update_run_record()` or any run write method
- `src/release_confidence_platform/audit_lifecycle/finalization_gate.py` — gate logic is unchanged
- `src/release_confidence_platform/audit_lifecycle/constants.py` — state machine is unchanged
- `infra/serverless.yml` — no infrastructure changes
- Any aggregation, reporting, or dashboard component

### Future Technical Considerations

The bug report's Option A (auto-timeout STARTED runs before the gate) remains a candidate future enhancement if product requirements evolve to treat in-flight runs as evidence-contributing under a "graceful degradation" or quorum model. This requires both an `update_run_record()` write method on the repository and a decision on partial-completion semantics. It must not be implemented as part of this fix.

Option C (repair re-invocation via a new EventBridge schedule) is architectural over-engineering for a defect that is fully resolved by Option B (the current fix). It introduces new infrastructure dependencies without additional correctness benefit.

---

## 5. Architecture Overview

The finalization handler currently has three distinct code paths for non-happy-path outcomes:

1. **Zero-execution path** — `execution_count == 0` before the gate is called. Handler calls `_fail_zero_execution_finalization()` which transitions `FINALIZING → FAILED`. This path already terminates deterministically.
2. **Gate failure path** — gate returns `passed=False` inside `_complete_finalization()`. Handler catches `FinalizationGateError` and currently returns `gate_failure` with no transition. **This is the defective path.**
3. **Terminal state idempotency path** — audit is already in COMPLETED, FAILED, or CANCELLED when the handler is invoked. Handler returns `skipped` immediately.

The fix makes path 2 symmetric with path 1: any gate failure triggers `FINALIZING → FAILED` with a structured reason code, then returns `gate_failure` with `lifecycle_state=FAILED`.

The gate itself is unchanged. It remains a pure function executed before any FAILED transition. Evidence of which checks failed is captured in the `gate_payload` and written to the lifecycle history entry metadata.

---

## 6. System Components

### `AuditFinalizationHandler` (modified)

Owns Phase 3 finalization lifecycle advancement. After this fix, it handles all three gate failure scenarios deterministically:

- Gate fails due to STARTED runs (`NO_ORPHANED_STARTED_RECORDS`): transitions to `FAILED` with reason `evidence_integrity_gate_failure`
- Gate fails due to missing S3 evidence (`EVERY_TERMINAL_RUN_HAS_EVIDENCE`): transitions to `FAILED` with reason `evidence_integrity_gate_failure`
- Gate fails due to any other check: transitions to `FAILED` with reason `evidence_integrity_gate_failure`

All gate failures use the same reason code. The specific failed check names are recorded in the lifecycle history metadata via `gate_payload["failedChecks"]`.

### `AuditLifecycleService` (unchanged)

Validates and writes the `FINALIZING → FAILED` transition. Already supports this transition per `constants.py:51-54`. No changes required.

### `AuditMetadataRepository` (unchanged)

`list_run_records()` read access is unchanged. No write method for run records is added.

### `finalization_integrity_gate()` (unchanged)

Pure function. Continues to evaluate all six checks. No changes.

### `FinalizationGateError` (unchanged)

`exc.payload` continues to carry `failedChecks` list. The new `_fail_gate_failure_finalization()` method reads `gate_payload.get("failedChecks", [])` to populate history metadata.

---

## 7. Data Models

No new data entities. The fix affects the content written to the existing `lifecycle_history` list on the audit record.

### Lifecycle History Entry (for gate failure transition)

```
{
  "client_id": "<client_id>",
  "audit_id": "<audit_id>",
  "from_state": "FINALIZING",
  "to_state": "FAILED",
  "timestamp": "<utc_iso>",
  "reason": "evidence_integrity_gate_failure",
  "actor": "finalization_handler",
  "metadata": {
    "gate_failure": true,
    "failed_checks": ["NO_ORPHANED_STARTED_RECORDS"]   // list of check name strings
  }
}
```

The `failed_checks` list is derived from `gate_payload["failedChecks"]` by extracting the `"check"` field from each entry. It may contain one or more check names from the set:

- `TERMINAL_COUNT_MATCHES_EXPECTED`
- `NO_ORPHANED_STARTED_RECORDS`
- `EVERY_TERMINAL_RUN_HAS_EVIDENCE`
- `EVERY_EVIDENCE_MAPS_TO_ONE_RUN`
- `NO_ORPHAN_EVIDENCE`
- `COUNTER_RECONCILIATION`

---

## 8. API Contracts

This fix does not add or modify any external API endpoints. The finalization handler is Lambda-internal, invoked by EventBridge Scheduler.

### Handler Response Contract (updated)

The `_response()` method signature and structure are unchanged. The response value for gate failure changes as follows:

**Before fix:**
```json
{"client_id": "...", "audit_id": "...", "status": "gate_failure", "lifecycle_state": "FINALIZING"}
```

**After fix:**
```json
{"client_id": "...", "audit_id": "...", "status": "gate_failure", "lifecycle_state": "FAILED"}
```

The `status` field value `"gate_failure"` is preserved. Only `lifecycle_state` changes from `"FINALIZING"` to `"FAILED"`. Callers that consume the response (EventBridge Scheduler, integration test assertions) must expect `lifecycle_state == "FAILED"` on gate failure after this fix.

---

## 9. Frontend Impact

None. This fix is entirely backend. No UI components are affected.

---

## 10. Backend Logic

### Responsibilities

After this fix, `AuditFinalizationHandler` is responsible for ensuring that every invocation ends with the audit in either a terminal state (COMPLETED, FAILED, CANCELLED) or in a valid retry-eligible state that has an active trigger. The gate failure path now always produces FAILED.

### Changes Required

#### Change 1: `handle()` — gate failure catch block

**Location:** `apps/backend/handlers/audit_finalization_handler.py`, lines 137-140

**Current code:**
```python
except FinalizationGateError:
    return self._response(
        validated, status="gate_failure", lifecycle_state=LIFECYCLE_STATE_FINALIZING
    )
```

**Replacement:**
```python
except FinalizationGateError as exc:
    self._fail_gate_failure_finalization(
        validated,
        expected_current_state=LIFECYCLE_STATE_FINALIZING,
        reason="evidence_integrity_gate_failure",
        gate_payload=exc.payload,
    )
    return self._response(
        validated, status="gate_failure", lifecycle_state=LIFECYCLE_STATE_FAILED
    )
```

#### Change 2: `_handle_finalizing_retry()` — gate failure catch block

**Location:** `apps/backend/handlers/audit_finalization_handler.py`, lines 159-162

**Current code:**
```python
except FinalizationGateError:
    return self._response(
        event, status="gate_failure", lifecycle_state=LIFECYCLE_STATE_FINALIZING
    )
```

**Replacement:**
```python
except FinalizationGateError as exc:
    self._fail_gate_failure_finalization(
        event,
        expected_current_state=LIFECYCLE_STATE_FINALIZING,
        reason="evidence_integrity_gate_failure",
        gate_payload=exc.payload,
    )
    return self._response(
        event, status="gate_failure", lifecycle_state=LIFECYCLE_STATE_FAILED
    )
```

#### Change 3: New private method `_fail_gate_failure_finalization()`

**Location:** `apps/backend/handlers/audit_finalization_handler.py` — add after `_fail_zero_execution_finalization()` (after line 296)

```python
def _fail_gate_failure_finalization(
    self,
    event: dict[str, Any],
    *,
    expected_current_state: str,
    reason: str,
    gate_payload: dict[str, Any],
) -> None:
    self.lifecycle.transition(
        LifecycleTransition(
            client_id=event["client_id"],
            audit_id=event["audit_id"],
            expected_current_state=expected_current_state,
            next_state=LIFECYCLE_STATE_FAILED,
            reason=reason,
            actor="finalization_handler",
            metadata={"gate_failure": True, "failed_checks": [
                fc["check"] for fc in gate_payload.get("failedChecks", [])
            ]},
        )
    )
    self._log_finalization(
        "auditFinalization_failed_gate_failure",
        event,
        execution_count=None,
        previous_state=expected_current_state,
        next_state=LIFECYCLE_STATE_FAILED,
        reason=reason,
        status="failed",
    )
```

### Validation Flow

No new input validation is required. `exc.payload` is the dict constructed in `_complete_finalization()` at lines 228-241. It is structurally guaranteed to contain a `"failedChecks"` key (a list of dicts each with a `"check"` key) because the same handler method builds it. The `gate_payload.get("failedChecks", [])` default guard is defensive for test stubs that may not set `failedChecks`.

### Business Rules

- Rule: Any gate failure, regardless of which checks fired, transitions the audit to `FAILED`.
- Rule: The gate must execute before the FAILED transition is attempted. It is not bypassed.
- Rule: The transition writes a history entry with `failed_checks` metadata identifying which gate checks failed.
- Rule: No distinction is made between "gate failed due to STARTED runs" and "gate failed due to evidence integrity." Both produce `FAILED`. Distinguishing by check type is a future concern if recovery semantics are added.

### Persistence Flow

`_fail_gate_failure_finalization()` calls `self.lifecycle.transition()` which calls `self.repository.append_lifecycle_transition()`. This is the same DynamoDB conditional write used by all other finalization transitions. The condition requires `lifecycle_state == FINALIZING`. If the audit has already transitioned (e.g., duplicate delivery after FAILED), the write will fail with `LifecycleConflictError` — but this case is handled upstream by the terminal state idempotency check at lines 66-76, which short-circuits before any gate or transition logic is reached on re-invocation.

### Error Handling

If `self.lifecycle.transition()` raises `LifecycleConflictError` inside `_fail_gate_failure_finalization()` (due to a concurrent transition racing with gate failure), the exception propagates up. This is correct: it means another concurrent invocation already advanced the state. The Lambda will return a non-200 response, which EventBridge Scheduler will record but will not retry (the schedule is already deleted). The audit will have reached a terminal state via the concurrent invocation.

---

## 11. File Structure

### Files Modified

```
apps/backend/handlers/audit_finalization_handler.py
    - handle(): except FinalizationGateError block (lines 137-140) → bind exc, call _fail_gate_failure_finalization(), return FAILED
    - _handle_finalizing_retry(): except FinalizationGateError block (lines 159-162) → same change
    - _fail_gate_failure_finalization(): new private method, added after _fail_zero_execution_finalization()

tests/integration/test_phase3_cancellation_finalization.py
    - test_gate_failure_on_handle_returns_gate_failure_response_not_exception: update assertions
    - test_gate_failure_on_retry_path_returns_gate_failure_response: update assertions
    - test_gate_failure_on_handle_transitions_to_failed_not_stuck_in_finalizing: new
    - test_gate_failure_on_retry_path_transitions_to_failed: new
    - test_audit_never_permanently_stuck_in_finalizing_after_gate_failure: new
```

### Files Unchanged

```
src/release_confidence_platform/core/constants/engine.py
src/release_confidence_platform/audit_lifecycle/finalization_gate.py
src/release_confidence_platform/audit_lifecycle/constants.py
packages/storage/audit_metadata_client.py
packages/audit_lifecycle/service.py
infra/serverless.yml
```

---

## 12. Security

No security surface changes. The fix does not:
- expose new endpoints or Lambda triggers
- change authentication or authorization behavior
- alter input validation
- introduce new external calls

The lifecycle transition path already sanitizes all fields via the `sanitize()` call in `AuditLifecycleService.transition()`. The `failed_checks` metadata list is derived from gate check name constants, not from user input.

---

## 13. Reliability

### Idempotency

The fix preserves all existing idempotency properties:

- On re-invocation when `current_state == FAILED`: lines 66-76 in `handle()` detect `FAILED` in `TERMINAL_STATES` and return `skipped` immediately. No gate is called. No transition is attempted.
- On re-invocation when `current_state == FINALIZING` (theoretical — would require external trigger): `_handle_finalizing_retry()` is entered. If the gate still fails, `_fail_gate_failure_finalization()` is called. The `append_lifecycle_transition()` conditional write enforces `expected_current_state == FINALIZING`. If the audit is already `FAILED` from a prior invocation, `LifecycleConflictError` is raised (correct behavior — concurrent safety).

### Failure Modes

| Failure Mode | Behavior After Fix |
|---|---|
| Gate fails on STARTED runs | `FINALIZING → FAILED` written; `gate_failure` response with `lifecycle_state=FAILED` |
| Gate fails on S3 evidence gap | Same as above |
| Gate fails on counter mismatch | Same as above |
| Gate fails on multiple checks | Same as above; all failed check names recorded in history metadata |
| `lifecycle.transition()` raises `LifecycleConflictError` | Exception propagates; Lambda returns error; schedule already deleted; audit in terminal state via concurrent path |
| EventBridge duplicate delivery after FAILED | Lines 66-76 return `skipped`; no further transition |

### Logging

`_fail_gate_failure_finalization()` calls `self._log_finalization()` with event key `"auditFinalization_failed_gate_failure"`. This produces a structured log entry at the `LOG_CATEGORY_CLIENT_SAFE` category. Operators can detect gate failure transitions in CloudWatch using this event key.

The gate failure payload (which checks failed, expected vs. actual values) continues to be logged via `logging.getLogger(__name__).error(json.dumps(failure_payload))` inside `_complete_finalization()` before `FinalizationGateError` is raised. This log is unchanged.

---

## 14. Dependencies

No new runtime dependencies. The fix uses only types and classes already imported in the handler:

- `LifecycleTransition` — already imported from `packages.audit_lifecycle.service`
- `LIFECYCLE_STATE_FAILED` — already imported from `packages.audit_lifecycle.constants`
- `LIFECYCLE_STATE_FINALIZING` — already imported

No new packages, Lambda layers, or infrastructure resources are required.

---

## 15. Assumptions

### Confirmed by Code Reading

- A-01: `FINALIZING → FAILED` is a valid state machine transition. Confirmed: `constants.py:51-54`.
- A-02: `FAILED` is in `TERMINAL_STATES`. Confirmed: `constants.py:27-31`. The idempotency check at `handle()` lines 66-76 will short-circuit on re-invocation after FAILED.
- A-03: `FinalizationGateError` carries `exc.payload` as a dict. Confirmed: `finalization_gate.py:49-51`. `exc.payload` is the `failure_payload` dict built at `audit_finalization_handler.py:228-241` which always includes `"failedChecks"` as a list.
- A-04: `AuditMetadataRepository` has no `update_run_record()` method. Confirmed: `audit_metadata_client.py` — only `list_run_records()` for run access.
- A-05: No `TIMEOUT` status exists in `RUN_STATUSES`. Confirmed: `engine.py:8`. There are only `STARTED`, `COMPLETED`, `FAILED`.
- A-06: `_fail_zero_execution_finalization()` provides a correct structural template for `_fail_gate_failure_finalization()`. Confirmed by reading lines 269-296 of the handler.

### Technical Assumptions Requiring Confirmation

- A-C01: The product/architecture decision that FAILED is the correct terminal state for gate failure — as opposed to a "partial completion" or operator-recoverable state — is confirmed by the problem statement instruction: "The simplest correct fix is: On gate failure, transition the audit to FAILED instead of returning gate_failure with no state advance." This document implements exactly that decision.
- A-C02: Treating all gate failure types uniformly (single reason code `evidence_integrity_gate_failure`) is acceptable. If future requirements call for distinguishing `started_runs_at_finalization` from evidence corruption failures, a reason code mapping by failed check can be added without structural changes to this design.

---

## 16. Risks / Open Questions

### Risk 1: FAILED is terminal — no automated recovery

FAILED is a terminal state. There is no automated path from FAILED to COMPLETED. An audit that reaches FAILED due to STARTED runs at finalization time cannot self-recover if those runs later complete. An operator must manually investigate.

**Acceptance:** Confirmed acceptable per the architectural decision in the problem statement. A gate failure indicates an evidence integrity condition that requires human review. Automated recovery (Option A/C) is out of scope for this fix.

### Risk 2: Existing tests assert `lifecycle_state == "FINALIZING"` after gate failure

Two tests in `test_phase3_cancellation_finalization.py` assert the old (incorrect) behavior:
- `test_gate_failure_on_handle_returns_gate_failure_response_not_exception` (lines 320-331)
- `test_gate_failure_on_retry_path_returns_gate_failure_response` (lines 334-348)

Both assert `result["lifecycle_state"] == "FINALIZING"` and `repo.audit["lifecycle_state"] == "FINALIZING"`. These assertions must be updated to reflect the correct post-fix behavior (`== "FAILED"`). This is a deliberate behavior change, not a regression.

**Action:** Update both tests as part of this fix. See Test Plan section.

### Risk 3: `_log_finalization()` receives `execution_count=None` in gate failure path

`_fail_gate_failure_finalization()` passes `execution_count=None` to `_log_finalization()`, matching the pattern already used by aggregation-related log calls (lines 337, 384, 402). The `_log_finalization()` method signature accepts `int | None` for `execution_count`. This is safe.

### Open Question 1: Stuck audit `audit_20260612_ba23618d`

The specific stuck audit in the bug report is currently in `RUNNING` state (Bug 1 deployment gap). Once the Bug 1 fix is deployed and the audit is manually re-triggered for finalization, if any run records are still in `STARTED` state, the audit will now transition to `FAILED` (with this fix deployed) rather than entering the `FINALIZING` dead-end. No additional recovery tooling is needed for this audit beyond deploying this fix and re-triggering finalization.

---

## 17. Implementation Notes

### For the Backend Developer

**Implementation order:**

1. Add `_fail_gate_failure_finalization()` as a new private method to `AuditFinalizationHandler`, placed immediately after `_fail_zero_execution_finalization()` (after line 296). Use `_fail_zero_execution_finalization()` as the structural template — the signature and body are parallel except for the gate payload parameter and metadata content.

2. Modify the `except FinalizationGateError` block in `handle()` (lines 137-140). Change `except FinalizationGateError:` to `except FinalizationGateError as exc:`. Call `_fail_gate_failure_finalization()` before the `return`. Change `lifecycle_state=LIFECYCLE_STATE_FINALIZING` to `lifecycle_state=LIFECYCLE_STATE_FAILED` in the `_response()` call.

3. Apply the identical change to the `except FinalizationGateError` block in `_handle_finalizing_retry()` (lines 159-162).

4. Update `test_gate_failure_on_handle_returns_gate_failure_response_not_exception`:
   - Change `assert result["lifecycle_state"] == "FINALIZING"` to `assert result["lifecycle_state"] == "FAILED"`
   - Change `assert repo.audit["lifecycle_state"] == "FINALIZING"` to `assert repo.audit["lifecycle_state"] == "FAILED"`
   - Add assertion: `assert [entry["to_state"] for entry in repo.audit["lifecycle_history"]] == ["FINALIZING", "FAILED"]`

5. Update `test_gate_failure_on_retry_path_returns_gate_failure_response`:
   - Change `assert result["lifecycle_state"] == "FINALIZING"` to `assert result["lifecycle_state"] == "FAILED"`
   - Change `assert repo.audit["lifecycle_state"] == "FINALIZING"` to `assert repo.audit["lifecycle_state"] == "FAILED"`
   - Add assertion: `assert [entry["to_state"] for entry in repo.audit["lifecycle_history"]] == ["FAILED"]` (retry path — FINALIZING transition already in history from prior invocation)

6. Add three new tests per the Test Plan section below.

**Symmetry check before submitting:** confirm that both `except FinalizationGateError` blocks (in `handle()` and `_handle_finalizing_retry()`) are exactly symmetric — same call to `_fail_gate_failure_finalization()` with `expected_current_state=LIFECYCLE_STATE_FINALIZING` and same response with `lifecycle_state=LIFECYCLE_STATE_FAILED`.

**Do not:**
- Add any method to `AuditMetadataRepository` that writes run records
- Add `TIMEOUT` to `RUN_STATUSES` or `engine.py`
- Modify `finalization_integrity_gate()` or any gate constants
- Modify `constants.py` (lifecycle state machine)
- Touch any aggregation, reporting, or dashboard code

---

## 18. Test Plan Specification

### Tests to Update (behavior change)

**File:** `tests/integration/test_phase3_cancellation_finalization.py`

#### `test_gate_failure_on_handle_returns_gate_failure_response_not_exception`

Current incorrect assertions:
```python
assert result["lifecycle_state"] == "FINALIZING"
assert repo.audit["lifecycle_state"] == "FINALIZING"
```

Updated assertions:
```python
assert result["status"] == "gate_failure"
assert result["lifecycle_state"] == "FAILED"
assert repo.audit["lifecycle_state"] == "FAILED"
assert "FINALIZING" in [entry["to_state"] for entry in repo.audit["lifecycle_history"]]
assert "FAILED" in [entry["to_state"] for entry in repo.audit["lifecycle_history"]]
```

#### `test_gate_failure_on_retry_path_returns_gate_failure_response`

Current incorrect assertions:
```python
assert result["lifecycle_state"] == "FINALIZING"
assert repo.audit["lifecycle_state"] == "FINALIZING"
```

Updated assertions:
```python
assert result["status"] == "gate_failure"
assert result["lifecycle_state"] == "FAILED"
assert repo.audit["lifecycle_state"] == "FAILED"
```

### Tests to Add (new coverage)

**File:** `tests/integration/test_phase3_cancellation_finalization.py`

#### `test_gate_failure_on_handle_transitions_to_failed_not_stuck_in_finalizing`

- Setup: `Repo(state="RUNNING", executions=1)` — one COMPLETED run record; `GateFailingS3` returns no S3 evidence keys
- Action: invoke `handler.handle(finalization_event())`
- Assertions:
  - `result["status"] == "gate_failure"`
  - `result["lifecycle_state"] == "FAILED"`
  - `repo.audit["lifecycle_state"] == "FAILED"`
  - `[entry["to_state"] for entry in repo.audit["lifecycle_history"]] == ["FINALIZING", "FAILED"]`

This verifies the full RUNNING → FINALIZING → FAILED path under gate failure.

#### `test_gate_failure_on_retry_path_transitions_to_failed`

- Setup: `Repo(state="FINALIZING", executions=1)` with `finalization` metadata set (`execution_count=1`); `GateFailingS3`
- Action: invoke `handler.handle(finalization_event())`
- Assertions:
  - `result["status"] == "gate_failure"`
  - `result["lifecycle_state"] == "FAILED"`
  - `repo.audit["lifecycle_state"] == "FAILED"`
  - `[entry["to_state"] for entry in repo.audit["lifecycle_history"]] == ["FAILED"]`

This verifies the retry path (`_handle_finalizing_retry()`) also transitions to FAILED on gate failure.

#### `test_audit_never_permanently_stuck_in_finalizing_after_gate_failure`

- Setup: `Repo(state="RUNNING", executions=4)` with run records list containing 4 COMPLETED + 1 STARTED record; standard S3 (no GateFailingS3 needed — gate will fail on Check 2 due to STARTED record)
- Action: invoke `handler.handle(finalization_event())`
- Assertions:
  - `repo.audit["lifecycle_state"] != "FINALIZING"` — the primary determinism invariant
  - `repo.audit["lifecycle_state"] == "FAILED"`
  - `result["lifecycle_state"] == "FAILED"`

This test is the regression guard: it proves that a STARTED run at finalization time no longer produces a permanent FINALIZING dead-end.

### Regression Scenarios Coverage Map

| Scenario | Test Coverage |
|---|---|
| 1. All runs complete before window end | C-05 (existing — unchanged) |
| 2. One run remains STARTED at window end | `test_audit_never_permanently_stuck_in_finalizing_after_gate_failure` (new) |
| 3. Multiple runs remain STARTED at window end | Variant of scenario 2 — covered by same test setup with additional STARTED records |
| 4. Finalization event arrives late | Covered by idempotency: RUNNING → FINALIZING → FAILED path applies regardless of timing |
| 5. Finalization event is retried (FINALIZING re-entry) | `test_gate_failure_on_retry_path_transitions_to_failed` (new) |
| 6. Duplicate finalization events | `test_duplicate_finalization_delivery_skips_terminal_state` (existing — unchanged) |
| 7. Missing finalization event recovery | Not in scope — EventBridge delivery is infrastructure-level |
| 8. Lifecycle transition idempotency | `test_duplicate_finalization_delivery_skips_terminal_state` (existing) + re-invocation after FAILED returns `skipped` (covered by terminal state guard, verifiable via existing terminal state test) |
| 9. Audit never remains in RUNNING after window end (gate failure path) | `test_gate_failure_on_handle_transitions_to_failed_not_stuck_in_finalizing` (new) |

### All Other Existing Tests

All other tests in `test_phase3_cancellation_finalization.py`, `test_execution_integrity_reconciliation.py`, and `test_execution_integrity_e2e.py` must pass without modification. The fix only affects the `except FinalizationGateError` paths. The happy path (`_complete_finalization()` succeeds), the zero-execution path, and the terminal state idempotency path are all unchanged.
