# Validation Specification

## Phase 7 — Audit Platform Integrity

---

## 1. Document Purpose

This document defines all validation rules that Phase 7 must satisfy at the level of individual, testable checks. It is the reference authority for both implementation correctness and QA test design.

Every rule is numbered, specific, and independently verifiable. Each domain section maps directly to a certification domain in the technical design. This specification is derived from:

- `docs/product/phase_7_audit_platform_integrity_product_spec.md` (Section 3, 4, 5, 7)
- `docs/architecture/phase_7_audit_platform_integrity_technical_design.md` (Section 6, 7, 8, 14)
- `docs/architecture/phase_6_phase7_consumer_contract.md` (Section 3, 4, 9)

---

## 2. Prerequisite Gate

### Inputs

| Input | Source | Description |
| --- | --- | --- |
| Operator-supplied identity tuple | CLI arguments | `client_id`, `audit_id`, `audit_execution_id`, `config_version`, `aggregation_version`, `intelligence_version`, `report_version` |
| `ReportMetadata` record | DynamoDB GetItem at exact SK | Record keyed at `CLIENT#{client_id} / AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#META` |

### Validation Rules

**PG-1.** Each identity argument must pass `validate_identifier` before any DynamoDB or S3 access is attempted. Invalid identifiers abort with a structured validation error. No prerequisite gate DynamoDB read occurs before argument validation.

**PG-2.** Phase 7 must perform a DynamoDB GetItem using the exact composite SK assembled from the identity tuple. Phase 7 must not scan, query with begins_with, or use any access pattern other than GetItem at the exact key.

**PG-3.** If the `ReportMetadata` DynamoDB record is absent (GetItem returns no item), Phase 7 must abort immediately with structured error `REPORT_NOT_COMPLETE`. No `CertificationJob` record may be created.

**PG-4.** If the `ReportMetadata` record exists but `status` is not `COMPLETE` (including but not limited to `PENDING`, `IN_PROGRESS`, `FAILED`, or any other value), Phase 7 must abort immediately with structured error `REPORT_NOT_COMPLETE`. No `CertificationJob` record may be created.

**PG-5.** Phase 7 must not infer report completeness from S3 key existence, partial artifact presence, or any signal other than `ReportMetadata.status = COMPLETE`. This gate is unconditional.

**PG-6.** When the prerequisite gate is satisfied (`status = COMPLETE`), Phase 7 must read all stable `ReportMetadata` fields defined in `phase7_consumer_contract_v1` Section 3.1 for use in domain checks and certificate construction. The S3 artifact location is obtained exclusively from `ReportMetadata.s3_artifact_ref`.

**PG-7.** Phase 7 must not construct or guess the Phase 6 report artifact S3 key independently. It must use `ReportMetadata.s3_artifact_ref` as the S3 key.

### Pass Condition

The prerequisite gate passes when and only when: (a) all identity arguments pass `validate_identifier`, and (b) the `ReportMetadata` DynamoDB record exists with `status = COMPLETE`.

### Fail Condition

The prerequisite gate fails when: (a) any identity argument fails `validate_identifier`, or (b) the `ReportMetadata` record is absent, or (c) `ReportMetadata.status != COMPLETE`.

### Effect on Pipeline

When the prerequisite gate fails, the entire Phase 7 pipeline aborts. No `CertificationJob` record is created. The structured error `REPORT_NOT_COMPLETE` is surfaced to the caller.

---

## 3. Idempotency Gate

### Validation Rules

**IG-1.** After the prerequisite gate passes, Phase 7 must read `CertificationMetadata` via DynamoDB GetItem at the exact composite SK including the `cert_version` component.

**IG-2.** If `CertificationMetadata` exists with `terminal_state = CERTIFIED` and `--force` is not supplied, Phase 7 must abort, return the existing `certificate_id` and S3 reference, and create no new `CertificationJob` record.

**IG-3.** If `CertificationMetadata` exists with `terminal_state = CERTIFIED` and `--force` is supplied, Phase 7 must proceed with a new certification event. The prior certificate artifact at its original S3 key must not be overwritten, modified, or deleted.

**IG-4.** If `CertificationMetadata` exists with `terminal_state = CERTIFICATION_FAILED`, Phase 7 must proceed with a new certification attempt regardless of whether `--force` is supplied.

**IG-5.** If `CertificationMetadata` exists with `terminal_state = CERTIFICATION_BLOCKED`, Phase 7 must proceed with a new certification attempt regardless of whether `--force` is supplied.

**IG-6.** If no `CertificationMetadata` record exists, Phase 7 must proceed with a new certification attempt.

---

## 4. Domain Validation Rules

The following eight sections specify the validation rules for each certification domain. All eight domains execute for every invocation regardless of the outcome of any other domain. Domain failures are contained by the domain executor so that all remaining domains continue to execute.

A domain produces `BLOCKED` status only when required artifact fields are missing, null, or unparseable — preventing the check from executing. A domain produces `FAILED` status when the check executes and the logical assertion does not hold. A domain produces `PASSED` status when all its checks execute and all assertions hold.

---

### Domain: RUNNER_HEALTH

**Purpose:** Verify that runners operated within expected health parameters during the audit window.

**Inputs Consumed**

| Field | Source |
| --- | --- |
| `executive_summary.total_executions` | S3 report artifact |
| `endpoints[*].reliability_metrics` (all per-endpoint fields) | S3 report artifact |
| `methodology_disclosure` (configuration fields governing expected execution ranges and error rate thresholds) | S3 report artifact |

**Validation Rules (4 checks)**

**RH-1.** `executive_summary.total_executions` is greater than zero and within the expected range defined by the audit window duration and execution frequency as expressed in `methodology_disclosure` configuration fields. If `methodology_disclosure` does not specify an explicit range, the check validates that `total_executions > 0`.

**RH-2.** For every endpoint in `endpoints[]`, `reliability_metrics.total_executions` is greater than zero. No endpoint may have a zero-result observation window.

**RH-3.** For every endpoint in `endpoints[]`, the computed failure rate (`reliability_metrics.total_fail / reliability_metrics.total_executions`) does not exceed the methodology error rate threshold referenced in `methodology_disclosure`. Where `total_executions = 0`, this check is BLOCKED (see BLOCKED condition).

**RH-4.** `methodology_trace` is present and non-null in all per-endpoint sub-sections (`stability_analysis`, `burst_analysis`, `consistency_analysis`) for all endpoints. References must be internally consistent (no sub-section may be absent while others are present).

**Pass Condition:** All four checks RH-1 through RH-4 pass for all endpoints.

**Fail Condition:** Any check fails for any endpoint.

**BLOCKED Condition:** `endpoints[]` is absent or non-iterable in the S3 artifact; `methodology_disclosure` is absent or null; any required `reliability_metrics` field is null on any endpoint preventing RH-3 computation.

**Evidence Written to Certificate (DomainResult fields)**

| Field | Value |
| --- | --- |
| `domain` | `RUNNER_HEALTH` |
| `checks_performed` | 4 |
| `checks_passed` | Count of RH-1 through RH-4 that passed |
| `failure_details` | Description of each failed or blocked check; empty array if PASSED |
| `evidence_refs` | `["executive_summary.total_executions", "endpoints[*].reliability_metrics", "methodology_disclosure"]` |

---

### Domain: EVIDENCE_COMPLETENESS

**Purpose:** Verify that the evidence base is complete relative to what the audit configuration required.

**Inputs Consumed**

| Field | Source |
| --- | --- |
| `executive_summary.total_executions` | S3 report artifact |
| `executive_summary.endpoint_count` | S3 report artifact |
| `endpoints[*].reliability_metrics` (total_executions, total_pass, total_fail, audit_success_rate) | S3 report artifact |
| `methodology_disclosure` (expected execution range, minimum observation count) | S3 report artifact |

**Validation Rules (4 checks)**

**EC-1.** `executive_summary.total_executions` is within the expected range for the configured audit window and execution frequency as defined in `methodology_disclosure`. If `methodology_disclosure` specifies minimum and maximum execution bounds, `total_executions` must fall within those bounds.

**EC-2.** For every endpoint in `endpoints[]`, `reliability_metrics.total_executions` is not below the methodology minimum observation count referenced in `methodology_disclosure`. If no explicit minimum is defined, `reliability_metrics.total_executions` must be greater than zero.

**EC-3.** For every endpoint in `endpoints[]`, all required `reliability_metrics` fields — `total_executions`, `total_pass`, `total_fail`, and `audit_success_rate` — are present and non-null.

**EC-4.** `executive_summary.endpoint_count` is greater than zero. An audit with zero endpoints cannot have a complete evidence base.

**Pass Condition:** All four checks EC-1 through EC-4 pass.

**Fail Condition:** Any check fails.

**BLOCKED Condition:** `executive_summary` section is absent; `endpoints[]` is absent or non-iterable; `methodology_disclosure` is absent; any required `reliability_metrics` field cannot be read due to parse failure.

**Evidence Written to Certificate (DomainResult fields)**

| Field | Value |
| --- | --- |
| `domain` | `EVIDENCE_COMPLETENESS` |
| `checks_performed` | 4 |
| `checks_passed` | Count of EC-1 through EC-4 that passed |
| `failure_details` | Description of each failed or blocked check; empty array if PASSED |
| `evidence_refs` | `["executive_summary.total_executions", "executive_summary.endpoint_count", "endpoints[*].reliability_metrics", "methodology_disclosure"]` |

---

### Domain: EVIDENCE_INTEGRITY

**Purpose:** Verify that the Phase 6 report artifact is intact — that identity fields in the S3 artifact are consistent with `ReportMetadata`, confirming no post-write modification.

**Inputs Consumed**

| Field | Source |
| --- | --- |
| `ReportMetadata.report_id` | DynamoDB (stable fields from prerequisite gate read) |
| `ReportMetadata.report_version` | DynamoDB |
| `ReportMetadata.intelligence_version` | DynamoDB |
| `ReportMetadata.aggregate_set_hash` | DynamoDB |
| `ReportMetadata.endpoint_count` | DynamoDB |
| `identity.report_id` | S3 report artifact |
| `identity.report_version` | S3 report artifact |
| `intelligence_provenance.intelligence_version` | S3 report artifact |
| `intelligence_provenance.aggregate_set_hash` | S3 report artifact |
| `executive_summary.endpoint_count` | S3 report artifact |

**Validation Rules (5 checks)**

**EI-1.** `intelligence_provenance.aggregate_set_hash` in the S3 artifact exactly matches `ReportMetadata.aggregate_set_hash` from DynamoDB. Case-sensitive string equality. A null or empty value in either source fails this check.

**EI-2.** `identity.report_id` in the S3 artifact exactly matches `ReportMetadata.report_id` from DynamoDB. Case-sensitive string equality.

**EI-3.** `identity.report_version` in the S3 artifact exactly matches `ReportMetadata.report_version` from DynamoDB. Case-sensitive string equality.

**EI-4.** `intelligence_provenance.intelligence_version` in the S3 artifact exactly matches `ReportMetadata.intelligence_version` from DynamoDB. Case-sensitive string equality.

**EI-5.** `ReportMetadata.endpoint_count` (integer) equals the value of `executive_summary.endpoint_count` (integer) in the S3 artifact. Type coercion is not permitted; both must be comparable as integers.

**Pass Condition:** All five cross-reference checks EI-1 through EI-5 pass.

**Fail Condition:** Any mismatch detected between the S3 artifact and `ReportMetadata`.

**BLOCKED Condition:** Any required field from `ReportMetadata` is absent at read time; any required field from the S3 artifact is absent, null, or unparseable.

**Evidence Written to Certificate (DomainResult fields)**

| Field | Value |
| --- | --- |
| `domain` | `EVIDENCE_INTEGRITY` |
| `checks_performed` | 5 |
| `checks_passed` | Count of EI-1 through EI-5 that passed |
| `failure_details` | Description of each mismatch including which fields were compared and what values were found |
| `evidence_refs` | `["identity.report_id", "identity.report_version", "intelligence_provenance.intelligence_version", "intelligence_provenance.aggregate_set_hash", "executive_summary.endpoint_count", "ReportMetadata.report_id", "ReportMetadata.report_version", "ReportMetadata.intelligence_version", "ReportMetadata.aggregate_set_hash", "ReportMetadata.endpoint_count"]` |

---

### Domain: EVIDENCE_LINEAGE

**Purpose:** Verify that the complete evidence lineage chain from Phase 4 through the Phase 6 report artifact is unbroken.

**Inputs Consumed**

| Field | Source |
| --- | --- |
| `intelligence_provenance` (all fields) | S3 report artifact |
| `input_lineage` (all fields) | S3 report artifact |
| `ReportMetadata.aggregate_set_hash` | DynamoDB |

**Validation Rules (5 checks)**

**EL-1.** `intelligence_provenance.aggregate_set_hash` is present, non-null, and non-empty in the S3 artifact. `ReportMetadata.aggregate_set_hash` is present and non-empty. Both must be non-empty strings.

**EL-2.** `intelligence_provenance.aggregate_set_hash` (S3 artifact) exactly matches `ReportMetadata.aggregate_set_hash` (DynamoDB). Case-sensitive string equality. This is the lineage hash consistency check linking Phase 4 through Phase 7.

**EL-3.** `intelligence_provenance.intelligence_job_id` is present and non-null in the S3 artifact. An empty string is treated as absent.

**EL-4.** All required `input_lineage` fields are present and non-null in the S3 artifact. Required fields are all fields defined in `phase7_consumer_contract_v1` Section 3.2 under `Input Lineage`.

**EL-5.** `intelligence_provenance.intelligence_completed_at` is a valid UTC ISO-8601 timestamp: non-null, non-empty, and parseable as a datetime with UTC timezone designation. An unparseable or timezone-ambiguous string fails this check.

**Pass Condition:** All five lineage checks EL-1 through EL-5 pass.

**Fail Condition:** Any lineage gap, hash mismatch, missing field, or invalid timestamp detected.

**BLOCKED Condition:** `intelligence_provenance` section is absent in the S3 artifact; `input_lineage` section is absent in the S3 artifact; the S3 artifact cannot be parsed.

**Evidence Written to Certificate (DomainResult fields)**

| Field | Value |
| --- | --- |
| `domain` | `EVIDENCE_LINEAGE` |
| `checks_performed` | 5 |
| `checks_passed` | Count of EL-1 through EL-5 that passed |
| `failure_details` | Description of each gap or mismatch found |
| `evidence_refs` | `["intelligence_provenance.aggregate_set_hash", "intelligence_provenance.intelligence_job_id", "intelligence_provenance.intelligence_completed_at", "input_lineage", "ReportMetadata.aggregate_set_hash"]` |

---

### Domain: OBSERVATION_COVERAGE

**Purpose:** Verify that all endpoints were observed with sufficient coverage and that coverage claims are internally consistent across the artifact and `ReportMetadata`.

**Inputs Consumed**

| Field | Source |
| --- | --- |
| `executive_summary.endpoint_count` | S3 report artifact |
| `executive_summary.audit_success_rate` | S3 report artifact |
| `executive_summary.total_executions` | S3 report artifact |
| `endpoints[]` (all sub-sections per element) | S3 report artifact |
| `ReportMetadata.endpoint_count` | DynamoDB |

**Validation Rules (5 checks)**

**OC-1.** For every endpoint in `endpoints[]`, the following sub-sections are present and non-null: `endpoint_score`, `reliability_metrics`, `stability_analysis`, `burst_analysis`, and `consistency_analysis`. The absence or null value of any single sub-section on any single endpoint fails this check.

**OC-2.** `executive_summary.endpoint_count` (integer) equals the actual count of elements in the `endpoints[]` array. This is the artifact-internal count consistency check.

**OC-3.** `ReportMetadata.endpoint_count` (integer from DynamoDB) equals the actual count of elements in the `endpoints[]` array. This is the cross-record count consistency check.

**OC-4.** `executive_summary.audit_success_rate` is a numeric value in the closed interval `[0.0, 1.0]`. Values strictly less than 0.0 or strictly greater than 1.0 fail this check. The value must be expressible with 3 decimal places of precision; values with more than 3 significant decimal places fail this check.

**OC-5.** `executive_summary.total_executions` is consistent with per-endpoint `reliability_metrics.total_executions` totals. The audit-level total must match or be reconcilable with the sum of per-endpoint totals. Discrepancies that are not explained by the methodology disclosure fail this check.

**Pass Condition:** All five coverage checks OC-1 through OC-5 pass.

**Fail Condition:** Any count mismatch, missing sub-section, or out-of-range value detected.

**BLOCKED Condition:** `endpoints[]` is absent or non-iterable in the S3 artifact; `executive_summary` section is absent; `ReportMetadata.endpoint_count` is absent from DynamoDB.

**Evidence Written to Certificate (DomainResult fields)**

| Field | Value |
| --- | --- |
| `domain` | `OBSERVATION_COVERAGE` |
| `checks_performed` | 5 |
| `checks_passed` | Count of OC-1 through OC-5 that passed |
| `failure_details` | Description of each failed check including actual vs expected counts or values |
| `evidence_refs` | `["executive_summary.endpoint_count", "executive_summary.audit_success_rate", "executive_summary.total_executions", "endpoints[*].endpoint_score", "endpoints[*].reliability_metrics", "endpoints[*].stability_analysis", "endpoints[*].burst_analysis", "endpoints[*].consistency_analysis", "ReportMetadata.endpoint_count"]` |

---

### Domain: SCHEDULER_INTEGRITY

**Purpose:** Verify that the scheduler produced observations consistent with the audit configuration and that no scheduler anomaly is present that was not disclosed.

**Inputs Consumed**

| Field | Source |
| --- | --- |
| `executive_summary.total_executions` | S3 report artifact |
| `executive_summary.endpoint_count` | S3 report artifact |
| `methodology_disclosure` (execution window, frequency, variance allowance, limitations) | S3 report artifact |
| `endpoints[*].reliability_metrics.total_executions` | S3 report artifact |

**Validation Rules (3 checks)**

**SI-1.** `executive_summary.total_executions` is within the expected range for the configured audit window and execution frequency as defined in `methodology_disclosure`. This check is independent of the EVIDENCE_COMPLETENESS domain; each domain verifies its own checks. If `methodology_disclosure` does not specify explicit bounds, the check validates that `total_executions > 0`.

**SI-2.** Execution density — computed as `total_executions / endpoint_count` — is consistent with per-endpoint `reliability_metrics.total_executions` values across all endpoints, within the allowed variance defined in `methodology_disclosure`. Variance is measured as the maximum deviation from the mean per-endpoint execution count. If `methodology_disclosure` defines an explicit variance allowance, that value governs. If not, a reasonable internal default applies.

**SI-3.** No content in `methodology_disclosure` indicates a scheduler anomaly that is not enumerated as a known limitation in `methodology_disclosure.limitations`. If `methodology_disclosure` contains anomaly indicators (fields or values signaling dropped windows, skipped intervals, or scheduler degradation) without corresponding entries in `limitations`, this check fails.

**Pass Condition:** All three scheduler checks SI-1 through SI-3 pass.

**Fail Condition:** Any scheduler integrity check fails.

**BLOCKED Condition:** `methodology_disclosure` is absent or null in the S3 artifact; `executive_summary.total_executions` or `executive_summary.endpoint_count` is absent; `endpoints[]` cannot be iterated.

**Evidence Written to Certificate (DomainResult fields)**

| Field | Value |
| --- | --- |
| `domain` | `SCHEDULER_INTEGRITY` |
| `checks_performed` | 3 |
| `checks_passed` | Count of SI-1 through SI-3 that passed |
| `failure_details` | Description of each scheduler violation found |
| `evidence_refs` | `["executive_summary.total_executions", "executive_summary.endpoint_count", "methodology_disclosure", "endpoints[*].reliability_metrics.total_executions"]` |

---

### Domain: METHODOLOGY_COMPLIANCE

**Purpose:** Verify that audit execution followed the configured methodology and that methodology disclosure is complete and unabridged.

**Inputs Consumed**

| Field | Source |
| --- | --- |
| `methodology_disclosure` (all fields including `limitations`) | S3 report artifact |
| `endpoints[*].stability_analysis.methodology_trace` | S3 report artifact |
| `endpoints[*].burst_analysis.methodology_trace` | S3 report artifact |
| `endpoints[*].consistency_analysis.methodology_trace` | S3 report artifact |
| `endpoints[*].endpoint_score.score_derivation` | S3 report artifact |

**Validation Rules (5 checks)**

**MC-1.** `methodology_disclosure` section is present, non-null, and non-empty in the S3 artifact. An empty object `{}` fails this check. The section must contain at least the fields required by `report_v1` schema.

**MC-2.** All methodology disclosure fields required by the `report_v1` schema are present in `methodology_disclosure`. Required fields are those defined in `phase7_consumer_contract_v1` Section 3.2 under Methodology Disclosure. The absence of any required field fails this check.

**MC-3.** `methodology_disclosure.limitations` is an array that is present in the S3 artifact. The array may be empty if no limitations apply, but the key must not be absent entirely.

**MC-4.** For every endpoint in `endpoints[]`, `methodology_trace` is present and non-null in all three per-endpoint analysis sub-sections: `stability_analysis`, `burst_analysis`, and `consistency_analysis`. The absence or null value of `methodology_trace` in any single sub-section on any single endpoint fails this check.

**MC-5.** For every endpoint in `endpoints[]`, `endpoint_score.score_derivation` is present and non-null. An absent or null `score_derivation` on any endpoint fails this check.

**Pass Condition:** All five methodology checks MC-1 through MC-5 pass for all endpoints and all top-level methodology disclosure fields.

**Fail Condition:** Any check fails for any endpoint, or any required top-level `methodology_disclosure` field is absent.

**BLOCKED Condition:** `methodology_disclosure` section is absent from the S3 artifact; `endpoints[]` is absent or non-iterable; the S3 artifact cannot be parsed.

**Evidence Written to Certificate (DomainResult fields)**

| Field | Value |
| --- | --- |
| `domain` | `METHODOLOGY_COMPLIANCE` |
| `checks_performed` | 5 |
| `checks_passed` | Count of MC-1 through MC-5 that passed |
| `failure_details` | Description of each missing field or absent methodology trace |
| `evidence_refs` | `["methodology_disclosure", "endpoints[*].stability_analysis.methodology_trace", "endpoints[*].burst_analysis.methodology_trace", "endpoints[*].consistency_analysis.methodology_trace", "endpoints[*].endpoint_score.score_derivation"]` |

---

### Domain: REPORT_INTEGRITY

**Purpose:** Verify that the report artifact is internally consistent and that no anomalous values are present that would undermine audit trustworthiness.

**Inputs Consumed**

| Field | Source |
| --- | --- |
| `identity.report_version` | S3 report artifact |
| `intelligence_provenance.intelligence_version` | S3 report artifact |
| `executive_summary.score_label` | S3 report artifact |
| `executive_summary.composite_score_value` | S3 report artifact |
| `executive_summary.score_label_description` | S3 report artifact |
| `endpoints[*].endpoint_id` | S3 report artifact |
| `endpoints[*].endpoint_score.*` (all numeric score fields) | S3 report artifact |

**Validation Rules (9 checks)**

**RI-1.** `identity.report_version` is exactly `report_v1`. Case-sensitive string equality. Any other value fails this check.

**RI-2.** `intelligence_provenance.intelligence_version` is exactly `intel_v1`. Case-sensitive string equality. Any other value fails this check.

**RI-3.** `executive_summary.score_label` is a member of the bounded set `{HIGH_CONFIDENCE, MODERATE_CONFIDENCE, LOW_CONFIDENCE}`. Case-sensitive membership check. Any value outside this set fails this check.

**RI-4.** `executive_summary.composite_score_value` is a numeric value in the closed interval `[0.0, 1.0]` with exactly 3 decimal places. Values strictly less than 0.0 or strictly greater than 1.0 fail this check. Values with more than 3 significant decimal places fail this check.

**RI-5.** `endpoints[]` is lexicographically sorted by `endpoint_id` in ascending order. The sort order must be Unicode code point ordering. A list with zero or one elements is trivially sorted and passes. Any pair of adjacent elements where the first `endpoint_id` is lexicographically greater than the second fails this check.

**RI-6.** No duplicate `endpoint_id` values exist in `endpoints[]`. If two or more endpoints share the same `endpoint_id` string, this check fails.

**RI-7.** No endpoint in `endpoints[]` has a null or empty `endpoint_id`. An `endpoint_id` of `null`, `""`, or the absence of the `endpoint_id` key fails this check.

**RI-8.** All numeric score fields for all endpoints in `endpoints[*].endpoint_score` are in the closed interval `[0.0, 1.0]` with exactly 3 decimal places. Any field outside this range or with more than 3 significant decimal places fails this check. This check applies to all numeric sub-fields of `endpoint_score` on every endpoint.

**RI-9.** `executive_summary.score_label_description` is a member of the bounded value set defined in `report_v1` constants in `constants.py`. This value is a Phase 6 fixed presentation string. Any value outside the defined bounded set fails this check.

**Pass Condition:** All nine checks RI-1 through RI-9 pass for all applicable fields and all endpoints.

**Fail Condition:** Any check fails.

**BLOCKED Condition:** `identity` section is absent from the S3 artifact; `executive_summary` section is absent; `endpoints[]` is absent or non-iterable; the S3 artifact cannot be deserialized.

**Evidence Written to Certificate (DomainResult fields)**

| Field | Value |
| --- | --- |
| `domain` | `REPORT_INTEGRITY` |
| `checks_performed` | 9 |
| `checks_passed` | Count of RI-1 through RI-9 that passed |
| `failure_details` | Description of each failed check including field name and value found |
| `evidence_refs` | `["identity.report_version", "intelligence_provenance.intelligence_version", "executive_summary.score_label", "executive_summary.composite_score_value", "executive_summary.score_label_description", "endpoints[*].endpoint_id", "endpoints[*].endpoint_score.*"]` |

---

## 5. Terminal State Aggregation Rules

The following rules determine `terminal_state` from the collected `domain_results[]` after all eight domains have executed. These rules are deterministic. The same set of domain results always produces the same terminal state.

**TA-1.** If any domain in `domain_results[]` has `status = BLOCKED`, the terminal state is `CERTIFICATION_BLOCKED`. This applies regardless of the status of any other domain. `BLOCKED` takes precedence over `FAILED`.

**TA-2.** If no domain has `status = BLOCKED` and one or more domains have `status = FAILED`, the terminal state is `CERTIFICATION_FAILED`.

**TA-3.** If all eight domains have `status = PASSED`, the terminal state is `CERTIFIED`. `domain_results[]` must contain exactly eight entries; fewer than eight entries is a pipeline integrity failure (implementation error, not a domain failure).

**TA-4.** `disclosed_failures` is populated as follows:
- If `terminal_state = CERTIFIED`: `disclosed_failures = []` (empty array).
- If `terminal_state = CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED`: `disclosed_failures` contains the `domain` identifier of every domain with `status = FAILED` or `status = BLOCKED`.

**TA-5.** `certification_summary` is a fixed string derived from `terminal_state` using the bounded mapping defined in `constants.py`:

| `terminal_state` | `certification_summary` |
| --- | --- |
| `CERTIFIED` | `INTEGRITY_VERIFIED` |
| `CERTIFICATION_FAILED` | `INTEGRITY_FAILED` |
| `CERTIFICATION_BLOCKED` | `INTEGRITY_BLOCKED` |

This mapping must not be altered without a `certificate_version` increment.

**TA-6.** `domain_results[]` must contain exactly eight entries — one per domain identifier in the bounded set. Domain identifiers: `RUNNER_HEALTH`, `EVIDENCE_COMPLETENESS`, `EVIDENCE_INTEGRITY`, `EVIDENCE_LINEAGE`, `OBSERVATION_COVERAGE`, `SCHEDULER_INTEGRITY`, `METHODOLOGY_COMPLIANCE`, `REPORT_INTEGRITY`. No domain may be absent.

---

## 6. Certificate Integrity Rules

**CI-1.** The `PlatformIntegrityCertificate` must contain all required fields defined in the `cert_v1` schema. The required fields are: `certificate_id`, `certificate_version`, `generated_at`, `generator_version`, `terminal_state`, `certification_summary`, `report_id`, `report_version`, `intelligence_version`, `aggregate_set_hash`, `s3_report_artifact_ref`, `client_id`, `audit_id`, `audit_execution_id`, `config_version`, `aggregation_version`, `domain_results`, and `disclosed_failures`. The absence of any required field is a `CERT_SCHEMA_VALIDATION_ERROR`.

**CI-2.** `certificate_version` must be exactly `cert_v1`.

**CI-3.** `certificate_id` must be a non-null, non-empty string generated once per invocation, with the prefix `cert_`. It must be unique across invocations.

**CI-4.** `generated_at` must be a valid UTC ISO-8601 timestamp. It must be generated once at `engine.py` pipeline entry and passed into the certificate and all pipeline stages. No domain module or publisher may independently call `datetime.now()` to set this field.

**CI-5.** The certificate JSON must be serialized using `sort_keys=True` and `indent=2`. This guarantees canonical field ordering and deterministic byte output for identical inputs.

**CI-6.** All numeric fields in the certificate must carry 3-decimal-place precision, consistent with Phase 5 and Phase 6 serialization conventions. Numeric fields read from the Phase 6 artifact are preserved as-is; Phase 7 must not re-round them.

**CI-7.** The certificate must be written to S3 under the `integrity/` key prefix using the path structure: `integrity/{client_id}/{audit_id}/{audit_execution_id}/{aggregation_version}/{intelligence_version}/{report_version}/{cert_version}/{certjob_id}/artifact.json`. The `certjob_id` segment guarantees per-invocation uniqueness.

**CI-8.** Once written to S3, a certificate artifact is immutable. No prior certificate artifact is deleted or overwritten by any subsequent invocation, including force re-runs.

**CI-9.** A `CertificationMetadata` DynamoDB record must be written for every invocation that reaches the persistence stage, regardless of `terminal_state` (including `CERTIFICATION_FAILED` and `CERTIFICATION_BLOCKED`).

**CI-10.** The certificate must not contain Phase 5 intelligence conclusions re-derived or re-stated as Phase 7 conclusions. The certificate must not contain re-computed reliability scores, labels, or component scores. The certificate must not embed Phase 6 report content; it references the report by `s3_report_artifact_ref` key only.

**CI-11.** `domain_results[]` ordering in the certificate must be deterministic. Domain results must appear in the canonical bounded-set order: `RUNNER_HEALTH`, `EVIDENCE_COMPLETENESS`, `EVIDENCE_INTEGRITY`, `EVIDENCE_LINEAGE`, `OBSERVATION_COVERAGE`, `SCHEDULER_INTEGRITY`, `METHODOLOGY_COMPLIANCE`, `REPORT_INTEGRITY`.

**CI-12.** Idempotency within `cert_v1`: given identical Phase 6 report artifact content and identical `ReportMetadata` fields, two certification runs must produce `domain_results[]`, `terminal_state`, and `disclosed_failures` that are identical in content. `certificate_id` and `generated_at` will differ between runs; all other deterministic fields must match.

---

## 7. Non-Mutation Rules

Phase 7 is prohibited from writing, updating, or deleting any Phase 6, Phase 5, Phase 4, or earlier phase artifact or DynamoDB record. The following rules define the testable boundary.

**NM-1.** All DynamoDB write operations in `repository.py` must target exclusively Phase 7 sort key namespaces. Write methods for `CertificationJob` use the `#CERTJOB#` SK prefix. Write methods for `CertificationMetadata` use the `#CERT#` SK prefix. No write method may target any SK containing `#RPTJOB#`, `#RPT#...#META`, `#INTEL#`, `#INTJOB#`, `#AGG#`, `#AGGJOB#`, `#SET`, `#MANIFEST#`, or any other Phase 6 or earlier namespace.

**NM-2.** The DynamoDB GetItem for `ReportMetadata` in `repository.py` is a read-only operation. No UpdateItem, PutItem, or DeleteItem targeting the `ReportMetadata` SK may exist anywhere in the Phase 7 code path.

**NM-3.** All S3 write operations in `publisher.py` must target keys with the `integrity/` prefix exclusively. No S3 PutObject, DeleteObject, or CopyObject may target keys with the `reports/`, `intelligence/`, or `raw-results/` prefixes.

**NM-4.** The S3 GetObject call for the Phase 6 report artifact in `publisher.py` uses the key obtained from `ReportMetadata.s3_artifact_ref`. No modification, conditional write, or lifecycle operation may accompany or follow this read.

**NM-5.** Domain modules are stateless and read-only by design. Each domain module function accepts input data structures and returns a `DomainResult`. Domain modules must have no interface for DynamoDB writes, S3 writes, or mutation of any data structure passed to them.

**NM-6.** Phase 7 must not read any Phase 5 DynamoDB record (`IntelligenceJob`, `IntelligenceMetadata`) or any Phase 5 S3 artifact. Phase 7 must not read any Phase 4 DynamoDB record or S3 artifact. Phase 7 must not read any `ReportJob` record (Phase 6-internal record excluded from the consumer contract). This restriction applies to all Phase 7 code paths, including retrieval CLI commands.

**How to Verify NM-1 through NM-6 in Tests:**

- Static analysis / AST or grep check: confirm no SK string containing disallowed prefixes appears in `repository.py` write paths.
- Unit test (`test_repository.py`): mock DynamoDB client; assert that all `put_item` and `update_item` calls use only `#CERTJOB#` or `#CERT#` SK prefixes.
- Unit test (`test_repository.py`): assert that no `delete_item` call exists in any Phase 7 code path.
- Unit test (`test_publisher.py`): mock S3 client; assert that all `put_object` calls use keys with `integrity/` prefix; assert that no `put_object`, `delete_object`, or `copy_object` call uses `reports/`, `intelligence/`, or `raw-results/` prefix.
- Integration test: execute a full certification pipeline against a Phase 6 fixture; after completion, assert that `ReportMetadata` record in DynamoDB is byte-identical to its state before Phase 7 was invoked.

---

## 8. Error Code Reference

| Code | Trigger Condition | Phase 7 Response |
| --- | --- | --- |
| `REPORT_NOT_COMPLETE` | `ReportMetadata` absent or `status != COMPLETE` | Abort; no `CertificationJob` created; structured error returned |
| `CERTIFICATION_ALREADY_CERTIFIED` | `CertificationMetadata.terminal_state = CERTIFIED` and `--force` not supplied | Abort; return existing `certificate_id` and S3 ref; no new job |
| `S3_REPORT_ARTIFACT_READ_FAILURE` | Phase 6 S3 artifact cannot be read via `s3_artifact_ref` | Domain executor receives BLOCKED inputs; `CERTIFICATION_BLOCKED` terminal state |
| `S3_CERTIFICATE_WRITE_FAILURE` | Phase 7 certificate S3 write fails | `CertificationJob → FAILED`; structured error to caller |
| `CERT_SCHEMA_VALIDATION_ERROR` | `PlatformIntegrityCertificate` Pydantic validation fails | `CertificationJob → FAILED`; structured error to caller |
| `DYNAMODB_WRITE_FAILURE` | DynamoDB write fails for `CertificationJob` or `CertificationMetadata` | `CertificationJob → FAILED`; structured error to caller |
| `CERTIFICATION_NOT_FOUND` | `CertificationMetadata` absent for the identity tuple (retrieval commands only) | Structured error to caller; no write operations |

---

## 9. Traceability

- Product Spec: `docs/product/phase_7_audit_platform_integrity_product_spec.md`
- Technical Design: `docs/architecture/phase_7_audit_platform_integrity_technical_design.md`
- Phase 6 → Phase 7 Consumer Contract: `docs/architecture/phase_6_phase7_consumer_contract.md`
- Phase 6 Test Plan (format reference): `docs/qa/phase_6_deterministic_reporting_test_plan.md`
- Compatibility gate test: `tests/unit/test_phase7_cert_schema.py`
- Non-mutation test: `tests/unit/audit_platform_integrity/test_repository.py`
