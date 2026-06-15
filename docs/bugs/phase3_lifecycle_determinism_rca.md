# Bug Report: Phase 3 Lifecycle Determinism — Audit Permanently Stuck in FINALIZING When Gate Blocks on STARTED Runs

**audit_id:** `audit_20260612_ba23618d`
**client_id:** `client_rca_fix_v1_d39611f5`
**branch:** `bugfix/phase3-running-after-window-rca-v2`
**Reported:** 2026-06-13
**Investigator:** Bug Investigator (systematic-debugging skill applied)

---

## 1. Summary

The finalization integrity gate (`finalization_integrity_gate()`) requires zero STARTED run records as a hard pass condition (Check 2: `NO_ORPHANED_STARTED_RECORDS`). The handler in commit `de3bdbb` now correctly catches `FinalizationGateError` and returns a `gate_failure` response instead of propagating as an unhandled exception. However, this catch is architecturally insufficient: after a `gate_failure`, the audit is permanently stuck in `FINALIZING` with no automatic recovery mechanism. The EventBridge finalization schedule is a one-time `at()` expression with `ActionAfterCompletion=DELETE`. Once it fires and the gate blocks on STARTED runs, the schedule is deleted and no mechanism re-triggers finalization. The `_handle_finalizing_retry()` path exists in the handler code but is unreachable without an external trigger, which no component provides after gate failure.

The result is a deterministic lifecycle dead-end: any audit with one or more runs that remain in `STARTED` state at finalization time will enter `FINALIZING`, have the gate block the `COMPLETED` transition, return `gate_failure`, and then stay in `FINALIZING` indefinitely — permanently stuck, with no automatic escape.

---

## 2. Investigation Context

- Source of report: Escalation — architectural determinism gap identified post Bug 2 fix (`de3bdbb`).
- Branch context: `bugfix/phase3-running-after-window-rca-v2` (contains `de3bdbb` which added `FinalizationGateError` catch in `handle()` and `_handle_finalizing_retry()`).
- Related workflow: Phase 3 scheduled audit finalization triggered by EventBridge Scheduler one-time `at()` schedule at audit window end.
- Prior bug chain:
  - Bug 1 (`hitl_phase_3_running_after_window_bug_report.md`): Decimal serialization in `_log_finalization()` crashed Lambda before `RUNNING → FINALIZING` transition. Fixed in commits `dba1ed5`/`e7ca123`.
  - Bug 2 (`phase_3_finalization_cleanup_bug_report.md`): `FinalizationGateError` from `_complete_finalization()` was unhandled, propagating as Lambda failure, leaving audit in `FINALIZING`. Fixed in commit `de3bdbb`.
  - This investigation: `de3bdbb` is necessary but not sufficient. The gate's STARTED-run check creates a permanent `FINALIZING` dead-end because no retry trigger exists.
- Affected audit: `client_rca_fix_v1_d39611f5` / `audit_20260612_ba23618d`, `lifecycle_state=RUNNING`, `audit_window.end_time=2026-06-12T16:36:25.756230Z`.

---

## 3. Observed Symptoms

- Audit `audit_20260612_ba23618d` stuck in `RUNNING` after window end (the immediate presentation, traced to Bug 1 deployment gap in `phase3_running_after_window_rca_v2.md`).
- Escalation scenario: if the same audit or any future audit reaches `FINALIZING` with one or more STARTED run records, the gate returns `passed=False`, the handler returns `gate_failure`, and no automatic re-trigger exists to advance the lifecycle.
- Expected behavior: audits must deterministically exit `FINALIZING` under all run completion scenarios, including late/incomplete executions at window end.
- Actual behavior after `de3bdbb`: audits with STARTED runs at finalization time enter a permanent `FINALIZING` dead-end with no automated escape.

---

## 4. Evidence Collected

### 4.1 Finalization schedule is one-time `at()` with `ActionAfterCompletion=DELETE`

`src/release_confidence_platform/storage/eventbridge_scheduler_client.py:39-46`:

```python
def create_schedule(self, definition: Any) -> dict[str, Any]:
    payload = {
        "Name": definition.name,
        "ScheduleExpression": definition.expression,
        "FlexibleTimeWindow": {"Mode": "OFF"},
    }
    if _is_one_time_at_expression(definition.expression):
        payload["ActionAfterCompletion"] = "DELETE"
```

`src/release_confidence_platform/audit_scheduling/builders.py:269-302`: `build_finalization()` generates `at({expression_time})` — always a one-time `at()` expression. The schedule fires exactly once. EventBridge Scheduler deletes the schedule immediately after it fires (confirmed by `ActionAfterCompletion=DELETE`). There is no re-fire mechanism.

### 4.2 The gate's STARTED-run check is a hard blocking condition

`src/release_confidence_platform/audit_lifecycle/finalization_gate.py:148-162`:

```python
started_count = len(started_runs)
if started_count != 0:
    started_ids = [r.get("run_id", "<unknown>") for r in started_runs]
    failures.append(
        CheckFailure(
            check=CHECK_NO_ORPHANED_STARTED_RECORDS,
            expected=0,
            actual=started_count,
            ...
        )
    )
```

Any run with `status == RUN_STATUS_STARTED` causes `GateResult(passed=False)`. The gate is a pure function with no side effects and no tolerance for STARTED runs. It does not distinguish between "run still in flight" and "run permanently orphaned."

### 4.3 Gate failure returns `gate_failure` and leaves audit in `FINALIZING`

`apps/backend/handlers/audit_finalization_handler.py:129-140`:

```python
try:
    self._complete_finalization(
        validated,
        audit=audit,
        expected_current_state=LIFECYCLE_STATE_FINALIZING,
        execution_count=execution_count,
        reason="finalization_completed",
    )
except FinalizationGateError:
    return self._response(
        validated, status="gate_failure", lifecycle_state=LIFECYCLE_STATE_FINALIZING
    )
```

After the `RUNNING → FINALIZING` transition at line 105-115, if the gate fires:
- The `FinalizationGateError` is caught.
- The handler returns `{"status": "gate_failure", "lifecycle_state": "FINALIZING"}`.
- No further lifecycle transition is attempted.
- The audit remains in `FINALIZING` permanently.

The same path exists in `_handle_finalizing_retry()` at lines 159-162 — it also catches and returns `gate_failure` with no state advance.

### 4.4 `_handle_finalizing_retry()` is only reachable if the handler is re-invoked externally

`apps/backend/handlers/audit_finalization_handler.py:78-79`:

```python
if current_state == LIFECYCLE_STATE_FINALIZING:
    return self._handle_finalizing_retry(validated, audit)
```

`_handle_finalizing_retry()` is only entered when the finalization handler is called again with the audit already in `FINALIZING` state. The finalization schedule has already been deleted by `ActionAfterCompletion=DELETE`. Nothing in the codebase re-invokes the finalization handler after a gate failure. There is no:
- Background repair job
- Lambda-to-Lambda re-invocation
- Scheduled periodic retry
- DLQ re-drive mechanism
- EventBridge retry policy on gate failure (gate failure returns a valid 200 response, not a Lambda error, so EventBridge has no retry signal)

The retry path exists in code but has no trigger path after the first gate failure.

### 4.5 The gate receives `gate_execution_count` derived from actual terminal runs, not `total_completed`

`apps/backend/handlers/audit_finalization_handler.py:212-215`:

```python
terminal_count = len([r for r in run_records if r.get("status") != RUN_STATUS_STARTED])
gate_execution_count = terminal_count if terminal_count > 0 else execution_count
finalization["execution_count"] = gate_execution_count
```

When STARTED runs exist: `terminal_count < total(run_records)`. The gate receives `gate_execution_count = terminal_count`. Then Check 1 (`TERMINAL_COUNT_MATCHES_EXPECTED`) receives `expected = terminal_count` and `actual = terminal_count` — this check passes. But Check 2 (`NO_ORPHANED_STARTED_RECORDS`) receives `started_count > 0` — this check fails regardless.

This means: the `execution_count` divergence between `execution_counters.total_completed` and the gate's `execution_count` parameter is explicitly compensated by the handler before calling the gate. The gate still blocks on the STARTED-run check.

### 4.6 No partial-completion path exists

The gate has no concept of "accept the completed subset and proceed." It is all-or-nothing: either all six checks pass (no STARTED runs, all terminal runs have S3 evidence, counters reconcile) or the gate blocks. There is no "quorum" or "graceful degradation" semantics.

### 4.7 The state machine permits `FINALIZING → FAILED`

`src/release_confidence_platform/audit_lifecycle/constants.py:51-54`:

```python
LIFECYCLE_STATE_FINALIZING: (
    LIFECYCLE_STATE_ANALYZING,
    LIFECYCLE_STATE_COMPLETED,
    LIFECYCLE_STATE_FAILED,
),
```

`FINALIZING → FAILED` is a valid, supported transition. It is currently used only for the zero-execution path (`_fail_zero_execution_finalization()`). The state machine does not prevent transitioning to `FAILED` after gate failure. The handler simply does not exercise this path on gate failure.

### 4.8 No Lambda retry policy is configured for `auditFinalization`

`infra/serverless.yml:124-131`: the `auditFinalization` function has no `eventInvokeConfig`, no `destinations`, no `maximumRetryAttempts`, and no DLQ. Since the gate failure is caught and a 200-class response is returned, EventBridge Scheduler's built-in Lambda invocation retry (which only triggers on Lambda errors/timeouts) does not apply.

### 4.9 `ensure_execution_allowed()` prevents late run completions from updating state

`packages/audit_scheduling/safeguards.py:159-168`: `ensure_execution_allowed()` checks `scheduled_at` against `audit_window.end_time`. After the audit window closes, scheduled executions with `scheduled_at > end_time` are rejected with `AUDIT_WINDOW_EXPIRED`. If a run was in-flight at window close, the scheduled execution handler does not have a path to mark it as `FAILED`/`TIMEOUT` — it was already launched and is executing independently. The DynamoDB run record remains in `STARTED` until the execution handler updates it, which may never happen for a crashed/timeout execution.

### 4.10 Test coverage of the gap

`tests/integration/test_execution_integrity_reconciliation.py:120-143` (C-01) confirms the gate blocks on STARTED runs and that `result["status"] == "gate_failure"`. However, no test asserts what happens after this point — specifically, no test covers the scenario where the EventBridge schedule fires once, the gate fails on STARTED runs, and then nothing else happens.

`tests/integration/test_phase3_cancellation_finalization.py:320-348` covers `test_gate_failure_on_handle_returns_gate_failure_response_not_exception` and `test_gate_failure_on_retry_path_returns_gate_failure_response` — these confirm the `FinalizationGateError` is caught. Neither test covers the recovery gap.

No test exists for: "after gate_failure, what mechanism advances the audit out of FINALIZING."

---

## 5. Execution Path / Failure Trace

### Scenario: Audit has 1 STARTED run at finalization time

1. Audit window ends at `T`. EventBridge fires the one-time `at(T)` finalization schedule.
2. `AuditFinalizationHandler.handle()` is invoked. `current_state = RUNNING`.
3. `execution_count = execution_counters.total_completed = N` (e.g., 4 completed, 1 in-flight).
4. `lifecycle.transition(RUNNING → FINALIZING)` succeeds. Audit is now `FINALIZING`. (line 105-115)
5. `repository.record_finalization()` writes the finalization metadata. (line 116)
6. `_complete_finalization()` is called. (line 130)
7. `run_records` is fetched — includes 4 COMPLETED + 1 STARTED.
8. `terminal_count = 4`. `gate_execution_count = 4`. Passed to gate.
9. `finalization_integrity_gate()` runs all six checks:
   - Check 1: `expected=4`, `actual=4` → passes.
   - Check 2: `started_count=1` → **FAILS** (`NO_ORPHANED_STARTED_RECORDS`).
   - Check 3: runs per terminal run (4 runs, 4 S3 keys present) → passes.
   - Check 4/5: S3 evidence and run mapping consistent → passes.
   - Check 6: `total_completed=4`, `terminal_count=4` → passes.
10. `gate_result.passed = False`. `FinalizationGateError` raised.
11. Handler catches `FinalizationGateError`. Returns `{"status": "gate_failure", "lifecycle_state": "FINALIZING"}`.
12. Lambda returns 200-class response. EventBridge marks invocation as successful.
13. EventBridge Scheduler deletes the finalization schedule (`ActionAfterCompletion=DELETE`).
14. **Audit is in `FINALIZING`. No further trigger exists. Permanently stuck.**

### What about the retry path?

`_handle_finalizing_retry()` is only reachable if the finalization handler is called again when `current_state == FINALIZING`. After step 13, the schedule no longer exists. Nothing calls the finalization handler again. The retry path is dead code in the STARTED-run scenario.

---

## 6. Failure Classification

- Primary classification: **Application Bug** — the handler returns `gate_failure` and leaves the audit in a non-terminal, non-recovering state with no automatic exit.
- Contributing classification: **Requirements Ambiguity** — the architectural requirement that "audits must deterministically exit `RUNNING` regardless of individual run anomalies" was not fully specified as a completion-path invariant; no design document specifies behavior when STARTED runs are present at window end.
- Severity: **Blocker** — any audit where an execution is still in-flight or has crashed without updating its status at finalization time will permanently enter the `FINALIZING` dead-end. This is not a theoretical edge case: Lambda timeouts, network partitions during execution, and race conditions between the last baseline execution and the finalization trigger are all realistic scenarios in production.
- Reproducibility: **Always reproducible** — deterministic given the conditions (one STARTED run at finalization time).

---

## 7. Root Cause Analysis

### Most Likely Root Cause

**The finalization handler has no recovery path for gate failure caused by STARTED runs. The `gate_failure` response returns 200 to EventBridge, which deletes the one-time schedule. The audit is permanently stuck in `FINALIZING` with no automatic escape.**

- Immediate failure point: `apps/backend/handlers/audit_finalization_handler.py:137-140` — the `except FinalizationGateError` block in `handle()` returns `gate_failure` without advancing the lifecycle to `FAILED` or scheduling a retry.
- Underlying root cause: the gate's `NO_ORPHANED_STARTED_RECORDS` check (Check 2) treats any STARTED run as a hard blocking failure, but the handler has no semantic distinction between "gate failed due to corrupted evidence" (genuine integrity violation) and "gate failed because one run was in-flight at window close" (expected race condition). Both are treated identically — return `gate_failure`, leave in `FINALIZING`, do nothing further.
- Supporting evidence:
  - `finalization_integrity_gate.py:148-162`: Check 2 is unconditional. `started_count != 0` → fail. No tolerance for in-flight runs.
  - `eventbridge_scheduler_client.py:45-46`: `ActionAfterCompletion=DELETE`. One-time schedule deleted on first invocation success.
  - `audit_finalization_handler.py:78-79`: `_handle_finalizing_retry()` requires external re-invocation of the handler — no component provides this.
  - `serverless.yml:124-131`: No retry policy, no DLQ, no periodic polling on `auditFinalization`.
  - `constants.py:51-54`: `FINALIZING → FAILED` is a valid transition that the handler deliberately avoids on gate failure.

### Confirmation: Fix in `de3bdbb` is necessary but architecturally insufficient

`de3bdbb` correctly prevents the Lambda from crashing and causing EventBridge to retry indefinitely. But returning `gate_failure` without advancing to a terminal state or establishing a retry mechanism leaves the lifecycle incomplete. The fix eliminated the symptom (unhandled exception) without addressing the root cause (no deterministic completion path under STARTED-run gate failure).

### Plausible Contributing Factors

1. **Semantic conflation in the gate**: the gate treats "data integrity failure" and "timing race at window close" as the same failure category. STARTED runs at window close are an expected transient condition for any audit where a scheduled execution fires within the finalization window.

2. **No STARTED-run resolution path in the scheduled execution handler**: `scheduled_execution_handler.py` does not mark orphaned STARTED runs as `FAILED`/`TIMEOUT` when the audit window closes. There is no cleanup sweep for runs that were in-flight at window close.

3. **`execution_counters.total_completed` and gate's `execution_count` can diverge**: the handler sets `gate_execution_count = terminal_count` when STARTED runs exist (line 213-215). This means `execution_count` in the gate is derived from actual terminal runs, not the counter. The counter tracks handler-path outcomes; the gate operates on DynamoDB run record states. They can diverge in race conditions (e.g., execution handler completes a run after the finalization handler reads `execution_counters` but before it reads `run_records`).

---

## 8. Confidence Level

**High.**

The failure path is fully traced in source code with no ambiguity:
- One-time schedule confirmed by `eventbridge_scheduler_client.py:45-46`.
- Gate blocking on STARTED runs confirmed by `finalization_gate.py:148-162`.
- No retry trigger confirmed by absence of any component that re-invokes the finalization handler after `gate_failure`.
- `FINALIZING → FAILED` transition available but unused on gate failure confirmed by `constants.py:51-54` and `audit_finalization_handler.py:137-140`.
- Tests C-01 and `test_gate_failure_on_handle_returns_gate_failure_response_not_exception` confirm the current behavior (gate_failure is caught and returned) — they also confirm no further state transition occurs.

---

## 9. Recommended Fix

**Owner:** backend developer

**Core decision required:** Choose between three fix approaches:

### Option A (Recommended): Treat STARTED runs at window end as terminal (auto-timeout)

At finalization time, if any run records remain in `STARTED` state, mark them as `TIMEOUT` (or a designated "finalization-forced-terminal" status) before invoking the gate. This preserves the gate's integrity while allowing lifecycle to proceed.

- File: `apps/backend/handlers/audit_finalization_handler.py`
- Function: `_complete_finalization()`
- Specific change: before calling `finalization_integrity_gate()`, iterate `run_records` and call `repository.update_run_record(run_id, {"status": "TIMEOUT", "completed_at": ...})` for every run with `status == RUN_STATUS_STARTED`. Re-fetch run records after update (or update the local list). The gate then sees zero STARTED runs.
- Requires: a `update_run_record()` or equivalent method on the repository that updates a run's status. Check 2 will pass. Evidence checks (3/4/5) may still fail if TIMEOUT runs have no S3 evidence — this is handled by the gate as a distinct Check 3 failure (`EVERY_TERMINAL_RUN_HAS_EVIDENCE`), which is accurate.
- Caution: the auto-timeout write must be idempotent (safe to re-apply on retry path). The status `TIMEOUT` must be in `RUN_STATUSES` and outside `RUN_STATUS_STARTED` (verify against `core/constants/engine.py`).

### Option B: On gate failure due to STARTED runs, transition to FAILED

If the gate fails specifically because of STARTED runs (Check 2 fired), treat the audit as `FAILED` rather than leaving it in `FINALIZING`.

- File: `apps/backend/handlers/audit_finalization_handler.py`
- Functions: `handle()` (lines 137-140) and `_handle_finalizing_retry()` (lines 159-162)
- Specific change: in the `except FinalizationGateError` blocks, inspect `exc.payload["failedChecks"]` for `check == "NO_ORPHANED_STARTED_RECORDS"`. If present, call `self.lifecycle.transition(... FINALIZING → FAILED ...)` with `reason="started_runs_at_finalization"` before returning. For other gate failures (evidence integrity), retain existing `gate_failure` behavior with a log.
- Pro: preserves gate integrity and gives audits with incomplete evidence a deterministic terminal state.
- Con: FAILED is a terminal state; there is no recovery if the STARTED run later completes.

### Option C: Add a finalization repair path (re-trigger after wait)

After `gate_failure`, schedule a repair invocation of the finalization handler (e.g., via a new one-time EventBridge schedule with a short delay, or via a Step Functions wait state) to retry once STARTED runs may have completed.

- This is the most complex option and introduces new infrastructure dependencies.
- Not recommended as a first fix; appropriate only if the audit SLA requires evidence from all in-flight runs.

### Recommended immediate fix: Option A for the common in-flight case, Option B as the fallback for orphaned runs

Specifically:
1. In `_complete_finalization()` (`audit_finalization_handler.py`), before the gate call (line 219), mark all STARTED runs as `TIMEOUT` via repository write if the audit window has passed.
2. In the `except FinalizationGateError` blocks (lines 137-140 and 159-162), if the failure payload contains `NO_ORPHANED_STARTED_RECORDS` after Option A, transition to `FAILED` as a catch-all.
3. Add `TIMEOUT` to `RUN_STATUSES` if not already present (verify `src/release_confidence_platform/core/constants/engine.py`).

Cautions:
- Do not bypass lifecycle safety controls or mutate audit state outside lifecycle service.
- Preserve evidence integrity: TIMEOUT runs without S3 evidence are accurately reported by Check 3 as a gate failure. Only Check 2 should be resolved by the auto-timeout.
- Preserve idempotency: the repair path via `_handle_finalizing_retry()` must handle re-application of TIMEOUT marking safely.
- Do not introduce dashboard, reporting, aggregation, or intelligence changes.

---

## 10. Suggested Validation Steps

### Unit / integration tests (must be added)

1. **New test: gate_failure_with_started_run_transitions_to_failed_or_timeout** — audit has 1 STARTED run at finalization, window has ended, audit transitions deterministically out of `FINALIZING` (to `FAILED` or `COMPLETED` depending on chosen option).
2. **New test: started_run_at_window_close_auto_timeout** — if Option A: STARTED run is auto-marked as `TIMEOUT` before gate; gate passes Check 2; lifecycle reaches `COMPLETED` if S3 evidence exists for completed runs.
3. **New test: finalizing_permanently_stuck_regression** — invoke handler once with STARTED run, confirm `gate_failure` is NOT the terminal outcome (regression guard for the current bug).
4. **New test: retry_path_with_auto_timeout_resolves** — simulate `_handle_finalizing_retry()` path with prior STARTED run that is now auto-timed-out; gate passes; `COMPLETED` reached.
5. **Existing tests must still pass:** C-01 through C-05 (`test_execution_integrity_reconciliation.py`), all `test_phase3_cancellation_finalization.py` tests, E2E-01 (`test_execution_integrity_e2e.py`).

### Manual validation

1. Create a short-window audit where one scheduled execution is timed to still be in-flight at finalization time (or simulate by injecting a STARTED run record directly).
2. Trigger finalization.
3. Confirm audit reaches a terminal state (`COMPLETED` or `FAILED`) — never permanently in `FINALIZING`.
4. Confirm CloudWatch shows structured log evidence of the auto-timeout or FAILED transition.
5. Confirm no subsequent EventBridge schedules are left enabled (the one-time schedule is deleted by `ActionAfterCompletion=DELETE` upon successful invocation).

### Regression guard

After fixing, confirm the following scenario does NOT occur:
- Audit enters `FINALIZING`.
- Gate returns `gate_failure`.
- No further lifecycle transition occurs.
- Audit is still in `FINALIZING` 24 hours later.

---

## 10. Coverage Gap Analysis

The escalation requires investigation of eight specific scenarios. Status of each:

| Scenario | Status | Evidence |
|---|---|---|
| 1. Finalization schedule is `at()` one-time only | **Confirmed** | `builders.py:269-302` generates `at(...)`, `eventbridge_scheduler_client.py:45-46` sets `ActionAfterCompletion=DELETE` |
| 2. EventBridge fires once | **Confirmed** | One-time schedule with `ActionAfterCompletion=DELETE`; no re-fire mechanism |
| 3. Full `handle()` execution path | **Traced** | `handle()` lines 61-144; see execution path section |
| 4. STARTED runs can indefinitely block lifecycle progression | **Confirmed — this is the root cause** | Gate Check 2 is hard blocking; no recovery trigger exists |
| 5. Can audit with STARTED runs escape FINALIZING under current design? | **No — confirmed dead-end** | No component re-invokes finalization handler after `gate_failure` 200 response |
| 6. Late or missing execution results handled correctly? | **Not handled** — STARTED runs are silently blocking | No auto-timeout or forced-terminal path for in-flight runs at window close |
| 7. Lifecycle transitions idempotent? | **Partially** — terminal state check at line 66-76 prevents re-finalization; `FINALIZING` retry path exists but requires external trigger | `handle()` lines 66-79 |
| 8. Recovery after missed/failed finalization attempts | **Not implemented** | No repair job, no scheduled retry, no DLQ re-drive after `gate_failure` 200 response |

### Specific question answers

**Q: When the gate fails because of STARTED runs, what happens next?**
Nothing automatic. Handler returns `gate_failure` (200), schedule is deleted, audit stays in `FINALIZING` permanently.

**Q: The `_handle_finalizing_retry()` path is invoked when `current_state == FINALIZING`. But what triggers a retry?**
Nothing, after the gate returns `gate_failure` on the first invocation. The schedule is deleted. No re-trigger mechanism exists in the current design. The retry path is theoretically reachable only via manual Lambda invocation or a future repair mechanism.

**Q: Does the finalization handler have any mechanism to handle "partial completion"?**
No. The gate is all-or-nothing. No partial-completion (quorum) semantics exist.

**Q: Is the gate's STARTED-run check consistent with the requirement that audits must deterministically exit RUNNING regardless of individual run anomalies?**
No. Check 2 directly contradicts this requirement. If any run is STARTED at finalization time, the gate blocks and no auto-escape exists.

**Q: What is the relationship between `execution_counters.total_completed` and the gate's `execution_count` parameter?**
They are explicitly decoupled in the handler (lines 212-215). When STARTED runs exist, `gate_execution_count = terminal_count` (actual terminal records) rather than `execution_counters.total_completed`. They can diverge in the following case: a run completes after `get_audit_metadata()` reads `total_completed` but before `list_run_records()` is called. In this race, `total_completed` is higher than `terminal_count` by 1, causing Check 6 (`COUNTER_RECONCILIATION`) to also fire. The current handler compensates by setting `gate_execution_count = terminal_count`, which makes Check 1 pass, but Check 6 still fires because `counter_total_completed != actual_terminal_count` from the gate's perspective (the gate re-reads `execution_counters` from the `audit_for_gate` dict, which was set from the original `audit` fetched before run records were loaded).

---

## 11. Open Questions / Missing Evidence

1. **Is `TIMEOUT` a defined run status?** Confirm whether `RUN_STATUS_TIMEOUT` exists in `src/release_confidence_platform/core/constants/engine.py`. If not, it must be added before Option A is implementable. Alternatively, `FAILED` can be used for auto-terminated in-flight runs.

2. **Repository interface for updating run records at finalization**: the finalization handler currently reads run records (`list_run_records()`) but does not write them. Option A requires a `update_run_record()` or equivalent write method. Confirm whether this method exists on `AuditMetadataRepository` and whether the DynamoDB table schema supports it.

3. **Concurrency risk of auto-timeout**: if a scheduled execution is genuinely still in flight when the finalization handler auto-timeouts its run record, the execution handler may subsequently try to write a `COMPLETED` status to a run already marked `TIMEOUT`. Confirm whether the execution handler uses conditional writes that would reject this update, or whether the TIMEOUT record would be overwritten.

4. **Business decision on partial-completion semantics**: is it acceptable to treat an audit with 1 in-flight run as `COMPLETED` (if all terminal runs pass the gate, ignoring the TIMEOUT run)? Or must the audit fail? This requires product/architecture sign-off.

5. **Recovery for the specific stuck audit**: `audit_20260612_ba23618d` is currently in `RUNNING` (not `FINALIZING`) per the escalation, due to Bug 1 deployment gap (per `phase3_running_after_window_rca_v2.md`). Once deployed and manually re-invoked, if execution runs are in STARTED state, the audit will enter the `FINALIZING` dead-end described here. The recovery plan must account for this.

---

## 12. Final Investigator Decision

**FIXED on branch `bugfix/phase3-running-after-window-rca-v2` (2026-06-13).**

---

## 13. New HITL Validation Failure (2026-06-13) and Extended Root Cause Analysis

### New HITL Audit Evidence

- **audit_id:** `audit_20260613_50fe5b4c`
- `audit_window.end_time: 2026-06-13T01:57:41.375524Z`
- `updated_at: 2026-06-13T01:53:04.108468Z` — never updated after window end
- `lifecycle_state: RUNNING`
- Finalization schedule confirmed created: `at(2026-06-13T09:57:56)` Asia/Hong_Kong = `2026-06-13T01:57:56Z` UTC
- Schedule was deleted (ActionAfterCompletion=DELETE confirmed — schedule fired)
- Audit remains RUNNING permanently

### Confirmed Root Cause 1 (NEW): `_normalize_product_schedule_config` silently disables finalization schedule

**Location:**
- `packages/audit_scheduling/service.py` lines 274-275 (packages version)
- `src/release_confidence_platform/audit_scheduling/service.py` lines 280-281 (src version)

**Defect:**

```python
# DEFECTIVE CODE (before fix):
if "finalization_schedule" not in config:
    config["finalization_schedule"] = {"enabled": False}
```

When an audit config S3 file does not contain an explicit `finalization_schedule` key (the expected and common case for most real configs), `_normalize_product_schedule_config` injected `{"enabled": False}`. This caused `build_all()` line 108:

```python
if (config.get("finalization_schedule") or {"enabled": True}).get("enabled", True):
```

to evaluate the `or {"enabled": True}` fallback NEVER — because `{"enabled": False}` is truthy. The `.get("enabled", True)` on `{"enabled": False}` returned `False`. Result: `build_finalization()` was silently skipped. No finalization schedule was created. The audit would remain RUNNING indefinitely after the window.

This defect only affects the `schedule_from_persisted_audit` path (which calls `_normalize_product_schedule_config`). The `schedule_audit` path does NOT call this function and correctly uses the fallback.

**Fix:** Remove the injection of `{"enabled": False}` from `_normalize_product_schedule_config` in both `packages/` and `src/` versions. The comment now explains the intentional design.

### Confirmed Root Cause 2 (NEW): Unhandled `LifecycleConflictError` on RUNNING→FINALIZING transition

**Location:** `apps/backend/handlers/audit_finalization_handler.py` — `handle()` method, line 105-116

**Defect:**

```python
# DEFECTIVE CODE (before fix):
self.lifecycle.transition(
    LifecycleTransition(
        ...
        expected_current_state=current_state,  # RUNNING
        next_state=LIFECYCLE_STATE_FINALIZING,
        ...
    )
)
```

`AuditLifecycleService.transition()` calls `repository.append_lifecycle_transition()`, which executes a DynamoDB conditional update with `ConditionExpression="lifecycle_state = :expected_state"`. If the audit state has changed between the initial `get_audit_metadata()` read (line 63) and the DynamoDB update, `ConditionalCheckFailedException` is raised and re-raised as `LifecycleConflictError`.

`LifecycleConflictError` was NOT caught in `handle()`. The exception propagated as an unhandled Lambda failure. EventBridge Scheduler:
1. Marks the Lambda invocation as failed
2. Deletes the one-time `at()` schedule (ActionAfterCompletion=DELETE fires on first invocation regardless of Lambda outcome for `at()` schedules)

The audit remains permanently in RUNNING with no active finalization schedule and no automatic recovery path.

**Fix:** Wrap the `lifecycle.transition(RUNNING → FINALIZING)` call in a `try/except LifecycleConflictError` block. On conflict, re-read the audit state and handle idempotently:
- Terminal state → return skipped
- FINALIZING state → execute `_handle_finalizing_retry()`
- Any other unexpected state → call `_fail_unexpected_state_finalization()` to drive to FAILED

A new helper `_fail_unexpected_state_finalization()` was added to the handler to drive the audit to FAILED when no other terminal path is available.

### Fix Summary

**Files changed:**

| File | Change |
|---|---|
| `packages/audit_scheduling/service.py` | Removed `{"enabled": False}` injection for absent `finalization_schedule` key |
| `src/release_confidence_platform/audit_scheduling/service.py` | Same fix applied to src version |
| `apps/backend/handlers/audit_finalization_handler.py` | Added `LifecycleConflictError` import; wrapped RUNNING→FINALIZING transition with conflict handler; added `_fail_unexpected_state_finalization()` method |
| `tests/api/test_operator_cli_rcp_contract.py` | Updated test asserting old (wrong) behavior to assert correct behavior |
| `tests/unit/test_operator_cli_rcp.py` | Updated test asserting old (wrong) behavior to assert correct behavior |
| `tests/integration/test_phase3_lifecycle_determinism_regression.py` | New regression test file — 10 tests covering RCA-1, RCA-2, RCA-3, and audit list read-through |

**Test counts:**
- Before fixes: 407 tests passing
- After fixes: 417 tests passing (10 new regression tests)

### Root Cause Confidence

**RCA-1 (normalize config defect):** Confirmed Root Cause. The code was directly read; the injection was explicit. Two existing tests had been written to assert the defective behavior — both updated to assert correct behavior.

**RCA-2 (unhandled LifecycleConflictError):** Confirmed Root Cause. `LifecycleConflictError` is raised by `append_lifecycle_transition` on DynamoDB conditional update failure. The exception class is not imported or caught in `handle()`. The code path is fully traceable.

**New HITL audit remaining in RUNNING:** Most Likely Root Cause is RCA-2 (the Lambda crashed on `LifecycleConflictError` from a race condition, or the Lambda was not deployed with RCA-1 fix and the finalization schedule was never created for an audit config without explicit `finalization_schedule` key). Direct CloudWatch logs for the specific invocation are not available from repository artifacts — exact cause cannot be confirmed to High confidence from code alone.

### Final Decision

**Fixed. All 417 tests pass on branch `bugfix/phase3-running-after-window-rca-v2`.**
