"""Phase 7 → Phase 8 Consumer Contract Compatibility Gate.

CON-P8-01 through CON-P8-15 — validates that Phase 7 output artifacts satisfy all
stable contract fields that Phase 8 depends on, as defined in
docs/architecture/phase_7_phase8_consumer_contract.md Section 3, 6, and 7.

This test is a BLOCKING gate: it must pass on every PR that touches Phase 7 or
Phase 6 artifacts. Failure blocks any Phase 7 change that would break the Phase 8
consumer contract. A breaking change requires a new contract version, certificate
version, and HITL approval per Section 7 of the consumer contract.

Source inputs:
  - docs/architecture/phase_7_phase8_consumer_contract.md Section 3, 6, 7
  - docs/architecture/phase_7_audit_platform_integrity_technical_design.md Section 8, 9
"""
from __future__ import annotations

import json
from typing import Any

import pytest

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
        failure_details=[] if status == "PASSED" else [f"{domain}: check_4 assertion not met"],
        evidence_refs=["executive_summary.total_executions", "endpoints[*].reliability_metrics"],
    )


def _make_full_domain_results(
    failed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> list[CertificationDomainResult]:
    """Return a list of 8 CertificationDomainResult instances for all canonical domains."""
    failed = set(failed_domains or [])
    blocked = set(blocked_domains or [])
    results = []
    for domain in CERT_DOMAIN_IDENTIFIERS:
        if domain in blocked:
            results.append(_make_domain_result(domain, "BLOCKED"))
        elif domain in failed:
            results.append(_make_domain_result(domain, "FAILED"))
        else:
            results.append(_make_domain_result(domain, "PASSED"))
    return results


def _make_certificate(
    terminal_state: str,
    disclosed_failures: list[str] | None = None,
    failed_domains: list[str] | None = None,
    blocked_domains: list[str] | None = None,
) -> PlatformIntegrityCertificate:
    """Return a PlatformIntegrityCertificate for the given terminal_state."""
    certification_summary = CERTIFICATION_SUMMARY_MAP[terminal_state]
    return PlatformIntegrityCertificate(
        identity=CertificationIdentity(
            certificate_id="cert_contract_test_fixture_0001",
            certificate_version=CERTIFICATE_VERSION,
            generated_at="2026-07-05T12:00:00.000Z",
            generator_version="0.0.0",
        ),
        result=CertificationResult(
            terminal_state=terminal_state,
            certification_summary=certification_summary,
            disclosed_failures=disclosed_failures or [],
        ),
        report_reference=CertificationReportReference(
            report_id="report_contract_test_fixture",
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
        domain_results=_make_full_domain_results(
            failed_domains=failed_domains,
            blocked_domains=blocked_domains,
        ),
        certjob_id="certjob_contract_test_fixture_0001",
    )


# ---------------------------------------------------------------------------
# Module-level fixtures — construct once, shared across all tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def certified_cert_dict() -> dict[str, Any]:
    """CERTIFIED certificate (all domains PASSED)."""
    return _make_certificate("CERTIFIED").to_dict()


@pytest.fixture(scope="module")
def failed_cert_dict() -> dict[str, Any]:
    """CERTIFICATION_FAILED certificate (one domain FAILED, none BLOCKED)."""
    return _make_certificate(
        terminal_state="CERTIFICATION_FAILED",
        disclosed_failures=["RUNNER_HEALTH"],
        failed_domains=["RUNNER_HEALTH"],
    ).to_dict()


@pytest.fixture(scope="module")
def blocked_cert_dict() -> dict[str, Any]:
    """CERTIFICATION_BLOCKED certificate (one domain BLOCKED)."""
    return _make_certificate(
        terminal_state="CERTIFICATION_BLOCKED",
        disclosed_failures=["EVIDENCE_LINEAGE"],
        blocked_domains=["EVIDENCE_LINEAGE"],
    ).to_dict()


# ---------------------------------------------------------------------------
# Mapping: Section 3.1 consumer contract field name → access path in to_dict()
#
# Note: consumer contract uses 'certification_job_id'; model field is 'certjob_id'.
# Note: s3_certificate_ref, created_at, completed_at are engine-generated at
# DynamoDB write time and are not fields of PlatformIntegrityCertificate.
# ---------------------------------------------------------------------------

_SECTION_3_1_FIELD_PATHS: dict[str, tuple[str, ...]] = {
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

# Top-level S3 certificate artifact sections from consumer contract Section 3.2
_SECTION_3_2_TOP_LEVEL_SECTIONS = [
    "identity",
    "result",
    "report_reference",
    "audit_provenance",
    "domain_results",
    "certjob_id",
]

# Sub-fields required in every domain_results[] entry per Section 3.2
_DOMAIN_RESULT_REQUIRED_SUBFIELDS = [
    "domain",
    "status",
    "checks_performed",
    "checks_passed",
    "failure_details",
    "evidence_refs",
]


# ---------------------------------------------------------------------------
# CON-P8-01: All Section 3.1 stable DynamoDB fields accessible from certificate
# ---------------------------------------------------------------------------


def test_con_p8_01_certification_metadata_stable_fields_accessible(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-01: All Section 3.1 CertificationMetadata stable fields that Phase 8 consumes
    are accessible from a constructed Phase 7 certificate artifact.

    s3_certificate_ref, created_at, completed_at are engine-generated at DynamoDB write time
    and are not part of the PlatformIntegrityCertificate model.
    """
    missing: list[str] = []
    for contract_field, path in _SECTION_3_1_FIELD_PATHS.items():
        node: Any = certified_cert_dict
        try:
            for key in path:
                node = node[key]
            if node is None:
                missing.append(f"{contract_field} (is None at path {path})")
        except (KeyError, TypeError):
            missing.append(f"{contract_field} (not found at path {path})")
    assert not missing, (
        f"Section 3.1 stable fields not accessible in Phase 7 certificate: {missing}"
    )


# ---------------------------------------------------------------------------
# CON-P8-02: All top-level S3 certificate artifact sections from Section 3.2 present
# ---------------------------------------------------------------------------


def test_con_p8_02_all_section_3_2_top_level_sections_present(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-02: All top-level S3 certificate artifact sections from consumer contract
    Section 3.2 are present in to_dict() output.
    """
    missing = [s for s in _SECTION_3_2_TOP_LEVEL_SECTIONS if s not in certified_cert_dict]
    assert not missing, (
        f"Section 3.2 top-level sections missing from certificate to_dict(): {missing}"
    )


# ---------------------------------------------------------------------------
# CON-P8-03: All domain_results[] sub-fields present for each domain
# ---------------------------------------------------------------------------


def test_con_p8_03_domain_results_sub_fields_present_for_each_domain(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-03: Every domain_results[] entry contains all required sub-fields from
    consumer contract Section 3.2.
    """
    domain_results = certified_cert_dict.get("domain_results", [])
    assert domain_results, "domain_results must be non-empty"
    for entry in domain_results:
        domain_name = entry.get("domain", "<unknown>")
        missing = [f for f in _DOMAIN_RESULT_REQUIRED_SUBFIELDS if f not in entry]
        assert not missing, (
            f"domain_results entry {domain_name!r} missing sub-fields: {missing}"
        )


# ---------------------------------------------------------------------------
# CON-P8-04: terminal_state bounded value set membership (all 3 valid)
# ---------------------------------------------------------------------------

_EXPECTED_TERMINAL_STATES = {"CERTIFIED", "CERTIFICATION_FAILED", "CERTIFICATION_BLOCKED"}


def test_con_p8_04_terminal_state_bounded_set_all_values_valid() -> None:
    """CON-P8-04: All three terminal_state values from Section 6 are valid — each can be
    used to construct a certificate with the correct certification_summary.
    """
    for state in _EXPECTED_TERMINAL_STATES:
        assert state in TERMINAL_STATES, (
            f"terminal_state {state!r} not in TERMINAL_STATES"
        )
    assert set(TERMINAL_STATES) == _EXPECTED_TERMINAL_STATES, (
        f"TERMINAL_STATES {set(TERMINAL_STATES)} does not match expected {_EXPECTED_TERMINAL_STATES}"
    )


# ---------------------------------------------------------------------------
# CON-P8-05: certification_summary bounded value set (all 3 present and non-empty)
# ---------------------------------------------------------------------------

_EXPECTED_SUMMARIES = {"INTEGRITY_VERIFIED", "INTEGRITY_FAILED", "INTEGRITY_BLOCKED"}


def test_con_p8_05_certification_summary_bounded_set_complete() -> None:
    """CON-P8-05: All three certification_summary values from Section 6 are present in
    CERTIFICATION_SUMMARY_MAP and all values are non-empty strings.
    """
    actual_summaries = set(CERTIFICATION_SUMMARY_MAP.values())
    assert actual_summaries == _EXPECTED_SUMMARIES, (
        f"CERTIFICATION_SUMMARY_MAP values {actual_summaries} do not match "
        f"expected {_EXPECTED_SUMMARIES}"
    )
    for state, summary in CERTIFICATION_SUMMARY_MAP.items():
        assert isinstance(summary, str) and summary, (
            f"CERTIFICATION_SUMMARY_MAP[{state!r}] must be a non-empty string"
        )


# ---------------------------------------------------------------------------
# CON-P8-06: disclosed_failures is empty when terminal_state = CERTIFIED
# ---------------------------------------------------------------------------


def test_con_p8_06_disclosed_failures_empty_when_certified(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-06: disclosed_failures is an empty list when terminal_state = CERTIFIED."""
    assert certified_cert_dict["result"]["terminal_state"] == "CERTIFIED"
    assert certified_cert_dict["result"]["disclosed_failures"] == [], (
        "disclosed_failures must be an empty list when terminal_state is CERTIFIED"
    )


# ---------------------------------------------------------------------------
# CON-P8-07: non-empty disclosed_failures only when terminal_state is FAILED or BLOCKED
# ---------------------------------------------------------------------------


def test_con_p8_07_non_empty_disclosed_failures_only_for_failed_or_blocked(
    failed_cert_dict: dict[str, Any],
    blocked_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-07: Non-empty disclosed_failures is only valid when terminal_state is
    CERTIFICATION_FAILED or CERTIFICATION_BLOCKED.
    """
    failed_state = failed_cert_dict["result"]["terminal_state"]
    failed_failures = failed_cert_dict["result"]["disclosed_failures"]
    assert failed_state == "CERTIFICATION_FAILED", (
        f"Expected CERTIFICATION_FAILED, got {failed_state!r}"
    )
    assert len(failed_failures) > 0, (
        "CERTIFICATION_FAILED certificate must have non-empty disclosed_failures"
    )

    blocked_state = blocked_cert_dict["result"]["terminal_state"]
    blocked_failures = blocked_cert_dict["result"]["disclosed_failures"]
    assert blocked_state == "CERTIFICATION_BLOCKED", (
        f"Expected CERTIFICATION_BLOCKED, got {blocked_state!r}"
    )
    assert len(blocked_failures) > 0, (
        "CERTIFICATION_BLOCKED certificate must have non-empty disclosed_failures"
    )


# ---------------------------------------------------------------------------
# CON-P8-08: Each disclosed_failures member is in CERT_DOMAIN_IDENTIFIERS
# ---------------------------------------------------------------------------


def test_con_p8_08_disclosed_failures_members_in_domain_identifiers(
    failed_cert_dict: dict[str, Any],
    blocked_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-08: Each member of disclosed_failures is a member of CERT_DOMAIN_IDENTIFIERS."""
    for cert_name, cert_dict in [("FAILED", failed_cert_dict), ("BLOCKED", blocked_cert_dict)]:
        failures = cert_dict["result"]["disclosed_failures"]
        for domain_id in failures:
            assert domain_id in CERT_DOMAIN_IDENTIFIERS, (
                f"{cert_name} certificate disclosed_failures contains {domain_id!r} "
                f"which is not in CERT_DOMAIN_IDENTIFIERS"
            )


# ---------------------------------------------------------------------------
# CON-P8-09: domain_results[] contains exactly 8 elements in a complete certificate
# ---------------------------------------------------------------------------


def test_con_p8_09_domain_results_contains_exactly_8_elements(
    certified_cert_dict: dict[str, Any],
    failed_cert_dict: dict[str, Any],
    blocked_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-09: domain_results[] contains exactly 8 elements in every complete certificate,
    regardless of terminal_state.
    """
    for cert_name, cert_dict in [
        ("CERTIFIED", certified_cert_dict),
        ("CERTIFICATION_FAILED", failed_cert_dict),
        ("CERTIFICATION_BLOCKED", blocked_cert_dict),
    ]:
        count = len(cert_dict["domain_results"])
        assert count == 8, (
            f"{cert_name} certificate domain_results has {count} entries, expected 8"
        )


# ---------------------------------------------------------------------------
# CON-P8-10: Each domain identifier in domain_results[] is in CERT_DOMAIN_IDENTIFIERS
# ---------------------------------------------------------------------------


def test_con_p8_10_each_domain_identifier_in_domain_results_is_valid(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-10: Every domain identifier in domain_results[] is a member of
    CERT_DOMAIN_IDENTIFIERS (Section 6 bounded set).
    """
    for entry in certified_cert_dict["domain_results"]:
        domain_id = entry.get("domain")
        assert domain_id in CERT_DOMAIN_IDENTIFIERS, (
            f"domain_results contains domain {domain_id!r} which is not in CERT_DOMAIN_IDENTIFIERS"
        )


# ---------------------------------------------------------------------------
# CON-P8-11: certificate_version == "cert_v1" in a constructed certificate
# ---------------------------------------------------------------------------


def test_con_p8_11_certificate_version_is_cert_v1(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-11: A constructed certificate has certificate_version == 'cert_v1'."""
    assert certified_cert_dict["identity"]["certificate_version"] == "cert_v1", (
        f"certificate_version must be 'cert_v1', got "
        f"{certified_cert_dict['identity']['certificate_version']!r}"
    )


# ---------------------------------------------------------------------------
# CON-P8-12: report_reference.report_version accessible and non-empty
# ---------------------------------------------------------------------------


def test_con_p8_12_report_reference_report_version_accessible_and_non_empty(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-12: report_reference.report_version is accessible in the certificate artifact
    and is a non-empty string (lineage chain completeness).
    """
    report_version = certified_cert_dict.get("report_reference", {}).get("report_version")
    assert isinstance(report_version, str), (
        f"report_reference.report_version must be a string, got {type(report_version)}"
    )
    assert report_version, "report_reference.report_version must be non-empty"


# ---------------------------------------------------------------------------
# CON-P8-13: report_reference.aggregate_set_hash accessible and non-empty
# ---------------------------------------------------------------------------


def test_con_p8_13_report_reference_aggregate_set_hash_accessible_and_non_empty(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-13: report_reference.aggregate_set_hash is accessible in the certificate artifact
    and is a non-empty string (Phase 4 → Phase 7 lineage chain completeness).
    """
    aggregate_set_hash = certified_cert_dict.get("report_reference", {}).get("aggregate_set_hash")
    assert isinstance(aggregate_set_hash, str), (
        f"report_reference.aggregate_set_hash must be a string, got {type(aggregate_set_hash)}"
    )
    assert aggregate_set_hash, "report_reference.aggregate_set_hash must be non-empty"


# ---------------------------------------------------------------------------
# CON-P8-14: Breaking change detection — field removal
# ---------------------------------------------------------------------------


def _validate_certificate_artifact_structure(d: dict[str, Any]) -> None:
    """Compatibility guard: raises AssertionError if any Section 3.2 stable section is absent."""
    missing = [s for s in _SECTION_3_2_TOP_LEVEL_SECTIONS if s not in d]
    if missing:
        raise AssertionError(f"Breaking change: removed stable sections {missing}")

    identity_required = ["certificate_id", "certificate_version", "generated_at",
                         "generator_version"]
    identity = d.get("identity", {})
    id_missing = [f for f in identity_required if f not in identity]
    if id_missing:
        raise AssertionError(f"Breaking change: identity section missing fields {id_missing}")

    result_required = ["terminal_state", "certification_summary", "disclosed_failures"]
    result = d.get("result", {})
    result_missing = [f for f in result_required if f not in result]
    if result_missing:
        raise AssertionError(f"Breaking change: result section missing fields {result_missing}")

    ref_required = ["report_id", "report_version", "s3_report_artifact_ref",
                    "intelligence_version", "aggregate_set_hash"]
    report_ref = d.get("report_reference", {})
    ref_missing = [f for f in ref_required if f not in report_ref]
    if ref_missing:
        raise AssertionError(
            f"Breaking change: report_reference section missing fields {ref_missing}"
        )

    provenance_required = ["client_id", "audit_id", "audit_execution_id",
                           "config_version", "aggregation_version"]
    provenance = d.get("audit_provenance", {})
    prov_missing = [f for f in provenance_required if f not in provenance]
    if prov_missing:
        raise AssertionError(
            f"Breaking change: audit_provenance section missing fields {prov_missing}"
        )


def test_con_p8_14_breaking_change_detection_field_removal(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-14: The compatibility guard detects removal of a stable Section 3.2 section
    or field.
    """
    # Baseline: current certificate passes guard
    _validate_certificate_artifact_structure(certified_cert_dict)

    # Simulate breaking change: remove the 'result' top-level section
    mutated = {k: v for k, v in certified_cert_dict.items() if k != "result"}
    with pytest.raises(AssertionError, match="Breaking change"):
        _validate_certificate_artifact_structure(mutated)

    # Simulate breaking change: remove a field from report_reference
    mutated_ref = {k: v for k, v in certified_cert_dict["report_reference"].items()
                   if k != "aggregate_set_hash"}
    mutated_cert = {**certified_cert_dict, "report_reference": mutated_ref}
    with pytest.raises(AssertionError, match="Breaking change"):
        _validate_certificate_artifact_structure(mutated_cert)


# ---------------------------------------------------------------------------
# CON-P8-15: Non-breaking addition allowed
# ---------------------------------------------------------------------------


def test_con_p8_15_non_breaking_addition_allowed(
    certified_cert_dict: dict[str, Any],
) -> None:
    """CON-P8-15: Adding a new top-level field to the certificate artifact does not trigger
    the compatibility guard (non-breaking per Section 7).
    """
    extended = {**certified_cert_dict, "future_v2_field": "new_value_not_in_contract_v1"}
    _validate_certificate_artifact_structure(extended)  # Must NOT raise
