# Phase 5 Consumer Contract

## Status

Proposed — Pending Phase 4A.3 HITL Approval

## Platform Constitutional Statement

**Aggregation owns facts. Phase 5 owns interpretation.**

Phase 5 may derive intelligence from aggregation outputs. Phase 5 shall never redefine or reinterpret persisted aggregation facts.

This ownership boundary is a constitutional statement. It governs all present and future interactions between aggregation (Phase 4) and reliability intelligence (Phase 5).

Structured logs are operational diagnostics. They shall never become authoritative evidence or replace immutable aggregation artifacts. Phase 5 must derive its inputs from immutable aggregation artifacts, not from CloudWatch logs or transient operational state.

---

## 1. Contract Purpose

This document defines the stable contract between the aggregation layer (Phase 4) and the Reliability Intelligence layer (Phase 5).

It specifies:
- What Phase 5 may consume from aggregation.
- What Phase 5 must not do.
- Which fields are stable and guaranteed for Phase 5 consumption.
- How contract changes are governed.

This contract is part of the Release Confidence Platform constitution. It becomes a compatibility gate: future aggregation changes that would break this contract require a new contract version, HITL approval, and automated regression test validation before implementation may proceed.

---

## 2. Ownership Responsibilities

| Concern | Owner |
| --- | --- |
| Raw execution evidence capture | Phase 1 / Phase 2 |
| Audit lifecycle, scheduling, finalization | Phase 3 |
| Deterministic aggregation, persistence, lineage | Phase 4 (Aggregation) |
| Reliability intelligence derivation | Phase 5 (Consumer) |
| Operator/customer reporting | Phase 6 |
| CI/CD integration | Phase 7 |

**Phase 4 responsibilities:**
- Produce deterministic, immutable, versioned aggregate artifacts from raw execution evidence.
- Preserve complete evidence lineage.
- Signal aggregate set completeness through the `AggregateSetCompletion` marker.

**Phase 5 responsibilities:**
- Consume stable aggregation artifacts as inputs.
- Derive reliability intelligence without re-implementing aggregation logic.
- Interpret aggregate outputs to produce reliability metrics, stability metrics, consistency metrics, trend analysis, and release confidence intelligence.

---

## 3. What Phase 5 May Consume

Phase 5 may consume only the following aggregation artifacts:

### 3.1 AggregateSetCompletion Marker

Phase 5 must require this marker before consuming any child aggregate records. The marker is the authoritative proof that the aggregate set is complete.

**Stable fields for Phase 5 consumption:**

| Field | Type | Description |
| --- | --- | --- |
| `aggregate_type` | String | Always `aggregate_set_completion` |
| `client_id` | String | Scoped client identifier |
| `audit_id` | String | Scoped audit identifier |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `aggregation_version` | String | Aggregation version (e.g., `agg_v1`) |
| `aggregation_job_id` | String | Job that produced this set |
| `completion_status` | String | Always `COMPLETE` when record exists |
| `created_at` | String | UTC ISO-8601 aggregate-set timestamp |
| `expected_execution_count` | Number | Finalization execution count validated by integrity gate |
| `source_run_count` | Number | Completed run metadata count |
| `source_raw_result_count` | Number | Raw evidence result count |
| `aggregate_record_count` | Number | Total aggregate records in set |
| `endpoint_aggregate_count` | Number | Endpoint aggregate record count |
| `manifest_count` | Number | Lineage manifest record count |
| `audit_lineage_manifest_ref` | Map | Reference to audit-scope lineage manifest |
| `aggregate_set_hash` | String | Deterministic completeness hash |

### 3.2 AuditAggregate Record

**Stable fields for Phase 5 consumption:**

| Field | Type | Description |
| --- | --- | --- |
| `aggregate_type` | String | Always `audit` |
| `aggregation_version` | String | `agg_v1` |
| `client_id` | String | Scoped client identifier |
| `audit_id` | String | Scoped audit identifier |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `created_at` | String | UTC ISO-8601 timestamp |
| `lineage` | Map | All sub-fields (see EvidenceLineage schema) |
| `request_counts.total` | Number | Total included raw result records |
| `request_counts.successful` | Number | PASS outcome count |
| `request_counts.failed` | Number | Non-PASS outcome count |
| `request_counts.skipped` | Number | Always `0` for `agg_v1` |
| `request_counts.timeout` | Number | TIMEOUT classification count |
| `request_counts.network_failure` | Number | CONNECTION_ERROR classification count |
| `status_code_distribution` | Map | HTTP status code → count; `NO_STATUS` for null/missing |
| `execution_duration_ms` | Number | `max(timestamp) - min(timestamp)` in ms |
| `latency_summary_ms.count` | Number | Included latency measurements |
| `latency_summary_ms.min` | Number | Minimum latency in ms (3 decimal places) |
| `latency_summary_ms.max` | Number | Maximum latency in ms (3 decimal places) |
| `latency_summary_ms.mean` | Number | Mean latency in ms (3 decimal places) |
| `latency_summary_ms.median` | Number | Median latency in ms (3 decimal places) |
| `latency_summary_ms.p95` | Number | 95th percentile latency in ms (3 decimal places) |
| `latency_summary_ms.p99` | Number | 99th percentile latency in ms (3 decimal places) |
| `endpoint_execution_counts` | Map | Sanitized endpoint id → raw result count |

### 3.3 EndpointAggregate Records

**Stable fields for Phase 5 consumption:**

| Field | Type | Description |
| --- | --- | --- |
| `aggregate_type` | String | Always `endpoint` |
| `aggregation_version` | String | `agg_v1` |
| `client_id` | String | Scoped client identifier |
| `audit_id` | String | Scoped audit identifier |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `endpoint_id` | String | Sanitized opaque endpoint identifier |
| `execution_count` | Number | Raw result records for this endpoint |
| `success_inputs.numerator` | Number | PASS count for success rate calculation |
| `success_inputs.denominator` | Number | `execution_count` (skipped = 0 for `agg_v1`) |
| `latency_distribution_ms` | Map | Same schema as `latency_summary_ms` |
| `timeout_count` | Number | TIMEOUT count for this endpoint |
| `failure_classification_counts` | Map | Failure bucket → count (bounded labels) |
| `http_response_distribution` | Map | HTTP status code → count; `NO_STATUS` for null/missing |
| `lineage` | Map | All sub-fields |

### 3.4 FailureClassificationAggregate Records

**Stable fields for Phase 5 consumption:**

| Field | Type | Description |
| --- | --- | --- |
| `aggregate_type` | String | Always `failure_classification` |
| `aggregation_version` | String | `agg_v1` |
| `scope` | String | `audit` \| `endpoint` |
| `endpoint_id` | String | Present only for endpoint scope |
| `classification_counts` | Map | Failure bucket → count; approved labels only |
| `lineage` | Map | All sub-fields |

**Approved classification labels:** `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, `PAYLOAD_VALIDATION_ERROR`, `MISSING_FAILURE_CLASSIFICATION`, `UNKNOWN_FAILURE_CLASSIFICATION`.

### 3.5 LineageManifest (Read-Only Traceability)

Phase 5 may read lineage manifests for evidence traceability purposes.

Phase 5 must not use lineage manifests to re-derive aggregation inputs or bypass aggregation logic. Lineage manifests are evidence chain records, not computation inputs for Phase 5.

**Stable fields for Phase 5 consumption:**

| Field | Type | Description |
| --- | --- | --- |
| `manifest_version` | String | `lineage_manifest_v1` |
| `manifest_scope` | String | `audit` \| `endpoint:{endpoint_id}` |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `aggregation_version` | String | `agg_v1` |
| `source_ref_count` | Number | Number of raw result refs |
| `manifest_hash` | String | Integrity hash |

---

## 4. What Phase 5 Must Not Do

Phase 5 is explicitly prohibited from:

1. **Consuming raw execution evidence directly.** Phase 5 must not read S3 raw result objects, DynamoDB run metadata, or any Phase 1/2/3 raw evidence records. All Phase 5 inputs must come from Phase 4 aggregation artifacts.

2. **Mutating aggregation artifacts.** Phase 5 must not create, update, delete, or extend any aggregation record, lineage manifest, or aggregate-set completion marker.

3. **Reinterpreting persisted aggregation facts.** Phase 5 must not re-aggregate, re-summarize, or re-count raw evidence. Phase 5 must not override aggregation counts, distributions, or classification results.

4. **Bypassing the AggregateSetCompletion marker.** Phase 5 must not infer aggregate set completeness from child record counts. The `AggregateSetCompletion` marker is the only authoritative completeness proof.

5. **Reading AggregationJob or AggregationJobIntent records.** These are internal aggregation implementation details and are not part of the Phase 5 consumer contract.

6. **Inferring reliability conclusions from structured logs.** Phase 5 must not use CloudWatch logs, structured log queries, or operational diagnostics as inputs for reliability intelligence. Structured logs are engineering diagnostics only.

7. **Redefining failure classifications.** Phase 5 must consume classification labels as defined by aggregation without renaming, remapping, or inferring alternative categorizations.

---

## 5. DynamoDB Access Patterns

Phase 5 must use only the following query patterns:

**Query 1: Find aggregate set completion marker**
```
PK = CLIENT#{client_id}
SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#SET
```

**Query 2: Get all aggregate records for a set**
```
PK = CLIENT#{client_id}
SK begins_with AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#
```

Downstream phases must not query by patterns that would return aggregation job, intent, or identity records unless those are separate namespaced queries with explicit filtering.

---

## 6. agg_v1 Semantic Guarantees

The following semantic guarantees apply to `aggregation_version = agg_v1`:

| Guarantee | Value |
| --- | --- |
| `skipped` in `request_counts` | Always `0` |
| `PAYLOAD_VALIDATION_ERROR` classification | Counted in `failed`, never in `skipped` |
| Latency precision | 3 decimal places, half-up rounding |
| Latency percentiles | Nearest-rank: `ceil(p/100 * count)`, 1-indexed |
| Endpoint identifier | Sanitized; unsafe values map to `unknown` or hash |
| Failure classification | Only execution-generated categories; no inference |

---

## 7. Contract Versioning and Compatibility Gate

### Version Governance

| Contract version | Aggregation version | Status |
| --- | --- | --- |
| `consumer_contract_v1` | `agg_v1` | Current baseline |

This document (`phase_4a_phase5_consumer_contract.md`) is the `consumer_contract_v1` baseline.

### Breaking Change Definition

A breaking change is any modification to a stable field that:
- Removes a field listed in Section 3.
- Renames a field listed in Section 3.
- Changes the type of a field listed in Section 3.
- Changes the semantic meaning of a field listed in Section 3 (e.g., redefining what `skipped` means).
- Removes a record type listed in Section 3.

New fields added to existing records are non-breaking. New record types are non-breaking.

### Breaking Change Process

Breaking changes require:
1. Contract version increment (e.g., `consumer_contract_v2`).
2. HITL approval of the new contract version document.
3. Explicit consumer migration documentation describing what Phase 5 must change.
4. Automated regression test validation in `tests/unit/test_phase5_consumer_contract.py`.

No breaking change may be merged without passing the compatibility gate test.

### Compatibility Gate Test

`tests/unit/test_phase5_consumer_contract.py` is the automated compatibility gate. It validates that all stable fields listed in Section 3 are present, correctly typed, and semantically consistent in the current aggregation output for a known fixture.

This test must pass for all `agg_v1` aggregation output. Failure of this test blocks Phase 4 implementation changes.

---

## 8. Non-Negotiable Invariants

These invariants cannot be waived by any future phase or product decision without a formal constitutional amendment approved through HITL governance:

1. Phase 5 shall never consume raw execution evidence directly.
2. Phase 5 shall never mutate aggregation artifacts.
3. The `AggregateSetCompletion` marker is the only authoritative completeness proof for an aggregate set.
4. Structured logs are engineering diagnostics and shall never replace immutable aggregation artifacts as authoritative evidence.
5. Aggregation owns facts. Phase 5 owns interpretation.

---

## 9. Traceability

- Phase 4A.2 Aggregation Schema: `docs/architecture/phase_4a_aggregation_schema.md`
- Phase 4A.1 Technical Design: `docs/architecture/phase_4a_aggregation_foundation_technical_design.md`
- Phase 4A.1 ADR: `docs/architecture/adr_phase_4a_engineering_retrieval_consumer_contract.md`
- Phase 4A.1 Product Spec: `docs/product/phase_4a_aggregation_foundation_product_spec.md`
- Phase 4 ADR: `docs/architecture/adr_phase_4_evidence_lineage_aggregation.md`
- Compatibility gate test: `tests/unit/test_phase5_consumer_contract.py`
