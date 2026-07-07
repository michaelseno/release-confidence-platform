# Technical Design

## Phase 7 — Audit Platform Integrity

---

## 1. Feature Overview

Phase 7 is the Audit Platform Integrity layer of the Release Confidence Platform. It is the final phase of the technical MVP (Phases 0 through 7).

Phase 7 occupies the terminal position in the platform pipeline:

```
Phase 1/2/3 (Execution, Evidence Capture, Finalization)
    → Phase 4 (Aggregation — produces deterministic aggregate facts)
        → Phase 5 (Reliability Intelligence — produces interpretation)
            → Phase 6 (Deterministic Reporting — produces Release Confidence Reports)
                → Phase 7 (Audit Platform Integrity — certifies the audit process)
```

**Constitutional boundary statement:** "Reporting owns presentation. Phase 7 owns platform integrity certification."

Phase 7 answers a fundamentally different question than all prior phases:

- Prior phases determine: Is the customer's API operationally reliable?
- Phase 7 determines: Can the customer trust the audit process that produced the Release Confidence Report?

Phase 7 is verification-only. It reads Phase 6 `ReportMetadata` DynamoDB records and S3 report artifacts — inputs defined by the locked `phase7_consumer_contract_v1` — and produces a single output: the **Platform Integrity Certificate**, an immutable artifact that certifies (or discloses the failure to certify) the trustworthiness of a completed audit.

Phase 7 never re-derives, re-scores, re-aggregates, or modifies any prior phase artifact. These boundaries are unconditional and cannot be waived.

**Inputs:**
- `ReportMetadata` DynamoDB record (prerequisite gate: `status = COMPLETE`)
- S3 report artifact at `ReportMetadata.s3_artifact_ref`

**Outputs:**
- Platform Integrity Certificate (S3 artifact under `integrity/` key prefix)
- `CertificationJob` DynamoDB record (execution log per invocation)
- `CertificationMetadata` DynamoDB record (authoritative terminal state per audit identity tuple)

This document covers all Phase 7 subphases:

| Subphase | Scope |
| --- | --- |
| 7.1 | Documentation — product spec, this technical design, certificate schema, Phase 8 consumer contract, QA plan |
| 7.2 | Certificate Model — `PlatformIntegrityCertificate` Pydantic model, domain result models, constants, versioning |
| 7.3 | Certification Engine — prerequisite gate, `CertificationJob` status lifecycle, domain executor, terminal state determination |
| 7.4 | Domain Implementations — all eight certification domain check implementations |
| 7.5 | Certificate Persistence — S3 artifact write under `integrity/` prefix, DynamoDB `CertificationJob` + `CertificationMetadata` records |
| 7.6 | Certification CLI — `rcp certify audit` operator command |
| 7.7 | Engineering Retrieval CLI — `rcp retrieve cert-*` operator commands |
| 7.8 | Validation Campaign — live certification validation against known Phase 6 report fixture artifacts |

---

## 2. Product Requirements Summary

The following requirements from `docs/product/phase_7_audit_platform_integrity_product_spec.md` govern this design:

| Requirement | Description |
| --- | --- |
| FR-1 | Prerequisite gate: `ReportMetadata.status = COMPLETE` must be verified before any certification activity begins |
| FR-2 | Idempotency: prior `CERTIFIED` record blocks re-certification without `--force`; prior `CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED` does not block re-certification |
| FR-3 | Eight certification domains execute for every invocation; no domain may be skipped |
| FR-4 | Terminal state is deterministic: `CERTIFIED` (all domains pass), `CERTIFICATION_FAILED` (one or more domains fail), `CERTIFICATION_BLOCKED` (domain completion blocked by infrastructure or missing artifacts); BLOCKED takes precedence over FAILED |
| FR-5 | Platform Integrity Certificate is immutable once written to S3 under `integrity/` prefix; force re-runs produce new `certificate_id` at a new S3 key; prior certificates are never overwritten |
| FR-6 | Certificate persisted to S3 and `CertificationMetadata` written to DynamoDB for every invocation, including CERTIFICATION_FAILED and CERTIFICATION_BLOCKED terminal states |
| FR-7 | `disclosed_failures` in the certificate enumerates all domain identifiers with `FAILED` or `BLOCKED` status; `failure_details` is non-empty for each failed domain |
| FR-8 | Certificate JSON serialized with `sort_keys=True` and 3-decimal-place precision on all numeric fields |
| FR-9 | Certification decisions are deterministic: same Phase 6 inputs always produce the same certification result within `cert_v1` |
| FR-10 | Phase 7 must not read Phase 5, Phase 4, or earlier artifacts at any point |
| FR-11 | Phase 7 must not write, update, or delete any Phase 6, Phase 5, Phase 4, or earlier DynamoDB record or S3 artifact |
| FR-12 | `rcp certify audit` CLI command with required identity arguments and optional `--force` flag |
| FR-13 | Four read-only retrieval CLI commands (`cert-status`, `cert-summary`, `cert-domains`, `cert-json`) with provenance envelopes; no write operations permitted in retrieval commands |
| NFR-1 | Certification is operator-invoked; no event-driven trigger; no CI/CD integration |
| NFR-2 | No customer-facing interface; no portal or dashboard |
| NFR-3 | No re-computation, re-scoring, or re-derivation of any Phase 5 or Phase 6 analytical conclusion |

---

## 3. Requirement-to-Architecture Mapping

| Requirement | Architecture Decision |
| --- | --- |
| FR-1 — Prerequisite gate | Enforced at `engine.py` entry via `repository.py` DynamoDB GetItem before `CertificationJob` creation |
| FR-2 — Idempotency | `CertificationMetadata` DynamoDB read at pipeline entry; `--force` bypasses only for prior `CERTIFIED` state |
| FR-3 — Eight domains execute | `engine.py` domain executor invokes all eight domain modules sequentially; result collection enforces exactly eight entries |
| FR-4 — Deterministic terminal state | `engine.py` terminal state determination function: all-PASSED → `CERTIFIED`; any-FAILED → `CERTIFICATION_FAILED`; any-BLOCKED → `CERTIFICATION_BLOCKED` (BLOCKED precedence over FAILED) |
| FR-5 — Certificate immutability | `publisher.py` writes to immutable S3 key including `certjob_id`; no overwrite path exists |
| FR-6 — Certificate always written | `engine.py` writes certificate and `CertificationMetadata` for all terminal states, including FAILED and BLOCKED |
| FR-7 — `disclosed_failures` enumeration | `engine.py` collects domain identifiers with FAILED or BLOCKED status after domain execution |
| FR-8 — Canonical serialization | `publisher.py`: `json.dumps(cert.model_dump(), sort_keys=True, indent=2)` |
| FR-9 — Determinism | No `datetime.now()` inside domain checks; `generated_at` passed from `engine.py`; domain logic reads only Phase 6 artifact fields |
| FR-10 — No prior artifact reads | `repository.py` contains no read methods targeting Phase 5, Phase 4, or earlier sort key prefixes |
| FR-11 — No prior artifact writes | `repository.py` contains no write methods targeting any sort key prefix other than `#CERTJOB#` and `#CERT#` |
| FR-12 — CLI command | `rcp certify audit` in `commands.py`; argument validation via `validate_identifier` for all identity components |
| FR-13 — Retrieval CLI | Four `retrieve cert-*` commands in `commands.py`; each performs DynamoDB read then optional S3 read; no write path exists |
| NFR-1 — Operator-invoked | No Lambda trigger, no EventBridge schedule; CLI-only invocation |
| NFR-3 — No re-computation | Domain modules contain no scoring formulas, label derivations, or aggregation logic; checks are purely logical assertions on Phase 6 artifact fields |

---

## 4. Technical Scope

### Current Technical Scope

- New `audit_platform_integrity/` module under `src/release_confidence_platform/`.
- CLI commands: `rcp certify audit` and four `rcp retrieve cert-*` commands.
- DynamoDB: two new record types (`CertificationJob`, `CertificationMetadata`) written to the existing platform metadata table.
- S3: immutable certificate artifact written to `integrity/` key prefix.
- `PlatformIntegrityCertificate` Pydantic model as the single certificate representation.
- Certification engine: prerequisite gate, domain executor, terminal state determination, persistence.
- Eight certification domain implementations (one module per domain).
- `cert_v1` certificate schema defined, versioned in code, and covered by a compatibility gate test.
- Unit and integration tests for all modules.
- Phase 7.8 validation campaign against known Phase 6 report fixture artifacts.
- Phase 8 consumer contract document (7.1 documentation deliverable; the implementation of Phase 8 is out of scope).

### Out of Scope

- Re-computation of any Phase 5 reliability score, composite score, or label.
- Re-derivation of any Phase 5 intelligence conclusion.
- Regeneration or modification of any Phase 6 report artifact.
- Rescoring of raw execution evidence.
- Direct reads of Phase 5 intelligence artifacts, Phase 4 aggregation artifacts, or Phase 1/2/3 raw evidence records.
- Event-driven Lambda trigger from `ReportMetadata` status changes.
- CI/CD integration of any kind.
- Customer portal, web interface, or dashboard.
- Real-time or streaming certification delivery.
- Configurable certification thresholds or custom domain rule overrides.
- Multi-audit certification aggregation or portfolio-level integrity certificates.
- Phase 8 Commercialization implementation.

### Future Technical Considerations

These ideas may be useful after Phase 7 but must not affect current implementation scope:

- Event-driven certification triggered automatically on `ReportMetadata.status = COMPLETE` transition.
- CI/CD gate integration referencing certificate `terminal_state`.
- Certification trending and historical analysis across multiple audits.
- Customer-visible certificate delivery via customer portal.

---

## 5. Architecture Overview

### 5.1 Platform Pipeline Position

```
[Phase 1/2/3]       Execution, Evidence Capture, Finalization
      │
      ▼
[Phase 4]           Aggregation → AggregateSetCompletion (immutable fact layer)
      │
      ▼
[Phase 5]           Reliability Intelligence → IntelligenceMetadata + S3 intelligence artifact
      │
      ▼
[Phase 6]           Deterministic Reporting → ReportMetadata + S3 report artifact
      │
      ▼              ◄── Phase 7 consumer contract v1 (this phase's input boundary)
[Phase 7]           Audit Platform Integrity → CertificationMetadata + S3 certificate artifact
```

### 5.2 Phase 7 Internal Component Overview

```
rcp certify audit <args>
        │
        ▼
[CertificationEngine]                     engine.py
   │  Prerequisite Gate (ReportMetadata.status = COMPLETE)
   │  Idempotency Gate (CertificationMetadata prior CERTIFIED)
   │  CertificationJob lifecycle (PENDING → IN_PROGRESS → COMPLETE|FAILED)
   │
   ├─► [CertificationRepository]          repository.py
   │      DynamoDB reads: ReportMetadata, CertificationMetadata
   │      DynamoDB writes: CertificationJob, CertificationMetadata
   │
   ├─► [CertificationPublisher]           publisher.py
   │      S3 reads: Phase 6 report artifact (via s3_artifact_ref)
   │      S3 writes: Phase 7 certificate artifact (integrity/ prefix)
   │
   └─► [Domain Executor]                  engine.py + domains/
           │
           ├── RUNNER_HEALTH              domains/runner_health.py
           ├── EVIDENCE_COMPLETENESS      domains/evidence_completeness.py
           ├── EVIDENCE_INTEGRITY         domains/evidence_integrity.py
           ├── EVIDENCE_LINEAGE           domains/evidence_lineage.py
           ├── OBSERVATION_COVERAGE       domains/observation_coverage.py
           ├── SCHEDULER_INTEGRITY        domains/scheduler_integrity.py
           ├── METHODOLOGY_COMPLIANCE     domains/methodology_compliance.py
           └── REPORT_INTEGRITY           domains/report_integrity.py
                    │
                    ▼
           Terminal State Determination
           (CERTIFIED | CERTIFICATION_FAILED | CERTIFICATION_BLOCKED)
                    │
                    ▼
           PlatformIntegrityCertificate (models.py)
```

### 5.3 Read / Write Separation

Phase 7 reads from two Phase 6 sources and writes to two Phase 7 destinations. These paths do not overlap:

| Operation | Source / Destination | What Phase 7 Does |
| --- | --- | --- |
| Read ReportMetadata | Phase 6 DynamoDB (PK/SK per consumer contract) | Read-only; prerequisite gate |
| Read S3 report artifact | Phase 6 S3 (`reports/` prefix) | Read-only; input to domain checks |
| Write CertificationJob | Phase 7 DynamoDB (`#CERTJOB#` SK prefix) | New record only |
| Write CertificationMetadata | Phase 7 DynamoDB (`#CERT#` SK prefix) | New or update per invocation |
| Write certificate artifact | Phase 7 S3 (`integrity/` prefix) | Immutable new object per invocation |

Phase 7 has no write path to Phase 6 sort key namespaces. Phase 7 has no read path to Phase 5, Phase 4, or earlier sort key namespaces.

---

## 6. Certification Domain Architecture

### 6.1 Domain Execution Pattern

Each certification domain is an independent, stateless verification unit. All eight domains execute for every certification invocation. No domain may skip, short-circuit another domain, or depend on the result of another domain.

Every domain receives two inputs:
1. The deserialized `ReportMetadata` record (stable fields per `phase7_consumer_contract_v1` Section 3.1).
2. The deserialized Phase 6 report artifact (stable sections per `phase7_consumer_contract_v1` Section 3.2).

Every domain produces one output: a `DomainResult` record containing:

| Field | Type | Description |
| --- | --- | --- |
| `domain` | String | Domain identifier from bounded set |
| `status` | String | `PASSED`, `FAILED`, or `BLOCKED` |
| `checks_performed` | Integer | Number of logical checks executed in this domain |
| `checks_passed` | Integer | Number of checks that passed |
| `failure_details` | String[] | Descriptions of failed checks; empty array if PASSED |
| `evidence_refs` | String[] | Phase 6 artifact field paths evaluated in this domain |

`BLOCKED` status is used exclusively when a domain cannot complete a check because required artifact fields are missing or inaccessible (null, absent, or parse failure). `BLOCKED` is not used for logical check failures; those are `FAILED`.

A domain module must not raise an unhandled exception. Infrastructure failures (S3 read errors, JSON parse errors) that prevent a domain from executing must produce `BLOCKED` status with a descriptive `failure_details` entry. The domain executor must catch and contain these failures so all remaining domains continue to execute.

---

### 6.2 RUNNER_HEALTH

**Purpose:** Verify that runners operated within expected health parameters during the audit window.

**Inputs consumed:**
- `endpoints[*].reliability_metrics` (all per-endpoint metrics including source_field_refs)
- `executive_summary.total_executions`
- `methodology_disclosure`

**Validation logic:**

| Check | Pass Criteria |
| --- | --- |
| Execution count range | `executive_summary.total_executions` is greater than zero and within the expected range for the audit window as defined by `methodology_disclosure` configuration fields |
| No zero-result endpoint | No endpoint in `endpoints[]` has `reliability_metrics.total_executions = 0` |
| Error rate threshold | No endpoint's computed failure rate (total_fail / total_executions) exceeds the methodology threshold referenced in `methodology_disclosure` |
| Methodology trace consistency | `methodology_trace` is present and non-null in all per-endpoint analysis sub-sections; references are internally consistent |

**Pass criteria:** All four checks pass for all endpoints.

**Fail criteria:** Any check fails for any endpoint.

**BLOCKED criteria:** `endpoints[]` is absent or non-iterable; `methodology_disclosure` is absent; required `reliability_metrics` fields are null on any endpoint.

**Evidence refs written to domain result:**
`executive_summary.total_executions`, `endpoints[*].reliability_metrics`, `methodology_disclosure`

---

### 6.3 EVIDENCE_COMPLETENESS

**Purpose:** Verify that the evidence base is complete relative to what the audit configuration required.

**Inputs consumed:**
- `executive_summary` (total_executions, endpoint_count)
- `endpoints[*].reliability_metrics`
- `methodology_disclosure`

**Validation logic:**

| Check | Pass Criteria |
| --- | --- |
| Total execution count | `executive_summary.total_executions` is within the expected range for the configured audit window and execution frequency as defined in `methodology_disclosure` |
| Per-endpoint minimum | No endpoint has `reliability_metrics.total_executions` below the methodology minimum observation count referenced in `methodology_disclosure` |
| Required fields present | All required `reliability_metrics` fields (total_executions, total_pass, total_fail, audit_success_rate) are present and non-null for every endpoint |
| Endpoint count positive | `executive_summary.endpoint_count` is greater than zero |

**Pass criteria:** All four checks pass.

**Fail criteria:** Any check fails.

**BLOCKED criteria:** `executive_summary` is absent; `endpoints[]` is absent; `methodology_disclosure` is absent; required fields cannot be read.

**Evidence refs:** `executive_summary.total_executions`, `executive_summary.endpoint_count`, `endpoints[*].reliability_metrics`, `methodology_disclosure`

---

### 6.4 EVIDENCE_INTEGRITY

**Purpose:** Verify that the Phase 6 report artifact is intact — that identity fields are consistent with `ReportMetadata` and that cross-record fields match.

**Inputs consumed:**
- `ReportMetadata` stable fields: `report_id`, `report_version`, `intelligence_version`, `aggregate_set_hash`, `endpoint_count`
- `identity.report_id`, `identity.report_version`
- `intelligence_provenance.intelligence_version`, `intelligence_provenance.aggregate_set_hash`
- `executive_summary.endpoint_count`

**Validation logic:**

| Check | Pass Criteria |
| --- | --- |
| Aggregate set hash cross-reference | `aggregate_set_hash` in the S3 artifact (`intelligence_provenance.aggregate_set_hash`) matches `aggregate_set_hash` in `ReportMetadata` |
| Report ID cross-reference | `identity.report_id` in the S3 artifact matches `report_id` in `ReportMetadata` |
| Report version cross-reference | `identity.report_version` in the S3 artifact matches `report_version` in `ReportMetadata` |
| Intelligence version cross-reference | `intelligence_provenance.intelligence_version` in the S3 artifact matches `intelligence_version` in `ReportMetadata` |
| Endpoint count cross-reference | `ReportMetadata.endpoint_count` matches `executive_summary.endpoint_count` in the S3 artifact |

**Pass criteria:** All five cross-reference checks pass.

**Fail criteria:** Any mismatch detected between the S3 artifact and `ReportMetadata`.

**BLOCKED criteria:** Any required field from `ReportMetadata` is absent; any required field from the S3 artifact is absent or null.

**Evidence refs:** `identity.report_id`, `identity.report_version`, `intelligence_provenance.intelligence_version`, `intelligence_provenance.aggregate_set_hash`, `executive_summary.endpoint_count`, `ReportMetadata.report_id`, `ReportMetadata.report_version`, `ReportMetadata.intelligence_version`, `ReportMetadata.aggregate_set_hash`, `ReportMetadata.endpoint_count`

---

### 6.5 EVIDENCE_LINEAGE

**Purpose:** Verify that the complete evidence lineage chain is unbroken from Phase 4 through the Phase 6 report artifact.

**Inputs consumed:**
- `intelligence_provenance` (all fields)
- `input_lineage` (all fields)
- `ReportMetadata.aggregate_set_hash`

**Validation logic:**

| Check | Pass Criteria |
| --- | --- |
| Aggregate set hash present | `aggregate_set_hash` is present, non-null, and non-empty in both `ReportMetadata` and the S3 artifact (`intelligence_provenance.aggregate_set_hash`) |
| Lineage hash consistency | `intelligence_provenance.aggregate_set_hash` matches `aggregate_set_hash` in `ReportMetadata` |
| Intelligence job ID present | `intelligence_provenance.intelligence_job_id` is present and non-null |
| Input lineage fields complete | All required `input_lineage` fields are present and non-null |
| Intelligence completion timestamp | `intelligence_provenance.intelligence_completed_at` is a valid UTC ISO-8601 timestamp (non-null, parseable) |

**Pass criteria:** All five lineage checks pass.

**Fail criteria:** Any lineage gap, mismatch, or invalid timestamp detected.

**BLOCKED criteria:** `intelligence_provenance` is absent; `input_lineage` is absent; required fields cannot be read.

**Evidence refs:** `intelligence_provenance.aggregate_set_hash`, `intelligence_provenance.intelligence_job_id`, `intelligence_provenance.intelligence_completed_at`, `input_lineage`, `ReportMetadata.aggregate_set_hash`

---

### 6.6 OBSERVATION_COVERAGE

**Purpose:** Verify that all endpoints were observed with sufficient coverage and that coverage claims are internally consistent.

**Inputs consumed:**
- `executive_summary` (endpoint_count, audit_success_rate, total_executions)
- `endpoints[]` (all sub-sections)
- `ReportMetadata.endpoint_count`

**Validation logic:**

| Check | Pass Criteria |
| --- | --- |
| Per-endpoint analysis sub-sections present | Every endpoint in `endpoints[]` has `endpoint_score`, `reliability_metrics`, `stability_analysis`, `burst_analysis`, and `consistency_analysis` present and non-null |
| Artifact endpoint count vs endpoints array | `executive_summary.endpoint_count` matches the count of elements in `endpoints[]` |
| ReportMetadata endpoint count vs endpoints array | `ReportMetadata.endpoint_count` matches the count of elements in `endpoints[]` |
| Audit success rate range | `executive_summary.audit_success_rate` is in `[0.0, 1.0]` with 3 decimal places |
| Total executions consistency | `executive_summary.total_executions` is consistent with per-endpoint `reliability_metrics.total_executions` totals (sum of per-endpoint totals matches or is reconcilable with audit-level total) |

**Pass criteria:** All five coverage checks pass.

**Fail criteria:** Any count mismatch, missing sub-section, or out-of-range value detected.

**BLOCKED criteria:** `endpoints[]` is absent or non-iterable; `executive_summary` is absent; required fields cannot be read.

**Evidence refs:** `executive_summary.endpoint_count`, `executive_summary.audit_success_rate`, `executive_summary.total_executions`, `endpoints[*].endpoint_score`, `endpoints[*].reliability_metrics`, `endpoints[*].stability_analysis`, `endpoints[*].burst_analysis`, `endpoints[*].consistency_analysis`, `ReportMetadata.endpoint_count`

---

### 6.7 SCHEDULER_INTEGRITY

**Purpose:** Verify that the scheduler produced observations consistent with the audit configuration.

**Inputs consumed:**
- `executive_summary.total_executions`
- `executive_summary.endpoint_count`
- `methodology_disclosure`
- `endpoints[*].reliability_metrics`

**Validation logic:**

| Check | Pass Criteria |
| --- | --- |
| Execution count in expected range | `executive_summary.total_executions` is within the expected range for the configured audit window and execution frequency as defined in `methodology_disclosure` (consistent with EVIDENCE_COMPLETENESS; each domain is independently verified) |
| Execution density consistency | Executions per endpoint (total_executions / endpoint_count) is consistent across all endpoints, within the allowed variance defined in `methodology_disclosure` |
| No undisclosed scheduler anomaly | No `methodology_disclosure` content indicates a scheduler anomaly that is not disclosed as a known limitation in `methodology_disclosure.limitations` |

**Pass criteria:** All three scheduler checks pass.

**Fail criteria:** Any scheduler integrity check fails.

**BLOCKED criteria:** `methodology_disclosure` is absent; `executive_summary` fields are absent; `endpoints[]` cannot be iterated.

**Evidence refs:** `executive_summary.total_executions`, `executive_summary.endpoint_count`, `methodology_disclosure`, `endpoints[*].reliability_metrics.total_executions`

---

### 6.8 METHODOLOGY_COMPLIANCE

**Purpose:** Verify that audit execution followed the configured methodology and that methodology disclosure is complete and unabridged.

**Inputs consumed:**
- `methodology_disclosure` (all fields)
- `endpoints[*].stability_analysis` (methodology_trace)
- `endpoints[*].burst_analysis` (methodology_trace)
- `endpoints[*].consistency_analysis` (methodology_trace)
- `endpoints[*].endpoint_score` (score_derivation)

**Validation logic:**

| Check | Pass Criteria |
| --- | --- |
| Methodology disclosure section present | `methodology_disclosure` section is present, non-null, and non-empty in the S3 artifact |
| Required disclosure fields present | All methodology disclosure fields required by `report_v1` schema are present |
| Limitations array present | `methodology_disclosure.limitations` array is present (may be empty if no limitations apply, but must not be absent) |
| Per-endpoint methodology trace | `methodology_trace` is present and non-null for all per-endpoint sub-sections: `stability_analysis`, `burst_analysis`, `consistency_analysis` |
| Score derivation present | `endpoint_score.score_derivation` is present and non-null for every endpoint in `endpoints[]` |

**Pass criteria:** All five methodology checks pass for all endpoints.

**Fail criteria:** Any check fails for any endpoint, or any top-level methodology disclosure field is absent.

**BLOCKED criteria:** `methodology_disclosure` is absent; `endpoints[]` is absent or non-iterable; required fields cannot be read.

**Evidence refs:** `methodology_disclosure`, `endpoints[*].stability_analysis.methodology_trace`, `endpoints[*].burst_analysis.methodology_trace`, `endpoints[*].consistency_analysis.methodology_trace`, `endpoints[*].endpoint_score.score_derivation`

---

### 6.9 REPORT_INTEGRITY

**Purpose:** Verify that the report artifact is internally consistent and that no anomalous values are present that would undermine audit trustworthiness. This domain encompasses both structural consistency and internal anomaly detection.

**Inputs consumed:**
- `identity` (report_version)
- `intelligence_provenance` (intelligence_version)
- `executive_summary` (score_label, composite_score_value, score_label_description)
- `endpoints[]` (endpoint_id, all numeric score fields)

**Validation logic:**

| Check | Pass Criteria |
| --- | --- |
| Report version | `identity.report_version` is `report_v1` |
| Intelligence version | `intelligence_provenance.intelligence_version` is `intel_v1` |
| Score label membership | `executive_summary.score_label` is a member of the bounded set: `{HIGH_CONFIDENCE, MODERATE_CONFIDENCE, LOW_CONFIDENCE}` |
| Composite score range | `executive_summary.composite_score_value` is in `[0.0, 1.0]` with exactly 3 decimal places |
| Endpoint ordering | `endpoints[]` is lexicographically sorted by `endpoint_id` in ascending order |
| No duplicate endpoint IDs | No duplicate `endpoint_id` values exist in `endpoints[]` |
| No null endpoint IDs | No endpoint has a null or empty `endpoint_id` |
| Endpoint numeric score ranges | All numeric score fields for all endpoints are in `[0.0, 1.0]` with 3 decimal places |
| Score label description membership | `executive_summary.score_label_description` is a member of the bounded value set defined in `report_v1` constants |

**Pass criteria:** All nine checks pass for all applicable fields and endpoints.

**Fail criteria:** Any check fails.

**BLOCKED criteria:** `identity` is absent; `executive_summary` is absent; `endpoints[]` is absent or non-iterable.

**Evidence refs:** `identity.report_version`, `intelligence_provenance.intelligence_version`, `executive_summary.score_label`, `executive_summary.composite_score_value`, `executive_summary.score_label_description`, `endpoints[*].endpoint_id`, `endpoints[*].endpoint_score.*`

---

## 7. Certification Execution Pipeline

The following steps execute in strict order. No step may be skipped or reordered:

```
rcp certify audit <identity arguments>
         │
         ▼
[1] Validate input identifiers (validate_identifier for all components)
         │
         ▼
[2] Read ReportMetadata DynamoDB record
    → PK = CLIENT#{client_id}
    → SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#META
    → If absent or status != COMPLETE: abort with REPORT_NOT_COMPLETE
    → No CertificationJob is created; error surfaced to caller
    → This is the Phase 7 prerequisite gate (unconditional)
         │
         ▼
[3] Check CertificationMetadata for prior CERTIFIED record
    → PK = CLIENT#{client_id}
    → SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#CERT#{cert_version}#META
    → If terminal_state = CERTIFIED and not --force: return existing certificate_id and S3 ref; abort
    → If terminal_state != CERTIFIED or --force: continue
         │
         ▼
[4] Generate certjob_id; write CertificationJob DynamoDB record (status = PENDING)
         │
         ▼
[5] Update CertificationJob → IN_PROGRESS
         │
         ▼
[6] Read Phase 6 S3 report artifact
    → Key obtained from ReportMetadata.s3_artifact_ref (must not construct or guess S3 key independently)
    → Deserialize JSON to report artifact structure
         │
         ▼
[7] Execute all eight certification domain checks
    → Domain executor invokes each domain module in sequence
    → Each domain receives ReportMetadata stable fields + deserialized report artifact
    → Domain failures are contained; remaining domains continue regardless
    → domain_results[] collects exactly eight DomainResult entries
         │
         ▼
[8] Determine terminal_state from domain results
    → Any domain with status = BLOCKED → CERTIFICATION_BLOCKED
    → Any domain with status = FAILED (and no BLOCKED) → CERTIFICATION_FAILED
    → All domains PASSED → CERTIFIED
    → BLOCKED takes precedence over FAILED
         │
         ▼
[9] Populate disclosed_failures
    → Collect domain identifiers with status FAILED or BLOCKED
    → Empty list if terminal_state = CERTIFIED
         │
         ▼
[10] Generate certificate_id; set generated_at timestamp
     Construct PlatformIntegrityCertificate model
         │
         ▼
[11] Serialize certificate to canonical JSON (sort_keys=True, indent=2)
     Write certificate artifact to S3 under integrity/ key prefix
         │
         ▼
[12] Write CertificationMetadata DynamoDB record
     → terminal_state, certificate_id, s3_certificate_ref, generated_at
         │
         ▼
[13] Update CertificationJob → COMPLETE
         │
         ▼
[14] Emit structured log record
     → terminal_state, all domain results, certificate_id, S3 key, certjob_id
         │
         ▼
[15] Display certification summary to operator
```

**Error path:** Any unrecoverable infrastructure failure between steps 4 and 13 results in `CertificationJob → FAILED` with structured `failure_stage` and `failure_reason`. If the failure occurs after step 6 and field coverage is sufficient, a `CERTIFICATION_BLOCKED` certificate should still be written (step 11), `CertificationMetadata` written (step 12), and then `CertificationJob` transitioned to `FAILED` (step 13). The certificate artifact, if written, provides a durable record of the blocked state.

---

## 8. Platform Integrity Certificate

### 8.1 Certificate Fields

The `PlatformIntegrityCertificate` Pydantic model must contain all required fields. No optional fields exist in `cert_v1`.

| Field | Type | Source | Description |
| --- | --- | --- | --- |
| `certificate_id` | String | Phase 7 generated | Unique identifier for this certification event; prefix `cert_` |
| `certificate_version` | String | Phase 7 constant | `cert_v1`; fixed from `constants.py` |
| `generated_at` | String | Phase 7 generated | UTC ISO-8601 timestamp passed from `engine.py` at pipeline entry |
| `generator_version` | String | Phase 7 generated | Platform version string |
| `terminal_state` | String | Phase 7 determined | `CERTIFIED` \| `CERTIFICATION_FAILED` \| `CERTIFICATION_BLOCKED` |
| `certification_summary` | String | Phase 7 determined | Fixed string from bounded set: `INTEGRITY_VERIFIED` \| `INTEGRITY_FAILED` \| `INTEGRITY_BLOCKED` |
| `report_id` | String | Phase 6 artifact | `identity.report_id` from Phase 6 S3 artifact |
| `report_version` | String | Phase 6 artifact | `identity.report_version` from Phase 6 S3 artifact |
| `intelligence_version` | String | Phase 6 artifact | `intelligence_provenance.intelligence_version` from Phase 6 S3 artifact |
| `aggregate_set_hash` | String | Phase 6 artifact | `intelligence_provenance.aggregate_set_hash`; completes the full Phase 4 → Phase 7 lineage chain |
| `s3_report_artifact_ref` | String | ReportMetadata | `ReportMetadata.s3_artifact_ref`; reference to the Phase 6 report this certificate covers |
| `client_id` | String | ReportMetadata | Scoped client identifier |
| `audit_id` | String | ReportMetadata | Scoped audit identifier |
| `audit_execution_id` | String | ReportMetadata | Durable execution identity |
| `config_version` | String | ReportMetadata | Configuration version |
| `aggregation_version` | String | ReportMetadata | Phase 4 aggregation version |
| `domain_results` | DomainResult[] | Phase 7 domain executor | Array of exactly eight per-domain verification results |
| `disclosed_failures` | String[] | Phase 7 determined | Domain identifiers with FAILED or BLOCKED status; empty array if CERTIFIED |

### 8.2 Certification Summary Bounded Mapping

Within `cert_v1`, the following mapping is fixed in `constants.py`:

| `terminal_state` | `certification_summary` |
| --- | --- |
| `CERTIFIED` | `INTEGRITY_VERIFIED` |
| `CERTIFICATION_FAILED` | `INTEGRITY_FAILED` |
| `CERTIFICATION_BLOCKED` | `INTEGRITY_BLOCKED` |

This mapping is fixed. It must not be altered without a `certificate_version` increment.

### 8.3 What the Certificate Must Not Contain

- Phase 5 intelligence conclusions re-derived or re-stated as Phase 7 conclusions.
- Re-computed reliability scores, labels, or component scores.
- Editorial commentary on the customer's API reliability.
- Embedded Phase 6 report content (referenced by `s3_report_artifact_ref` key only).
- Recommendations to the customer's engineering team.
- Any field that re-interprets Phase 5 or Phase 6 analytical conclusions.
- Any field that overrides, relabels, or substitutes a Phase 5 `score_label` or `score_label_description`.

### 8.4 Serialization

Certificate JSON serialization uses:

```
json.dumps(certificate.model_dump(), sort_keys=True, indent=2)
```

All numeric fields carry 3-decimal-place precision, consistent with Phase 5 and Phase 6 artifact serialization conventions. `generated_at` is sourced from `engine.py` at pipeline entry and passed into the certificate; it is not generated inside domain modules or publisher.

---

## 9. DynamoDB Schema

Phase 7 writes to the existing platform metadata table. No new DynamoDB tables are introduced.

### 9.1 CertificationJob

**Purpose:** Execution log for each `rcp certify audit` invocation. Provides a durable lifecycle audit trail per certification attempt, independent of the terminal outcome.

**PK:** `CLIENT#{client_id}`

**SK:** `AUDIT#{audit_id}#CERTJOB#{certjob_id}`

**Lifecycle:** `PENDING → IN_PROGRESS → COMPLETE | FAILED`

**Fields:**

| Field | Type | Description |
| --- | --- | --- |
| `PK` | String | `CLIENT#{client_id}` |
| `SK` | String | `AUDIT#{audit_id}#CERTJOB#{certjob_id}` |
| `certjob_id` | String | Unique job identifier; prefix `certjob_` |
| `client_id` | String | Scoped client identifier |
| `audit_id` | String | Scoped audit identifier |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `aggregation_version` | String | Phase 4 aggregation version |
| `intelligence_version` | String | Phase 5 intelligence version |
| `report_version` | String | Phase 6 report version |
| `cert_version` | String | Certificate schema version (`cert_v1`) |
| `status` | String | `PENDING` \| `IN_PROGRESS` \| `COMPLETE` \| `FAILED` |
| `failure_stage` | String or null | Stage at which failure occurred; null if status != FAILED |
| `failure_reason` | String or null | Structured error description; null if status != FAILED |
| `certificate_id` | String or null | Populated on COMPLETE; null during lifecycle |
| `s3_certificate_ref` | String or null | S3 key of the certificate artifact; populated on COMPLETE |
| `created_at` | String | UTC ISO-8601 timestamp of job creation |
| `completed_at` | String or null | UTC ISO-8601 timestamp of terminal state; null until terminal |

**Ownership model:** Scoped per client. Multiple `CertificationJob` records may exist for the same audit identity tuple (one per invocation, including force re-runs).

**Lifecycle:** Immutable at terminal state (`COMPLETE` or `FAILED`). A failed job record is never retried in-place; a new invocation creates a new `certjob_id`.

---

### 9.2 CertificationMetadata

**Purpose:** Authoritative terminal state record for a completed certification event, per audit identity tuple. This is the record Phase 8 consumers will use to discover certification outcomes.

**PK:** `CLIENT#{client_id}`

**SK:** `AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#CERT#{cert_version}#META`

**Fields:**

| Field | Type | Description |
| --- | --- | --- |
| `PK` | String | `CLIENT#{client_id}` |
| `SK` | String | Full composite sort key as above |
| `certificate_version` | String | `cert_v1` |
| `certificate_id` | String | Most recent certificate identifier |
| `certjob_id` | String | Job ID that produced this metadata record |
| `client_id` | String | Scoped client identifier |
| `audit_id` | String | Scoped audit identifier |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `aggregation_version` | String | Phase 4 aggregation version |
| `intelligence_version` | String | Phase 5 intelligence version |
| `report_version` | String | Phase 6 report version |
| `cert_version` | String | Certificate schema version (`cert_v1`) |
| `terminal_state` | String | `CERTIFIED` \| `CERTIFICATION_FAILED` \| `CERTIFICATION_BLOCKED` |
| `certification_summary` | String | Fixed label from bounded set |
| `report_id` | String | Reference to the Phase 6 report this certificate covers |
| `s3_certificate_ref` | String | S3 key of the Phase 7 certificate artifact |
| `s3_report_artifact_ref` | String | S3 key of the Phase 6 report artifact this certificate covers |
| `disclosed_failures` | String[] | Domain identifiers with FAILED or BLOCKED status |
| `created_at` | String | UTC ISO-8601 timestamp of first certification completion |
| `completed_at` | String | UTC ISO-8601 timestamp of most recent certification completion |

**Ownership model:** Scoped per client. One `CertificationMetadata` record per full audit identity tuple (including `cert_version`). Force re-runs update the existing record with the new `certificate_id`, `certjob_id`, `terminal_state`, and `completed_at`.

**Lifecycle:** Updated on each certification completion (including force re-runs). `created_at` is set once on initial write and never modified.

---

### 9.3 DynamoDB Access Patterns

Phase 7 uses the following DynamoDB access patterns:

**Read ReportMetadata (prerequisite gate):**
```
GetItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#META
```

**Read CertificationMetadata (idempotency gate):**
```
GetItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#CERT#{cert_version}#META
```

**Write CertificationJob (new record per invocation):**
```
PutItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#CERTJOB#{certjob_id}
  ConditionExpression: attribute_not_exists(PK)
```

**Update CertificationJob (status transitions):**
```
UpdateItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#CERTJOB#{certjob_id}
```

**Write / Update CertificationMetadata:**
```
PutItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#CERT#{cert_version}#META
```

**Phase 7 must not query:**
- Phase 5 sort key prefixes (`#INTJOB#`, `#INTEL#...#META`)
- Phase 4 sort key prefixes (`#AGG#`, `#AGGJOB#`, `#SET`, `#MANIFEST#`)
- Phase 6 `ReportJob` records (`#RPTJOB#`)
- Any raw evidence, run, or audit lifecycle record

---

## 10. S3 Artifact Structure

### Certificate Artifact Key

```
integrity/{client_id}/{audit_id}/{audit_execution_id}/{config_version}/{aggregation_version}/{intelligence_version}/{report_version}/{cert_version}/{certjob_id}/artifact.json
```

**Example:**
```
integrity/client_abc/audit_xyz/audexec_0b1c2d3e/cfg_v1/agg_v1/intel_v1/report_v1/cert_v1/certjob_4f5a6b7c8d9e0a1b2c3d4e5f/artifact.json
```

**Key properties:**
- `certjob_id` segment guarantees per-invocation uniqueness. Force re-certification produces a new key; the previous certificate artifact is preserved.
- `integrity/` prefix does not overlap with `reports/` (Phase 6), `intelligence/` (Phase 5), or `raw-results/` (Phase 1/2).
- Phase 7 writes to `integrity/` prefix only. Phase 7 reads from `reports/` prefix only (via `ReportMetadata.s3_artifact_ref`).
- Phase 7 must not construct the Phase 6 report artifact S3 key independently. It must use `ReportMetadata.s3_artifact_ref`.

---

## 11. Certificate Schema Versioning and Determinism

### Version Constants

| Constant | Value | Location |
| --- | --- | --- |
| `CERT_VERSION` | `cert_v1` | `constants.py` |
| `certjob_id` prefix | `certjob_` | `constants.py` / `identity.py` |
| `certificate_id` prefix | `cert_` | `constants.py` / `identity.py` |
| `CERTIFICATION_SUMMARY_MAP` | fixed mapping | `constants.py` |

### Versioning Rules

1. The `cert_v1` schema is immutable after Phase 7.1 HITL approval.
2. Structural changes to `PlatformIntegrityCertificate` (field addition, removal, rename, type change) require a new `certificate_version` (e.g., `cert_v2`).
3. New `certificate_version` records are written to distinct `CertificationMetadata` sort keys (the `#CERT#{cert_version}` segment changes). Existing `cert_v1` records are never modified.
4. Changes to the `CERTIFICATION_SUMMARY_MAP` also require a new `certificate_version`.
5. Changes to domain check logic that alter which fields are evaluated or what pass/fail criteria are applied require a new `certificate_version` and HITL approval.

### Determinism Guarantees

| Guarantee | Mechanism |
| --- | --- |
| Identical inputs → identical certification result | Domain checks are pure logical assertions on Phase 6 artifact fields; no random or time-based input |
| Certificate JSON byte-identical for identical inputs | `sort_keys=True`; fixed `generated_at` passed from `engine.py`; no `datetime.now()` inside domain modules |
| `certificate_id` uniqueness | Generated once per invocation in `engine.py`; passed into `PlatformIntegrityCertificate` model construction |
| Domain result ordering | `domain_results[]` array ordered by bounded domain identifier set order; deterministic |
| Numeric precision | Score fields read directly from Phase 6 artifact without re-computation; preserved as-is |

### Compatibility Gate Test

`tests/unit/test_phase7_cert_schema.py` is the compatibility gate test. It validates that the `PlatformIntegrityCertificate` Pydantic model:
- Contains all required fields from the `cert_v1` schema.
- Produces correct `certification_summary` for each `terminal_state`.
- Enforces `certificate_version = cert_v1`.
- Produces byte-identical JSON serialization for identical inputs.
- `domain_results[]` contains exactly eight entries with correct domain identifiers.

---

## 12. Operator CLI Design

Phase 7 extends the operator CLI with two command groups: certification execution (`rcp certify`) and certification retrieval (`rcp retrieve cert-*`).

### 12.1 `rcp certify audit`

**Purpose:** Trigger Phase 7 platform integrity certification for a completed report.

**Signature:**
```
rcp certify audit \
  --client-id CLIENT_ID \
  --audit-id AUDIT_ID \
  --audit-execution-id AUDIT_EXECUTION_ID \
  --config-version CONFIG_VERSION \
  --aggregation-version AGGREGATION_VERSION \
  --intelligence-version INTELLIGENCE_VERSION \
  --report-version REPORT_VERSION \
  [--force]
```

**Required arguments:**

| Argument | Description |
| --- | --- |
| `--client-id` | Scoped client identifier |
| `--audit-id` | Scoped audit identifier |
| `--audit-execution-id` | Durable execution identity |
| `--config-version` | Configuration version |
| `--aggregation-version` | Phase 4 aggregation version |
| `--intelligence-version` | Phase 5 intelligence version |
| `--report-version` | Phase 6 report version (e.g., `report_v1`) |

**Optional argument:**

| Argument | Description |
| --- | --- |
| `--force` | Re-certify even if a `CERTIFIED` record already exists for this audit identity tuple |

**Argument validation:** `validate_identifier` is called on the three primary identity arguments (`client_id`, `audit_id`, `execution`) before any DynamoDB or S3 access. Version string arguments (`config_version`, `aggregation_version`, `intelligence_version`, `report_version`, `cert_version`) are fixed-set values with restricted choices defined by the CLI parser and are not subject to `validate_identifier`. Invalid primary identifiers abort with a structured validation error before the prerequisite gate.

**Output:**

```
Phase 7 Certification — rcp certify audit
==========================================
Prerequisite Gate:     PASS — ReportMetadata.status = COMPLETE
Idempotency Gate:      [PASS — no prior CERTIFIED record | BYPASSED — --force supplied]

Domain Verification Results:
  RUNNER_HEALTH            PASSED   (N checks performed, N passed)
  EVIDENCE_COMPLETENESS    PASSED   (N checks performed, N passed)
  EVIDENCE_INTEGRITY       PASSED   (N checks performed, N passed)
  EVIDENCE_LINEAGE         PASSED   (N checks performed, N passed)
  OBSERVATION_COVERAGE     PASSED   (N checks performed, N passed)
  SCHEDULER_INTEGRITY      PASSED   (N checks performed, N passed)
  METHODOLOGY_COMPLIANCE   PASSED   (N checks performed, N passed)
  REPORT_INTEGRITY         PASSED   (N checks performed, N passed)

Terminal State:        CERTIFIED
Certification Summary: INTEGRITY_VERIFIED

Certificate ID:        cert_xxxxxxxxxxxxxxxx
Certificate Version:   cert_v1
S3 Certificate Ref:    integrity/.../.../artifact.json

Disclosed Failures:    (none)
```

For `CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED` output:
- Domains with FAILED or BLOCKED status display inline failure details.
- `disclosed_failures` lists all failed/blocked domain identifiers.

---

### 12.2 `rcp retrieve cert-status`

**Purpose:** Display `CertificationMetadata` record summary.

**Signature (same identity arguments as `rcp certify audit`):**
```
rcp retrieve cert-status \
  --client-id CLIENT_ID \
  --audit-id AUDIT_ID \
  --audit-execution-id AUDIT_EXECUTION_ID \
  --config-version CONFIG_VERSION \
  --aggregation-version AGGREGATION_VERSION \
  --intelligence-version INTELLIGENCE_VERSION \
  --report-version REPORT_VERSION
```

**Output:**

```
Certificate ID:        cert_xxxxxxxxxxxxxxxx
Certificate Version:   cert_v1
Terminal State:        CERTIFIED
Report ID:             report_xxxxxxxxxxxxxxxx
Generated At:          2026-07-05T12:00:00Z
```

**Constraints:** Read-only. No `CertificationJob` or `CertificationMetadata` record may be written, updated, or deleted by this command.

---

### 12.3 `rcp retrieve cert-summary`

**Purpose:** Display certification summary including terminal state, certification summary string, domain status table, and disclosed failures.

**Signature:** Same identity arguments.

**Output:**

```
Certificate ID:        cert_xxxxxxxxxxxxxxxx
Certificate Version:   cert_v1
Report ID:             report_xxxxxxxxxxxxxxxx
Report Version:        report_v1
Intelligence Version:  intel_v1
Generated At:          2026-07-05T12:00:00Z

Terminal State:        CERTIFIED
Certification Summary: INTEGRITY_VERIFIED

Domain Status:
  RUNNER_HEALTH            PASSED
  EVIDENCE_COMPLETENESS    PASSED
  EVIDENCE_INTEGRITY       PASSED
  EVIDENCE_LINEAGE         PASSED
  OBSERVATION_COVERAGE     PASSED
  SCHEDULER_INTEGRITY      PASSED
  METHODOLOGY_COMPLIANCE   PASSED
  REPORT_INTEGRITY         PASSED

Disclosed Failures:    (none)
```

**Constraints:** Read-only. DynamoDB GetItem for `CertificationMetadata`; S3 read for certificate artifact. No writes.

---

### 12.4 `rcp retrieve cert-domains`

**Purpose:** Display full per-domain verification results from the Platform Integrity Certificate S3 artifact.

**Signature:** Same identity arguments.

**Output:** Full `domain_results[]` array for all eight domains, including `checks_performed`, `checks_passed`, `failure_details`, and `evidence_refs` per domain, preceded by the provenance envelope.

**Constraints:** Read-only.

---

### 12.5 `rcp retrieve cert-json`

**Purpose:** Output the full Platform Integrity Certificate as canonical JSON from S3.

**Signature:** Same identity arguments.

**Output:** Full serialized `PlatformIntegrityCertificate` JSON artifact, preceded by the provenance envelope.

**Constraints:** Read-only.

---

### 12.6 Provenance Envelope

All retrieval commands display the following provenance envelope before section output:

```
Certificate ID:        cert_xxxxxxxxxxxxxxxx
Certificate Version:   cert_v1
Report ID:             report_xxxxxxxxxxxxxxxx
Report Version:        report_v1
Generated At:          2026-07-05T12:00:00Z
```

---

### 12.7 Error Handling in Retrieval Commands

If no `CertificationMetadata` record exists for the audit identity tuple, all `rcp retrieve cert-*` commands must return structured error `CERTIFICATION_NOT_FOUND` and perform no write operations.

---

## 13. Error Codes and Terminal States

### 13.1 Phase 7 Structured Error Codes

| Code | Condition |
| --- | --- |
| `REPORT_NOT_COMPLETE` | `ReportMetadata` record absent or `status != COMPLETE`; no `CertificationJob` is created |
| `CERTIFICATION_ALREADY_CERTIFIED` | `CertificationMetadata.terminal_state = CERTIFIED` exists and `--force` not supplied |
| `S3_REPORT_ARTIFACT_READ_FAILURE` | Phase 6 S3 artifact cannot be read via `s3_artifact_ref` |
| `S3_CERTIFICATE_WRITE_FAILURE` | Phase 7 S3 certificate artifact write fails |
| `CERT_SCHEMA_VALIDATION_ERROR` | `PlatformIntegrityCertificate` model construction fails Pydantic validation |
| `DYNAMODB_WRITE_FAILURE` | DynamoDB write fails for `CertificationJob` or `CertificationMetadata` |
| `CERTIFICATION_NOT_FOUND` | `CertificationMetadata` record absent for the identity tuple (retrieval commands only) |

### 13.2 Terminal States

| Terminal State | Condition | Implication |
| --- | --- | --- |
| `CERTIFIED` | All eight domain check statuses are `PASSED` | Audit platform integrity is verified for this report. Report may be issued. |
| `CERTIFICATION_FAILED` | One or more domain check statuses are `FAILED` and no domain is `BLOCKED` | Integrity verification found failures. Report must not be issued without explicit disclosure of all failed domains. |
| `CERTIFICATION_BLOCKED` | One or more domain checks could not complete due to missing required artifacts, inaccessible data, or infrastructure failure (`BLOCKED` status from any domain) | Platform integrity could not be fully verified. Report must not be issued without operator review and disclosure. `CERTIFICATION_BLOCKED` takes precedence over `CERTIFICATION_FAILED`. |

### 13.3 Idempotency Behavior

| Prior State | `--force` Supplied | Behavior |
| --- | --- | --- |
| `CERTIFIED` | No | Abort; return existing `certificate_id` and S3 ref; no new `CertificationJob` created |
| `CERTIFIED` | Yes | Create new `CertificationJob`; produce new certification event; prior certificate artifact preserved at its original S3 key |
| `CERTIFICATION_FAILED` | No | Proceed with new certification attempt |
| `CERTIFICATION_FAILED` | Yes | Proceed with new certification attempt (same as without `--force`) |
| `CERTIFICATION_BLOCKED` | No | Proceed with new certification attempt |
| `CERTIFICATION_BLOCKED` | Yes | Proceed with new certification attempt (same as without `--force`) |
| No prior record | No or Yes | Proceed with new certification attempt |

---

## 14. Non-Mutation Guarantee

Phase 7 enforces the prohibition on mutating Phase 6 (and earlier) artifacts through the following architectural constraints:

1. **`repository.py` write methods target only Phase 7 sort key namespaces.** Write methods for `CertificationJob` use the `#CERTJOB#` SK prefix. Write methods for `CertificationMetadata` use the `#CERT#` SK prefix. No write method exists that targets `#RPTJOB#`, `#RPT#...#META`, `#INTEL#`, `#AGG#`, or any other Phase 6 or earlier sort key prefix.

2. **`repository.py` read methods for Phase 6 content use GetItem only with the exact `ReportMetadata` SK pattern defined in `phase7_consumer_contract_v1` Section 5.** No write method targets the `ReportMetadata` SK.

3. **`publisher.py` S3 write path targets the `integrity/` prefix only.** S3 write operations in `publisher.py` are parameterized to produce keys with the `integrity/{...}` structure. No write method accepts a key with `reports/`, `intelligence/`, or `raw-results/` prefix.

4. **Domain modules are read-only by design.** Each domain module function signature accepts input data structures and returns a `DomainResult`. No domain module has an interface for DynamoDB writes, S3 writes, or mutation of any data structure passed to it.

5. **Immutable S3 write per invocation.** The `certjob_id` segment in the certificate S3 key guarantees a new key per invocation. No overwrite path exists. S3 writes in `publisher.py` use `PutObject` without override conditions on existing objects; the unique key structure prevents collision.

6. **Test coverage requirement.** A unit test in `tests/unit/audit_platform_integrity/test_repository.py` must assert that no write method in `repository.py` can target Phase 6, Phase 5, or Phase 4 sort key prefixes. A unit test must assert that no Phase 6 `ReportMetadata`, `ReportJob`, or S3 report artifact is modified during a full certification execution against a known fixture.

---

## 15. Module Structure

```
src/release_confidence_platform/
└── audit_platform_integrity/
    ├── __init__.py
    ├── constants.py              # CERT_VERSION, certjob_id prefix, cert_id prefix,
    │                             # CERTIFICATION_SUMMARY_MAP, domain identifier constants
    ├── identity.py               # certjob_id and certificate_id generation
    ├── models.py                 # PlatformIntegrityCertificate Pydantic model,
    │                             # DomainResult, terminal state and status enums
    ├── engine.py                 # Certification pipeline: prerequisite gate → idempotency gate
    │                             # → CertificationJob lifecycle → S3 artifact read
    │                             # → domain executor → terminal state determination
    │                             # → certificate construction → persistence → structured log
    ├── publisher.py              # S3 artifact read (Phase 6 reports/) and write (integrity/)
    ├── repository.py             # DynamoDB: ReportMetadata read (read-only), CertificationJob
    │                             # write/update, CertificationMetadata write/update
    ├── commands.py               # CLI: rcp certify audit, rcp retrieve cert-* commands
    └── domains/
        ├── __init__.py
        ├── base.py               # DomainResult dataclass, domain executor interface
        ├── runner_health.py      # RUNNER_HEALTH domain checks
        ├── evidence_completeness.py  # EVIDENCE_COMPLETENESS domain checks
        ├── evidence_integrity.py     # EVIDENCE_INTEGRITY domain checks
        ├── evidence_lineage.py       # EVIDENCE_LINEAGE domain checks
        ├── observation_coverage.py   # OBSERVATION_COVERAGE domain checks
        ├── scheduler_integrity.py    # SCHEDULER_INTEGRITY domain checks
        ├── methodology_compliance.py # METHODOLOGY_COMPLIANCE domain checks
        └── report_integrity.py       # REPORT_INTEGRITY domain checks
```

CLI commands are registered in `commands.py` under the existing `rcp` Click group following established platform CLI conventions. The `certify` group and `retrieve cert-*` commands must follow the same layering pattern as Phase 6 retrieval commands: CLI commands invoke `engine.py` or service-level methods; they do not interact with storage directly.

Test structure:
```
tests/
├── unit/
│   └── audit_platform_integrity/
│       ├── test_models.py
│       ├── test_engine.py
│       ├── test_repository.py
│       ├── test_publisher.py
│       ├── test_commands.py
│       ├── test_identity.py
│       └── domains/
│           ├── test_runner_health.py
│           ├── test_evidence_completeness.py
│           ├── test_evidence_integrity.py
│           ├── test_evidence_lineage.py
│           ├── test_observation_coverage.py
│           ├── test_scheduler_integrity.py
│           ├── test_methodology_compliance.py
│           └── test_report_integrity.py
├── integration/
│   └── audit_platform_integrity/
│       └── test_certification_pipeline_integration.py
└── unit/
    └── test_phase7_cert_schema.py  # Compatibility gate test
```

---

## 16. Security Considerations

**Authentication and Authorization:**
- Phase 7 is an operator-invoked CLI tool. Authorization is enforced at the IAM level through the AWS credentials used by the CLI process.
- Phase 7 requires read access to the platform metadata DynamoDB table (for `ReportMetadata` and `CertificationMetadata` reads) and write access limited to the `#CERTJOB#` and `#CERT#` sort key namespace within the same table.
- Phase 7 requires read access to the `reports/` S3 prefix and write access to the `integrity/` S3 prefix.
- IAM policies must not grant Phase 7 write access to `reports/`, `intelligence/`, or `raw-results/` S3 prefixes.
- IAM policies must not grant Phase 7 write access to sort key namespaces other than `#CERTJOB#` and `#CERT#`.

**Input Validation:**
- All identity arguments are validated with `validate_identifier` before any DynamoDB or S3 access.
- The Phase 6 report artifact JSON is deserialized and validated against the `ReleaseConfidenceReport` Pydantic model before domain checks begin. Malformed or unexpected JSON produces `CERTIFICATION_BLOCKED` with an appropriate `failure_details` entry.
- No Phase 6 artifact field value is used as a DynamoDB key or S3 key fragment. Field values are used as comparison inputs only.

**Sensitive Data:**
- Structured logs must not include Phase 6 report artifact content beyond field paths and verification results. Payload content, score values, and customer-specific data must not appear in structured log output.
- `failure_details` in domain results must describe what check failed and what condition was found, without reproducing raw customer payload content.

**Misuse Risk:**
- `--force` bypasses the idempotency gate for prior `CERTIFIED` records. Operators must understand that force re-certification creates a new certificate artifact but does not modify or invalidate the prior certificate. Operator training and runbook documentation should address this.
- The `cert-json` retrieval command outputs the full certificate artifact. This output should be treated as an internal operational document; it must not be sent directly to customers without operator review.

---

## 17. Reliability and Operational Considerations

**Retries:**
- Phase 7 does not implement internal retry logic for domain check failures. Domain `BLOCKED` status is the appropriate signal for retriable conditions; the operator reruns `rcp certify audit`.
- DynamoDB conditional writes on `CertificationJob` creation prevent duplicate records from concurrent invocations.
- S3 write failures produce `DYNAMODB_WRITE_FAILURE` or `S3_CERTIFICATE_WRITE_FAILURE` structured errors surfaced to the operator; the operator reruns.

**Timeouts:**
- S3 and DynamoDB API calls must use explicit timeouts consistent with platform standards.
- The domain executor must enforce a total execution timeout across all eight domains. Individual domain failures must not block remaining domain execution.

**Failure Modes:**
- `ReportMetadata` DynamoDB record absent or incomplete: `REPORT_NOT_COMPLETE`; no `CertificationJob` created.
- S3 report artifact read failure after prerequisite gate passes: `CERTIFICATION_BLOCKED` certificate produced if sufficient fields can be populated from `ReportMetadata`; `CertificationJob` transitions to `FAILED`.
- Partial domain execution (infrastructure failure mid-execution): remaining domains receive `BLOCKED` status; `terminal_state = CERTIFICATION_BLOCKED`; certificate written.
- DynamoDB write failure for `CertificationMetadata`: `S3_CERTIFICATE_WRITE_FAILURE` or `DYNAMODB_WRITE_FAILURE`; certificate may be in S3 but metadata record not written; `CertificationJob` transitions to `FAILED`.

**Logging and Monitoring:**
- Structured log records follow the `docs/architecture/structured_logging.md` standard.
- A completion log record at step 14 of the pipeline must include: `event_type = CERTIFICATION_COMPLETE`, `terminal_state`, `certificate_id`, `certjob_id`, all eight domain statuses, `s3_certificate_ref`, `client_id`, `audit_id`.
- A failure log record on any `CertificationJob → FAILED` transition must include: `event_type = CERTIFICATION_FAILED_INFRASTRUCTURE`, `certjob_id`, `failure_stage`, `failure_reason`.
- Prerequisite gate failures must be logged at the appropriate level with `event_type = CERTIFICATION_GATE_BLOCKED`, `reason = REPORT_NOT_COMPLETE`.

**Performance Considerations:**
- Domain checks are in-memory logical assertions on deserialized JSON. The dominant cost is S3 reads (one for the Phase 6 report artifact). No additional network calls occur during domain execution.
- The Phase 6 report artifact size is bounded by the number of endpoints assessed and the fixed report schema. No pagination or chunked read is required.
- For very large `endpoints[]` arrays (high endpoint count audits), the `REPORT_INTEGRITY` and `OBSERVATION_COVERAGE` domains iterate all endpoints. This is O(n) in endpoint count and must complete within the domain executor timeout.

---

## 18. Non-Negotiable Invariants

The following invariants cannot be waived by any future phase or product decision without a formal constitutional amendment approved through HITL governance:

1. Phase 7 shall never re-derive, re-score, or reinterpret any Phase 5 intelligence conclusion or Phase 6 report section.
2. Phase 7 shall never read Phase 5 intelligence artifacts directly for any platform integrity verification purpose.
3. Phase 7 shall never read Phase 4 aggregation artifacts directly.
4. Phase 7 shall never read Phase 1, Phase 2, or Phase 3 raw execution evidence records for any purpose.
5. `ReportMetadata.status = COMPLETE` is the only authoritative prerequisite gate for Phase 7 platform integrity certification. No alternative completeness signal may substitute. No `CertificationJob` may be created if this gate is not satisfied.
6. Phase 7 shall never mutate any Phase 6 report artifact, `ReportMetadata` record, `ReportJob` record, or any Phase 5, Phase 4, or earlier artifact.
7. Certification decisions must be deterministic: identical Phase 6 inputs always produce identical certification results within `cert_v1`.
8. The Platform Integrity Certificate is immutable once written to S3. Prior certificate artifacts are never overwritten or deleted.
9. All eight certification domains must execute for every invocation. No domain may be skipped.
10. Phase 7 may not include CI/CD integrations. These belong to post-Phase 7 phases.
11. Reporting owns presentation. Phase 7 owns platform integrity certification.

---

## 19. Traceability

- Product Spec: `docs/product/phase_7_audit_platform_integrity_product_spec.md`
- Phase 6 → Phase 7 Consumer Contract: `docs/architecture/phase_6_phase7_consumer_contract.md`
- Phase 6 Technical Design: `docs/architecture/phase_6_deterministic_reporting_technical_design.md`
- Phase 6 Report Schema: `docs/architecture/phase_6_report_schema.md`
- Phase 7 Certification Independence ADR: `docs/architecture/adr_phase7_certification_independence.md`
- Naming and Schema Versioning: `docs/architecture/naming_and_schema_versioning.md`
- Structured Logging: `docs/architecture/structured_logging.md`
- Product Constitution: `RCP_Product_Strategy.md`
- Compatibility gate test: `tests/unit/test_phase7_cert_schema.py`
- Non-mutation test: `tests/unit/audit_platform_integrity/test_repository.py`
