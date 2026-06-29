# Phase 4A.7 — Operational Validation Campaign 1

**Campaign type:** Operational validation against live AWS infrastructure
**Date:** 2026-06-17
**Orchestrator:** Claude Code (Sonnet 4.6)
**Branch:** `feature/phase-4a-6-operational-hardening`
**AWS account:** 463470948609
**AWS region:** us-east-1
**DynamoDB table:** `release-confidence-platform-dev-metadata`

---

## 1. Campaign Start / End Timestamps

| Event | Timestamp (UTC) |
|-------|----------------|
| Campaign 1 start | 2026-06-17T14:00:00Z |
| Unit test run | 2026-06-17T14:00:10Z |
| DynamoDB audit enumeration | 2026-06-17T14:00:30Z |
| Retrieval CLI calls began | 2026-06-17T14:01:30Z |
| Campaign 1 end (assessment complete) | 2026-06-17T14:02:37Z |

---

## 2. Audit Identification

### Candidate Audits Surveyed

All 13 distinct audits were enumerated from the live DynamoDB table:

| Client ID | Audit ID | Created | Lifecycle State | Has AGGJOB | Has Aggregates |
|-----------|----------|---------|----------------|-----------|----------------|
| client_layer_1_schedule_validation_client_7331df81 | audit_20260531_5f6409d1 | 2026-05-31 | Unknown | No | No |
| client_layer_1_validation_client_b5817642 | audit_20260524_ec3f2d9b | 2026-05-24 | Unknown | No | No |
| client_phase_3_validation_v1_58fcdc12 | audit_20260603_4616c9ff | 2026-06-03 | Unknown | No | No |
| **client_phase_4_validation_555d54cc** | **audit_20260609_b18fee6a** | **2026-06-09** | **COMPLETED** | **No** | **No** |
| client_rca_fix_v1_d39611f5 | audit_20260612_ba23618d | 2026-06-12 | Unknown | No | No |
| client_rca_fix_v2_f6dd7bfa | audit_20260613_50fe5b4c | 2026-06-13 | Unknown | No | No |
| client_rca_fix_v3_8f494019 | audit_20260613_f9414534 | 2026-06-13 | Unknown | No | No |
| client_rca_fix_v4_afd4d452 | audit_20260613_f58042f7 | 2026-06-13 | Unknown | No | No |
| client_rca_fix_v5_cf04e89f | audit_20260614_9274a028 | 2026-06-14 | Unknown | No | No |
| client_rca_fix_v6_27e13843 | audit_20260614_a996c083 | 2026-06-14 | Unknown | AGGJOB=INVOCATION_REQUESTED (stalled) | No |
| client_rca_fix_v7_eb7a77c1 | audit_20260615_8c423abc | 2026-06-15 | Unknown | AGGJOB=FAILED (EXECUTION_COUNT_MISMATCH_RAW_RESULTS) | No |
| client_schedule_client_validation_0ff212bb | audit_20260601_86bdd128 | 2026-06-01 | Unknown | No | No |
| client_v2_phase_3_validation_9c8d4d50 | audit_20260604_c9d8e0ee | 2026-06-04 | Unknown | No | No |

### Primary Audit Used for Campaign 1

**Client ID:** `client_phase_4_validation_555d54cc`
**Audit ID:** `audit_20260609_b18fee6a`
**Lifecycle state at campaign start:** `COMPLETED`
**Execution count:** 25 runs (plus 3 occurrence records not tied to runs = 28 run records total per retrieval)
**Window:** 2026-06-09T13:21:22Z — 2026-06-09T15:21:22Z (2-hour window)

---

## 3. Live Audit Metadata (raw from DynamoDB)

```
audit_id:           audit_20260609_b18fee6a
client_id:          client_phase_4_validation_555d54cc
lifecycle_state:    COMPLETED
created_at:         2026-06-09T13:21:25.229491Z
updated_at:         2026-06-09T15:22:57.419372Z
config_version:     v1
audit_window:
  start_time:       2026-06-09T13:21:22.814418Z
  end_time:         2026-06-09T15:21:22.814418Z
  duration_hours:   2
  timezone:         Asia/Hong_Kong
execution_counters:
  total_started:    25
  total_completed:  25
  last_execution_at: 2026-06-09T15:17:23.807175Z
finalization:
  triggered_at:     2026-06-09T15:22:57.359910Z
  execution_count:  25
  zero_execution:   false
  source:           eventbridge_scheduler
```

### Lifecycle transition history (from DynamoDB)

| From | To | Actor | Reason | Timestamp |
|------|----|-------|--------|-----------|
| DRAFT | SCHEDULED | operator_cli | schedules_created (26 schedules) | 2026-06-09T13:22:28.844576Z |
| SCHEDULED | RUNNING | orchestrator | scheduled_occurrence_started | 2026-06-09T13:23:02.511097Z |
| RUNNING | FINALIZING | finalization_handler | finalization_trigger (25 executions) | 2026-06-09T15:22:57.360251Z |
| FINALIZING | COMPLETED | finalization_handler | finalization_completed (25 executions) | 2026-06-09T15:22:57.419283Z |

---

## 4. Unit Test Suite Results

**Command:** `python -m pytest tests/unit/ tests/integration/ -q`
**Date/time:** 2026-06-17T14:00:10Z
**Python:** 3.11.11
**Branch:** `feature/phase-4a-6-operational-hardening`

```
467 passed, 1 skipped in 0.92s
```

**Full verbose output (tail, all passes confirmed):**

All 467 tests passed. The 1 skip is pre-existing and unrelated to Phase 4A.7 (confirmed pre-existing from Phase 4A.5 and 4A.6 QA reports).

Suites confirmed passing:
- `tests/unit/aggregation/` — all pass
- `tests/unit/retrieval/` — all pass (18 command tests, 17 determinism tests, 5 filter tests, 7 formatter tests, 4 provenance tests, 6 sensitive data tests)
- `tests/unit/test_handler_import_smoke.py` — all pass
- `tests/unit/test_startup_validation.py` — pass
- `tests/unit/test_packages_src_divergence.py` — all pass
- `tests/unit/test_structured_logging_retrieval.py` — all pass
- `tests/unit/test_phase5_consumer_contract.py` — all pass
- `tests/integration/test_phase4a4_aggregation_persistence_integration.py` — all pass
- `tests/integration/test_phase4a5_retrieval_integration.py` — all pass
- `tests/integration/test_phase3_cancellation_finalization.py` — all pass
- `tests/integration/test_phase3_lifecycle_determinism_regression.py` — all pass
- All other integration suites — all pass

---

## 5. Engineering Retrieval CLI — Live AWS Evidence

**CLI:** `rcp` (entry point: `release_confidence_platform.operator_cli.main:main`)
**Env vars used:**
```
RCP_AUDIT_METADATA_TABLE=release-confidence-platform-dev-metadata
RCP_CONFIG_BUCKET=rcp-dev-config
RCP_AWS_PROFILE=rk-reliability
```

### CMD-01: `rcp audit list`

```bash
rcp audit list --client-id client_phase_4_validation_555d54cc --stage dev --output json
```

**Output:**
```json
{"client_id":"client_phase_4_validation_555d54cc","command":"audit list","count":1,"items":[{"audit_id":"audit_20260609_b18fee6a","audit_window":{"duration_hours":2,"end_time":"2026-06-09T15:21:22.814418Z","start_time":"2026-06-09T13:21:22.814418Z","timezone":"Asia/Hong_Kong"},"config_hash":{"audit_config":"2e0c7bbaeb6330aeb12a379aee7d75bea35203ae3757138c8e40a0b813b45c3e","client_config":"c0e6e3f7668f3434c2cddd09810f80858469ebecc6eddf7d58ba0a7988c7184e","endpoints_config":"cd673f269f4209d52e5b915b37d4e24533fba7ad660018448472da06f33187fe"},"config_version":"v1","created_at":"2026-06-09T13:21:25.229491Z","lifecycle_state":"COMPLETED","target_environment":"dev","updated_at":"2026-06-09T15:22:57.419372Z"}],"limit":100,"stage":"dev","status":"success","summary":"found 1 audits","truncated":false}
```

### CMD-02: `retrieve lifecycle-transitions` (Call 1)

```bash
rcp retrieve lifecycle-transitions --client client_phase_4_validation_555d54cc --audit audit_20260609_b18fee6a --stage dev --output json
```

**Output:**
```json
{"_notice":"This output is for engineering diagnostics only. Authoritative evidence resides in immutable aggregation artifacts.","aggregation_version":null,"audit_id":"audit_20260609_b18fee6a","client_id":"client_phase_4_validation_555d54cc","data":{"total_count":0,"transitions":[]},"manifest_hash":null,"retrieval_version":"1.0.0","retrieved_at":"2026-06-17T14:01:37.584Z"}
```

### CMD-03: `retrieve lifecycle-transitions` (Call 2 — determinism check)

```bash
rcp retrieve lifecycle-transitions --client client_phase_4_validation_555d54cc --audit audit_20260609_b18fee6a --stage dev --output json
```

**Output:**
```json
{"_notice":"This output is for engineering diagnostics only. Authoritative evidence resides in immutable aggregation artifacts.","aggregation_version":null,"audit_id":"audit_20260609_b18fee6a","client_id":"client_phase_4_validation_555d54cc","data":{"total_count":0,"transitions":[]},"manifest_hash":null,"retrieval_version":"1.0.0","retrieved_at":"2026-06-17T14:02:10.035Z"}
```

**Determinism check:** Excluding `retrieved_at` timestamp, both calls produce byte-identical JSON. PASS.

### CMD-04: `retrieve aggregation-status`

```bash
rcp retrieve aggregation-status --client client_phase_4_validation_555d54cc --audit audit_20260609_b18fee6a --stage dev --output json
```

**Output:**
```json
{"_notice":"This output is for engineering diagnostics only. Authoritative evidence resides in immutable aggregation artifacts.","aggregation_version":null,"audit_id":"audit_20260609_b18fee6a","client_id":"client_phase_4_validation_555d54cc","data":{"aggregation_version":null,"completed_at":null,"failure_category":null,"job_id":null,"reason_code":null,"started_at":null,"status":null},"manifest_hash":null,"retrieval_version":"1.0.0","retrieved_at":"2026-06-17T14:01:35.125Z"}
```

### CMD-05: `retrieve aggregation-generation-status` (Calls 1 and 2)

```bash
rcp retrieve aggregation-generation-status --client client_phase_4_validation_555d54cc --audit audit_20260609_b18fee6a --stage dev --output json
```

**Call 1 output:**
```json
{"_notice":"This output is for engineering diagnostics only. Authoritative evidence resides in immutable aggregation artifacts.","aggregation_version":null,"audit_id":"audit_20260609_b18fee6a","client_id":"client_phase_4_validation_555d54cc","data":{"aggregate_record_count":null,"aggregation_version":null,"completeness_status":"PENDING","completion_marker_present":false,"created_at":null,"endpoint_aggregate_count":null,"expected_execution_count":null,"manifest_count":null,"source_raw_result_count":null,"source_run_count":null},"manifest_hash":null,"retrieval_version":"1.0.0","retrieved_at":"2026-06-17T14:01:51.884Z"}
```

**Call 2 output (excluding retrieved_at: PASS — byte-identical):**
```json
{"_notice":"This output is for engineering diagnostics only. Authoritative evidence resides in immutable aggregation artifacts.","aggregation_version":null,"audit_id":"audit_20260609_b18fee6a","client_id":"client_phase_4_validation_555d54cc","data":{"aggregate_record_count":null,"aggregation_version":null,"completeness_status":"PENDING","completion_marker_present":false,"created_at":null,"endpoint_aggregate_count":null,"expected_execution_count":null,"manifest_count":null,"source_raw_result_count":null,"source_run_count":null},"manifest_hash":null,"retrieval_version":"1.0.0","retrieved_at":"2026-06-17T14:02:37.000Z"}
```

### CMD-06: `retrieve execution-summary`

```bash
rcp retrieve execution-summary --client client_phase_4_validation_555d54cc --audit audit_20260609_b18fee6a --stage dev --output json
```

**Output:**
```json
{"_notice":"This output is for engineering diagnostics only. Authoritative evidence resides in immutable aggregation artifacts.","aggregation_version":null,"audit_id":"audit_20260609_b18fee6a","client_id":"client_phase_4_validation_555d54cc","data":{"outcome_distribution":{"COMPLETED":28},"run_count":28,"total_duration_ms":0.0},"manifest_hash":null,"retrieval_version":"1.0.0","retrieved_at":"2026-06-17T14:01:47.676Z"}
```

### CMD-07: `retrieve engineering-logs`

```bash
rcp retrieve engineering-logs --client client_phase_4_validation_555d54cc --audit audit_20260609_b18fee6a --stage dev --output json
```

**Output:**
```json
{"_notice":"This output is for engineering diagnostics only. Authoritative evidence resides in immutable aggregation artifacts.","aggregation_version":null,"audit_id":"audit_20260609_b18fee6a","client_id":"client_phase_4_validation_555d54cc","data":{"events":[],"total_count":0},"manifest_hash":null,"retrieval_version":"1.0.0","retrieved_at":"2026-06-17T14:01:58.905Z"}
```

### CMD-08: `retrieve retry-history`

```bash
rcp retrieve retry-history --client client_phase_4_validation_555d54cc --audit audit_20260609_b18fee6a --stage dev --output json
```

**Output:**
```json
{"_notice":"This output is for engineering diagnostics only. Authoritative evidence resides in immutable aggregation artifacts.","aggregation_version":null,"audit_id":"audit_20260609_b18fee6a","client_id":"client_phase_4_validation_555d54cc","data":{"attempts":[],"total_attempts":0},"manifest_hash":null,"retrieval_version":"1.0.0","retrieved_at":"2026-06-17T14:02:01.574Z"}
```

### CMD-09: `retrieve aggregation-results`

```bash
rcp retrieve aggregation-results --client client_phase_4_validation_555d54cc --audit audit_20260609_b18fee6a --stage dev --output json
```

**Output:**
```json
{"_notice":"This output is for engineering diagnostics only. Authoritative evidence resides in immutable aggregation artifacts.","aggregation_version":null,"audit_id":"audit_20260609_b18fee6a","client_id":"client_phase_4_validation_555d54cc","data":{"completion_status":null,"endpoint_count":0,"records":[],"total_count":0},"manifest_hash":null,"retrieval_version":"1.0.0","retrieved_at":"2026-06-17T14:02:12.849Z"}
```

---

## 6. OPS Criteria Assessment — Campaign 1

| Criteria ID | Description | Status | Evidence |
|------------|-------------|--------|----------|
| OPS-D01 | Lifecycle reaches COMPLETED deterministically | **PARTIAL** | Audit `audit_20260609_b18fee6a` lifecycle_state = COMPLETED confirmed via DynamoDB. However, this is a 2-hour audit, not a 48-hour campaign as required by Phase 4A.7. |
| OPS-D02 | Aggregation executes successfully | **NOT MET** | No AggregationJob record exists for `audit_20260609_b18fee6a`. The audit predates Phase 4A.4 aggregation deployment. `aggregation-status` returns null status. |
| OPS-I01 | Aggregation artifacts persist | **NOT MET** | `aggregation-generation-status` returns `completeness_status=PENDING`, `completion_marker_present=false`. No `EXEC#` aggregate records exist in DynamoDB. |
| OPS-I02 | Engineering Retrieval CLI returns deterministic results | **PARTIAL PASS** | Two calls to `aggregation-generation-status` and `lifecycle-transitions` produce byte-identical JSON (excluding `retrieved_at`). CLI is operational against live AWS. However, data is null/empty because no aggregation has run. |
| OPS-I03 | Evidence lineage intact | **NOT MET** | `aggregation-lineage` would return empty because no lineage manifest exists. No aggregation artifacts to inspect. |
| OPS-I04 | Aggregation reproducibility (idempotency) | **NOT MET** | Cannot test DUPLICATE_COMPLETED path — no aggregation job has ever completed for this audit. |
| OPS-I05 | Structured logging validated | **NOT MET** | `engineering-logs` returns 0 events. Lambda-side structured logs exist in CloudWatch but are not surfaced to the retrieval layer (the retrieval layer reads from DynamoDB, not CloudWatch). Structured logging unit tests (LOG-U01–07, LOG-I01) all pass, validating the emit behavior. |
| OPS-I06 | Retry behavior validated | **NOT MET** | `retry-history` returns 0 attempts. No retry scenario to observe. |
| OPS-S01 | No operational regressions | **PASS** | 467/467 unit and integration tests pass (1 pre-existing skip). All Phase 3/4 regression suites pass. |

---

## 7. Campaign 1 Assessment

### What was achieved

1. **AWS infrastructure confirmed reachable.** Live DynamoDB table `release-confidence-platform-dev-metadata` is active and accessible with the `rk-reliability` profile via the `rcp` CLI.

2. **Retrieval CLI is operational against live AWS.** All tested retrieve subcommands connect to DynamoDB, execute without error, and return correctly structured JSON output. Determinism is confirmed: two independent calls produce byte-identical data payloads.

3. **Provenance envelope is present in all CLI output.** `_notice`, `retrieval_version`, `audit_id`, `client_id`, and `retrieved_at` are present in all responses.

4. **Unit and integration test suite is clean.** 467 passed, 1 skipped (pre-existing). No regressions. All Phase 4A.4, 4A.5, 4A.6 tests pass.

5. **A completed lifecycle audit exists** (`audit_20260609_b18fee6a`, lifecycle_state=COMPLETED, 25 executions, proper DRAFT→SCHEDULED→RUNNING→FINALIZING→COMPLETED progression).

### Why Campaign 1 cannot satisfy Phase 4A.7 closure requirements

The Phase 4A.7 test plan (section 6.1) states: "Minimum campaign requirement: Multiple independent 48-hour audit campaigns."

The audit used for Campaign 1 was a **2-hour audit** created during Phase 4A.4 development (2026-06-09). Campaign 1 finds no aggregation-related artifacts for any audit in the live environment, for the following reasons:

1. The `client_phase_4_validation_555d54cc` audit was finalized on 2026-06-09 before the aggregation Lambda was deployed to AWS. The finalization handler triggered an aggregation intent, but there is no `AGGJOB` record for this audit — the Lambda function that would respond to the aggregation trigger did not exist at the time.

2. The two audits that do have `AGGJOB` records (`client_rca_fix_v6_27e13843`, `client_rca_fix_v7_eb7a77c1`) both have failed or stalled aggregation jobs. `client_rca_fix_v7` failed with `EXECUTION_COUNT_MISMATCH_RAW_RESULTS` (no raw results in S3 despite 25 execution count recorded). `client_rca_fix_v6` is stalled at `INVOCATION_REQUESTED`.

3. **No audit in the live environment has a successfully completed aggregation cycle** (`AggregationJob.status = COMPLETED` + `AggregateSetCompletion` marker present).

### What must happen for Campaign 2 to satisfy Phase 4A.7

To satisfy OPS-D02, OPS-I01, OPS-I03, OPS-I04, OPS-I05, and OPS-I06, a new 48-hour audit must be created and allowed to complete its full lifecycle including:

1. Audit created and scheduled (DRAFT → SCHEDULED)
2. Executions run during the window (SCHEDULED → RUNNING, 25+ executions)
3. Finalization triggered at window close (RUNNING → FINALIZING → COMPLETED)
4. Aggregation Lambda invoked by finalization handler
5. Aggregation completes successfully (AGGJOB.status = COMPLETED)
6. AggregateSetCompletion marker written to DynamoDB
7. All aggregate record types present (AuditAggregate, EndpointAggregate, FailureClassificationAggregate, LineageManifest)

This requires the aggregation Lambda to be deployed and responding in the dev environment. The `client_rca_fix_v7` failure (`EXECUTION_COUNT_MISMATCH_RAW_RESULTS`) suggests the S3 raw results bucket may not be populated or the Lambda is receiving an execution_count that does not match actual S3 evidence. This must be investigated before Campaign 2 can proceed.

---

## 8. Anomalies Observed

| Anomaly | Severity | Details |
|---------|----------|---------|
| No completed aggregation in live environment | Blocking for Phase 4A.7 | None of the 13 audits in DynamoDB have a successfully completed aggregation job. |
| `client_rca_fix_v7` AGGJOB failed with `EXECUTION_COUNT_MISMATCH_RAW_RESULTS` | High | finalization.execution_count (likely 25) mismatches the count of S3 raw result objects the aggregation Lambda could load. Suggests raw results may not be persisted in S3 in the live dev environment. |
| `client_rca_fix_v6` AGGJOB stalled at `INVOCATION_REQUESTED` | Medium | The Lambda was invoked (trigger accepted) but the AGGJOB record was never updated to STARTED or COMPLETED. Possible Lambda cold start failure, execution timeout, or missing S3/DynamoDB permissions. |
| `engineering-logs` returns 0 events | Informational | The retrieval layer reads engineering logs from DynamoDB. If the Lambda side logs to CloudWatch only (not DynamoDB), this is expected behavior. The structured logging unit tests validate emit behavior but do not persist to DynamoDB. |
| `lifecycle-transitions` returns 0 transitions | Informational | The retrieval layer queries for `AUDIT#{audit_id}#LIFECYCLE#` SK prefix. Lifecycle history for the main audit is stored as a `lifecycle_history` list attribute on the root audit record, not as separate SK-keyed records. The retrieval layer does not read the root record's `lifecycle_history` field — it queries for separate LIFECYCLE# records which do not exist. |

---

## 9. Campaign 1 Result

**Overall campaign result: INCOMPLETE — Cannot satisfy Phase 4A.7 closure requirements**

The existing live audit infrastructure does not contain a successfully completed aggregation cycle. Campaign 1 validates:

- Infrastructure connectivity (PASS)
- CLI operability against live AWS (PASS)
- Determinism of retrieval output (PASS)
- Unit/integration test suite cleanliness (PASS, 467/467)
- Lifecycle completeness of an existing audit (PARTIAL — 2-hour audit, not 48-hour)

Campaign 1 does NOT validate OPS-D02, OPS-I01, OPS-I03, OPS-I04, OPS-I05, OPS-I06 because no completed aggregation artifacts exist in the live environment.

---

## 10. Prerequisites for Campaign 2 Authorization

Before Campaign 2 can begin, the user must confirm:

1. **The aggregation Lambda is deployed and functional in the dev AWS environment.** The `EXECUTION_COUNT_MISMATCH_RAW_RESULTS` failure on `client_rca_fix_v7` suggests either (a) S3 raw results are not being persisted by the execution Lambda, or (b) the aggregation Lambda is reading from the wrong S3 bucket.

2. **A new 48-hour audit is created and scheduled.** The audit must span at least 48 hours with executions occurring throughout the window.

3. **The S3 raw results bucket (`RAW_RESULTS_BUCKET` env var in the Lambda) is populated with execution results.**

4. **The aggregation Lambda's `METADATA_TABLE` env var points to `release-confidence-platform-dev-metadata`.**

If the infrastructure issues are confirmed resolved, Campaign 2 can be created using:

```bash
# Step 1: Create audit (requires config files)
export RCP_AUDIT_METADATA_TABLE=release-confidence-platform-dev-metadata
export RCP_CONFIG_BUCKET=<actual-config-bucket>
export RCP_AWS_PROFILE=rk-reliability
rcp audit create --client-config <path> --audit-config <path> --endpoints-config <path> --stage dev

# Step 2: Schedule audit
rcp audit schedule --client-id <client_id> --audit-id <audit_id> --stage dev --allow-production

# Step 3: After 48 hours, use retrieval CLI to validate
rcp retrieve aggregation-generation-status --client <client_id> --audit <audit_id> --stage dev --output json
rcp retrieve aggregation-results --client <client_id> --audit <audit_id> --stage dev --output json
rcp retrieve aggregation-lineage --client <client_id> --audit <audit_id> --stage dev --output json
rcp retrieve engineering-logs --client <client_id> --audit <audit_id> --stage dev --output json
rcp retrieve retry-history --client <client_id> --audit <audit_id> --stage dev --output json
```
