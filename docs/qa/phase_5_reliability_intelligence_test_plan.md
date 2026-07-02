# Test Plan

## 1. Scope and Objectives

This test plan covers QA validation for Phase 5: Reliability Intelligence.

Phase 5 is an operator-invoked pipeline that reads Phase 4 aggregation artifacts and produces:

- An immutable S3 JSON intelligence artifact containing per-endpoint reliability metrics, stability analysis, burst analysis, consistency analysis, composite scoring, and methodology disclosure.
- A DynamoDB `IntelligenceJob` record per invocation.
- A DynamoDB `IntelligenceMetadata` record per `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version)` combination.

Phase 5 validation is divided into eight subphases:

1. **Phase 5.1 — Documentation / Consumer Contract Compatibility Gate**
2. **Phase 5.2 — Reliability Metrics Core**
3. **Phase 5.3 — Stability Analysis**
4. **Phase 5.4 — Burst Analysis**
5. **Phase 5.5 — Consistency Analysis**
6. **Phase 5.6 — Release Confidence Scoring**
7. **Phase 5.7 — Engineering Retrieval CLI**
8. **Phase 5.8 — Validation Campaign (48-Hour Audits)**

Cross-cutting concerns (determinism, Phase 4 non-mutation, idempotency, write ordering, raw evidence exclusion) are collected in Section 11. Phase 5 is not complete until all sections pass and HITL approval is granted for Phase 5.8.

---

## 2. Test Strategy

### 2.1 Approach

Phase 5 is a pure computation and persistence layer. It reads from Phase 4, applies `intel_v1` algorithms, and writes to S3 and DynamoDB. The test strategy is:

- **Unit tests** for each algorithm and analysis module in isolation using Phase 4 `agg_v1` fixtures.
- **Unit tests** for DynamoDB write path contract (correct SK patterns, no Phase 4 SK mutations).
- **Unit tests** for S3 artifact structure, field completeness, and serialization determinism.
- **Contract tests** for the Phase 6 consumer contract compatibility gate.
- **Integration tests** for end-to-end pipeline behavior: Phase 4 fixture load → computation → S3 write → DynamoDB write → retrieval.
- **Validation campaign** for live 48-hour audit data.

### 2.2 Intelligence Version in Scope

All tests in this plan target `intelligence_version = intel_v1`. Tests must assert the exact algorithm names, thresholds, label values, and weight constants defined for `intel_v1`. Tests are not forward-compatible with `intel_v2`.

### 2.3 Fixture Policy

All unit test fixtures must be derived from Phase 4 `agg_v1` aggregate fields only. No test may construct fixtures using raw execution evidence, S3 raw result content, or any Phase 1/2/3 record structure. See Section 12 for required fixture coverage.

### 2.4 Test File Locations

| Test Type | Location |
| --- | --- |
| Consumer contract compatibility gate | `tests/unit/test_phase6_consumer_contract.py` |
| Phase 4 non-mutation gate | `tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py` |
| Algorithm unit tests | `tests/unit/reliability_intelligence/` |
| DynamoDB record schema tests | `tests/unit/reliability_intelligence/` |
| S3 artifact structure tests | `tests/unit/reliability_intelligence/` |
| Retrieval CLI unit tests | `tests/unit/retrieval/` |
| Integration tests | `tests/integration/` |

### 2.5 Execution Commands

- Unit tests: `python -m pytest tests/unit/`
- Integration tests: `python -m pytest tests/integration/`
- Contract gate only: `python -m pytest tests/unit/test_phase6_consumer_contract.py`
- Phase 4 mutation gate only: `python -m pytest tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py`
- Linting: `python -m ruff check src/ apps/ tests/`

---

## 3. Phase 5.1 — Documentation / Consumer Contract Compatibility Gate

### 3.1 Scope

Phase 5.1 delivers the Phase 6 consumer contract document (`docs/architecture/phase_5_phase6_consumer_contract.md`) and the automated compatibility gate test (`tests/unit/test_phase6_consumer_contract.py`). The compatibility gate must pass before any Phase 5.2–5.7 implementation change is merged.

This section validates:

- All stable `IntelligenceMetadata` fields are present and correctly typed against a known fixture.
- All S3 artifact top-level sections are present.
- All per-endpoint sub-sections are structurally complete.
- Bounded label set membership is enforced.
- Numeric score fields conform to 3-decimal precision.
- `endpoints` array ordering is lexicographic.

### 3.2 Compatibility Gate Tests

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| CON-01 | IntelligenceMetadata: all stable DynamoDB fields present | All fields from Phase 6 contract Section 3.1 (`intelligence_version`, `intelligence_job_id`, `client_id`, `audit_id`, `audit_execution_id`, `config_version`, `aggregation_version`, `status`, `composite_score`, `score_label`, `endpoint_count`, `s3_artifact_ref`, `aggregate_set_hash`, `created_at`, `completed_at`) are present and non-null in a COMPLETE fixture |
| CON-02 | IntelligenceMetadata: all stable fields are correctly typed | `composite_score` is Number; `score_label` is String; `endpoint_count` is Number; `status` is String; all timestamp fields are ISO-8601 strings |
| CON-03 | S3 artifact: all top-level sections present | `intelligence_version`, `aggregation_version`, `client_id`, `audit_id`, `audit_execution_id`, `config_version`, `intelligence_job_id`, `generated_at`, `generator_version`, `audit_reliability_summary`, `composite_score`, `input_lineage`, `endpoints`, `methodology_disclosure` all present in artifact fixture |
| CON-04 | S3 artifact: `audit_reliability_summary` complete | All fields: `total_executions`, `total_pass`, `total_fail`, `total_timeout`, `total_network_failure`, `audit_success_rate`, `endpoint_count`, `audit_latency_mean_ms`, `audit_latency_p95_ms`, `audit_latency_p99_ms`, `source_field_refs` present |
| CON-05 | S3 artifact: `composite_score` section complete | All fields: `value`, `score_label`, `intelligence_version`, `aggregation_version`, `aggregate_set_hash`, `endpoint_count`, `component_breakdown` with all four component sub-fields (`reliability`, `stability`, `burst`, `consistency`) each having `weight`, `value`, `description` |
| CON-06 | S3 artifact: `input_lineage` section complete | All fields: `aggregate_set_hash`, `aggregation_job_id`, `aggregation_version`, `aggregate_set_completion_created_at`, `endpoint_aggregate_count`, `source_raw_result_count`, `audit_lineage_manifest_ref` with `manifest_scope`, `source_ref_count`, `manifest_hash` |
| CON-07 | S3 artifact: per-endpoint `reliability_metrics` complete | For each endpoint: `execution_count`, `pass_count`, `fail_count`, `timeout_count`, `success_rate`, `success_rate_numerator`, `success_rate_denominator`, `latency_min_ms`, `latency_max_ms`, `latency_mean_ms`, `latency_median_ms`, `latency_p95_ms`, `latency_p99_ms`, `latency_count`, `failure_classification_breakdown`, `http_response_distribution`, `source_field_refs` all present |
| CON-08 | S3 artifact: per-endpoint `stability_analysis` complete | `success_rate_stability_label`, `latency_stability_label`, `methodology_trace` present for each endpoint |
| CON-09 | S3 artifact: per-endpoint `burst_analysis` complete | `failure_burst_label`, `latency_spike_label`, `methodology_trace` present for each endpoint |
| CON-10 | S3 artifact: per-endpoint `consistency_analysis` complete | `consistency_label`, `methodology_trace` present for each endpoint |
| CON-11 | S3 artifact: per-endpoint `endpoint_score` complete | `composite_score`, `reliability_score`, `stability_score`, `burst_score`, `consistency_score`, `score_derivation` present for each endpoint |
| CON-12 | S3 artifact: `methodology_disclosure` section complete | All sub-fields: `intelligence_version`, `scoring.composite_score_range`, `scoring.rollup`, `scoring.precision`, `scoring.component_weights`, `scoring.per_endpoint_formula`, `stability_label_definitions`, `burst_label_definitions`, `consistency_label_definitions`, `label_to_score_mapping`, `limitations` all present |
| CON-13 | `score_label` is a member of the bounded value set | `score_label` is one of: `HIGH_CONFIDENCE`, `MODERATE_CONFIDENCE`, `LOW_CONFIDENCE` |
| CON-14 | Stability labels are members of bounded value sets | `success_rate_stability_label` is one of `STABLE`, `DEGRADED`, `INSUFFICIENT_DATA`; `latency_stability_label` is one of `STABLE`, `DEGRADED`, `INSUFFICIENT_DATA` |
| CON-15 | Burst labels are members of bounded value sets | `failure_burst_label` is one of `NO_BURST_DETECTED`, `BURST_SUSPECTED`, `INSUFFICIENT_DATA`; `latency_spike_label` is one of `NO_SPIKE_DETECTED`, `SPIKE_SUSPECTED`, `INSUFFICIENT_DATA` |
| CON-16 | Consistency labels are members of bounded value set | `consistency_label` is one of `CONSISTENT`, `INCONSISTENT`, `INSUFFICIENT_DATA` |
| CON-17 | `composite_score.value` is in range `[0.0, 1.0]` | Score value is a decimal in the closed interval `[0.0, 1.0]` |
| CON-18 | All numeric score fields have exactly 3 decimal places | `composite_score.value`, `success_rate`, per-endpoint `composite_score`, `reliability_score`, `stability_score`, `burst_score`, `consistency_score` all have 3 decimal places |
| CON-19 | `endpoints` array is sorted lexicographically ascending by `endpoint_id` | Given fixture with endpoints `ep_b`, `ep_a`, `ep_c`, the output array order is `ep_a`, `ep_b`, `ep_c` |
| CON-20 | Removing a stable field from fixture causes test failure | Removing `composite_score` from the `IntelligenceMetadata` fixture causes contract test to fail |
| CON-21 | Breaking type change causes test failure | Changing `composite_score` from Number to String in the `IntelligenceMetadata` fixture causes contract test to fail |
| CON-22 | Adding a non-breaking field does not cause test failure | Adding a new field `extra_field` not in the contract causes no contract test to fail |
| CON-23 | Component weights in disclosure match `intel_v1` constants | `reliability.weight = 0.50`, `stability.weight = 0.20`, `burst.weight = 0.15`, `consistency.weight = 0.15` in `component_breakdown` |
| CON-24 | `INSUFFICIENT_DATA` label-to-score mapping is 0.5 | `methodology_disclosure.label_to_score_mapping` maps `INSUFFICIENT_DATA` to `0.5` |

---

## 4. Phase 5.2 — Reliability Metrics Core

### 4.1 Scope

Validate that the intelligence engine correctly derives reliability metrics from Phase 4 `EndpointAggregate` and `FailureClassificationAggregate` fields. These metrics are passthrough operations: no re-computation of raw counts is permitted. All counts are carried from Phase 4 with no augmentation.

### 4.2 Unit Tests — Success Rate Computation

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| MET-SR01 | Success rate from known numerator/denominator | **Given** an `EndpointAggregate` with `success_inputs.numerator = 95` and `success_inputs.denominator = 100`; **When** metrics are derived; **Then** `success_rate = 0.950`, `success_rate_numerator = 95`, `success_rate_denominator = 100` |
| MET-SR02 | Success rate at exactly 100% | **Given** `numerator = 50`, `denominator = 50`; **When** derived; **Then** `success_rate = 1.000` |
| MET-SR03 | Success rate at exactly 0% | **Given** `numerator = 0`, `denominator = 100`; **When** derived; **Then** `success_rate = 0.000`, `fail_count = 100` |
| MET-SR04 | Success rate with fractional result rounds to 3 decimal places half-up | **Given** `numerator = 1`, `denominator = 3`; **When** derived; **Then** `success_rate = 0.333` (half-up rounding applied) |
| MET-SR05 | Zero executions returns INSUFFICIENT_DATA state | **Given** `success_inputs.denominator = 0`; **When** metrics are derived; **Then** `execution_count = 0`, `success_rate` is absent or null, `fail_count = 0`, all analysis labels are `INSUFFICIENT_DATA` |

### 4.3 Unit Tests — Failure Classification Passthrough

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| MET-FC01 | Failure classification breakdown is carried without remapping | **Given** a `FailureClassificationAggregate` with `classification_counts = {"TIMEOUT": 5, "HTTP_ERROR": 3}`; **When** derived; **Then** `failure_classification_breakdown = {"HTTP_ERROR": 3, "TIMEOUT": 5}` with lexicographic key ordering and counts identical |
| MET-FC02 | All approved failure classification labels are carried | All Phase 4 approved labels (`PASS`, `ASSERTION_FAILURE`, `HTTP_ERROR`, `TIMEOUT`, `CONNECTION_ERROR`, `INVALID_RESPONSE`, `RUNNER_ERROR`, `PAYLOAD_VALIDATION_ERROR`, `MISSING_FAILURE_CLASSIFICATION`, `UNKNOWN_FAILURE_CLASSIFICATION`) are carried without renaming when present |
| MET-FC03 | No failure classification labels are added by Phase 5 | **Given** a fixture with only `{"TIMEOUT": 3}`; **When** derived; **Then** `failure_classification_breakdown` contains only `{"TIMEOUT": 3}`; no Phase 5-originated label present |
| MET-FC04 | `timeout_count` matches TIMEOUT classification count | **Given** `classification_counts = {"TIMEOUT": 7}`; **When** derived; **Then** `timeout_count = 7` in `reliability_metrics` |

### 4.4 Unit Tests — Latency Profile Passthrough

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| MET-LAT01 | All six latency percentile values are carried from Phase 4 | **Given** an `EndpointAggregate` with `latency_stats.min_ms = 10`, `max_ms = 500`, `mean_ms = 120`, `median_ms = 100`, `p95_ms = 400`, `p99_ms = 480`; **When** derived; **Then** all six values match exactly in `reliability_metrics` |
| MET-LAT02 | Zero latency count sets all latency fields to null | **Given** `latency_stats.count = 0`; **When** derived; **Then** `latency_min_ms`, `latency_max_ms`, `latency_mean_ms`, `latency_median_ms`, `latency_p95_ms`, `latency_p99_ms` are all null |
| MET-LAT03 | `latency_count` matches Phase 4 latency stats count | **Given** Phase 4 `latency_stats.count = 47`; **When** derived; **Then** `latency_count = 47` in `reliability_metrics` |

### 4.5 Unit Tests — Source Field Refs (Evidence Traceability)

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| MET-REF01 | `source_field_refs` maps each derived field to Phase 4 source | **Given** a known `EndpointAggregate` fixture; **When** derived; **Then** `source_field_refs` is a non-empty map where each key is a derived field name and each value identifies the Phase 4 record type and field |
| MET-REF02 | `source_field_refs` does not contain raw URLs, headers, or PII | Canary injection: given a Phase 4 fixture with a canary value embedded in a prohibited field; when derived; `source_field_refs` values do not contain the canary |

---

## 5. Phase 5.3 — Stability Analysis

### 5.1 Scope

Validate the `success_rate_stability_v1` and `latency_stability_v1` algorithms. These are distributional characterization algorithms applied to Phase 4 aggregate summary statistics. They do not assess temporal trends.

### 5.2 Unit Tests — success_rate_stability_v1

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| STAB-SR01 | STABLE at threshold value | **Given** `success_rate = 0.950`; **When** `success_rate_stability_v1` applied; **Then** `success_rate_stability_label = STABLE` |
| STAB-SR02 | STABLE above threshold | **Given** `success_rate = 1.000`; **When** applied; **Then** `success_rate_stability_label = STABLE` |
| STAB-SR03 | DEGRADED below threshold | **Given** `success_rate = 0.949`; **When** applied; **Then** `success_rate_stability_label = DEGRADED` |
| STAB-SR04 | DEGRADED at zero success rate | **Given** `success_rate = 0.000`; **When** applied; **Then** `success_rate_stability_label = DEGRADED` |
| STAB-SR05 | INSUFFICIENT_DATA at zero executions | **Given** `execution_count = 0`; **When** applied; **Then** `success_rate_stability_label = INSUFFICIENT_DATA` |
| STAB-SR06 | Threshold is exclusive on the DEGRADED side | **Given** `success_rate = 0.9499` (3 decimal places = 0.950 after rounding); confirm threshold comparison uses the rounded value; **Then** label is correct per rounded rate |

### 5.3 Unit Tests — latency_stability_v1

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| STAB-LAT01 | STABLE when p99/mean and max/p95 ratios are within threshold | **Given** `p99_ms = 200`, `mean_ms = 100` (ratio 2.0), `max_ms = 300`, `p95_ms = 200` (ratio 1.5); **When** applied; **Then** `latency_stability_label = STABLE` (assuming thresholds exceed these ratios) |
| STAB-LAT02 | DEGRADED when p99/mean spread ratio exceeds threshold | **Given** spread ratios violating the threshold; **When** applied; **Then** `latency_stability_label = DEGRADED` |
| STAB-LAT03 | INSUFFICIENT_DATA at zero latency count | **Given** `latency_count = 0`; **When** applied; **Then** `latency_stability_label = INSUFFICIENT_DATA` |
| STAB-LAT04 | INSUFFICIENT_DATA when latency fields are null | **Given** `latency_p99_ms = null`, `latency_mean_ms = null`; **When** applied; **Then** `latency_stability_label = INSUFFICIENT_DATA` |

### 5.4 Unit Tests — Methodology Trace Completeness

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| STAB-TR01 | Stability methodology trace contains algorithm name | `methodology_trace.algorithm` is present and equals `success_rate_stability_v1` or `latency_stability_v1` as applicable |
| STAB-TR02 | Stability methodology trace contains version | `methodology_trace.version` or equivalent version field is present |
| STAB-TR03 | Stability methodology trace contains input fields | `methodology_trace` includes the input values used (e.g., `success_rate`, `p99_ms`, `mean_ms`) |
| STAB-TR04 | Stability methodology trace contains thresholds | `methodology_trace` includes the threshold value(s) applied (e.g., `0.95` for success rate) |
| STAB-TR05 | Stability methodology trace contains intermediate values | Computed intermediate values (e.g., spread ratios for latency) are present in `methodology_trace` |
| STAB-TR06 | Stability methodology trace contains label determination explanation | `methodology_trace` includes a human-readable explanation of why the resulting label was assigned |

### 5.5 Unit Tests — Methodology Trace Wording

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| STAB-WD01 | Stability methodology trace states distributional characterization | `methodology_trace` wording includes the phrase "distributional characterization, not temporal assessment" (exact substring match) |
| STAB-WD02 | Stability trace wording is present for both algorithms | Both `success_rate_stability_v1` and `latency_stability_v1` traces include the required phrase |

---

## 6. Phase 5.4 — Burst Analysis

### 6.1 Scope

Validate the `failure_burst_v1` and `latency_spike_v1` algorithms. Both derive burst and spike signals from Phase 4 aggregate summary statistics. `agg_v1` does not carry temporal execution order, so burst timing is not determinable.

### 6.2 Unit Tests — failure_burst_v1

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| BURST-FB01 | NO_BURST_DETECTED when timeout proportion is exactly 0.20 | **Given** `timeout_count = 20`, `execution_count = 100` (ratio 0.200); **When** `failure_burst_v1` applied; **Then** `failure_burst_label = NO_BURST_DETECTED` (≤0.20 is non-burst) |
| BURST-FB02 | BURST_SUSPECTED when timeout proportion exceeds 0.20 | **Given** `timeout_count = 21`, `execution_count = 100` (ratio 0.210); **When** applied; **Then** `failure_burst_label = BURST_SUSPECTED` |
| BURST-FB03 | NO_BURST_DETECTED when zero timeouts | **Given** `timeout_count = 0`, `execution_count = 50` (ratio 0.0); **When** applied; **Then** `failure_burst_label = NO_BURST_DETECTED` |
| BURST-FB04 | BURST_SUSPECTED when timeout proportion is high | **Given** `timeout_count = 10`, `execution_count = 30` (ratio 0.333); **When** applied; **Then** `failure_burst_label = BURST_SUSPECTED` |
| BURST-FB05 | INSUFFICIENT_DATA when execution count is below MIN_EXECUTION_COUNT | **Given** `execution_count = 9` (below `MIN_EXECUTION_COUNT = 10`); **When** applied; **Then** `failure_burst_label = INSUFFICIENT_DATA` |
| BURST-FB06 | INSUFFICIENT_DATA when zero executions | **Given** `execution_count = 0`; **When** applied; **Then** `failure_burst_label = INSUFFICIENT_DATA` |
| BURST-FB07 | Threshold comparison is exclusive (>0.20 triggers BURST_SUSPECTED) | **Given** `timeout_count = 200`, `execution_count = 999` (ratio 0.2002); **When** applied; **Then** `failure_burst_label = BURST_SUSPECTED`; boundary at exactly 0.200 returns NO_BURST_DETECTED |

### 6.3 Unit Tests — latency_spike_v1

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| BURST-LS01 | NO_SPIKE_DETECTED when max/p99 ratio is exactly 3.0 | **Given** `max_ms = 300`, `p99_ms = 100` (ratio 3.0); **When** `latency_spike_v1` applied; **Then** `latency_spike_label = NO_SPIKE_DETECTED` (≤3.0 is non-spike) |
| BURST-LS02 | SPIKE_SUSPECTED when max/p99 ratio exceeds 3.0 | **Given** `max_ms = 301`, `p99_ms = 100` (ratio 3.01); **When** applied; **Then** `latency_spike_label = SPIKE_SUSPECTED` |
| BURST-LS03 | NO_SPIKE_DETECTED when ratio is below threshold | **Given** `max_ms = 200`, `p99_ms = 150` (ratio 1.33); **When** applied; **Then** `latency_spike_label = NO_SPIKE_DETECTED` |
| BURST-LS04 | INSUFFICIENT_DATA when latency count is below minimum threshold | **Given** latency count below minimum; **When** applied; **Then** `latency_spike_label = INSUFFICIENT_DATA` |
| BURST-LS05 | INSUFFICIENT_DATA when latency fields are null | **Given** `latency_p99_ms = null`, `latency_max_ms = null`; **When** applied; **Then** `latency_spike_label = INSUFFICIENT_DATA` |

### 6.4 Unit Tests — Burst Methodology Trace Completeness

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| BURST-TR01 | Burst trace contains algorithm name | `methodology_trace.algorithm` is `failure_burst_v1` or `latency_spike_v1` as applicable |
| BURST-TR02 | Burst trace contains input values | `timeout_count`, `execution_count`, and computed ratio (or latency values and ratio) are present in trace |
| BURST-TR03 | Burst trace contains threshold | Threshold value `0.20` (for burst) or `3.0` (for spike) is present in trace |
| BURST-TR04 | Burst trace contains intermediate ratio | The computed `timeout_count / execution_count` ratio (or `max / p99` ratio) is present as an intermediate value |
| BURST-TR05 | Burst trace contains label determination explanation | Human-readable explanation of why the label was assigned is present |

### 6.5 Unit Tests — Burst Methodology Trace Wording

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| BURST-WD01 | Burst trace states temporal burst timing is not determinable | `methodology_trace` wording includes a statement that temporal burst timing is not determinable from `agg_v1` data (exact required phrase documented in technical design; substring match) |
| BURST-WD02 | Wording present in both burst and spike traces | Both `failure_burst_v1` and `latency_spike_v1` traces include the required temporal limitation statement |

---

## 7. Phase 5.5 — Consistency Analysis

### 7.1 Scope

Validate the `outcome_consistency_v1` algorithm. This algorithm uses Bernoulli variance `p*(1-p)` applied to the aggregate-level success rate `p`. Per-run data is not available from `agg_v1` and must not be accessed.

### 7.2 Unit Tests — outcome_consistency_v1 Labels

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| CONS-OC01 | CONSISTENT when Bernoulli variance is exactly 0.05 | **Given** `p` such that `p*(1-p) = 0.05` (e.g., `p ≈ 0.0528` or `p ≈ 0.9472`); **When** `outcome_consistency_v1` applied; **Then** `consistency_label = CONSISTENT` (≤0.05 is consistent) |
| CONS-OC02 | CONSISTENT when variance is below threshold | **Given** `success_rate = 1.000` → variance `1.0 * 0.0 = 0.000`; **When** applied; **Then** `consistency_label = CONSISTENT` |
| CONS-OC03 | CONSISTENT when success rate is 0.0 | **Given** `success_rate = 0.000` → variance `0.0 * 1.0 = 0.000`; **When** applied; **Then** `consistency_label = CONSISTENT` (perfectly uniform failure is consistent) |
| CONS-OC04 | INCONSISTENT when Bernoulli variance exceeds 0.05 | **Given** `success_rate = 0.5` → variance `0.5 * 0.5 = 0.25 > 0.05`; **When** applied; **Then** `consistency_label = INCONSISTENT` |
| CONS-OC05 | INCONSISTENT at maximum variance | **Given** `success_rate = 0.5` (maximum variance); **When** applied; **Then** `consistency_label = INCONSISTENT` |
| CONS-OC06 | INSUFFICIENT_DATA when execution count is below minimum threshold | **Given** `execution_count` below minimum consistency characterization threshold; **When** applied; **Then** `consistency_label = INSUFFICIENT_DATA` |
| CONS-OC07 | INSUFFICIENT_DATA when zero executions | **Given** `execution_count = 0`; **When** applied; **Then** `consistency_label = INSUFFICIENT_DATA` |

### 7.3 Unit Tests — Bernoulli Variance Formula Accuracy

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| CONS-VAR01 | Variance formula computed as p*(1-p) using the aggregate success rate | **Given** `success_rate = 0.8`; **When** variance computed; **Then** intermediate value `variance = 0.8 * 0.2 = 0.16` is present in `methodology_trace` |
| CONS-VAR02 | Variance comparison uses the rounded success rate | **Given** `numerator = 1`, `denominator = 3` → `success_rate = 0.333`; **When** variance computed; **Then** variance = `0.333 * 0.667 = 0.222`; not the unrounded `0.3333...` value |

### 7.4 Unit Tests — Consistency Methodology Trace Completeness

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| CONS-TR01 | Consistency trace contains algorithm name | `methodology_trace.algorithm = outcome_consistency_v1` |
| CONS-TR02 | Consistency trace contains input `p` value | The success rate `p` used as input is present in `methodology_trace` |
| CONS-TR03 | Consistency trace contains computed variance | `p*(1-p)` intermediate value is present in `methodology_trace` |
| CONS-TR04 | Consistency trace contains threshold | Threshold value `0.05` is present in `methodology_trace` |
| CONS-TR05 | Consistency trace contains label determination explanation | Human-readable explanation of the label assignment is present |

### 7.5 Unit Tests — Consistency Methodology Trace Wording

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| CONS-WD01 | Consistency trace states per-run data not available from agg_v1 | `methodology_trace` wording includes a statement that per-run data is not available from `agg_v1` (exact required phrase documented in technical design; substring match) |

---

## 8. Phase 5.6 — Release Confidence Scoring

### 8.1 Scope

Validate the composite scoring pipeline including per-endpoint score computation, audit-level rollup, label assignment, and score precision. Scoring uses `intel_v1` fixed weights and a label-to-score mapping. All scores must be computed using Python `Decimal` with half-up rounding to 3 decimal places.

### 8.2 Unit Tests — Per-Endpoint Composite Score

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| SCORE-EP01 | Per-endpoint composite score uses correct weights | **Given** `reliability_score = 1.0`, `stability_score = 1.0`, `burst_score = 1.0`, `consistency_score = 1.0`; **When** scored; **Then** `endpoint_composite_score = 1.0 * 0.50 + 1.0 * 0.20 + 1.0 * 0.15 + 1.0 * 0.15 = 1.000` |
| SCORE-EP02 | Zero-execution endpoint: reliability_score = 0.0; secondary INSUFFICIENT_DATA components = 0.5 | **Given** `execution_count = 0` and all analysis labels are `INSUFFICIENT_DATA`; **When** scored; **Then** `reliability_score = 0.0` (no evidence — evidence-first principle per Technical Design Section 13.3 Step 1), `stability_score = 0.5`, `burst_score = 0.5`, `consistency_score = 0.5`; `endpoint_composite_score = 0.0 * 0.50 + 0.5 * 0.20 + 0.5 * 0.15 + 0.5 * 0.15 = 0.000 + 0.100 + 0.075 + 0.075 = 0.250`. Note: `INSUFFICIENT_DATA_SCORE = 0.5` applies exclusively to secondary analytical components (stability, burst, consistency); it does not apply to the primary reliability component. |
| SCORE-EP03 | Mixed INSUFFICIENT_DATA and actual scores compute correctly | **Given** `reliability_score = 0.9`, `stability_score = 0.5` (INSUFFICIENT_DATA), `burst_score = 0.5` (INSUFFICIENT_DATA), `consistency_score = 0.5` (INSUFFICIENT_DATA); **When** scored; **Then** `endpoint_composite_score = 0.9 * 0.50 + 0.5 * 0.20 + 0.5 * 0.15 + 0.5 * 0.15 = 0.450 + 0.100 + 0.075 + 0.075 = 0.700` |
| SCORE-EP04 | Weights sum to exactly 1.0 | `0.50 + 0.20 + 0.15 + 0.15 = 1.00`; confirmed via constants validation |
| SCORE-EP05 | Score precision is 3 decimal places | **Given** a computation that yields an unrounded value (e.g., `0.9 * 0.50 + 0.8 * 0.20 + 0.9 * 0.15 + 0.7 * 0.15`); **When** scored; **Then** result is rounded to exactly 3 decimal places using half-up rounding |
| SCORE-EP06 | Per-endpoint score is clamped to `[0.0, 1.0]` | No score may be less than 0.0 or greater than 1.0 |
| SCORE-EP07 | `reliability_score` is the success rate value | **Given** `success_rate = 0.870`; **When** scored; **Then** `reliability_score = 0.870` in `endpoint_score` |

### 8.3 Unit Tests — Score Label Assignment at Boundaries

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| SCORE-LB01 | HIGH_CONFIDENCE at exactly 0.80 | **Given** `composite_score.value = 0.800`; **When** label assigned; **Then** `score_label = HIGH_CONFIDENCE` |
| SCORE-LB02 | HIGH_CONFIDENCE above 0.80 | **Given** `composite_score.value = 0.801`; **When** label assigned; **Then** `score_label = HIGH_CONFIDENCE` |
| SCORE-LB03 | HIGH_CONFIDENCE at 1.000 | **Given** `composite_score.value = 1.000`; **Then** `score_label = HIGH_CONFIDENCE` |
| SCORE-LB04 | MODERATE_CONFIDENCE just below 0.80 | **Given** `composite_score.value = 0.799`; **Then** `score_label = MODERATE_CONFIDENCE` |
| SCORE-LB05 | MODERATE_CONFIDENCE at exactly 0.50 | **Given** `composite_score.value = 0.500`; **Then** `score_label = MODERATE_CONFIDENCE` |
| SCORE-LB06 | LOW_CONFIDENCE just below 0.50 | **Given** `composite_score.value = 0.499`; **Then** `score_label = LOW_CONFIDENCE` |
| SCORE-LB07 | LOW_CONFIDENCE at 0.000 | **Given** `composite_score.value = 0.000`; **Then** `score_label = LOW_CONFIDENCE` |
| SCORE-LB08 | No other score_label values are produced | Score labels are exclusively `HIGH_CONFIDENCE`, `MODERATE_CONFIDENCE`, or `LOW_CONFIDENCE`; no other string value is ever produced |

### 8.4 Unit Tests — Audit-Level Composite Rollup

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| SCORE-ROLL01 | Audit composite score is unweighted mean of per-endpoint scores | **Given** two endpoints with `endpoint_composite_score = 0.900` and `endpoint_composite_score = 0.700`; **When** audit rollup computed; **Then** `audit_composite_score = (0.900 + 0.700) / 2 = 0.800` |
| SCORE-ROLL02 | Single endpoint audit uses that endpoint's score | **Given** one endpoint with `endpoint_composite_score = 0.750`; **Then** `audit_composite_score = 0.750` |
| SCORE-ROLL03 | Three-endpoint rollup computes arithmetic mean | **Given** endpoints with scores `0.900`, `0.800`, `0.700`; **Then** `audit_composite_score = 0.800` |
| SCORE-ROLL04 | Rollup result has exactly 3 decimal places | Rollup result is rounded to 3 decimal places half-up using Python `Decimal` |
| SCORE-ROLL05 | `endpoint_count` in composite_score matches number of scored endpoints | **Given** three endpoints scored; **Then** `composite_score.endpoint_count = 3` |

### 8.5 Unit Tests — Evidence Trace in Endpoint Score

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| SCORE-EV01 | Per-endpoint evidence trace includes `aggregate_set_hash` | **Given** a known `AggregateSetCompletion.aggregate_set_hash`; **When** per-endpoint score produced; **Then** the hash is present in the endpoint evidence trace |
| SCORE-EV02 | Per-endpoint evidence trace includes all component scores | `reliability_score`, `stability_score`, `burst_score`, `consistency_score` are all present in per-endpoint evidence trace or `score_derivation` |

### 8.6 Unit Tests — Methodology Disclosure in S3 Artifact

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| SCORE-DISC01 | `methodology_disclosure` section is present in every S3 artifact | Artifact fixture always contains `methodology_disclosure` at the top level |
| SCORE-DISC02 | `limitations` array is present and non-empty | `methodology_disclosure.limitations` is a non-empty array |
| SCORE-DISC03 | `scoring.per_endpoint_formula` is present | The exact weighted formula string is present in `methodology_disclosure.scoring.per_endpoint_formula` |

---

## 9. Phase 5.7 — Engineering Retrieval CLI

### 9.1 Scope

Validate all retrieval commands that expose Phase 5 intelligence output to operators. Retrieval commands are unconditionally read-only. No Phase 5 DynamoDB record or S3 artifact may be mutated by a retrieval command.

### 9.2 Unit Tests — Command Correctness

| Test ID | Command | Pass Criteria |
| --- | --- | --- |
| IRET-U01 | `retrieve intelligence-summary` | Returns all `IntelligenceMetadata` stable fields: `intelligence_version`, `intelligence_job_id`, `client_id`, `audit_id`, `audit_execution_id`, `config_version`, `aggregation_version`, `status`, `composite_score`, `score_label`, `endpoint_count`, `s3_artifact_ref`, `aggregate_set_hash`, `created_at`, `completed_at` |
| IRET-U02 | `retrieve intelligence-detail` | Returns full S3 artifact content including all top-level sections: identity/provenance, `audit_reliability_summary`, `composite_score`, `input_lineage`, `endpoints`, `methodology_disclosure` |
| IRET-U03 | `retrieve intelligence-methodology` | Returns the `methodology_disclosure` section from the S3 artifact; all sub-fields present |
| IRET-U04 | `retrieve intelligence-status` | Returns current `status` field and `intelligence_job_id` from `IntelligenceMetadata`; `failure_reason` if `status = FAILED` |
| IRET-U05 | `retrieve intelligence-summary` for FAILED job returns structured failure metadata | `failure_reason` is present; `composite_score` and `score_label` are absent |
| IRET-U06 | `retrieve intelligence-detail` for non-existent audit returns controlled not-found | Structured empty or not-found response; no unhandled exception |

### 9.3 Unit Tests — Output Format and Provenance

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| IRET-F01 | `--output json` produces well-formed JSON | `json.loads()` succeeds; no parsing error |
| IRET-F02 | `--output human` produces readable formatted output | Output is non-empty; key labels match expected field names |
| IRET-F03 | JSON output field ordering is deterministic | Two independent invocations for same audit state produce byte-identical JSON |
| IRET-F04 | Default output format is human-readable | Command without `--output` flag defaults to human format |
| IRET-PROV01 | Every JSON output includes provenance envelope | Top-level `retrieved_at`, `retrieval_version`, `intelligence_version`, `audit_id`, `client_id`, `intelligence_job_id` all present |
| IRET-PROV02 | Every JSON output includes `_notice` field | `_notice` contains the engineering diagnostic disclaimer string |
| IRET-PROV03 | Human-readable output includes disclaimer | Disclaimer text appears before any data in human-readable format |
| IRET-REPR01 | Byte-identical JSON for same persisted state | Two independent retrieval calls against the same `IntelligenceMetadata` and S3 artifact produce identical serialized JSON bytes |

### 9.4 Unit Tests — Sensitive Data Exclusion

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| IRET-S01 | Retrieval output contains no raw request or response bodies | No raw HTTP body content in any retrieval output field |
| IRET-S02 | Retrieval output contains no raw headers, cookies, or tokens | No header values in any log or retrieval event field |
| IRET-S03 | Retrieval output contains no credentials, secrets, or PII | Canary token injection: canary value not present in any retrieval output |
| IRET-S04 | `endpoint_id` values in output are sanitized Phase 4 identifiers | No raw URL patterns, path parameters, or query strings in `endpoint_id` fields |
| IRET-S05 | `s3_artifact_ref` contains only the sanitized S3 key path | `s3_artifact_ref` value matches `intelligence/{client_id}/{audit_id}/...` structure; no raw URLs or payload fragments |

### 9.5 Unit Tests — Retrieval Read-Only Invariant

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| IRET-RO01 | All retrieval commands produce no DynamoDB mutations | DynamoDB state before and after a retrieval command invocation is identical (verified by mock call capture) |
| IRET-RO02 | All retrieval commands produce no S3 mutations | S3 write calls are not invoked by any retrieval command |

---

## 10. Phase 5.8 — Validation Campaign

### 10.1 Campaign Requirements

Phase 5.8 is an operational validation campaign, not a PR. It requires execution against live 48-hour audit data. Unit and integration tests from Phases 5.1–5.7 are necessary but not sufficient for Phase 5.8 closure.

**Minimum campaign requirement:** At least two independent 48-hour audit campaigns demonstrating all Phase 5 success criteria.

### 10.2 Campaign Success Criteria

Each 48-hour campaign must demonstrate all of the following:

| Criteria | Evidence Required |
| --- | --- |
| Phase 4 aggregation is COMPLETE before intelligence invocation | `AggregateSetCompletion` marker present; `AggregationJob.status = COMPLETED` confirmed before CLI invocation |
| Intelligence job reaches COMPLETE deterministically | `IntelligenceJob.status = COMPLETE`; `IntelligenceMetadata.status = COMPLETE` after invocation |
| S3 artifact written and retrievable | `retrieve intelligence-detail` returns valid artifact; `s3_artifact_ref` resolves to accessible S3 object |
| DynamoDB records are correct | `IntelligenceJob` and `IntelligenceMetadata` both present; all required fields non-null |
| Composite score is in `[0.0, 1.0]` | `composite_score` value within bounds; `score_label` in bounded set |
| All endpoint analyses present | Each endpoint in S3 artifact contains `reliability_metrics`, `stability_analysis`, `burst_analysis`, `consistency_analysis`, `endpoint_score` |
| Methodology trace is complete | `methodology_disclosure` section present; all required sub-fields present |
| `aggregate_set_hash` traces to Phase 4 | `IntelligenceMetadata.aggregate_set_hash` matches `AggregateSetCompletion.aggregate_set_hash` from Phase 4 |
| Retrieval CLI returns deterministic results | `retrieve intelligence-summary` output is identical across two independent invocations |
| Idempotency confirmed | Re-invoking without `--force` returns a rejection; no new artifact written |
| Force re-generation produces new IntelligenceJob | Invoking with `--force` produces a new `IntelligenceJob` record with a new `intelligence_job_id`; previous artifact preserved at original S3 key |
| Phase 4 records unmodified | Phase 4 DynamoDB records are identical before and after Phase 5 invocation |
| No operational regressions | All prior Phase 3/4 tests continue to pass |

### 10.3 Campaign Documentation

Each campaign requires:

- Campaign start and end timestamps.
- Audit identifiers used.
- Phase 4 aggregation job ID and completion timestamp.
- Intelligence job ID, invocation timestamp, and completion timestamp.
- `composite_score` value and `score_label`.
- `aggregate_set_hash` value linking to Phase 4.
- Full `retrieve intelligence-summary` output in JSON format.
- `retrieve intelligence-status` output before and after invocation.
- Idempotency test result (second invocation rejection evidence).
- Any failure events observed during the campaign and their resolution.

### 10.4 HITL Gate

Phase 5.8 closes only upon HITL approval after at least two successful 48-hour campaigns are documented. Phase 5 is not considered complete without this gate.

---

## 11. Cross-Cutting Tests

### 11.1 Determinism

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| XCUT-DET01 | Byte-identical S3 artifact JSON for identical Phase 4 inputs | **Given** two independent Phase 5 invocations for the same Phase 4 aggregate fixture; **When** both write S3 artifacts; **Then** both artifact JSON byte strings are identical |
| XCUT-DET02 | Byte-identical artifact after simulated re-computation from same aggregate fixture | Deserializing and re-serializing the artifact JSON produces identical bytes |
| XCUT-DET03 | `endpoints` array order is deterministic across invocations | Array position of each endpoint is identical in both independent invocations |
| XCUT-DET04 | `failure_classification_breakdown` key ordering is deterministic | Keys are lexicographic ascending; order is identical across invocations |

### 11.2 AggregateSetCompletion Gate

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| XCUT-GATE01 | Absence of AggregateSetCompletion marker causes hard stop | **Given** Phase 4 aggregate records present but `AggregateSetCompletion` marker absent; **When** Phase 5 invoked; **Then** pipeline stops immediately; no S3 artifact written; structured error returned with reason `AGG_SET_NOT_COMPLETE` or equivalent |
| XCUT-GATE02 | Partial Phase 4 aggregate set without completion marker causes hard stop | **Given** only `AuditAggregate` and `EndpointAggregate` records present, no `AggregateSetCompletion`; **When** Phase 5 invoked; **Then** same hard stop behavior as XCUT-GATE01 |
| XCUT-GATE03 | Hard stop produces no IntelligenceJob record in PENDING state | When the gate blocks invocation, no `IntelligenceJob` DynamoDB record is written |

### 11.3 Phase 4 Non-Mutation

Test file: `tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py`

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| XCUT-P4M01 | Phase 5 repository write methods only write to Phase 5 SK namespaces | All Phase 5 `repository.py` write operations target SK patterns containing `#INTJOB#` or `#INTEL#`; no write is attempted to any Phase 4-namespaced SK |
| XCUT-P4M02 | Phase 5 does not write to `#AGGJOB#` SK prefix | Mock assertion: no DynamoDB `PutItem`, `UpdateItem`, or `DeleteItem` call is made with SK containing `#AGGJOB#` |
| XCUT-P4M03 | Phase 5 does not write to `#SET` SK suffix | No write to `AggregateSetCompletion` SK pattern from Phase 5 |
| XCUT-P4M04 | Phase 5 does not write to `#AUDIT` SK suffix | No write to `AuditAggregate` SK pattern from Phase 5 |
| XCUT-P4M05 | Phase 5 does not write to `#ENDPOINT#` SK prefix | No write to `EndpointAggregate` or `FailureClassificationAggregate` SK patterns from Phase 5 |
| XCUT-P4M06 | Phase 5 does not write to `#LINEAGE#` SK prefix | No write to `LineageManifest` SK pattern from Phase 5 |
| XCUT-P4M07 | Phase 5 does not write to `#EXECUTION_ID` SK | No write to `AuditExecutionIdentity` SK pattern from Phase 5 |
| XCUT-P4M08 | Phase 5 does not write to `#RUN#` SK prefix | No write to Phase 1/3 run metadata SK patterns from Phase 5 |

### 11.4 No Raw Evidence Access

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| XCUT-RAW01 | Phase 5 does not read from S3 `raw-results/` key prefix | Mock assertion: no S3 `GetObject` call with key matching `raw-results/*` is made by Phase 5 |
| XCUT-RAW02 | Phase 5 does not query Phase 1/2/3 DynamoDB record types | No DynamoDB query or get-item call targets SK patterns belonging to Phase 1, 2, or 3 records (`#RUN#`, `SCHEDULED_EXECUTION`, `EVENT#`, etc.) |
| XCUT-RAW03 | Phase 5 reads only the Phase 4 SK query pattern defined in consumer contract | The only Phase 4 DynamoDB access pattern used is `SK begins_with AUDIT#{id}#EXEC#{id}#CFG#{v}#AGG#{v}#` per `docs/architecture/phase_4a_phase5_consumer_contract.md` |

### 11.5 Idempotency

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| XCUT-IDEM01 | Re-invocation without `--force` is rejected | **Given** `IntelligenceMetadata.status = COMPLETE`; **When** Phase 5 invoked again without `--force`; **Then** invocation rejected; structured error returned; no new `IntelligenceJob` created; existing artifact not overwritten |
| XCUT-IDEM02 | Force re-generation produces new IntelligenceJob with new job ID | **Given** `IntelligenceMetadata.status = COMPLETE`; **When** Phase 5 invoked with `--force`; **Then** new `IntelligenceJob` record created with new `intelligence_job_id`; `IntelligenceMetadata.generation_count` incremented; previous S3 artifact preserved at original key |
| XCUT-IDEM03 | Force re-generation updates `IntelligenceMetadata` fields | `intelligence_job_id`, `composite_score`, `score_label`, `endpoint_count`, `s3_artifact_ref`, `completed_at`, `updated_at`, `generation_count` are updated; `created_at` is unchanged |
| XCUT-IDEM04 | Re-invocation for FAILED job proceeds without `--force` | **Given** `IntelligenceMetadata.status = FAILED`; **When** Phase 5 invoked without `--force`; **Then** new attempt proceeds (FAILED is not a completed terminal state that requires force override) |

### 11.6 S3 Write Before DynamoDB COMPLETE

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| XCUT-ORD01 | S3 artifact is written before DynamoDB status is set to COMPLETE | **Given** a mock pipeline that captures write call ordering; **When** pipeline completes successfully; **Then** `S3.PutObject` call occurs before `DynamoDB.UpdateItem` setting `status = COMPLETE` |
| XCUT-ORD02 | S3 write failure prevents DynamoDB COMPLETE status | **Given** S3 write raises an exception; **When** pipeline handles the exception; **Then** `IntelligenceJob.status` is set to `FAILED`; `IntelligenceMetadata.status` is `FAILED`; no `COMPLETE` status is written |

### 11.7 Consumer Contract Compatibility Gate (Cross-Cutting)

| Test ID | Test Description | Pass Criteria |
| --- | --- | --- |
| XCUT-CCG01 | `tests/unit/test_phase6_consumer_contract.py` must pass for all Phase 5 changes | The compatibility gate test suite passes with zero failures before any Phase 5 implementation change is considered complete |

---

## 12. Test Fixture Requirements

### 12.1 Fixture Source Constraint

All Phase 5 unit test fixtures must be derived from Phase 4 `agg_v1` aggregate fields only. The following Phase 4 record fields are the only permitted fixture inputs:

- `EndpointAggregate`: `endpoint_id`, `request_counts`, `success_inputs`, `latency_stats`, `http_response_distribution`, `aggregation_version`
- `FailureClassificationAggregate`: `endpoint_id`, `classification_counts`, `aggregation_version`
- `AuditAggregate`: `total_request_count`, `total_pass_count`, `total_fail_count`, `audit_execution_id`, `config_version`, `aggregation_version`
- `AggregateSetCompletion`: `aggregate_set_hash`, `aggregation_job_id`, `aggregation_version`, `created_at`, `endpoint_aggregate_count`, `source_raw_result_count`

No fixture may contain raw HTTP bodies, raw headers, raw S3 result content, or any Phase 1/2/3 record structure.

### 12.2 Required Fixture Coverage

The following fixtures must exist and be used by Phase 5.2–5.7 tests:

| Fixture Name | Description | Required For |
| --- | --- | --- |
| `fixture_endpoint_fully_passing` | `success_inputs.numerator = success_inputs.denominator`, non-zero; latency data present; no failures | MET, STAB, SCORE: STABLE and HIGH_CONFIDENCE paths |
| `fixture_endpoint_with_failures` | `numerator < denominator`, `classification_counts` has TIMEOUT and HTTP_ERROR; latency data present | MET-FC, BURST, CONS: INCONSISTENT and BURST_SUSPECTED paths |
| `fixture_endpoint_insufficient_data` | `denominator = 0` or denominator below minimum threshold for all algorithms | STAB-SR05, STAB-LAT03, BURST-FB06, CONS-OC07: all INSUFFICIENT_DATA paths |
| `fixture_endpoint_burst_suspected` | `timeout_count / execution_count > 0.20` (e.g., `timeout_count = 21`, `execution_count = 100`) | BURST-FB02: BURST_SUSPECTED path |
| `fixture_endpoint_spike_suspected` | `latency_max_ms / latency_p99_ms > 3.0` | BURST-LS02: SPIKE_SUSPECTED path |
| `fixture_agg_set_completion` | Valid `AggregateSetCompletion` marker with known `aggregate_set_hash` | XCUT-GATE: prerequisite gate tests; SCORE-EV01: evidence trace |
| `fixture_multi_endpoint_audit` | Three or more endpoints with distinct `endpoint_id` values in non-lexicographic order | CON-19, SCORE-ROLL01, XCUT-DET03: ordering and rollup tests |

---

## 13. Acceptance Criteria Traceability

| Acceptance Criterion | Description | Test Case(s) |
| --- | --- | --- |
| AC-P1 | S3 immutable intelligence artifact written on successful run | XCUT-ORD01, XCUT-GATE01 (negation), CON-03 |
| AC-P2 | `IntelligenceJob` DynamoDB record written per invocation | CON-01, XCUT-IDEM02 |
| AC-P3 | `IntelligenceMetadata` DynamoDB record written per combination | CON-01, XCUT-IDEM03 |
| AC-P4 | `success_rate_stability_v1` correctly classifies STABLE, DEGRADED, INSUFFICIENT_DATA | STAB-SR01 through STAB-SR06 |
| AC-P5 | `latency_stability_v1` correctly classifies using spread ratios | STAB-LAT01 through STAB-LAT04 |
| AC-P6 | `failure_burst_v1` correctly classifies using >0.20 timeout proportion | BURST-FB01 through BURST-FB07 |
| AC-P7 | `latency_spike_v1` correctly classifies using max/p99 ratio >3.0 | BURST-LS01 through BURST-LS05 |
| AC-P8 | `outcome_consistency_v1` correctly classifies using Bernoulli variance >0.05 | CONS-OC01 through CONS-OC07, CONS-VAR01, CONS-VAR02 |
| AC-P9 | Composite score computed with correct weights (0.50/0.20/0.15/0.15) | SCORE-EP01 through SCORE-EP07 |
| AC-P10 | INSUFFICIENT_DATA contributes 0.5 (neutral) to secondary analytical components (stability, burst, consistency); reliability_score = 0.0 when execution_count = 0 per evidence-first principle | SCORE-EP02, SCORE-EP03 |
| AC-P11 | Score labels correctly assigned at boundaries (0.80, 0.50) | SCORE-LB01 through SCORE-LB08 |
| AC-P12 | Unweighted arithmetic mean rollup for audit composite score | SCORE-ROLL01 through SCORE-ROLL05 |
| AC-P13 | Phase 4 records never mutated by Phase 5 | XCUT-P4M01 through XCUT-P4M08 |
| AC-P14 | Determinism: identical Phase 4 inputs produce byte-identical S3 artifact | XCUT-DET01 through XCUT-DET04, IRET-REPR01 |
| AC-P15 | AggregateSetCompletion gate hard stops and produces no artifact when marker absent | XCUT-GATE01 through XCUT-GATE03 |
| AC-P16 | Phase 5 never reads raw evidence (S3 raw-results or Phase 1/2/3 DynamoDB records) | XCUT-RAW01 through XCUT-RAW03 |
| AC-P17 | Re-invocation without `--force` rejected; with `--force` produces new IntelligenceJob | XCUT-IDEM01 through XCUT-IDEM04 |
| AC-P18 | S3 artifact written before DynamoDB COMPLETE status set | XCUT-ORD01, XCUT-ORD02 |
| AC-P19 | Engineering Retrieval CLI returns correct data for all retrieval command variants | IRET-U01 through IRET-U06 |
| AC-P20 | Retrieval output format correctness, provenance, determinism | IRET-F01 through IRET-REPR01 |
| AC-P21 | Retrieval sensitive data exclusion | IRET-S01 through IRET-S05 |
| AC-P22 | Phase 6 consumer contract compatibility gate passes | CON-01 through CON-24, XCUT-CCG01 |
| AC-P23 | Methodology trace completeness for all three analysis types | STAB-TR01 through STAB-TR06, BURST-TR01 through BURST-TR05, CONS-TR01 through CONS-TR05 |
| AC-P24 | Required wording present in methodology traces (distributional characterization; temporal burst limitation; per-run data limitation) | STAB-WD01, STAB-WD02, BURST-WD01, BURST-WD02, CONS-WD01 |
| AC-P25 | Failure classification labels carried from Phase 4 without remapping | MET-FC01, MET-FC02, MET-FC03 |
| AC-P26 | Latency profile fields carried from Phase 4 without recomputation | MET-LAT01, MET-LAT02, MET-LAT03 |
| AC-P27 | DynamoDB PK/SK patterns for IntelligenceJob and IntelligenceMetadata are correct | XCUT-P4M01 (positive form: only Phase 5 SK patterns are written) |
| AC-P28 | Phase 5.8 validation campaign: live 48-hour audit data demonstrating all pipeline criteria | Phase 5.8 campaign documentation per Section 10.3 |

---

## 14. QA Sign-Off Criteria

Phase 5 QA sign-off requires all of the following. No partial approval is issued.

### 14.1 Automated Test Requirements

All of the following test suites must pass with zero failures:

| Suite | Pass Requirement |
| --- | --- |
| `tests/unit/test_phase6_consumer_contract.py` | Zero failures; this is the compatibility gate |
| `tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py` | Zero failures; this is the mutation guard |
| `tests/unit/reliability_intelligence/` (all algorithm unit tests) | Zero failures |
| `tests/unit/retrieval/` (Phase 5 retrieval additions) | Zero failures |
| `tests/integration/` (Phase 5 integration tests) | Zero failures |
| All prior Phase 3/4 regression suites | Zero regressions: `tests/unit/aggregation/`, `tests/integration/test_phase3_cancellation_finalization.py`, `tests/integration/test_phase3_lifecycle_determinism_regression.py`, `tests/unit/test_handler_import_smoke.py` |
| `python -m ruff check src/ apps/ tests/` | Zero linting errors |

### 14.2 Evidence Requirements

| Evidence Item | Required |
| --- | --- |
| Test execution output showing zero failures across all suites | Yes |
| Two completed 48-hour campaign documentation files per Section 10.3 | Yes |
| `retrieve intelligence-summary` JSON output from each campaign | Yes |
| Idempotency confirmation (second invocation rejection output) | Yes |
| `aggregate_set_hash` cross-reference confirming Phase 4 lineage trace | Yes |

### 14.3 Blocking Defect Policy

Any single failure in the following categories blocks Phase 5.8 closure regardless of all other results:

- Phase 4 mutation detected (any XCUT-P4M test failure)
- AggregateSetCompletion gate bypassed (any XCUT-GATE test failure)
- S3 written after DynamoDB COMPLETE (XCUT-ORD01 failure)
- Incorrect algorithm threshold (any boundary test failure in STAB, BURST, CONS, SCORE-LB sections)
- Phase 6 consumer contract compatibility gate failure (any CON test failure)
- Raw evidence accessed (any XCUT-RAW test failure)
- Incorrect score weight (SCORE-EP01 failure or weight constant divergence)
- Secondary analytical component (stability, burst, or consistency) with INSUFFICIENT_DATA contributing a value other than 0.5 (SCORE-EP02 failure); or reliability_score returning a non-zero value when execution_count = 0

### 14.4 HITL Gate

Phase 5.8 closes only upon:

1. All automated test requirements in 14.1 satisfied.
2. All evidence items in 14.2 present.
3. No blocking defects per 14.3.
4. Human reviewer issues: `HITL validation successful`

---

## 15. Regression Requirements

All tests from the following suites must continue to pass throughout Phase 5 development:

- `tests/unit/aggregation/` (Phase 4 aggregation unit tests)
- `tests/integration/test_phase3_cancellation_finalization.py`
- `tests/integration/test_phase3_lifecycle_determinism_regression.py`
- `tests/unit/test_handler_import_smoke.py`
- `tests/unit/test_aggregation_trigger_real_repository_wiring.py`
- `tests/unit/test_evidence_integrity_gate_failed_runs.py`
- `tests/unit/test_phase5_consumer_contract.py` (Phase 4→Phase 5 consumer contract gate)
- `tests/integration/test_phase4a4_aggregation_persistence_integration.py`
- `tests/integration/test_phase4a5_retrieval_integration.py`
