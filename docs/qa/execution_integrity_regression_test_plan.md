# Test Plan: Execution Integrity Regression

**Feature:** Execution Integrity Remediation — Phase 3 / Phase 4 Incident
**Branch:** `bugfix/execution-integrity-remediation`
**Prepared by:** QA Engineering
**RCA Source:** `docs/bugs/phase_3_phase_4_execution_integrity_rca.md`
**Remediation Plan:** `docs/bugs/execution_integrity_remediation_plan.md`
**Date:** 2026-06-12

---

## 1. Feature Overview

Three confirmed defects produced the incident where audit `audit_20260609_b18fee6a` reached `COMPLETED` with one `RUN` record stranded as `STARTED`:

1. **Sanitization boundary violation.** `DynamoDBMetadataClient.put_started_once()` (line 39 of `dynamodb_client.py`) calls `Item=sanitize(item)` on the full DynamoDB item before writing. `CoreEngineOrchestrator._started_item()` (~line 599 of `service.py`) wraps the entire dict in `sanitize(...)` before returning it. The UUID `48a87626-e2f9-4f81-82ff-2475004829ec` contains the substring `2475004829`, which satisfies `PHONE_PATTERN` in `sanitizer.py`. This mutated `SK` and `run_id` to `...#RUN#48a87626-e2f9-4f81-82ff-[REDACTED]ec` in the persisted item, while terminal updates computed keys from the unsanitized run ID, causing `ConditionalCheckFailedException` on every terminal write.

2. **Scheduler counter semantics.** `ScheduledExecutionHandler.handle()` (lines 157–166 of `scheduled_execution_handler.py`) increments `total_completed` and sets `claim_status=completed` unconditionally after any normal `orchestrator.run()` return, including `status=FAILED` returns.

3. **Finalization has no reconciliation gate.** `AuditFinalizationHandler.handle()` (lines 72–73 of `audit_finalization_handler.py`) reads `execution_counters.total_completed` directly and transitions to `COMPLETED` if nonzero, without querying `RUN` child records or raw S3 evidence.

---

## 2. Acceptance Criteria Mapping

| Acceptance Criterion | Workstream | Test IDs |
|---|---|---|
| `PK`, `SK`, `run_id` must not be mutated by sanitization before DynamoDB persistence | A | A-01, A-02, A-03, A-04 |
| UUID with phone-like digit substring persists byte-identically as DynamoDB key material | A | A-01, A-02 |
| Terminal update key resolves to the same key as initial `put_started_once` key | A | A-03 |
| `_started_item()` does not sanitize canonical identifier fields | A | A-04 |
| `total_completed` increments only when orchestrator returns `status=COMPLETED` | B | B-01 |
| `total_completed` does not increment when orchestrator returns `status=FAILED` | B | B-02 |
| Occurrence marked `claim_status=failed` when orchestrator returns `FAILED` | B | B-03 |
| Counters consistent with terminal `RUN` records across mixed execution sequence | B | B-04 |
| Finalization blocked when any `RUN` record is `status=STARTED` | C | C-01 |
| Finalization blocked when `COMPLETED` `RUN` record has `raw_result_s3_key=None` | C | C-02 |
| Finalization blocked when `total_completed` exceeds count of terminal `RUN` records | C | C-03 |
| Finalization blocked when `total_completed` is less than count of terminal `RUN` records | C | C-04 |
| Finalization succeeds when all evidence reconciles | C | C-05 |
| Evidence counts reconcile for a clean audit | ER | ER-01 |
| Orphaned `STARTED` run causes detectable evidence mismatch | ER | ER-02 |
| Full lifecycle completes cleanly without manual intervention | E2E | E2E-01 |

---

## 3. Test Scenarios

---

### Workstream A — Execution Identity Tests

---

#### A-01: Phone-like UUID persists with byte-identical PK, SK, run_id

**Test name:** `test_put_started_once_phone_like_uuid_persists_unsanitized_keys`
**Test type:** Unit
**Component under test:** `DynamoDBMetadataClient.put_started_once()` in `src/release_confidence_platform/storage/dynamodb_client.py`
**Recommended file:** `tests/unit/test_execution_identity_dynamodb.py`

**Setup / preconditions:**
- Instantiate `DynamoDBMetadataClient` with an in-memory stub that records the exact `Item` dict passed to `put_item`.
- `client_id="client_test"`, `audit_id="audit_test"`, `run_id="48a87626-e2f9-4f81-82ff-2475004829ec"`.
- Build item using `metadata_client.keys(client_id, audit_id, run_id)` merged with `{"status": "STARTED", "run_id": run_id, "raw_result_s3_key": None, "completed_at": None, "failure_summary": None}`.

**Action:** Call `metadata_client.put_started_once(item)`.

**Expected result:**
- Persisted `PK == "CLIENT#client_test"` — no `[REDACTED]`.
- Persisted `SK == "AUDIT#audit_test#RUN#48a87626-e2f9-4f81-82ff-2475004829ec"` — no `[REDACTED]`.
- Persisted `run_id == "48a87626-e2f9-4f81-82ff-2475004829ec"` — no `[REDACTED]`.

**Failure mode being guarded:** Sanitization of primary-key material before `put_item` mutates `SK` and `run_id`, making the item unreachable by subsequent key-based operations.

---

#### A-02: Sanitizer redacts phone-like substrings in value strings — documents the UUID collision risk

**Test name:** `test_sanitizer_redacts_phone_in_value_strings_not_in_run_ids`
**Test type:** Unit
**Component under test:** `sanitize()` in `src/release_confidence_platform/sanitization/sanitizer.py`
**Recommended file:** `tests/unit/test_sanitizer_uuid_boundary.py`

**Setup / preconditions:** No external dependencies.

**Action:**
- Part 1: Assert `PHONE_PATTERN.search("48a87626-e2f9-4f81-82ff-2475004829ec")` is not None.
- Part 2: Assert `sanitize("48a87626-e2f9-4f81-82ff-2475004829ec")` produces a string containing `[REDACTED]`.
- Part 3: Assert that `put_started_once()` in A-01 does NOT produce a persisted item with `[REDACTED]` in key fields (byte-identity cross-check).

**Expected result:** Parts 1 and 2 confirm the sanitizer's built-in behavior; Part 3 confirms the remediation excludes key fields from sanitization.

**Failure mode being guarded:** Documents the pattern so any future widening of the sanitization boundary that re-introduces key mutation is caught.

---

#### A-03: `update_terminal()` key matches `put_started_once()` key for phone-like run IDs

**Test name:** `test_update_terminal_key_matches_put_started_once_key_for_phone_like_uuid`
**Test type:** Unit
**Component under test:** `DynamoDBMetadataClient.update_terminal()` in `src/release_confidence_platform/storage/dynamodb_client.py`
**Recommended file:** `tests/unit/test_execution_identity_dynamodb.py`

**Setup / preconditions:**
- In-memory DynamoDB stub that enforces `attribute_exists(PK) AND attribute_exists(SK)` by raising `ConditionalCheckFailedException` when the key is absent.
- Call `put_started_once()` first using `run_id="48a87626-e2f9-4f81-82ff-2475004829ec"`.

**Action:** Call `metadata_client.update_terminal(metadata_client.keys(client_id, audit_id, run_id), {"status": "COMPLETED", "completed_at": "2026-06-12T00:00:00Z", "raw_result_s3_key": "s3://bucket/key", "failure_summary": None})`.

**Expected result:**
- No exception raised.
- Stub item has `status == "COMPLETED"` and `raw_result_s3_key == "s3://bucket/key"`.

**Failure mode being guarded:** Key mismatch between write and update paths produces `ConditionalCheckFailedException`, stranding the run as `STARTED`.

---

#### A-04: `_started_item()` in orchestrator does not sanitize canonical identifier fields

**Test name:** `test_orchestrator_started_item_preserves_canonical_identifiers`
**Test type:** Unit
**Component under test:** `CoreEngineOrchestrator._started_item()` in `apps/backend/orchestrator/service.py`
**Recommended file:** `tests/unit/test_execution_identity_orchestrator.py`

**Setup / preconditions:**
- Construct a minimal `OrchestratorEvent` with `run_id="48a87626-e2f9-4f81-82ff-2475004829ec"`, `client_id="client_test"`, `audit_id="audit_test"`, `scenario_type="baseline_health"`, `triggered_by="eventbridge_scheduler"`.
- Instantiate `CoreEngineOrchestrator` with stub dependencies.

**Action:** Call `orchestrator._started_item(event)` and capture the returned dict.

**Expected result:**
- `result["PK"] == "CLIENT#client_test"` — no `[REDACTED]`.
- `result["SK"] == "AUDIT#audit_test#RUN#48a87626-e2f9-4f81-82ff-2475004829ec"` — no `[REDACTED]`.
- `result["run_id"] == "48a87626-e2f9-4f81-82ff-2475004829ec"` — no `[REDACTED]`.
- `result["status"] == "STARTED"`.

**Failure mode being guarded:** `_started_item()` wrapping the full dict in `sanitize(...)`. This test must fail against unpatched code and pass once identifier fields are excluded from sanitization.

---

### Workstream B — Scheduler Counter Semantics Tests

---

#### B-01: `total_completed` increments on orchestrator `COMPLETED` return

**Test name:** `test_scheduler_increments_total_completed_on_orchestrator_completed`
**Test type:** Integration
**Component under test:** `ScheduledExecutionHandler.handle()` in `apps/backend/handlers/scheduled_execution_handler.py`
**Recommended file:** `tests/integration/test_phase3_scheduled_execution.py`

**Setup / preconditions:**
- `Orchestrator.run()` returns `{"run_id": "run-ok-01", "status": "COMPLETED", "raw_result_s3_key": "raw-results/.../results.json"}`.
- `Repo.audit["execution_counters"] = {"total_started": 5, "total_completed": 5}`.

**Action:** Call `ScheduledExecutionHandler(repository=repo, orchestrator=orch).handle(schedule_event())`.

**Expected result:** `repo.audit["execution_counters"]["total_completed"] == 6`, `total_started == 6`, response `status == "accepted"`.

**Failure mode being guarded:** Fix for B-02 must not suppress completion counting on genuine completions.

---

#### B-02: `total_completed` does NOT increment on orchestrator `FAILED` return

**Test name:** `test_scheduler_does_not_increment_total_completed_on_orchestrator_failed`
**Test type:** Integration
**Component under test:** `ScheduledExecutionHandler.handle()` in `apps/backend/handlers/scheduled_execution_handler.py`
**Recommended file:** `tests/integration/test_phase3_scheduled_execution.py`

**Setup / preconditions:**
- `FailingOrchestrator.run()` returns `{"run_id": "48a87626-e2f9-4f81-82ff-2475004829ec", "status": "FAILED", "failure_summary": {"error_type": "STORAGE_ERROR", "message": "ConditionalCheckFailedException"}}`.
- `Repo.audit["execution_counters"] = {"total_started": 5, "total_completed": 5}`.

**Action:** Call handler with `FailingOrchestrator`.

**Expected result:**
- `total_completed` remains `5`.
- `total_started` becomes `6`.
- A `total_failed` (or equivalent) key exists and equals `1`.
- Handler exits without exception.

**Failure mode being guarded:** Direct reproduction of the incident counter defect. Scheduler previously incremented `total_completed` on `FAILED` returns, inflating the counter used by finalization.

---

#### B-03: Occurrence marked `claim_status=failed` on orchestrator `FAILED` return

**Test name:** `test_scheduler_marks_occurrence_failed_when_orchestrator_returns_failed`
**Test type:** Integration
**Component under test:** `ScheduledExecutionHandler.handle()` in `apps/backend/handlers/scheduled_execution_handler.py`
**Recommended file:** `tests/integration/test_phase3_scheduled_execution.py`

**Setup / preconditions:** Same `FailingOrchestrator` as B-02.

**Action:** Call handler with `FailingOrchestrator`.

**Expected result:**
- Occurrence item in `repo.claims` has `claim_status == "failed"`.
- `run_id` is the failed run's ID.
- `completed_at` is set.

**Failure mode being guarded:** In the incident, the failed occurrence was recorded as `claim_status=completed`, making all 25 occurrences appear cleanly completed.

---

#### B-04: Counter invariant holds across a mixed-result execution sequence

**Test name:** `test_scheduler_counter_consistency_after_mixed_execution_sequence`
**Test type:** Integration
**Component under test:** `ScheduledExecutionHandler.handle()` in `apps/backend/handlers/scheduled_execution_handler.py`
**Recommended file:** `tests/integration/test_phase3_scheduled_execution.py`

**Setup / preconditions:**
- Orchestrator returns `COMPLETED` for occurrences 1–4, `FAILED` for occurrence 5.
- Five handler calls with distinct `schedule_occurrence_id` values.
- Counters start at zero.

**Action:** Execute all 5 calls sequentially.

**Expected result:**
- `total_completed == 4`, `total_started == 5`.
- `total_completed + total_failed == total_started`.
- 4 occurrences have `claim_status == "completed"`, 1 has `claim_status == "failed"`.

**Failure mode being guarded:** Accumulated counter drift across a mixed sequence prevents finalization from seeing correct evidence counts.

---

### Workstream C — Finalization Integrity Gate Tests

---

#### C-01: Finalization blocked when one `RUN` record is `STARTED`

**Test name:** `test_finalization_blocked_when_run_record_is_started`
**Test type:** Integration
**Component under test:** `AuditFinalizationHandler.handle()` in `apps/backend/handlers/audit_finalization_handler.py`
**Recommended file:** `tests/integration/test_phase3_cancellation_finalization.py`

**Setup / preconditions:**
- `Repo.list_run_records()` returns 4 `COMPLETED` records (all with `raw_result_s3_key` set) and 1 `STARTED` record (`raw_result_s3_key=None`, `completed_at=None`).
- `execution_counters.total_completed = 5`, `lifecycle_state = "RUNNING"`.

**Action:** Call `AuditFinalizationHandler(repository=repo).handle(finalization_event())`.

**Expected result:**
- `lifecycle_state` is NOT `"COMPLETED"`.
- No `FINALIZING -> COMPLETED` transition in lifecycle history.

**Failure mode being guarded:** Primary invariant violation. Finalization completed an audit while one `RUN` remained `STARTED`.

---

#### C-02: Finalization blocked when `COMPLETED` `RUN` has `raw_result_s3_key=None`

**Test name:** `test_finalization_blocked_when_completed_run_missing_raw_result_key`
**Test type:** Integration
**Component under test:** `AuditFinalizationHandler.handle()` in `apps/backend/handlers/audit_finalization_handler.py`
**Recommended file:** `tests/integration/test_phase3_cancellation_finalization.py`

**Setup / preconditions:**
- 4 `COMPLETED` records with `raw_result_s3_key` set; 1 `COMPLETED` record with `raw_result_s3_key=None`.
- `total_completed = 5`, `lifecycle_state = "RUNNING"`.

**Action:** Call finalization handler.

**Expected result:**
- `lifecycle_state` is NOT `"COMPLETED"`.
- No `FINALIZING -> COMPLETED` transition.

**Failure mode being guarded:** A `COMPLETED` run without `raw_result_s3_key` means the evidence link is broken. A status-only check would pass such a record incorrectly.

---

#### C-03: Finalization blocked when `total_completed` exceeds terminal `RUN` record count

**Test name:** `test_finalization_blocked_when_counters_exceed_terminal_run_count`
**Test type:** Integration
**Component under test:** `AuditFinalizationHandler.handle()` in `apps/backend/handlers/audit_finalization_handler.py`
**Recommended file:** `tests/integration/test_phase3_cancellation_finalization.py`

**Setup / preconditions:**
- `list_run_records()` returns 4 `COMPLETED` records (all with `raw_result_s3_key` set).
- `total_completed = 6`, `lifecycle_state = "RUNNING"`.

**Action:** Call finalization handler.

**Expected result:**
- `lifecycle_state` is NOT `"COMPLETED"`. Mismatch detected and finalization held.

**Failure mode being guarded:** Counter over-count (from the incident's failed-run counter increment) signals more completions than evidence supports.

---

#### C-04: Finalization blocked when `total_completed` is less than terminal `RUN` record count

**Test name:** `test_finalization_blocked_when_counters_below_terminal_run_count`
**Test type:** Integration
**Component under test:** `AuditFinalizationHandler.handle()` in `apps/backend/handlers/audit_finalization_handler.py`
**Recommended file:** `tests/integration/test_phase3_cancellation_finalization.py`

**Setup / preconditions:**
- `list_run_records()` returns 6 `COMPLETED` records (all with `raw_result_s3_key` set).
- `total_completed = 4`, `lifecycle_state = "RUNNING"`.

**Action:** Call finalization handler.

**Expected result:**
- `lifecycle_state` is NOT `"COMPLETED"`. Mismatch detected and finalization held.

**Failure mode being guarded:** Counter under-count also signals inconsistency.

---

#### C-05: Finalization succeeds when all evidence reconciles

**Test name:** `test_finalization_succeeds_when_all_evidence_reconciles`
**Test type:** Integration
**Component under test:** `AuditFinalizationHandler.handle()` in `apps/backend/handlers/audit_finalization_handler.py`
**Recommended file:** `tests/integration/test_phase3_cancellation_finalization.py`

**Setup / preconditions:**
- `list_run_records()` returns 5 `COMPLETED` records, all with `raw_result_s3_key` set and `completed_at` set.
- `total_completed = 5`, `lifecycle_state = "RUNNING"`.

**Action:** Call finalization handler.

**Expected result:**
- `lifecycle_state == "COMPLETED"`.
- Lifecycle history: `RUNNING -> FINALIZING -> COMPLETED`.
- Response `status == "completed"`.
- `finalization.execution_count == 5`.

**Failure mode being guarded:** Positive regression guard. An over-restrictive finalization gate would block valid clean-audit completions.

---

### Evidence Reconciliation Tests

---

#### ER-01: Execution count equals terminal `RUN` count equals raw S3 object count for a clean audit

**Test name:** `test_evidence_reconciliation_counts_match_for_clean_audit`
**Test type:** Integration
**Component under test:** Finalization reconciliation logic
**Recommended file:** `tests/integration/test_execution_integrity_reconciliation.py`

**Setup / preconditions:**
- 5 `COMPLETED` `RUN` records, each with a distinct `raw_result_s3_key`.
- S3 stub contains exactly 5 objects at those keys.
- `total_completed = 5`, `lifecycle_state = "RUNNING"`.

**Action:** Trigger finalization, then verify all three counts.

**Expected result:** `execution_count == 5`, terminal `COMPLETED` `RUN` records == 5, raw S3 objects linked from those records == 5. Audit reaches `COMPLETED`.

**Failure mode being guarded:** Clean audits must produce a consistent evidence triangle.

---

#### ER-02: Orphaned `STARTED` run causes detectable evidence count mismatch

**Test name:** `test_evidence_reconciliation_detects_orphaned_started_run`
**Test type:** Integration
**Component under test:** Finalization reconciliation logic
**Recommended file:** `tests/integration/test_execution_integrity_reconciliation.py`

**Setup / preconditions:**
- 4 `COMPLETED` `RUN` records with `raw_result_s3_key` set; 1 `STARTED` record with `raw_result_s3_key=None`.
- S3 stub contains 5 objects (including orphan raw evidence at the unsanitized key path).
- `total_completed = 5` (pre-fix counter inflation), `lifecycle_state = "RUNNING"`.

**Action:** Trigger finalization.

**Expected result:**
- `count of terminal COMPLETED RUN records (4) != total_completed (5)` is detected.
- One `RUN` record is `STARTED` — detected.
- Audit does NOT reach `"COMPLETED"`.
- Response or lifecycle history contains a reason code indicating unresolved run records.

**Failure mode being guarded:** Direct in-process reproduction of the incident scenario. This test must fail on unpatched code and pass after remediation.

---

### End-to-End Test

---

#### E2E-01: Full lifecycle completes cleanly with phone-like UUID run included

**Test name:** `test_e2e_full_lifecycle_execution_finalization_aggregation_trigger`
**Test type:** End-to-end (in-process simulation)
**Component under test:** `ScheduledExecutionHandler` -> `CoreEngineOrchestrator` -> `DynamoDBMetadataClient` -> `AuditFinalizationHandler`
**Recommended file:** `tests/integration/test_execution_integrity_e2e.py`

**Setup / preconditions:**
- In-memory DynamoDB stub enforcing conditional checks.
- In-memory S3 stub.
- Stub `ApiRunner` returning successful `RunnerOutcome`.
- 3 baseline occurrences; one occurrence injects `run_id="48a87626-e2f9-4f81-82ff-2475004829ec"`.
- `AggregationInvoker` stub.

**Action:**
1. Call `ScheduledExecutionHandler.handle()` for all 3 occurrence events.
2. Call `AuditFinalizationHandler.handle()` with a finalization event.

**Verification points:**

After Step 1:
- `total_completed == 3`, `total_started == 3`.
- All 3 occurrences have `claim_status == "completed"`.
- DynamoDB stub has exactly 3 `RUN` records, all `status == "COMPLETED"`.
- The phone-like UUID run record has `SK == "AUDIT#<audit_id>#RUN#48a87626-e2f9-4f81-82ff-2475004829ec"` (no `[REDACTED]`) and `raw_result_s3_key` is non-None.
- S3 stub has exactly 3 raw result objects; one is at a path containing `48a87626-e2f9-4f81-82ff-2475004829ec`.
- Zero `RUN` records remain `STARTED`.

After Step 2:
- `lifecycle_state == "COMPLETED"`.
- `finalization.execution_count == 3`.
- Lifecycle history: `RUNNING -> FINALIZING -> COMPLETED`.
- An `AGGJOB` intent record exists in the DynamoDB stub.
- `finalization.execution_count (3) == count of COMPLETED RUN records (3) == count of S3 raw objects linked from those records (3)`.

**Failure mode being guarded:** All four defect vectors (identifier mutation, counter semantics, finalization gate, evidence reconciliation) must be simultaneously correct. Regression in any one component causes this test to fail.

---

## 4. Edge Cases

| Edge case | Covered by |
|---|---|
| UUID contains exactly 10 contiguous digits matching `PHONE_PATTERN` | A-01, A-02, A-04, E2E-01 |
| UUID with 10-digit substring at end of UUID segment (incident UUID) | A-01, A-03 |
| Terminal update after successful `put_started_once` using unsanitized key | A-03 |
| Orchestrator returns `FAILED` without raising an exception | B-02, B-03, ER-02 |
| `COMPLETED` run with `raw_result_s3_key=None` | C-02 |
| Counter higher than terminal record count | C-03 |
| Counter lower than terminal record count | C-04 |
| Orphan raw S3 evidence not linked from any `COMPLETED` run | ER-02 |
| All evidence reconciles — positive gate path | C-05, ER-01, E2E-01 |
| Aggregation intent persisted after clean finalization | E2E-01 |

---

## 5. Test Types Covered

| Type | Test IDs |
|---|---|
| Unit | A-01, A-02, A-03, A-04 |
| Integration | B-01, B-02, B-03, B-04, C-01, C-02, C-03, C-04, C-05, ER-01, ER-02 |
| End-to-end (in-process simulation) | E2E-01 |

---

## 6. Coverage Justification

Workstream A targets the confirmed root cause at the lowest possible layer — `put_started_once()` and `_started_item()`. Each test addresses a distinct code path, so a partial fix (fixing one but not the other) is caught.

Workstream B provides mirror tests (B-01 vs B-02) to ensure the fix does not suppress completion counting on valid completions while correctly blocking counting on failures. B-04 validates the accumulated invariant across a mixed sequence.

Workstream C gates finalization against four distinct evidence failure modes (unresolved `STARTED`, incomplete `COMPLETED`, counter over-count, counter under-count) plus the positive case (C-05) to guard against an over-restrictive gate.

Evidence Reconciliation tests validate the three-way count triangle as an integrated property. ER-02 reproduces the exact incident scenario in controlled form.

E2E-01 provides a single test that validates all four defect vectors simultaneously using the exact incident UUID.

---

## 7. Prerequisite State for Test Implementation

The following code changes are assumed and must be present before tests in the corresponding workstreams can pass:

1. `_started_item()` (`service.py` ~line 599) must not apply `sanitize()` to `PK`, `SK`, `run_id`, `client_id`, or `audit_id`. Tests A-04 and E2E-01 will fail until this is fixed.
2. `put_started_once()` (`dynamodb_client.py` line 39) must not pass key fields through `sanitize()`. Tests A-01 and A-03 will fail until this is fixed.
3. `ScheduledExecutionHandler` must branch counter and occurrence logic on `result.get("status")`. Tests B-02, B-03, B-04 will fail until this is fixed.
4. `AuditFinalizationHandler` must call a `RUN` record reconciliation query before `FINALIZING -> COMPLETED`. Tests C-01 through C-04, ER-02, and E2E-01 will fail until this is fixed.

Tests A-01 and A-04 explicitly document defects present in the unpatched branch. Failing these tests against pre-fix code is the intended behavior — they serve as acceptance tests for the remediation.

---

## 8. Out of Scope

- Cloud deployment validation (Phase 4 aggregation Lambda, `AGGREGATION_FUNCTION_NAME` env var, CloudWatch alarms). These are infrastructure owner concerns covered by Workstream E of the remediation plan.
- Recovery workflow for the specific orphaned run in `dev`. Addressed by Workstream F (disaster recovery procedure).
- Performance characteristics of the finalization reconciliation DynamoDB query.
- EventBridge re-delivery semantics.
