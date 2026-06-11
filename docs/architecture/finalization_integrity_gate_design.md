# Finalization Integrity Gate — Design Specification

## 1. Feature Overview

The finalization integrity gate is a mandatory pre-condition check that must pass before any audit lifecycle transition from `FINALIZING` to `COMPLETED` is allowed. It enforces the invariant established in `docs/architecture/adr_execution_evidence_source_of_truth.md`:

> An audit SHALL NEVER transition to COMPLETED while any execution evidence remains unresolved.

The gate evaluates the consistency of three evidence layers — audit metadata counters, DynamoDB RUN records, and S3 raw evidence objects — and produces either a pass result or a structured failure report. It does not modify state. It does not retry. It blocks the transition on any failure.

## 2. Product Requirements Summary

This gate implements the corrective action identified in `docs/bugs/phase_3_phase_4_execution_integrity_rca.md` under "Phase 3 lifecycle/finalization owner":

- Add a finalization reconciliation gate before `FINALIZING -> COMPLETED`.
- Query RUN records for the audit and reject/hold/fail finalization if any run is not terminal or has null terminal fields inconsistent with its status.
- Reconcile counters against run records and raw S3 evidence according to approved semantics before recording `finalization.execution_count`.

The gate applies to the existing finalization handler at `apps/backend/handlers/audit_finalization_handler.py`. It must execute inside `_complete_finalization(...)` before the `AuditLifecycleService.transition(...)` call that writes `COMPLETED`.

## 3. Requirement-to-Architecture Mapping

| Requirement | Gate mechanism |
| --- | --- |
| No COMPLETED with unresolved STARTED records | Check 2: STARTED count must be zero |
| No COMPLETED when RUN count diverges from expected | Check 1: terminal RUN count must equal expectedRunCount |
| No COMPLETED when raw evidence is missing for a terminal RUN | Check 3: every terminal RUN must have a corresponding S3 object |
| No COMPLETED when raw evidence has no RUN owner | Check 4 and 5: every S3 object must map to exactly one terminal RUN |
| Counters must not diverge from persisted evidence | Check 6: operational counters must match persisted terminal RUN counts |

## 4. Technical Scope

### Current Technical Scope

- Define the gate function signature, input contract, check set, pass/fail semantics, and structured error format.
- Define where the gate is invoked within the finalization handler.
- Define the administrative recovery procedure that resolves gate failures.
- Define test coverage requirements.

**Prerequisite note:** WS-C implementation must not begin until WS-A (identifier sanitization fix) is verified deployed. The gate correctly blocks COMPLETED when orphans exist, but new orphans will be produced on every affected UUID until WS-A is deployed. Deploying WS-C before WS-A only adds detection without eliminating the root cause; every audit execution with a phone-pattern UUID will produce a new orphan that must be manually recovered.

### Out of Scope

- Fixing the sanitizer boundary defect that produces orphaned STARTED records (`src/release_confidence_platform/sanitization/sanitizer.py`). The gate detects that defect's symptoms; the fix is a separate workstream.
- Fixing the scheduled execution handler counter increment semantics (`apps/backend/handlers/scheduled_execution_handler.py`). The gate detects counter divergence; correcting counter semantics is a separate workstream.
- Automated repair of orphaned evidence. The gate identifies failures and surfaces them; human-confirmed recovery is always required.
- Phase 4 aggregation changes. The existing Phase 4 integrity gate in `src/release_confidence_platform/aggregation/integrity.py` is unaffected.
- Large-audit pagination design. The MVP gate reads all RUN records and all S3 keys for the audit in bounded queries. Pagination support for very large audits is deferred.

### Future Technical Considerations

- Automated reconciliation workflows for orphaned STARTED records, triggered by gate failure events.
- Pagination support for audits with run counts that exceed a single DynamoDB query page.
- A CloudWatch alarm on `FINALIZATION_INTEGRITY_GATE_FAILURE` events for operational monitoring.

## 5. Architecture Overview

The gate is a pure function. It accepts the audit record, all RUN records for the audit, and all raw S3 evidence keys for the audit, and returns a typed result. The finalization handler calls the gate synchronously before issuing the lifecycle transition. If the gate fails, the handler returns without writing `COMPLETED` and surfaces the structured failure to its caller.

```
AuditFinalizationHandler._complete_finalization(...)
    |
    +--> finalization_integrity_gate(audit, run_records, s3_evidence_keys)
    |         |
    |         +--> GateResult(passed=True)   --> proceed with lifecycle.transition(COMPLETED)
    |         |
    |         +--> GateResult(passed=False,  --> raise FinalizationGateError(failure_payload)
    |                  failed_checks=[...])       handler returns without COMPLETED transition
    |
    +--> (only on GateResult.passed) lifecycle.transition(COMPLETED)
```

The gate does not write to DynamoDB or S3. It reads. The transition is a separate operation issued only after the gate passes.

## 6. System Components

| Component | Responsibility |
| --- | --- |
| `finalization_integrity_gate` function | Evaluates all six checks. Returns `GateResult`. Pure function, no side effects. |
| `GateResult` dataclass | Typed result carrying `passed: bool`, `failed_checks: list[CheckFailure]`, `timestamp: str`. |
| `CheckFailure` dataclass | Carries `check: str`, `expected: int \| None`, `actual: int \| None`, `detail: str`. |
| `FinalizationGateError` exception | Raised by the handler when the gate fails. Carries the structured error payload. |
| `AuditFinalizationHandler._complete_finalization(...)` | Invokes the gate and handles `FinalizationGateError`. Existing method, updated to include the gate call. |
| `AuditMetadataRepository` | Existing repository. The handler already uses it; it must provide `list_run_records(client_id, audit_id)` for gate input. |
| `S3StorageClient` | Existing client. Must provide `list_raw_evidence_keys(client_id, audit_id)` for gate input. |

## 7. Data Models

### GateResult

**Purpose:** Carries the complete pass or failure result of a single gate evaluation.

**Fields:**

| Field | Type | Description |
| --- | --- | --- |
| `passed` | `bool` | True only when all six checks pass. |
| `failed_checks` | `list[CheckFailure]` | Empty when passed. One entry per failed check when not passed. |
| `timestamp` | `str` | ISO-8601 UTC timestamp of gate evaluation. |

### CheckFailure

**Purpose:** Carries the detail for one failing gate check.

**Fields:**

| Field | Type | Description |
| --- | --- | --- |
| `check` | `str` | Symbolic check name (see Check names below). |
| `expected` | `int \| None` | Expected value, if numeric. None for non-numeric checks. |
| `actual` | `int \| None` | Actual observed value, if numeric. None for non-numeric checks. |
| `detail` | `str` | Human-readable description of the mismatch, safe to log. |

### Check names (symbolic constants)

These names are the authoritative identifiers for each check. They appear in `CheckFailure.check`, log output, and the structured error payload.

| Constant | Check |
| --- | --- |
| `TERMINAL_COUNT_MATCHES_EXPECTED` | Check 1 |
| `NO_ORPHANED_STARTED_RECORDS` | Check 2 |
| `EVERY_TERMINAL_RUN_HAS_EVIDENCE` | Check 3 |
| `EVERY_EVIDENCE_MAPS_TO_ONE_RUN` | Check 4 |
| `NO_ORPHAN_EVIDENCE` | Check 5 |
| `COUNTER_RECONCILIATION` | Check 6 |

## 8. Gate Checks

All six checks must pass. A gate result is `passed=True` only when all six checks pass. If any check fails, the gate returns `passed=False` immediately after evaluating all checks (do not short-circuit; collect all failures so the recovery operator has the complete picture).

### Inputs

| Input | Source | Description |
| --- | --- | --- |
| `audit` | DynamoDB audit metadata item | Provides `finalization.execution_count`, `execution_counters.total_completed`, `execution_counters.total_started`. |
| `run_records` | DynamoDB query: `AUDIT#{audit_id}#RUN#` prefix | All RUN child records for the audit, as persisted by `DynamoDBMetadataClient`. |
| `s3_evidence_keys` | S3 list: `raw-results/{client_id}/{audit_id}/` prefix | All raw evidence object keys for the audit. Each key contains the run_id path segment by platform convention: `raw-results/{client_id}/{audit_id}/{run_id}/results.json`. |

### Check 1 — Terminal count matches expected

Count the RUN records whose `status` is one of `COMPLETED`, `FAILED`, or `ERROR` (any value in `RUN_STATUSES` that is not `STARTED`). This count is the authoritative expected value. `finalization.execution_count` on the audit record must equal this count; it is set at finalization trigger time from the RUN record count, not from `execution_counters.total_completed`.

**Pass condition:** `len(terminal_runs) == finalization.execution_count`

Where `finalization.execution_count` is set at finalization trigger time as `len(terminal_run_records)` queried at that moment — not copied from `execution_counters.total_completed`. The RUN record count is the evidence-derived denominator; the counter is not authoritative for this check.

**Failure detail example:** "Expected 25 terminal RUN records (finalization.execution_count), found 24 terminal RUN records in DynamoDB"

Note: for audits with a repeated schedule, one occurrence produces multiple RUN records (for example: 1 occurrence triggers 5 RUN records in the confirmed incident scenario). `execution_counters.total_completed` counts occurrence handler completions, not RUN record writes. Using `total_completed` as the expected count would cause Check 1 to always fail on any clean repeated-schedule audit. The correct expected value is always the persisted RUN record count as of finalization trigger time.

### Check 2 — No orphaned STARTED records

Count the RUN records whose `status` is `STARTED`. This count must be zero.

**Pass condition:** `len(started_runs) == 0`

**Failure detail example:** "2 RUN records remain in STARTED state: [run_id_1, run_id_2]"

This is the primary check that would have blocked the incident on audit `audit_20260609_b18fee6a`. The orphaned item with `SK=AUDIT#audit_20260609_b18fee6a#RUN#48a87626-e2f9-4f81-82ff-[REDACTED]ec` and `status=STARTED` would have failed this check.

### Check 3 — Every terminal RUN has raw evidence

For each terminal RUN record, derive the expected S3 key path using the platform convention: `raw-results/{client_id}/{audit_id}/{run_id}/results.json`. Verify that a key matching that path exists in `s3_evidence_keys`.

**Pass condition:** for every terminal RUN record, the expected S3 key is present in the evidence key set.

**Failure detail example:** "1 terminal RUN record has no corresponding S3 evidence object: run_id=abc123, searched_key=raw-results/client_xyz/audit_abc/abc123/results.json"

The `searched_key` field must be included verbatim in every Check 3 `CheckFailure.detail` so that recovery operators can distinguish a key-mismatch failure (evidence exists under a different path, e.g., due to sanitizer mutation of the run_id used to construct the key) from a case where the evidence object is genuinely absent from S3. Without `searched_key`, the operator cannot determine which key was looked up or verify whether the object exists under an alternate path.

Note: extract `run_id` from the terminal RUN record using the `run_id` field, not by parsing the `SK`. The `SK` may be sanitized (as demonstrated in the incident); the `run_id` field on the item should be used for the key construction.

### Check 4 — Every raw evidence maps to exactly one RUN

For each raw S3 evidence key, extract the `run_id` path segment (the directory component between `{audit_id}/` and `/results.json`). Look up that `run_id` in the set of all RUN records. Verify that exactly one RUN record exists with that `run_id`.

**Pass condition:** for every S3 evidence key, exactly one RUN record has a matching `run_id`.

**Failure detail example:** "S3 evidence key .../48a87626-e2f9-4f81-82ff-2475004829ec/results.json has no matching RUN record (0 found)"

This check surfaces the key mismatch described in the incident: the S3 key uses the unsanitized UUID `2475004829ec` while the DynamoDB RUN record was written under the sanitized key `[REDACTED]ec`, so no RUN record is found for the S3 path.

### Check 5 — No orphan evidence

For each S3 evidence key, verify that the corresponding RUN record (if found) is in a terminal state, not `STARTED`.

**Pass condition:** every S3 evidence key maps to a terminal RUN record.

**Failure detail example:** "S3 evidence key .../run_id_x/results.json maps to a STARTED RUN record"

This check prevents an audit from completing when raw evidence exists for a run whose RUN record has not reached a terminal state.

### Check 6 — Counter reconciliation

Verify that the operational counters on the audit metadata item are consistent with the persisted terminal RUN record counts. Specifically:

- `execution_counters.total_completed` as stored on the audit item must equal `len(terminal_runs)`.

This check is informational evidence of counter/evidence divergence. It surfaces the counter increment defect described in `docs/bugs/phase_3_phase_4_execution_integrity_rca.md` under "Confirmed Counter/Reconciliation Defect".

**Pass condition:** `audit["execution_counters"]["total_completed"] == len(terminal_runs)`

**Failure detail example:** "Counter total_completed=25 does not match terminal RUN record count=24"

Note: this check alone is not sufficient to block completion; Checks 1 and 2 are the primary blocking checks. Check 6 is included to make counter divergence visible in gate failure reports even when the run count itself happens to match.

## 9. Gate Trigger

The gate is invoked by `AuditFinalizationHandler._complete_finalization(...)` in `apps/backend/handlers/audit_finalization_handler.py` before every `FINALIZING -> COMPLETED` transition, including the retry path in `_handle_finalizing_retry(...)`.

**When:** immediately before `self.lifecycle.transition(...)` is called with `next_state=LIFECYCLE_STATE_COMPLETED`.

**Who invokes:** the finalization handler. No other code path should issue a `COMPLETED` lifecycle transition.

**Blocking:** gate failure must prevent `lifecycle.transition(COMPLETED)` from being called. The finalization handler must catch `FinalizationGateError`, log the full failure payload, and return without transitioning. The audit remains in `FINALIZING`.

**Inputs the handler must supply:**

1. The audit metadata item — already loaded at the start of `handle(...)`.
2. All RUN records for the audit — new query, to be added to the handler: `repository.list_run_records(client_id, audit_id)`.
3. All raw S3 evidence keys for the audit — new list operation, to be added to the handler: `s3_storage.list_raw_evidence_keys(client_id, audit_id)`.

The S3StorageClient (`packages/storage/s3_client.py`) must be injected into the finalization handler alongside the existing repository. The handler bootstrap in the `handler(...)` function at the bottom of `apps/backend/handlers/audit_finalization_handler.py` must be updated to inject it.

## 10. Backend Logic

### Responsibilities

- Accept audit record, run records list, and S3 evidence keys list as inputs.
- Evaluate all six checks in sequence, collecting all failures before returning.
- Return `GateResult(passed=True)` if all checks pass, `GateResult(passed=False, failed_checks=[...])` otherwise.
- Never write to DynamoDB or S3.
- Never raise an exception for a normal gate failure; only raise for unexpected infrastructure errors (e.g., malformed inputs that indicate a programming error).

### Validation Flow

Before running checks, the gate must validate that its inputs are structurally complete:

- `audit` is a non-empty dict with a `finalization` sub-dict containing a valid integer `execution_count > 0`.
- `run_records` is a list (may be empty; an empty list will fail Check 1 and Check 2 if expected count is nonzero).
- `s3_evidence_keys` is a list (may be empty; an empty list will fail Check 3 if terminal runs exist).

If inputs fail structural validation, raise `ValueError` with a clear description. This is a programming error, not a gate failure.

### Business Rules

- Terminal states for RUN records are `COMPLETED`, `FAILED`, and `ERROR`. These are the values in `RUN_STATUSES` minus `STARTED`. The gate must not hardcode these values; it must use the constants from `release_confidence_platform.core.constants.engine`.
- The S3 key convention is `raw-results/{client_id}/{audit_id}/{run_id}/results.json`. The gate extracts `run_id` from S3 keys by splitting on `/` and reading the fourth path segment (index 3, zero-based, after `raw-results`).
- Collect all failing checks before returning rather than short-circuiting on the first failure.

### Persistence Flow

None. The gate is read-only.

### Error Handling

| Scenario | Behavior |
| --- | --- |
| All checks pass | Return `GateResult(passed=True, failed_checks=[])` |
| One or more checks fail | Return `GateResult(passed=False, failed_checks=[...])` |
| Structurally invalid inputs | Raise `ValueError` (programming error, not gate failure) |
| Unexpected infrastructure error during input fetch (in handler, not gate) | Propagate exception; do not issue COMPLETED transition |

## 11. Failure Behavior

When the gate returns `passed=False`:

1. The finalization handler must NOT call `lifecycle.transition(COMPLETED)`.
2. The handler must log the full failure payload using the structured logger at level `ERROR`.
3. The handler must raise `FinalizationGateError` carrying the structured error payload.
4. The audit lifecycle state remains `FINALIZING`.
5. The handler does not auto-retry. The failure is surfaced to the caller (EventBridge Scheduler, which will record a Lambda invocation failure).

The audit stays in `FINALIZING` until either:
- The root cause is corrected (e.g., the orphaned STARTED record is resolved by the administrative recovery procedure) and the finalization handler is re-invoked (idempotent re-delivery), at which point the gate is re-evaluated; or
- An operator triggers the recovery procedure and manually advances the lifecycle after confirming evidence consistency.

### Structured Error Format

The `FinalizationGateError` payload, and the corresponding log entry, must conform to this structure:

```json
{
  "type": "FINALIZATION_INTEGRITY_GATE_FAILURE",
  "auditId": "audit_20260609_b18fee6a",
  "timestamp": "2026-06-11T10:00:00.000000Z",
  "failedChecks": [
    {
      "check": "NO_ORPHANED_STARTED_RECORDS",
      "expected": 0,
      "actual": 1,
      "detail": "1 RUN record remains in STARTED state: 48a87626-e2f9-4f81-82ff-[REDACTED]ec"
    },
    {
      "check": "EVERY_TERMINAL_RUN_HAS_EVIDENCE",
      "expected": null,
      "actual": null,
      "detail": "1 terminal RUN record has no corresponding S3 evidence object: run_id=48a87626-e2f9-4f81-82ff-[REDACTED]ec, searched_key=raw-results/client_xyz/audit_20260609_b18fee6a/48a87626-e2f9-4f81-82ff-[REDACTED]ec/results.json"
    },
    {
      "check": "EVERY_EVIDENCE_MAPS_TO_ONE_RUN",
      "expected": null,
      "actual": null,
      "detail": "S3 evidence key raw-results/.../48a87626-e2f9-4f81-82ff-2475004829ec/results.json has no matching RUN record (0 found)"
    }
  ]
}
```

The `searched_key` value in `EVERY_TERMINAL_RUN_HAS_EVIDENCE` failures is the exact S3 key path constructed from the `run_id` field of the RUN record. Its presence allows the recovery operator to verify: (a) the object does not exist at that path, and (b) whether the object exists under an alternate path using the unsanitized UUID — confirming a sanitizer key-mismatch rather than a genuinely missing evidence object.

The `detail` field in each `CheckFailure` must not include raw PII. Run IDs and S3 keys are structural identifiers, not PII, and must be included verbatim to support operational reconciliation. Do not pass this payload through the shared `sanitize()` function; the identifier values must remain unredacted for operator recovery use.

## 12. Recovery Procedure

The recovery path is an administrative reconciliation procedure. It is not reachable through normal execution paths (scheduled execution handler, operator CLI audit commands, or EventBridge triggers). Access requires privileged IAM credentials, an approved recovery runbook, and human confirmation before any state-mutating step.

### Requirements

- **Privileged access.** Not reachable via normal execution paths.
- **Fully auditable.** Every read, decision, and write must be logged with the operator identity, timestamp, reason, and the evidence state before and after.
- **Deterministic.** The same input evidence produces the same resolution action.
- **Non-destructive.** No evidence is deleted without explicit operator confirmation and a documented reason. Orphaned S3 objects are quarantined, not deleted.

### Recovery Steps

**Step 1 — Obtain the gate failure report.** Read the `FinalizationGateError` log entry for the target audit from CloudWatch. Identify all `failedChecks`.

**Step 2 — For each orphaned STARTED record (Check 2 failure):**

a. Query the DynamoDB RUN record by its sanitized SK. Note the `run_id` as stored in the DynamoDB item (which may be sanitized).

b. Determine whether execution completed externally by checking CloudWatch logs for the Lambda request that wrote the STARTED record. Look for `raw_result_write_completed` and `terminal_metadata_update_failed` log entries.

c. If execution completed and raw evidence exists: the recovery operator may update the RUN record to `COMPLETED` (or `FAILED` if execution failed) using a direct DynamoDB update, recording `completed_at`, `raw_result_s3_key` (the S3 path under the unsanitized run_id), and a `reconciliation_note` explaining the recovery action. This requires an approved DynamoDB write operation with full before/after logging.

d. If execution did not complete or evidence is ambiguous: update the RUN record `status` to `ERROR` with `completed_at` set to the reconciliation timestamp and a `reconciliation_note` documenting the reason.

e. In either case, log the action: operator identity, timestamp, run_id, previous state, new state, and reconciliation_note.

**Step 3 — For each orphaned S3 evidence key (Check 4 or Check 5 failure):**

a. Extract the `run_id` from the S3 key path.

b. Attempt to match the S3 key to a DynamoDB RUN record using the unsanitized run_id (not the sanitized key in DynamoDB). If a STARTED record exists under the sanitized equivalent, this confirms the root cause described in the RCA.

c. If a matching RUN record is found: update the RUN record to a terminal state per Step 2c or 2d.

d. If no matching RUN record exists at all: quarantine the S3 object by adding a metadata tag `quarantine_reason=no_run_record` and `quarantine_at=<timestamp>`. Do not delete the object. Log the quarantine action.

**Step 4 — Re-run the gate.** Re-invoke the finalization handler for the audit (which will re-run the gate against the updated evidence). If all checks pass, the handler will issue the `COMPLETED` transition.

**Step 5 — If checks still fail:** escalate. Do not issue a manual `COMPLETED` lifecycle transition outside the finalization handler. The gate must pass before `COMPLETED` is written.

## 13. Implementation Notes

### Gate function signature

The gate must be implemented as a standalone function (or static method) in a new module. Suggested location: `src/release_confidence_platform/audit_lifecycle/finalization_gate.py`.

Suggested signature:

```python
def finalization_integrity_gate(
    *,
    audit: dict[str, Any],
    run_records: list[dict[str, Any]],
    s3_evidence_keys: list[str],
    client_id: str,
    audit_id: str,
) -> GateResult:
    ...
```

The function must be a pure function: given the same inputs, it always returns the same result. It must not call DynamoDB or S3 directly. All reads are the caller's responsibility; the gate only evaluates the provided data.

### Idempotency

The gate is idempotent. Running it multiple times against the same inputs returns the same `GateResult`. There is no gate state to reset.

### Handler integration points

In `apps/backend/handlers/audit_finalization_handler.py`:

- Inject `s3_storage: S3StorageClient` into `AuditFinalizationHandler.__init__(...)`.
- Before `_complete_finalization(...)` calls `lifecycle.transition(COMPLETED)`, add:
  1. `run_records = repository.list_run_records(client_id, audit_id)`
  2. `s3_keys = s3_storage.list_raw_evidence_keys(client_id, audit_id)`
  3. `gate_result = finalization_integrity_gate(audit=audit, run_records=run_records, s3_evidence_keys=s3_keys, client_id=client_id, audit_id=audit_id)`
  4. If `not gate_result.passed`: log the failure payload and raise `FinalizationGateError(gate_result)`.
- Apply the same gate call in `_handle_finalizing_retry(...)` before the existing `_complete_finalization(...)` call.
- Update the `handler(...)` bootstrap function to inject `S3StorageClient`.

### Gate failure payload logging — identifier preservation requirement

Gate failure payloads are audit-trail records, not user-facing output. They must preserve raw identifier values (`run_id`, S3 key paths) for operator recovery. These values must not be passed through `StructuredLogger`, which unconditionally calls `sanitize()` on all fields (confirmed in `packages/core/logging.py:52`). `sanitize()` would mutate `run_id` values containing phone-pattern digit sequences, destroying the diagnostic information required for recovery reconciliation.

The finalization handler must log gate failure payloads using one of the following approaches:

1. **Direct structured JSON output (preferred for MVP):** use `logging.getLogger(__name__).error(json.dumps(payload))` where `payload` is the `FinalizationGateError` structured dict. This bypasses `StructuredLogger` entirely and emits the payload byte-identical.

2. **`StructuredLogger` with explicit PII-bypass (deferred):** extend `StructuredLogger` with a `sanitize: bool = True` parameter that, when set to `False`, skips the `sanitize()` call. This is a future enhancement; the direct JSON path is sufficient for MVP.

The handler must NOT call `structured_logger.log(...)` for gate failure payloads until option 2 is implemented. The implementation note at the call site must read: "Gate failure payload logged via direct JSON — do not route through StructuredLogger without sanitize=False support."

### Repository additions required

`packages/storage/audit_metadata_client.py` (the `AuditMetadataRepository` class) must expose:

- `list_run_records(client_id: str, audit_id: str) -> list[dict]`: queries all items with `PK=CLIENT#{client_id}` and `SK` beginning with `AUDIT#{audit_id}#RUN#`. Returns the decoded item list.

`packages/storage/s3_client.py` (the `S3StorageClient` class) must expose:

- `list_raw_evidence_keys(client_id: str, audit_id: str) -> list[str]`: lists all S3 object keys under the prefix `raw-results/{client_id}/{audit_id}/`. Returns the key strings.

Both methods must handle pagination (DynamoDB `LastEvaluatedKey` and S3 `ContinuationToken`) and return the complete result set.

### Test coverage requirements

**Unit tests for the gate function (one test per check, each in isolation):**

- Check 1 pass: terminal run count equals expected.
- Check 1 fail: terminal run count less than expected.
- Check 1 fail: terminal run count greater than expected.
- Check 2 pass: no STARTED records.
- Check 2 fail: one STARTED record present.
- Check 2 fail: multiple STARTED records present.
- Check 3 pass: every terminal run has a matching S3 key.
- Check 3 fail: one terminal run has no matching S3 key.
- Check 4 pass: every S3 key maps to exactly one RUN record.
- Check 4 fail: one S3 key has no matching RUN record (the sanitized-key mismatch scenario).
- Check 4 fail: one S3 key maps to more than one RUN record.
- Check 5 pass: all S3 keys map to terminal RUN records.
- Check 5 fail: one S3 key maps to a STARTED RUN record.
- Check 6 pass: counter equals terminal run count.
- Check 6 fail: counter exceeds terminal run count.
- Check 6 fail: counter is less than terminal run count.
- Multiple check failures collected: both Check 2 and Check 4 fail, both failures appear in `failed_checks`.

**Integration tests for the gate within the finalization handler:**

- Full gate pass: handler with consistent evidence completes the COMPLETED transition.
- Check 2 failure: handler with one STARTED record does not transition to COMPLETED and logs the gate failure payload.
- Check 4 failure: handler with an orphaned S3 key (no matching RUN record) does not transition to COMPLETED.
- Retry path: handler in FINALIZING retry path also invokes the gate and blocks on failure.
- Gate pass on retry: after recovery resolves a STARTED record, the retry path succeeds.

**Regression test for the specific incident scenario:**

- Build inputs representing audit `audit_20260609_b18fee6a` state at the time of incident: 25 expected, 28 terminal runs, 1 STARTED run, 29 S3 keys, one S3 key whose run_id does not match any RUN record `run_id` field.
- Assert gate returns `passed=False`.
- Assert `failed_checks` includes at minimum `NO_ORPHANED_STARTED_RECORDS` and `EVERY_EVIDENCE_MAPS_TO_ONE_RUN`.
- Assert the handler does not issue the `COMPLETED` lifecycle transition.

## 14. File Structure

New file:

```
src/release_confidence_platform/audit_lifecycle/finalization_gate.py
```

Modified files:

```
apps/backend/handlers/audit_finalization_handler.py
packages/storage/audit_metadata_client.py
packages/storage/s3_client.py
```

New test files:

```
tests/unit/audit_lifecycle/test_finalization_gate.py
tests/integration/test_finalization_integrity_gate.py
```

## 15. Security

- The gate is read-only. It has no write permissions or side effects.
- Gate failure payloads contain run IDs and S3 key paths. These are structural identifiers, not PII. They must not be passed through `sanitize()`. They must be included verbatim in logs to support recovery.
- The gate function must not be callable from any normal execution path by an operator or customer. It is invoked exclusively by the finalization handler.
- The recovery procedure requires privileged IAM credentials. The IAM role for the finalization Lambda must NOT be expanded to include DynamoDB item-level update permissions for run records. Recovery operations require a separate privileged administrative role not attached to any Lambda.

## 16. Reliability

- The gate reads from DynamoDB and S3. Both calls must use the existing client retry semantics (already implemented in `src/release_confidence_platform/storage/dynamodb_client.py` and `packages/storage/s3_client.py`).
- If the DynamoDB list or S3 list call fails (infrastructure error, not gate failure), the exception propagates to the finalization handler, which does not issue the `COMPLETED` transition. This is fail-closed by default.
- The gate must complete within the finalization Lambda timeout. At MVP audit sizes (tens to low hundreds of run records), single-page queries are expected. If DynamoDB pagination is encountered, the gate must follow all pages to completion before evaluating checks.
- Gate evaluation adds latency to the finalization path. This is acceptable because finalization runs once per audit at the end of the audit window, not on the hot execution path.

## 17. Dependencies

| Dependency | Purpose |
| --- | --- |
| `src/release_confidence_platform/core/constants/engine.py` | `RUN_STATUSES` — authoritative set of valid run status values. |
| `packages/storage/audit_metadata_client.py` | `AuditMetadataRepository.list_run_records(...)` — provides DynamoDB RUN records. |
| `packages/storage/s3_client.py` | `S3StorageClient.list_raw_evidence_keys(...)` — provides raw evidence key list. |
| `apps/backend/handlers/audit_finalization_handler.py` | Invokes the gate; handles `FinalizationGateError`. |
| `packages/audit_lifecycle/service.py` | `AuditLifecycleService.transition(...)` — gated by the gate result. |

## 18. Assumptions

- Run IDs embedded in S3 key paths use the unsanitized (canonical) UUID, as confirmed by the incident evidence (`raw-results/.../48a87626-e2f9-4f81-82ff-2475004829ec/results.json`).
- The `run_id` field on a DynamoDB RUN item may be sanitized (incident-confirmed). The gate uses the `run_id` field for RUN-to-S3 matching in Check 3, and the S3 path segment for S3-to-RUN matching in Check 4. These two directions may produce different run_id values for the same run when the sanitizer defect is present. This is intentional: detecting the mismatch is the purpose of Checks 3 and 4.
- `finalization.execution_count` on the audit item was set from `execution_counters.total_completed` at finalization trigger time (confirmed from `audit_finalization_handler.py` line 73). It is the "expected" value against which the gate compares persisted terminal RUN count.
- The platform S3 key convention for raw evidence is `raw-results/{client_id}/{audit_id}/{run_id}/results.json`. This is confirmed by the RCA evidence and the `S3StorageClient` usage in `apps/backend/orchestrator/service.py`.

## 19. Risks and Open Questions

| Risk | Mitigation |
| --- | --- |
| Sanitizer defect persists: gate will surface failures but orphaned STARTED records will keep appearing | Sanitizer fix is a parallel workstream. Gate blocks COMPLETED until fix is deployed and any existing orphans are reconciled. |
| Large audits: DynamoDB list may return thousands of records | Add pagination to `list_run_records`. MVP gate reads all pages before evaluating. |
| S3 list pagination: `list_raw_evidence_keys` must follow `ContinuationToken` | Implement pagination in `S3StorageClient.list_raw_evidence_keys`. Fail-closed if pagination is truncated. |
| Finalization re-delivery while recovery is in progress: gate re-evaluates on each invocation | Gate is idempotent; re-evaluation is safe. Handler will block again until evidence is consistent. |
| Recovery operator makes a DynamoDB update that introduces a new inconsistency | Recovery procedure requires re-running the gate after every state change. Gate catches newly introduced inconsistencies. |

## 20. Relationship to ADR

This document is the mechanical enforcement specification for the invariant defined in `docs/architecture/adr_execution_evidence_source_of_truth.md`. The ADR establishes the principle; this document defines the implementation contract for the gate that enforces it.

Every requirement in this specification traces to the ADR decision: "Finalization must reconcile persisted evidence before allowing COMPLETED transition."
