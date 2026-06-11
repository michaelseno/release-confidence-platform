# Technical Design

## 1. Feature Overview

Phase 4 adds a backend-only aggregation layer that reads immutable raw execution evidence for successfully finalized Phase 3 audits and writes deterministic, immutable, versioned aggregate datasets. Aggregates are derived analytical inputs for future internal phases only; raw evidence remains the source of truth.

This revision incorporates the human-approved Phase 4 architecture decisions for a first-class durable `audit_execution_id`, mandatory `config_version`, explicit skipped-count semantics, zero-execution exclusion, bounded endpoint-scoped lineage manifests, internal-only lifecycle triggering, a pre-aggregation evidence integrity validation gate, durable recovery taxonomy, aggregate-set completion semantics, and security-sensitive storage/logging controls.

## 2. Product Requirements Summary

- Aggregate only audits that completed successful Phase 3 finalization.
- Reject incomplete, non-finalized, failed, cancelled, execution-failed, zero-execution, or metadata-inconsistent audits without aggregate creation.
- Read raw evidence without mutation, deletion, replacement, compaction, or reclassification.
- Produce audit-level and endpoint-level aggregate datasets with failure-classification counts.
- Preserve lineage on every aggregate using `audit_id`, durable `audit_execution_id`, mandatory `config_version`, `aggregation_version`, `aggregation_job_id`, `aggregation_timestamp`, and a bounded immutable lineage manifest/reference resolving to exact raw result references.
- Prevent duplicate records and double counting under retries, duplicate events, concurrent triggers, and repeated execution.
- Treat aggregate records as immutable and versioned; future semantic changes require a new `aggregation_version`.
- Exclude scoring, conclusions, AI insights, reports, dashboards, operator/customer workflows, release gating, and public APIs.
- Exclude sensitive raw content from aggregate records, job metadata, lineage manifests, errors, and logs.

## 3. Requirement-to-Architecture Mapping

| Requirement | Technical Design Response |
| --- | --- |
| FR-001, FR-010, AC-001 | `AggregationEligibilityService` accepts only canonical audit metadata with `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, and successful finalization completion transition metadata; `EvidenceIntegrityValidator` then reconciles finalization counts, completed run metadata, raw evidence count, duplicate source refs, identity/config resolution, and lineage completeness before aggregation. |
| FR-002, AC-002 | Raw evidence is read through read-only S3/repository methods; Phase 4 never writes, deletes, mutates, compacts, or reclassifies raw evidence. |
| FR-003, FR-004, AC-003, AC-004 | `AggregationEngine` emits one audit aggregate and one endpoint aggregate per represented sanitized endpoint for each aggregate set. |
| FR-005, AC-005, AC-006 | Failure classifications are grouped only from execution-generated raw categories; missing/unknown values use deterministic buckets. |
| FR-006, AC-007 | Every aggregate stores bounded lineage metadata and a `lineage_manifest_ref`; audit aggregates reference the audit-scoped manifest and endpoint aggregates reference endpoint-scoped manifest entries/records resolving to exact canonical raw result references for that endpoint. |
| FR-007, FR-008, FR-009, AC-008 through AC-010 | Job claim, aggregate-set uniqueness, same-job duplicate handling, conflict reload, immutable writes, and an aggregate-set completion marker use deterministic identity and conditional writes. Duplicate raw references fail validation before aggregate creation. |
| FR-011, AC-009, AC-011 | MVP aggregate persistence fails before aggregate writes when transaction/item-size limits would be exceeded; no chunking protocol is in current scope. |
| FR-012, AC-015 | `agg_v1` defines deterministic sorting, counting, nearest-rank percentiles, and decimal precision/rounding. |
| NFR-005, AC-014 | Strict aggregate input/output allowlist, endpoint identifier sanitization, IAM least privilege, internal trigger controls, and sanitized errors/logs prevent raw sensitive content exposure. |

## 4. Technical Scope

### Current Technical Scope

- Internal system-managed aggregation trigger after successful finalization.
- Canonical propagation and persistence of durable `audit_execution_id` from Phase 4 onward.
- Mandatory `config_version` validation, propagation, and aggregate/manifest persistence.
- Aggregation job metadata and immutable aggregate storage under the existing audit/client metadata partition.
- Bounded immutable lineage manifest storage/reference design.
- Explicit pre-aggregation evidence integrity validation gate that fails closed before aggregate computation, manifest writes, or aggregate writes.
- Durable aggregation failure taxonomy separating evidence-producing failures from evidence-transforming failures.
- Canonical aggregate-set completion marker for downstream completeness checks.
- Durable aggregation job intent persisted by finalization before asynchronous aggregation invocation.
- Deterministic aggregate calculation for `agg_v1`.
- Retry safety, duplicate trigger handling, duplicate raw reference validation, and fail-before-write oversized behavior.
- Security controls for field allowlists, endpoint identifiers, IAM, internal invocation, errors, and logs.

### Out of Scope

- Public/customer/operator API or UI for aggregation invocation.
- Normal manual aggregation or reaggregation workflows.
- Reliability conclusions, scores, reports, dashboards, AI insights, recommendations, release gates, or CI/CD decisions.
- Raw evidence mutation, deletion, replacement, compaction, reclassification, or checksum backfill into raw evidence.
- Chunked aggregate persistence protocol for oversized aggregate sets.
- S3 object-versioning enablement or retroactive version id guarantees.

### Future Technical Considerations

- Future aggregation versions may write new immutable aggregate sets.
- Future reaggregation/backfill tooling may be added as a privileged audited administrative workflow.
- Privileged administrative disaster-recovery aggregation invocation is deferred unless separately designed, implemented, and reviewed; Phase 4 normal operators still cannot manually trigger aggregation.
- Future phases may consume `audit_execution_id` as the canonical identity for reliability intelligence, reports, CI/CD, support tooling, commercialization, and multi-tenancy.

## 5. Architecture Overview

### Selected Pattern

Use an internal lifecycle-triggered job processor with a pure deterministic aggregation core:

1. Phase 3 successful finalization completion first persists an `AggregationJobIntent`/pending job record, then invokes the internal `aggregate_audit` trigger. No user/operator/customer invocation path exists.
2. Handler validates event shape and safe identifiers, then creates/claims or resumes the `AggregationJob` inside controlled orchestration flow with conditional write semantics.
3. Eligibility service loads canonical audit metadata and validates finalization state, durable execution identity, and `config_version` before any raw evidence processing.
4. Raw evidence reader discovers completed run metadata and reads immutable Raw Result Schema v1 S3 envelopes read-only.
5. `EvidenceIntegrityValidator` executes a hard gate before aggregate computation or any lineage/aggregate writes. It reconciles finalization metadata, completed run count, loaded raw evidence count, duplicate source references, resolved `audit_execution_id`, resolved `config_version`, and lineage completeness.
6. Aggregation engine computes deterministic DTOs from approved raw fields only after the integrity gate passes.
7. Lineage writer prepares one audit-scoped immutable bounded manifest plus endpoint-scoped immutable manifest entries/records for each endpoint aggregate.
8. Aggregate repository writes all lineage manifests, aggregate records, and the canonical aggregate-set completion marker atomically when within MVP storage limits. If limits would be exceeded, the job fails before manifest, aggregate, or completion-marker creation.
9. Job metadata records `COMPLETED`, `FAILED`, `INELIGIBLE`, `DUPLICATE_COMPLETED`, or `CONFLICT` with controlled sanitized reason codes and durable failure category.

### Boundary Decisions

- `audit_execution_id` is the canonical durable execution identifier from Phase 4 onward. `run_id` remains a raw evidence/run implementation detail and must not be used as the long-term primary lineage key.
- Raw S3 evidence is not mutated to add `audit_execution_id`, `config_version`, checksum, or skipped fields. Linkage is established by Phase 4 metadata, run metadata, aggregate records, and immutable lineage manifests.
- The aggregation engine is pure: no AWS calls, logging side effects, lifecycle transitions, or raw evidence mutation.
- Phase 4 does not transition audits to `ANALYZING` and does not trigger Phase 5/6/7 workflows.
- The aggregate set, not any individual endpoint child, is the canonical aggregated evidence artifact. Downstream phases must require the `AggregateSetCompletion` marker before consuming any Phase 4 aggregate records.

## 6. System Components

### AggregationTriggerHandler

Suggested location: `apps/backend/handlers/aggregation_handler.py`

Responsibilities:
- Accept only internal `aggregate_audit` events from approved system principals/rules.
- Validate `schema_version`, `client_id`, `audit_id`, `aggregation_version`, optional `aggregation_job_id`, and optional correlation metadata.
- Reject event payloads containing raw evidence or unsupported fields.
- Invoke orchestration and return sanitized structured outcomes.

### AggregationJobIntentRecorder

Suggested location: existing finalization metadata/repository layer plus `src/release_confidence_platform/aggregation/repository.py`

Responsibilities:
- During successful Phase 3 finalization, persist a durable pending aggregation intent before asynchronous invocation.
- Use the same aggregate-set identity inputs available at finalization (`client_id`, `audit_id`, `aggregation_version`, and, once resolved, `audit_execution_id`/`config_version`) and a generated safe `aggregation_job_id`.
- Record invocation state transitions such as `INTENT_RECORDED`, `INVOCATION_REQUESTED`, `INVOCATION_FAILED`, `STARTED`, and terminal orchestration outcome.
- Ensure a finalized audit cannot silently remain without aggregation lifecycle evidence when async invocation fails.

### AggregationOrchestrator

Suggested location: `src/release_confidence_platform/aggregation/orchestrator.py`

Responsibilities:
- Coordinate job claim, eligibility, raw evidence read, validation, manifest creation, aggregate write, and job outcome update.
- Enforce fail-before-write behavior for invalid input, duplicate raw references, missing lineage fields, and oversized aggregate sets.
- Handle same-`aggregation_job_id` duplicate events and job-claim conflicts inside orchestration, producing controlled `DUPLICATE_COMPLETED` or `CONFLICT` outcomes rather than uncaught conditional-write failures.
- Emit sanitized audit logs/metrics only.

### AggregationEligibilityService

Responsibilities:
- Load canonical audit metadata only from `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}`.
- Validate exact eligibility: `lifecycle_state = COMPLETED`, `finalization.execution_count` integer `> 0`, `finalization.zero_execution = false`, and finalization completion transition present/consistent.
- Reject audits with failed/cancelled/in-progress states, missing/invalid finalization, zero execution, execution failure, missing `audit_execution_id`, or missing `config_version`.
- Resolve `audit_execution_id` and `config_version` only from validated metadata; no defaults, inference, or substitution from `audit_id`.

### AuditExecutionIdentityResolver

Responsibilities:
- Introduce/resolve durable first-class `audit_execution_id` for Phase 4 aggregate processing.
- Preferred propagation point: canonical audit/finalization metadata must include `audit_execution_id` before aggregation starts. If upstream Phase 3 metadata does not yet persist it, Phase 4 must create and persist a durable execution identity in controlled Phase 4-owned metadata before raw evidence processing, using a conditional write keyed to the audit finalization record, not by mutating raw S3 evidence.
- Persist the resolved value in `AggregationJob`, aggregate records, and lineage manifests.
- Preserve links to existing raw evidence via `{audit_id, run_id, raw_result_s3_key, result_index}` references; do not reinterpret `run_id` as canonical execution identity.

### RawEvidenceReader

Responsibilities:
- Query run metadata under `PK = CLIENT#{client_id}`, `SK begins_with AUDIT#{audit_id}#RUN#`.
- Include only completed run metadata with `raw_result_version = v1` and non-empty `raw_result_s3_key`.
- Read raw result envelopes from stored S3 keys using read-only access.
- Validate envelope/run consistency and produce canonical raw result references.
- Do not log S3 keys if they would include unsafe raw data; use sanitized key hashes/short references in logs.

### EvidenceIntegrityValidator

Responsibilities:
- Execute after canonical audit metadata, run metadata, and raw evidence envelopes are loaded, but before aggregate computation, lineage manifest persistence, aggregate writes, or aggregate-set completion marker writes.
- Validate all gate conditions listed below as one hard fail-closed decision:
  - `lifecycle_state = COMPLETED`.
  - successful finalization metadata and successful finalization transition are present and consistent.
  - `finalization.execution_count` is an integer `> 0`.
  - `finalization.zero_execution = false`.
  - expected finalization execution count equals persisted completed run metadata count considered for aggregation.
  - expected finalization execution count equals loaded raw evidence result count used for aggregation.
  - every completed run metadata record has a readable Raw Result Schema v1 envelope and at least one expected canonical raw result reference as defined by current execution semantics.
  - no duplicate raw source reference identities exist in the loaded input set.
  - `audit_execution_id` is present/resolved before validation passes.
  - `config_version` is present/resolved before validation passes.
  - lineage completeness: every canonical aggregate input record has a canonical sanitized raw source reference, endpoint scope assignment, and all required lineage keys; every endpoint aggregate has a non-empty endpoint-scoped source reference set.
- Classify failures caused by missing/incomplete/corrupt evidence as `EVIDENCE_PRODUCING` failures and block aggregation with no aggregate or lineage manifest creation.
- Produce only sanitized validation diagnostics: reason code, expected counts, observed counts, component name, and correlation/job ids. Do not include raw source values.

### AggregationEngine

Responsibilities:
- Deterministically compute counts, distributions, duration, and latency summaries from an allowlisted canonical input DTO.
- Sort included records by canonical reference identity before processing.
- Treat unknown/missing classification and endpoint identifiers deterministically.
- Return aggregate DTOs without persistence or logging side effects.

### LineageManifestRepository

Responsibilities:
- Persist immutable sanitized manifest records or S3 objects containing complete canonical raw result references for the audit aggregate set and exact endpoint source scopes.
- Return bounded `lineage_manifest_ref` embedded in every aggregate. Audit-level aggregate records reference manifest scope `audit`; endpoint aggregate records must reference `endpoint:{endpoint_id}` or a manifest entry id whose source set is exactly the records used for that endpoint aggregate.
- Enforce manifest size caps and fail before aggregate creation if the manifest cannot be written safely within MVP limits.

### AggregateRepository

Responsibilities:
- Persist job metadata, optional audit execution identity metadata, lineage manifests, and aggregate records using conditional writes.
- Enforce uniqueness and immutability.
- Provide read helpers for duplicate detection and future internal consumers.
- Persist the canonical `AggregateSetCompletion` marker atomically with the complete aggregate set and expose completeness reload helpers used by conflict/duplicate handling.

## 7. Data Models

## AuditExecutionIdentity

### Purpose

Durable first-class execution identity for a finalized audit, canonical for Phase 4+ lineage and future internal consumers.

### Primary Key

- Preferred if stored on canonical audit/finalization metadata: existing `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}`, field `audit_execution_id`.
- If a separate Phase 4 identity child is required: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#EXECUTION_ID`.

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `client_id` | string | Validated tenant/client identifier. |
| `audit_id` | string | Validated audit identifier. |
| `audit_execution_id` | string | Durable opaque identifier generated/validated once; canonical Phase 4+ execution key. |
| `source` | string | `phase3_metadata` or `phase4_identity_assignment`. |
| `created_at` | string | UTC ISO-8601 timestamp. |

### Ownership Model

Scoped by `client_id` and `audit_id`. Internal backend access only.

### Lifecycle

Create once by conditional write if not already present. Never mutate raw evidence. Missing/unresolvable identity blocks aggregation.

## AggregationJob

### Purpose

Tracks each aggregation attempt, eligibility decision, duplicate detection, retry, failure, and completion.

### Primary Key

- `PK = CLIENT#{client_id}`
- `SK = AUDIT#{audit_id}#AGGJOB#{aggregation_job_id}`

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `client_id` | string | Validated client identifier. |
| `audit_id` | string | Validated audit identifier. |
| `audit_execution_id` | string/null | Resolved durable execution id; null only for validation failures before resolution. |
| `config_version` | string/null | Mandatory for processing; null only for failures before resolution. |
| `aggregation_job_id` | string | Safe generated/validated id. |
| `aggregation_version` | string | `agg_v1`. |
| `status` | string | `INTENT_RECORDED`, `INVOCATION_REQUESTED`, `INVOCATION_FAILED`, `STARTED`, `COMPLETED`, `FAILED`, `INELIGIBLE`, `DUPLICATE_COMPLETED`, `CONFLICT`. |
| `failure_category` | string/null | `EVIDENCE_PRODUCING`, `EVIDENCE_TRANSFORMING`, or null for successful/duplicate/ineligible outcomes. |
| `reason_code` | string/null | Controlled reason code only. |
| `started_at` / `completed_at` | string/null | UTC ISO-8601 timestamps. |
| `trigger_invocation_attempted_at` | string/null | UTC ISO-8601 timestamp for async invocation request from finalization. |
| `trigger_invocation_status` | string/null | `NOT_REQUESTED`, `REQUESTED`, `FAILED`, `ACCEPTED` when tracked separately from `status`. |
| `source_run_count` | number | Completed run metadata records considered. |
| `source_raw_result_count` | number | Raw result records aggregated. |
| `expected_execution_count` | number/null | Finalization `execution_count` used by the integrity gate. |
| `aggregate_record_count` | number | Aggregate records written. |
| `lineage_manifest_ref` | object/null | Bounded reference when created. |
| `aggregate_set_ref` | object/null | Canonical aggregate-set completion marker reference when completed. |
| `duplicate_of_aggregation_job_id` | string/null | Existing completed job if duplicate trigger is no-op. |
| `error_summary` | object/null | Sanitized reason code, component, and correlation id only. |

### Lifecycle

Created by conditional put. Updated only for job outcome metadata. Does not alter immutable aggregate records.

## AggregationJobIntent

### Purpose

Durable evidence that Phase 3 finalization requested Phase 4 aggregation before asynchronous invocation, preventing finalized audits from silently lacking aggregation lifecycle state if invocation fails.

### Primary Key

- Preferred: reuse `AggregationJob` item keyed by `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#AGGJOB#{aggregation_job_id}` with initial `status = INTENT_RECORDED`.
- If implementation separates intent from job attempts: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#AGGINTENT#{aggregation_job_id}`.

### Fields

Same safe identity fields as `AggregationJob`, plus finalization correlation id, intent timestamp, invocation status, and sanitized invocation failure reason code if async invocation fails.

### Ownership Model

Internal backend access only under the client/audit partition.

### Lifecycle

Created once during successful finalization before async invocation. Transitioned by finalization/aggregation orchestration to invocation and terminal job outcomes. Normal operators cannot create or mutate intent records.

## AggregateSetCompletion

### Purpose

Canonical immutable parent/completion record for a fully written aggregate set. This is the authoritative downstream-consumable aggregated evidence record for an audit execution/configuration/aggregation version. The audit aggregate remains the audit-level metrics record, not the sole completeness proof.

### Primary Key

- `PK = CLIENT#{client_id}`
- `SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#SET`

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `aggregate_type` | string | `aggregate_set_completion`. |
| `client_id`, `audit_id`, `audit_execution_id`, `config_version`, `aggregation_version`, `aggregation_job_id` | string | Required aggregate-set identity and writer job. |
| `completion_status` | string | Always `COMPLETE` for records that exist. No partial marker is written. |
| `created_at` | string | Same aggregate-set timestamp. |
| `expected_execution_count` | number | Finalization execution count validated by integrity gate. |
| `source_run_count` | number | Completed run metadata count validated by integrity gate. |
| `source_raw_result_count` | number | Raw evidence result count validated by integrity gate. |
| `aggregate_record_count` | number | Number of aggregate records in the set, excluding job and intent records. |
| `endpoint_aggregate_count` | number | Number of endpoint aggregate records. |
| `manifest_count` | number | Number of audit/endpoint lineage manifest records. |
| `audit_lineage_manifest_ref` | object | Audit-scope manifest reference. |
| `aggregate_set_hash` | string | Hash over canonical aggregate-set metadata and manifest hashes for deterministic completeness proof. |

### Ownership Model

Scoped by `client_id`, `audit_id`, `audit_execution_id`, `config_version`, and `aggregation_version`.

### Lifecycle

Write-once via conditional put, atomically with the complete manifest and aggregate record set. Downstream consumers must require this marker and must not infer completeness from child aggregates alone.

## AuditAggregate

### Purpose

One audit-level summary for a finalized audit execution, configuration version, and aggregation version.

### Primary Key

- `PK = CLIENT#{client_id}`
- `SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#AUDIT`

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `aggregate_type` | string | `audit`. |
| `aggregation_version` | string | `agg_v1`. |
| `lineage` | object | Bounded lineage metadata and manifest reference. |
| `request_counts` | object | `total`, `successful`, `failed`, `skipped`, `timeout`, `network_failure`. |
| `status_code_distribution` | map | String status code to count; no-response bucket `NO_STATUS`. |
| `execution_duration_ms` | number | `max(timestamp) - min(timestamp)` from valid included timestamps; `0` if fewer than two timestamps. |
| `latency_summary_ms` | object | `count`, `min`, `max`, `mean`, `median`, `p95`, `p99`; null stats when count is zero except `count=0`. |
| `endpoint_execution_counts` | map | Sanitized endpoint id to included raw result count. |
| `created_at` | string | Same as lineage aggregation timestamp. |

### Ownership Model

Scoped by `client_id`, `audit_id`, `audit_execution_id`, `config_version`, and `aggregation_version`.

### Lifecycle

Write-once via conditional put. Never updated or deleted by Phase 4.

## EndpointAggregate

### Purpose

One endpoint-level summary per represented sanitized endpoint.

### Primary Key

- `PK = CLIENT#{client_id}`
- `SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#ENDPOINT#{endpoint_id}`

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `aggregate_type` | string | `endpoint`. |
| `endpoint_id` | string | Opaque/sanitized safe identifier; never raw URL/query/header/payload/token content. |
| `execution_count` | number | Included raw records for endpoint. |
| `success_inputs` | object | `numerator = PASS count`; `denominator = execution_count - skipped_count`. For Raw Result Schema v1, skipped is always 0. |
| `latency_distribution_ms` | object | Deterministic bucket counts plus summary stats. |
| `timeout_count` | number | Count where approved raw failure classification is `TIMEOUT`. |
| `failure_classification_counts` | map | Failure bucket to count. |
| `http_response_distribution` | map | String status code to count; `NO_STATUS` for null/missing. |
| `lineage` | object | Bounded lineage metadata plus manifest reference scoped exactly to this endpoint's source refs. Audit-wide manifest refs are not sufficient for endpoint aggregates in Phase 4. |

### Lifecycle

Write-once via conditional put. Endpoint aggregate is omitted when no raw result records exist for that endpoint.

## FailureClassificationAggregate

### Purpose

Queryable failure classification counts for audit-level and endpoint-level consumers without root-cause inference.

### Primary Key

- Audit-level: `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#FAILURE_CLASSIFICATION`
- Endpoint-level if implemented for query ergonomics: `SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#ENDPOINT#{endpoint_id}#FAILURE_CLASSIFICATION`

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `aggregate_type` | string | `failure_classification`. |
| `scope` | string | `audit` or `endpoint`. |
| `endpoint_id` | string/null | Present only for endpoint scope. |
| `classification_counts` | map | Counts by approved raw `failure_type` plus deterministic buckets. |
| `lineage` | object | Bounded lineage metadata plus manifest reference. |

### Bucket Rules

- Approved preserved labels: `PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, `PAYLOAD_VALIDATION_ERROR`.
- Missing/null/empty/whitespace: `MISSING_FAILURE_CLASSIFICATION`.
- Non-empty unapproved value: `UNKNOWN_FAILURE_CLASSIFICATION`.
- No inferred/enriched/root-cause categories are allowed.

## EvidenceLineage

### Purpose

Trace every aggregate to exact source evidence and aggregation semantics while bounding aggregate item size and sensitive-data exposure.

### Fields

| Field | Type | Description |
| --- | --- | --- |
| `client_id` | string | Client id for standalone traceability. |
| `audit_id` | string | Audit id. |
| `audit_execution_id` | string | Durable first-class execution identity. Required. |
| `config_version` | string | Mandatory resolved configuration version. Required. |
| `aggregation_version` | string | `agg_v1`. |
| `aggregation_job_id` | string | Job that wrote this aggregate set. |
| `aggregation_timestamp` | string | UTC ISO-8601 timestamp fixed once per aggregate set. |
| `lineage_manifest_ref` | object | Bounded immutable reference to exact source refs. |
| `source_ref_count` | number | Count of canonical raw result refs in manifest scope. |
| `lineage_manifest_hash` | string | Hash of canonical manifest payload for integrity/reproducibility. |

No aggregate record stores unbounded inline `source_raw_result_refs` arrays.

## LineageManifest

### Purpose

Immutable sanitized manifest resolving to the exact canonical raw result references used by an aggregate set or endpoint scope.

### Primary Key / Location

Preferred DynamoDB child item when under item limit:
- `PK = CLIENT#{client_id}`
- `SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#LINEAGE#{manifest_scope}`

If the manifest would exceed safe DynamoDB item size, MVP behavior is controlled fail-before-write unless a separately reviewed S3 manifest design is implemented. Chunking is out of current scope.

### Manifest Fields

| Field | Type | Description |
| --- | --- | --- |
| `manifest_version` | string | `lineage_manifest_v1`. |
| `manifest_scope` | string | `audit` or `endpoint:{endpoint_id}`. |
| `client_id`, `audit_id`, `audit_execution_id`, `config_version`, `aggregation_version`, `aggregation_job_id` | string | Required lineage keys. |
| `created_at` | string | UTC ISO-8601 timestamp. |
| `source_ref_count` | number | Number of refs. |
| `source_raw_result_refs` | array | Canonically sorted sanitized refs only, bounded by item-size policy. |
| `manifest_hash` | string | Hash of canonical serialized manifest content. |

### Raw Result Reference Format

```json
{
  "raw_result_version": "v1",
  "run_id": "run_123",
  "raw_result_s3_key": "raw-results/clientA/auditA/run_123/results.json",
  "s3_version_id": "optional-version-id-if-available",
  "result_index": 0,
  "endpoint_id": "endpoint_health",
  "result_timestamp": "2026-06-07T12:00:00Z"
}
```

Stable reference identity is `{raw_result_s3_key, s3_version_id if present, run_id, result_index}`. If S3 version id is unavailable, `s3_version_id` is null and `object_version_lineage_available = false` is recorded in the manifest; this is a known limitation, not a reason to mutate raw evidence.

### Indexes / Constraints

- Existing table key pattern remains `PK = CLIENT#{client_id}`, `SK = ...`; no new table is required for MVP.
- Conditional writes and the `AggregateSetCompletion` marker enforce one complete aggregate set per `{client_id, audit_id, audit_execution_id, config_version, aggregation_version}`.
- Aggregate set identity includes `audit_execution_id` and `config_version`; duplicate detection must not collapse distinct executions/configurations.

### Migration Approach

- Add child sort-key prefixes for `#AGGJOB#`, `#AGGINTENT#` if separate from job, `#EXECUTION_ID`, `#LINEAGE#`, `#AGG#`, and aggregate-set completion `#SET` as needed.
- No raw evidence migration/backfill is required.
- No existing raw result S3 objects are rewritten to add execution/config/checksum fields.
- Existing audit listing must continue positive canonical-row filtering so aggregate child records are not returned as audits.

## 8. API Contracts

Phase 4 introduces no public/customer-facing HTTP API. Contracts are internal handler/function events only.

## Endpoint: Internal Event `aggregate_audit`

### Purpose

Start, retry, or no-op duplicate aggregation for one successfully finalized audit and aggregation version.

### Authentication / Authorization

Internal invocation only. Resource policies and IAM must allow invocation only from the approved Phase 3 finalization system role and Phase 4 aggregation worker role needed to resume a durable job intent. Customer, operator, CI/CD, public HTTP, general admin, and normal support roles must not invoke aggregation. Privileged administrative disaster-recovery invocation is explicitly deferred from Phase 4 implementation; adding it requires a separate reviewed operational contract, role, audit fields, and QA/security evidence.

### Request Parameters

None.

### Request Body

```json
{
  "event_type": "aggregate_audit",
  "schema_version": "phase4.aggregation_event.v1",
  "client_id": "clientA",
  "audit_id": "audit123",
  "aggregation_version": "agg_v1",
  "aggregation_job_id": "optional-safe-job-id"
}
```

### Response Body

```json
{
  "client_id": "clientA",
  "audit_id": "audit123",
  "audit_execution_id": "audexec_123",
  "config_version": "config_v1",
  "aggregation_version": "agg_v1",
  "aggregation_job_id": "aggjob_123",
  "status": "COMPLETED",
  "aggregate_record_count": 5,
  "source_raw_result_count": 42,
  "reason_code": null
}
```

### Success Status Codes

- Internal function success / Lambda `200` equivalent for controlled `COMPLETED`, `INELIGIBLE`, or `DUPLICATE_COMPLETED` outcomes.

### Error Status Codes

- `400` controlled validation error: invalid identifiers, unsupported aggregation version, unsafe event shape, duplicate raw references, missing `audit_execution_id`, missing `config_version`.
- `409` controlled conflict: active non-stale job already processing the same aggregate set.
- `500` controlled internal failure: raw evidence read/storage/calculation failure with sanitized job metadata.

### Validation Rules

- `client_id`, `audit_id`, `audit_execution_id`, `aggregation_job_id`, and endpoint identifiers must match the repository safe identifier pattern and be bounded to implementation-defined maximum length before use in keys or logs. Recommended max length: 128 characters for ids; endpoint aggregate key component should use a sanitized id or hash when longer.
- `aggregation_version` must be exactly `agg_v1` for initial implementation.
- Event must contain no raw URLs, query strings, headers, cookies, request/response bodies, payloads, tokens, credentials, PII, or raw evidence.
- Unknown event fields must be rejected or ignored only if guaranteed not to be logged/persisted; rejection is preferred.

### Side Effects

- Writes aggregation job metadata.
- Successful finalization writes an aggregation job intent before async invocation; the aggregation worker updates that durable lifecycle record.
- May write a Phase 4-owned audit execution identity metadata item if missing and safely assignable before processing.
- Reads audit/run metadata and S3 raw evidence.
- Writes immutable lineage manifests and aggregate child records when eligible and within limits.
- Writes the canonical aggregate-set completion marker only when the complete aggregate set is written.
- Does not transition audit lifecycle and does not trigger Phase 5/6/7.

### Idempotency / Duplicate Handling

- Unique aggregate set identity: `{client_id, audit_id, audit_execution_id, config_version, aggregation_version}`.
- If a completed aggregate set already exists, return/record `DUPLICATE_COMPLETED`; do not overwrite or append.
- A duplicate event with the same `aggregation_job_id` must be handled inside orchestration. If the job already reached `COMPLETED` or the aggregate-set completion marker exists, return/record `DUPLICATE_COMPLETED`. If the same job is currently active and non-stale, return/record controlled `CONFLICT`. If the same job is stale and no aggregate-set completion marker exists, retry may resume only according to deterministic stale-job rules and must not create duplicate records.
- If duplicate source raw result references are discovered within the input set, fail with `DUPLICATE_RAW_RESULT_REFERENCE` before lineage/aggregate creation. Heuristic deduplication is out of scope.
- If concurrent aggregate writes conflict after initial duplicate check, reload aggregate-set completeness by checking the canonical `AggregateSetCompletion` marker and required child counts. If complete, return/record `DUPLICATE_COMPLETED`; if incomplete or ambiguous, return/record controlled `CONFLICT` with no additional writes.

## 9. Frontend Impact

No frontend work is in scope.

### Components Affected

- None.

### API Integration

- None public/customer-facing.

### UI States

- None.

## 10. Backend Logic

### Responsibilities

- Validate internal aggregation events and identifiers.
- Enforce internal-only trigger controls.
- Persist durable aggregation job intent before async invocation from finalization.
- Resolve/persist durable `audit_execution_id` without mutating raw evidence.
- Validate mandatory `config_version` before processing.
- Claim/record aggregation attempts.
- Enforce finalized-audit eligibility and zero-execution exclusion.
- Discover and read raw evidence read-only.
- Enforce the evidence integrity validation gate, including count reconciliation, duplicate raw result references, lineage completeness, identity, config, and allowed raw input fields.
- Compute deterministic aggregate records.
- Persist immutable audit/endpoint lineage manifests, aggregate records, and aggregate-set completion marker with conditional writes.
- Classify failures durably as evidence-producing or evidence-transforming.
- Record sanitized outcomes and logs.

### Validation Flow

0. During successful Phase 3 finalization, persist `AggregationJobIntent`/pending job metadata before asynchronous invocation. If invocation fails, update the intent/job to `INVOCATION_FAILED` with failure category `EVIDENCE_TRANSFORMING` and reason `AGGREGATION_TRIGGER_INVOCATION_FAILED`; no aggregate records are created, and lifecycle evidence exists for deterministic worker retry/reconciliation.
1. Validate event schema, known fields, and safe identifiers.
2. Validate `aggregation_version = agg_v1`.
3. Claim, resume, or classify duplicate `aggregation_job_id` inside the orchestrator. Job-claim conditional conflicts must produce controlled `DUPLICATE_COMPLETED` or `CONFLICT` outcomes.
4. Load canonical audit metadata.
5. Resolve or assign durable `audit_execution_id` before raw evidence processing; fail closed if not resolvable/assignable.
6. Resolve `config_version` from canonical audit/finalization metadata; fail closed with `MISSING_CONFIG_VERSION` if absent/invalid.
7. Validate eligibility: `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, and successful finalization completion transition.
8. Check whether the aggregate set already exists for `{client_id, audit_id, audit_execution_id, config_version, aggregation_version}`.
9. Query completed run metadata and read Raw Result Schema v1 envelopes.
10. Build canonical allowed-field raw input DTOs and canonical source refs.
11. Execute `EvidenceIntegrityValidator`. Reject incomplete finalization metadata, expected/completed/raw count mismatch, unreadable/missing raw evidence, duplicate source refs, missing `audit_execution_id`, missing `config_version`, and lineage completeness gaps before aggregate computation or any manifest/aggregate writes.
12. Build audit-scope and endpoint-scope lineage manifest payloads in memory. Every endpoint aggregate must have a non-empty endpoint-scoped manifest/manifest entry containing exactly the refs used for that endpoint.
13. Estimate aggregate, manifest, transaction, and aggregate-set completion marker sizes; if limits would be exceeded, fail before writes with `AGGREGATE_SET_TOO_LARGE` or `LINEAGE_MANIFEST_TOO_LARGE`.
14. Compute aggregates from canonically sorted records.
15. Transactionally/atomically write lineage manifest(s), aggregate records, canonical `AggregateSetCompletion`, and final job completion when within limits. The completion marker is written last within the atomic set semantics and never exists for partial aggregate sets.
16. On write conflict, reload aggregate-set completeness. If complete, mark `DUPLICATE_COMPLETED`; if incomplete/ambiguous, mark `CONFLICT`.
17. Mark job completed, duplicate, ineligible, conflict, or failed with sanitized metadata and durable failure category.

### Business Rules

- Total request count: count included raw result records after validation.
- Successful request count: count included records whose raw execution classification is `PASS`.
- Failed request count: count included records whose raw execution classification is not `PASS`, including `PAYLOAD_VALIDATION_ERROR`, because Raw Result Schema v1 has no explicit skipped field.
- Skipped request count for `agg_v1`: count only explicit skipped indicators. Raw Result Schema v1 has none; therefore `skipped_requests = 0` for all `agg_v1` aggregates. Do not infer skipped from `PAYLOAD_VALIDATION_ERROR`, missing latency, missing HTTP status, payload metadata, or other failure fields.
- Timeout count: count approved raw classification `TIMEOUT` only.
- Network failure count: count approved raw classification `CONNECTION_ERROR` only.
- HTTP status distribution: count integer `status_code` values as strings; null/missing as `NO_STATUS`.
- Latency inputs: include only numeric `duration_ms >= 0`; exclude null/missing/non-numeric/negative values and expose `latency_summary_ms.count`.
- Latency stats for `agg_v1`: sort ascending. `min`/`max` are exact numeric values rounded using the canonical rule below. `mean = sum / count`. `median` is middle value for odd count and average of the two middle values for even count. `p95` and `p99` use nearest-rank percentile: rank `ceil(p/100 * count)`, 1-indexed, clamped to `[1, count]`.
- Decimal precision/rounding for `agg_v1`: emit numeric latency statistics in milliseconds rounded to 3 decimal places using half-up rounding; omit trailing insignificant zeros only if existing JSON serialization does so consistently. Counts remain integers.
- Endpoint execution count: count raw records after endpoint normalization.
- Execution duration: use valid raw record timestamps; duration is max minus min in milliseconds. If fewer than two valid timestamps, duration is `0`.
- Zero-execution audits: audits with `finalization.execution_count = 0`, `finalization.zero_execution = true`, execution-failed finalization, or no completed execution evidence are not eligible; no zero-count aggregate is created.
- Integrity gate count rule: `finalization.execution_count` must equal both the persisted completed run metadata count and the loaded raw result evidence count used for aggregation. Any mismatch is an evidence-producing failure and no aggregate or lineage manifest is created.

### Strict Aggregate Input Allowlist

Aggregation may read only these raw/result metadata fields into the canonical calculation DTO:
- `raw_result_version`
- `run_id`
- `raw_result_s3_key`
- optional `s3_version_id`
- derived `result_index`
- validated/sanitized `endpoint_id`
- execution `timestamp`
- numeric `duration_ms`
- integer `status_code`
- execution-generated `failure_type` / outcome category

Forbidden in aggregate DTOs, aggregate records, manifests, job metadata, errors, and logs:
- raw URLs, query strings, headers, cookies, request bodies, response bodies, payloads, payload fragments, tokens, secrets, credentials, PII, tenant-sensitive content, and any raw endpoint content not already validated as a safe opaque identifier.

### Endpoint Identifier Handling

- Validate endpoint identifiers against the existing safe identifier syntax before use in keys/logs.
- Bound endpoint id length. Recommended maximum: 128 characters in record body; if key component would exceed safe length, use deterministic sanitized representation such as `endpoint_hash_<sha256-prefix>` while retaining no raw unsafe endpoint content.
- Existing `endpoint_id` syntax is safe but not semantically guaranteed opaque; therefore Phase 4 must treat it as potentially sensitive unless it passes allowlist validation and contains no URL/query/header/payload/token patterns.
- Missing or unsafe endpoint id maps to controlled placeholder `unknown` or deterministic sanitized hash only from approved non-sensitive source; do not log rejected raw value.

### Persistence Flow

- Use existing metadata table child records.
- Successful finalization puts a durable job intent first, before async invocation.
- Aggregation orchestration claims/resumes the job and builds all aggregate, manifest, and completion marker records in memory before writes.
- MVP writes only when the complete manifest+aggregate set fits approved DynamoDB transaction/item-size limits.
- If the set would exceed limits, fail before manifest/aggregate/completion-marker writes. Do not implement deterministic chunks without a separately reviewed design.
- Every manifest and aggregate record uses conditional put `attribute_not_exists(PK) AND attribute_not_exists(SK)`.
- The `AggregateSetCompletion` marker is now in current scope and is the canonical proof of completeness. Write it atomically with the complete aggregate set; do not write a partial marker.
- On write conflict, reload only sanitized aggregate-set metadata and the completion marker; if complete and child counts match marker metadata, record duplicate outcome; otherwise fail with controlled conflict. Do not treat partial aggregate records as complete.

### Error Handling

- Ineligible audits: mark job `INELIGIBLE`, log controlled reason, create no aggregates.
- Missing `audit_execution_id` or `config_version`: controlled validation failure before raw evidence processing and no aggregates.
- Integrity gate failures: mark job `FAILED` with `failure_category = EVIDENCE_PRODUCING`, controlled reason code, count diagnostics when safe, and no manifest/aggregate/completion marker.
- Duplicate completed aggregate set: mark job `DUPLICATE_COMPLETED`, no aggregate writes.
- Duplicate raw result reference: mark job `FAILED` or validation-failed with `DUPLICATE_RAW_RESULT_REFERENCE`, no manifest/aggregate writes.
- Oversized aggregate/manifest: mark job `FAILED` with `AGGREGATE_SET_TOO_LARGE` or `LINEAGE_MANIFEST_TOO_LARGE`, no manifest/aggregate writes.
- Raw evidence read/schema failure: mark job `FAILED`; do not mutate raw evidence.
- Evidence-transforming failures such as aggregation timeout before writes, transient storage/worker failure, trigger invocation failure after intent persistence, or infrastructure throttling: mark job `FAILED` or `INVOCATION_FAILED` with `failure_category = EVIDENCE_TRANSFORMING`; retry may occur deterministically without rerunning the audit if no aggregate-set completion marker exists.
- Storage conflicts: reload aggregate-set completion. Complete sets produce `DUPLICATE_COMPLETED`; incomplete/ambiguous sets produce `CONFLICT` with `failure_category = EVIDENCE_TRANSFORMING` and no further writes.
- Error summaries include only reason code, component name, safe correlation/job ids, and count fields. No exception text containing raw input values unless sanitized.

### Durable Failure Taxonomy

| Failure category | Examples | Outcome | Retry / recovery rule |
| --- | --- | --- | --- |
| `EVIDENCE_PRODUCING` | Missing raw evidence, expected/completed/raw count mismatch, incomplete execution, lineage corruption, duplicate source references, unresolved `audit_execution_id`, unresolved `config_version` after approved resolution path. | Aggregation blocked; no aggregate, lineage manifest, or aggregate-set completion marker. | Do not retry aggregation against the same evidence expecting success. Requires a new audit execution or upstream evidence repair only through approved governance. |
| `EVIDENCE_TRANSFORMING` | Aggregation timeout before writes, transient S3/DynamoDB throttling, storage conflict, worker crash, async trigger invocation failure after job intent persistence, transaction contention. | No downstream-consumable aggregate unless a complete aggregate-set marker already exists. | Deterministic retry may proceed without rerunning the audit when no complete aggregate set exists and stale/claim rules permit. |

Controlled reason codes must be bounded enums. Required additions include: `EXECUTION_COUNT_MISMATCH_COMPLETED_RUNS`, `EXECUTION_COUNT_MISMATCH_RAW_RESULTS`, `MISSING_RAW_EVIDENCE`, `INCOMPLETE_EXECUTION_EVIDENCE`, `LINEAGE_INCOMPLETE`, `LINEAGE_CORRUPT`, `DUPLICATE_RAW_RESULT_REFERENCE`, `MISSING_AUDIT_EXECUTION_ID`, `MISSING_CONFIG_VERSION`, `AGGREGATION_TRIGGER_INVOCATION_FAILED`, `AGGREGATION_TIMEOUT`, `TRANSIENT_STORAGE_FAILURE`, `WORKER_FAILURE`, `AGGREGATE_WRITE_CONFLICT`, and `AGGREGATE_SET_INCOMPLETE_CONFLICT`.

## 11. File Structure

Suggested additions only; source code is not implemented by this design.

```text
src/release_confidence_platform/aggregation/
  __init__.py
  constants.py
  events.py
  eligibility.py
  identity.py
  integrity.py
  engine.py
  lineage.py
  models.py
  orchestrator.py
  repository.py

apps/backend/handlers/
  aggregation_handler.py

tests/unit/aggregation/
  test_eligibility.py
  test_identity_and_config.py
  test_engine_counts.py
  test_latency_stats.py
  test_lineage_manifest.py
  test_idempotency.py
  test_security_sanitization.py
```

## 12. Security

- Authentication: internal AWS IAM invocation only; no public/customer/operator API.
- Authorization: only the approved Phase 3 finalization/system role and Phase 4 worker role needed to process durable intents may invoke normal aggregation. Break-glass manual invocation is deferred from Phase 4; no normal operator, general admin, customer, or support role may manually trigger aggregation.
- IAM table permissions: aggregation role may read canonical audit/run metadata and conditionally put/update only Phase 4-owned job, identity, lineage, and aggregate child-key prefixes. It must not have broad update permission for raw run evidence fields except the explicitly approved identity propagation metadata path if used.
- IAM S3 permissions: aggregation role has `s3:GetObject` and, if bucket versioning is enabled, `s3:GetObjectVersion` for raw-results prefixes. It has no `PutObject`, `DeleteObject`, or lifecycle mutation permissions on raw-results. If S3 lineage manifests are later approved, use a separate manifest prefix with write-once controls, not raw-results.
- Input validation: validate and bound every identifier before key construction or logging.
- Sensitive data: strict allowlist applies to aggregate records, manifests, jobs, errors, and logs. Do not persist/log headers, cookies, bodies, payloads, queries, raw URLs, tokens, credentials, PII, tenant-sensitive content, or raw unsafe endpoint content.
- Misuse prevention: handler must reject unexpected fields and must not be routable from customer-facing endpoints or general operator tooling.

## 13. Reliability

- Determinism: stable sorting by raw reference identity; deterministic nearest-rank percentile algorithm; canonical 3-decimal half-up rounding; sorted map keys where deterministic serialization is required.
- Retry safety: conditional job, identity, manifest, aggregate, and aggregate-set completion writes prevent duplicates; raw reads are side-effect free.
- Concurrency: concurrent triggers race on aggregate-set conditional writes; one succeeds, others reload completion state and become duplicate/conflict outcomes.
- Fail-before-write: integrity gate failures, duplicate raw refs, missing identity/config, ineligible audits, and oversized manifest/aggregate sets fail before aggregate/manifest/completion marker creation.
- Trigger durability: finalization persists job intent before async invocation so invocation failure leaves auditable lifecycle evidence and a deterministic recovery artifact.
- Timeouts: raw evidence reads should paginate with bounded page size and stop before writes if limits are exceeded.
- Observability: sanitized logs/metrics for `aggregation_intent_recorded`, `aggregation_trigger_invocation_failed`, `aggregation_job_started`, `aggregation_integrity_gate_failed`, `aggregation_ineligible`, `aggregation_duplicate_completed`, `aggregation_conflict`, `raw_evidence_loaded`, `lineage_manifest_write_started`, `aggregate_write_started`, `aggregate_set_completed`, and `aggregation_failed`.
- S3 versioning limitation: if raw-result object version id is unavailable, record `object_version_lineage_available = false` in the manifest and rely on immutable key/run/index conventions; do not claim version-level proof.
- Rollback: do not delete aggregates. Failed jobs may be retried with a new job id; complete aggregate sets cause duplicate no-op handling.

## 14. Dependencies

- Phase 1 Raw Result Schema v1 and S3 raw result persistence.
- Phase 1/3 run metadata at `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}#RUN#{run_id}`.
- Phase 3 audit metadata at `PK = CLIENT#{client_id}`, `SK = AUDIT#{audit_id}`.
- Phase 3 finalization semantics where successful finalization is indicated by `lifecycle_state = COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, and completion transition.
- Existing identifier validators, sanitization utilities, DynamoDB/S3 wrappers, and IAM deployment mechanisms.

## 15. Assumptions

### Resolved Architecture Decisions

- `audit_execution_id` is a new durable first-class canonical execution identifier for Phase 4+; `run_id` is not the long-term primary lineage key.
- `config_version` is mandatory; missing/invalid values fail closed before aggregate creation.
- Raw Result Schema v1 has no explicit skipped field; `agg_v1` emits `skipped_requests = 0` and treats `PAYLOAD_VALIDATION_ERROR` as failed.
- Zero-execution and execution-failed audits are ineligible; no zero-count aggregate is created.
- Duplicate raw result references fail validation before manifest/aggregate creation.
- MVP oversized behavior is controlled fail-before-write; chunking is out of scope.
- Lineage uses bounded immutable audit-scope and endpoint-scope manifests/references, not unbounded arrays on aggregate records.
- The canonical downstream-consumable artifact is the `AggregateSetCompletion` marker plus its referenced immutable aggregate set; child aggregate records alone are not sufficient completeness proof.
- Aggregation is system-managed after successful finalization; privileged administrative DR invocation/reaggregation is deferred from Phase 4 and normal operators cannot manually trigger aggregation.
- Durable job intent before async invocation is selected over adding a new durable queue because it aligns with the existing metadata-table/job orchestration pattern and avoids introducing new infrastructure during remediation. A queue/DLQ design remains a future option if operational needs grow.

### Technical Assumptions Requiring Confirmation

- The implementation team can safely add Phase 4 child key prefixes and optional identity metadata without breaking existing audit queries.
- Existing deployment tooling can express the IAM restrictions above precisely enough for least privilege.
- If Phase 4 must assign `audit_execution_id`, the approved identifier generator and conditional write path will be available in backend shared utilities.
- Existing finalization code can persist a Phase 4 job intent in the metadata table before async invocation without altering product-facing finalization behavior.

## 16. Risks / Open Questions

- **S3 versioning limitation:** absence of `s3_version_id` weakens object-version lineage proof; manifest must explicitly record this limitation.
- **IAM precision risk:** broad table permissions could allow accidental canonical/raw metadata mutation; implementation must scope role permissions and code paths tightly.
- **Manifest size risk:** large audits may exceed DynamoDB item/transaction limits; current MVP fails before writes until a chunked/S3 manifest design is separately reviewed.
- **Endpoint-scoped manifest count risk:** endpoint exact-lineage records increase manifest count and transaction pressure; MVP still fails before writes rather than producing incomplete lineage.
- **Endpoint semantic opacity risk:** syntactically safe endpoint ids may still encode sensitive meaning; sanitization and no-raw logging must be tested.
- **Deferred DR consequence:** if automatic intent retry/reconciliation cannot recover an evidence-transforming failure, Phase 4 has no normal manual recovery path; recovery requires engineering/governance intervention until a privileged DR workflow is separately approved.
- **Review status:** prior architecture/security review was blocked; this design should be rerun through architecture and security review before implementation.

## 17. Implementation Notes

Backend handoff tasks:

1. Persist a durable aggregation job intent during successful finalization before async invocation; record `INVOCATION_FAILED` if invocation fails.
2. Implement `audit_execution_id` resolver/persistence before raw evidence processing; never use `run_id` as aggregate-set identity.
3. Enforce mandatory `config_version` validation and persist it on jobs, manifests, aggregates, and aggregate-set completion marker.
4. Implement eligibility exactly: `COMPLETED`, `finalization.execution_count > 0`, `finalization.zero_execution = false`, finalization completion transition; reject zero-execution/execution-failed audits.
5. Implement `EvidenceIntegrityValidator` as a hard gate before aggregate computation or writes. It must reconcile expected execution count with completed run count and loaded raw evidence count, validate no duplicate raw source refs, validate identity/config, and validate lineage completeness.
6. Implement durable `failure_category` and bounded reason codes separating `EVIDENCE_PRODUCING` from `EVIDENCE_TRANSFORMING` failures.
7. Implement `agg_v1` skipped semantics: no explicit Raw Result Schema v1 skipped field means skipped count is always `0`; `PAYLOAD_VALIDATION_ERROR` counts as failed.
8. Build canonical source refs and fail with `DUPLICATE_RAW_RESULT_REFERENCE` before writes if duplicates are present.
9. Build immutable bounded audit-scope and endpoint-scope lineage manifest(s); endpoint aggregates must reference exact endpoint-scoped source sets.
10. Add and write the canonical `AggregateSetCompletion` marker atomically with the complete aggregate set; downstream reads must require it.
11. Handle same-job duplicate events and concurrent write conflicts inside orchestration, returning `DUPLICATE_COMPLETED` or controlled `CONFLICT` with aggregate-set completeness reload.
12. Fail before manifest/aggregate/completion-marker writes when DynamoDB item/transaction limits would be exceeded; do not add chunking without a new reviewed design.
13. Implement latency percentiles and 3-decimal half-up rounding exactly as specified.
14. Enforce raw-field allowlist and endpoint identifier sanitization in DTO construction, persistence, and logs.
15. Add IAM/resource policy changes for internal trigger source, Phase 4 worker intent processing, read-only raw S3 access, and write-limited Phase 4 metadata prefixes; do not add normal manual/DR invocation roles in Phase 4.
16. Add tests for integrity gate count mismatches, partial/missing evidence, failure taxonomy, endpoint-scoped lineage, same-job duplicates, concurrent conflict reload, trigger invocation failure lifecycle evidence, security sanitization, internal trigger rejection, missing identity/config, duplicate raw refs, oversized fail-before-write, S3 version-id absent manifest flag, and deterministic rounding.

QA verification expectations after backend remediation:

- Existing Phase 4 QA approval is stale; rerun targeted blocker coverage and regression tests.
- Required negative cases must assert no aggregate records, no lineage manifests, and no aggregate-set completion marker are created for evidence-producing failures.
- Required idempotency cases must assert no duplicate aggregates and no ambiguous failed state for safe duplicate events.
- Required lineage cases must prove endpoint aggregate lineage resolves only to that endpoint's exact canonical source refs.
- Required trigger recovery cases must prove finalized audits have durable aggregation lifecycle evidence even if async invocation fails.
