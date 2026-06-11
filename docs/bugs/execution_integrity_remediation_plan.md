# Execution Integrity Remediation Plan

**Incident:** Audit `audit_20260609_b18fee6a` transitioned to `COMPLETED` with one persisted `RUN` record remaining `STARTED`.
**RCA:** `docs/bugs/phase_3_phase_4_execution_integrity_rca.md`
**Branch:** `bugfix/execution-integrity-remediation`
**Priority:** Critical
**Date:** 2026-06-12

---

## Executive Summary

Four confirmed defects enabled an audit to report a clean `COMPLETED` state while canonical execution evidence was unresolved. Two are implementation bugs (identifier mutation, counter semantics) and two are architectural gaps (no evidence reconciliation gate, no Phase 4 deployment). Left unresolved, these defects allow any UUID whose hex digits contain a phone-like ten-digit sequence to produce an orphaned `STARTED` run that silently passes through lifecycle completion. The platform's release-confidence conclusions would then rest on incomplete evidence.

All four root causes are addressable through targeted changes to three Lambda handlers and the shared persistence layer, together with mandatory evidence reconciliation before every `COMPLETED` transition.

---

## Confirmed Root Causes

| ID | Root Cause | Component |
|----|------------|-----------|
| RC-001 | `sanitize(item)` mutates canonical DynamoDB key material before `put_started_once()`, leaving `SK` and `run_id` mismatched from the unsanitized key used by all subsequent terminal updates | `src/release_confidence_platform/storage/dynamodb_client.py:39` + `apps/backend/orchestrator/service.py:599` |
| RC-002 | Finalization reads `execution_counters.total_completed` as the sole authority for lifecycle completion; it does not query `RUN` child records or raw S3 evidence | `apps/backend/handlers/audit_finalization_handler.py:72–73` |
| RC-003 | Scheduler handler increments `total_completed` unconditionally after `orchestrator.run()` returns, including on `result.status == FAILED` returns | `apps/backend/handlers/scheduled_execution_handler.py:157–166` |
| RC-004 | Dev environment does not contain the approved Phase 4 aggregation Lambda, `AGGREGATION_FUNCTION_NAME` env var, or aggregation job records; therefore no post-finalization integrity gate ran | Infrastructure / deployment state |

---

## Workstream A — Execution Identity: Protect Canonical Identifiers

### Problem

`DynamoDBMetadataClient.put_started_once()` writes `Item=sanitize(item)`. The full item includes `PK`, `SK`, and `run_id`. The shared sanitizer matches the substring `2475004829` within UUID `48a87626-e2f9-4f81-82ff-2475004829ec` against `PHONE_PATTERN` and replaces it with `[REDACTED]`. The persisted item therefore has a mutated primary key. All subsequent terminal updates reference the unsanitized UUID key, which fails `attribute_exists(PK) AND attribute_exists(SK)`, leaving the `STARTED` item orphaned.

Additionally, `CoreEngineOrchestrator._started_item()` wraps the returned dict in `sanitize(...)` before returning, compounding the boundary violation upstream.

### Affected Components

| File | Location | Issue |
|------|----------|-------|
| `src/release_confidence_platform/storage/dynamodb_client.py` | Line 39, `put_started_once()` | `Item=sanitize(item)` passes key material through PII redaction |
| `apps/backend/orchestrator/service.py` | ~Line 599, `_started_item()` | Returns dict wrapped in `sanitize(...)` |
| `src/release_confidence_platform/sanitization/sanitizer.py` | `PHONE_PATTERN`, `sanitize()` | Correct for logs/output; incorrect scope for DynamoDB item keys |
| `packages/storage/dynamodb_client.py` | Line 33, `put_started_once()` | `Item=sanitize(item)` — active production persistence path; same defect as the src path |
| `packages/storage/dynamodb_client.py` | Line 45, `update_terminal()` | `sanitize(updates).values()` — passes update field values through PII redaction before expression values are built |

Note: `packages/storage/dynamodb_client.py` is the active production persistence path. Both `put_started_once()` at line 33 and `update_terminal()` at line 45 in this file must be fixed. The `src/release_confidence_platform/storage/dynamodb_client.py` path must also be fixed for completeness, but the packages path is the confirmed active call site for the incident.

### Required Fix

1. Remove `sanitize()` from the path that writes DynamoDB item key material. `put_started_once()` must write the item with `PK`, `SK`, and `run_id` exactly as generated — byte-identical to what terminal update paths will use.
2. Remove the `sanitize()` wrapper in `_started_item()` for the returned dict, or scope it to exclude canonical identifier fields (`PK`, `SK`, `run_id`, `audit_id`, `client_id`, all S3 key fields, and all lineage identifier fields).
3. Sanitization of `run_id` and related identifiers is only permitted in: structured log events, user-visible CLI output, and diagnostic API responses.

### Validation

- Unit test: `put_started_once()` with `run_id="48a87626-e2f9-4f81-82ff-2475004829ec"` persists `SK` byte-identical to input.
- Unit test: `_started_item()` returns dict with unsanitized `PK`, `SK`, `run_id`.
- Unit test: `update_terminal()` key matches `put_started_once()` key for the incident UUID.
- Regression guard: `PHONE_PATTERN.search(run_id)` is not None for the incident UUID — document this test explicitly.

### Definition of Done

- [ ] `put_started_once()` in `packages/storage/dynamodb_client.py:33` writes key material without mutation for any UUID (sanitize call removed from Item argument)
- [ ] `update_terminal()` in `packages/storage/dynamodb_client.py:45` writes update field values without mutation (sanitize call removed from expression values construction)
- [ ] `put_started_once()` in `src/release_confidence_platform/storage/dynamodb_client.py:39` writes key material without mutation for any UUID
- [ ] `_started_item()` in `apps/backend/orchestrator/service.py` returns canonical identifiers without sanitization
- [ ] Terminal update key resolves to the same DynamoDB item as initial `put_started_once()` key
- [ ] All four unit tests pass
- [ ] Regression test: UUID `48a87626-e2f9-4f81-82ff-2475004829ec` persists with byte-identical SK in both `packages/storage/dynamodb_client.py` and `src/release_confidence_platform/storage/dynamodb_client.py`

---

## Workstream B — Scheduler Counter Semantics

### Problem

`ScheduledExecutionHandler.handle()` increments `total_started` and `total_completed` on the normal return path after `orchestrator.run()`, regardless of `result.status`. When the orchestrator returns `status=FAILED` (as it did for the orphan run), the scheduler still marks the occurrence `claim_status=completed` and increments `total_completed`. This inflates the completion counter used by finalization.

### Affected Components

| File | Location | Issue |
|------|----------|-------|
| `apps/backend/handlers/scheduled_execution_handler.py` | Lines 157–166 | Increments `total_completed` on any normal return; does not branch on `result.status` |

### Required Fix

#### Single-execution path (`else` branch, `scheduled_execution_handler.py:138–152`)

Branch counter and occurrence state on `result.get("status")`:

- `COMPLETED` → increment `total_completed`; set occurrence `claim_status=completed`
- `FAILED` → increment `total_failed` (new counter key); set occurrence `claim_status=failed`
- Any unrecognized status → increment `total_unresolved`; set occurrence `claim_status=unresolved`; do not increment `total_completed`

#### RepeatedExecutionCoordinator path (`scheduled_execution_handler.py:131–137`)

`RepeatedExecutionCoordinator.run()` returns a list of individual RUN results (confirmed: line 133–135, `results = RepeatedExecutionCoordinator(self.orchestrator).run(...)`). Each element in the returned list is the result dict for one individual RUN record execution.

Counter update semantics for the repeated path:

- Iterate over each result dict in `results`.
- For each result: if `result.get("status") == COMPLETED`, increment `total_completed`; if `result.get("status") == FAILED`, increment `total_failed`; otherwise increment `total_unresolved`.
- The total run record count (`len(results)`) is the denominator for Check 6 reconciliation (not the occurrence count, which is always 1 for a repeated-schedule occurrence invocation).
- Set occurrence `claim_status` based on the aggregate outcome: `completed` if all results are terminal and at least one is `COMPLETED`; `failed` if all results are terminal and none are `COMPLETED`; `partial` if results are mixed.

**Rationale:** the repeated-execution path previously used a single occurrence-level counter update applied regardless of individual RUN result statuses (`scheduled_execution_handler.py:161–163` — `total_completed` incremented once after the coordinator returns). This conflates the occurrence (1) with the RUN records produced (N). For finalization Check 6 reconciliation, the denominator is `len(terminal_run_records)`, which is N — the total RUN record count across all occurrences. The counter update for the repeated path must reflect individual RUN result statuses, not occurrence completion.

Counter semantics must be explicitly documented in a code comment at the counter-update site for both paths: counters track individual RUN record outcome distributions, not occurrence handler completions. A note must reference the finalization reconciliation gate as the canonical evidence authority and note that `total_completed` does not equal the occurrence count for repeated-schedule audits.

### Validation

- Integration test: single-execution `FAILED` orchestrator return → `total_completed` unchanged, `total_failed` incremented, occurrence `claim_status=failed`.
- Integration test: single-execution `COMPLETED` orchestrator return → `total_completed` incremented, occurrence `claim_status=completed`.
- Integration test: single-execution mixed sequence (4 completed, 1 failed) → `total_completed=4`, `total_failed=1`, `total_started=5`.
- Integration test: repeated-execution coordinator returns 5 results (4 `COMPLETED`, 1 `FAILED`) → `total_completed=4`, `total_failed=1`, occurrence `claim_status=partial`.
- Integration test: repeated-execution coordinator returns 5 results (all `COMPLETED`) → `total_completed=5`, `total_failed=0`, occurrence `claim_status=completed`.
- Integration test: Check 6 reconciliation denominator for a repeated-execution audit with 1 occurrence and 5 RUN records equals 5, not 1.

### Definition of Done

- [ ] `total_completed` never increments when orchestrator returns `status=FAILED` (single-execution path)
- [ ] `total_failed` tracks failed occurrence handler paths separately (single-execution path)
- [ ] `RepeatedExecutionCoordinator` path iterates individual RUN result statuses for counter updates
- [ ] Check 6 reconciliation denominator is `len(terminal_run_records)` (total RUN count), not occurrence count
- [ ] Counter semantics documented at both update sites (single and repeated paths)
- [ ] Six integration tests pass (three single-execution, three repeated-execution)

---

## Workstream C — Finalization Integrity Gate

### Problem

`AuditFinalizationHandler.handle()` reads `execution_counters.total_completed` as `execution_count` and transitions to `COMPLETED` when nonzero. It does not query `RUN` child records, verify their terminal states, or reconcile raw S3 evidence. This makes the completion decision entirely dependent on a derived counter that can diverge from persisted evidence (as it did in the incident).

### Affected Components

| File | Location | Issue |
|------|----------|-------|
| `apps/backend/handlers/audit_finalization_handler.py` | Lines 72–73 | Counter-only finalization decision; no RUN reconciliation |

### Required Fix

Introduce a mandatory finalization integrity gate invoked before every `FINALIZING → COMPLETED` transition.

**Gate location:** `_complete_finalization()` (or equivalent), before lifecycle state write.

**Gate implementation:** `src/release_confidence_platform/audit_lifecycle/finalization_gate.py` — pure function, no side effects.

**Gate signature:**
```python
def finalization_integrity_gate(
    audit: dict,
    run_records: list[dict],
    s3_evidence_keys: list[str],
    client_id: str,
    audit_id: str,
) -> GateResult:
    ...
```

**Gate checks (all must pass):**

| Check | Pass condition | Failure code |
|-------|----------------|--------------|
| 1. Expected count consistent | `execution_counters.total_completed == len(terminal_run_records)` | `COUNTER_RUN_COUNT_MISMATCH` |
| 2. No unresolved runs | Zero `RUN` records with `status=STARTED` | `UNRESOLVED_STARTED_RUNS` |
| 3. Every completed run has raw evidence | Every `COMPLETED` `RUN` has non-null `raw_result_s3_key` | `MISSING_RAW_EVIDENCE_LINK` |
| 4. No orphan raw evidence | Every S3 key maps to exactly one `COMPLETED` `RUN` record | `ORPHAN_RAW_EVIDENCE` |
| 5. No orphan run records | Every terminal `RUN` record maps to one S3 evidence object | `RUN_WITHOUT_EVIDENCE` |
| 6. Finalization count reconciled | `finalization.execution_count == len(terminal_run_records)` | `FINALIZATION_COUNT_MISMATCH` |

**Failure behavior:** gate returns a `GateResult(passed=False, failures=[...])`. Finalization handler logs the failures as structured events, records them on the audit item as `finalization.integrity_failures`, and does not transition to `COMPLETED`. The audit remains in `FINALIZING` pending administrative recovery.

### Validation

- Integration test: one `STARTED` RUN → gate blocks, `lifecycle_state != COMPLETED`.
- Integration test: one `COMPLETED` RUN with `raw_result_s3_key=None` → gate blocks.
- Integration test: `total_completed > count(COMPLETED RUNs)` → gate blocks.
- Integration test: `total_completed < count(COMPLETED RUNs)` → gate blocks.
- Integration test: all evidence reconciles → gate passes, audit reaches `COMPLETED`.

### Definition of Done

- [ ] `finalization_gate.py` is a pure function with no writes
- [ ] All six checks implemented with structured failure codes
- [ ] Gate is invoked before every `FINALIZING → COMPLETED` transition
- [ ] Five integration tests pass
- [ ] Positive-path test (clean audit) passes

---

## Workstream D — Lifecycle Invariant Enforcement

### Formal Invariant

> An audit SHALL NEVER transition to `COMPLETED` while any execution evidence remains unresolved or internally inconsistent.

This invariant is now enforced mechanically by the Workstream C gate. This workstream formalizes it in documentation and ensures it is part of all future review gates.

### Required Actions

1. Add the invariant to `docs/architecture/execution_lifecycle.md` under a dedicated "Completion Invariant" section.
2. Reference the invariant in `docs/architecture/adr_execution_evidence_source_of_truth.md` (already drafted).
3. Add an invariant-verification checklist item to QA sign-off templates.
4. Add invariant verification to release readiness review checklist.

### Definition of Done

- [ ] Invariant documented in `execution_lifecycle.md`
- [ ] Invariant referenced in ADR
- [ ] QA and release readiness checklists updated

---

## Workstream E — Phase 4 Deployment Validation

### Problem

The dev environment at incident time was missing all Phase 4 aggregation resources. Without these, no post-finalization integrity gate executed. Before continuing Phase 4 end-to-end validation, the environment must be verified to match the approved Phase 4 architecture.

### Required Verification

Confirm presence of each component in the target validation environment:

| Component | Evidence Required |
|-----------|------------------|
| `release-confidence-platform-{stage}-auditAggregation` Lambda | `aws lambda get-function` succeeds |
| `AGGREGATION_FUNCTION_NAME` env var on `auditFinalization` Lambda | `aws lambda get-function-configuration` shows var |
| Aggregation IAM role with invoke permission | IAM policy attached to finalization execution role |
| Aggregation EventBridge or Lambda trigger wiring | Trigger configured on `auditAggregation` or synchronous invoke path verified |
| Aggregation environment variables on `auditAggregation` | `METADATA_TABLE`, `RAW_RESULTS_BUCKET`, `STAGE` present |
| `AGGJOB` record creation on finalization | Post-finalization DynamoDB query returns `AGGJOB` item |
| Aggregation log group | `/aws/lambda/release-confidence-platform-{stage}-auditAggregation` exists and contains invocation records |
| Canonical aggregate persistence | `AGGREGATE#...` records exist in metadata table after aggregation |

### Definition of Done

- [ ] All eight deployment evidence items verified in the target validation environment
- [ ] Aggregation Lambda responds to test invocation without error
- [ ] Post-finalization `AGGJOB` record confirmed in DynamoDB after a test audit

---

## Workstream F — Disaster Recovery / Reconciliation Procedure

### Problem

The incident left one orphaned `STARTED` run (`SK=AUDIT#audit_20260609_b18fee6a#RUN#48a87626-e2f9-4f81-82ff-[REDACTED]ec`) and one orphan raw S3 object (`raw-results/.../48a87626-e2f9-4f81-82ff-2475004829ec/results.json`). These cannot be resolved by normal operational flows. A deterministic, auditable, non-destructive recovery procedure is needed for exceptional cases.

### Recovery Procedure Design

The procedure must:
- Be executed only under privileged authorization (requires documented approval)
- Never overwrite or delete raw S3 evidence
- Produce an audit trail of all mutations
- Be deterministic: given the same orphaned state, always produce the same resolution
- Not affect any other run record or audit

**Procedure steps:**

1. **Read-only discovery phase** — query all `STARTED` RUN records for the target audit; list all raw S3 objects; compare to all `COMPLETED` RUN records. Produce a reconciliation report. No writes.

2. **Operator review** — submit reconciliation report for privileged authorization. Document the approver, timestamp, and justification.

3. **Evidence preservation** — copy orphan raw S3 object to an audit-trail prefix (`reconciliation-archive/...`) before any metadata mutations. This creates a permanent record independent of run metadata.

4. **Metadata remediation** — with authorization: either
   - (a) write a corrected terminal `RUN` record with the unsanitized key linking to the raw S3 evidence, marking it `FAILED` (preferred — preserves evidence while resolving the lifecycle gap), or
   - (b) write a tombstone record at the sanitized key pointing to the unsanitized S3 key for audit trail purposes.

5. **Lifecycle re-evaluation** — if all `STARTED` records are now resolved, re-run finalization integrity gate (read-only evaluation only). If gate passes, document that a re-finalization may be warranted; do not automatically transition lifecycle state.

6. **Reconciliation report** — produce a final structured report covering: orphaned records found, actions taken, before/after evidence state, gate result.

### Definition of Done

- [ ] Procedure documented in `docs/operations/execution_reconciliation_procedure.md`
- [ ] Procedure requires documented authorization before any DDB writes
- [ ] Procedure is non-destructive: raw S3 objects are never deleted or overwritten
- [ ] Procedure includes a read-only discovery phase that produces a human-reviewable report before any writes

---

## Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Another phone-like UUID is generated in dev/staging during remediation window | Medium | High | WS-A fix eliminates the defect; regression test covers the exact pattern |
| Finalization gate blocks a legitimate clean audit due to over-strict evidence check | Low | Medium | WS-C includes explicit positive-path test (C-05); gate is pure function testable independently |
| Counter semantics fix breaks existing behavior for repeated-schedule occurrences | Low | Medium | WS-B integration test B-04 covers mixed sequences including repeated-schedule semantics |
| Phase 4 environment deployment fails | Medium | High | WS-E requires verified deployment evidence before Phase 4 validation continues |
| Orphaned dev data causes confusion during Phase 4 re-validation | Low | Low | WS-F procedure provides clean resolution path; Phase 4 validation uses a new audit |
| New invariant check adds latency to finalization | Low | Low | Gate queries only terminal RUN records (bounded count); pure function with no additional writes |
| Future sanitizer expansion re-introduces key mutation | Low | High | WS-A regression test with `PHONE_PATTERN` UUID is a permanent guard |

---

## Dependency Order

```
WS-A (persistence identity fix)
  └── WS-C (finalization gate, depends on WS-A for accurate RUN keys)
        └── Phase 4 E2E validation
WS-B (counter semantics)
  └── WS-C (finalization gate, depends on accurate counters for reconciliation)
WS-D (documentation)
  └── can proceed in parallel
WS-E (deployment validation)
  └── must complete before Phase 4 validation re-run
WS-F (recovery procedure)
  └── can proceed in parallel; apply to dev incident after WS-A/C are deployed
```

---

## References

| Resource | Path |
|----------|------|
| RCA | `docs/bugs/phase_3_phase_4_execution_integrity_rca.md` |
| ADR: Evidence Source of Truth | `docs/architecture/adr_execution_evidence_source_of_truth.md` |
| Finalization Gate Design | `docs/architecture/finalization_integrity_gate_design.md` |
| QA Regression Test Plan | `docs/qa/execution_integrity_regression_test_plan.md` |
| Persistence client | `src/release_confidence_platform/storage/dynamodb_client.py` |
| Sanitizer | `src/release_confidence_platform/sanitization/sanitizer.py` |
| Orchestrator | `apps/backend/orchestrator/service.py` |
| Scheduled execution handler | `apps/backend/handlers/scheduled_execution_handler.py` |
| Finalization handler | `apps/backend/handlers/audit_finalization_handler.py` |
| Phase 4 integrity check | `src/release_confidence_platform/aggregation/integrity.py` |
