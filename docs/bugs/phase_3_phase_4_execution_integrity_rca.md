# Phase 3 / Phase 4 Execution Integrity RCA

## Executive Summary

Audit `audit_20260609_b18fee6a` in `dev` / `us-east-1` transitioned to `COMPLETED` even though one persisted `RUN` record remained unresolved with `status = STARTED`, `completed_at = NULL`, `raw_result_s3_key = NULL`, and `failure_summary = NULL`.

**Confirmed root cause:** the Phase 1/3 run metadata persistence path sanitizes the full DynamoDB `RUN` item before the initial `put_item`. The shared sanitizer treats the numeric portion of the generated UUID `48a87626-e2f9-4f81-82ff-2475004829ec` as phone-like PII and mutates both `run_id` and `SK` to `48a87626-e2f9-4f81-82ff-[REDACTED]ec`. Later terminal updates use the unsanitized UUID key, so DynamoDB cannot find the persisted item and returns `ConditionalCheckFailedException`. This leaves the sanitized `STARTED` item orphaned while the S3 raw result object is successfully written under the unsanitized run ID.

**Confirmed integrity gap:** Phase 3 finalization relies on `audit.execution_counters.total_completed`; it does not reconcile canonical persisted `RUN` records or raw S3 evidence before `RUNNING -> FINALIZING -> COMPLETED`. The scheduler handler increments `total_started` and `total_completed` after any orchestrator return, including a returned `FAILED` result caused by terminal metadata write failure. Therefore finalization recorded `execution_count = 25` and completed the audit despite unresolved run evidence.

**Phase 4 status in dev:** no Phase 4 aggregation Lambda is deployed in this environment, the finalization Lambda has no `AGGREGATION_FUNCTION_NAME`, no aggregation log group exists, and no `AGGJOB` records exist for the audit. Therefore no Phase 4 integrity gate executed for this audit. Repository code contains a Phase 4 gate that would fail closed on count mismatch if deployed, but the observed dev incident was not caused by Phase 4 aggregation logic.

**Limited scan result:** isolated within the approved environment/window. A bounded DynamoDB scan found exactly one unresolved `STARTED` run between `2026-06-09T13:21:00Z` and `2026-06-09T15:30:00Z` across 197 scanned table items. CloudWatch log filtering found exactly the two terminal update failures for that same request.

Primary responsibility: **execution engine / persistence** for identifier mutation, with **Phase 3 lifecycle/finalization** as the invariant-enforcement gap and **shared contract** risk between counters, persisted run metadata, raw S3 evidence, and aggregation eligibility.

## Incident Description

- **Source of investigation:** user-requested RCA, cloud/read-only evidence review.
- **Target environment:** `dev`, `us-east-1`, AWS account available through default credentials.
- **Target audit:** `audit_20260609_b18fee6a`.
- **Target client:** `client_phase_4_validation_555d54cc`.
- **Investigation window:** `2026-06-09T13:21:00Z` through `2026-06-09T15:30:00Z`.
- **Architectural invariant under test:** an audit must not transition to `COMPLETED` while any persisted `RUN` record remains unresolved.
- **Observed invariant violation:** canonical audit metadata shows `lifecycle_state = COMPLETED`, while one persisted `RUN` child item remains `STARTED`.

## Timeline Reconstruction

CloudWatch epoch timestamps were queried for the approved window. Lambda request IDs are included where available from log records.

| Timestamp UTC | Component | Request / correlation ID | Source event | Persisted state / evidence | Notes |
| --- | --- | --- | --- | --- | --- |
| `2026-06-09T13:21:25.229491Z` | audit metadata persistence | not available in inspected logs | audit creation/config init path | Audit item created with `PK=CLIENT#client_phase_4_validation_555d54cc`, `SK=AUDIT#audit_20260609_b18fee6a`, `lifecycle_state` later observed as `COMPLETED`; `audit_window.start_time=2026-06-09T13:21:22.814418Z`, `audit_window.end_time=2026-06-09T15:21:22.814418Z`; `config_version=v1`. | Source: DynamoDB audit metadata `created_at`. |
| `2026-06-09T13:22:28.844576Z` | Phase 3 scheduling | not available in inspected logs | operator scheduling | `lifecycle_history`: `DRAFT -> SCHEDULED`, actor `operator_cli`, reason `schedules_created`, `schedule_count=26`. | Metadata contains 24 baseline schedules, 1 repeated schedule, 1 finalization schedule. |
| `2026-06-09T13:23:02.511097Z` | scheduled execution handler / lifecycle | scheduledExecution request for first baseline not fully expanded here | EventBridge baseline occurrence | `lifecycle_history`: `SCHEDULED -> RUNNING`, actor `orchestrator`, reason `scheduled_occurrence_started`. | First accepted scheduled occurrence started audit execution. |
| `2026-06-09T13:23:02Z` through `2026-06-09T15:17:23Z` | scheduled execution handler + core orchestrator | multiple scheduledExecution requests | EventBridge baseline/repeated occurrences | 25 occurrence claim records persisted with `claim_status=completed`; 29 run records were present: 28 `COMPLETED`, 1 `STARTED`. | The repeated schedule produced 5 run records but one occurrence/counter increment. |
| `2026-06-09T14:37:58.272117Z` | core orchestrator inside scheduledExecution | `fa6a2825-21f3-4610-bce1-96808454fd26` | baseline occurrence scheduled for `2026-06-09T14:37:21.048039Z` | Log: `event_validation_completed`; run ID generated as `48a87626-e2f9-4f81-82ff-[REDACTED]ec` in logs. | Actual S3 key later proves unsanitized UUID suffix was `2475004829ec`; sanitizer redacted the phone-like digit sequence in persisted/logged strings. |
| `2026-06-09T14:37:58.337753Z` | core orchestrator | `fa6a2825-21f3-4610-bce1-96808454fd26` | same baseline occurrence | Log: `duplicate_preflight_completed`. | Duplicate preflight passed. |
| `2026-06-09T14:37:58.338129Z` | core orchestrator / DynamoDB run metadata | `fa6a2825-21f3-4610-bce1-96808454fd26` | same baseline occurrence | Log: `metadata_started_write_started`. | Initial run metadata write attempted. |
| `2026-06-09T14:37:58.345232Z` | core orchestrator / DynamoDB run metadata | `fa6a2825-21f3-4610-bce1-96808454fd26` | same baseline occurrence | Log: `metadata_started_write_completed`; DDB persisted `SK=AUDIT#audit_20260609_b18fee6a#RUN#48a87626-e2f9-4f81-82ff-[REDACTED]ec`, `status=STARTED`, `started_at=2026-06-09T14:37:58.337989Z`. | This is the first bad persistence point: primary-key material was sanitized/mutated. |
| `2026-06-09T14:37:58.430058Z` | core orchestrator | `fa6a2825-21f3-4610-bce1-96808454fd26` | same baseline occurrence | Log: `config_load_completed`, `endpoint_count=5`, `schedule_iteration_count=1`. | Execution proceeded after STARTED item write. |
| `2026-06-09T14:37:58.430314Z` through `2026-06-09T14:38:00.690469Z` | API runner | `fa6a2825-21f3-4610-bce1-96808454fd26` | endpoint executions | Five endpoint `endpoint_execution_started`/`endpoint_execution_completed` log pairs; all recorded `failure_type=PASS`. | The outbound execution itself completed. |
| `2026-06-09T14:38:00.691962Z` | S3 raw evidence writer | `fa6a2825-21f3-4610-bce1-96808454fd26` | same baseline occurrence | Log: `raw_result_write_started`. | Raw evidence write began. |
| `2026-06-09T14:38:00.744954Z` | S3 raw evidence writer | `fa6a2825-21f3-4610-bce1-96808454fd26` | same baseline occurrence | Log: `raw_result_write_completed`; S3 object exists at `raw-results/client_phase_4_validation_555d54cc/audit_20260609_b18fee6a/48a87626-e2f9-4f81-82ff-2475004829ec/results.json`, `LastModified=2026-06-09T14:38:01Z`, `Size=6210`. | Raw evidence exists but is not linked from the run metadata item. |
| `2026-06-09T14:38:00.745235Z` | DynamoDB terminal run metadata update | `fa6a2825-21f3-4610-bce1-96808454fd26` | same baseline occurrence | Log: `terminal_metadata_update_started`, `terminal_status=COMPLETED`. | Terminal update used the unsanitized UUID key. |
| `2026-06-09T14:38:00.753719Z` | DynamoDB terminal run metadata update | `fa6a2825-21f3-4610-bce1-96808454fd26` | same baseline occurrence | Log: `terminal_metadata_update_failed`, `error_type=STORAGE_ERROR`, `aws_error_code=ConditionalCheckFailedException`, `operation=update_item`, `terminal_status=COMPLETED`. | The unsanitized key did not match the sanitized persisted `SK`, so the condition `attribute_exists(PK) AND attribute_exists(SK)` failed. |
| `2026-06-09T14:38:00.754017Z` | orchestrator failure path | `fa6a2825-21f3-4610-bce1-96808454fd26` | failure handling after completed update failure | Log: `terminal_metadata_update_started`, `terminal_status=FAILED`. | Failure path attempted to mark same run failed. |
| `2026-06-09T14:38:00.765381Z` | DynamoDB terminal run metadata update | `fa6a2825-21f3-4610-bce1-96808454fd26` | failure handling | Log: `terminal_metadata_update_failed`, `aws_error_code=ConditionalCheckFailedException`, `terminal_status=FAILED`. | Failed update used same unsanitized key and failed for the same reason. |
| `2026-06-09T14:38:00.765691Z` | orchestrator failure response | `fa6a2825-21f3-4610-bce1-96808454fd26` | failure handling | Log: `run_failed`, `event_type=STORAGE_ERROR`; subsequent log `run_returning`, `status=FAILED`. | Orchestrator returned a failure result; it did not raise to scheduled handler. |
| `2026-06-09T14:38:00.766110Z` | scheduled execution handler | `fa6a2825-21f3-4610-bce1-96808454fd26` | same baseline occurrence | Log: `orchestrator_execution_completed`, `run_id=... [REDACTED]ec`; occurrence record later shows `claim_status=completed`, `completed_at=2026-06-09T14:38:00.766464Z`. | Scheduled handler treated returned result as completed enough to complete occurrence processing. |
| `2026-06-09T14:38:00.766464Z` | scheduled execution handler / audit metadata counters | `fa6a2825-21f3-4610-bce1-96808454fd26` | same baseline occurrence | Occurrence item persisted `claim_status=completed`, `run_id=48a87626-e2f9-4f81-82ff-[REDACTED]ec`; audit counter later includes this occurrence. | Counter increment is independent of terminal `RUN` state. |
| `2026-06-09T15:17:23.807175Z` | scheduled execution handler / audit metadata counters | `db6a282e-81c0-4b4f-84f2-ca189e10bb1c` for last baseline | final baseline occurrence | Audit metadata `execution_counters.total_started=25`, `total_completed=25`, `last_execution_at=2026-06-09T15:17:23.807175Z`. | Counters represent scheduler occurrence completions, not terminal run-record reconciliation. |
| `2026-06-09T15:22:57.359910Z` | audit finalization handler | `a86a282f-ad94-41b5-9164-4bbadd0c9c57` | EventBridge finalization schedule | Finalization metadata persisted: `execution_count=25`, `zero_execution=false`, `source=eventbridge_scheduler`, `schedule_occurrence_id=finalization#2026-06-09T15:22:21.048039Z`. | Finalization used `execution_counters.total_completed` only. |
| `2026-06-09T15:22:57.360251Z` | audit finalization handler / lifecycle | `a86a282f-ad94-41b5-9164-4bbadd0c9c57` | finalization trigger | `lifecycle_history`: `RUNNING -> FINALIZING`, reason `finalization_trigger`, metadata `execution_count=25`. | No persisted RUN reconciliation occurred before transition. |
| `2026-06-09T15:22:57.419283Z` | audit finalization handler / lifecycle | `a86a282f-ad94-41b5-9164-4bbadd0c9c57` | finalization completion | `lifecycle_history`: `FINALIZING -> COMPLETED`, reason `finalization_completed`, metadata `execution_count=25`; audit `updated_at=2026-06-09T15:22:57.419372Z`. | Invariant violation became durable here. |
| `2026-06-09T15:22:57Z` through `2026-06-09T15:30:00Z` | Phase 4 aggregation | none observed | expected post-finalization internal trigger | No `AUDIT#audit_20260609_b18fee6a#AGGJOB#` items; no `auditAggregation` Lambda exists; no aggregation log group exists; finalization Lambda env lacks `AGGREGATION_FUNCTION_NAME`. | Phase 4 did not run in dev for this audit. |

### Execution occurrence summary

- Occurrence claim records for target audit: `25`, all `claim_status=completed`.
- Completed persisted `RUN` records: `28`.
- Unresolved persisted `RUN` records: `1`.
- Raw S3 result objects: `29`.
- Audit counters: `total_started=25`, `total_completed=25`.
- Finalization metadata: `execution_count=25`, `zero_execution=false`.

The count differences are explained by two separate semantics and one defect:

1. The repeated schedule has one occurrence but produces five run records.
2. The baseline occurrence at `2026-06-09T14:37:21.048039Z` wrote raw S3 evidence but failed both terminal run metadata updates.
3. The scheduled handler increments audit counters per accepted scheduled occurrence, not per terminal `RUN` record, and does so even when the orchestrator returns `status=FAILED`.

## Evidence Collected

### Cloud/DynamoDB/S3 evidence

- **Audit metadata item:** `release-confidence-platform-dev-metadata`, key `CLIENT#client_phase_4_validation_555d54cc` / `AUDIT#audit_20260609_b18fee6a`.
  - `lifecycle_state = COMPLETED`.
  - `execution_counters.total_started = 25`.
  - `execution_counters.total_completed = 25`.
  - `finalization.execution_count = 25`.
  - `finalization.zero_execution = false`.
  - `config_version = v1`.
  - Lifecycle history contains `RUNNING -> FINALIZING` at `2026-06-09T15:22:57.360251Z` and `FINALIZING -> COMPLETED` at `2026-06-09T15:22:57.419283Z`.
- **Run metadata query:** same table, prefix `AUDIT#audit_20260609_b18fee6a#RUN#`.
  - `Count=29`.
  - Status distribution: `COMPLETED=28`, `STARTED=1`.
  - Orphan item: `SK=AUDIT#audit_20260609_b18fee6a#RUN#48a87626-e2f9-4f81-82ff-[REDACTED]ec`, `status=STARTED`, `completed_at=NULL`, `raw_result_s3_key=NULL`, `failure_summary=NULL`.
- **S3 raw result listing:** bucket `release-confidence-platform-dev-raw-results`, prefix `raw-results/client_phase_4_validation_555d54cc/audit_20260609_b18fee6a/`.
  - `29` raw result objects exist.
  - Orphan run's raw evidence object exists under unsanitized UUID path: `.../48a87626-e2f9-4f81-82ff-2475004829ec/results.json`, last modified `2026-06-09T14:38:01Z`.
- **Occurrence query:** 25 occurrence claim records, all `claim_status=completed`.
  - Orphan occurrence item persisted `run_id=48a87626-e2f9-4f81-82ff-[REDACTED]ec`, `completed_at=2026-06-09T14:38:00.766464Z`.
- **Aggregation query:** no `AUDIT#audit_20260609_b18fee6a#AGGJOB#` items.
- **Execution identity query:** no `AUDIT#audit_20260609_b18fee6a#EXECUTION_ID` item.

### CloudWatch evidence

- Log group `/aws/lambda/release-confidence-platform-dev-scheduledExecution` contains request `fa6a2825-21f3-4610-bce1-96808454fd26` for orphan run.
- Key log sequence for that request:
  - `metadata_started_write_completed` at `2026-06-09T14:37:58.345232Z`.
  - `raw_result_write_completed` at `2026-06-09T14:38:00.744954Z`.
  - `terminal_metadata_update_failed` at `2026-06-09T14:38:00.753719Z`, `terminal_status=COMPLETED`, `aws_error_code=ConditionalCheckFailedException`, `operation=update_item`.
  - `terminal_metadata_update_failed` at `2026-06-09T14:38:00.765381Z`, `terminal_status=FAILED`, same error.
  - `run_failed` and `run_returning status=FAILED` at `2026-06-09T14:38:00.765Z`.
  - `orchestrator_execution_completed` at `2026-06-09T14:38:00.766110Z`.
- Log group `/aws/lambda/release-confidence-platform-dev-auditFinalization` contains request `a86a282f-ad94-41b5-9164-4bbadd0c9c57`, `START` at `2026-06-09T15:22:55.883Z`, `END/REPORT` at `2026-06-09T15:22:57.442Z`. The deployed finalization code emitted no structured finalization logs.
- Lambda configuration for `release-confidence-platform-dev-auditFinalization`:
  - `LastModified=2026-06-04T14:22:04.000+0000`.
  - Environment has `RAW_RESULTS_BUCKET`, `STAGE`, `METADATA_TABLE`, `LOG_LEVEL`, `SCHEDULER_GROUP_NAME`.
  - **No `AGGREGATION_FUNCTION_NAME`.**
- `release-confidence-platform-dev-auditAggregation` function does not exist.
- No `/aws/lambda/release-confidence-platform-dev-auditAggregation` log group exists.

### Repository/code evidence

- `apps/backend/orchestrator/service.py`
  - `_started_item(...)` builds run metadata with `**self.metadata_storage.keys(event.client_id, event.audit_id, event.run_id)`, `run_id`, `status=STARTED`, `raw_result_s3_key=None`, `completed_at=None`.
  - Successful path writes S3 raw results before calling `metadata_storage.update_terminal(...)` with the unsanitized `event.run_id` key.
  - Failure path catches `EngineError`/generic exceptions and returns a sanitized failure response rather than raising to the scheduled handler.
- `src/release_confidence_platform/storage/dynamodb_client.py`
  - `keys(...)` returns `SK=f"AUDIT#{audit_id}#RUN#{run_id}"`.
  - `put_started_once(...)` writes `Item=sanitize(item)`.
  - `update_terminal(...)` updates by key and only sanitizes update values, not key.
  - `update_terminal(...)` requires `ConditionExpression="attribute_exists(PK) AND attribute_exists(SK)"`.
- `src/release_confidence_platform/sanitization/sanitizer.py`
  - `PHONE_PATTERN` redacts 10-digit phone-like substrings in all strings.
  - `sanitize(...)` recursively sanitizes all mapping values, including persistence keys and identifiers.
  - This explains `2475004829` within the UUID being replaced by `[REDACTED]` in the persisted `SK` and `run_id`.
- `apps/backend/handlers/scheduled_execution_handler.py`
  - After `self.orchestrator.run(...)`, handler sets occurrence `claim_status=completed` and increments `total_started` and `total_completed` unconditionally on the normal return path.
  - It does not require returned `result.status == COMPLETED` and does not verify the terminal `RUN` record.
- `apps/backend/handlers/audit_finalization_handler.py`
  - `execution_count = (audit.get("execution_counters") or {}).get("total_completed", 0)`.
  - It records `finalization.execution_count` from counters and transitions to `COMPLETED` when count is nonzero.
  - It does not query/reconcile `RUN` child records or raw S3 evidence.
- `src/release_confidence_platform/aggregation/integrity.py`
  - Phase 4 validates `finalization.execution_count` equals `len(runs)` and `len(records)` before aggregation.
  - This gate was not deployed/executed in dev for this audit.

## Root Cause

### Confirmed Root Cause

The initial `RUN` metadata write path sanitizes primary-key and identifier fields before persistence. For run ID `48a87626-e2f9-4f81-82ff-2475004829ec`, the sanitizer matched the `2475004829` substring as phone-like PII and replaced it with `[REDACTED]`. This mutated the persisted DynamoDB `SK` and `run_id` to `48a87626-e2f9-4f81-82ff-[REDACTED]ec`.

Subsequent terminal metadata updates used the unsanitized run ID key, `...#RUN#48a87626-e2f9-4f81-82ff-2475004829ec`, which did not match the persisted sanitized key. DynamoDB returned `ConditionalCheckFailedException` for both the attempted `COMPLETED` and attempted `FAILED` terminal updates, leaving the only persisted run metadata item in `STARTED` forever.

Evidence directly proving this:

- S3 object key exists with unsanitized UUID: `.../48a87626-e2f9-4f81-82ff-2475004829ec/results.json`.
- DynamoDB `RUN` item exists only under sanitized key: `...#RUN#48a87626-e2f9-4f81-82ff-[REDACTED]ec`.
- CloudWatch logs show terminal update failures with `ConditionalCheckFailedException` immediately after `raw_result_write_completed`.
- Repository code sanitizes the full item on `put_started_once(...)` but computes terminal update keys from the unsanitized `event.run_id`.

### Confirmed Invariant-Enforcement Gap

Phase 3 finalization does not enforce the architectural invariant. It completes based only on `execution_counters.total_completed`, which is independently maintained and not reconciled with persisted `RUN` terminal states or raw S3 evidence.

Evidence:

- Finalization code reads `audit.execution_counters.total_completed` into `execution_count`.
- Finalization metadata persisted `execution_count=25` and lifecycle transitioned to `COMPLETED`.
- At the same time, DynamoDB had one unresolved `RUN` and 29 raw S3 objects.

### Confirmed Counter/Reconciliation Defect

The scheduled handler marks occurrences completed and increments `total_started`/`total_completed` after any normal orchestrator return, even when the orchestrator returns `status=FAILED` due to run metadata persistence failure.

Evidence:

- Orphan request logs `run_returning status=FAILED` at `14:38:00.765Z` and then `orchestrator_execution_completed` at `14:38:00.766Z`.
- Occurrence item for that failed run has `claim_status=completed`.
- Audit counters include that occurrence in `total_completed`.

## Contributing Factors

1. **Sanitization boundary is over-broad for persistence.** The shared sanitizer is appropriate for logs and sensitive raw values, but it is used on DynamoDB primary-key material and canonical identifiers.
2. **Run-record terminal update is not atomic with raw evidence write.** Raw S3 evidence can be written successfully while the terminal metadata update fails, producing dangling raw evidence with no completed run metadata link.
3. **Orchestrator failure is returned, not raised, to scheduler.** The scheduled handler treats the returned failure as a completed invocation and updates counters/occurrence state.
4. **Counters have ambiguous semantics.** `total_completed` currently counts completed scheduler occurrence handler paths, not terminal completed `RUN` records. Repeated schedule semantics further diverge: one repeated occurrence produced five completed run records.
5. **Finalization has no pre-completion reconciliation gate.** It does not query `RUN` children or verify absence of `STARTED`/unresolved states.
6. **Dev deployment lacks Phase 4.** The repository contains Phase 4 integrity logic, but the target dev stack has no aggregation Lambda/function env var/job records, so no post-finalization integrity gate ran.

## Technical Analysis

### Execution Counter Investigation

`execution_counters` are independently maintained on the audit metadata item by `ScheduledExecutionHandler`:

- `total_started = counters.get("total_started", 0) + 1`
- `total_completed = counters.get("total_completed", 0) + 1`
- `last_execution_at = utc_now_iso()`

This occurs after occurrence update on the handler's normal path. It is not derived from persisted `RUN` child records. It has no DynamoDB transaction boundary with the `RUN` terminal update. If the orchestrator returns a failure payload rather than raising, counters still increment.

For this audit:

| Source | Count | Meaning |
| --- | ---: | --- |
| Occurrence records | 25 | Completed scheduler occurrence claims. |
| `execution_counters.total_completed` | 25 | Independently maintained occurrence-path counter. |
| `finalization.execution_count` | 25 | Copied from `execution_counters.total_completed`. |
| Completed `RUN` records | 28 | Terminal run metadata with `status=COMPLETED` and raw S3 key. |
| Unresolved `RUN` records | 1 | Persisted `STARTED` item whose terminal update missed due to sanitized key mismatch. |
| S3 raw result objects | 29 | Raw evidence objects written, including orphan run. |

`total_completed` is therefore not a reliable source for finalization evidence integrity.

### Finalization Logic Review

Finalization currently decides successful closeout as follows:

1. Load canonical audit metadata.
2. If terminal, skip.
3. Read `execution_counters.total_completed`.
4. Transition current state to `FINALIZING`.
5. Persist finalization metadata with `execution_count` from counters.
6. If execution count is zero, fail.
7. Otherwise transition `FINALIZING -> COMPLETED`.

It does **not**:

- query `AUDIT#...#RUN#` child records,
- reject unresolved `STARTED` records,
- reconcile completed run count with raw S3 evidence count,
- verify every raw S3 result has a completed `RUN` metadata link,
- verify counters match persisted evidence.

### RUN Record Lifecycle

For the orphaned run:

1. EventBridge scheduled baseline occurrence invoked `scheduledExecution`.
2. Orchestrator generated run ID containing phone-like substring `2475004829`.
3. Duplicate preflight passed against the unsanitized S3 key and metadata key.
4. `put_started_once(sanitize(item))` persisted a **sanitized** primary key and `run_id`.
5. Endpoint execution completed successfully.
6. S3 raw result object was written under the **unsanitized** run ID.
7. `update_terminal(keys(...unsanitized run_id...))` failed because that key did not exist.
8. Failure-path terminal update also failed for the same reason.
9. Orchestrator returned `FAILED`.
10. Scheduled handler completed the occurrence and incremented counters anyway.

No evidence indicates Lambda timeout or process termination. The request completed normally in CloudWatch and explicitly logged the two conditional update failures.

### Evidence Integrity Validation

Repository Phase 4 code would perform these relevant checks if deployed:

- Audit lifecycle/finalization eligibility.
- Required `audit_execution_id` and `config_version`.
- `finalization.execution_count` integer `> 0`.
- `finalization.execution_count == len(completed_runs)`.
- `finalization.execution_count == len(raw_records)`.
- duplicate raw source reference detection.
- lineage completeness.

For this audit, using current persisted state:

- Expected finalization count: `25`.
- Completed run records considered by Phase 4 repository: `28`.
- Raw records would be loaded from those 28 completed runs only; the orphan raw S3 object is not reachable through a completed run metadata record.

Therefore, if the current repository Phase 4 gate were deployed and triggered, it should block before aggregate creation with `EXECUTION_COUNT_MISMATCH_COMPLETED_RUNS` or a related evidence-count mismatch. However, cloud evidence confirms Phase 4 did not run.

### Aggregation Investigation

Expected architecture says successful finalization should persist an aggregation job intent and asynchronously invoke aggregation.

Observed dev environment:

- `release-confidence-platform-dev-auditFinalization` has no `AGGREGATION_FUNCTION_NAME` environment variable.
- `release-confidence-platform-dev-auditAggregation` function is absent.
- No aggregation log group exists.
- No `AGGJOB` records exist for the audit.
- No `EXECUTION_ID` record exists for the audit.

Conclusion: no aggregation artifacts were observed because Phase 4 was not deployed/configured in the target dev stack at incident time, not because an aggregation job was invoked and blocked. This is an environment/deployment-state limitation relative to Phase 4 architecture, not the primary cause of the audit-completed-with-unresolved-run violation.

### Invariant Verification

The invariant does not appear to be enforced in the deployed Phase 3 finalization path. It is partially enforced in repository Phase 4 aggregation code as a fail-closed pre-aggregation check, but that is too late to prevent `COMPLETED` lifecycle state and was not deployed in dev.

Required enforcement point: before any lifecycle transition to `COMPLETED`, finalization must reconcile persisted evidence and fail/hold if unresolved runs remain. Phase 4 may also retain its fail-closed gate as a downstream defense.

### Consistency Matrix

| Evidence source | Observed value | Consistency assessment |
| --- | --- | --- |
| Audit lifecycle | `COMPLETED` | Inconsistent with unresolved run. |
| Finalization metadata | `execution_count=25`, `zero_execution=false` | Consistent with counters only; inconsistent with run/S3 evidence. |
| Audit counters | `total_started=25`, `total_completed=25` | Counts occurrence handler completions, not terminal run records. |
| Occurrence records | 25 completed | Consistent with counters; one occurrence completed despite run failure. |
| RUN records | 28 completed, 1 started | Inconsistent with lifecycle `COMPLETED`; evidence unresolved. |
| S3 raw result objects | 29 objects | Inconsistent with completed run metadata count; orphan raw object exists. |
| Phase 4 job intent | 0 records | Expected in approved architecture, absent in deployed dev stack. |
| Phase 4 aggregate set | none | Expected absence in dev because aggregation not deployed/triggered; if deployed, should block due count mismatch. |

## Business Impact

- **Evidence integrity risk:** audit metadata reports successful completion even though persisted execution evidence is unresolved and raw evidence is not fully linked.
- **Misleading release-confidence signal:** downstream consumers may interpret `COMPLETED` plus `execution_count=25` as a clean audit when one run has no terminal metadata and one raw result is orphaned.
- **Aggregation/reporting risk:** if downstream phases rely only on lifecycle/finalization metadata, they may produce incomplete or invalid analytics. A deployed Phase 4 gate should block, but the lifecycle state itself is already misleading.
- **Customer trust risk:** customers/operators could see a terminal success despite internal evidence inconsistency.
- **Operational recovery risk:** the raw evidence object exists but is disconnected from canonical run metadata by a mutated key; automated reconciliation must handle this carefully to avoid double counting or silent data loss.

Severity: **High**. The incident does not show data deletion or security exposure, but it violates a core audit integrity invariant and can produce misleading completed audit metadata.

## Architectural Impact

This incident exposes a shared contract problem across phases:

1. **Execution engine/persistence contract:** canonical identifiers and primary keys must never be passed through PII redaction that changes their values.
2. **Phase 3 lifecycle contract:** lifecycle completion must be based on reconciled persisted evidence, not independent counters.
3. **Phase 4 aggregation contract:** aggregation must continue to fail closed, but Phase 4 cannot be the only integrity boundary because lifecycle `COMPLETED` is already externally meaningful.
4. **Counter semantics contract:** audit counters need explicit semantics (`occurrence_completed`, `run_completed`, `run_failed`, `run_unresolved`) or must be derived/reconciled from source-of-truth records.

## Invariant Violations

Primary invariant violated:

> An audit must not transition to `COMPLETED` while any persisted `RUN` record remains unresolved.

Observed violation:

- Audit transitioned to `COMPLETED` at `2026-06-09T15:22:57.419283Z`.
- Persisted `RUN` item remained `STARTED` with null terminal fields.
- Finalization did not detect this because it did not query/reconcile run records.

Secondary invariant/contract violations:

- Canonical DynamoDB key material was mutated by sanitization.
- Raw S3 evidence was written but not linked by terminal run metadata.
- Occurrence and counter state reported completion after the orchestrator returned failure.
- Approved Phase 4 lifecycle-triggered aggregation artifacts were absent in deployed dev stack.

## Corrective Actions

Recommendations only; no remediation was performed in this investigation.

1. **Execution engine / persistence owner**
   - Stop applying redaction-oriented `sanitize(...)` to DynamoDB primary-key material and canonical identifiers.
   - Introduce persistence-safe validation/normalization that preserves `PK`, `SK`, `client_id`, `audit_id`, `run_id`, and S3 keys exactly after identifier validation.
   - Add regression coverage for UUIDs containing phone-like 10-digit substrings, asserting the persisted `SK` and `run_id` remain unchanged.

2. **Execution engine / persistence owner**
   - Treat terminal metadata update failure after raw S3 write as a hard propagated failure to the scheduler layer, or persist an explicit recoverable terminal-update-failed state that finalization can detect.
   - Ensure failure-path terminal updates cannot silently leave `STARTED` records unresolved.

3. **Phase 3 lifecycle/finalization owner**
   - Add a finalization reconciliation gate before `FINALIZING -> COMPLETED`.
   - Query `RUN` records for the audit and reject/hold/fail finalization if any run is not terminal (`COMPLETED`/`FAILED`) or has null terminal fields inconsistent with status.
   - Reconcile counters against run records and raw S3 evidence according to approved semantics before recording `finalization.execution_count`.

4. **Phase 3 scheduler/orchestration owner**
   - Update scheduled handler semantics so occurrence completion and audit counters reflect the orchestrator result and/or verified terminal run metadata.
   - Do not increment `total_completed` when `result.status != COMPLETED`.
   - Record failed/skipped counts separately with controlled reason codes.

5. **Phase 4 / platform owner**
   - Ensure dev/staging deployments intended for Phase 4 validation actually deploy the aggregation Lambda, finalization env var, dedicated roles, and aggregation job-intent path.
   - Retain Phase 4 fail-closed integrity validation as downstream defense.

6. **Data recovery owner**
   - Separately design a read-only-first reconciliation/remediation plan for the specific orphaned run and raw S3 object. Do not mutate evidence manually without approved recovery workflow.

## Preventive Actions

- Add invariant tests: finalization must not complete when any `RUN` child is `STARTED`, lacks `completed_at`, lacks `raw_result_s3_key` when completed, or has terminal-update failure metadata.
- Add property/regression tests for generated UUIDs that contain PII-looking substrings; persistence keys must remain stable.
- Add integration tests for the failure mode: S3 raw write succeeds, terminal DDB update fails, scheduler must not increment completion counters and finalization must not complete.
- Add an operational metric/alarm for `terminal_metadata_update_failed` and for audits where `lifecycle_state=COMPLETED` but unresolved `RUN` records exist.
- Add a periodic read-only reconciliation report for dev/staging that compares lifecycle, counters, run records, occurrence records, S3 raw objects, and aggregation job state.
- Clarify and document counter semantics: occurrence counters vs run counters vs raw-result counts.
- Add deployment validation for Phase 4 environments: aggregation Lambda exists, finalization has `AGGREGATION_FUNCTION_NAME`, and a post-finalization `AGGJOB` intent is created.

## Recommended SDLC Routing

- **Primary owner:** execution engine / persistence backend.
  - Reason: confirmed identifier mutation occurs in `DynamoDBMetadataClient.put_started_once(...)` via `sanitize(item)` and directly causes the orphaned run.
- **Secondary owner:** Phase 3 lifecycle/finalization backend.
  - Reason: finalization completed without persisted-run reconciliation.
- **Secondary owner:** scheduler/orchestration backend.
  - Reason: occurrence/counter completion semantics ignored returned orchestrator `FAILED` status.
- **Phase 4 owner:** not primary for this incident, but should validate fail-closed behavior after deployment/configuration is present.
- **Release/infrastructure owner:** validate whether `dev` should contain Phase 4 aggregation resources for the current validation phase; cloud evidence shows it did not at incident time.

Suggested validation after fixes:

1. Unit test sanitizer/persistence boundary with run ID `48a87626-e2f9-4f81-82ff-2475004829ec` and assert DDB `SK` remains unsanitized.
2. Integration test simulated terminal update failure after raw S3 write; assert scheduled handler does not increment `total_completed` and occurrence is not marked successfully completed.
3. Integration test finalization with one unresolved `RUN`; assert audit does not transition to `COMPLETED`.
4. End-to-end dev validation: run a scheduled audit, verify counts reconcile: occurrence records, terminal run records, raw S3 objects, finalization metadata, and aggregation job/integrity outcome.
5. Limited regression scan after deployment: no `COMPLETED` audits with unresolved `RUN` children in the validation window.

## Open Questions / Missing Evidence

- CloudWatch logs for finalization contained only START/END/REPORT because the deployed finalization Lambda predates structured finalization logging. DynamoDB lifecycle timestamps provide the finalization state transitions.
- EventBridge Scheduler invocation history is not directly available from the queried evidence. Lambda logs and persisted occurrence/finalization records were used as invocation evidence.
- No CloudTrail data-event export was provided for Lambda invoke or DynamoDB write calls. Existing CloudWatch and persisted records were sufficient to confirm the root cause.
- The exact deployment/version boundary between repository Phase 4 code and dev cloud stack should be clarified by release/infrastructure; dev does not currently match the approved Phase 4 architecture.
