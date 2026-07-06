# Implementation Plan

## 1. Feature Overview

Phase 7.2 — Certificate Data Model. Implements the foundational data layer for the `audit_platform_integrity` module: `constants.py`, `models.py`, `identity.py`, `__init__.py`, and a complete unit test suite for these modules. No engine, repository, publisher, CLI, or domain executor code is included in this subphase.

## 2. Technical Scope

- Define `cert_v1` constants: `CERTIFICATE_VERSION`, `CERT_ID_PREFIX`, `CERTJOB_ID_PREFIX`, `CERT_DOMAIN_IDENTIFIERS`, `CERTIFICATION_SUMMARY_MAP`, `TERMINAL_STATES`, `DOMAIN_STATUSES`.
- Implement Pydantic models: `CertificationDomainResult`, `CertificationAuditProvenance`, `CertificationReportReference`, `CertificationIdentity`, `CertificationResult`, `PlatformIntegrityCertificate`.
- Implement ID generation: `generate_certificate_id()`, `generate_certjob_id()`.
- Write unit tests for models and constants, with complete acceptance criteria coverage from GitHub Issue #77.

## 3. Source Inputs

1. `docs/architecture/phase_7_audit_platform_integrity_technical_design.md` — Sections 6, 8, 9, 10, 11, 15
2. `docs/product/phase_7_audit_platform_integrity_product_spec.md` — Sections 4.2, 4.3
3. `src/release_confidence_platform/deterministic_reporting/models.py` — Pydantic conventions
4. `src/release_confidence_platform/deterministic_reporting/constants.py` — constants file pattern
5. `src/release_confidence_platform/deterministic_reporting/identity.py` — ID generation pattern
6. `src/release_confidence_platform/reliability_intelligence/identity.py` — comparison pattern
7. `tests/unit/deterministic_reporting/test_models.py` — test style reference

## 4. API Contracts Affected

No API contract changes. This subphase introduces the data model only. No endpoints, CLI commands, or network interfaces are implemented here.

## 5. Data Models / Storage Affected

New Pydantic models defined in `src/release_confidence_platform/audit_platform_integrity/models.py`:

- `CertificationDomainResult` — per-domain verification result (domain, status, checks_performed, checks_passed, failure_details, evidence_refs)
- `CertificationAuditProvenance` — audit identity fields (client_id, audit_id, audit_execution_id, config_version, aggregation_version, intelligence_version, report_version)
- `CertificationReportReference` — Phase 6 report reference (report_id, report_version, s3_report_artifact_ref, intelligence_version, aggregate_set_hash)
- `CertificationIdentity` — certificate identity (certificate_id, certificate_version, generated_at, generator_version)
- `CertificationResult` — certification outcome (terminal_state, certification_summary, disclosed_failures)
- `PlatformIntegrityCertificate` — complete certificate artifact (identity, result, report_reference, audit_provenance, domain_results, certjob_id)

No DynamoDB or S3 code. No migration required.

## 6. Files Expected to Change

New files (all net-new):
- `src/release_confidence_platform/audit_platform_integrity/__init__.py`
- `src/release_confidence_platform/audit_platform_integrity/constants.py`
- `src/release_confidence_platform/audit_platform_integrity/models.py`
- `src/release_confidence_platform/audit_platform_integrity/identity.py`
- `tests/unit/audit_platform_integrity/__init__.py`
- `tests/unit/audit_platform_integrity/test_models.py`
- `tests/unit/audit_platform_integrity/test_constants.py`

One documentation artifact:
- `docs/backend/phase_7_2_certificate_data_model_implementation_plan.md` (this file)
- `docs/backend/phase_7_2_certificate_data_model_implementation_report.md`

## 7. Security / Authorization Considerations

No authentication, authorization, or sensitive data handling in the data model layer. All fields are structural schema definitions. No secrets, tokens, or credentials.

## 8. Dependencies / Constraints

- `pydantic` — already present (used by Phase 6 models); using `BaseModel`, `field_validator`, `model_validator` (Pydantic v2 API)
- `uuid` — stdlib; used in identity.py
- No new dependencies required

## 9. Assumptions

**Assumption A: `CERTIFICATION_SUMMARY_MAP` values — documented conflict.**
The approved technical design (Section 8.2) defines:
- `CERTIFIED` → `INTEGRITY_VERIFIED`
- `CERTIFICATION_FAILED` → `INTEGRITY_FAILED`
- `CERTIFICATION_BLOCKED` → `INTEGRITY_BLOCKED`

The task instruction specifies long descriptive strings (e.g., `"Audit platform integrity verified. All certification domains passed."`). Per input priority rules (approved technical design takes precedence), this implementation uses the short codes from Section 8.2. Tests reference the constants, so both would produce passing tests; the short codes are consistent with the CLI output shown in Section 12.1.

**Assumption B: Nested model structure.**
The task instruction organizes certificate fields into nested sub-models (CertificationIdentity, CertificationResult, CertificationReportReference, CertificationAuditProvenance). The technical design Section 8.1 lists certificate fields as conceptual flat fields. The nested model structure follows the Phase 6 `ReleaseConfidenceReport` pattern (which also uses nested sub-models). This is treated as an implementation modeling choice, not a product behavior change. `to_dict()` returns nested JSON matching the sub-model structure.

**Assumption C: `certjob_id` in `PlatformIntegrityCertificate`.**
The task adds `certjob_id: str` to `PlatformIntegrityCertificate`. The technical design Section 8.1 does not list `certjob_id` in the certificate fields, but `CertificationMetadata` DynamoDB record (Section 9.2) does carry `certjob_id`. Including it in the certificate artifact provides durable cross-reference between the artifact and the job that produced it. This is a minor structural addition consistent with platform patterns.

## 10. Validation Plan

```
python -m pytest tests/unit/audit_platform_integrity/ -v
```

All tests must pass with 0 failures before commit.
