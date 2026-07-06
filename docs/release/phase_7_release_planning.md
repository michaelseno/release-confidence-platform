# Phase 7 — Audit Platform Integrity: Release Planning

**Phase:** 7 — Audit Platform Integrity
**Status:** PLANNING — implementation has not begun
**Date:** 2026-07-05
**Prepared by:** Platform Engineering

---

## 1. Planning Summary

Phase 7 is the Audit Platform Integrity layer and the final phase of the Release Confidence Platform technical MVP (Phases 0–7).

Phase 6 is formally closed (2026-07-04). All Phase 6 artifacts, consumer contracts, and DynamoDB/S3 schemas are locked and serve as the stable, immutable inputs for Phase 7.

Phase 7 planning artifacts produced during this session:

| Artifact | Path | Status |
| --- | --- | --- |
| Product Specification | `docs/product/phase_7_audit_platform_integrity_product_spec.md` | COMPLETE |
| Technical Design | `docs/architecture/phase_7_audit_platform_integrity_technical_design.md` | COMPLETE |
| Architecture Decision Record | `docs/architecture/adr_phase7_certification_independence.md` | COMPLETE |
| Validation Specification | `docs/qa/phase_7_audit_platform_integrity_validation_spec.md` | COMPLETE |
| Test Plan | `docs/qa/phase_7_audit_platform_integrity_test_plan.md` | COMPLETE |
| Release Planning | `docs/release/phase_7_release_planning.md` | COMPLETE (this document) |

No implementation work has begun. No code has been written or modified.

---

## 2. Phase 7 Objectives

From the Product Constitution (`RCP_Product_Strategy.md`):

> Validate the integrity of the audit process itself. Certify the trustworthiness of the audit platform before a report is issued.

Phase 7 capabilities:
- Runner health verification
- Evidence completeness validation
- Observation coverage verification
- Internal anomaly detection
- Scheduler integrity verification
- Audit methodology compliance
- Evidence certification

**Non-Negotiable Rule from Product Constitution:**

> No Release Confidence Report shall be issued unless Audit Platform Integrity verification has successfully completed or all material limitations have been explicitly disclosed.

---

## 3. Locked Constraints

These constraints are unconditional and apply to every subphase:

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
- No CI/CD integrations (GitHub Actions, Jenkins, Azure DevOps, etc.) — those belong to later phases.

---

## 4. Phase 7 Success Criteria

### From Product Constitution (verbatim)

1. Audit platform integrity is verified.
2. Evidence quality is certified.
3. Report integrity is defensible.

### Planning-Level Additions

4. The Platform Integrity Certificate (`cert_v1`) is produced deterministically: identical inputs always produce an identical certification result.
5. All eight certification domains execute independently and produce domain results that are recorded in the certificate.
6. The Phase 7 `certify audit` CLI command triggers certification and reports terminal state and all domain results to the operator.
7. The Phase 7 retrieval CLI commands expose all certification artifacts read-only without requiring direct S3 or DynamoDB access.
8. A `CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED` terminal state enumerates all `disclosed_failures` explicitly by domain identifier.
9. Phase 7 never mutates any Phase 6 artifact, `ReportMetadata` record, or `ReportJob` record.
10. Phase 7 never reads any Phase 5, Phase 4, or earlier artifact directly.
11. The Phase 7 non-mutation invariant is enforced structurally (runtime SK assertion guard) and covered by a dedicated unit test suite.
12. A Phase 8 consumer contract is authored and locked before Phase 7 is declared complete.

---

## 5. Phase 7 Subphase Plan

Phase 7 follows the same subphase model established by Phases 4–6. Each subphase has a dedicated GitHub Issue and PR.

| Subphase | Description | Key Deliverables |
| --- | --- | --- |
| 7.1 | Documentation | Product spec, technical design, ADR, validation spec, test plan, Phase 8 consumer contract |
| 7.2 | Certification Data Model | `CertificationJob`, `CertificationMetadata` DynamoDB records; `PlatformIntegrityCertificate` schema; S3 key structure; `cert_v1` constants |
| 7.3 | Domain Executors | All eight certification domain implementations: RUNNER_HEALTH, EVIDENCE_COMPLETENESS, EVIDENCE_INTEGRITY, EVIDENCE_LINEAGE, OBSERVATION_COVERAGE, SCHEDULER_INTEGRITY, METHODOLOGY_COMPLIANCE, REPORT_INTEGRITY |
| 7.4 | Certification Engine | `CertificationEngine` orchestrator: prerequisite gate → idempotency → domain execution → terminal state determination → certificate persistence |
| 7.5 | Repository and Publisher | `CertificationRepository` (DynamoDB read/write), `CertificationPublisher` (S3 write); non-mutation enforcement; structured logging |
| 7.6 | Operator CLI | `rcp certify audit` execution command; `rcp retrieve cert-*` retrieval commands (cert-status, cert-summary, cert-domains, cert-json) |
| 7.7 | Hardening | Cross-phase quality assessment; resolution of any blocking findings; non-mutation invariant structural enforcement; consumer contract gate test (`test_phase7_cert_schema.py`) |
| 7.8 | Validation Campaign | Live operational validation against Phase 6 reports from Phase 6.8 campaigns; minimum two independent certification campaigns against known-good and known-failure-injected fixtures |

---

## 6. Exit Criteria

Phase 7 is complete when all of the following conditions are met:

### Documentation (7.1)

- [ ] Product Specification approved (HITL)
- [ ] Technical Design approved (HITL)
- [ ] ADR (`adr_phase7_certification_independence.md`) approved (HITL)
- [ ] Validation Specification approved (HITL)
- [ ] Test Plan approved (HITL)
- [ ] Phase 8 consumer contract authored and HITL-approved

### Implementation (7.2–7.6)

- [ ] All eight certification domains implemented and independently unit-tested
- [ ] Certification Engine passes all unit tests including idempotency, prerequisite gate, and terminal state determination
- [ ] Non-mutation invariant enforced by runtime SK assertion guard (`_assert_phase7_sk()` or equivalent)
- [ ] `certify audit` CLI command triggers full certification pipeline
- [ ] All `retrieve cert-*` CLI commands return correct output without modifying any artifact
- [ ] `cert_v1` schema constants defined in `constants.py` with no inline magic values

### Hardening (7.7)

- [ ] Cross-phase quality assessment conducted (Architecture, Security, Quality reviewers)
- [ ] All CRITICAL and HIGH findings resolved before Phase 7.8
- [ ] Non-mutation invariant covered by dedicated unit test suite (analogous to Phase 5 `test_engine_no_phase4_mutation.py`)
- [ ] Phase 7 consumer contract compatibility gate test (`tests/unit/test_phase7_cert_schema.py`) passing
- [ ] Phase 6 non-mutation invariant test passing (Phase 7 must not mutate Phase 6 artifacts)

### Validation Campaign (7.8)

- [ ] Minimum two independent live validation campaigns executed
- [ ] Campaign 01: at least one known-good Phase 6 report → `CERTIFIED` terminal state verified
- [ ] Campaign 02: at least one Phase 6 report with injected failure condition → `CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED` verified
- [ ] All eight domain identifiers verified in certificate `domain_results[]`
- [ ] `disclosed_failures` verified as empty on `CERTIFIED` output
- [ ] `disclosed_failures` verified as non-empty on `CERTIFICATION_FAILED` / `CERTIFICATION_BLOCKED` output
- [ ] Idempotency verified: re-certifying a `CERTIFIED` audit without `--force` returns existing certificate
- [ ] Phase 6 artifact non-mutation verified across all campaigns
- [ ] Unit test suite: all tests pass at campaign time

### QA Gate

- [ ] `[QA SIGN-OFF APPROVED]` issued by QA agent

### HITL Gate

- [ ] Release-readiness summary presented to human reviewer
- [ ] `HITL validation successful` received before PR creation

---

## 7. Risk Assessment

### Risk R1: Domain Threshold Definition Complexity

**Category:** Architecture
**Severity:** Medium
**Description:** Several certification domains (RUNNER_HEALTH, OBSERVATION_COVERAGE, SCHEDULER_INTEGRITY) require numeric thresholds (e.g., minimum observation count, maximum allowed execution variance) that must be derived from the audit configuration. The current Phase 6 consumer contract exposes `methodology_disclosure` fields that describe methodology parameters, but the exact threshold values available for Phase 7 cross-checking must be carefully validated against what the `methodology_disclosure` section actually contains.

**Mitigation:** Technical Design (Section 6) must enumerate the exact `methodology_disclosure` field paths and values that Phase 7 will use for each numeric check before 7.3 implementation begins. Any gap between what Phase 7 needs and what `methodology_disclosure` provides must be identified in 7.1 and either resolved via a Phase 6 non-breaking contract amendment or addressed through a Phase 7 design constraint.

**Owner:** Architect. Flag during 7.1 review.

---

### Risk R2: `CERTIFICATION_BLOCKED` Classification Ambiguity

**Category:** Design
**Severity:** Medium
**Description:** The distinction between `CERTIFICATION_FAILED` (check logic ran but found a failure) and `CERTIFICATION_BLOCKED` (check could not run due to infrastructure failure or missing required artifacts) must be precise. Incorrect classification — especially classifying a logic failure as BLOCKED — would weaken the certification's value.

**Mitigation:** Technical Design Section 13 (terminal state determination) defines the precedence rule (`CERTIFICATION_BLOCKED` > `CERTIFICATION_FAILED`). Domain executor unit tests must include explicit scenarios for each terminal state path. Cross-phase quality assessment should review the classification boundary.

**Owner:** dev-backend. Flag during 7.3/7.4 implementation.

---

### Risk R3: `methodology_disclosure` Field Availability

**Category:** Consumer Contract
**Severity:** Medium
**Description:** Phase 7 domain checks (particularly SCHEDULER_INTEGRITY and METHODOLOGY_COMPLIANCE) depend on fields within `methodology_disclosure` in the Phase 6 S3 artifact. If any required field is absent or inconsistently structured across Phase 6.8 campaign artifacts, Phase 7 domain checks may produce false `CERTIFICATION_BLOCKED` results on valid reports.

**Mitigation:** During 7.1, validate the `methodology_disclosure` structure in the three Phase 6.8 campaign artifacts (`report_bf0df6...`, `report_505e9c...`, `report_8aab5b...`) against Phase 7 domain check requirements. If gaps exist, document them as known Phase 7 constraints or propose non-breaking Phase 6 additions before implementation begins.

**Owner:** QA. Flag during 7.1 validation spec review.

---

### Risk R4: Non-Mutation Enforcement Completeness

**Category:** Architecture Integrity
**Severity:** High
**Description:** The non-mutation invariant is the most critical architectural constraint in Phase 7. Any accidental write to a Phase 6 DynamoDB record or S3 artifact would violate the platform's evidence integrity guarantees and could permanently corrupt the trustworthiness of a completed report.

**Mitigation:** Runtime SK assertion guard (analogous to Phase 5's `_assert_phase5_sk()`) must be implemented in 7.5 (`CertificationRepository`) before any DynamoDB write path goes live. Dedicated unit test suite covering all DynamoDB write paths (asserting they target only `#CERTJOB#` and `#CERT#` SK namespaces) must be authored in 7.5 and treated as a blocking gate for 7.7 Hardening.

**Owner:** dev-backend. Non-negotiable architectural gate.

---

### Risk R5: Fixture Quality for Failure Scenarios

**Category:** Testing
**Severity:** Medium
**Description:** Phase 7 unit tests depend on Phase 6 report artifact fixtures that accurately represent failure scenarios (broken lineage, missing fields, inconsistent field values). Poorly constructed fixtures may produce false-positive test passes.

**Mitigation:** The QA Test Plan (7.1) specifies a fixture construction strategy. During 7.3 implementation, fixture construction should begin with a known-good Phase 6.8 campaign artifact and apply targeted mutations for each failure scenario rather than constructing failure fixtures from scratch. This reduces the risk of structural gaps in fixtures.

**Owner:** QA. Flag during 7.3/7.4 unit test authoring.

---

### Risk R6: Live Campaign Coverage for CERTIFICATION_FAILED Path

**Category:** Validation
**Severity:** Medium
**Description:** Unlike Phase 6.8, which validated against three known-good audit data sets, Phase 7.8 must demonstrate both `CERTIFIED` (happy path) and `CERTIFICATION_FAILED` / `CERTIFICATION_BLOCKED` (failure path) outcomes in live campaigns. Producing a clean `CERTIFICATION_FAILED` outcome requires either a genuinely failed audit (unavailable) or controlled failure injection into a known artifact.

**Mitigation:** Phase 7.8 validation plan must specify a controlled failure injection strategy — for example, temporarily modifying a campaign artifact's `aggregate_set_hash` field in a test copy to produce a broken lineage scenario. The original artifact must not be modified. Failure injection must be scoped to a test copy only and must be documented as such in the campaign report.

**Owner:** QA. Define strategy in 7.1 test plan.

---

## 8. Release Readiness Checklist

The following checklist governs the Phase 7.7 Hardening review gate. All items must be `[x]` before the Phase 7 release-readiness summary is presented for HITL approval.

### Code Quality

- [ ] All Phase 7 modules follow existing code style and folder ownership conventions (`docs/architecture/folder_ownership.md`)
- [ ] No inline magic values — all domain thresholds and bounded value sets defined in `constants.py`
- [ ] All DynamoDB write paths protected by runtime SK assertion guard
- [ ] No direct reads of Phase 5 (`#INTJOB#`, `#INTEL#`) or Phase 4 (`#AGG#`, `#AGGJOB#`, `#SET`, `#MANIFEST#`) SK namespaces
- [ ] No writes to Phase 6 (`#RPTJOB#`, `#RPT#`) SK namespaces
- [ ] `certify audit` CLI enforces all required argument validation before any DynamoDB or S3 access

### Test Coverage

- [ ] All eight certification domains have independent unit tests covering PASSED, FAILED, and BLOCKED paths
- [ ] `CertificationEngine` idempotency unit tests cover all three prior terminal state cases (`CERTIFIED`, `CERTIFICATION_FAILED`, `CERTIFICATION_BLOCKED`)
- [ ] Prerequisite gate unit tests cover absent `ReportMetadata`, `status != COMPLETE`, and `status = COMPLETE` paths
- [ ] Non-mutation structural test suite (`test_phase7_no_phase6_mutation.py`) passes
- [ ] Phase 7 consumer contract compatibility gate test (`test_phase7_cert_schema.py`) passes
- [ ] Full unit suite passes (`pytest tests/unit/`) with zero failures

### Architectural Compliance

- [ ] Certificate artifact does not embed Phase 6 report content — references `s3_report_artifact_ref` key only
- [ ] Certificate `domain_results[]` contains all eight domain identifiers
- [ ] `terminal_state` determination is deterministic for all domain result combinations
- [ ] `CERTIFICATION_BLOCKED` takes precedence over `CERTIFICATION_FAILED` when both conditions apply
- [ ] Certificate serialization uses canonical field ordering (`sort_keys=True`) and 3-decimal-place precision

### Consumer Contract

- [ ] Phase 8 consumer contract authored (`docs/architecture/phase_7_phase8_consumer_contract.md`)
- [ ] Phase 8 consumer contract HITL-approved before Phase 7 closure
- [ ] Compatibility gate test (`test_phase7_cert_schema.py`) validates all stable certificate fields

### Validation Campaign

- [ ] Phase 7.8 Campaign 01: `CERTIFIED` terminal state on known-good Phase 6.8 report — PASS
- [ ] Phase 7.8 Campaign 02: `CERTIFICATION_FAILED` or `CERTIFICATION_BLOCKED` on controlled failure injection — PASS
- [ ] No Phase 6 artifact mutation detected across all campaigns
- [ ] All eight domain identifiers present in campaign certificate `domain_results[]`
- [ ] Idempotency verified: re-run of `CERTIFIED` audit without `--force` returns existing certificate

### QA and HITL

- [ ] `[QA SIGN-OFF APPROVED]` issued
- [ ] Release-readiness summary presented to human reviewer
- [ ] `HITL validation successful` received

---

## 9. Phase 7 GitHub Issues

The following GitHub Issues should be opened when implementation is authorized to begin:

| Subphase | Proposed Issue Title |
| --- | --- |
| 7.1 | Phase 7 — Documentation: Product Spec, Technical Design, ADR, Validation Spec, Test Plan, Phase 8 Consumer Contract |
| 7.2 | Phase 7.2 — Certification Data Model: DynamoDB Schema, S3 Key Structure, cert_v1 Constants |
| 7.3 | Phase 7.3 — Certification Domain Executors: All Eight Domains |
| 7.4 | Phase 7.4 — Certification Engine: Orchestration Pipeline |
| 7.5 | Phase 7.5 — Certification Repository and Publisher: DynamoDB/S3 Persistence, Non-Mutation Enforcement |
| 7.6 | Phase 7.6 — Operator CLI: certify audit, retrieve cert-* Commands |
| 7.7 | Phase 7.7 — Hardening: Cross-Phase Quality Assessment, Consumer Contract Gate |
| 7.8 | Phase 7.8 — Validation Campaign: Live Certification Campaigns |

---

## 10. Phase 8 Readiness Gate

Phase 7 gates Phase 8 (Reference Audit & Commercialization Framework). Phase 8 may not begin until:

1. Phase 7.8 validation campaign is complete and QA-approved.
2. The Phase 7 → Phase 8 consumer contract is authored and HITL-approved.
3. `HITL validation successful` is received for Phase 7 closure.

The Platform Integrity Certificate (`cert_v1`) schema and the `phase7_phase8_consumer_contract_v1` baseline become Phase 8's locked inputs.

---

## 11. MVP Completion Statement

Upon successful completion of Phase 7, the Release Confidence Platform technical MVP is complete.

The complete technical pipeline is:

```
Phase 1/2 (Raw Evidence Capture)
    → Phase 3 (Audit Lifecycle & Scheduling)
        → Phase 4 (Deterministic Aggregation)
            → Phase 5 (Reliability Intelligence)
                → Phase 6 (Deterministic Reporting)
                    → Phase 7 (Audit Platform Integrity)
```

Every Release Confidence Report issued after Phase 7 will be accompanied by a Platform Integrity Certificate — a deterministic, evidence-backed attestation that the audit process that produced the report was itself verified.

This completes RCP's foundational trust model.

---

*Phase 7 Release Planning prepared 2026-07-05. Implementation begins after HITL approval of planning artifacts.*
