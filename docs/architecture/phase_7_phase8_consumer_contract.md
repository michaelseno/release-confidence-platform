# Phase 8 Consumer Contract

## Status

Accepted — Phase 7.1 Deliverable

## Platform Constitutional Statement

**Phase 7 owns platform integrity certification. Phase 8 owns the reference audit and commercialization framework.**

Phase 8 may consume Phase 7 certification artifacts to reference and illustrate the Platform Integrity Certification methodology. Phase 8 shall never re-derive, re-evaluate, or reinterpret any Phase 7 certification domain result, terminal state, or certification summary.

Phase 8 must not read Phase 6 report artifacts directly for any purpose that bypasses Phase 7. The Platform Integrity Certificate is the authoritative attestation of audit trustworthiness. Any Phase 8 reference to audit integrity must reference the Phase 7 certificate, not re-verify it.

---

## 1. Contract Purpose

This document defines the stable contract between the Audit Platform Integrity layer (Phase 7) and the Reference Audit & Commercialization Framework (Phase 8).

It specifies:
- What Phase 8 may consume from Phase 7.
- What Phase 8 must not do.
- Which fields are stable and guaranteed for Phase 8 consumption.
- How contract changes are governed.

This contract becomes a compatibility gate: future Phase 7 changes that would break this contract require a new contract version, HITL approval, and automated regression test validation before implementation may proceed.

---

## 2. Ownership Responsibilities

| Concern | Owner |
| --- | --- |
| Raw execution evidence capture | Phase 1 / Phase 2 |
| Audit lifecycle, scheduling, finalization | Phase 3 |
| Deterministic aggregation, persistence, lineage | Phase 4 (Aggregation) |
| Reliability intelligence derivation | Phase 5 (Reliability Intelligence) |
| Operator and customer reporting | Phase 6 (Deterministic Reporting) |
| Audit platform integrity verification | Phase 7 (Audit Platform Integrity) |
| Reference audit & commercialization framework | Phase 8 (Consumer) |

**Phase 7 responsibilities:**
- Produce an immutable Platform Integrity Certificate artifact for each completed audit.
- Persist the certificate in S3 under the `integrity/` key prefix.
- Persist `CertificationMetadata` in DynamoDB with all stable fields defined in Section 3.1.
- Signal certification completeness through `CertificationMetadata.terminal_state = CERTIFIED` (or `CERTIFICATION_FAILED` / `CERTIFICATION_BLOCKED` for failure cases).
- Expose all domain results, disclosed failures, and lineage references faithfully within the certificate artifact.

**Phase 8 responsibilities:**
- Consume Phase 7 certificate artifacts as authoritative, immutable inputs.
- Reference the certificate by `s3_certificate_ref` key in commercialization documents; do not embed certificate content.
- Not bypass the `CertificationMetadata.terminal_state = CERTIFIED` prerequisite gate when illustrating a complete, successful audit engagement.
- Not re-derive or reinterpret any Phase 7 certification domain result.

---

## 3. What Phase 8 May Consume

Phase 8 may consume only the following Phase 7 artifacts.

### 3.1 CertificationMetadata DynamoDB Record (Prerequisite Gate)

Phase 8 must require `CertificationMetadata.terminal_state = CERTIFIED` before referencing a Phase 7 certificate as part of a complete, successful audit engagement in any commercialization document or reference audit. This is the authoritative proof that platform integrity certification completed successfully.

If Phase 8 references an audit engagement where `terminal_state` is not `CERTIFIED`, the engagement must be explicitly labeled as having a disclosed integrity limitation, consistent with the Product Constitution's non-negotiable disclosure rule.

**Stable fields for Phase 8 consumption:**

| Field | Type | Description |
| --- | --- | --- |
| `certificate_version` | String | Certificate schema version (e.g., `cert_v1`) |
| `certification_job_id` | String | Job ID of the most recent complete certification event |
| `certificate_id` | String | Canonical certificate identifier |
| `client_id` | String | Scoped client identifier |
| `audit_id` | String | Scoped audit identifier |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `aggregation_version` | String | Phase 4 aggregation version |
| `intelligence_version` | String | Phase 5 intelligence version |
| `report_version` | String | Phase 6 report version |
| `terminal_state` | String | Must be `CERTIFIED` for complete engagement references; bounded set: `{CERTIFIED, CERTIFICATION_FAILED, CERTIFICATION_BLOCKED}` |
| `certification_summary` | String | Fixed deterministic summary string derived from `terminal_state`; bounded set defined in Section 6 |
| `report_id` | String | Reference to the Phase 6 report this certificate covers |
| `s3_certificate_ref` | String | S3 key of the authoritative Phase 7 certificate artifact |
| `s3_report_artifact_ref` | String | S3 key of the Phase 6 report artifact this certificate covers (carried from Phase 7) |
| `aggregate_set_hash` | String | Phase 4 lineage hash carried through the full pipeline (Phase 4 → 5 → 6 → 7); completes the full evidence chain |
| `created_at` | String | UTC ISO-8601 timestamp of first certification |
| `completed_at` | String | UTC ISO-8601 timestamp of the most recent successful certification |

Phase 8 uses `s3_certificate_ref` to locate the S3 artifact for full certificate content, domain results, and disclosed failures. Phase 8 must not construct or guess the S3 key independently.

---

### 3.2 S3 Certificate Artifact (Full Artifact)

Phase 8 may read the full S3 certificate artifact located at the key referenced by `CertificationMetadata.s3_certificate_ref`. The artifact is an immutable JSON document (the serialized `PlatformIntegrityCertificate`) written once per certification event.

**Stable top-level sections:**

#### Certificate Identity

| Field | Type | Description |
| --- | --- | --- |
| `certificate_id` | String | Canonical certificate identifier |
| `certificate_version` | String | `cert_v1` |
| `generated_at` | String | UTC ISO-8601 artifact generation timestamp |
| `generator_version` | String | Platform version string at time of certification |

#### Certification Result

| Field | Type | Description |
| --- | --- | --- |
| `terminal_state` | String | `CERTIFIED`, `CERTIFICATION_FAILED`, or `CERTIFICATION_BLOCKED` |
| `certification_summary` | String | Fixed deterministic summary string (bounded set defined in Section 6) |
| `disclosed_failures` | String[] | Domain identifiers with FAILED or BLOCKED status; empty array if `CERTIFIED` |

#### Report Reference

| Field | Type | Description |
| --- | --- | --- |
| `report_id` | String | Phase 6 report identifier |
| `report_version` | String | `report_v1` |
| `s3_report_artifact_ref` | String | S3 key of the Phase 6 report artifact |
| `intelligence_version` | String | `intel_v1` (carried from Phase 6 artifact) |
| `aggregate_set_hash` | String | Phase 4 lineage hash; completes the full lineage chain |

#### Audit Provenance

| Field | Type | Description |
| --- | --- | --- |
| `client_id` | String | Scoped client identifier |
| `audit_id` | String | Scoped audit identifier |
| `audit_execution_id` | String | Durable execution identity |
| `config_version` | String | Configuration version |
| `aggregation_version` | String | Phase 4 aggregation version |

#### Domain Results (`domain_results[]`)

Phase 8 may consume the full `domain_results` array. Each element contains the following stable sub-sections:

- `domain` — domain identifier from the bounded set (Section 6)
- `status` — `PASSED`, `FAILED`, or `BLOCKED`
- `checks_performed` — count of checks executed
- `checks_passed` — count of checks that passed
- `failure_details` — descriptions of failed checks; empty if `PASSED`
- `evidence_refs` — Phase 6 artifact field paths evaluated in this domain

Phase 8 may reference individual domain results to illustrate what the Audit Platform Integrity methodology verifies. Phase 8 must not re-evaluate, override, or substitute any domain status.

---

## 4. What Phase 8 Must Not Do

Phase 8 is explicitly prohibited from:

1. **Re-computing or re-deriving any certification domain result.** Phase 8 must not re-evaluate runner health, evidence completeness, evidence lineage, or any other certification domain. All domain results in the Phase 7 certificate artifact are authoritative as persisted.

2. **Reading Phase 7 DynamoDB records directly for operational purposes.** Phase 8's use of Phase 7 data is for documentation and commercialization reference only. Phase 8 must use the `rcp retrieve cert-*` CLI commands or reference Phase 7 certificate artifacts by key.

3. **Bypassing the Phase 7 certificate for audit integrity claims.** Any Phase 8 document, reference audit, or commercialization asset that claims an audit's integrity was verified must reference the Phase 7 `certificate_id` and `s3_certificate_ref`. Phase 8 may not assert audit integrity without a `CERTIFIED` Phase 7 certificate.

4. **Mutating Phase 7 certificate artifacts or DynamoDB records.** Phase 8 must not create, update, delete, or extend any Phase 7 certificate artifact, `CertificationMetadata` record, or `CertificationJob` record.

5. **Reading `CertificationJob` records.** These are Phase 7-internal audit log records. They are not part of the Phase 8 consumer contract and must not be used by Phase 8. Phase 8 must derive all needed information from `CertificationMetadata` and the S3 certificate artifact.

6. **Overriding, relabeling, or substituting Phase 7 certification summaries.** Phase 8 must not rename `terminal_state` values, substitute alternative `certification_summary` strings, or re-characterize certification outcomes in any commercialization document.

7. **Presenting a `CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED` audit as a complete successful engagement.** Any Phase 8 reference to an audit with a non-`CERTIFIED` terminal state must explicitly disclose the certification limitation.

---

## 5. DynamoDB Access Patterns

Phase 8 must use only the following DynamoDB access pattern:

**Query 1: Get CertificationMetadata record (prerequisite gate)**

```
GetItem:
  PK = CLIENT#{client_id}
  SK = AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}#AGG#{aggregation_version}#INTEL#{intelligence_version}#RPT#{report_version}#CERT#{cert_version}#META
```

This is a point lookup. Phase 8 must verify `terminal_state = CERTIFIED` on the returned record before referencing the audit as a complete successful engagement.

**Phase 8 must not query:**
- Any Phase 7 sort key prefix other than `#CERT#...#META`
- `CertificationJob` records (SK prefix `#CERTJOB#`)
- Any Phase 6 sort key prefix (`#RPTJOB#`, `#RPT#...#META`)
- Any Phase 5 sort key prefix (`#INTJOB#`, `#INTEL#...#META`)
- Any Phase 4 sort key prefix (`#AGG#`, `#AGGJOB#`, `#SET`, `#MANIFEST#`)

---

## 6. Bounded Value Sets (Stable for Phase 8)

### Terminal State Guarantees

`terminal_state` in Phase 7 artifacts is derived deterministically from domain execution results:

| Terminal State | Condition | Phase 8 Usage |
| --- | --- | --- |
| `CERTIFIED` | All eight certification domains PASSED | Complete successful audit engagement; no disclosure required |
| `CERTIFICATION_FAILED` | One or more domains FAILED | Engagement must disclose all `disclosed_failures` |
| `CERTIFICATION_BLOCKED` | One or more domains BLOCKED due to infrastructure or missing artifact | Engagement must disclose all `disclosed_failures`; operator review required |

`CERTIFICATION_BLOCKED` takes precedence over `CERTIFICATION_FAILED` when both conditions apply.

### Certification Summary Guarantees

`certification_summary` is a fixed Phase 7 presentation string derived deterministically from `terminal_state` within `cert_v1`:

| Terminal State | Certification Summary |
| --- | --- |
| `CERTIFIED` | `Audit platform integrity verified. All certification domains passed.` |
| `CERTIFICATION_FAILED` | `Audit platform integrity verification failed. See disclosed_failures for details.` |
| `CERTIFICATION_BLOCKED` | `Audit platform integrity verification blocked. One or more domains could not be evaluated. Operator review required.` |

Phase 8 must not define, derive, or substitute an alternative summary mapping.

### Domain Identifier Bounded Set

`domain` values in `domain_results[]` are always members of this set:

| Domain Identifier | Certification Domain |
| --- | --- |
| `RUNNER_HEALTH` | Runner health verification |
| `EVIDENCE_COMPLETENESS` | Evidence completeness validation |
| `EVIDENCE_INTEGRITY` | Evidence integrity verification |
| `EVIDENCE_LINEAGE` | Evidence lineage verification |
| `OBSERVATION_COVERAGE` | Observation coverage verification |
| `SCHEDULER_INTEGRITY` | Scheduler integrity verification |
| `METHODOLOGY_COMPLIANCE` | Audit methodology compliance verification |
| `REPORT_INTEGRITY` | Report integrity and internal anomaly detection |

Phase 8 must not define or reference additional domain identifiers outside this set within `cert_v1`.

---

## 7. Contract Versioning and Compatibility Gate

### Version Governance

| Contract version | Certificate version | Report version | Intelligence version | Status |
| --- | --- | --- | --- | --- |
| `phase8_consumer_contract_v1` | `cert_v1` | `report_v1` | `intel_v1` | Current baseline |

This document (`phase_7_phase8_consumer_contract.md`) is the `phase8_consumer_contract_v1` baseline.

### Breaking Change Definition

A breaking change is any modification to a stable field or section that:
- Removes a field listed in Section 3.
- Renames a field listed in Section 3.
- Changes the type of a field listed in Section 3.
- Changes the semantic meaning of a field listed in Section 3.
- Changes a `terminal_state`, `certification_summary`, or domain identifier value within `cert_v1`.
- Removes a section of the S3 certificate artifact listed in Section 3.
- Changes the `CertificationMetadata` prerequisite gate behavior.

New fields added to existing records or artifact sections are non-breaking within `cert_v1`. New Phase 7 retrieval commands are non-breaking.

### Breaking Change Process

Breaking changes require:
1. Contract version increment (e.g., `phase8_consumer_contract_v2`).
2. Certificate version increment (e.g., `cert_v2`), unless the break is limited to DynamoDB metadata fields only.
3. HITL approval of the new contract version document.
4. Explicit Phase 8 migration documentation.
5. Automated regression test validation in `tests/unit/test_phase8_consumer_contract.py`.

No breaking change may be merged without passing the compatibility gate test.

### Compatibility Gate Test

`tests/unit/test_phase8_consumer_contract.py` is the automated compatibility gate. It validates that all stable fields listed in Section 3 are present, correctly typed, and semantically consistent in the current Phase 7 certificate artifact output for a known fixture.

The test must cover:
- All `CertificationMetadata` stable DynamoDB fields from Section 3.1.
- All top-level S3 certificate artifact sections from Section 3.2.
- All `domain_results[]` sub-fields.
- `terminal_state` bounded value set membership.
- `certification_summary` bounded value set membership.
- `disclosed_failures` is empty array when `terminal_state = CERTIFIED`.
- `domain_results[]` contains all eight domain identifiers.

---

## 8. The Complete Audit Deliverable Package

Phase 8 defines the complete customer-facing audit deliverable package as the composition of:

1. The Phase 6 Release Confidence Report (referenced by `report_id` and `s3_report_artifact_ref`)
2. The Phase 7 Platform Integrity Certificate (referenced by `certificate_id` and `s3_certificate_ref`)

Both artifacts are referenced by key. Phase 8 does not embed or duplicate the content of either artifact.

The complete deliverable package is defined in Phase 8 commercialization documentation and represents the full output of one RCP standard audit engagement.

---

## 9. Non-Negotiable Invariants

These invariants cannot be waived by any future phase or product decision without a formal constitutional amendment approved through HITL governance:

1. Phase 8 shall never re-derive, re-evaluate, or reinterpret any Phase 7 certification domain result or terminal state.
2. Phase 8 shall never assert audit platform integrity for an engagement without referencing a Phase 7 `certificate_id`.
3. A `CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED` terminal state requires explicit disclosure in any Phase 8 document that references the corresponding audit engagement.
4. `CertificationMetadata.terminal_state = CERTIFIED` is the only authoritative signal of successful platform integrity certification for Phase 8 consumption purposes.
5. Phase 8 shall never mutate any Phase 7 certificate artifact or `CertificationMetadata` record.
6. Phase 7 owns platform integrity certification. Phase 8 owns the reference audit and commercialization framework.

---

## 10. Traceability

- Phase 7 Technical Design: `docs/architecture/phase_7_audit_platform_integrity_technical_design.md`
- Phase 7 Certificate Schema: defined in `docs/architecture/phase_7_audit_platform_integrity_technical_design.md` Section 8
- Phase 7 Product Spec: `docs/product/phase_7_audit_platform_integrity_product_spec.md`
- Phase 6 → Phase 7 Consumer Contract (format reference): `docs/architecture/phase_6_phase7_consumer_contract.md`
- ADR — Certification Independence: `docs/architecture/adr_phase7_certification_independence.md`
- Naming and Schema Versioning: `docs/architecture/naming_and_schema_versioning.md`
- Product Constitution: `RCP_Product_Strategy.md`
- Compatibility gate test: `tests/unit/test_phase8_consumer_contract.py`
