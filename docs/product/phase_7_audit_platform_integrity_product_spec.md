# Product Specification

## 1. Phase Overview

Phase 7 is the Audit Platform Integrity layer of the Release Confidence Platform. It is the final phase of the technical MVP (Phases 0 through 7).

Phase 7 answers a fundamentally different question than all prior phases:

- Prior phases determine: *Is the customer's API operationally reliable?*
- Phase 7 determines: *Can the customer trust the audit process that produced the Release Confidence Report?*

Phase 7 is a verification-only layer. It consumes exclusively the Phase 6 `ReportMetadata` DynamoDB record and the S3 report artifact — inputs defined by the locked `phase7_consumer_contract_v1`. Phase 7 produces a single output: the **Platform Integrity Certificate**, an immutable artifact that certifies (or discloses the failure to certify) the trustworthiness of a completed audit.

Phase 7 completes the technical MVP. Every Release Confidence Report produced by Phase 6 must have a corresponding Platform Integrity Certificate before it can be issued to a customer.

**Non-Negotiable Rule (verbatim from Product Constitution):**

> No Release Confidence Report shall be issued unless Audit Platform Integrity verification has successfully completed or all material limitations have been explicitly disclosed.

### Locked Constraints

The following constraints are unconditional and apply to every implementation decision in Phase 7:

- Phase 7 is verification only.
- No recalculation of reliability.
- No regeneration of operational intelligence.
- No modification of aggregation results.
- No rewriting of Release Confidence Reports.
- No rescoring of evidence.
- No reinterpretation of audit observations.
- Certification decisions must be deterministic.
- Every certification decision must be evidence-backed.
- Every certification must be reproducible.
- Phase 7 must not include CI/CD integrations (GitHub Actions, Jenkins, etc.) — those belong to later phases.

### Target Users

**Platform Engineer / Operator**: Invokes Phase 7 certification via CLI after confirming `ReportMetadata.status = COMPLETE`. Reviews certification output for terminal state and disclosed failures. Uses the retrieval CLI for operational inspection and pre-delivery validation.

**QA Engineer**: Validates Phase 7 certification output against known Phase 6 fixture artifacts. Confirms that all domain checks execute, that failure conditions produce correct terminal states, and that the Platform Integrity Certificate is generated deterministically.

**Audit Customer (Indirect)**: Receives the Platform Integrity Certificate as part of the final audit engagement deliverable. The certificate confirms that the process producing their Release Confidence Report was itself verified. Does not directly interact with Phase 7 CLI or artifacts.

**Phase 8 / Post-Phase 7 Consumers (Internal)**: Phase 8 Commercialization and downstream phases reference the Platform Integrity Certificate as part of the complete audit deliverable package. The certificate is a stable, immutable reference artifact with a defined key in S3.

---

## 2. Product Positioning

### What Phase 7 Is

Phase 7 is an independent integrity verification layer that audits the audit process itself.

A complete and deterministic Release Confidence Report (Phase 6) faithfully presents Phase 5 intelligence conclusions. But faithfulness to intelligence is not the same as trustworthiness of the evidence collection process that produced that intelligence. Phase 7 closes this gap.

Phase 7 makes the audit process itself auditable. It certifies:

- That the audit produced sufficient, complete, and intact evidence
- That runners executed correctly during the audit window
- That the scheduler produced observation coverage meeting methodology minimums
- That the full lineage chain from Phase 4 aggregation through Phase 6 report is unbroken
- That the report artifact is internally consistent with the intelligence that produced it
- That no internal anomalies undermine the trustworthiness of the audit

This second-order verification strengthens RCP's position as an **independent** audit platform. Customers do not merely receive a score — they receive a certified attestation that the process producing the score was sound.

### What Phase 7 Is NOT

| What Phase 7 Is Not | What Owns It Instead |
| --- | --- |
| A reliability scoring or re-scoring layer | Phase 5 (Reliability Intelligence) |
| A re-derivation of intelligence conclusions | Phase 5 (Reliability Intelligence) |
| A regeneration of Release Confidence Reports | Phase 6 (Deterministic Reporting) |
| A re-computation of aggregation results | Phase 4 (Aggregation) |
| A rescoring of raw execution evidence | Phase 5 |
| A CI/CD integration or gating mechanism | Post-Phase 7 phases |
| A customer portal or self-service interface | Post-Phase 7 phases |
| A monitoring or alerting platform | Separate concern |
| A test automation framework | Separate concern |
| A real-time or streaming system | Not part of MVP |

### How Phase 7 Relates to Phase 6

Phase 6 owns presentation. Phase 7 owns platform integrity certification.

Phase 7 does not know how Phase 5 derived its conclusions. Phase 7 does not know how Phase 4 aggregated raw evidence. Phase 7 knows only what Phase 6 faithfully reported — and it verifies that the platform which produced that report behaved correctly, completely, and consistently.

### Problem Statement

Five failure modes exist that prior phases do not address and that undermine the defensibility of any Release Confidence Report:

1. **Runner degradation during the audit window**: A runner may produce valid-looking raw evidence while in a degraded state. Prior phases capture what was observed — not whether observation conditions were sound.

2. **Observation coverage gaps**: The scheduler may have skipped observation windows. Phase 3 enforces audit lifecycle completion but does not certify that observation density met methodology minimums.

3. **Evidence artifact integrity**: S3 report artifacts may be corrupted or modified after initial write. No prior phase verifies artifact integrity against a known hash.

4. **Lineage chain breaks**: The chain from Phase 4 aggregation through Phase 5 intelligence to Phase 6 report must be unbroken. No prior phase performs an end-to-end lineage verification pass.

5. **Report internal inconsistency**: The report artifact may contain fields that are internally inconsistent due to generation failures or version mismatches that bypassed prior detection gates.

Phase 7 closes all five gaps by verifying the audit process across eight certification domains and producing a deterministic, immutable certificate recording the outcome.

---

## 3. Core Capabilities

Phase 7 verification is organized into eight certification domains. Each domain is independently evaluated. A single domain failure produces `CERTIFICATION_FAILED` for the audit, subject to the disclosure policy in Section 5.

All domain checks are verification-only. Domain checks read Phase 6 report artifact fields and apply logical rules. They do not re-derive, re-compute, or reinterpret any analytical conclusion.

### 3.1 Runner Health Verification

Verifies that runners operated within expected health parameters during the audit window.

Checks performed:

- Runner execution count is within the expected range for the audit duration and configuration
- No runner produced a zero-result observation window
- Runner error rates did not exceed the methodology threshold during any observation window
- All methodology trace fields on per-endpoint analysis entries reference consistent runner state

Inputs: `endpoints[].reliability_metrics`, `executive_summary.total_executions`, `methodology_disclosure`.

### 3.2 Evidence Completeness Validation

Verifies that the evidence base is complete relative to what the audit configuration required.

Checks performed:

- Total execution count (`executive_summary.total_executions`) is within the expected range for the configured audit window and execution frequency
- No endpoint was observed fewer than the methodology minimum observation count
- All required evidence artifact fields are present and non-null for every endpoint
- `executive_summary.endpoint_count` is greater than zero

Inputs: `executive_summary`, `endpoints[].reliability_metrics`, `methodology_disclosure`.

### 3.3 Evidence Integrity Verification

Verifies that the Phase 6 report artifact is intact — that the artifact has not been modified since initial write and that identity fields are consistent with `ReportMetadata`.

Checks performed:

- `aggregate_set_hash` in the S3 artifact matches `aggregate_set_hash` in `ReportMetadata`
- `identity.report_id` in the S3 artifact matches `report_id` in `ReportMetadata`
- `identity.report_version` in the S3 artifact matches `report_version` in `ReportMetadata`
- `intelligence_provenance.intelligence_version` in the S3 artifact matches `intelligence_version` in `ReportMetadata`

Inputs: `ReportMetadata` (all stable fields per `phase7_consumer_contract_v1` Section 3.1), `identity`, `intelligence_provenance`.

### 3.4 Evidence Lineage Verification

Verifies that the complete evidence lineage chain is unbroken from Phase 4 through the Phase 6 report artifact.

Checks performed:

- `aggregate_set_hash` is present, non-null, and non-empty in both `ReportMetadata` and the S3 artifact
- `intelligence_provenance.aggregate_set_hash` matches `aggregate_set_hash` in `ReportMetadata`
- `intelligence_provenance.intelligence_job_id` is present and non-null
- All required `input_lineage` fields are present and non-null
- `intelligence_provenance.intelligence_completed_at` is a valid UTC ISO-8601 timestamp

Inputs: `intelligence_provenance`, `input_lineage`, `ReportMetadata.aggregate_set_hash`.

### 3.5 Observation Coverage Verification

Verifies that all endpoints were observed with sufficient coverage to meet methodology minimums and that coverage claims are internally consistent.

Checks performed:

- Every endpoint in `endpoints[]` has `endpoint_score`, `reliability_metrics`, `stability_analysis`, `burst_analysis`, and `consistency_analysis` present and non-null
- `executive_summary.endpoint_count` matches the count of elements in `endpoints[]`
- `ReportMetadata.endpoint_count` matches the count of elements in `endpoints[]`
- `executive_summary.audit_success_rate` is in `[0.0, 1.0]` with 3 decimal places
- `executive_summary.total_executions` is consistent with per-endpoint `reliability_metrics` totals

Inputs: `executive_summary`, `endpoints[]`, `ReportMetadata.endpoint_count`.

### 3.6 Scheduler Integrity Verification

Verifies that the scheduler produced observations consistent with the audit configuration.

Checks performed:

- `executive_summary.total_executions` is within the expected range for the configured audit window and execution frequency
- Execution density (executions per endpoint) is consistent across all endpoints, within the allowed variance defined in `methodology_disclosure`
- No `methodology_disclosure` entry indicates a scheduler anomaly that was not disclosed as a known limitation in `methodology_disclosure.limitations`

Inputs: `executive_summary.total_executions`, `executive_summary.endpoint_count`, `methodology_disclosure`, `endpoints[].reliability_metrics`.

### 3.7 Audit Methodology Compliance Verification

Verifies that audit execution followed the configured methodology and that methodology disclosure is complete and unabridged.

Checks performed:

- `methodology_disclosure` section is present, non-null, and non-empty in the S3 artifact
- All methodology disclosure fields required by `report_v1` schema are present
- `methodology_disclosure.limitations` array is present (may be empty if no limitations apply, but must not be absent)
- `methodology_trace` is present and non-null for all per-endpoint sub-sections: `stability_analysis`, `burst_analysis`, `consistency_analysis`
- `endpoint_score.score_derivation` is present and non-null for every endpoint in `endpoints[]`

Inputs: `methodology_disclosure`, `endpoints[].stability_analysis`, `endpoints[].burst_analysis`, `endpoints[].consistency_analysis`, `endpoints[].endpoint_score`.

### 3.8 Report Integrity and Internal Anomaly Detection

Verifies that the report artifact is internally consistent and that no anomalous values are present that would undermine audit trustworthiness.

Checks performed:

- `identity.report_version` is `report_v1`
- `intelligence_provenance.intelligence_version` is `intel_v1`
- `executive_summary.score_label` is a member of the bounded set: `{HIGH_CONFIDENCE, MODERATE_CONFIDENCE, LOW_CONFIDENCE}`
- `executive_summary.composite_score_value` is in `[0.0, 1.0]` with exactly 3 decimal places
- `endpoints[]` is lexicographically sorted by `endpoint_id` (required by `report_v1`)
- No duplicate `endpoint_id` values exist in `endpoints[]`
- No endpoint has a null or empty `endpoint_id`
- All numeric score fields for all endpoints are in `[0.0, 1.0]` with 3 decimal places
- `executive_summary.score_label_description` is a member of the bounded value set defined in `report_v1` constants

Inputs: `identity`, `intelligence_provenance`, `executive_summary`, `endpoints[]`.

---

## 4. Platform Integrity Certificate

### 4.1 What the Certificate Is

The Platform Integrity Certificate is the sole artifact Phase 7 produces. It is a separate artifact from the Phase 6 Release Confidence Report — it complements the report but does not replace or embed it.

The certificate records the outcome of all eight Phase 7 certification domain checks for a specific completed audit. It is the evidence-backed attestation that the audit platform operated correctly, completely, and consistently for this audit engagement.

### 4.2 Certificate Contents

The following fields are required in every Platform Integrity Certificate:

| Field | Type | Description |
| --- | --- | --- |
| `certificate_id` | String | Unique identifier for this certification event |
| `certificate_version` | String | Certificate schema version: `cert_v1` |
| `generated_at` | String | UTC ISO-8601 timestamp of certificate generation |
| `generator_version` | String | Platform version string at time of certification |
| `terminal_state` | String | `CERTIFIED`, `CERTIFICATION_FAILED`, or `CERTIFICATION_BLOCKED` |
| `certification_summary` | String | Fixed, deterministic summary string derived from `terminal_state` bounded set |
| `report_id` | String | Reference to the Phase 6 report this certificate covers |
| `report_version` | String | `report_v1` |
| `intelligence_version` | String | `intel_v1` (carried from Phase 6 artifact) |
| `aggregate_set_hash` | String | Phase 4 lineage hash carried from Phase 6 artifact; completes the full lineage chain |
| `s3_report_artifact_ref` | String | S3 key of the Phase 6 report artifact this certificate covers |
| `client_id` | String | Scoped client identifier |
| `audit_id` | String | Scoped audit identifier |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `aggregation_version` | String | Phase 4 aggregation version |
| `domain_results` | Object[] | Array of per-domain verification results (see 4.3) |
| `disclosed_failures` | String[] | Domain identifiers with `FAILED` or `BLOCKED` status; empty array if `CERTIFIED` |

### 4.3 Domain Result Structure

Each element in `domain_results[]` must contain:

| Field | Type | Description |
| --- | --- | --- |
| `domain` | String | Domain identifier (bounded set; see below) |
| `status` | String | `PASSED`, `FAILED`, or `BLOCKED` |
| `checks_performed` | Integer | Number of checks executed in this domain |
| `checks_passed` | Integer | Number of checks that passed |
| `failure_details` | String[] | Descriptions of failed checks; empty array if `PASSED` |
| `evidence_refs` | String[] | Phase 6 artifact field paths evaluated in this domain |

**Domain identifier bounded set:**

| Domain Identifier | Certification Domain |
| --- | --- |
| `RUNNER_HEALTH` | Section 3.1 |
| `EVIDENCE_COMPLETENESS` | Section 3.2 |
| `EVIDENCE_INTEGRITY` | Section 3.3 |
| `EVIDENCE_LINEAGE` | Section 3.4 |
| `OBSERVATION_COVERAGE` | Section 3.5 |
| `SCHEDULER_INTEGRITY` | Section 3.6 |
| `METHODOLOGY_COMPLIANCE` | Section 3.7 |
| `REPORT_INTEGRITY` | Section 3.8 |

### 4.4 What the Certificate Must Not Contain

- Phase 5 intelligence conclusions re-derived or re-stated as Phase 7 conclusions
- Re-computed reliability scores, labels, or component scores
- Editorial commentary on the customer's API reliability
- Embedded Phase 6 report content (reference by `s3_report_artifact_ref` key only)
- Recommendations to the customer's engineering team
- Any field that re-interprets Phase 5 or Phase 6 analytical conclusions
- Any field that overrides, relabels, or substitutes a Phase 5 `score_label` or `score_label_description`

### 4.5 Immutability Requirement

The Platform Integrity Certificate is immutable once written to S3 under the `integrity/` key prefix.

A certification event cannot be amended. A new certification event produces a new `certificate_id` and a new S3 artifact at a new key. No prior certificate artifact is deleted or overwritten. This applies to `CERTIFICATION_FAILED` and `CERTIFICATION_BLOCKED` certificates as well as `CERTIFIED` certificates.

The `cert_v1` schema is immutable after HITL approval of Phase 7.1 documentation. Schema changes require a new `certificate_version`.

### 4.6 Certificate Serialization

Certificate JSON serialization must use canonical field ordering (`sort_keys=True`) and 3-decimal-place precision for all numeric fields, consistent with Phase 5 and Phase 6 artifact serialization conventions.

---

## 5. Certification Lifecycle

### 5.1 Prerequisite Gate

Phase 7 requires `ReportMetadata.status = COMPLETE` before consuming any Phase 6 report artifact.

This is the Phase 7 prerequisite gate, directly analogous to the `IntelligenceMetadata.status = COMPLETE` gate used by Phase 6.

If the record is absent or `status != COMPLETE`, Phase 7 must abort with structured error `REPORT_NOT_COMPLETE`. No certification activity — including `CertificationJob` creation — may proceed past this point.

Phase 7 must not infer report completeness from S3 key existence, partial artifact presence, or any signal other than the `ReportMetadata.status = COMPLETE` DynamoDB record. This gate is unconditional.

### 5.2 Idempotency

If a `CertificationMetadata` record already exists with `terminal_state = CERTIFIED` for the audit identity tuple `(client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version, report_version, certificate_version)`, Phase 7 must not re-certify without `--force`. The existing certificate remains authoritative.

A prior `CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED` record does not block a new certification attempt. Subsequent invocations without `--force` must proceed normally if prior terminal state is not `CERTIFIED`.

### 5.3 Execution Flow

The following steps execute in order. No step may be skipped or reordered:

1. Check `ReportMetadata.status = COMPLETE` (prerequisite gate — abort with `REPORT_NOT_COMPLETE` if not met)
2. Check `CertificationMetadata` for prior `CERTIFIED` record (idempotency gate)
3. Create a `CertificationJob` DynamoDB record with `status = PENDING`
4. Transition `CertificationJob` to `IN_PROGRESS`
5. Read all stable `ReportMetadata` fields via the DynamoDB point lookup defined in the Phase 7 consumer contract
6. Read the S3 report artifact via `ReportMetadata.s3_artifact_ref` (do not construct or guess the S3 key independently)
7. Execute all eight certification domain checks, collecting domain results
8. Determine `terminal_state` from domain results per the rules in Section 5.4
9. Populate `disclosed_failures` from all domain identifiers with `FAILED` or `BLOCKED` status
10. Serialize and write the Platform Integrity Certificate to S3 under the `integrity/` key prefix
11. Write `CertificationMetadata` DynamoDB record with `terminal_state` and `s3_certificate_ref`
12. Transition `CertificationJob` to `COMPLETE`
13. Emit structured log record with `terminal_state`, all domain results, `certificate_id`, and S3 key

If an unrecoverable infrastructure failure occurs at any step after step 3 and before step 12, `CertificationJob` must transition to `FAILED` with a structured error description. A `CERTIFICATION_BLOCKED` certificate may still be written if the failure is diagnosable and field coverage is sufficient to populate required certificate fields.

### 5.4 Terminal States

| Terminal State | Condition | Implication |
| --- | --- | --- |
| `CERTIFIED` | All eight domain check statuses are `PASSED` | Audit platform integrity is verified for this report. Report may be issued. |
| `CERTIFICATION_FAILED` | One or more domain check statuses are `FAILED` | Integrity verification found failures. Report must not be issued without explicit disclosure of all failed domains per Section 5.5. |
| `CERTIFICATION_BLOCKED` | Phase 7 could not complete one or more domain checks due to missing required artifacts, inaccessible data, or infrastructure failure | Platform integrity could not be fully verified. Report must not be issued without operator review and disclosure. |

Terminal state determination is deterministic. The same set of domain results always produces the same terminal state. `CERTIFICATION_BLOCKED` takes precedence over `CERTIFICATION_FAILED` if both conditions apply.

### 5.5 Disclosure Requirement

When `terminal_state` is `CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED`:

- The Platform Integrity Certificate must enumerate all `disclosed_failures` explicitly by domain identifier
- `failure_details` for each failed domain must describe what check failed and what value was found
- The Release Confidence Report must not be issued to the customer without explicit disclosure of all material limitations identified in the certificate
- This disclosure requirement is non-negotiable per the Product Constitution

Disclosure is the operator's responsibility. Phase 7 provides the certificate with complete failure information. The act of disclosure — including how failures are communicated to the customer — is an operational decision outside Phase 7's scope.

---

## 6. Operator CLI

Phase 7 extends the operator CLI with two command groups: certification execution (`rcp certify`) and certification retrieval (`rcp retrieve cert-*`).

All certification retrieval commands are unconditionally read-only. No `CertificationJob` or `CertificationMetadata` record may be written, updated, or deleted by a retrieval command.

All retrieval commands must include a provenance envelope identifying `certificate_version`, `certificate_id`, `report_id`, `report_version`, and `generated_at`.

### 6.1 Certification Execution Commands

**`rcp certify audit`**

Triggers Phase 7 platform integrity certification for a completed report.

Required arguments:

| Argument | Description |
| --- | --- |
| `client_id` | Scoped client identifier |
| `audit_id` | Scoped audit identifier |
| `audit_execution_id` | Durable execution identity |
| `config_version` | Configuration version |
| `aggregation_version` | Phase 4 aggregation version |
| `intelligence_version` | Phase 5 intelligence version |
| `report_version` | Phase 6 report version (e.g., `report_v1`) |

Optional arguments:

| Argument | Description |
| --- | --- |
| `--force` | Re-certify even if a `CERTIFIED` record already exists for this audit identity tuple |

Expected output:

- Prerequisite gate check result
- Per-domain verification results: domain identifier, status, checks performed, checks passed, failure details
- Terminal state: `CERTIFIED`, `CERTIFICATION_FAILED`, or `CERTIFICATION_BLOCKED`
- `certificate_id` and S3 key of the Platform Integrity Certificate artifact
- `disclosed_failures` list (if any)

### 6.2 Certification Retrieval Commands

**`rcp retrieve cert-status`**

Displays `CertificationMetadata` record: terminal state, certificate ID, and timestamps.

Required arguments: same as `rcp certify audit`.

Expected output:

- `terminal_state`
- `certificate_id`
- `generated_at` timestamp
- `report_id` reference
- Provenance envelope

---

**`rcp retrieve cert-summary`**

Displays the certification summary: terminal state, `certification_summary` string, domain status table, and disclosed failures.

Required arguments: same as `rcp certify audit`.

Expected output:

- `terminal_state` and `certification_summary` string
- All domain identifiers with their status (`PASSED`, `FAILED`, `BLOCKED`)
- `disclosed_failures` list
- Provenance envelope

---

**`rcp retrieve cert-domains`**

Displays full per-domain verification results from the Platform Integrity Certificate S3 artifact.

Required arguments: same as `rcp certify audit`.

Expected output:

- Full `domain_results[]` array including `checks_performed`, `checks_passed`, `failure_details`, and `evidence_refs` per domain
- Provenance envelope

---

**`rcp retrieve cert-json`**

Outputs the full Platform Integrity Certificate as canonical JSON from S3.

Required arguments: same as `rcp certify audit`.

Expected output:

- Full serialized Platform Integrity Certificate JSON artifact
- Provenance envelope

---

## 7. Acceptance Criteria

All acceptance criteria follow the Given / When / Then format. Each criterion maps directly to a QA-executable test case.

### Prerequisite Gate

**AC-1**
Given `rcp certify audit` is invoked for an audit,
When `ReportMetadata` is absent for that audit identity tuple,
Then Phase 7 must abort with structured error `REPORT_NOT_COMPLETE` and no `CertificationJob` record must be created.

**AC-2**
Given `rcp certify audit` is invoked for an audit,
When `ReportMetadata.status` is not `COMPLETE` for that audit identity tuple,
Then Phase 7 must abort with structured error `REPORT_NOT_COMPLETE` and no `CertificationJob` record must be created.

**AC-3**
Given `ReportMetadata.status = COMPLETE` and a valid `s3_artifact_ref`,
When `rcp certify audit` is invoked,
Then Phase 7 must proceed past the prerequisite gate, read the S3 artifact via `ReportMetadata.s3_artifact_ref`, and begin certification domain execution.

### Idempotency

**AC-4**
Given a `CertificationMetadata` record with `terminal_state = CERTIFIED` already exists for the audit identity tuple,
When `rcp certify audit` is invoked without `--force`,
Then Phase 7 must not re-certify and must return the existing `certificate_id` and S3 reference without creating a new `CertificationJob`.

**AC-5**
Given a `CertificationMetadata` record with `terminal_state = CERTIFIED` already exists for the audit identity tuple,
When `rcp certify audit` is invoked with `--force`,
Then Phase 7 must produce a new certification event with a new `certificate_id` at a new S3 key, and the prior certificate artifact must remain at its original S3 key unmodified.

**AC-6**
Given a `CertificationMetadata` record with `terminal_state = CERTIFICATION_FAILED` exists for the audit identity tuple,
When `rcp certify audit` is invoked without `--force`,
Then Phase 7 must proceed with a new certification attempt.

### Domain Execution

**AC-7**
Given a valid Phase 6 report artifact,
When Phase 7 executes all certification domains,
Then `domain_results[]` must contain exactly eight entries — one per domain — with no domain identifier missing from the bounded set.

**AC-8**
Given a valid Phase 6 report artifact with all integrity checks passing,
When Phase 7 executes all certification domains,
Then all eight domain statuses must be `PASSED` and `terminal_state` must be `CERTIFIED`.

**AC-9**
Given a Phase 6 report artifact where `methodology_disclosure` is absent or empty,
When Phase 7 executes the `METHODOLOGY_COMPLIANCE` domain,
Then that domain's status must be `FAILED` and `disclosed_failures` must include `METHODOLOGY_COMPLIANCE`.

**AC-10**
Given a Phase 6 report artifact where `executive_summary.composite_score_value` is outside `[0.0, 1.0]`,
When Phase 7 executes the `REPORT_INTEGRITY` domain,
Then that domain's status must be `FAILED`.

**AC-11**
Given a Phase 6 report artifact where `executive_summary.endpoint_count` does not match the count of elements in `endpoints[]`,
When Phase 7 executes the `OBSERVATION_COVERAGE` domain,
Then that domain's status must be `FAILED`.

**AC-12**
Given a Phase 6 report artifact where `aggregate_set_hash` in the S3 artifact does not match `aggregate_set_hash` in `ReportMetadata`,
When Phase 7 executes the `EVIDENCE_LINEAGE` domain,
Then that domain's status must be `FAILED` and `disclosed_failures` must include `EVIDENCE_LINEAGE`.

**AC-13**
Given a Phase 6 report artifact with duplicate `endpoint_id` values in `endpoints[]`,
When Phase 7 executes the `REPORT_INTEGRITY` domain,
Then that domain's status must be `FAILED`.

**AC-14**
Given a Phase 6 report artifact where `executive_summary.score_label` is not a member of `{HIGH_CONFIDENCE, MODERATE_CONFIDENCE, LOW_CONFIDENCE}`,
When Phase 7 executes the `REPORT_INTEGRITY` domain,
Then that domain's status must be `FAILED`.

**AC-15**
Given a Phase 6 report artifact where `endpoints[]` is not lexicographically sorted by `endpoint_id`,
When Phase 7 executes the `REPORT_INTEGRITY` domain,
Then that domain's status must be `FAILED`.

**AC-16**
Given a Phase 6 report artifact where any endpoint in `endpoints[]` is missing a required sub-section (`stability_analysis`, `burst_analysis`, or `consistency_analysis`),
When Phase 7 executes the `METHODOLOGY_COMPLIANCE` domain,
Then that domain's status must be `FAILED`.

**AC-17**
Given a Phase 6 report artifact where `ReportMetadata.endpoint_count` does not match `executive_summary.endpoint_count`,
When Phase 7 executes the `EVIDENCE_INTEGRITY` domain,
Then that domain's status must be `FAILED`.

### Terminal State Determination

**AC-18**
Given all eight domain check statuses are `PASSED`,
When Phase 7 determines terminal state,
Then `terminal_state` must be `CERTIFIED` and `disclosed_failures` must be an empty array.

**AC-19**
Given one or more domain check statuses are `FAILED`,
When Phase 7 determines terminal state,
Then `terminal_state` must be `CERTIFICATION_FAILED` and `disclosed_failures` must enumerate all domain identifiers with `FAILED` status.

**AC-20**
Given Phase 7 cannot complete any domain check due to inaccessible Phase 6 artifacts or infrastructure failure,
When Phase 7 determines terminal state,
Then `terminal_state` must be `CERTIFICATION_BLOCKED` and `disclosed_failures` must enumerate all domain identifiers that could not complete.

**AC-21**
Given identical Phase 6 report artifact content and identical `ReportMetadata` fields,
When Phase 7 certification is executed twice (using `--force` on the second invocation),
Then both certificates must have identical `domain_results[]`, `terminal_state`, and `disclosed_failures` within `cert_v1`.

### Certificate Persistence

**AC-22**
Given any terminal state,
When Phase 7 completes certification,
Then a Platform Integrity Certificate JSON artifact must be written to S3 under the `integrity/` key prefix, and a `CertificationMetadata` DynamoDB record must be written with the corresponding `terminal_state`.

**AC-23**
Given certification completes with any terminal state,
When the certificate artifact is inspected,
Then it must contain all required fields: `certificate_id`, `certificate_version`, `generated_at`, `generator_version`, `terminal_state`, `certification_summary`, `report_id`, `report_version`, `intelligence_version`, `aggregate_set_hash`, `s3_report_artifact_ref`, `client_id`, `audit_id`, `audit_execution_id`, `domain_results`, and `disclosed_failures`.

**AC-24**
Given certification completes,
When the certificate artifact is inspected,
Then no Phase 5 intelligence conclusions must be re-derived, re-stated as Phase 7 conclusions, or present as Phase 7-owned values. The certificate must reference Phase 6 artifact content by field path only.

**AC-25**
Given certification completes,
When Phase 7 writes the `CertificationMetadata` DynamoDB record,
Then no Phase 6 `ReportMetadata` record, Phase 6 `ReportJob` record, or any Phase 5, Phase 4, or earlier-phase DynamoDB record must be written, updated, or deleted.

**AC-26**
Given the `CertificationJob` record is created with `status = PENDING`,
When certification completes successfully,
Then the `CertificationJob` record must have transitioned to `status = COMPLETE`.

### Disclosure

**AC-27**
Given `terminal_state = CERTIFICATION_FAILED`,
When the certificate is produced,
Then `disclosed_failures` must enumerate all domain identifiers with `FAILED` status and `failure_details` for each failed domain must be non-empty.

**AC-28**
Given `terminal_state = CERTIFICATION_BLOCKED`,
When the certificate is produced,
Then `disclosed_failures` must enumerate all domain identifiers that could not complete and `certification_summary` must reflect the blocked state deterministically.

### Retrieval CLI

**AC-29**
Given a `CertificationMetadata` record exists for the audit identity tuple,
When `rcp retrieve cert-status` is invoked,
Then the output must include `terminal_state`, `certificate_id`, `generated_at`, and `report_id`, and no write operations must occur.

**AC-30**
Given a `CertificationMetadata` record exists for the audit identity tuple,
When `rcp retrieve cert-json` is invoked,
Then the full Platform Integrity Certificate JSON artifact must be returned from S3 with a provenance envelope containing `certificate_version`, `certificate_id`, `report_id`, `report_version`, and `generated_at`.

**AC-31**
Given no `CertificationMetadata` record exists for the audit identity tuple,
When any `rcp retrieve cert-*` command is invoked,
Then the command must return a structured error `CERTIFICATION_NOT_FOUND` and perform no write operations.

**AC-32**
Given a `CertificationMetadata` record with `terminal_state = CERTIFICATION_FAILED` exists,
When `rcp retrieve cert-summary` is invoked,
Then the output must include the `CERTIFICATION_FAILED` terminal state, `disclosed_failures` list, and all domain statuses.

---

## 8. Out of Scope

The following are explicitly out of scope for Phase 7:

- Re-computation of any Phase 5 reliability score, composite score, component score, or label
- Re-derivation of any Phase 5 intelligence conclusion
- Regeneration of any Phase 6 Release Confidence Report
- Modification, update, or amendment of any Phase 6 report artifact
- Rescoring of raw execution evidence
- Reinterpretation of audit observations
- Direct read of Phase 5 intelligence artifacts (`IntelligenceJob`, `IntelligenceMetadata`, Phase 5 S3 artifacts)
- Direct read of Phase 4 aggregation artifacts (`AggregateSetCompletion`, Phase 4 DynamoDB records)
- Direct read of Phase 1/2/3 raw execution evidence records or run metadata
- Read of Phase 6 `ReportJob` records (these are Phase 6-internal audit log records, excluded from the Phase 7 consumer contract)
- CI/CD integration of any kind (GitHub Actions, Jenkins, GitLab CI, CircleCI, etc.) — these belong to post-Phase 7 phases
- Customer portal, web interface, or dashboard
- Event-driven Lambda trigger from `ReportMetadata` status change
- Real-time or streaming certification delivery
- Certification comparison, trending, or historical analysis across multiple audits
- Configurable certification thresholds or custom domain rule overrides
- Multi-audit certification aggregation or portfolio-level integrity certificates
- Certification failure remediation instructions or replay recommendations
- Communication of failures directly to the audit customer (this is an operator responsibility)
- Phase 8 Commercialization consumer contract (authored in Phase 7.1 as a documentation deliverable but not implemented)

---

## 9. Phase 7 Success Criteria

### From Product Constitution (verbatim)

- Audit platform integrity is verified
- Evidence quality is certified
- Report integrity is defensible

### Spec-Level Success Criteria

Phase 7 is complete when all of the following are true:

1. All Phase 7.1 documentation artifacts are HITL-approved: product spec, technical design, certificate schema, Phase 8 consumer contract, QA plan.
2. The `cert_v1` Platform Integrity Certificate schema is defined, versioned in code, and covered by a compatibility gate test.
3. `rcp certify audit` produces a deterministic Platform Integrity Certificate for a known Phase 6 report artifact fixture input.
4. All eight certification domains execute for every invocation and produce structured `domain_results` entries with correct field coverage.
5. `CERTIFIED` terminal state is produced for a clean Phase 6 report artifact with all integrity checks passing.
6. `CERTIFICATION_FAILED` terminal state is produced when any single domain check fails, with correct `disclosed_failures` enumeration and non-empty `failure_details`.
7. `CERTIFICATION_BLOCKED` terminal state is produced when required Phase 6 artifacts are missing or inaccessible.
8. The Phase 7 prerequisite gate (`ReportMetadata.status = COMPLETE`) is enforced unconditionally. No `CertificationJob` is created if the gate is not satisfied.
9. No Phase 5 or Phase 4 artifact is read directly by any Phase 7 code path.
10. No Phase 6 artifact or DynamoDB record is mutated by any Phase 7 code path.
11. All four certification retrieval CLI commands return correct data with complete provenance envelopes, and none perform write operations.
12. The Phase 7.8 validation campaign confirms correct `CERTIFIED`, `CERTIFICATION_FAILED`, and `CERTIFICATION_BLOCKED` behavior against known Phase 6 report fixture artifacts, including per-domain failure injection tests.

---

## 10. Exit Criteria

Phase 7 is considered complete when all of the following conditions are met:

1. Phase 7.1 documentation is complete and HITL-approved: product spec (`this document`), technical design, certificate schema, Phase 8 consumer contract, and QA plan.
2. The `cert_v1` certificate schema Pydantic model is defined, versioned, and stable in code.
3. `rcp certify audit` CLI command is implemented and all acceptance criteria in Section 7 pass.
4. All eight certification domains are implemented and individually testable.
5. Certificate persistence is implemented: S3 write under `integrity/` prefix, `CertificationJob` and `CertificationMetadata` DynamoDB writes.
6. All four retrieval CLI commands (`cert-status`, `cert-summary`, `cert-domains`, `cert-json`) are implemented and pass all retrieval acceptance criteria.
7. Phase 7 validation campaign (subphase 7.8) confirms correct behavior for all three terminal states against known fixtures.
8. Phase 7 passes per-domain failure injection tests for each of the eight domains independently.
9. No Phase 6, Phase 5, Phase 4, or earlier-phase artifact is mutated by any Phase 7 code path, verified by test.
10. QA sign-off is formally recorded.
11. HITL validation is obtained before Phase 7 PR is created.

---

## 11. Subphase Breakdown

| Subphase | Scope |
| --- | --- |
| 7.1 | Documentation — product spec, technical design, certificate schema, Phase 8 consumer contract, QA plan |
| 7.2 | Certificate Model — `PlatformIntegrityCertificate` Pydantic model, domain result models, constants, versioning |
| 7.3 | Certification Engine — prerequisite gate, `CertificationJob` status lifecycle, domain executor, terminal state determination |
| 7.4 | Domain Implementations — all eight certification domain check implementations |
| 7.5 | Certificate Persistence — S3 artifact write under `integrity/` prefix, DynamoDB `CertificationJob` + `CertificationMetadata` records |
| 7.6 | Certification CLI — `rcp certify audit` operator command |
| 7.7 | Engineering Retrieval CLI — `rcp retrieve cert-*` operator commands |
| 7.8 | Validation Campaign — live certification validation against known Phase 6 report fixture artifacts |

---

## 12. Traceability

- Phase 6 → Phase 7 Consumer Contract: `docs/architecture/phase_6_phase7_consumer_contract.md`
- Phase 6 Product Spec: `docs/product/phase_6_deterministic_reporting_product_spec.md`
- Phase 6 Technical Design: `docs/architecture/phase_6_deterministic_reporting_technical_design.md`
- Phase 6 Report Schema: `docs/architecture/phase_6_report_schema.md`
- Naming and Schema Versioning: `docs/architecture/naming_and_schema_versioning.md`
- Product Constitution: `RCP_Product_Strategy.md`
