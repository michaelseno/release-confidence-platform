# Implementation Plan

## Phase 7.3 — Certification Domain Executors

---

## 1. Feature Overview

Implement all eight certification domain check functions for Phase 7 Audit Platform
Integrity. Each executor is a pure function that takes Phase 6 report artifact data
and returns a `CertificationDomainResult`. No DynamoDB, S3, engine, repository,
publisher, or CLI code belongs in this subphase.

---

## 2. Technical Scope

- Single module: `src/release_confidence_platform/audit_platform_integrity/domains.py`
- Eight functions: `check_runner_health`, `check_evidence_completeness`,
  `check_evidence_integrity`, `check_evidence_lineage`, `check_observation_coverage`,
  `check_scheduler_integrity`, `check_methodology_compliance`, `check_report_integrity`
- Test file: `tests/unit/audit_platform_integrity/test_domains.py`
- Pure functions only; no I/O, no side effects, no logging

---

## 3. Source Inputs

1. `docs/architecture/phase_7_audit_platform_integrity_technical_design.md` — Section 6
2. `docs/qa/phase_7_audit_platform_integrity_validation_spec.md` — Sections 2–9
3. `src/release_confidence_platform/audit_platform_integrity/models.py`
4. `src/release_confidence_platform/audit_platform_integrity/constants.py`
5. `src/release_confidence_platform/deterministic_reporting/models.py`
6. `tests/unit/deterministic_reporting/test_models.py` (fixture reference)
7. `tests/unit/audit_platform_integrity/test_models.py` (test style reference)

---

## 4. API Contracts Affected

No API contract changes. Domain functions are internal pure functions consumed by
the Phase 7.4+ engine layer.

Function signatures:

```python
def check_runner_health(report: ReleaseConfidenceReport) -> CertificationDomainResult
def check_evidence_completeness(report: ReleaseConfidenceReport) -> CertificationDomainResult
def check_evidence_integrity(report: ReleaseConfidenceReport, report_metadata: dict) -> CertificationDomainResult
def check_evidence_lineage(report: ReleaseConfidenceReport, report_metadata: dict) -> CertificationDomainResult
def check_observation_coverage(report: ReleaseConfidenceReport, report_metadata: dict) -> CertificationDomainResult
def check_scheduler_integrity(report: ReleaseConfidenceReport) -> CertificationDomainResult
def check_methodology_compliance(report: ReleaseConfidenceReport) -> CertificationDomainResult
def check_report_integrity(report: ReleaseConfidenceReport) -> CertificationDomainResult
```

---

## 5. Data Models / Storage Affected

No data model or storage changes. All inputs are deserialized `ReleaseConfidenceReport`
Pydantic instances and a plain `dict` of stable `ReportMetadata` fields.

---

## 6. Files Expected to Change

- `src/release_confidence_platform/audit_platform_integrity/domains.py` (new)
- `tests/unit/audit_platform_integrity/test_domains.py` (new)

---

## 7. Security / Authorization Considerations

Pure functions with no I/O. No authentication or ownership checks required in this
subphase. Input validation is performed by Pydantic at the `ReleaseConfidenceReport`
construction boundary before domain functions are called.

---

## 8. Dependencies / Constraints

- Imports from existing modules only: `audit_platform_integrity.models`,
  `audit_platform_integrity.constants`, `deterministic_reporting.models`,
  `deterministic_reporting.constants`
- No new dependencies
- Python 3.11 required (used for `datetime.fromisoformat` with 'Z' suffix support)

---

## 9. Assumptions

**Assumption 1 (field name mapping):** The validation spec uses `total_executions`,
`total_pass`, `total_fail`, `audit_success_rate` when describing per-endpoint
`reliability_metrics` fields. The actual Pydantic model uses `execution_count`,
`pass_count`, `fail_count`, `success_rate`. Implementations use the actual model
field names.

**Assumption 2 (RH-3 threshold):** `MethodologyDisclosure` has no explicit
numeric error rate threshold field. RH-3 is implemented as a data integrity check:
`fail_count / execution_count` must be in `[0.0, 1.0]`. This is always true for
valid data; test injection via `model_construct` exercises the failure path.

**Assumption 3 (SI-2 variance allowance):** `MethodologyDisclosure` has no explicit
numeric variance field. SI-2 accepts per-endpoint `execution_count` values in
`[floor(mean), ceil(mean)]` where `mean = total_executions / endpoint_count`. This
permits natural ±1 deviation from integer division.

**Assumption 4 (SI-3 anomaly detection):** No anomaly-indicator fields exist in
the `MethodologyDisclosure` model. SI-3 is implemented as: `limitations` must be
present and not None (scheduler anomaly disclosure check). A None `limitations`
indicates the anomaly disclosure mechanism is missing.

**Assumption 5 (BLOCKED conditions with Pydantic):** Domain functions accept models
constructed via `model_construct()` (bypassing Pydantic validation) to support
BLOCKED test scenarios. All required sections are guarded with `getattr(..., None)`
checks before access.

**Assumption 6 (3-decimal-place check):** Float precision check: `abs(value - round(value, 3)) < 1e-9`.
This handles standard float representation without false negatives for well-formed
Phase 6 artifacts.

---

## 10. Validation Plan

```bash
uv run pytest tests/unit/audit_platform_integrity/test_domains.py -v
uv run pytest tests/unit/ -q --tb=no
```
