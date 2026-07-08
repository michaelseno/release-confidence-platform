"""Phase 7 Certificate Schema Compatibility Gate.

CERT-01 through CERT-14 — validates that the PlatformIntegrityCertificate Pydantic
model and cert_v1 constants satisfy all schema invariants required by the Phase 8
consumer contract.

This test is a BLOCKING gate: it must pass on every PR that touches Phase 7 or
Phase 6 artifacts. Failure blocks Phase 7 implementation changes per Section 11 of
the Phase 7 technical design (docs/architecture/phase_7_audit_platform_integrity_technical_design.md).

Source inputs:
  - docs/architecture/phase_7_audit_platform_integrity_technical_design.md Section 8, 11
  - docs/architecture/phase_7_phase8_consumer_contract.md Section 3, 6
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from release_confidence_platform.audit_platform_integrity.constants import (
    CERT_DOMAIN_IDENTIFIERS,
    CERTIFICATION_SUMMARY_MAP,
    CERTIFICATE_VERSION,
    TERMINAL_STATES,
)
from release_confidence_platform.audit_platform_integrity.models import (
    CertificationAuditProvenance,
    CertificationDomainResult,
    CertificationIdentity,
    CertificationReportReference,
    CertificationResult,
    PlatformIntegrityCertificate,
)

# ---------------------------------------------------------------------------
# Fixture factories
# ---------------------------------------------------------------------------

_AGGREGATE_SET_HASH = "deadbeef0123456789abcdef01234567deadbeef0123456789abcdef01234567"


def _make_domain_result(domain: str, status: str = "PASSED") -> CertificationDomainResult:
    checks_passed = 4 if status == "PASSED" else 3
    return CertificationDomainResult(
        domain=domain,
        status=status,
        checks_performed=4,
        checks_passed=checks_passed,
        failure_details=[] if status == "PASSED" else ["check_4 failed: assertion not met"],
        evidence_refs=["executive_summary.total_executions", "endpoints[*].reliability_metrics"],
    )


def _make_certified_certificate() -> PlatformIntegrityCertificate:
    """Return a fully-constructed CERTIFIED PlatformIntegrityCertificate with all 8 domains."""
    return PlatformIntegrityCertificate(
        identity=CertificationIdentity(
            certificate_id="cert_schema_test_fixture_0001",
            certificate_version=CERTIFICATE_VERSION,
            generated_at="2026-07-05T12:00:00.000Z",
            generator_version="0.0.0",
        ),
        result=CertificationResult(
            terminal_state="CERTIFIED",
            certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFIED"],
            disclosed_failures=[],
        ),
        report_reference=CertificationReportReference(
            report_id="report_schema_test_fixture",
            report_version="report_v1",
            s3_report_artifact_ref=(
                "reports/client_abc/audit_xyz/audexec_0001/agg_v1/intel_v1/report_v1/artifact.json"
            ),
            intelligence_version="intel_v1",
            aggregate_set_hash=_AGGREGATE_SET_HASH,
        ),
        audit_provenance=CertificationAuditProvenance(
            client_id="client_abc",
            audit_id="audit_xyz",
            audit_execution_id="audexec_0001",
            config_version="cfg_v1",
            aggregation_version="agg_v1",
            intelligence_version="intel_v1",
            report_version="report_v1",
        ),
        domain_results=[_make_domain_result(d) for d in CERT_DOMAIN_IDENTIFIERS],
        certjob_id="certjob_schema_test_fixture_0001",
    )


# ---------------------------------------------------------------------------
# Module-level fixtures — construct once, shared across all tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def certified_cert() -> PlatformIntegrityCertificate:
    return _make_certified_certificate()


@pytest.fixture(scope="module")
def certified_cert_dict(certified_cert: PlatformIntegrityCertificate) -> dict[str, Any]:
    return certified_cert.to_dict()


# ---------------------------------------------------------------------------
# Mapping: consumer contract Section 3.1 field name → access path in to_dict()
#
# Note: s3_certificate_ref, created_at, and completed_at are populated by the
# Phase 7 engine at DynamoDB write time — they are not fields of
# PlatformIntegrityCertificate and are therefore not checked here.
# Note: consumer contract uses 'certification_job_id'; model field is 'certjob_id'.
# ---------------------------------------------------------------------------

_METADATA_FIELD_PATHS: dict[str, tuple[str, ...]] = {
    "certificate_version":    ("identity", "certificate_version"),
    "certification_job_id":   ("certjob_id",),
    "certificate_id":         ("identity", "certificate_id"),
    "client_id":              ("audit_provenance", "client_id"),
    "audit_id":               ("audit_provenance", "audit_id"),
    "audit_execution_id":     ("audit_provenance", "audit_execution_id"),
    "config_version":         ("audit_provenance", "config_version"),
    "aggregation_version":    ("audit_provenance", "aggregation_version"),
    "intelligence_version":   ("audit_provenance", "intelligence_version"),
    "report_version":         ("audit_provenance", "report_version"),
    "terminal_state":         ("result", "terminal_state"),
    "certification_summary":  ("result", "certification_summary"),
    "report_id":              ("report_reference", "report_id"),
    "s3_report_artifact_ref": ("report_reference", "s3_report_artifact_ref"),
    "aggregate_set_hash":     ("report_reference", "aggregate_set_hash"),
}


# ---------------------------------------------------------------------------
# CERT-01: CertificationMetadata stable DynamoDB fields derivable from model
# ---------------------------------------------------------------------------


def test_cert_01_certification_metadata_stable_fields_derivable_from_model(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CERT-01: All Section 3.1 model-accessible CertificationMetadata fields are
    accessible via to_dict() with the correct nested path.

    s3_certificate_ref, created_at, completed_at are engine-generated at write time
    and are not fields of PlatformIntegrityCertificate; they are not checked here.
    """
    missing: list[str] = []
    for contract_field, path in _METADATA_FIELD_PATHS.items():
        node: Any = certified_cert_dict
        try:
            for key in path:
                node = node[key]
            if node is None:
                missing.append(f"{contract_field} (is None at path {path})")
        except (KeyError, TypeError):
            missing.append(f"{contract_field} (not found at path {path})")
    assert not missing, (
        f"CertificationMetadata stable fields not accessible in certificate: {missing}"
    )


# ---------------------------------------------------------------------------
# CERT-02: Top-level S3 certificate artifact sections present
# ---------------------------------------------------------------------------

_REQUIRED_TOP_LEVEL_SECTIONS = ["identity", "result", "report_reference", "audit_provenance",
                                 "domain_results", "certjob_id"]


def test_cert_02_top_level_certificate_sections_present(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CERT-02: PlatformIntegrityCertificate.to_dict() contains all required top-level sections
    from consumer contract Section 3.2.
    """
    missing = [s for s in _REQUIRED_TOP_LEVEL_SECTIONS if s not in certified_cert_dict]
    assert not missing, f"Certificate to_dict() missing required top-level sections: {missing}"


# ---------------------------------------------------------------------------
# CERT-03: CertificationDomainResult sub-fields complete
# ---------------------------------------------------------------------------

_REQUIRED_DOMAIN_RESULT_FIELDS = [
    "domain", "status", "checks_performed", "checks_passed",
    "failure_details", "evidence_refs",
]


def test_cert_03_domain_result_sub_fields_complete(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CERT-03: Every domain_results[] element contains all required sub-fields from
    consumer contract Section 3.2.
    """
    domain_results = certified_cert_dict.get("domain_results", [])
    assert domain_results, "domain_results must be non-empty"
    for result in domain_results:
        missing = [f for f in _REQUIRED_DOMAIN_RESULT_FIELDS if f not in result]
        assert not missing, (
            f"domain_results entry for {result.get('domain')!r} missing fields: {missing}"
        )


# ---------------------------------------------------------------------------
# CERT-04: TERMINAL_STATES contains all three required values
# ---------------------------------------------------------------------------

_EXPECTED_TERMINAL_STATES = {"CERTIFIED", "CERTIFICATION_FAILED", "CERTIFICATION_BLOCKED"}


def test_cert_04_terminal_states_contains_all_required_values() -> None:
    """CERT-04: TERMINAL_STATES bounded set contains exactly the three required values."""
    assert _EXPECTED_TERMINAL_STATES == set(TERMINAL_STATES), (
        f"TERMINAL_STATES mismatch. "
        f"Expected: {_EXPECTED_TERMINAL_STATES}, got: {set(TERMINAL_STATES)}"
    )


# ---------------------------------------------------------------------------
# CERT-05: CERTIFICATION_SUMMARY_MAP has exactly one entry per terminal state
# ---------------------------------------------------------------------------


def test_cert_05_certification_summary_map_one_entry_per_terminal_state() -> None:
    """CERT-05: CERTIFICATION_SUMMARY_MAP has exactly one entry per terminal state and all
    values are non-empty strings.
    """
    assert set(CERTIFICATION_SUMMARY_MAP.keys()) == set(TERMINAL_STATES), (
        f"CERTIFICATION_SUMMARY_MAP keys {set(CERTIFICATION_SUMMARY_MAP.keys())} "
        f"must match TERMINAL_STATES {set(TERMINAL_STATES)}"
    )
    for state, summary in CERTIFICATION_SUMMARY_MAP.items():
        assert isinstance(summary, str), (
            f"CERTIFICATION_SUMMARY_MAP[{state!r}] must be a string, got {type(summary)}"
        )
        assert summary, (
            f"CERTIFICATION_SUMMARY_MAP[{state!r}] must be non-empty"
        )


# ---------------------------------------------------------------------------
# CERT-06: certification_summary values are the three required strings
# ---------------------------------------------------------------------------

_EXPECTED_CERTIFICATION_SUMMARIES = {
    "CERTIFIED": "INTEGRITY_VERIFIED",
    "CERTIFICATION_FAILED": "INTEGRITY_FAILED",
    "CERTIFICATION_BLOCKED": "INTEGRITY_BLOCKED",
}


def test_cert_06_certification_summary_values_are_correct() -> None:
    """CERT-06: CERTIFICATION_SUMMARY_MAP maps each terminal_state to the required
    certification_summary value as defined in the Phase 7 technical design Section 8.2.
    """
    for state, expected_summary in _EXPECTED_CERTIFICATION_SUMMARIES.items():
        actual = CERTIFICATION_SUMMARY_MAP.get(state)
        assert actual == expected_summary, (
            f"CERTIFICATION_SUMMARY_MAP[{state!r}] = {actual!r}, expected {expected_summary!r}"
        )


# ---------------------------------------------------------------------------
# CERT-07: CERT_DOMAIN_IDENTIFIERS contains all 8 canonical domain identifiers
# ---------------------------------------------------------------------------

_EXPECTED_DOMAIN_IDENTIFIERS = {
    "RUNNER_HEALTH",
    "EVIDENCE_COMPLETENESS",
    "EVIDENCE_INTEGRITY",
    "EVIDENCE_LINEAGE",
    "OBSERVATION_COVERAGE",
    "SCHEDULER_INTEGRITY",
    "METHODOLOGY_COMPLIANCE",
    "REPORT_INTEGRITY",
}


def test_cert_07_cert_domain_identifiers_contains_all_8_domains() -> None:
    """CERT-07: CERT_DOMAIN_IDENTIFIERS contains exactly the 8 canonical domain identifiers
    from the Phase 8 consumer contract Section 6.
    """
    actual = set(CERT_DOMAIN_IDENTIFIERS)
    assert actual == _EXPECTED_DOMAIN_IDENTIFIERS, (
        f"CERT_DOMAIN_IDENTIFIERS mismatch. "
        f"Missing: {_EXPECTED_DOMAIN_IDENTIFIERS - actual}, "
        f"Extra: {actual - _EXPECTED_DOMAIN_IDENTIFIERS}"
    )
    assert len(CERT_DOMAIN_IDENTIFIERS) == 8, (
        f"CERT_DOMAIN_IDENTIFIERS must have exactly 8 entries, got {len(CERT_DOMAIN_IDENTIFIERS)}"
    )


# ---------------------------------------------------------------------------
# CERT-08: CERTIFICATE_VERSION == "cert_v1"
# ---------------------------------------------------------------------------


def test_cert_08_certificate_version_is_cert_v1() -> None:
    """CERT-08: CERTIFICATE_VERSION constant is 'cert_v1'."""
    assert CERTIFICATE_VERSION == "cert_v1", (
        f"CERTIFICATE_VERSION must be 'cert_v1', got {CERTIFICATE_VERSION!r}"
    )


# ---------------------------------------------------------------------------
# CERT-09: Fully-constructed certificate to_dict() has all required top-level keys
# ---------------------------------------------------------------------------


def test_cert_09_to_dict_has_all_required_top_level_keys(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CERT-09: A fully-constructed PlatformIntegrityCertificate with all 8 domain results
    serializes to a dict via to_dict() with all required top-level keys present.
    """
    missing = [s for s in _REQUIRED_TOP_LEVEL_SECTIONS if s not in certified_cert_dict]
    assert not missing, (
        f"to_dict() output missing required keys: {missing}"
    )
    # Verify nested sections are dicts/lists, not None
    assert isinstance(certified_cert_dict["identity"], dict)
    assert isinstance(certified_cert_dict["result"], dict)
    assert isinstance(certified_cert_dict["report_reference"], dict)
    assert isinstance(certified_cert_dict["audit_provenance"], dict)
    assert isinstance(certified_cert_dict["domain_results"], list)
    assert isinstance(certified_cert_dict["certjob_id"], str)


# ---------------------------------------------------------------------------
# CERT-10: disclosed_failures is empty when terminal_state = CERTIFIED
# ---------------------------------------------------------------------------


def test_cert_10_disclosed_failures_empty_when_certified(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CERT-10: disclosed_failures is empty list when terminal_state = CERTIFIED."""
    assert certified_cert_dict["result"]["terminal_state"] == "CERTIFIED"
    assert certified_cert_dict["result"]["disclosed_failures"] == [], (
        "disclosed_failures must be empty list when terminal_state is CERTIFIED"
    )


def test_cert_10b_model_rejects_non_empty_disclosed_failures_when_certified() -> None:
    """CERT-10b: Model validator rejects disclosed_failures with CERTIFIED terminal_state."""
    with pytest.raises(ValidationError):
        CertificationResult(
            terminal_state="CERTIFIED",
            certification_summary="INTEGRITY_VERIFIED",
            disclosed_failures=["RUNNER_HEALTH"],
        )


# ---------------------------------------------------------------------------
# CERT-11: checks_performed and checks_passed must be >= 0
# ---------------------------------------------------------------------------


def test_cert_11_checks_performed_non_negative_validated() -> None:
    """CERT-11a: Model rejects checks_performed < 0."""
    with pytest.raises(ValidationError):
        CertificationDomainResult(
            domain="RUNNER_HEALTH",
            status="PASSED",
            checks_performed=-1,
            checks_passed=0,
            failure_details=[],
            evidence_refs=[],
        )


def test_cert_11b_checks_passed_non_negative_validated() -> None:
    """CERT-11b: Model rejects checks_passed < 0."""
    with pytest.raises(ValidationError):
        CertificationDomainResult(
            domain="RUNNER_HEALTH",
            status="PASSED",
            checks_performed=4,
            checks_passed=-1,
            failure_details=[],
            evidence_refs=[],
        )


def test_cert_11c_checks_passed_le_checks_performed_validated() -> None:
    """CERT-11c: Model rejects checks_passed > checks_performed."""
    with pytest.raises(ValidationError):
        CertificationDomainResult(
            domain="RUNNER_HEALTH",
            status="PASSED",
            checks_performed=3,
            checks_passed=4,
            failure_details=[],
            evidence_refs=[],
        )


# ---------------------------------------------------------------------------
# CERT-12: certificate_version must be cert_v1 (model validation)
# ---------------------------------------------------------------------------


def test_cert_12_model_rejects_non_cert_v1_version() -> None:
    """CERT-12: Model validator rejects certificate_version != 'cert_v1'."""
    with pytest.raises(ValidationError):
        CertificationIdentity(
            certificate_id="cert_test",
            certificate_version="cert_v2",
            generated_at="2026-07-05T12:00:00.000Z",
            generator_version="0.0.0",
        )


def test_cert_12b_certificate_version_in_constructed_cert(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CERT-12b: Constructed certificate identity.certificate_version is 'cert_v1'."""
    assert certified_cert_dict["identity"]["certificate_version"] == "cert_v1"


# ---------------------------------------------------------------------------
# CERT-13: domain_results must contain exactly 8 entries
# ---------------------------------------------------------------------------


def test_cert_13_domain_results_has_exactly_8_entries(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CERT-13: domain_results[] contains exactly 8 entries (one per domain)."""
    domain_results = certified_cert_dict["domain_results"]
    assert len(domain_results) == 8, (
        f"domain_results must have exactly 8 entries, got {len(domain_results)}"
    )


def test_cert_13b_model_rejects_fewer_than_8_domain_results() -> None:
    """CERT-13b: Model rejects domain_results with fewer than 8 entries."""
    with pytest.raises(ValidationError):
        PlatformIntegrityCertificate(
            identity=CertificationIdentity(
                certificate_id="cert_test",
                certificate_version=CERTIFICATE_VERSION,
                generated_at="2026-07-05T12:00:00.000Z",
                generator_version="0.0.0",
            ),
            result=CertificationResult(
                terminal_state="CERTIFIED",
                certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFIED"],
                disclosed_failures=[],
            ),
            report_reference=CertificationReportReference(
                report_id="report_test",
                report_version="report_v1",
                s3_report_artifact_ref="reports/client/audit/artifact.json",
                intelligence_version="intel_v1",
                aggregate_set_hash=_AGGREGATE_SET_HASH,
            ),
            audit_provenance=CertificationAuditProvenance(
                client_id="client_test",
                audit_id="audit_test",
                audit_execution_id="audexec_test",
                config_version="cfg_v1",
                aggregation_version="agg_v1",
                intelligence_version="intel_v1",
                report_version="report_v1",
            ),
            # Only 1 domain result — must be rejected
            domain_results=[_make_domain_result("RUNNER_HEALTH")],
            certjob_id="certjob_test",
        )


# ---------------------------------------------------------------------------
# CERT-14: JSON serialization is stable (byte-identical for identical inputs)
# ---------------------------------------------------------------------------


def test_cert_14_json_serialization_is_byte_identical_for_identical_inputs() -> None:
    """CERT-14: Canonical JSON serialization is byte-identical for two independently constructed
    certificates with identical field values (sort_keys=True determinism guarantee).
    """
    cert_a = _make_certified_certificate()
    cert_b = _make_certified_certificate()
    json_a = json.dumps(cert_a.to_dict(), sort_keys=True, indent=2)
    json_b = json.dumps(cert_b.to_dict(), sort_keys=True, indent=2)
    assert json_a == json_b, (
        "JSON serialization of two certificates with identical inputs must be byte-identical"
    )
    # Verify the serialized output is valid JSON and round-trips correctly
    round_trip = json.loads(json_a)
    assert round_trip["identity"]["certificate_version"] == "cert_v1"
    assert round_trip["result"]["terminal_state"] == "CERTIFIED"
    assert len(round_trip["domain_results"]) == 8
