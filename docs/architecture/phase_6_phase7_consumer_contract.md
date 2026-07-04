# Phase 7 Consumer Contract

## Status

Accepted — Phase 6.1 Deliverable

## Platform Constitutional Statement

**Reporting owns presentation. Phase 7 owns platform integrity certification.**

Phase 7 may consume Phase 6 report artifacts to perform Audit Platform Integrity verification. Phase 7 shall never re-derive, re-score, re-compute, or reinterpret any Phase 6 report section or any Phase 5 intelligence conclusion.

Phase 7 must not read Phase 5 intelligence artifacts directly for any purpose related to reporting. All Phase 7 inputs must come from Phase 6 report artifacts. The report layer is the only authorized presentation of Phase 5 intelligence conclusions for Phase 7's platform integrity certification workflow.

---

## 1. Contract Purpose

This document defines the stable contract between the Deterministic Reporting layer (Phase 6) and the Audit Platform Integrity layer (Phase 7).

It specifies:
- What Phase 7 may consume from Phase 6.
- What Phase 7 must not do.
- Which fields are stable and guaranteed for Phase 7 consumption.
- How contract changes are governed.

This contract is part of the Release Confidence Platform constitution. It becomes a compatibility gate: future Phase 6 changes that would break this contract require a new contract version, HITL approval, and automated regression test validation before implementation may proceed.

---

## 2. Ownership Responsibilities

| Concern | Owner |
| --- | --- |
| Raw execution evidence capture | Phase 1 / Phase 2 |
| Audit lifecycle, scheduling, finalization | Phase 3 |
| Deterministic aggregation, persistence, lineage | Phase 4 (Aggregation) |
| Reliability intelligence derivation | Phase 5 (Reliability Intelligence) |
| Operator and customer reporting | Phase 6 (Deterministic Reporting) |
| Audit Platform Integrity verification | Phase 7 (Consumer) |
| CI/CD integration | Post-Phase 7 |

**Phase 6 responsibilities:**
- Consume stable Phase 5 intelligence artifacts as inputs.
- Produce deterministic, immutable Release Confidence Reports as Phase 6 artifacts.
- Persist report artifacts in S3 and DynamoDB.
- Signal report completeness through the `ReportMetadata.status = COMPLETE` record.
- Expose all Phase 5 intelligence conclusions, methodology, and evidence lineage faithfully within the report artifact.

**Phase 7 responsibilities:**
- Consume stable Phase 6 report artifacts as inputs.
- Perform Audit Platform Integrity verification against the report artifact.
- Produce a separate Platform Integrity Certification artifact that references the Phase 6 report.
- Not bypass the `ReportMetadata.status = COMPLETE` prerequisite gate.

---

## 3. What Phase 7 May Consume

Phase 7 may consume only the following Phase 6 artifacts.

### 3.1 ReportMetadata DynamoDB Record (Prerequisite Gate)

Phase 7 must require `ReportMetadata.status = COMPLETE` before consuming any Phase 6 report artifact. This is the authoritative proof that report generation is complete and the S3 artifact is ready for consumption. It is the Phase 7 prerequisite gate, directly analogous to the `IntelligenceMetadata.status = COMPLETE` gate used by Phase 6 to gate Phase 5 consumption.

Phase 7 must not proceed to platform integrity verification if this record is absent, or if `status` is not `COMPLETE`.

**Stable fields for Phase 7 consumption:**

| Field | Type | Description |
| --- | --- | --- |
| `report_version` | String | Report schema version (e.g., `report_v1`) |
| `report_job_id` | String | Job ID of the most recent complete generation event |
| `report_id` | String | Canonical report identifier |
| `client_id` | String | Scoped client identifier |
| `audit_id` | String | Scoped audit identifier |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `aggregation_version` | String | Phase 4 aggregation version (from Phase 5) |
| `intelligence_version` | String | Phase 5 intelligence version consumed by this report |
| `status` | String | Must be `COMPLETE`; Phase 7 gate field |
| `composite_score` | Number | Audit composite score carried from Phase 5; decimal in `[0.0, 1.0]`, 3 decimal places |
| `score_label` | String | Phase 5 confidence label; bounded set defined in Section 6 |
| `endpoint_count` | Number | Number of endpoints assessed |
| `s3_artifact_ref` | String | S3 key of the authoritative Phase 6 report artifact JSON |
| `aggregate_set_hash` | String | Immutable lineage reference to Phase 4 `AggregateSetCompletion` hash (carried through Phase 5 and Phase 6) |
| `created_at` | String | UTC ISO-8601 timestamp of first report generation |
| `completed_at` | String | UTC ISO-8601 timestamp of the most recent successful generation |

Phase 7 uses `s3_artifact_ref` to locate the S3 artifact for full report content, methodology disclosure, and evidence lineage. Phase 7 must not construct or guess the S3 key independently.

---

### 3.2 S3 Report Artifact (Full Artifact)

Phase 7 may read the full S3 report artifact located at the key referenced by `ReportMetadata.s3_artifact_ref`. The artifact is an immutable JSON document (the serialized `ReleaseConfidenceReport` DTO) written once per report generation event.

**Stable top-level sections:**

#### Report Identity

| Field | Type | Description |
| --- | --- | --- |
| `identity.report_id` | String | Canonical report identifier |
| `identity.report_version` | String | `report_v1` |
| `identity.generated_at` | String | UTC ISO-8601 artifact generation timestamp |
| `identity.generator_version` | String | Platform version string at time of generation |

#### Intelligence Provenance

| Field | Type | Description |
| --- | --- | --- |
| `intelligence_provenance.intelligence_version` | String | `intel_v1` |
| `intelligence_provenance.intelligence_job_id` | String | Phase 5 job ID |
| `intelligence_provenance.client_id` | String | Scoped client identifier |
| `intelligence_provenance.audit_id` | String | Scoped audit identifier |
| `intelligence_provenance.audit_execution_id` | String | Durable execution identity |
| `intelligence_provenance.config_version` | String | Configuration version |
| `intelligence_provenance.aggregation_version` | String | Phase 4 aggregation version |
| `intelligence_provenance.aggregate_set_hash` | String | Lineage hash linking to Phase 4 |
| `intelligence_provenance.intelligence_completed_at` | String | UTC ISO-8601 Phase 5 completion timestamp |

#### Executive Summary

| Field | Type | Description |
| --- | --- | --- |
| `executive_summary.score_label` | String | Phase 5 confidence label; bounded set defined in Section 6 |
| `executive_summary.composite_score_value` | Number | `[0.0, 1.0]`, 3 decimal places |
| `executive_summary.endpoint_count` | Number | Endpoints assessed |
| `executive_summary.audit_success_rate` | Number | Audit-level success rate; 3 decimal places |
| `executive_summary.total_executions` | Number | Total raw execution count |
| `executive_summary.score_label_description` | String | Phase 6 fixed presentation string; bounded by `score_label` value |

#### Audit Reliability Overview (`audit_reliability_overview`)

Full pass-through from Phase 5 `audit_reliability_summary`. All fields are stable for Phase 7 consumption.

#### Composite Score (`composite_score`)

Full pass-through from Phase 5 `composite_score`. All fields are stable for Phase 7 consumption. Phase 7 must not recompute or re-derive the composite score.

#### Per-Endpoint Analysis (`endpoints[]`)

Phase 7 may consume the full `endpoints` array. Each element contains the following stable sub-sections, all direct pass-through from Phase 5:

- `endpoint_id`
- `reliability_metrics` (including `source_field_refs`)
- `stability_analysis` (labels and `methodology_trace`)
- `burst_analysis` (labels and `methodology_trace`)
- `consistency_analysis` (label and `methodology_trace`)
- `endpoint_score` (all score fields and `score_derivation`)

#### Methodology Disclosure (`methodology_disclosure`)

Phase 7 must carry `methodology_disclosure` through to its Platform Integrity Certification artifact or summary output. Phase 7 must not modify, summarize, or omit any methodology disclosure field.

#### Input Lineage (`input_lineage`)

Full pass-through from Phase 5 `input_lineage`. All lineage fields are stable for Phase 7 consumption.

---

## 4. What Phase 7 Must Not Do

Phase 7 is explicitly prohibited from:

1. **Re-computing, re-scoring, or re-deriving any intelligence conclusion or report section.** Phase 7 must not recompute success rates, stability labels, burst labels, consistency labels, component scores, composite scores, or any other analytical conclusion. All such values in the Phase 6 report artifact are pre-computed by Phase 5 and passed through faithfully by Phase 6. They are authoritative as persisted.

2. **Reading Phase 5 intelligence artifacts directly.** Phase 7 must not read Phase 5 DynamoDB records (`IntelligenceJob`, `IntelligenceMetadata`) or Phase 5 S3 intelligence artifacts for any platform integrity verification purpose. All Phase 7 inputs must come from Phase 6 report artifacts.

3. **Reading Phase 4 aggregation artifacts directly.** Phase 7 must not read any Phase 4 DynamoDB record or S3 artifact.

4. **Reading raw execution evidence.** Phase 7 must not read S3 raw result objects, DynamoDB run metadata, or any Phase 1/2/3 raw evidence records.

5. **Mutating Phase 6 artifacts or DynamoDB records.** Phase 7 must not create, update, delete, or extend any Phase 6 report artifact, `ReportMetadata` record, or `ReportJob` record.

6. **Bypassing the `ReportMetadata.status = COMPLETE` gate.** Phase 7 must not infer report completeness from partial artifact presence, S3 key existence, or any signal other than the `ReportMetadata.status = COMPLETE` DynamoDB record. This gate is unconditional.

7. **Overriding, reinterpreting, or relabeling Phase 5 or Phase 6 conclusions.** Phase 7 must not rename score labels, adjust thresholds, reweight components, or substitute alternative descriptions for methodology traces.

8. **Reading `ReportJob` records.** These are Phase 6-internal audit log records. They are not part of the Phase 7 consumer contract and must not be used by Phase 7. Phase 7 must derive all needed information from `ReportMetadata` and the S3 artifact.

---

## 5. DynamoDB Access Patterns

Phase 7 must use only the following DynamoDB access pattern:

**Query 1: Get ReportMetadata record (prerequisite gate)**

```
GetItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#META
```

This is a point lookup. Phase 7 must verify `status = COMPLETE` on the returned record before proceeding to any S3 artifact read.

If the record is absent or `status != COMPLETE`, Phase 7 must not proceed. Phase 7 must surface a structured error to the caller: `REPORT_NOT_COMPLETE`.

**Phase 7 must not query:**
- Any Phase 5 sort key prefix (`#INTJOB#`, `#INTEL#...#META`)
- Any Phase 4 sort key prefix (`#AGG#`, `#AGGJOB#`, `#SET`, `#MANIFEST#`)
- `ReportJob` records (SK prefix `#RPTJOB#`)
- Any other Phase 6 or Phase 5 record type not listed above

---

## 6. Bounded Value Sets (Stable for Phase 7)

### Score Label Guarantees

`score_label` in Phase 6 artifacts is a verbatim pass-through of the Phase 5 `score_label` value, which is derived deterministically from `composite_score.value` within `intel_v1`:

| Label | Phase 5 Condition | Meaning |
| --- | --- | --- |
| `HIGH_CONFIDENCE` | `composite_score.value >= 0.80` | Reliability indicators across all endpoints are strong |
| `MODERATE_CONFIDENCE` | `0.50 <= composite_score.value < 0.80` | Reliability indicators are mixed or partially insufficient |
| `LOW_CONFIDENCE` | `composite_score.value < 0.50` | Reliability indicators indicate meaningful risk |

Phase 7 must not define, derive, or substitute an alternative label mapping.

### `score_label_description` (Phase 6 Presentation Layer)

The `executive_summary.score_label_description` field is a Phase 6 fixed presentation string. It is not a Phase 5 value. The bounded mapping is fixed within `report_v1` in `constants.py`. Phase 7 may read this value but must not substitute or override it.

---

## 7. Contract Versioning and Compatibility Gate

### Version Governance

| Contract version | Report version | Intelligence version | Status |
| --- | --- | --- | --- |
| `phase7_consumer_contract_v1` | `report_v1` | `intel_v1` | Current baseline |

This document (`phase_6_phase7_consumer_contract.md`) is the `phase7_consumer_contract_v1` baseline.

### Breaking Change Definition

A breaking change is any modification to a stable field or section that:
- Removes a field listed in Section 3.
- Renames a field listed in Section 3.
- Changes the type of a field listed in Section 3.
- Changes the semantic meaning of a field listed in Section 3.
- Changes a `score_label` or `score_label_description` value within `report_v1`.
- Removes a section of the S3 artifact listed in Section 3.
- Changes the `ReportMetadata` prerequisite gate behavior.

New fields added to existing records or artifact sections are non-breaking within `report_v1`. New Phase 6 retrieval commands are non-breaking.

### Breaking Change Process

Breaking changes require:
1. Contract version increment (e.g., `phase7_consumer_contract_v2`).
2. Report version increment (e.g., `report_v2`), unless the break is limited to DynamoDB metadata fields only.
3. HITL approval of the new contract version document.
4. Explicit Phase 7 migration documentation.
5. Automated regression test validation in `tests/unit/test_phase7_consumer_contract.py`.

No breaking change may be merged without passing the compatibility gate test.

### Compatibility Gate Test

`tests/unit/test_phase7_consumer_contract.py` is the automated compatibility gate. It validates that all stable fields listed in Section 3 are present, correctly typed, and semantically consistent in the current Phase 6 report artifact output for a known fixture.

The test must cover:
- All `ReportMetadata` stable DynamoDB fields from Section 3.1.
- All top-level S3 artifact sections from Section 3.2.
- All per-endpoint sub-sections.
- All `methodology_disclosure` sub-fields.
- `score_label` bounded value set membership.
- `score_label_description` bounded value set membership.
- `composite_score.value` range `[0.0, 1.0]` enforcement.
- Precision: 3 decimal places for all numeric score fields.
- `endpoints` array lexicographic sort order.

---

## 8. Phase 7 Certification Artifact

Phase 7 produces its own Platform Integrity Certification artifact, separate from the Phase 6 report. The certification artifact must:

- Reference `report_id` and `report_version` from the Phase 6 artifact.
- Reference `intelligence_version` and `aggregate_set_hash` from the Phase 6 artifact (for full lineage chain).
- Not duplicate or embed Phase 6 report content; reference it by key only.
- Be persisted as a separate Phase 7 artifact under a Phase 7-exclusive S3 key prefix (e.g., `integrity/`).

The final customer-facing deliverable (the Release Confidence Report with Platform Integrity certification) references both the Phase 6 artifact and the Phase 7 certification by key. This composition is a Phase 7+ concern.

---

## 9. Non-Negotiable Invariants

These invariants cannot be waived by any future phase or product decision without a formal constitutional amendment approved through HITL governance:

1. Phase 7 shall never re-derive, re-score, or reinterpret any Phase 5 intelligence conclusion or Phase 6 report section.
2. Phase 7 shall never read Phase 5 intelligence artifacts directly for any platform integrity verification purpose.
3. Phase 7 shall never read Phase 4 aggregation artifacts directly.
4. `ReportMetadata.status = COMPLETE` is the only authoritative prerequisite gate for Phase 7 platform integrity verification. No alternative completeness signal may substitute.
5. Phase 7 shall never mutate any Phase 6 report artifact, `ReportMetadata` record, or `ReportJob` record.
6. Reporting owns presentation. Phase 7 owns platform integrity certification.

---

## 10. Traceability

- Phase 6 Technical Design: `docs/architecture/phase_6_deterministic_reporting_technical_design.md`
- Phase 6 Report Schema: `docs/architecture/phase_6_report_schema.md`
- Phase 6 Product Spec: `docs/product/phase_6_deterministic_reporting_product_spec.md`
- Phase 5 → Phase 6 Consumer Contract (format reference): `docs/architecture/phase_5_phase6_consumer_contract.md`
- Phase 5 Reliability Intelligence Schema: `docs/architecture/phase_5_reliability_intelligence_schema.md`
- Naming and Schema Versioning: `docs/architecture/naming_and_schema_versioning.md`
- Product Constitution: `RCP_Product_Strategy.md`
- Compatibility gate test: `tests/unit/test_phase7_consumer_contract.py`
