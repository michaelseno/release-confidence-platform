# Bug Report: Phase 3 Audit Remains RUNNING After Window End (v2)

**audit_id:** `audit_20260612_ba23618d`
**client_id:** `client_rca_fix_v1_d39611f5`
**stage:** `dev`
**Reported:** 2026-06-13
**Investigator:** Bug Investigator (systematic-debugging skill applied)

---

## 1. Summary

Audit `audit_20260612_ba23618d` is stuck in `RUNNING` after its 2-hour audit window closed at `2026-06-12T16:36:25Z`. The expected lifecycle path is `RUNNING -> FINALIZING -> COMPLETED` (or `FAILED`). This is the third occurrence of the RUNNING-after-window pattern; the first two were fixed in `bugfix/execution-integrity-remediation` (commits `dba1ed5`, `e7ca123`). The most likely root cause is that the deployed `auditFinalization` Lambda in the AWS dev environment was **not updated** after the fix commits were merged to main, meaning the stale code ran against this audit and failed before the `RUNNING -> FINALIZING` transition for the same reason as Bug 1 (Decimal serialization failure in `_log_finalization()`).

A confirmed secondary finding is that the current finalization handler contains **no top-level exception handler** for `FinalizationGateError` raised from `_complete_finalization()` — meaning a gate failure after `RUNNING -> FINALIZING` transition would also leave the audit stuck (at `FINALIZING`), though that does not explain the `RUNNING` state observed here.

---

## 2. Investigation Context

- **Source of report:** HITL / post-window audit state observation.
- **Branch context:** `main` (commits `dba1ed5`, `e7ca123` are the latest merged execution integrity remediation).
- **Related workflow:** Phase 3 scheduled audit finalization triggered by EventBridge Scheduler one-time `at()` schedule at audit window end.
- **Affected audit:**
  - `client_id`: `client_rca_fix_v1_d39611f5`
  - `audit_id`: `audit_20260612_ba23618d`
  - `audit_window.start_time`: `2026-06-12T14:36:25.756230Z`
  - `audit_window.end_time`: `2026-06-12T16:36:25.756230Z`
  - `audit_window.timezone`: `Asia/Hong_Kong`
  - `created_at`: `2026-06-12T14:36:28.204673Z`
  - `updated_at`: `2026-06-12T16:32:24.753015Z`
  - `current lifecycle_state`: `RUNNING`
- **Reporting command:** `rcp audit list` (reads DynamoDB directly via `DiscoveryListService.list_audits()` — no stale cache concern).
- **Prior bug context:** Bug 1 (`hitl_phase_3_running_after_window_bug_report.md`) was a Decimal serialization failure in `_log_finalization()`. Bug 2 (`phase_3_finalization_cleanup_bug_report.md`) was `FINALIZING` never reaching `COMPLETED`. Both fixed in commits `dba1ed5`/`e7ca123`.

---

## 3. Observed Symptoms

- **Command:** `rcp audit list --client-id client_rca_fix_v1_d39611f5 --stage dev`
- **Observed behavior:** audit `audit_20260612_ba23618d` reports `lifecycle_state = RUNNING` after `2026-06-12T16:36:25Z`.
- **Expected behavior:** at or after `audit_window.end_time`, the EventBridge Scheduler finalization event fires the `auditFinalization` Lambda, which transitions the audit `RUNNING -> FINALIZING -> COMPLETED` (nonzero executions) or `RUNNING -> FINALIZING -> FAILED` (zero executions).
- **Key anomaly:** `updated_at = 2026-06-12T16:32:24.753015Z` — 4 minutes and 1 second before window close (`16:36:25Z`). The audit was actively executing until very close to finalization time. No finalization-related `lifecycle_history` entries are present (inferred from the RUNNING state).

---

## 4. Evidence Collected

### 4.1 Audit config: `.local-configs/client_rca_fix_v1_d39611f5/audits/audit_20260612_ba23618d/audit_config.json`

The config has:
```json
"audit_window": {
  "duration_hours": 2,
  "timezone": "Asia/Hong_Kong"
}
```
No `start_time` or `end_time` is present. `finalization_schedule.enabled = true`.

### 4.2 `validate_audit_window()` — `src/release_confidence_platform/audit_scheduling/safeguards.py:108-133`

When no `start_time` is present, the function defaults to `now = datetime.now(UTC)` at the moment of the scheduling call. At the time of scheduling (≈ `created_at = 2026-06-12T14:36:28Z`), this produced:

- `start_time = 2026-06-12T14:36:25.756230Z` (matches defect report)
- `end_time = start_time + timedelta(hours=2) = 2026-06-12T16:36:25.756230Z` (matches defect report)

The `start_time` and `end_time` in the defect report are dynamically computed at scheduling time from `utc_now()`, not static config values. **This is expected behavior and is not the defect.**

### 4.3 `_normalize_product_schedule_config()` — `src/release_confidence_platform/audit_scheduling/service.py:259-282`

- `finalization_schedule` is present in config (`{"enabled": true}`) and is NOT overwritten (line 280: only sets disabled default if key is absent).
- `baseline_schedule` is present → remapped to `config["baseline"]`.
- `repeated_schedule` is present → remapped to `config["repeated"] = [repeated_schedule_dict]`.

### 4.4 `ScheduleBuilder.build_all()` — `src/release_confidence_platform/audit_scheduling/builders.py:99-113`

Line 111: `(config.get("finalization_schedule") or {"enabled": True}).get("enabled", True)` evaluates to `True`. `build_finalization()` is called.

### 4.5 `build_finalization()` — `src/release_confidence_platform/audit_scheduling/builders.py:269-302`

- Uses `audit_window["end_time"] = "2026-06-12T16:36:25.756230Z"`.
- `expression_timezone = audit_window.get("timezone") = "Asia/Hong_Kong"` (UTC+8).
- `eventbridge_scheduler_at_datetime("2026-06-12T16:36:25.756230Z", schedule_expression_timezone="Asia/Hong_Kong")` converts `16:36:25Z` → `00:36:25+08:00 (next day)` and strips microseconds.
- **Generated expression:** `at(2026-06-13T00:36:25)` with `ScheduleExpressionTimezone = Asia/Hong_Kong`.
- This is **semantically correct**: EventBridge interprets `00:36:25` as Asia/Hong_Kong local time, which is `2026-06-12T16:36:25Z` UTC.
- This schedule was valid and future-dated at scheduling time. EventBridge Scheduler would accept it.

**H1 (finalization schedule not created): Ruled out.** The audit executed through its window (updated_at shows activity at 16:32Z); scheduling was successful or the audit would not have reached RUNNING. build_all() always calls build_finalization() when enabled, and it is enabled.

**H2 (malformed or past at() expression): Ruled out.** The expression is correctly computed and was ~2 hours in the future at scheduling time.

### 4.6 Lifecycle TRANSITIONS — `src/release_confidence_platform/audit_lifecycle/constants.py:45-48`

```python
LIFECYCLE_STATE_RUNNING: (
    LIFECYCLE_STATE_FINALIZING,
    LIFECYCLE_STATE_FAILED,
    LIFECYCLE_STATE_CANCELLED,
)
```

`RUNNING -> FINALIZING` is a valid transition. The handler at line 105 passes `expected_current_state=current_state` (which is `RUNNING`) and `next_state=LIFECYCLE_STATE_FINALIZING`. This will succeed if reached.

### 4.7 `AuditFinalizationHandler.handle()` — `apps/backend/handlers/audit_finalization_handler.py:61-139`

Execution path for `current_state = RUNNING`:

1. **Line 62:** `validate_finalization_event(event)` — validates payload. Standard payload from `build_finalization()` includes all required fields: `event_type`, `client_id`, `audit_id`, `schedule_name`, `triggered_by`, `audit_window_end`, `schedule_occurrence_id`. No reason to fail here.
2. **Line 63:** `self.repository.get_audit_metadata(...)` — DynamoDB read. Transient failure would be retried by Lambda; persistent failure is extremely unlikely for an active audit.
3. **Line 64:** `current_state = audit["lifecycle_state"]` → `"RUNNING"`.
4. **Line 66:** `RUNNING not in TERMINAL_STATES` → skip terminal branch.
5. **Line 78:** `RUNNING != LIFECYCLE_STATE_FINALIZING` → skip finalizing-retry branch.
6. **Line 81-83:** `execution_count = _normalize_execution_count((audit.get("execution_counters") or {}).get("total_completed", 0))`.
   - DynamoDB returns numeric fields as `Decimal`. `_normalize_execution_count(Decimal("N"))` returns `int(N)` in the **fixed** code (lines 452-456). This is safe.
   - In the **stale (pre-fix) code**, `Decimal` is passed directly to `_log_finalization()`.
7. **Lines 96-104:** `self._log_finalization("auditFinalization_transition_requested", ...)` with `execution_count=execution_count`.
   - **In fixed code:** `execution_count` is already an `int` → `StructuredLogger.log(...)` serializes cleanly → no failure.
   - **In stale pre-fix code:** `execution_count` is a `Decimal` → `StructuredLogger.log(...)` calls `json.dumps(...)` without a Decimal-safe encoder → **`TypeError: Object of type Decimal is not JSON serializable`** → Lambda fails here, BEFORE line 105.
8. **Line 105 (only reached on fixed code):** `lifecycle.transition(... RUNNING -> FINALIZING ...)`.

**The RUNNING state observed is only possible if:**
- (a) The handler was never invoked (H1 — ruled out), OR
- (b) The handler failed before line 105.

**The only failure modes before line 105 consistent with the RUNNING state are:**
- Serialization failure in `_log_finalization()` due to `Decimal` execution_count — **the identical Bug 1 pattern**.
- An unhandled exception in `get_audit_metadata()` — unlikely for an actively-executing audit.
- A malformed finalization event — no evidence.

**H4 (schedule fired before fix was deployed): Ruled out.** The audit was created `2026-06-12T14:36:28Z`, which is 21 hours 48 minutes after the fix commits (`dba1ed5` at `2026-06-11T16:47:58Z` UTC). The schedule fires at window end `16:36:25Z` — also well after the fix commit.

### 4.8 Fix commit timing vs Lambda deployment

- Fix commits (`dba1ed5`, `e7ca123`) merged to main: **`2026-06-11T16:47:58Z` UTC**.
- Affected audit `created_at`: **`2026-06-12T14:36:28Z` UTC** — 21h 49min after merge.
- QA report (`docs/qa/execution_integrity_qa_report.md`): all 17 regression tests pass; WS-E (cloud infrastructure / Lambda deployment validation) is **explicitly marked out of scope**.
- No record in the repository of a `sls deploy` or Lambda redeployment between the fix commit and this audit's creation.
- Prior incident data (from `phase_3_phase_4_execution_integrity_rca.md`): `auditFinalization` Lambda `LastModified = 2026-06-04T14:22:04.000+0000` as of `2026-06-09`. If not redeployed since then, the Lambda binary for the audit's finalization event at `16:36:25Z` on `2026-06-12` was still the pre-fix code.

**H5 (stale Lambda deployment, fix in code but not deployed): This is the most likely root cause.** The fix exists in the repository but was not deployed to the AWS dev environment before this audit's finalization window. The deployed Lambda ran the pre-fix code, hit the Decimal serialization error in `_log_finalization()`, and failed before the `RUNNING -> FINALIZING` transition.

### 4.9 State-based deduction

The lifecycle state `RUNNING` is a hard diagnostic constraint:

- If `FinalizationGateError` were raised (gate failure), the audit would be in `FINALIZING` (transition at line 105 completes before gate runs in `_complete_finalization()`).
- If handler was never invoked, lifecycle state remains `RUNNING`.
- If handler failed before line 105 (`validate_finalization_event`, `get_audit_metadata`, or `_log_finalization`), lifecycle state remains `RUNNING`.

Gate failures, `_complete_finalization` exceptions, and any failure AFTER line 105 cannot produce `RUNNING` state. Only pre-transition failure or no-invocation produces `RUNNING`.

### 4.10 Prior bug pattern recurrence

Bug 1 (hitl_phase_3_running_after_window_bug_report.md):
- Lambda `LastModified = 2026-06-03T14:28:26Z`, audit `created_at = 2026-06-03T14:45:16Z`.
- Lambda was stale → Decimal bug hit → audit stuck in `RUNNING`.
- Fix: normalize `Decimal` to `int` before logging.

Current defect:
- Fix merged `2026-06-11T16:47:58Z`, audit `created_at = 2026-06-12T14:36:28Z`.
- QA validated the fix in code; WS-E (deployment) was out of scope.
- If Lambda not redeployed → same Decimal bug hit → audit stuck in `RUNNING`.

**The recurrence pattern is identical: fix exists in code, Lambda binary in dev is stale.**

### 4.11 Secondary finding: uncaught `FinalizationGateError`

In `AuditFinalizationHandler.handle()` (lines 61-139), `_complete_finalization()` at lines 129-135 can raise `FinalizationGateError`. The `handle()` method has no `try/except` around the `_complete_finalization()` call. If the integrity gate fails after `RUNNING -> FINALIZING` transition:
- The gate error propagates to the Lambda function entry point at line 459.
- The Lambda fails and returns a 500-class error to EventBridge.
- The audit state is `FINALIZING` (transition completed).
- EventBridge may retry the schedule invocation.
- On retry, `current_state == LIFECYCLE_STATE_FINALIZING` → `_handle_finalizing_retry()` path (line 79).

This means gate failures leave the audit in `FINALIZING`, not `RUNNING`. This is not the cause of the current defect, but it is a latent operational concern: there is no structured error response that distinguishes gate failure (evidence mismatch) from a transient Lambda error. Both cause Lambda failure and potential infinite retry behavior unless the EventBridge schedule's `ActionAfterCompletion=DELETE` ensures no retry.

---

## 5. Execution Path / Failure Trace

### Reconstructed path (stale Lambda hypothesis)

1. **Scheduling (≈ `2026-06-12T14:36:28Z`):** Operator ran `rcp audit schedule`. `_normalize_product_schedule_config()` remapped `finalization_schedule` correctly. `validate_audit_window()` computed `start_time = 14:36:25.756230Z`, `end_time = 16:36:25.756230Z` from `utc_now()`. `build_all()` called `build_finalization()`. Generated: `at(2026-06-13T00:36:25)` with `ScheduleExpressionTimezone = Asia/Hong_Kong`. EventBridge Scheduler created the one-time finalization schedule.

2. **Execution window (`14:36:25Z` – `16:32:24Z`):** Scheduled execution occurrences ran. Audit transitioned `SCHEDULED -> RUNNING` on first execution. `execution_counters.total_completed` accumulated. `updated_at = 2026-06-12T16:32:24.753015Z` is the last confirmed execution event — 4 minutes 1 second before window close.

3. **Finalization trigger (`≈ 16:36:25Z`):** EventBridge Scheduler fired the finalization one-time schedule. Lambda `auditFinalization` was invoked.

4. **Handler entry — stale Lambda path:**
   - `validate_finalization_event(event)` passed.
   - `get_audit_metadata(...)` returned audit item with `lifecycle_state = RUNNING` and `execution_counters.total_completed = Decimal("N")` (DynamoDB numeric type).
   - `_normalize_execution_count(Decimal("N"))` in **stale code** returned the `Decimal` unchanged (the normalization in the stale version did not exist or was incomplete — see Bug 1 root cause).
   - `_log_finalization("auditFinalization_transition_requested", ..., execution_count=Decimal("N"), ...)` called `StructuredLogger.log(...)`.
   - `json.dumps(record, sort_keys=True)` raised `TypeError: Object of type Decimal is not JSON serializable`.
   - Lambda function failed with unhandled exception before `lifecycle.transition(RUNNING -> FINALIZING)` at line 105.

5. **Post-failure:** EventBridge retried the Lambda (Lambda error → EventBridge retry policy). If `ActionAfterCompletion` was `NONE` in the stale code (pre-fix), retries also fail the same way. If `ActionAfterCompletion` was set to `DELETE` in a partially-deployed state, the schedule was consumed and no retries occurred.

6. **Audit remains `RUNNING`** because no lifecycle write succeeded. `updated_at` is frozen at `16:32:24.753015Z` (last execution write, not finalization write).

---

## 6. Failure Classification

- **Primary classification:** Environment / Configuration Issue (deployment gap: code fix merged, Lambda not redeployed to dev).
- **Contributing classification:** Application Bug (the underlying Decimal serialization defect is the same Application Bug from Bug 1; it recurs because the fix was not deployed).
- **Severity:** Blocker. Prevents audit lifecycle completion. Recurs deterministically for any audit created after the fix commit but before Lambda redeployment.
- **Reproducibility:** Always reproducible — any audit created after the fix commit but finalized against the stale Lambda will fail the same way for DynamoDB-backed execution counters.

---

## 7. Root Cause Analysis

### Most Likely Root Cause

**Deployment gap: execution integrity fix (`dba1ed5`, `e7ca123`) was merged to main but the `auditFinalization` Lambda in AWS dev was not redeployed.**

- **Immediate failure point:** `_log_finalization()` in `audit_finalization_handler.py` at approximately line 96 (in the stale code), before `lifecycle.transition(RUNNING -> FINALIZING)` at line 105.
- **Underlying cause:** The stale deployed Lambda code attempts to pass a DynamoDB `Decimal` execution counter directly to `StructuredLogger.log(...)`, which calls `json.dumps(...)` without a Decimal-safe encoder. This is the identical failure mode from Bug 1.
- **Supporting evidence:**
  - Audit `updated_at = 16:32:24Z`, window ended `16:36:25Z`. Active execution confirmed → scheduling was successful → finalization schedule was created → finalization event was fired by EventBridge.
  - Audit is in `RUNNING`, not `FINALIZING`. State-based deduction: handler failed BEFORE `lifecycle.transition()` at line 105. The only pre-transition failure consistent with this pattern is the `_log_finalization()` Decimal serialization error.
  - QA report confirms fix works in code but explicitly marks deployment (WS-E) as out of scope.
  - No repository artifact records a `sls deploy` between fix commit (`2026-06-11T16:47:58Z`) and audit creation (`2026-06-12T14:36:28Z`).
  - Prior Lambda `LastModified = 2026-06-04T14:22:04Z` (from `phase_3_phase_4_execution_integrity_rca.md`) predates the fix commit by 7 days 12 hours 44 minutes. If not redeployed after the fix, the binary in dev on `2026-06-12T16:36:25Z` was still the pre-fix code.
  - Bug 1 was caused by this exact failure in the same Lambda under the same conditions (DynamoDB Decimal counter + `_log_finalization()` serialization path).

### Plausible Contributing Factors

1. **No deployment gate in the QA/HITL workflow:** WS-E (deployment validation) was explicitly out of scope in the QA report. This left a gap between code-level fix validation and live Lambda behavior.

2. **No deployment verification step after merge:** The fix was merged but no artifact (CloudWatch log, Lambda LastModified confirmation, or CI deployment record) confirms the Lambda binary was updated before the affected audit was created.

3. **No automatic rollforward mechanism:** The finalization schedule fires once. If the Lambda is stale and fails, there is no automatic recovery path; the audit remains stuck in `RUNNING` indefinitely.

---

## 8. Confidence Level

**Medium-High.**

The circumstantial evidence is strong and the pattern is consistent with the prior Bug 1 root cause:
- RUNNING state (not FINALIZING) localizes the failure to the pre-transition window of the handler.
- The only pre-transition failure mode consistent with this pattern for a healthy DynamoDB audit is Decimal serialization in `_log_finalization()`.
- QA report does not confirm Lambda deployment; no deployment artifact exists in the repository.
- Timing alignment: fix merged `2026-06-11T16:48Z`, audit created `2026-06-12T14:36Z`, finalization fired `16:36Z` — deployment window is exactly the missing gap.

Confidence is **not High** because:
- No direct CloudWatch log for this audit's finalization invocation is available from repository artifacts. The `TypeError: Object of type Decimal is not JSON serializable` stack trace cannot be confirmed without CloudWatch access.
- Lambda `LastModified` for the affected audit's finalization window cannot be confirmed without AWS API access.
- A different pre-transition failure (e.g., transient DynamoDB error at `get_audit_metadata()`) cannot be fully excluded from code artifacts alone.

---

## 9. Recommended Fix

### Primary fix (infrastructure owner)

**Deploy the execution integrity fix to the AWS dev environment.**

Run `sls deploy --stage dev` (or the equivalent deployment command for this project) from a clean working tree on the `main` branch with the latest fix commits. This will update the `auditFinalization` Lambda binary to the fixed code that correctly normalizes `Decimal` execution counters before logging.

After deployment, verify `auditFinalization` Lambda `LastModified` is after `2026-06-11T16:47:58Z`.

### Recovery fix (operations / release manager)

The stuck audit `audit_20260612_ba23618d` will not self-heal. Options:
1. Manually re-invoke the finalization Lambda with the correct finalization event payload after the fix is deployed. The handler is idempotent for `RUNNING` state: it will transition `RUNNING -> FINALIZING -> COMPLETED` or `RUNNING -> FINALIZING -> FAILED` depending on execution count.
2. Alternatively, create a fresh validation audit to confirm the fix is working end-to-end.

Manual replay must be release-manager/user-approved and must use the correct `event_type = "audit_finalization"` payload matching the `validate_finalization_event()` contract.

### Process fix (QA / release process)

Add a deployment gate to the release workflow:
- After any fix branch is merged to main, require a `sls deploy --stage dev` and a CloudWatch confirmation log (e.g., a test finalization invocation against a short-window audit) before the branch is considered fully remediated.
- Mark WS-E as in-scope for all QA cycles that modify Lambda code paths in `apps/backend/handlers/`.

### Secondary code fix (backend)

Add a top-level exception handler in `AuditFinalizationHandler.handle()` for `FinalizationGateError` so that gate failures return a structured `{"status": "gate_failure", "lifecycle_state": "FINALIZING"}` response instead of propagating as an unhandled exception. This prevents EventBridge from treating a gate failure as a transient Lambda error and retrying indefinitely. This fix is not related to the current `RUNNING` defect but prevents future `FINALIZING`-stuck scenarios under gate failure conditions.

- **Owner:** backend
- **File:** `apps/backend/handlers/audit_finalization_handler.py`
- **Scope:** wrap lines 129-139 (`_complete_finalization(...)` and `_trigger_aggregation_after_finalization(...)`) in a `try/except FinalizationGateError` block that logs the gate failure and returns a structured failure response without re-raising.

---

## 10. Suggested Validation Steps

### Deployment validation (required first)

1. Run `aws lambda get-function --function-name release-confidence-platform-dev-auditFinalization` and confirm `LastModified` is after `2026-06-11T16:47:58Z`.
2. Alternatively, check CloudWatch `/aws/lambda/release-confidence-platform-dev-auditFinalization` for a `auditFinalization_transition_requested` structured log entry — this log line only appears in the fixed code path, never in the stale pre-fix code.

### Fix validation (new audit)

1. Create a fresh short-window audit (e.g., 5-10 minute window) with `finalization_schedule.enabled = true`.
2. Wait for the finalization window to pass.
3. Confirm CloudWatch `/aws/lambda/release-confidence-platform-dev-auditFinalization` shows:
   - `auditFinalization_transition_requested` (no TypeError)
   - `auditFinalization_completed` (FINALIZING → COMPLETED)
4. Confirm `rcp audit list` shows the audit in `COMPLETED`.
5. Confirm `execution_counters.total_completed` in DynamoDB is an integer (not Decimal) when retrieved via `get_audit_metadata`.

### Regression guard

1. Run `pytest tests/integration/test_phase3_cancellation_finalization.py` — all 15 pre-existing tests should pass.
2. Run `pytest tests/integration/test_execution_integrity_reconciliation.py` — all gate reconciliation tests should pass.
3. Run `pytest tests/integration/test_execution_integrity_e2e.py` — E2E-01 full lifecycle test should pass.
4. Confirm no `TypeError: Object of type Decimal is not JSON serializable` in CloudWatch for any finalization invocation after deployment.

### Stuck audit recovery validation

If the stuck audit is replayed manually:
1. Verify `lifecycle_history` for `audit_20260612_ba23618d` shows `RUNNING -> FINALIZING` and then `FINALIZING -> COMPLETED` or `FINALIZING -> FAILED` with correct `actor = finalization_handler`.
2. Verify `finalization.execution_count` is recorded and is a positive integer.
3. Verify `updated_at` advances to the recovery time.

---

## 11. Open Questions / Missing Evidence

1. **Lambda LastModified confirmation:** The repository does not contain a deployment artifact confirming whether `auditFinalization` Lambda was redeployed after commit `dba1ed5` (`2026-06-11T16:47:58Z`). This is the single most important missing piece. If `LastModified > 2026-06-11T16:47:58Z`, the stale-deployment hypothesis is eliminated and a different pre-transition failure must be investigated.

2. **CloudWatch log for finalization invocation:** No CloudWatch evidence is available in repository artifacts for the finalization Lambda invocation at `≈ 2026-06-12T16:36:25Z`. The `TypeError` stack trace (if present) would confirm Bug 1 recurrence. If no invocation exists in CloudWatch, it would indicate the schedule was never fired (requiring re-evaluation of H1).

3. **EventBridge Scheduler schedule state:** The finalization schedule `at(2026-06-13T00:36:25)` TZ=Asia/Hong_Kong should be queried. If it exists and is `ENABLED` with `ActionAfterCompletion=NONE`, that confirms the stale pre-fix code ran (since the fix adds `DELETE`). If the schedule is absent, EventBridge deleted it — but it may have been deleted due to a successful invocation that still failed before the DynamoDB transition.

4. **Zero-execution edge case:** `execution_counters.total_completed` for this audit is not confirmed from repository artifacts. If total_completed was 0 at finalization time (e.g., no executions completed before the window), `_normalize_execution_count` returns 0, and the handler would attempt `RUNNING -> FINALIZING -> FAILED` rather than `-> COMPLETED`. This would still be blocked by the Decimal bug on the pre-fix code. The path through `_fail_zero_execution_finalization` is irrelevant to the `RUNNING` state — it can only be reached after the `RUNNING -> FINALIZING` transition at line 105.

5. **Recovery decision:** No determination has been made on whether the stuck audit should be manually recovered or abandoned. This requires release-manager / user direction.

---

## 12. Final Investigator Decision

**Ready for developer fix — deployment action required first.**

The most likely root cause (stale Lambda deployment) is an infrastructure/deployment action, not a code change. The code fix already exists on `main`. The required action is:

1. Deploy `main` to the AWS dev environment.
2. Verify Lambda `LastModified` confirms the redeployment.
3. Decide on recovery action for `audit_20260612_ba23618d`.
4. Run end-to-end validation with a fresh short-window audit.

If after Lambda redeployment the next validation audit still gets stuck in `RUNNING`, escalate to investigate a new pre-transition failure mode (H3) with CloudWatch logs as primary evidence.

The secondary code fix (top-level `FinalizationGateError` handler in `handle()`) should be routed to the backend developer as a separate, non-urgent improvement.

---

## Round 3 Update — Lambda Packaging Root Cause Confirmed

**Updated:** 2026-06-13
**Status:** Root cause confirmed via direct CloudWatch evidence. Supersedes the Round 2 stale-deployment hypothesis.

---

### Summary

The Round 2 hypothesis (stale Lambda deployment, Decimal serialization failure) was directionally correct in identifying that the `auditFinalization` Lambda was not working, but did not identify the specific defect. CloudWatch logs obtained after Round 2 provide direct, unambiguous evidence of the actual failure mechanism: the Lambda crashes at **module import time** due to a PYTHONPATH packaging defect, before any application logic executes.

The root cause is that `apps/backend/handlers/audit_finalization_handler.py` has no `sys.path` manipulation at module level, and the Lambda deployment does not set `PYTHONPATH=/var/task/src`, so `import release_confidence_platform` fails immediately on every invocation.

---

### CloudWatch Evidence

CloudWatch logs for the `auditFinalization` Lambda show the following error on **every invocation** after the audit window ended:

```
Runtime.ImportModuleError:
Unable to import module 'apps.backend.handlers.audit_finalization_handler'
No module named 'release_confidence_platform'
```

This error occurs at the Python module initialization stage — before the `handler()` function is entered, before `validate_finalization_event()` is called, and before any DynamoDB reads or lifecycle transitions execute. No application logic runs on any invocation.

**Affected audit (Round 3):**
- `client_id`: `client_rca_fix_v3_8f494019`
- `audit_id`: `audit_20260613_f9414534`
- `audit_window.end`: `2026-06-13T04:52:08.476253Z`
- `lifecycle_state`: `RUNNING` (stuck)
- `updated_at`: `2026-06-13T04:47:36.794650Z`

---

### Packaging Analysis

**File:** `/Users/mjseno/Documents/Development/2026_fortfolio_projects/release-confidence-platform/infra/serverless.yml`

The `package.patterns` configuration correctly includes:

```yaml
- '../src/release_confidence_platform/__init__.py'
- '../src/release_confidence_platform/aggregation/**'
- '../src/release_confidence_platform/audit_lifecycle/**'
- '../src/release_confidence_platform/storage/**'
- '../src/release_confidence_platform/core/**'
- '../src/release_confidence_platform/sanitization/**'
```

These patterns deploy `release_confidence_platform` to `/var/task/src/release_confidence_platform/` inside the Lambda runtime.

Lambda's default `sys.path` includes `/var/task` but NOT `/var/task/src`. When Python attempts `import release_confidence_platform`, it looks for `/var/task/release_confidence_platform/` — which does not exist. The package lives at `/var/task/src/release_confidence_platform/` and is therefore invisible to the Python import system.

---

### Why `aggregation_handler.py` Works But `audit_finalization_handler.py` Does Not

`aggregation_handler.py` line 11 contains:

```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))
```

This executes at module load time and inserts `/var/task/src` into `sys.path` **before** any `release_confidence_platform` imports are attempted. All subsequent imports succeed.

`audit_finalization_handler.py` has no equivalent `sys.path` manipulation. The module-level imports at lines 30–42 (which include `from release_confidence_platform.audit_lifecycle import ...` and similar) execute before the `handler()` function runs. Python raises `ModuleNotFoundError: No module named 'release_confidence_platform'` during these module-level imports, which the Lambda runtime surfaces as `Runtime.ImportModuleError`. The Lambda terminates immediately.

---

### Why `scheduled_execution_handler.py` and `orchestrator_handler.py` Are Unaffected

Both handlers import exclusively from `packages.*` and `apps.backend.*`. These modules are deployed under `/var/task/packages/` and `/var/task/apps/` respectively, both of which are on the default Lambda `sys.path` under `/var/task`. Neither handler imports from `release_confidence_platform` at module level, so neither is affected by the missing `/var/task/src` path entry.

---

### Fix Strategy

#### Primary fix (systemic — infrastructure owner)

Add `PYTHONPATH: /var/task/src` to the Lambda provider environment block in `infra/serverless.yml`:

```yaml
provider:
  environment:
    PYTHONPATH: /var/task/src
```

This ensures all Lambdas resolve `release_confidence_platform` regardless of which handler file they use. It applies globally at deploy time and cannot regress silently when new handlers are added. This is superior to per-handler `sys.path.insert` workarounds because it does not depend on handler authors remembering to add path manipulation code.

#### Secondary cleanup (backend owner)

Once `PYTHONPATH` is set in `serverless.yml`, remove the `sys.path.insert` workaround from `aggregation_handler.py` line 11. The workaround is no longer needed and leaving it in place creates confusing redundancy and obscures the true mechanism that makes imports work.

- **File:** `apps/backend/handlers/aggregation_handler.py`
- **Scope:** Remove `sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))` and the `import os`, `import sys` lines if they are unused after removal.

---

### DynamoDB Result Records — Not a Separate Defect

A secondary question in the HITL brief asked whether DynamoDB result records (RUN records) are expected to exist before finalization runs.

Based on code analysis:

- RUN records are written during execution via `AuditMetadataRepository` during the orchestration path, not during finalization. They SHOULD be present before finalization if executions occurred.
- The `audit_finalization_handler.py` calls `self.repository.list_run_records()` inside `_complete_finalization()`, which is reached only after the `RUNNING -> FINALIZING` lifecycle transition at line 105.
- Because the `auditFinalization` Lambda crashes at import time (before `handler()` is entered), `list_run_records()` is never called on any invocation.

**The absence of DynamoDB result observation during finalization is a consequence of the Lambda crash, not an independent defect.** There is no evidence of a separate data/fixture or persistence issue. This question is resolved: not a defect.

---

### Confidence Level: HIGH

Round 2 confidence was Medium-High (circumstantial, no CloudWatch access). Round 3 confidence is **High** based on:

- Direct CloudWatch error message: `Runtime.ImportModuleError: Unable to import module 'apps.backend.handlers.audit_finalization_handler' — No module named 'release_confidence_platform'`. This is deterministic, not intermittent.
- Code-level confirmation: `audit_finalization_handler.py` has no `sys.path` manipulation; `aggregation_handler.py` does. The behavioral difference between the two handlers is fully explained by this structural difference.
- Packaging analysis confirms `release_confidence_platform` is deployed under `/var/task/src/` (not `/var/task/`), and Lambda `sys.path` does not include `/var/task/src` by default.
- The Round 2 `Decimal` serialization hypothesis is now superseded. The handler never reached the `_log_finalization()` call — it failed before `handler()` was entered.

---

### Updated Final Investigator Decision

**Ready for developer fix — packaging defect confirmed.**

Required actions:
1. Add `PYTHONPATH: /var/task/src` to the `provider.environment` block in `infra/serverless.yml`.
2. Deploy to the AWS dev environment (`sls deploy --stage dev`).
3. Verify CloudWatch no longer shows `Runtime.ImportModuleError` for `auditFinalization` invocations.
4. Run a fresh short-window audit and confirm end-to-end `RUNNING -> FINALIZING -> COMPLETED` lifecycle transition.
5. As a follow-on cleanup, remove the `sys.path.insert` workaround from `aggregation_handler.py` once the `PYTHONPATH` fix is deployed and validated.
