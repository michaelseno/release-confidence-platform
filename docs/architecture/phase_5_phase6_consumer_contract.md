# Phase 6 Consumer Contract

## Status

Accepted — Phase 5.1 Deliverable

## Platform Constitutional Statement

**Intelligence owns interpretation. Phase 6 owns reporting.**

Phase 6 may consume Phase 5 intelligence artifacts to produce Release Confidence Reports. Phase 6 shall never re-derive, re-score, re-compute, or reinterpret any Phase 5 intelligence conclusion.

This ownership boundary is a constitutional statement. It governs all present and future interactions between reliability intelligence (Phase 5) and deterministic reporting (Phase 6).

Phase 6 must not read Phase 4 aggregation artifacts directly. All Phase 6 inputs must come from Phase 5 intelligence artifacts. The intelligence layer is the only authorized translation of aggregation facts into reliability conclusions.

---

## 1. Contract Purpose

This document defines the stable contract between the Reliability Intelligence layer (Phase 5) and the Deterministic Reporting layer (Phase 6).

It specifies:
- What Phase 6 may consume from Phase 5.
- What Phase 6 must not do.
- Which fields are stable and guaranteed for Phase 6 consumption.
- How contract changes are governed.

This contract is part of the Release Confidence Platform constitution. It becomes a compatibility gate: future Phase 5 changes that would break this contract require a new contract version, HITL approval, and automated regression test validation before implementation may proceed.

---

## 2. Ownership Responsibilities

| Concern | Owner |
| --- | --- |
| Raw execution evidence capture | Phase 1 / Phase 2 |
| Audit lifecycle, scheduling, finalization | Phase 3 |
| Deterministic aggregation, persistence, lineage | Phase 4 (Aggregation) |
| Reliability intelligence derivation | Phase 5 (Reliability Intelligence) |
| Operator and customer reporting | Phase 6 (Consumer) |
| CI/CD integration | Phase 7 |

**Phase 5 responsibilities:**
- Derive reliability intelligence from Phase 4 aggregation artifacts without re-implementing aggregation logic.
- Persist immutable intelligence artifacts in S3 and DynamoDB.
- Signal intelligence completeness through the `IntelligenceMetadata.status = COMPLETE` record.
- Expose all scoring methodology, label definitions, thresholds, and evidence traces within the intelligence artifact.

**Phase 6 responsibilities:**
- Consume stable Phase 5 intelligence artifacts as inputs.
- Translate pre-computed intelligence into human-readable Release Confidence Reports.
- Present Phase 5 conclusions faithfully without alteration, relabeling, or re-derivation.
- Not bypass the `IntelligenceMetadata.status = COMPLETE` prerequisite gate.

---

## 3. What Phase 6 May Consume

Phase 6 may consume only the following Phase 5 artifacts.

### 3.1 IntelligenceMetadata DynamoDB Record (Prerequisite Gate)

Phase 6 must require `IntelligenceMetadata.status = COMPLETE` before consuming any Phase 5 intelligence. This is the authoritative proof that intelligence generation is complete and the S3 artifact is ready for consumption. It is the Phase 6 prerequisite gate, directly analogous to the `AggregateSetCompletion` marker used by Phase 5 to gate Phase 4 consumption.

Phase 6 must not proceed to report generation if this record is absent, or if `status` is not `COMPLETE`.

**Stable fields for Phase 6 consumption:**

| Field | Type | Description |
| --- | --- | --- |
| `intelligence_version` | String | Intelligence schema version (e.g., `intel_v1`) |
| `intelligence_job_id` | String | Job ID of the most recent complete generation event |
| `client_id` | String | Scoped client identifier |
| `audit_id` | String | Scoped audit identifier |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `aggregation_version` | String | Phase 4 aggregation version consumed by this intelligence artifact |
| `status` | String | Must be `COMPLETE`; Phase 6 gate field |
| `composite_score` | Number | Audit composite score; decimal in `[0.0, 1.0]`, 3 decimal places |
| `score_label` | String | Human-readable confidence label derived from `composite_score`; bounded label set defined in Section 6 |
| `endpoint_count` | Number | Number of endpoints scored |
| `s3_artifact_ref` | String | S3 key of the authoritative intelligence artifact JSON |
| `aggregate_set_hash` | String | Immutable lineage reference to the Phase 4 `AggregateSetCompletion` hash |
| `created_at` | String | UTC ISO-8601 timestamp of first intelligence generation |
| `completed_at` | String | UTC ISO-8601 timestamp of the most recent successful generation |

Phase 6 uses `s3_artifact_ref` to locate the S3 artifact for per-endpoint detail and methodology disclosure. Phase 6 must not construct or guess the S3 key independently.

---

### 3.2 S3 Intelligence Artifact (Full Artifact)

Phase 6 may read the full S3 intelligence artifact located at the key referenced by `IntelligenceMetadata.s3_artifact_ref`. The artifact is an immutable JSON document written once per intelligence generation event.

**Stable top-level sections:**

#### Identity and Provenance

| Field | Type | Description |
| --- | --- | --- |
| `intelligence_version` | String | `intel_v1` |
| `aggregation_version` | String | Phase 4 aggregation version consumed |
| `client_id` | String | Scoped client identifier |
| `audit_id` | String | Scoped audit identifier |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `intelligence_job_id` | String | Opaque generation job identifier |
| `generated_at` | String | UTC ISO-8601 artifact generation timestamp |
| `generator_version` | String | Platform version string at time of generation |

#### Audit Reliability Summary (`audit_reliability_summary`)

| Field | Type | Description |
| --- | --- | --- |
| `total_executions` | Number | Total raw result records across all endpoints |
| `total_pass` | Number | PASS outcome count across all endpoints |
| `total_fail` | Number | Non-PASS outcome count across all endpoints |
| `total_timeout` | Number | TIMEOUT classification count |
| `total_network_failure` | Number | CONNECTION_ERROR classification count |
| `audit_success_rate` | Number | Audit-level success rate; decimal, 3 decimal places |
| `endpoint_count` | Number | Distinct endpoint count in this audit |
| `audit_latency_mean_ms` | Number or null | Audit-level mean latency |
| `audit_latency_p95_ms` | Number or null | Audit-level p95 latency |
| `audit_latency_p99_ms` | Number or null | Audit-level p99 latency |
| `source_field_refs` | Map | Evidence trace mapping each field to its Phase 4 source |

#### Composite Score (`composite_score`)

| Field | Type | Description |
| --- | --- | --- |
| `composite_score.value` | Number | Audit composite score; decimal in `[0.0, 1.0]`, 3 decimal places |
| `composite_score.score_label` | String | Human-readable confidence label; bounded set defined in Section 6 |
| `composite_score.intelligence_version` | String | `intel_v1` |
| `composite_score.aggregation_version` | String | Phase 4 aggregation version |
| `composite_score.aggregate_set_hash` | String | Lineage hash linking score to Phase 4 aggregate set |
| `composite_score.endpoint_count` | Number | Number of endpoints included in composite rollup |
| `composite_score.component_breakdown` | Map | Per-layer weighted contribution; sub-fields below |
| `composite_score.component_breakdown.reliability.weight` | Number | `0.50` (fixed in `intel_v1`) |
| `composite_score.component_breakdown.reliability.value` | Number | Unweighted mean of per-endpoint success rates |
| `composite_score.component_breakdown.reliability.description` | String | Human-readable description of rollup method |
| `composite_score.component_breakdown.stability.weight` | Number | `0.20` (fixed in `intel_v1`) |
| `composite_score.component_breakdown.stability.value` | Number | Mean of per-endpoint stability scores |
| `composite_score.component_breakdown.stability.description` | String | Human-readable description of rollup method |
| `composite_score.component_breakdown.burst.weight` | Number | `0.15` (fixed in `intel_v1`) |
| `composite_score.component_breakdown.burst.value` | Number | Mean of per-endpoint burst scores |
| `composite_score.component_breakdown.burst.description` | String | Human-readable description of rollup method |
| `composite_score.component_breakdown.consistency.weight` | Number | `0.15` (fixed in `intel_v1`) |
| `composite_score.component_breakdown.consistency.value` | Number | Mean of per-endpoint consistency scores |
| `composite_score.component_breakdown.consistency.description` | String | Human-readable description of rollup method |

#### Input Lineage (`input_lineage`)

| Field | Type | Description |
| --- | --- | --- |
| `input_lineage.aggregate_set_hash` | String | `AggregateSetCompletion.aggregate_set_hash`; immutable lineage link to Phase 4 |
| `input_lineage.aggregation_job_id` | String | `AggregationJob` identifier that produced the consumed Phase 4 set |
| `input_lineage.aggregation_version` | String | Phase 4 aggregation version |
| `input_lineage.aggregate_set_completion_created_at` | String | UTC ISO-8601 timestamp of the Phase 4 `AggregateSetCompletion` marker |
| `input_lineage.endpoint_aggregate_count` | Number | Phase 4 endpoint aggregate record count consumed |
| `input_lineage.source_raw_result_count` | Number | Phase 4 raw result count at aggregation time |
| `input_lineage.audit_lineage_manifest_ref` | Map | Reference to the Phase 4 audit-scope lineage manifest |
| `input_lineage.audit_lineage_manifest_ref.manifest_scope` | String | `audit` |
| `input_lineage.audit_lineage_manifest_ref.source_ref_count` | Number | Number of raw result references in the lineage manifest |
| `input_lineage.audit_lineage_manifest_ref.manifest_hash` | String | Phase 4 lineage manifest integrity hash |

#### Per-Endpoint Intelligence Array (`endpoints[]`)

Phase 6 may consume the full `endpoints` array. Each element contains the following stable sub-sections.

**Per-Endpoint Identity:**

| Field | Type | Description |
| --- | --- | --- |
| `endpoint_id` | String | Sanitized opaque endpoint identifier; inherited from Phase 4 |

**Reliability Metrics (`endpoints[*].reliability_metrics`):**

| Field | Type | Description |
| --- | --- | --- |
| `execution_count` | Number | Total raw result records for this endpoint |
| `pass_count` | Number | PASS outcome count |
| `fail_count` | Number | Non-PASS outcome count |
| `timeout_count` | Number | TIMEOUT count |
| `success_rate` | Number | Decimal, 3 decimal places; `pass_count / execution_count` |
| `success_rate_numerator` | Number | Retained for traceability; equals `pass_count` |
| `success_rate_denominator` | Number | Retained for traceability; equals `execution_count` |
| `latency_min_ms` | Number or null | Minimum latency; null when `latency_count = 0` |
| `latency_max_ms` | Number or null | Maximum latency; null when `latency_count = 0` |
| `latency_mean_ms` | Number or null | Mean latency; null when `latency_count = 0` |
| `latency_median_ms` | Number or null | Median latency; null when `latency_count = 0` |
| `latency_p95_ms` | Number or null | 95th percentile latency; null when `latency_count = 0` |
| `latency_p99_ms` | Number or null | 99th percentile latency; null when `latency_count = 0` |
| `latency_count` | Number | Number of latency measurements |
| `failure_classification_breakdown` | Map | Failure classification label → count; Phase 4 labels carried without remapping |
| `http_response_distribution` | Map | HTTP status code (or `NO_STATUS`) → count |
| `source_field_refs` | Map | Evidence trace mapping each derived field to its Phase 4 source record and field |

**Stability Analysis (`endpoints[*].stability_analysis`):**

| Field | Type | Description |
| --- | --- | --- |
| `success_rate_stability_label` | String | `STABLE` \| `DEGRADED` \| `INSUFFICIENT_DATA` |
| `latency_stability_label` | String | `STABLE` \| `DEGRADED` \| `INSUFFICIENT_DATA` |
| `methodology_trace` | Map | Full methodology trace including algorithm name, version, inputs, thresholds, intermediate values, and label determination explanation |

**Burst Analysis (`endpoints[*].burst_analysis`):**

| Field | Type | Description |
| --- | --- | --- |
| `failure_burst_label` | String | `NO_BURST_DETECTED` \| `BURST_SUSPECTED` \| `INSUFFICIENT_DATA` |
| `latency_spike_label` | String | `NO_SPIKE_DETECTED` \| `SPIKE_SUSPECTED` \| `INSUFFICIENT_DATA` |
| `methodology_trace` | Map | Full methodology trace including algorithm name, version, inputs, thresholds, intermediate values, and label determination explanation |

**Consistency Analysis (`endpoints[*].consistency_analysis`):**

| Field | Type | Description |
| --- | --- | --- |
| `consistency_label` | String | `CONSISTENT` \| `INCONSISTENT` \| `INSUFFICIENT_DATA` |
| `methodology_trace` | Map | Full methodology trace including algorithm name, version, inputs, thresholds, intermediate values, and label determination explanation |

**Endpoint Score (`endpoints[*].endpoint_score`):**

| Field | Type | Description |
| --- | --- | --- |
| `composite_score` | Number | Per-endpoint composite score; decimal in `[0.0, 1.0]`, 3 decimal places |
| `reliability_score` | Number | Success rate value; direct input to weighted formula |
| `stability_score` | Number | Mean of stability label-to-score mappings |
| `burst_score` | Number | Mean of burst and spike label-to-score mappings |
| `consistency_score` | Number | Consistency label-to-score mapping value |
| `score_derivation` | Map | Human-readable formula descriptions for each component |

#### Methodology Disclosure (`methodology_disclosure`)

Phase 6 must carry `methodology_disclosure` through to Report output. Phase 6 must not modify, summarize, or omit any methodology disclosure field.

| Sub-Field | Description |
| --- | --- |
| `intelligence_version` | `intel_v1` |
| `scoring.composite_score_range` | `[0.0, 1.0]` |
| `scoring.rollup` | Arithmetic mean formula description |
| `scoring.precision` | `3 decimal places, half-up rounding via Python Decimal` |
| `scoring.component_weights` | Fixed weight table: reliability 0.50, stability 0.20, burst 0.15, consistency 0.15 |
| `scoring.per_endpoint_formula` | The exact weighted formula string |
| `stability_label_definitions` | Bounded definitions for `STABLE`, `DEGRADED`, `INSUFFICIENT_DATA` |
| `burst_label_definitions` | Bounded definitions for all burst and spike labels |
| `consistency_label_definitions` | Bounded definitions for `CONSISTENT`, `INCONSISTENT`, `INSUFFICIENT_DATA` |
| `label_to_score_mapping` | Complete deterministic label-to-numeric-score table |
| `limitations` | Full limitations array; must be presented verbatim in reports |

---

## 4. What Phase 6 Must Not Do

Phase 6 is explicitly prohibited from:

1. **Re-computing, re-scoring, or re-deriving any intelligence conclusion.** Phase 6 must not recompute success rates, stability labels, burst labels, consistency labels, component scores, or composite scores from Phase 4 or Phase 5 inputs. All scores and labels consumed by Phase 6 are pre-computed and immutable.

2. **Reading Phase 4 aggregation artifacts directly.** Phase 6 must not read Phase 4 DynamoDB records (`AuditAggregate`, `EndpointAggregate`, `FailureClassificationAggregate`, `AggregateSetCompletion`, `LineageManifest`) or Phase 4 S3 artifacts for any reporting purpose. All Phase 6 inputs must come from Phase 5 intelligence artifacts.

3. **Reading raw execution evidence.** Phase 6 must not read S3 raw result objects, DynamoDB run metadata, or any Phase 1/2/3 raw evidence records.

4. **Mutating Phase 5 artifacts or DynamoDB records.** Phase 6 must not create, update, delete, or extend any Phase 5 intelligence artifact, `IntelligenceMetadata` record, or `IntelligenceJob` record.

5. **Bypassing the `IntelligenceMetadata.status = COMPLETE` gate.** Phase 6 must not infer intelligence completeness from partial artifact presence, S3 key existence, or any signal other than the `IntelligenceMetadata.status = COMPLETE` DynamoDB record. This gate is unconditional.

6. **Overriding, reinterpreting, or relabeling Phase 5 conclusions.** Phase 6 must not rename stability labels, adjust score thresholds, reweight components, redefine score_label boundaries, or substitute alternative descriptions for persisted methodology traces. Phase 5 conclusions are authoritative and must be presented as-is.

7. **Reading `IntelligenceJob` records.** These are Phase 5-internal audit log records. They are not part of the Phase 6 consumer contract and must not be used by Phase 6. Phase 6 must derive all needed information from `IntelligenceMetadata` and the S3 artifact.

---

## 5. DynamoDB Access Patterns

Phase 6 must use only the following DynamoDB access pattern:

**Query 1: Get IntelligenceMetadata record (prerequisite gate)**

```
GetItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#META
```

This is a point lookup. Phase 6 must verify `status = COMPLETE` on the returned record before proceeding to any S3 artifact read.

If the record is absent or `status != COMPLETE`, Phase 6 must not proceed. Phase 6 must surface a structured error to the caller: `INTELLIGENCE_NOT_COMPLETE`.

**Phase 6 must not query:**
- Any Phase 4 sort key prefix (`#AGG#`, `#AGGJOB#`, `#SET`, `#MANIFEST#`)
- `IntelligenceJob` records (SK prefix `#INTJOB#`)
- Any other Phase 5 or Phase 4 record type not listed above

---

## 6. intel_v1 Semantic Guarantees

The following semantic guarantees apply to `intelligence_version = intel_v1` and are stable for Phase 6 consumption:

### Scoring Guarantees

| Guarantee | Value |
| --- | --- |
| `composite_score.value` range | `[0.0, 1.0]` |
| Numeric precision | 3 decimal places, half-up rounding via Python `Decimal` |
| Audit composite rollup | Unweighted arithmetic mean of per-endpoint composite scores |
| Component weight — reliability | `0.50` (fixed within `intel_v1`) |
| Component weight — stability | `0.20` (fixed within `intel_v1`) |
| Component weight — burst | `0.15` (fixed within `intel_v1`) |
| Component weight — consistency | `0.15` (fixed within `intel_v1`) |
| `INSUFFICIENT_DATA` label-to-score | Always `0.5` (neutral; no penalty, no reward) |

### Score Label Guarantees

`score_label` is a bounded string derived deterministically from `composite_score.value`. The mapping is fixed within `intel_v1`:

| Label | Condition | Meaning |
| --- | --- | --- |
| `HIGH_CONFIDENCE` | `composite_score.value >= 0.80` | Reliability indicators across all endpoints are strong |
| `MODERATE_CONFIDENCE` | `0.50 <= composite_score.value < 0.80` | Reliability indicators are mixed or partially insufficient |
| `LOW_CONFIDENCE` | `composite_score.value < 0.50` | Reliability indicators indicate meaningful risk |

Phase 6 must not define, derive, or substitute an alternative label mapping. `score_label` is computed by Phase 5 and consumed as-is by Phase 6.

### Stability Label Guarantees

Bounded label set for `success_rate_stability_label` and `latency_stability_label`:

| Label | Meaning |
| --- | --- |
| `STABLE` | Distributional indicators are consistent with stable behavior across the full observation window |
| `DEGRADED` | Distributional indicators are inconsistent with stable behavior |
| `INSUFFICIENT_DATA` | Execution or latency count is below the minimum threshold for characterization |

### Burst Label Guarantees

Bounded label set for `failure_burst_label`:

| Label | Meaning |
| --- | --- |
| `NO_BURST_DETECTED` | Timeout proportion does not exceed the burst detection threshold |
| `BURST_SUSPECTED` | Timeout proportion is consistent with concentrated service outage events |
| `INSUFFICIENT_DATA` | Execution count is below the minimum threshold for burst characterization |

Bounded label set for `latency_spike_label`:

| Label | Meaning |
| --- | --- |
| `NO_SPIKE_DETECTED` | Max/p99 latency ratio does not exceed the spike detection threshold |
| `SPIKE_SUSPECTED` | Max/p99 latency ratio is consistent with isolated spike events |
| `INSUFFICIENT_DATA` | Latency count is below the minimum threshold for spike characterization |

### Consistency Label Guarantees

Bounded label set for `consistency_label`:

| Label | Meaning |
| --- | --- |
| `CONSISTENT` | Bernoulli outcome variance `p*(1-p)` is at or below `0.05`; predominantly uniform outcomes |
| `INCONSISTENT` | Bernoulli outcome variance `p*(1-p)` exceeds `0.05`; mixed outcomes |
| `INSUFFICIENT_DATA` | Execution count is below the minimum threshold for consistency estimation |

### Structural Guarantees

| Guarantee | Value |
| --- | --- |
| `endpoints` array ordering | Canonical lexicographic ascending order by `endpoint_id` |
| `failure_classification_breakdown` key ordering | Lexicographic ascending |
| S3 artifact serialization | `json.dumps(..., sort_keys=True)`; canonical field ordering |
| Determinism | Identical Phase 4 inputs produce byte-identical S3 artifact JSON |
| `endpoint_id` values | Sanitized Phase 4 identifiers; never raw URLs, headers, or PII |
| Methodology trace persistence | All algorithm inputs, thresholds, and intermediate values are persisted in the artifact |
| `success_rate` null behavior | If `success_rate_denominator = 0`, `success_rate` is absent or null; all analysis labels are `INSUFFICIENT_DATA` |
| Latency null behavior | All latency fields are `null` when `latency_count = 0` |

### Phase 4 Failure Classification Carrythrough

Phase 5 carries Phase 4 failure classification labels into `failure_classification_breakdown` without renaming, remapping, or augmentation. Phase 6 must not remap or infer alternative categorizations. The Phase 4 approved classification labels are:

`PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, `PAYLOAD_VALIDATION_ERROR`, `MISSING_FAILURE_CLASSIFICATION`, `UNKNOWN_FAILURE_CLASSIFICATION`

---

## 7. Contract Versioning and Compatibility Gate

### Version Governance

| Contract version | Intelligence version | Status |
| --- | --- | --- |
| `phase6_consumer_contract_v1` | `intel_v1` | Current baseline |

This document (`phase_5_phase6_consumer_contract.md`) is the `phase6_consumer_contract_v1` baseline.

### Breaking Change Definition

A breaking change is any modification to a stable field or section that:
- Removes a field listed in Section 3.
- Renames a field listed in Section 3.
- Changes the type of a field listed in Section 3.
- Changes the semantic meaning of a field listed in Section 3 (e.g., redefining `score_label` thresholds, changing a label value, removing a label from a bounded set).
- Changes a scoring weight, scoring formula, or rollup method within `intel_v1`.
- Removes a section of the S3 artifact listed in Section 3.
- Changes the `IntelligenceMetadata` prerequisite gate behavior.

New fields added to existing records or artifact sections are non-breaking within `intel_v1`. New analysis sections not consumed by this contract are non-breaking. New retrieval commands are non-breaking.

### Breaking Change Process

Breaking changes require:
1. Contract version increment (e.g., `phase6_consumer_contract_v2`).
2. Intelligence version increment (e.g., `intel_v2`), unless the break is limited to DynamoDB metadata fields only.
3. HITL approval of the new contract version document.
4. Explicit Phase 6 migration documentation describing what Phase 6 must change and what Phase 5 must expose differently.
5. Automated regression test validation in `tests/unit/test_phase6_consumer_contract.py`.

No breaking change may be merged without passing the compatibility gate test.

### Compatibility Gate Test

`tests/unit/test_phase6_consumer_contract.py` is the automated compatibility gate. It validates that all stable fields listed in Section 3 are present, correctly typed, and semantically consistent in the current Phase 5 intelligence artifact output for a known fixture.

This test must pass for all `intel_v1` Phase 5 output. Failure of this test blocks Phase 5 implementation changes.

The test must cover:
- All `IntelligenceMetadata` stable DynamoDB fields from Section 3.1.
- All top-level S3 artifact sections from Section 3.2.
- All per-endpoint sub-sections (`reliability_metrics`, `stability_analysis`, `burst_analysis`, `consistency_analysis`, `endpoint_score`).
- All `methodology_disclosure` sub-fields.
- `score_label` bounded value set membership.
- All stability, burst, and consistency label bounded value set memberships.
- `composite_score.value` range `[0.0, 1.0]` enforcement.
- Precision: 3 decimal places for all numeric score fields.
- `endpoints` array lexicographic sort order.

---

## 8. Non-Negotiable Invariants

These invariants cannot be waived by any future phase or product decision without a formal constitutional amendment approved through HITL governance:

1. Phase 6 shall never re-derive, re-score, or reinterpret any Phase 5 intelligence conclusion.
2. Phase 6 shall never read Phase 4 aggregation artifacts directly for any reporting purpose.
3. Phase 6 shall never read raw execution evidence from Phase 1, Phase 2, Phase 3, or S3 raw result objects.
4. `IntelligenceMetadata.status = COMPLETE` is the only authoritative prerequisite gate for Phase 6 report generation. No alternative completeness signal may substitute.
5. Phase 6 shall never mutate any Phase 5 intelligence artifact, `IntelligenceMetadata` record, or `IntelligenceJob` record.
6. Phase 6 shall never relabel, redefine, or reweight Phase 5 intelligence conclusions. Score labels, analysis labels, and methodology disclosure are authoritative as persisted and must be presented as-is.
7. Intelligence owns interpretation. Phase 6 owns reporting.

---

## 9. Traceability

- Phase 5 Technical Design: `docs/architecture/phase_5_reliability_intelligence_technical_design.md`
- Phase 5 Product Spec: `docs/product/phase_5_reliability_intelligence_product_spec.md`
- Phase 4 → Phase 5 Consumer Contract (format reference): `docs/architecture/phase_4a_phase5_consumer_contract.md`
- Phase 4A Aggregation Schema: `docs/architecture/phase_4a_aggregation_schema.md`
- Phase 4A Aggregation Foundation Technical Design: `docs/architecture/phase_4a_aggregation_foundation_technical_design.md`
- Phase 4A Engineering Retrieval ADR: `docs/architecture/adr_phase_4a_engineering_retrieval_consumer_contract.md`
- Sanitization Boundary ADR: `docs/architecture/adr_sanitization_boundary.md`
- Naming and Schema Versioning: `docs/architecture/naming_and_schema_versioning.md`
- Product Constitution: `RCP_Product_Strategy.md`
- Compatibility gate test: `tests/unit/test_phase6_consumer_contract.py`
