# Phase 4A.2 — Aggregation Schema

## 1. Overview

This document defines the canonical persisted aggregation schema for Phase 4A. It specifies the DynamoDB record types, primary key patterns, field definitions, types, constraints, and versioning rules that govern all aggregation artifacts.

This schema is the authoritative source for:
- Phase 4A.4 persistence implementation.
- Phase 4A.5 Engineering Retrieval CLI data access.
- Phase 4A.3 Phase 5 consumer contract field stability guarantees.
- Future aggregation version additions.

The schema is immutable after publication except through formal versioning. Field additions to existing record types require a new `aggregation_version`. Field renames, removals, or type changes require a new `aggregation_version` and explicit consumer migration.

## 2. Table Configuration

All aggregation records are stored in the existing metadata DynamoDB table.

**Primary key pattern (consistent across all Phase 4 record types):**

```
PK = CLIENT#{client_id}
SK = AUDIT#{audit_id}#...
```

No new table is required for Phase 4A.

## 3. Record Types

### 3.1 AggregationJobIntent

**Purpose:** Durable evidence that Phase 3 finalization requested Phase 4 aggregation before asynchronous invocation. Prevents finalized audits from silently lacking aggregation lifecycle state.

**Sort Key:**
```
AUDIT#{audit_id}#AGGJOB#{aggregation_job_id}
```
(Reuses the AggregationJob sort key with initial `status = INTENT_RECORDED`)

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | `AUDIT#{audit_id}#AGGJOB#{aggregation_job_id}` |
| `record_type` | String | Yes | `aggregation_job_intent` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `aggregation_job_id` | String | Yes | Safe generated job identifier |
| `aggregation_version` | String | Yes | `agg_v1` |
| `status` | String | Yes | `INTENT_RECORDED` on creation |
| `created_at` | String | Yes | UTC ISO-8601 timestamp |
| `finalization_correlation_id` | String | No | Correlation id from finalization that recorded intent |
| `invocation_status` | String | No | `NOT_REQUESTED` \| `REQUESTED` \| `FAILED` \| `ACCEPTED` |
| `invocation_attempted_at` | String | No | UTC ISO-8601 timestamp |
| `invocation_failure_reason_code` | String | No | Controlled reason code if invocation failed |

**Lifecycle:** Created once during successful finalization. Status updated to reflect invocation outcome.

---

### 3.2 AggregationJob

**Purpose:** Tracks each aggregation attempt, eligibility decision, duplicate detection, retry, failure, and completion.

**Sort Key:**
```
AUDIT#{audit_id}#AGGJOB#{aggregation_job_id}
```

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | `AUDIT#{audit_id}#AGGJOB#{aggregation_job_id}` |
| `record_type` | String | Yes | `aggregation_job` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Conditional | Resolved durable execution id; null only before resolution |
| `config_version` | String | Conditional | Resolved config version; null only before resolution |
| `aggregation_job_id` | String | Yes | Safe generated/validated job identifier |
| `aggregation_version` | String | Yes | `agg_v1` |
| `status` | String | Yes | See status enum below |
| `failure_category` | String | No | `EVIDENCE_PRODUCING` \| `EVIDENCE_TRANSFORMING` \| null |
| `reason_code` | String | No | Controlled reason code from bounded enum; null on success |
| `started_at` | String | No | UTC ISO-8601 timestamp |
| `completed_at` | String | No | UTC ISO-8601 timestamp |
| `trigger_invocation_attempted_at` | String | No | UTC ISO-8601 timestamp |
| `trigger_invocation_status` | String | No | `NOT_REQUESTED` \| `REQUESTED` \| `FAILED` \| `ACCEPTED` |
| `source_run_count` | Number | No | Completed run metadata records considered |
| `source_raw_result_count` | Number | No | Raw result records aggregated |
| `expected_execution_count` | Number | No | Finalization `execution_count` used by integrity gate |
| `aggregate_record_count` | Number | No | Aggregate records written |
| `lineage_manifest_ref` | Map | No | Bounded manifest reference when created |
| `aggregate_set_ref` | Map | No | AggregateSetCompletion reference when completed |
| `duplicate_of_aggregation_job_id` | String | No | Existing completed job if this is a duplicate |
| `error_summary` | Map | No | `{ reason_code, component, correlation_id }` — sanitized only |

**Status enum:** `INTENT_RECORDED` \| `INVOCATION_REQUESTED` \| `INVOCATION_FAILED` \| `STARTED` \| `COMPLETED` \| `FAILED` \| `INELIGIBLE` \| `DUPLICATE_COMPLETED` \| `CONFLICT`

**Lifecycle:** Created by conditional put. Updated only for job outcome metadata.

---

### 3.3 AuditExecutionIdentity

**Purpose:** Durable first-class execution identity for a finalized audit, canonical for Phase 4+ lineage.

**Sort Key (if separate child item):**
```
AUDIT#{audit_id}#EXECUTION_ID
```
(Preferred: stored as a field on the canonical audit metadata item if possible.)

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | `AUDIT#{audit_id}#EXECUTION_ID` |
| `record_type` | String | Yes | `audit_execution_identity` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Yes | Durable opaque identifier; canonical Phase 4+ execution key |
| `source` | String | Yes | `phase3_metadata` \| `phase4_identity_assignment` |
| `created_at` | String | Yes | UTC ISO-8601 timestamp |

**Lifecycle:** Created once by conditional write. Never mutated.

---

### 3.4 LineageManifest

**Purpose:** Immutable sanitized manifest resolving to the exact canonical raw result references used by an aggregate set or endpoint scope.

**Sort Key:**
```
AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#LINEAGE#{manifest_scope}
```

Where `manifest_scope` is:
- `audit` — for the audit-wide lineage manifest
- `endpoint:{endpoint_id}` — for per-endpoint scoped manifests (sanitized endpoint id)

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | As above |
| `record_type` | String | Yes | `lineage_manifest` |
| `manifest_version` | String | Yes | `lineage_manifest_v1` |
| `manifest_scope` | String | Yes | `audit` \| `endpoint:{endpoint_id}` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Yes | Durable execution identifier |
| `config_version` | String | Yes | Mandatory config version |
| `aggregation_version` | String | Yes | `agg_v1` |
| `aggregation_job_id` | String | Yes | Job that wrote this manifest |
| `created_at` | String | Yes | UTC ISO-8601 timestamp |
| `source_ref_count` | Number | Yes | Number of canonical raw result refs |
| `source_raw_result_refs` | List | Yes | Canonically sorted sanitized refs (bounded) |
| `manifest_hash` | String | Yes | Hash of canonical serialized manifest content |

**source_raw_result_refs item schema:**
```json
{
  "raw_result_version": "v1",
  "run_id": "run_123",
  "raw_result_s3_key": "<sanitized key reference>",
  "s3_version_id": "<version id or null>",
  "object_version_lineage_available": true,
  "result_index": 0,
  "endpoint_id": "<sanitized endpoint id>",
  "result_timestamp": "2026-06-07T12:00:00Z"
}
```

**Lifecycle:** Written once by conditional put. Never mutated.

---

### 3.5 AggregateSetCompletion

**Purpose:** Canonical immutable parent/completion record for a fully written aggregate set. Authoritative downstream-consumable proof of completeness.

**Sort Key:**
```
AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#SET
```

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | As above |
| `record_type` | String | Yes | `aggregate_set_completion` |
| `aggregate_type` | String | Yes | `aggregate_set_completion` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Yes | Durable execution identifier |
| `config_version` | String | Yes | Mandatory config version |
| `aggregation_version` | String | Yes | `agg_v1` |
| `aggregation_job_id` | String | Yes | Job that wrote this aggregate set |
| `completion_status` | String | Yes | Always `COMPLETE` — no partial marker is written |
| `created_at` | String | Yes | UTC ISO-8601 aggregation timestamp |
| `expected_execution_count` | Number | Yes | Finalization execution count validated by integrity gate |
| `source_run_count` | Number | Yes | Completed run metadata count validated |
| `source_raw_result_count` | Number | Yes | Raw evidence result count validated |
| `aggregate_record_count` | Number | Yes | Number of aggregate records in set (excluding job/intent records) |
| `endpoint_aggregate_count` | Number | Yes | Number of endpoint aggregate records |
| `manifest_count` | Number | Yes | Number of lineage manifest records |
| `audit_lineage_manifest_ref` | Map | Yes | Reference to audit-scope lineage manifest |
| `aggregate_set_hash` | String | Yes | Hash over canonical aggregate-set metadata and manifest hashes |

**audit_lineage_manifest_ref schema:**
```json
{
  "manifest_scope": "audit",
  "source_ref_count": 42,
  "manifest_hash": "<hash>"
}
```

**Lifecycle:** Written once by conditional put, atomically with all aggregate records. Never mutated.

---

### 3.6 AuditAggregate

**Purpose:** Audit-level summary record for a finalized audit execution, config version, and aggregation version.

**Sort Key:**
```
AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#AUDIT
```

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | As above |
| `record_type` | String | Yes | `audit_aggregate` |
| `aggregate_type` | String | Yes | `audit` |
| `aggregation_version` | String | Yes | `agg_v1` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Yes | Durable execution identifier |
| `config_version` | String | Yes | Mandatory config version |
| `lineage` | Map | Yes | See EvidenceLineage schema below |
| `request_counts` | Map | Yes | See RequestCounts schema below |
| `status_code_distribution` | Map | Yes | String status code → count; `NO_STATUS` for null/missing |
| `execution_duration_ms` | Number | Yes | `max(timestamp) - min(timestamp)` from valid included timestamps; `0` if < 2 timestamps |
| `latency_summary_ms` | Map | Yes | See LatencySummary schema below |
| `endpoint_execution_counts` | Map | Yes | Sanitized endpoint id → included raw result count |
| `created_at` | String | Yes | UTC ISO-8601; same as lineage `aggregation_timestamp` |

**RequestCounts schema:**
```json
{
  "total": 42,
  "successful": 38,
  "failed": 4,
  "skipped": 0,
  "timeout": 1,
  "network_failure": 1
}
```

- `skipped` is always `0` for `agg_v1` (Raw Result Schema v1 has no explicit skipped indicator).
- `PAYLOAD_VALIDATION_ERROR` is counted in `failed`, not `skipped`.
- `timeout` counts only raw classification `TIMEOUT`.
- `network_failure` counts only raw classification `CONNECTION_ERROR`.

**LatencySummary schema:**
```json
{
  "count": 42,
  "min": 45.123,
  "max": 2150.456,
  "mean": 312.789,
  "median": 287.500,
  "p95": 1823.456,
  "p99": 2087.123
}
```

- Only numeric `duration_ms >= 0` values are included.
- Stats are `null` when `count = 0`, except `count` itself which is `0`.
- All numeric latency values are rounded to 3 decimal places using half-up rounding.
- `median`: middle value for odd count; average of two middle values for even count.
- `p95` / `p99`: nearest-rank percentile — rank = `ceil(p/100 * count)`, 1-indexed, clamped to `[1, count]`.

**Lifecycle:** Written once by conditional put. Never updated or deleted.

---

### 3.7 EndpointAggregate

**Purpose:** One endpoint-level summary per represented sanitized endpoint.

**Sort Key:**
```
AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#ENDPOINT#{endpoint_id}
```

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | As above |
| `record_type` | String | Yes | `endpoint_aggregate` |
| `aggregate_type` | String | Yes | `endpoint` |
| `aggregation_version` | String | Yes | `agg_v1` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Yes | Durable execution identifier |
| `config_version` | String | Yes | Mandatory config version |
| `endpoint_id` | String | Yes | Opaque/sanitized endpoint identifier; never raw URL/query/header/payload/token |
| `execution_count` | Number | Yes | Included raw records for this endpoint |
| `success_inputs` | Map | Yes | See SuccessInputs schema below |
| `latency_distribution_ms` | Map | Yes | Latency summary stats (same schema as `latency_summary_ms`) |
| `timeout_count` | Number | Yes | Count where raw classification is `TIMEOUT` |
| `failure_classification_counts` | Map | Yes | Failure bucket → count (see bucket rules) |
| `http_response_distribution` | Map | Yes | String status code → count; `NO_STATUS` for null/missing |
| `lineage` | Map | Yes | See EvidenceLineage schema; must reference endpoint-scoped manifest |

**SuccessInputs schema:**
```json
{
  "numerator": 38,
  "denominator": 42
}
```

- `numerator` = count of raw records with classification `PASS`.
- `denominator` = `execution_count - skipped_count`. For `agg_v1`, skipped = 0, so denominator = `execution_count`.

**Failure classification bucket rules:**
- Preserved labels: `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, `PAYLOAD_VALIDATION_ERROR`.
- Missing/null/empty/whitespace classification: `MISSING_FAILURE_CLASSIFICATION`.
- Non-empty unapproved value: `UNKNOWN_FAILURE_CLASSIFICATION`.
- No inferred, enriched, or root-cause categories.

**Lifecycle:** Written once by conditional put. One record per represented sanitized endpoint. Endpoint omitted if no raw records exist for it.

---

### 3.8 FailureClassificationAggregate

**Purpose:** Queryable failure classification counts for audit-level and endpoint-level consumers without root-cause inference.

**Sort Keys:**
- Audit-level: `AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#FAILURE_CLASSIFICATION`
- Endpoint-level: `AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#ENDPOINT#{endpoint_id}#FAILURE_CLASSIFICATION`

**Fields:**

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | As above |
| `record_type` | String | Yes | `failure_classification_aggregate` |
| `aggregate_type` | String | Yes | `failure_classification` |
| `aggregation_version` | String | Yes | `agg_v1` |
| `scope` | String | Yes | `audit` \| `endpoint` |
| `endpoint_id` | String | Conditional | Present only for endpoint scope |
| `classification_counts` | Map | Yes | See bucket rules above; at minimum `PASS` count present |
| `lineage` | Map | Yes | Bounded lineage metadata and manifest reference |

**Lifecycle:** Written once by conditional put.

---

## 4. EvidenceLineage Schema (shared by all aggregate records)

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `client_id` | String | Yes | Client identifier |
| `audit_id` | String | Yes | Audit identifier |
| `audit_execution_id` | String | Yes | Durable first-class execution identity. Required; fails closed if absent. |
| `config_version` | String | Yes | Mandatory resolved config version. Required; fails closed if absent. |
| `aggregation_version` | String | Yes | `agg_v1` |
| `aggregation_job_id` | String | Yes | Job that wrote this aggregate set |
| `aggregation_timestamp` | String | Yes | UTC ISO-8601 timestamp fixed once per aggregate set |
| `lineage_manifest_ref` | Map | Yes | Bounded immutable reference to exact source refs |
| `source_ref_count` | Number | Yes | Count of canonical raw result refs in manifest scope |
| `lineage_manifest_hash` | String | Yes | Hash of canonical manifest payload |

**lineage_manifest_ref schema:**
```json
{
  "manifest_scope": "audit | endpoint:{endpoint_id}",
  "manifest_hash": "<hash>",
  "source_ref_count": 42
}
```

No aggregate record stores unbounded inline `source_raw_result_refs` arrays. All source refs are stored in the `LineageManifest` record.

---

## 5. Sort Key Prefix Index

| Prefix | Record Type |
| --- | --- |
| `AUDIT#{id}` | Canonical audit record (Phase 3) |
| `AUDIT#{id}#RUN#{id}` | Run metadata (Phase 1/3) |
| `AUDIT#{id}#AGGJOB#{id}` | AggregationJob / AggregationJobIntent |
| `AUDIT#{id}#EXECUTION_ID` | AuditExecutionIdentity (if separate) |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#SET` | AggregateSetCompletion |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#AUDIT` | AuditAggregate |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#ENDPOINT#{id}` | EndpointAggregate |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#ENDPOINT#{id}#FAILURE_CLASSIFICATION` | EndpointFailureClassificationAggregate |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#FAILURE_CLASSIFICATION` | AuditFailureClassificationAggregate |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#LINEAGE#{scope}` | LineageManifest |

Existing audit listing queries must use positive canonical-row filtering so aggregate child records are not returned as audits.

---

## 6. Schema Versioning Rules

1. This schema is immutable after publication for `aggregation_version = agg_v1`.
2. Field additions to existing record types require a new `aggregation_version` (e.g., `agg_v2`).
3. Field renames, removals, or type changes require a new `aggregation_version` and explicit consumer migration documentation.
4. New `aggregation_version` records are written as new records; existing `agg_v1` records are never modified.
5. The `aggregation_version` field on every record is the canonical version identifier.

---

## 7. Sensitive Data Exclusion

No field in any aggregation record may contain:
- Raw request or response bodies.
- HTTP headers or cookies.
- Tokens, credentials, secrets, or PII.
- Raw URLs, query strings, or path parameters.
- Payload fragments or tenant-sensitive raw content.

Endpoint identifiers in `endpoint_id` fields must be validated as safe opaque identifiers. Raw URL patterns map to controlled placeholder `unknown` or a deterministic sanitized hash.

---

## 8. Backward Compatibility Guarantee

The Phase 5 consumer contract published in Phase 4A.3 references the stable fields defined in this schema document. Any change to this schema that affects stable fields constitutes a breaking contract change and requires: contract version increment, HITL approval, and consumer migration documentation.

The compatibility gate test (`tests/unit/test_phase5_consumer_contract.py`) validates that all stable fields defined here are present and correctly typed in the current aggregation output.
