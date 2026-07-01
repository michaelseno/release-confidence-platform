# Phase 5 — Reliability Intelligence DynamoDB Schema

## 1. Overview

Phase 5 introduces exactly two new DynamoDB record types to the existing platform metadata table:

- **IntelligenceJob** — one record per intelligence generation invocation; immutable at terminal state; functions as an audit log
- **IntelligenceMetadata** — one record per `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version)` combination; reflects current generation state; updatable only via `--force` re-generation

All per-endpoint analysis detail, methodology traces, evidence traces, and composite score breakdowns live exclusively in the S3 intelligence artifact. DynamoDB holds only status, summary, and artifact reference metadata. This keeps DynamoDB lean: at most two Phase 5 records are written per `(audit_execution_id, intelligence_version)` combination per generation event, regardless of endpoint count.

Phase 5 never mutates any Phase 4 DynamoDB record. All Phase 5 write paths target Phase 5-exclusive sort key namespaces. This boundary is unconditional and is enforced by `repository.py` write methods.

This schema document is the authoritative reference for:

- Phase 5.2–5.7 implementation (`repository.py` read and write paths)
- Phase 5.7 Engineering Retrieval CLI DynamoDB access patterns
- Phase 6 consumer contract DynamoDB access patterns (per `docs/architecture/phase_5_phase6_consumer_contract.md`)
- Future schema version additions

The schema is immutable after publication for `intelligence_version = intel_v1`. All changes require a new `intelligence_version` per Section 8.

---

## 2. Table Reference

Phase 5 records use the existing platform metadata DynamoDB table. No new table is required.

| Property | Value |
| --- | --- |
| Table name | `release-confidence-platform-${stage}-metadata` |
| Supported stages | `dev`, `staging`, `prod` |
| Primary key type | Composite (PK + SK) |
| PK attribute | `PK` (String) |
| SK attribute | `SK` (String) |

Phase 5 records share this table with all Phase 1–4 records. Sort key namespacing ensures zero overlap between Phase 4 and Phase 5 record types. The `#INTEL#` segment is reserved exclusively for Phase 5+ records.

---

## 3. PK/SK Patterns

### 3.1 IntelligenceJob

**PK:**
```
CLIENT#{client_id}
```

**SK:**
```
AUDIT#{audit_id}#INTJOB#{intelligence_job_id}
```

**Example:**
```
PK = CLIENT#client_abc
SK = AUDIT#audit_xyz#INTJOB#intjob_4f5a6b7c8d9e0a1b2c3d4e5f6a7b8c9d
```

One record per invocation. Multiple `IntelligenceJob` records may exist under the same `audit_id` — one per generation event, including force re-generations. They are distinguished by `intelligence_job_id`. The `intelligence_job_id` segment (`intjob_`) does not appear in any Phase 4 sort key. No Phase 4 query pattern returns `IntelligenceJob` records.

---

### 3.2 IntelligenceMetadata

**PK:**
```
CLIENT#{client_id}
```

**SK:**
```
AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#META
```

**Example:**
```
PK = CLIENT#client_abc
SK = AUDIT#audit_xyz#EXEC#audexec_0b1c2d3e#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#META
```

Exactly one record per `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version)` combination. This record is the Phase 6 prerequisite gate anchor and the canonical current-state summary for a given intelligence version. The `#INTEL#` segment ensures Phase 4 query patterns (`SK begins_with AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#`) never return this record.

---

## 4. Record Schemas

### 4.1 IntelligenceJob

**Purpose:** Tracks each intelligence generation invocation — status, timing, pipeline outcome, and S3 artifact reference. Analogous to `AggregationJob` in Phase 4. One record per invocation. Immutable once `status` reaches `COMPLETE` or `FAILED`.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | `AUDIT#{audit_id}#INTJOB#{intelligence_job_id}` |
| `record_type` | String | Yes | `intelligence_job` |
| `intelligence_version` | String | Yes | `intel_v1` |
| `intelligence_job_id` | String | Yes | Opaque generated job identifier (prefix: `intjob_`) |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Yes | Durable execution identity |
| `config_version` | String | Yes | Configuration version |
| `aggregation_version` | String | Yes | Phase 4 aggregation version consumed (e.g., `agg_v1`) |
| `aggregation_job_id` | String | No | Phase 4 aggregation job that produced the consumed aggregate set; immutable lineage reference |
| `status` | String | Yes | `PENDING` \| `IN_PROGRESS` \| `COMPLETE` \| `FAILED` |
| `composite_score` | Number | No | Audit composite score; decimal in `[0.0, 1.0]`, 3 decimal places; present when `status = COMPLETE` |
| `endpoint_count` | Number | No | Endpoints scored; present when `status = COMPLETE` |
| `s3_artifact_ref` | String | No | S3 key of the written intelligence artifact; present when `status = COMPLETE` |
| `aggregate_set_hash` | String | No | Hash from `AggregateSetCompletion`; immutable lineage link to Phase 4 |
| `is_force_regeneration` | Boolean | No | `true` if invoked with `--force`; absent otherwise |
| `created_at` | String | Yes | UTC ISO-8601 creation timestamp |
| `updated_at` | String | Yes | UTC ISO-8601 last status update timestamp |
| `completed_at` | String | No | UTC ISO-8601 completion timestamp; present when `status = COMPLETE` or `FAILED` |
| `failure_stage` | String | No | Pipeline stage where failure occurred; present when `status = FAILED` |
| `failure_reason` | String | No | Controlled failure reason code; present when `status = FAILED` |

**Ownership:** Scoped to `client_id`. Written once per invocation via conditional write. Never mutated after `status` reaches `COMPLETE` or `FAILED`.

---

### 4.2 IntelligenceMetadata

**Purpose:** Current-state intelligence summary for a specific `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version)` combination. Serves as the Phase 6 prerequisite gate anchor and the retrieval CLI fast-path for status, score, and S3 artifact reference. Updated on each status transition and force re-generation.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `PK` | String | Yes | `CLIENT#{client_id}` |
| `SK` | String | Yes | `AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#META` |
| `record_type` | String | Yes | `intelligence_metadata` |
| `intelligence_version` | String | Yes | `intel_v1` |
| `intelligence_job_id` | String | Yes | Job ID of the most recent generation event; reference to active `IntelligenceJob` |
| `client_id` | String | Yes | Validated client identifier |
| `audit_id` | String | Yes | Validated audit identifier |
| `audit_execution_id` | String | Yes | Durable execution identity |
| `config_version` | String | Yes | Configuration version |
| `aggregation_version` | String | Yes | Phase 4 aggregation version consumed |
| `status` | String | Yes | `PENDING` \| `IN_PROGRESS` \| `COMPLETE` \| `FAILED` |
| `composite_score` | Number | No | Audit composite score; decimal in `[0.0, 1.0]`, 3 decimal places; present when `status = COMPLETE` |
| `score_label` | String | No | Bounded confidence label derived deterministically from `composite_score`; present when `status = COMPLETE`; stable for Phase 6 consumption |
| `endpoint_count` | Number | No | Endpoints scored; present when `status = COMPLETE` |
| `s3_artifact_ref` | String | No | S3 key of the latest complete intelligence artifact; present when `status = COMPLETE` |
| `aggregate_set_hash` | String | No | Phase 4 `AggregateSetCompletion.aggregate_set_hash`; immutable lineage link |
| `generation_count` | Number | Yes | Count of generation events including force re-generations; starts at `1` |
| `created_at` | String | Yes | UTC ISO-8601 timestamp of first generation invocation; never updated |
| `updated_at` | String | Yes | UTC ISO-8601 timestamp of most recent state update |
| `completed_at` | String | No | UTC ISO-8601 completion timestamp of most recent successful generation |
| `failure_reason` | String | No | Controlled failure reason code; present when `status = FAILED` |

**Ownership:** One record per `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version)`. Written on first invocation via conditional put; updated on each status transition and force re-generation via update item.

---

### 4.3 `score_label` Bounded Value Set

`score_label` is computed deterministically from `composite_score.value` within `intel_v1`. The mapping is fixed and defined in `constants.py`. It must not be altered without a new `intelligence_version`:

| Label | Condition | Meaning |
| --- | --- | --- |
| `HIGH_CONFIDENCE` | `composite_score >= 0.80` | Reliability indicators across all endpoints are strong |
| `MODERATE_CONFIDENCE` | `0.50 <= composite_score < 0.80` | Reliability indicators are mixed or partially insufficient |
| `LOW_CONFIDENCE` | `composite_score < 0.50` | Reliability indicators indicate meaningful risk |

Phase 6 must not define, derive, or substitute an alternative label mapping. `score_label` is computed by Phase 5 and consumed as-is. This label set is part of the stable Phase 6 consumer contract and is explicitly listed in `docs/architecture/phase_5_phase6_consumer_contract.md` Section 6.

---

## 5. Record Lifecycle

### 5.1 IntelligenceJob Status Transitions

```
[invocation start]
       |
       v
   PENDING
       |
  [computation begins]
       |
       v
  IN_PROGRESS
   /         \
[success]  [failure]
   |             |
   v             v
COMPLETE      FAILED
```

- `PENDING` is written at invocation start. A new `intelligence_job_id` is always generated for each invocation. The write is a conditional put keyed on the new `intelligence_job_id`, so it will not overwrite an existing record.
- `IN_PROGRESS` is written once Phase 4 aggregate records are loaded and computation is ready to begin.
- `COMPLETE` is written after S3 artifact write and DynamoDB completion update both succeed. At this point `composite_score`, `endpoint_count`, `s3_artifact_ref`, `aggregate_set_hash`, and `completed_at` are set.
- `FAILED` is written if any pipeline step from metrics computation through S3 write raises an exception. `failure_stage` and `failure_reason` are populated.
- Once `COMPLETE` or `FAILED`, the record is never mutated. Subsequent invocations for the same audit produce new `IntelligenceJob` records with new `intelligence_job_id` values.

### 5.2 IntelligenceMetadata Status Transitions

```
[first invocation]
       |
  created PENDING
       |
  [status mirrors IntelligenceJob]
       |
  IN_PROGRESS
   /         \
[success]  [failure]
   |             |
   v             v
COMPLETE      FAILED
```

On force re-generation from `COMPLETE`:

```
COMPLETE
   |
  [--force invoked, new intelligence_job_id generated]
   |
   v
PENDING (updated in place)
   |
  [status mirrors new IntelligenceJob transitions]
```

- Created on the first invocation with `status = PENDING` and `generation_count = 1`.
- Updated alongside the corresponding `IntelligenceJob` on each status transition.
- On force re-generation: `intelligence_job_id`, `composite_score`, `score_label`, `endpoint_count`, `s3_artifact_ref`, `completed_at`, `updated_at`, and `generation_count` are updated to reflect the latest generation. `created_at` is never updated.
- Multiple `IntelligenceJob` records may correspond to a single `IntelligenceMetadata` record over the record's lifetime (one per generation event).

---

## 6. Access Patterns

### 6.1 Phase 5 Write Patterns

| Operation | Record | Write Type | Sort Key |
| --- | --- | --- | --- |
| Create intelligence job | `IntelligenceJob` | Conditional put (new `intelligence_job_id`) | `AUDIT#{audit_id}#INTJOB#{intelligence_job_id}` |
| Create intelligence metadata | `IntelligenceMetadata` | Conditional put (first generation for combination) | `AUDIT#{audit_id}#EXEC#{...}#INTEL#{intelligence_version}#META` |
| Update job to IN_PROGRESS | `IntelligenceJob` | Update item | Same SK as create |
| Update metadata to IN_PROGRESS | `IntelligenceMetadata` | Update item | Same SK as create |
| Update job to COMPLETE | `IntelligenceJob` | Update item | Same SK as create |
| Update metadata to COMPLETE | `IntelligenceMetadata` | Update item | Same SK as create |
| Update job to FAILED | `IntelligenceJob` | Update item | Same SK as create |
| Update metadata to FAILED | `IntelligenceMetadata` | Update item | Same SK as create |

### 6.2 Phase 5 Read Patterns

**Idempotency check (reads IntelligenceMetadata before any write):**
```
GetItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#META
```

**Prerequisite gate (reads Phase 4 AggregateSetCompletion):**
```
GetItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#SET
```

**Load Phase 4 aggregate records for computation:**
```
Query:
  PK = CLIENT#{client_id}
  SK begins_with AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#
```

This single query returns `AuditAggregate`, all `EndpointAggregate` records, all `FailureClassificationAggregate` records, and the `AggregateSetCompletion` marker. Phase 5 filters to the needed record types by `record_type` field after retrieval.

Phase 5 Phase 4 reads are limited to these patterns as defined in `docs/architecture/phase_4a_phase5_consumer_contract.md`. No other Phase 4 sort key patterns may be read by Phase 5.

### 6.3 Phase 6 Read Pattern

Phase 6 uses a single DynamoDB read:

```
GetItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#META
```

Phase 6 must verify `status = COMPLETE` on the returned record before proceeding to any S3 artifact read. If the record is absent or `status != COMPLETE`, Phase 6 must not proceed and must return `INTELLIGENCE_NOT_COMPLETE`. Full Phase 6 access pattern constraints are defined in `docs/architecture/phase_5_phase6_consumer_contract.md` Section 5.

### 6.4 Retrieval CLI Read Patterns

| Command Category | DynamoDB Read | S3 Read |
| --- | --- | --- |
| Status, summary, score, lineage | `GetItem` on `IntelligenceMetadata` SK | None |
| Endpoints, stability, burst, consistency, evidence-trace, methodology | `GetItem` on `IntelligenceMetadata` SK (for `s3_artifact_ref`) | Full artifact read via `publisher.py` |

Retrieval commands are unconditionally read-only. No `IntelligenceJob` or `IntelligenceMetadata` record may be written, updated, or deleted by a retrieval command.

---

## 7. S3 Artifact Key Structure

Phase 5 intelligence artifacts are written to the existing platform S3 bucket under the exclusive `intelligence/` key prefix:

```
intelligence/{client_id}/{audit_id}/{audit_execution_id}/{aggregation_version}/{intelligence_version}/{intelligence_job_id}/artifact.json
```

**Example:**
```
intelligence/client_abc/audit_xyz/audexec_0b1c2d3e/agg_v1/intel_v1/intjob_4f5a6b7c8d9e0a1b2c3d4e5f6a7b8c9d/artifact.json
```

**Key properties:**

- The `intelligence_job_id` path segment ensures each generation produces a unique, addressable S3 key.
- Force re-generation produces a new key (new `intelligence_job_id`). The previous artifact is preserved at its original key and is not deleted.
- `IntelligenceMetadata.s3_artifact_ref` and `IntelligenceJob.s3_artifact_ref` store the complete S3 key string.
- The `intelligence/` prefix does not overlap with the Phase 4 `raw-results/` key prefix. These prefixes are mutually exclusive by construction.
- Phase 6 must use `IntelligenceMetadata.s3_artifact_ref` to locate the artifact. Phase 6 must not construct or infer the S3 key independently.

The artifact is an immutable JSON document written once per generation. Its content is defined in `docs/architecture/phase_5_reliability_intelligence_technical_design.md` Section 8.2 and is the authoritative detailed record of the intelligence output.

---

## 8. Naming and Versioning Constraints

### 8.1 Identifier Format

| Identifier | Format | Example |
| --- | --- | --- |
| `intelligence_job_id` | `intjob_{uuid4().hex}` | `intjob_4f5a6b7c8d9e0a1b2c3d4e5f6a7b8c9d` |
| `INTELLIGENCE_VERSION` constant | `intel_v{n}` | `intel_v1` |

The `intjob_` prefix is analogous to `aggjob_` in Phase 4 and follows the platform-wide identifier prefix convention. Both are defined as constants in their respective modules (`identity.py` for Phase 5, analogous to Phase 4).

All identifier components used in PK, SK, or S3 key construction must be validated through the existing `validate_identifier` utilities before use. `aggregation_version` is validated against the bounded set of known versions (`agg_v1`) before any Phase 4 record query. `intelligence_version` is fixed to `intel_v1` from `constants.py` and is not overridable by CLI argument.

### 8.2 Schema Versioning Rules

1. This schema is immutable after publication for `intelligence_version = intel_v1`.
2. Field additions to `IntelligenceJob` or `IntelligenceMetadata` require a new `intelligence_version` (e.g., `intel_v2`).
3. Field renames, removals, or type changes require a new `intelligence_version` and explicit consumer migration documentation.
4. New `intelligence_version` records are written as new `IntelligenceMetadata` items at distinct sort keys (the `INTEL#{intelligence_version}` segment changes). Existing `intel_v1` records are never modified.
5. The `intelligence_version` field on every Phase 5 record is the canonical version identifier.
6. `score_label` boundaries (`HIGH_CONFIDENCE`, `MODERATE_CONFIDENCE`, `LOW_CONFIDENCE`) are fixed within `intel_v1`. Changing threshold values or adding labels requires a new `intelligence_version`.
7. Composite score weights (0.50/0.20/0.15/0.15) are fixed within `intel_v1` and are part of the stable Phase 6 consumer contract. Any change requires a new `intelligence_version` and HITL approval.

### 8.3 Sensitive Data Exclusion

No field in any Phase 5 DynamoDB record may contain:

- Raw request or response bodies.
- HTTP headers, cookies, tokens, credentials, secrets, or PII.
- Raw URLs, query strings, or path parameters.
- Payload fragments or tenant-sensitive raw content.

The `s3_artifact_ref` field stores only the S3 key path, which follows the sanitized component structure `intelligence/{client_id}/{audit_id}/...`. No raw endpoint URL or payload appears in the S3 key or in any Phase 5 DynamoDB field. `endpoint_id` values in Phase 5 records are inherited from Phase 4 sanitized identifiers and must not be un-sanitized or expanded by Phase 5.

---

## 9. Phase 4 Sort Key Namespaces — Phase 5 Write Prohibition

Phase 5 must never write to or mutate any record under a Phase 4 sort key namespace. The following table defines Phase 4-exclusive namespaces and the access type Phase 5 is permitted:

| Sort Key Prefix | Phase 4 Record Type | Phase 5 Access |
| --- | --- | --- |
| `AUDIT#{id}` | Canonical audit record (Phase 3) | Read-only via consumer contract |
| `AUDIT#{id}#RUN#{id}` | Run metadata (Phase 1/3) | Prohibited |
| `AUDIT#{id}#AGGJOB#{id}` | AggregationJob / AggregationJobIntent | Prohibited |
| `AUDIT#{id}#EXECUTION_ID` | AuditExecutionIdentity | Prohibited |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#SET` | AggregateSetCompletion | Read-only (prerequisite gate only) |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#AUDIT` | AuditAggregate | Read-only via consumer contract |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#ENDPOINT#{id}` | EndpointAggregate | Read-only via consumer contract |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#ENDPOINT#{id}#FAILURE_CLASSIFICATION` | EndpointFailureClassificationAggregate | Read-only via consumer contract |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#FAILURE_CLASSIFICATION` | AuditFailureClassificationAggregate | Read-only via consumer contract |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#LINEAGE#{scope}` | LineageManifest | Read-only via consumer contract |

Phase 5 `repository.py` write methods must target only the two Phase 5 sort key patterns:

```
AUDIT#{audit_id}#INTJOB#{intelligence_job_id}
AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#META
```

Any write to a Phase 4-namespaced sort key from `repository.py` is a programming error. This invariant must be covered by `tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py`.

---

## 10. Sort Key Prefix Index (Phase 5 Additions)

Phase 5 additions:

| Prefix | Record Type |
| --- | --- |
| `AUDIT#{id}#INTJOB#{id}` | IntelligenceJob |
| `AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#INTEL#{v}#META` | IntelligenceMetadata |

Combined platform prefix index (Phase 4 entries from `docs/architecture/phase_4a_aggregation_schema.md`):

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

Audit listing queries must apply positive canonical-row filtering so that Phase 4 and Phase 5 child records are not returned as audits.

---

## 11. Traceability

| Document | Role |
| --- | --- |
| `docs/architecture/phase_5_reliability_intelligence_technical_design.md` | Primary source; defines DynamoDB record types, field tables, PK/SK structure, access patterns, lifecycle, and pipeline behavior |
| `docs/architecture/phase_5_phase6_consumer_contract.md` | Phase 6 consumer contract; defines stable fields on `IntelligenceMetadata`, `score_label` bounded value set, and Phase 6 DynamoDB access constraints |
| `docs/architecture/phase_4a_aggregation_schema.md` | Format reference; Phase 4 sort key prefix index; Phase 4 field schemas referenced by Phase 5 read paths |
| `docs/architecture/phase_4a_phase5_consumer_contract.md` | Phase 4 consumer contract boundary; read-only query patterns for Phase 5's Phase 4 reads |
| `docs/architecture/naming_and_schema_versioning.md` | Naming conventions; identifier format rules; resource naming |
| `docs/architecture/adr_sanitization_boundary.md` | Sanitization requirements applicable to Phase 5 record fields and S3 key construction |
| `RCP_Product_Strategy.md` | Product constitution; phase governance; core product principles |
