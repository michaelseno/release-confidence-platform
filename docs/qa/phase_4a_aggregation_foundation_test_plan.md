# Test Plan

## 1. Overview

This test plan covers QA validation for Phase 4A: Deterministic Aggregation Foundation and Engineering Retrieval Layer.

Phase 4A validation is divided into five areas:

1. **Phase 4A.4 — Aggregation Persistence Validation**
2. **Phase 4A.5 — Engineering Retrieval CLI Validation**
3. **Phase 4A.5 — Structured Logging Validation**
4. **Phase 4A.6 — Operational Hardening Validation**
5. **Phase 4A.7 — Operational Validation Campaign (48-Hour Audits)**

Each area has its own acceptance criteria. Phase 4A is not complete until all areas pass and HITL approval is granted for Phase 4A.7.

## 2. Phase 4A.4 — Aggregation Persistence Validation

### 2.1 Scope

Confirm Phase 4 aggregation persistence is production-ready. Validate idempotency, immutability, completion marker atomicity, and retry safety.

### 2.2 Unit Tests

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| AGG-P1 | Aggregation write produces all required record types | `AuditAggregate`, `EndpointAggregate`, `FailureClassificationAggregate`, `LineageManifest` (audit + endpoint), and `AggregateSetCompletion` marker all present after one successful run |
| AGG-P2 | Duplicate trigger produces DUPLICATE_COMPLETED | Second invocation with same `aggregation_job_id` returns `DUPLICATE_COMPLETED` and creates no new aggregate records |
| AGG-P3 | Second invocation with new job id for same aggregate set produces DUPLICATE_COMPLETED | No new aggregate records created; existing set is complete |
| AGG-P4 | Conditional write prevents overwrite | Attempting to write an existing aggregate record with `attribute_not_exists` condition fails without corruption |
| AGG-P5 | Retry after pre-write failure produces exactly one aggregate set | Job fails before write; retry completes; exactly one complete aggregate set exists |
| AGG-P6 | AggregateSetCompletion marker is not written for partial sets | Simulated mid-write failure leaves no completion marker |
| AGG-P7 | Integrity gate blocks write on count mismatch | `finalization.execution_count` mismatch with loaded evidence count produces `FAILED` job with `EVIDENCE_PRODUCING` category and no aggregate records |
| AGG-P8 | Missing audit_execution_id blocks aggregation | Job fails closed with `MISSING_AUDIT_EXECUTION_ID` reason before any aggregate creation |
| AGG-P9 | Missing config_version blocks aggregation | Job fails closed with `MISSING_CONFIG_VERSION` reason before any aggregate creation |

### 2.3 Integration Tests

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| AGG-I1 | End-to-end aggregation with real DynamoDB fixtures | Complete aggregate set written; all record types present; completion marker exists |
| AGG-I2 | End-to-end idempotency | Running aggregation twice for same audit produces one complete aggregate set |

## 3. Phase 4A.5 — Engineering Retrieval CLI Validation

### 3.1 Scope

Validate all required retrieval commands for correctness, output format, filtering, and sensitive data exclusion.

### 3.2 Unit Tests — Command Correctness

| Test ID | Command | Pass Criteria |
| --- | --- | --- |
| RET-U01 | `retrieve aggregation-results` | Returns all aggregate record types for a completed aggregate set |
| RET-U02 | `retrieve aggregation-metadata` | Returns job status, failure_category, reason_code, source counts, timestamps |
| RET-U03 | `retrieve aggregation-lineage` | Returns `lineage_manifest_ref`, `source_ref_count`, `manifest_hash` from manifest records |
| RET-U04 | `retrieve aggregation-status` | Returns current aggregation job status and reason code |
| RET-U05 | `retrieve orchestration-timeline` | Returns events ordered by timestamp covering job claim through completion |
| RET-U06 | `retrieve lifecycle-transitions` | Returns ordered state transitions with from/to state, actor, reason, timestamp |
| RET-U07 | `retrieve execution-summary` | Returns run count, total execution duration, outcome distribution |
| RET-U08 | `retrieve audit-event-timeline` | Returns all audit-scoped events in timestamp order |
| RET-U09 | `retrieve engineering-logs` | Returns structured log events for the audit; no raw evidence content |
| RET-U10 | `retrieve retry-history` | Returns all aggregation job attempts with status and timestamps |
| RET-U11 | `retrieve aggregation-generation-status` | Returns completion marker fields if set exists; PENDING if not yet completed |
| RET-U12 | `retrieve aggregation-version` | Returns `aggregation_version` from completion marker or latest aggregate |
| RET-U13 | `retrieve evidence-references` | Returns source_raw_result_refs from lineage manifest; bounded count |
| RET-U14 | `retrieve failure-summaries` | Returns classification_counts by approved failure type labels |
| RET-U15 | `retrieve processing-timeline` | Returns per-stage timestamps from job metadata |

### 3.3 Unit Tests — Output Format

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| RET-F01 | `--output json` produces well-formed JSON | `json.loads()` succeeds; all required fields present |
| RET-F02 | `--output human` produces readable formatted output | Output is non-empty; key labels match expected field names |
| RET-F03 | JSON output field ordering is deterministic | Two calls to same command produce byte-identical JSON |
| RET-F04 | Default output format is human-readable | Command without `--output` flag defaults to human format |

### 3.4 Unit Tests — Filtering

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| RET-FL01 | `--client` filter restricts to specified client | Records from other clients not returned |
| RET-FL02 | `--audit` filter restricts to specified audit | Records from other audits not returned |
| RET-FL03 | `--endpoint` filter restricts endpoint aggregate results | Only the specified endpoint's aggregate returned |
| RET-FL04 | Unknown client ID returns empty result or controlled not-found | No error; structured empty or not-found response |
| RET-FL05 | Unknown audit ID returns empty result or controlled not-found | No error; structured empty or not-found response |

### 3.5 Unit Tests — Sensitive Data Exclusion

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| RET-S01 | Aggregation results output contains no raw request bodies | No request body content in any field |
| RET-S02 | Aggregation results output contains no raw response bodies | No response body content in any field |
| RET-S03 | Engineering logs output contains no raw headers | No header values in log event fields |
| RET-S04 | Evidence references output contains no raw S3 key values | S3 keys represented as sanitized references, not raw paths |
| RET-S05 | Retrieval output contains no credentials, tokens, or PII | Canary token injection test passes (canary value not present in any retrieval output) |
| RET-S06 | Endpoint IDs in retrieval output are sanitized | No raw URL patterns in endpoint_id fields |

### 3.6 Integration Tests

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| RET-I01 | Retrieval against known fixture aggregation state | All commands return data consistent with fixture |
| RET-I02 | Retrieval for failed aggregation job returns correct failure metadata | Failure category, reason code, and component returned; no aggregate records returned |
| RET-I03 | Retrieval commands produce no mutations | DynamoDB state after retrieval is identical to state before |

## 4. Phase 4A.5 — Structured Logging Validation

### 4.1 Unit Tests

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| LOG-U01 | Aggregation job claim emits `aggregation_job_claimed` event | Event present with correct fields: job_id, audit_id, client_id |
| LOG-U02 | Eligibility evaluation emits `aggregation_eligibility_evaluated` | Event present with result and reason_code |
| LOG-U03 | Integrity gate emits `aggregation_integrity_gate_evaluated` | Event present with result, expected_count, observed_count |
| LOG-U04 | Aggregate set completion emits `aggregation_set_completed` | Event present with record counts |
| LOG-U05 | Aggregation failure emits `aggregation_job_failed` | Event present with failure_category and reason_code |
| LOG-U06 | Lifecycle transition emits `lifecycle_transition` | Event present with from_state, to_state, actor, reason |
| LOG-U07 | Log events contain no sensitive payload content | Canary injection: no canary value appears in any log event output |

### 4.2 Integration Tests

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| LOG-I01 | End-to-end aggregation emits complete structured log timeline | All required events from above appear in order for a full aggregation cycle |

## 5. Phase 4A.6 — Operational Hardening Validation

### 5.1 src/packages Divergence Tests

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| OPS-D01 | Critical functions produce identical outputs for shared fixtures in src/ and packages/ | Behavioral equivalence test passes for all audited modules |
| OPS-D02 | Post-remediation: no test failures from packages/ module divergence | All existing tests pass after synchronization |

### 5.2 Import Smoke Tests

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| OPS-I01 | aggregation_handler imports without error | Handler module imports successfully |
| OPS-I02 | audit_finalization_handler imports without error | Handler module imports successfully |
| OPS-I03 | orchestrator_handler imports without error | Handler module imports successfully |
| OPS-I04 | scheduled_execution_handler imports without error | Handler module imports successfully |
| OPS-I05 | All aggregation submodules import without error | `src/release_confidence_platform/aggregation/*` imports successfully |
| OPS-I06 | Import smoke test detects missing module | When a required import is removed, the smoke test fails |

### 5.3 Startup Validation Tests

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| OPS-S01 | Lambda handler startup validation raises on missing critical import | Missing module causes startup failure before handler invocation |

## 6. Phase 4A.7 — Operational Validation Campaign

### 6.1 Campaign Requirements

Phase 4A.7 is not a PR. It is an operational validation campaign.

**Minimum campaign requirement:** Multiple independent 48-hour audit campaigns.

Short-duration audits are acceptable during Phase 4A.4–4A.6 development. They do not satisfy Phase 4A closure requirements.

### 6.2 Campaign Success Criteria

Each 48-hour campaign must demonstrate all of the following:

| Criteria | Evidence Required |
| --- | --- |
| Lifecycle reaches COMPLETED deterministically | Audit record shows `lifecycle_state = COMPLETED` after window close |
| Aggregation executes successfully | `AggregationJob` record shows `status = COMPLETED` |
| Aggregation artifacts persist | `AggregateSetCompletion` marker present; all child aggregate records present |
| Engineering Retrieval CLI returns deterministic results | `retrieve aggregation-results` output is identical across multiple calls |
| Evidence lineage intact | `retrieve aggregation-lineage` returns complete manifest ref with non-zero `source_ref_count` |
| Aggregation reproducibility | Re-running aggregation for same audit produces `DUPLICATE_COMPLETED` (idempotency confirmation) |
| Structured logging validated | `retrieve engineering-logs` returns complete event timeline |
| Retry behavior validated | At least one retry scenario produces safe outcome (no duplicate records, no partial state) |
| No operational regressions | All prior Phase 3/4 tests continue to pass |

### 6.3 Campaign Documentation

Each campaign requires:

- Campaign start and end timestamps.
- Audit identifiers used.
- Lifecycle transition timestamps.
- Aggregation job metadata (job id, status, source counts).
- Engineering Retrieval CLI output (JSON format).
- Any failure or retry events observed and their resolution.

### 6.4 HITL Gate

Phase 4A.7 closes only upon HITL approval after multiple successful 48-hour campaigns are documented.

## 7. Regression Requirements

All tests from the following suites must continue to pass throughout Phase 4A:

- `tests/unit/aggregation/` (Phase 4 aggregation unit tests)
- `tests/integration/test_phase3_cancellation_finalization.py`
- `tests/integration/test_phase3_lifecycle_determinism_regression.py`
- `tests/unit/test_handler_import_smoke.py`
- `tests/unit/test_aggregation_trigger_real_repository_wiring.py`
- `tests/unit/test_evidence_integrity_gate_failed_runs.py`

## 8. Test Execution Requirements

- Unit tests must be executable with `python -m pytest tests/unit/`
- Integration tests must be executable with `python -m pytest tests/integration/`
- Linting must pass with `python -m ruff check src/ apps/ tests/`
- Import smoke tests must be executable in isolation: `python -m pytest tests/unit/test_handler_import_smoke.py`
