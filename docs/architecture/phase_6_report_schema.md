# Phase 6 — Deterministic Reporting Schema

## 1. Overview

Phase 6 introduces exactly two new DynamoDB record types to the existing platform metadata table:

- **ReportJob** — one record per report generation invocation; immutable at terminal state; functions as an audit log
- **ReportMetadata** — one record per `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version, report_version)` combination; reflects current generation state; updatable only via `--force` re-generation

All per-section report content — executive summary, per-endpoint analysis, methodology disclosure, evidence lineage — lives exclusively in the S3 report artifact (the serialized `ReleaseConfidenceReport` DTO). DynamoDB holds only status, summary, and artifact reference metadata. This keeps DynamoDB lean: at most two Phase 6 records are written per `(audit_execution_id, report_version)` combination per generation event, regardless of endpoint count.

Phase 6 never mutates any Phase 5 DynamoDB record. All Phase 6 write paths target Phase 6-exclusive sort key namespaces. This boundary is unconditional and is enforced by `repository.py` write methods.

This schema document is the authoritative reference for:

- Phase 6.3–6.4 implementation (`repository.py` read and write paths)
- Phase 6.7 Engineering Retrieval CLI DynamoDB access patterns
- Phase 7 consumer contract DynamoDB access patterns (`docs/architecture/phase_6_phase7_consumer_contract.md`)
- Future schema version additions

The schema is immutable after publication for `report_version = report_v1`. All changes require a new `report_version` per Section 8.

---

## 2. Table Reference

Phase 6 records use the existing platform metadata DynamoDB table. No new table is required.

| Property | Value |
| --- | --- |
| Table name | `release-confidence-platform-${stage}-metadata` |
| Supported stages | `dev`, `staging`, `prod` |
| Primary key type | Composite (PK + SK) |
| PK attribute | `PK` (String) |
| SK attribute | `SK` (String) |

Phase 6 records share this table with all Phase 1–5 records. Sort key namespacing ensures zero overlap between Phase 5 and Phase 6 record types. The `#RPT#` segment is reserved exclusively for Phase 6+ records.

---

## 3. PK/SK Patterns

### 3.1 ReportJob

**PK:**
```
CLIENT#{client_id}
```

**SK:**
```
AUDIT#{audit_id}#RPTJOB#{report_job_id}
```

**Example:**
```
PK = CLIENT#client_abc
SK = AUDIT#audit_xyz#RPTJOB#rptjob_4f5a6b7c8d9e0a1b2c3d4e5f6a7b8c9d
```

One record per invocation. Multiple `ReportJob` records may exist under the same `audit_id` — one per generation event, including force re-generations. They are distinguished by `report_job_id`. The `RPTJOB#` segment does not appear in any Phase 5 sort key. No Phase 5 query pattern returns `ReportJob` records.

---

### 3.2 ReportMetadata

**PK:**
```
CLIENT#{client_id}
```

**SK:**
```
AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#META
```

**Example:**
```
PK = CLIENT#client_abc
SK = AUDIT#audit_xyz#EXEC#audexec_0b1c2d3e#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#RPT#report_v1#META
```

Exactly one record per `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version, report_version)` combination. This record is the Phase 7 prerequisite gate anchor and the canonical current-state summary for a given report version. The `#RPT#` segment ensures Phase 5 query patterns (`SK begins_with AUDIT#{id}#EXEC#{id}#...#INTEL#{v}#META`) never return this record.

---

## 4. Record Schemas

### 4.1 ReportJob

**Purpose:** Tracks each report generation invocation — status, timing, pipeline outcome, and S3 artifact reference. Analogous to `IntelligenceJob` in Phase 5. One record per invocation. Immutable once `status` reaches `COMPLETE` or `FAILED`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | `AUDIT#{audit_id}#RPTJOB#{report_job_id}` |
| `record_type` | String | Yes | `report_job` |
| `report_version` | String | Yes | `report_v1` |
| `report_job_id` | String | Yes | Opaque generated job identifier (prefix: `rptjob_`) |
| `report_id` | String | No | Canonical report identifier (prefix: `report_`); present when `status = COMPLETE` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Yes | Durable execution identity |
| `config_version` | String | Yes | Configuration version |
| `aggregation_version` | String | Yes | Phase 4 aggregation version (carried from Phase 5 artifact) |
| `intelligence_version` | String | Yes | Phase 5 intelligence version consumed (e.g., `intel_v1`) |
| `intelligence_job_id` | String | Yes | Phase 5 job ID of the consumed COMPLETE intelligence artifact |
| `status` | String | Yes | `PENDING` \| `IN_PROGRESS` \| `COMPLETE` \| `FAILED` |
| `composite_score` | Number | No | Audit composite score carried from Phase 5; present when `status = COMPLETE` |
| `score_label` | String | No | Phase 5 confidence label carried verbatim; present when `status = COMPLETE` |
| `endpoint_count` | Number | No | Endpoint count carried from Phase 5; present when `status = COMPLETE` |
| `s3_artifact_ref` | String | No | S3 key of the written Phase 6 report artifact; present when `status = COMPLETE` |
| `aggregate_set_hash` | String | No | Phase 4 lineage hash carried from Phase 5; immutable lineage link |
| `is_force_regeneration` | Boolean | No | `true` if invoked with `--force`; absent otherwise |
| `created_at` | String | Yes | UTC ISO-8601 creation timestamp |
| `updated_at` | String | Yes | UTC ISO-8601 last status update timestamp |
| `completed_at` | String | No | UTC ISO-8601 completion timestamp; present when `status = COMPLETE` or `FAILED` |
| `failure_stage` | String | No | Pipeline stage where failure occurred; present when `status = FAILED` |
| `failure_reason` | String | No | Controlled failure reason code; present when `status = FAILED` |

**Ownership:** Scoped to `client_id`. Written once per invocation via conditional write. Never mutated after `status` reaches `COMPLETE` or `FAILED`.

---

### 4.2 ReportMetadata

**Purpose:** Current-state report summary for a specific `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version, report_version)` combination. Serves as the Phase 7 prerequisite gate anchor and the retrieval CLI fast-path for status, score, and S3 artifact reference. Updated on each status transition and force re-generation.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | `AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#META` |
| `record_type` | String | Yes | `report_metadata` |
| `report_version` | String | Yes | `report_v1` |
| `report_job_id` | String | Yes | Job ID of the most recent generation event; reference to active `ReportJob` |
| `report_id` | String | No | Canonical report identifier; present when `status = COMPLETE` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Yes | Durable execution identity |
| `config_version` | String | Yes | Configuration version |
| `aggregation_version` | String | Yes | Phase 4 aggregation version |
| `intelligence_version` | String | Yes | Phase 5 intelligence version consumed |
| `status` | String | Yes | `PENDING` \| `IN_PROGRESS` \| `COMPLETE` \| `FAILED` |
| `composite_score` | Number | No | Audit composite score carried from Phase 5; present when `status = COMPLETE` |
| `score_label` | String | No | Phase 5 confidence label; present when `status = COMPLETE`; stable for Phase 7 consumption |
| `endpoint_count` | Number | No | Endpoint count; present when `status = COMPLETE` |
| `s3_artifact_ref` | String | No | S3 key of the latest complete Phase 6 report artifact; present when `status = COMPLETE` |
| `aggregate_set_hash` | String | No | Phase 4 lineage hash; immutable lineage link |
| `generation_count` | Number | Yes | Count of generation events including force re-generations; starts at `1` |
| `created_at` | String | Yes | UTC ISO-8601 timestamp of first generation invocation; never updated |
| `updated_at` | String | Yes | UTC ISO-8601 timestamp of most recent state update |
| `completed_at` | String | No | UTC ISO-8601 completion timestamp of most recent successful generation |
| `failure_reason` | String | No | Controlled failure reason code; present when `status = FAILED` |

**Ownership:** One record per `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version, report_version)`. Written on first invocation via conditional put; updated on each status transition and force re-generation via update item.

---

### 4.3 `score_label` Bounded Value Set

`score_label` in Phase 6 DynamoDB records is a verbatim pass-through of the Phase 5 `score_label` value. Phase 6 does not compute or derive `score_label`. The bounded value set is defined by Phase 5 and is carried into Phase 6 records for summary convenience and Phase 7 prerequisite gate use.

| Label | Condition | Meaning |
| --- | --- | --- |
| `HIGH_CONFIDENCE` | Phase 5: `composite_score >= 0.80` | Reliability indicators are strong |
| `MODERATE_CONFIDENCE` | Phase 5: `0.50 <= composite_score < 0.80` | Reliability indicators are mixed |
| `LOW_CONFIDENCE` | Phase 5: `composite_score < 0.50` | Reliability indicators indicate risk |

Phase 6 must not alter or substitute the `score_label` value on any DynamoDB record or DTO field.

---

## 5. Record Lifecycle

### 5.1 ReportJob Status Transitions

```
[invocation start]
       │
       ▼
   PENDING
       │
  [DTO construction begins]
       │
       ▼
  IN_PROGRESS
   /         \
[success]  [failure]
   │             │
   ▼             ▼
COMPLETE      FAILED
```

- `PENDING` is written at invocation start. A new `report_job_id` is always generated for each invocation.
- `IN_PROGRESS` is written once the Phase 5 S3 intelligence artifact is loaded and DTO construction begins.
- `COMPLETE` is written after S3 report artifact write and DynamoDB completion update both succeed. At this point `composite_score`, `score_label`, `endpoint_count`, `s3_artifact_ref`, `report_id`, and `completed_at` are set.
- `FAILED` is written if any pipeline step from Phase 5 artifact read through S3 write raises an exception. `failure_stage` and `failure_reason` are populated.
- Once `COMPLETE` or `FAILED`, the record is never mutated.

### 5.2 ReportMetadata Status Transitions

```
[first invocation]
       │
  created PENDING
       │
  [status mirrors ReportJob]
       │
  IN_PROGRESS
   /         \
[success]  [failure]
   │             │
   ▼             ▼
COMPLETE      FAILED
```

On force re-generation from `COMPLETE`:

```
COMPLETE
   │
  [--force invoked, new report_job_id generated]
   │
   ▼
PENDING (updated in place)
   │
  [status mirrors new ReportJob transitions]
```

- Created on the first invocation with `status = PENDING` and `generation_count = 1`.
- Updated alongside the corresponding `ReportJob` on each status transition.
- On force re-generation: `report_job_id`, `report_id`, `composite_score`, `score_label`, `endpoint_count`, `s3_artifact_ref`, `completed_at`, `updated_at`, and `generation_count` are updated. `created_at` is never updated.

---

## 6. Access Patterns

### 6.1 Phase 6 Write Patterns

| Operation | Record | Write Type | Sort Key |
| --- | --- | --- | --- |
| Create report job | `ReportJob` | Conditional put (new `report_job_id`) | `AUDIT#{audit_id}#RPTJOB#{report_job_id}` |
| Create report metadata | `ReportMetadata` | Conditional put (first generation for combination) | `AUDIT#{audit_id}#EXEC#{...}#RPT#{report_version}#META` |
| Update job to IN_PROGRESS | `ReportJob` | Update item | Same SK as create |
| Update metadata to IN_PROGRESS | `ReportMetadata` | Update item | Same SK as create |
| Update job to COMPLETE | `ReportJob` | Update item | Same SK as create |
| Update metadata to COMPLETE | `ReportMetadata` | Update item | Same SK as create |
| Update job to FAILED | `ReportJob` | Update item | Same SK as create |
| Update metadata to FAILED | `ReportMetadata` | Update item | Same SK as create |

### 6.2 Phase 6 Read Patterns

**Prerequisite gate (reads Phase 5 IntelligenceMetadata before any write):**
```
GetItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#META
```

Phase 6 verifies `status = COMPLETE` on this record. If absent or `status != COMPLETE`, Phase 6 aborts with `INTELLIGENCE_NOT_COMPLETE`.

**Idempotency check (reads ReportMetadata before any write):**
```
GetItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#META
```

### 6.3 Phase 7 Read Pattern

Phase 7 uses a single DynamoDB read:

```
GetItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#META
```

Phase 7 must verify `status = COMPLETE` on the returned record. Full Phase 7 access pattern constraints are defined in `docs/architecture/phase_6_phase7_consumer_contract.md`.

### 6.4 Retrieval CLI Read Patterns

| Command Category | DynamoDB Read | S3 Read |
| --- | --- | --- |
| `retrieve report-status` | `GetItem` on `ReportMetadata` SK | None |
| `retrieve report-summary`, `report-endpoints`, `report-methodology`, `report-lineage`, `report-json`, `report-markdown` | `GetItem` on `ReportMetadata` SK (for `s3_artifact_ref`) | Full artifact read via `publisher.py` |

---

## 7. S3 Artifact Key Structure

Phase 6 report artifacts are written to the existing platform S3 bucket under the exclusive `reports/` key prefix:

```
reports/{client_id}/{audit_id}/{audit_execution_id}/{aggregation_version}/{intelligence_version}/{report_version}/{report_job_id}/artifact.json
```

**Example:**
```
reports/client_abc/audit_xyz/audexec_0b1c2d3e/agg_v1/intel_v1/report_v1/rptjob_4f5a6b7c8d9e0a1b2c3d4e5f6a7b8c9d/artifact.json
```

**Key properties:**
- `report_job_id` path segment ensures each generation produces a unique, addressable S3 key.
- Force re-generation produces a new key (new `report_job_id`). The previous artifact is preserved at its original key and is not deleted.
- `ReportMetadata.s3_artifact_ref` and `ReportJob.s3_artifact_ref` store the complete S3 key string.
- The `reports/` prefix does not overlap with Phase 5's `intelligence/` prefix or Phase 1/2's `raw-results/` prefix.
- Phase 7 must use `ReportMetadata.s3_artifact_ref` to locate the artifact. Phase 7 must not construct or infer the S3 key independently.

The artifact is an immutable JSON document (the serialized `ReleaseConfidenceReport` DTO) written once per generation. Its content is defined in `docs/architecture/phase_6_deterministic_reporting_technical_design.md` Section 5.

---

## 8. Naming and Versioning Constraints

### 8.1 Identifier Format

| Identifier | Format | Example |
| --- | --- | --- |
| `report_job_id` | `rptjob_{uuid4().hex}` | `rptjob_4f5a6b7c8d9e0a1b2c3d4e5f6a7b8c9d` |
| `report_id` | `report_{uuid4().hex}` | `report_9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d` |
| `REPORT_VERSION` constant | `report_v{n}` | `report_v1` |

The `rptjob_` prefix is analogous to `intjob_` in Phase 5 and `aggjob_` in Phase 4. All identifier components used in PK, SK, or S3 key construction must be validated through the existing `validate_identifier` utilities before use.

### 8.2 Schema Versioning Rules

1. This schema is immutable after publication for `report_version = report_v1`.
2. Field additions to `ReportJob` or `ReportMetadata` require a new `report_version` (e.g., `report_v2`).
3. Field renames, removals, or type changes require a new `report_version` and explicit consumer migration documentation.
4. New `report_version` records are written as new `ReportMetadata` items at distinct sort keys (the `RPT#{report_version}` segment changes). Existing `report_v1` records are never modified.
5. The `report_version` field on every Phase 6 record is the canonical version identifier.

### 8.3 Sensitive Data Exclusion

No field in any Phase 6 DynamoDB record may contain:
- Raw request or response bodies.
- HTTP headers, cookies, tokens, credentials, secrets, or PII.
- Raw URLs, query strings, or path parameters.
- Payload fragments or tenant-sensitive raw content.

`endpoint_id` values in Phase 6 records are inherited from Phase 5 sanitized identifiers and must not be un-sanitized or expanded. The `s3_artifact_ref` stores only the S3 key path, which follows the sanitized component structure.

---

## 9. Phase 5 Sort Key Namespaces — Phase 6 Write Prohibition

Phase 6 must never write to or mutate any record under a Phase 5 sort key namespace. Phase 6 write methods in `repository.py` must target only the two Phase 6 sort key patterns:

```
AUDIT#{audit_id}#RPTJOB#{report_job_id}
AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#META
```

Any write to a Phase 5-namespaced sort key from Phase 6's `repository.py` is a programming error.

---

## 10. Sort Key Prefix Index (Phase 6 Additions)

Phase 6 additions:

| Prefix | Record Type |
| --- | --- |
| `AUDIT#{id}#RPTJOB#{id}` | ReportJob |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#INTEL#{v}#RPT#{v}#META` | ReportMetadata |

Combined platform prefix index (cumulative through Phase 6):

| Prefix | Record Type | Phase |
| --- | --- | --- |
| `AUDIT#{id}` | Canonical audit record | 3 |
| `AUDIT#{id}#RUN#{id}` | Run metadata | 1/3 |
| `AUDIT#{id}#AGGJOB#{id}` | AggregationJob / AggregationJobIntent | 4 |
| `AUDIT#{id}#EXECUTION_ID` | AuditExecutionIdentity | 4 |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#SET` | AggregateSetCompletion | 4 |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#AUDIT` | AuditAggregate | 4 |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#ENDPOINT#{id}` | EndpointAggregate | 4 |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#ENDPOINT#{id}#FAILURE_CLASSIFICATION` | EndpointFailureClassificationAggregate | 4 |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#FAILURE_CLASSIFICATION` | AuditFailureClassificationAggregate | 4 |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#LINEAGE#{scope}` | LineageManifest | 4 |
| `AUDIT#{id}#INTJOB#{id}` | IntelligenceJob | 5 |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#INTEL#{v}#META` | IntelligenceMetadata | 5 |
| `AUDIT#{id}#RPTJOB#{id}` | ReportJob | 6 |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#INTEL#{v}#RPT#{v}#META` | ReportMetadata | 6 |

---

## 11. Traceability

| Document | Role |
| --- | --- |
| `docs/architecture/phase_6_deterministic_reporting_technical_design.md` | Primary source; defines module structure, DTO schema, pipeline, determinism guarantees |
| `docs/product/phase_6_deterministic_reporting_product_spec.md` | Product specification; functional and non-functional requirements |
| `docs/architecture/phase_6_phase7_consumer_contract.md` | Phase 7 consumer contract; stable Phase 6 fields for Phase 7 consumption |
| `docs/architecture/phase_5_phase6_consumer_contract.md` | Phase 5 → Phase 6 contract; stable Phase 5 fields consumed by Phase 6 |
| `docs/architecture/phase_5_reliability_intelligence_schema.md` | Phase 5 schema reference; parent of Phase 6 read patterns |
| `docs/architecture/naming_and_schema_versioning.md` | Naming conventions; identifier format rules |
| `docs/architecture/adr_sanitization_boundary.md` | Sanitization requirements |
| `RCP_Product_Strategy.md` | Product constitution |
