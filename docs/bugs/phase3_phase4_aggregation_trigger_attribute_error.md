# Bug Report

## 1. Summary

`AttributeError: 'AuditMetadataRepository' object has no attribute 'aggregation_job_keys'` raised at runtime when `_trigger_aggregation_after_finalization` calls `self.repository.aggregation_job_keys(...)`. The Lambda handler imports `AuditMetadataRepository` from `packages/storage/audit_metadata_client.py`, which is missing three aggregation-related methods that were added exclusively to the canonical `src/release_confidence_platform/storage/audit_metadata_client.py` version and never backported to the `packages/` mirror. The error fires after the audit lifecycle has already transitioned to `COMPLETED`, leaving the aggregation chain silently broken and no release confidence report produced.

---

## 2. Investigation Context

- Source: Confirmed runtime AttributeError, reproduction run against AWS environment
- Feature / workflow: Phase 4 aggregation trigger — `_trigger_aggregation_after_finalization` called from `AuditFinalizationHandler` after `_complete_finalization` succeeds
- Branch context: `bugfix/phase3-running-after-window-rca-v2`
- Validation audit: `audit_id: audit_20260614_9274a028`, `client_id: client_rca_fix_v5_cf04e89f`
- Entry points:
  - Line 182 of `apps/backend/handlers/audit_finalization_handler.py` — normal finalization path
  - Line 210 — finalizing-retry path
- Failing call: `self.repository.aggregation_job_keys(event["client_id"], event["audit_id"], job_id)` at handler line 437

---

## 3. Observed Symptoms

**Error at runtime:**
```
AttributeError: 'AuditMetadataRepository' object has no attribute 'aggregation_job_keys'
```

**Failing call chain:**
1. `handler()` at line 594 instantiates `AuditMetadataRepository` from `packages.storage.audit_metadata_client` (line 596)
2. Passes the instance as `repository` to `AuditFinalizationHandler`
3. `_trigger_aggregation_after_finalization` is called at line 182 (or 210 on retry)
4. Line 437 calls `self.repository.aggregation_job_keys(...)` — method does not exist on the `packages/` class
5. Python raises `AttributeError`

**Observed behavior:** The `AttributeError` fires after the COMPLETED transition is written. The audit lifecycle state is `COMPLETED` in DynamoDB, but no aggregation job intent record is written, no Lambda invocation is attempted, and the release confidence report is never produced.

**Expected behavior:** After COMPLETED is written, `_trigger_aggregation_after_finalization` records an aggregation job intent item in DynamoDB and invokes the aggregation Lambda, enabling end-to-end report generation.

---

## 4. Evidence Collected

**Files inspected:**

| File | Finding |
|------|---------|
| `apps/backend/handlers/audit_finalization_handler.py` line 27 | Imports `AuditMetadataRepository` from `packages.storage.audit_metadata_client` |
| `apps/backend/handlers/audit_finalization_handler.py` line 596 | Instantiates `AuditMetadataRepository(os.environ["METADATA_TABLE"], table)` |
| `apps/backend/handlers/audit_finalization_handler.py` line 437 | Calls `self.repository.aggregation_job_keys(event["client_id"], event["audit_id"], job_id)` |
| `packages/storage/audit_metadata_client.py` | `AuditMetadataRepository` class ends at line 227. `aggregation_job_keys`, `put_aggregation_job_intent_once`, and `update_aggregation_job_intent` are absent. |
| `src/release_confidence_platform/storage/audit_metadata_client.py` line 42 | `aggregation_job_keys` present |
| `src/release_confidence_platform/storage/audit_metadata_client.py` line 264 | `put_aggregation_job_intent_once` present |
| `src/release_confidence_platform/storage/audit_metadata_client.py` line 272 | `update_aggregation_job_intent` present |
| `tests/integration/test_phase3_lifecycle_determinism_regression.py` lines 100-107 | Hand-written `_SimpleRepo` stub manually defines all three aggregation methods; tests never instantiate the real `packages/` class |

**Key code evidence — `packages/` class boundary (line 210, last method before `_call`):**
```python
def _put_conditional(self, item: dict[str, Any], *, error: Exception) -> None:
    try:
        self._call(
            "put_item",
            Item=sanitize(item),
            ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
        )
    except ClientError as exc:
        ...

def _call(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
```

`packages/` `_put_conditional` does NOT accept `preserve_client_error_codes` — the `src/` version's `_call` signature includes it, but `packages/` `_call` does not. The three missing methods must use the `packages/` calling convention (`_put_conditional(item, error=...)` without `preserve_client_error_codes`), which is exactly what the `src/` version of `put_aggregation_job_intent_once` does.

**Confirmed: `update_occurrence` exists in `packages/` at line 171**, so `update_aggregation_job_intent` can delegate to it identically to the `src/` version.

---

## 5. Execution Path / Failure Trace

```
handler() [line 594]
  → AuditMetadataRepository(table_name, table)  [imports from packages/, line 27/596]
  → AuditFinalizationHandler(repository=..., ...)
      → handle(event)
          → _handle_finalizing() or _handle_finalizing_retry()
              → _complete_finalization(...)          # writes COMPLETED to DynamoDB
              → _trigger_aggregation_after_finalization(event)  [line 182 / 210]
                  → self.repository.aggregation_job_keys(...)  [line 437]
                  *** AttributeError: no such method on packages/ class ***
```

The COMPLETED state is already persisted when the error fires. The failure is silent from the lifecycle perspective (audit stays COMPLETED) but fatal for the aggregation chain.

---

## 6. Failure Classification

**Primary: Application Bug — Method Backport Gap**

The `packages/` directory is a development-time mirror of `src/release_confidence_platform/`. Three methods were added to the canonical `src/` version during Phase 4 aggregation work but were never copied to the `packages/` mirror. The Lambda handler imports from `packages/`, so it resolves to the stale class at runtime.

**Contributing factor: Test Bug**

Integration tests for `_trigger_aggregation_after_finalization` exclusively use `_SimpleRepo` hand-written stubs that define all three methods. No test ever instantiated the real `packages.storage.audit_metadata_client.AuditMetadataRepository` and exercised the aggregation trigger path, so the gap was not caught.

**Severity: HIGH**

The defect does not corrupt lifecycle state (COMPLETED is durable), but it silently breaks the end-to-end release confidence report chain. No aggregation job intent is recorded, no aggregation Lambda is invoked, and no report is produced. The platform's primary output is blocked for every audit that reaches COMPLETED.

---

## 7. Root Cause Analysis

**Immediate failure point:** `self.repository.aggregation_job_keys(...)` at `apps/backend/handlers/audit_finalization_handler.py` line 437 raises `AttributeError` because the `packages/` class does not define the method.

**Underlying root cause (Confirmed):**

The `packages/storage/audit_metadata_client.py` file is a development-time mirror of `src/release_confidence_platform/storage/audit_metadata_client.py`. During Phase 4 aggregation implementation, three methods were added to the `src/` canonical version:
- `aggregation_job_keys` (key construction helper, line 42)
- `put_aggregation_job_intent_once` (conditional put for idempotent intent creation, line 264)
- `update_aggregation_job_intent` (thin delegation to `update_occurrence`, line 272)

These were never backported to `packages/storage/audit_metadata_client.py`. The Lambda `handler()` function at line 594 imports from `packages/` (line 27), so at runtime it resolves to the older, incomplete class. The first call to any of the three methods produces `AttributeError`.

**Supporting evidence:**
- `packages/` class has 18 methods; `src/` class has 21 methods — the three aggregation methods account for the delta
- `aggregation_job_keys` follows the exact pattern of `audit_keys` (line 25) and `occurrence_keys` (line 28), which are present in both versions — this is a pure omission, not a design difference
- The `_put_conditional` signature in `packages/` (line 210) supports `(item, *, error)` — the same signature used by `put_aggregation_job_intent_once` in `src/`, so no adaptation is needed
- `update_occurrence` at `packages/` line 171 is identical in both versions — `update_aggregation_job_intent` can delegate to it without modification

**Contributing factors:**
- Integration tests use `_SimpleRepo` stubs (lines 51-107 in `test_phase3_lifecycle_determinism_regression.py`) that manually define all three methods, masking the gap from the real class
- No test imports and instantiates `packages.storage.audit_metadata_client.AuditMetadataRepository` and calls `_trigger_aggregation_after_finalization` through it

---

## 8. Confidence Level

**High.** The class definition is directly readable; the missing methods are confirmed absent by inspection of the full `packages/` file (228 lines). The `src/` version contains all three methods at confirmed line numbers. The handler import path is explicit at line 27. The failure trace from import to `AttributeError` is deterministic and requires no inference.

---

## 9. Recommended Fix

**Owner:** Backend developer

**File:** `packages/storage/audit_metadata_client.py`

**Action:** Add the three missing methods to `AuditMetadataRepository`, inserted after `occurrence_keys` (line 34) to maintain the key-construction method grouping.

```python
def aggregation_job_keys(self, client_id: str, audit_id: str, job_id: str) -> dict[str, str]:
    return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#AGGJOB#{job_id}"}

def put_aggregation_job_intent_once(self, item: dict[str, Any]) -> None:
    self._put_conditional(
        item,
        error=StorageError("Aggregation job intent exists", "AGGREGATION_JOB_INTENT_EXISTS"),
    )

def update_aggregation_job_intent(self, key: dict[str, str], updates: dict[str, Any]) -> None:
    self.update_occurrence(key, updates)
```

**Cautions:**
- Do NOT copy `preserve_client_error_codes` into `_put_conditional` calls — `packages/` `_call` does not accept that kwarg (line 222). The `src/` `put_aggregation_job_intent_once` correctly calls `_put_conditional(item, error=...)` without it; copy that form exactly.
- `update_aggregation_job_intent` must delegate to `self.update_occurrence` (present in `packages/` at line 171), not re-implement the update logic.
- No imports need to change — `StorageError` is already imported at line 10.

**Secondary fix — test gap:**

Add a regression test that instantiates the real `packages.storage.audit_metadata_client.AuditMetadataRepository` (not a stub) and exercises `_trigger_aggregation_after_finalization` against it with a mocked DynamoDB client. This ensures any future `packages/` vs. `src/` divergence is caught at test time.

---

## 10. Suggested Validation Steps

1. **Attribute check:** After adding the three methods, confirm `hasattr(AuditMetadataRepository(...), 'aggregation_job_keys')` returns `True` when the class is imported from `packages.storage.audit_metadata_client`.

2. **Unit test — real class:** Write or run a test that:
   - Imports `AuditMetadataRepository` from `packages.storage.audit_metadata_client`
   - Instantiates it with a mock DynamoDB client
   - Calls `aggregation_job_keys("c1", "a1", "j1")` and asserts `{"PK": "CLIENT#c1", "SK": "AUDIT#a1#AGGJOB#j1"}`
   - Calls `put_aggregation_job_intent_once({"PK": ..., "SK": ..., ...})` and asserts `put_item` was called on the DynamoDB mock
   - Calls `update_aggregation_job_intent(key, updates)` and asserts it delegates to `update_occurrence`

3. **Integration regression:** Run `tests/integration/test_phase3_lifecycle_determinism_regression.py` with the stub replaced (or supplemented) by the real `packages/` class to confirm no new failures.

4. **End-to-end validation against AWS:**
   - Trigger a new finalization for `client_id: client_rca_fix_v5_cf04e89f` or a fresh audit
   - Confirm the Lambda does not raise `AttributeError`
   - Confirm an aggregation job intent record is written to DynamoDB (`SK` prefix `AUDIT#<id>#AGGJOB#`)
   - Confirm the aggregation Lambda is invoked (check CloudWatch for `auditFinalization_aggregation_trigger_requested` log event)
   - Confirm a release confidence report is produced

5. **Regression check:** Re-run the full existing integration test suite to confirm no regression from the three additions.

---

## 11. Open Questions / Missing Evidence

- **Sync mechanism:** It is unclear whether `packages/` is auto-generated, a symlink, or manually maintained. If auto-generated, the generation script also needs updating. If manually maintained, a linting or CI guard comparing the two files' method sets would prevent future divergence.
- **Other missing methods:** The `src/` version contains additional methods not present in `packages/` (`list_audits_for_client`, `list_clients_from_registry`, `scan_clients_bounded`, and private helpers `_client_id_from_item`, `_is_canonical_audit_metadata_item`, `_ddb_scalar`, `_unmarshal_ddb_item`, `_unmarshal_ddb_value`). These are not called by the finalization handler and are therefore not blocking, but the divergence should be reconciled.

---

## 12. Final Investigator Decision

**Ready for developer fix.**

The root cause is confirmed, the fix is additive and scoped to three method additions in one file, no design decisions are required, and all constraints (calling convention, delegation target, import graph) are fully specified above.
