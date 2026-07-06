"""Unit tests for Phase 7 cert_v1 Pydantic models (Phase 7.2).

Covers acceptance criteria from GitHub Issue #77 and the QA test plan:
  MOD-01  CertificationDomainResult valid construction
  MOD-02  CertificationDomainResult rejects unknown domain value
  MOD-03  CertificationDomainResult rejects unknown status value
  MOD-04  CertificationDomainResult rejects checks_passed > checks_performed
  MOD-05  CertificationDomainResult rejects negative checks_performed
  MOD-06  CertificationResult valid construction for all three terminal states
  MOD-07  CertificationResult rejects unknown terminal_state
  MOD-08  CertificationResult rejects certification_summary not matching CERTIFICATION_SUMMARY_MAP
  MOD-09  CertificationResult rejects non-empty disclosed_failures when CERTIFIED
  MOD-10  CertificationResult accepts empty disclosed_failures when CERTIFICATION_FAILED
  MOD-11  CertificationIdentity rejects certificate_version != cert_v1
  MOD-12  PlatformIntegrityCertificate valid full construction with all 8 domain results
  MOD-13  PlatformIntegrityCertificate rejects fewer than 8 domain results
  MOD-14  PlatformIntegrityCertificate rejects duplicate domain identifiers
  MOD-15  PlatformIntegrityCertificate rejects missing domain identifier
  MOD-16  PlatformIntegrityCertificate.to_dict() returns a plain dict
  MOD-17  generate_certificate_id() returns string starting with cert_
  MOD-18  generate_certjob_id() returns string starting with certjob_
  MOD-19  generate_certificate_id() returns unique values on repeated calls
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from release_confidence_platform.audit_platform_integrity.constants import (
    CERT_DOMAIN_IDENTIFIERS,
    CERTIFICATION_SUMMARY_MAP,
    CERTIFICATE_VERSION,
)
from release_confidence_platform.audit_platform_integrity.identity import (
    generate_certificate_id,
    generate_certjob_id,
)
from release_confidence_platform.audit_platform_integrity.models import (
    CertificationDomainResult,
    CertificationIdentity,
    CertificationResult,
    PlatformIntegrityCertificate,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _valid_domain_result(domain: str = "RUNNER_HEALTH") -> dict[str, Any]:
    """Return a minimal valid domain result dict."""
    return {
        "domain": domain,
        "status": "PASSED",
        "checks_performed": 4,
        "checks_passed": 4,
        "failure_details": [],
        "evidence_refs": ["executive_summary.total_executions"],
    }


def _all_domain_results() -> list[dict[str, Any]]:
    """Return a list of 8 valid domain result dicts — one per domain identifier."""
    return [
        _valid_domain_result(domain=d)
        for d in CERT_DOMAIN_IDENTIFIERS
    ]


def _valid_certificate_data() -> dict[str, Any]:
    """Return a complete valid PlatformIntegrityCertificate dict."""
    return {
        "identity": {
            "certificate_id": generate_certificate_id(),
            "certificate_version": CERTIFICATE_VERSION,
            "generated_at": "2026-07-05T12:00:00.000Z",
            "generator_version": "0.0.0",
        },
        "result": {
            "terminal_state": "CERTIFIED",
            "certification_summary": CERTIFICATION_SUMMARY_MAP["CERTIFIED"],
            "disclosed_failures": [],
        },
        "report_reference": {
            "report_id": "report_abc1234567890abcdef1234567890ab",
            "report_version": "report_v1",
            "s3_report_artifact_ref": "reports/client_x/audit_y/audexec_z/agg_v1/intel_v1/report_v1/rptjob_abc/artifact.json",
            "intelligence_version": "intel_v1",
            "aggregate_set_hash": "deadbeef" * 8,
        },
        "audit_provenance": {
            "client_id": "client_test",
            "audit_id": "audit_test",
            "audit_execution_id": "audexec_test",
            "config_version": "v1",
            "aggregation_version": "agg_v1",
            "intelligence_version": "intel_v1",
            "report_version": "report_v1",
        },
        "domain_results": _all_domain_results(),
        "certjob_id": generate_certjob_id(),
    }


# ---------------------------------------------------------------------------
# MOD-01: CertificationDomainResult valid construction
# ---------------------------------------------------------------------------


def test_mod_01_domain_result_valid_construction() -> None:
    """MOD-01: A valid domain result dict constructs without error."""
    data = _valid_domain_result()
    result = CertificationDomainResult(**data)

    assert result.domain == "RUNNER_HEALTH"
    assert result.status == "PASSED"
    assert result.checks_performed == 4
    assert result.checks_passed == 4
    assert result.failure_details == []
    assert result.evidence_refs == ["executive_summary.total_executions"]


def test_mod_01b_domain_result_all_domains_accepted() -> None:
    """MOD-01b: All 8 domain identifiers are accepted as valid domain values."""
    for domain in CERT_DOMAIN_IDENTIFIERS:
        data = _valid_domain_result(domain=domain)
        result = CertificationDomainResult(**data)
        assert result.domain == domain


def test_mod_01c_domain_result_failed_status_with_details() -> None:
    """MOD-01c: A FAILED domain result with failure_details constructs without error."""
    data = {
        "domain": "REPORT_INTEGRITY",
        "status": "FAILED",
        "checks_performed": 5,
        "checks_passed": 4,
        "failure_details": ["composite_score_value out of [0.0, 1.0]"],
        "evidence_refs": ["executive_summary.composite_score_value"],
    }
    result = CertificationDomainResult(**data)
    assert result.status == "FAILED"
    assert len(result.failure_details) == 1


def test_mod_01d_domain_result_blocked_status_accepted() -> None:
    """MOD-01d: BLOCKED status is accepted as a valid domain status."""
    data = _valid_domain_result()
    data["status"] = "BLOCKED"
    data["failure_details"] = ["endpoints[] is absent or non-iterable"]
    result = CertificationDomainResult(**data)
    assert result.status == "BLOCKED"


# ---------------------------------------------------------------------------
# MOD-02: CertificationDomainResult rejects unknown domain value
# ---------------------------------------------------------------------------


def test_mod_02_domain_result_rejects_unknown_domain() -> None:
    """MOD-02: An unrecognised domain identifier raises ValidationError."""
    data = _valid_domain_result()
    data["domain"] = "UNKNOWN_DOMAIN"
    with pytest.raises(ValidationError):
        CertificationDomainResult(**data)


def test_mod_02b_domain_result_rejects_empty_domain() -> None:
    """MOD-02b: An empty string domain raises ValidationError."""
    data = _valid_domain_result()
    data["domain"] = ""
    with pytest.raises(ValidationError):
        CertificationDomainResult(**data)


def test_mod_02c_domain_result_rejects_lowercase_domain() -> None:
    """MOD-02c: A lowercase domain identifier (not in bounded set) raises ValidationError."""
    data = _valid_domain_result()
    data["domain"] = "runner_health"
    with pytest.raises(ValidationError):
        CertificationDomainResult(**data)


# ---------------------------------------------------------------------------
# MOD-03: CertificationDomainResult rejects unknown status value
# ---------------------------------------------------------------------------


def test_mod_03_domain_result_rejects_unknown_status() -> None:
    """MOD-03: An unrecognised status value raises ValidationError."""
    data = _valid_domain_result()
    data["status"] = "UNKNOWN_STATUS"
    with pytest.raises(ValidationError):
        CertificationDomainResult(**data)


def test_mod_03b_domain_result_rejects_lowercase_status() -> None:
    """MOD-03b: Lowercase status string raises ValidationError."""
    data = _valid_domain_result()
    data["status"] = "passed"
    with pytest.raises(ValidationError):
        CertificationDomainResult(**data)


def test_mod_03c_all_valid_statuses_accepted() -> None:
    """MOD-03c: PASSED, FAILED, and BLOCKED are all accepted as valid status values."""
    for status in ("PASSED", "FAILED", "BLOCKED"):
        data = _valid_domain_result()
        data["status"] = status
        result = CertificationDomainResult(**data)
        assert result.status == status


# ---------------------------------------------------------------------------
# MOD-04: CertificationDomainResult rejects checks_passed > checks_performed
# ---------------------------------------------------------------------------


def test_mod_04_domain_result_rejects_checks_passed_exceeds_performed() -> None:
    """MOD-04: checks_passed > checks_performed raises ValidationError."""
    data = _valid_domain_result()
    data["checks_performed"] = 3
    data["checks_passed"] = 4
    with pytest.raises(ValidationError):
        CertificationDomainResult(**data)


def test_mod_04b_domain_result_checks_passed_equal_to_performed_accepted() -> None:
    """MOD-04b: checks_passed == checks_performed is valid."""
    data = _valid_domain_result()
    data["checks_performed"] = 5
    data["checks_passed"] = 5
    result = CertificationDomainResult(**data)
    assert result.checks_passed == result.checks_performed


def test_mod_04c_domain_result_checks_passed_zero_accepted() -> None:
    """MOD-04c: checks_passed = 0 with checks_performed > 0 is valid (all checks failed)."""
    data = _valid_domain_result()
    data["checks_performed"] = 4
    data["checks_passed"] = 0
    result = CertificationDomainResult(**data)
    assert result.checks_passed == 0


# ---------------------------------------------------------------------------
# MOD-05: CertificationDomainResult rejects negative checks_performed
# ---------------------------------------------------------------------------


def test_mod_05_domain_result_rejects_negative_checks_performed() -> None:
    """MOD-05: checks_performed < 0 raises ValidationError."""
    data = _valid_domain_result()
    data["checks_performed"] = -1
    with pytest.raises(ValidationError):
        CertificationDomainResult(**data)


def test_mod_05b_domain_result_rejects_negative_checks_passed() -> None:
    """MOD-05b: checks_passed < 0 raises ValidationError."""
    data = _valid_domain_result()
    data["checks_passed"] = -1
    with pytest.raises(ValidationError):
        CertificationDomainResult(**data)


def test_mod_05c_domain_result_checks_performed_zero_accepted() -> None:
    """MOD-05c: checks_performed = 0 with checks_passed = 0 is valid (BLOCKED domain)."""
    data = _valid_domain_result()
    data["checks_performed"] = 0
    data["checks_passed"] = 0
    result = CertificationDomainResult(**data)
    assert result.checks_performed == 0
    assert result.checks_passed == 0


# ---------------------------------------------------------------------------
# MOD-06: CertificationResult valid construction for all three terminal states
# ---------------------------------------------------------------------------


def test_mod_06_certification_result_valid_certified() -> None:
    """MOD-06a: CertificationResult with CERTIFIED state constructs without error."""
    result = CertificationResult(
        terminal_state="CERTIFIED",
        certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFIED"],
        disclosed_failures=[],
    )
    assert result.terminal_state == "CERTIFIED"
    assert result.certification_summary == CERTIFICATION_SUMMARY_MAP["CERTIFIED"]
    assert result.disclosed_failures == []


def test_mod_06b_certification_result_valid_failed() -> None:
    """MOD-06b: CertificationResult with CERTIFICATION_FAILED state constructs without error."""
    result = CertificationResult(
        terminal_state="CERTIFICATION_FAILED",
        certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFICATION_FAILED"],
        disclosed_failures=["REPORT_INTEGRITY"],
    )
    assert result.terminal_state == "CERTIFICATION_FAILED"
    assert result.disclosed_failures == ["REPORT_INTEGRITY"]


def test_mod_06c_certification_result_valid_blocked() -> None:
    """MOD-06c: CertificationResult with CERTIFICATION_BLOCKED state constructs without error."""
    result = CertificationResult(
        terminal_state="CERTIFICATION_BLOCKED",
        certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFICATION_BLOCKED"],
        disclosed_failures=["EVIDENCE_LINEAGE", "OBSERVATION_COVERAGE"],
    )
    assert result.terminal_state == "CERTIFICATION_BLOCKED"
    assert len(result.disclosed_failures) == 2


# ---------------------------------------------------------------------------
# MOD-07: CertificationResult rejects unknown terminal_state
# ---------------------------------------------------------------------------


def test_mod_07_certification_result_rejects_unknown_terminal_state() -> None:
    """MOD-07: An unrecognised terminal_state raises ValidationError."""
    with pytest.raises(ValidationError):
        CertificationResult(
            terminal_state="UNKNOWN_STATE",
            certification_summary="whatever",
            disclosed_failures=[],
        )


def test_mod_07b_certification_result_rejects_empty_terminal_state() -> None:
    """MOD-07b: Empty terminal_state raises ValidationError."""
    with pytest.raises(ValidationError):
        CertificationResult(
            terminal_state="",
            certification_summary="",
            disclosed_failures=[],
        )


# ---------------------------------------------------------------------------
# MOD-08: CertificationResult rejects certification_summary not matching map
# ---------------------------------------------------------------------------


def test_mod_08_certification_result_rejects_wrong_summary_for_certified() -> None:
    """MOD-08a: certification_summary that does not match map for CERTIFIED raises ValidationError."""
    with pytest.raises(ValidationError):
        CertificationResult(
            terminal_state="CERTIFIED",
            certification_summary="wrong summary",
            disclosed_failures=[],
        )


def test_mod_08b_certification_result_rejects_wrong_summary_for_failed() -> None:
    """MOD-08b: certification_summary that does not match map for CERTIFICATION_FAILED raises ValidationError."""
    with pytest.raises(ValidationError):
        CertificationResult(
            terminal_state="CERTIFICATION_FAILED",
            certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFIED"],
            disclosed_failures=["RUNNER_HEALTH"],
        )


def test_mod_08c_certification_result_rejects_wrong_summary_for_blocked() -> None:
    """MOD-08c: certification_summary that does not match map for CERTIFICATION_BLOCKED raises ValidationError."""
    with pytest.raises(ValidationError):
        CertificationResult(
            terminal_state="CERTIFICATION_BLOCKED",
            certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFICATION_FAILED"],
            disclosed_failures=["EVIDENCE_COMPLETENESS"],
        )


# ---------------------------------------------------------------------------
# MOD-09: CertificationResult rejects non-empty disclosed_failures when CERTIFIED
# ---------------------------------------------------------------------------


def test_mod_09_certification_result_rejects_nonempty_failures_when_certified() -> None:
    """MOD-09: Non-empty disclosed_failures with CERTIFIED terminal_state raises ValidationError."""
    with pytest.raises(ValidationError):
        CertificationResult(
            terminal_state="CERTIFIED",
            certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFIED"],
            disclosed_failures=["RUNNER_HEALTH"],
        )


def test_mod_09b_certification_result_certified_with_empty_failures_accepted() -> None:
    """MOD-09b: Empty disclosed_failures with CERTIFIED terminal_state is valid."""
    result = CertificationResult(
        terminal_state="CERTIFIED",
        certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFIED"],
        disclosed_failures=[],
    )
    assert result.disclosed_failures == []


# ---------------------------------------------------------------------------
# MOD-10: CertificationResult accepts empty disclosed_failures when CERTIFICATION_FAILED
# ---------------------------------------------------------------------------


def test_mod_10_certification_result_accepts_empty_failures_when_failed() -> None:
    """MOD-10: Empty disclosed_failures is accepted even for CERTIFICATION_FAILED state.

    The model does not enforce that CERTIFICATION_FAILED requires non-empty disclosed_failures
    at the model layer — that enforcement belongs to the certification engine.
    """
    result = CertificationResult(
        terminal_state="CERTIFICATION_FAILED",
        certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFICATION_FAILED"],
        disclosed_failures=[],
    )
    assert result.terminal_state == "CERTIFICATION_FAILED"
    assert result.disclosed_failures == []


def test_mod_10b_certification_result_accepts_multiple_failures_when_failed() -> None:
    """MOD-10b: Multiple disclosed_failures are accepted for CERTIFICATION_FAILED."""
    result = CertificationResult(
        terminal_state="CERTIFICATION_FAILED",
        certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFICATION_FAILED"],
        disclosed_failures=["RUNNER_HEALTH", "REPORT_INTEGRITY"],
    )
    assert len(result.disclosed_failures) == 2


def test_mod_10c_certification_result_rejects_unknown_domain_in_failures() -> None:
    """MOD-10c: An unknown domain identifier in disclosed_failures raises ValidationError."""
    with pytest.raises(ValidationError):
        CertificationResult(
            terminal_state="CERTIFICATION_FAILED",
            certification_summary=CERTIFICATION_SUMMARY_MAP["CERTIFICATION_FAILED"],
            disclosed_failures=["UNKNOWN_DOMAIN"],
        )


# ---------------------------------------------------------------------------
# MOD-11: CertificationIdentity rejects certificate_version != cert_v1
# ---------------------------------------------------------------------------


def test_mod_11_identity_rejects_wrong_certificate_version() -> None:
    """MOD-11: certificate_version != 'cert_v1' raises ValidationError."""
    with pytest.raises(ValidationError):
        CertificationIdentity(
            certificate_id="cert_abc123",
            certificate_version="cert_v2",
            generated_at="2026-07-05T12:00:00.000Z",
            generator_version="0.0.0",
        )


def test_mod_11b_identity_accepts_cert_v1() -> None:
    """MOD-11b: certificate_version = 'cert_v1' is accepted."""
    identity = CertificationIdentity(
        certificate_id="cert_abc123",
        certificate_version=CERTIFICATE_VERSION,
        generated_at="2026-07-05T12:00:00.000Z",
        generator_version="0.0.0",
    )
    assert identity.certificate_version == CERTIFICATE_VERSION


def test_mod_11c_identity_rejects_empty_certificate_version() -> None:
    """MOD-11c: Empty certificate_version raises ValidationError."""
    with pytest.raises(ValidationError):
        CertificationIdentity(
            certificate_id="cert_abc123",
            certificate_version="",
            generated_at="2026-07-05T12:00:00.000Z",
            generator_version="0.0.0",
        )


# ---------------------------------------------------------------------------
# MOD-12: PlatformIntegrityCertificate valid full construction with 8 domain results
# ---------------------------------------------------------------------------


def test_mod_12_certificate_valid_full_construction() -> None:
    """MOD-12: A complete certificate dict with all 8 domain results constructs without error."""
    data = _valid_certificate_data()
    cert = PlatformIntegrityCertificate(**data)

    assert cert.identity.certificate_version == CERTIFICATE_VERSION
    assert cert.result.terminal_state == "CERTIFIED"
    assert cert.result.disclosed_failures == []
    assert len(cert.domain_results) == 8
    assert cert.certjob_id.startswith("certjob_")
    assert cert.audit_provenance.client_id == "client_test"
    assert cert.report_reference.report_version == "report_v1"


def test_mod_12b_certificate_domain_results_all_domains_present() -> None:
    """MOD-12b: All 8 domain identifiers are present in domain_results."""
    data = _valid_certificate_data()
    cert = PlatformIntegrityCertificate(**data)

    present_domains = {r.domain for r in cert.domain_results}
    assert present_domains == set(CERT_DOMAIN_IDENTIFIERS)


# ---------------------------------------------------------------------------
# MOD-13: PlatformIntegrityCertificate rejects fewer than 8 domain results
# ---------------------------------------------------------------------------


def test_mod_13_certificate_rejects_fewer_than_8_domain_results() -> None:
    """MOD-13: domain_results with 7 entries raises ValidationError."""
    data = _valid_certificate_data()
    data["domain_results"] = _all_domain_results()[:7]
    with pytest.raises(ValidationError):
        PlatformIntegrityCertificate(**data)


def test_mod_13b_certificate_rejects_more_than_8_domain_results() -> None:
    """MOD-13b: domain_results with 9 entries raises ValidationError."""
    data = _valid_certificate_data()
    extra = copy.deepcopy(_all_domain_results())
    extra.append(_valid_domain_result(domain="RUNNER_HEALTH"))
    data["domain_results"] = extra
    with pytest.raises(ValidationError):
        PlatformIntegrityCertificate(**data)


def test_mod_13c_certificate_rejects_empty_domain_results() -> None:
    """MOD-13c: Empty domain_results list raises ValidationError."""
    data = _valid_certificate_data()
    data["domain_results"] = []
    with pytest.raises(ValidationError):
        PlatformIntegrityCertificate(**data)


# ---------------------------------------------------------------------------
# MOD-14: PlatformIntegrityCertificate rejects duplicate domain identifiers
# ---------------------------------------------------------------------------


def test_mod_14_certificate_rejects_duplicate_domain_identifiers() -> None:
    """MOD-14: domain_results with duplicate domain identifiers raises ValidationError."""
    data = _valid_certificate_data()
    # Build 8 results but use RUNNER_HEALTH twice and omit REPORT_INTEGRITY
    duped: list[Any] = [_valid_domain_result("RUNNER_HEALTH")] * 2
    for d in CERT_DOMAIN_IDENTIFIERS[1:7]:
        duped.append(_valid_domain_result(d))
    data["domain_results"] = duped
    with pytest.raises(ValidationError):
        PlatformIntegrityCertificate(**data)


# ---------------------------------------------------------------------------
# MOD-15: PlatformIntegrityCertificate rejects missing domain identifier
# ---------------------------------------------------------------------------


def test_mod_15_certificate_rejects_missing_domain_identifier() -> None:
    """MOD-15: domain_results missing one domain identifier raises ValidationError.

    8 entries but REPORT_INTEGRITY appears twice instead of once, with no
    METHODOLOGY_COMPLIANCE — should fail on either duplicate or missing check.
    """
    data = _valid_certificate_data()
    # Replace METHODOLOGY_COMPLIANCE with a second REPORT_INTEGRITY entry
    replaced: list[Any] = []
    for d in CERT_DOMAIN_IDENTIFIERS:
        if d == "METHODOLOGY_COMPLIANCE":
            replaced.append(_valid_domain_result("REPORT_INTEGRITY"))
        else:
            replaced.append(_valid_domain_result(d))
    data["domain_results"] = replaced
    with pytest.raises(ValidationError):
        PlatformIntegrityCertificate(**data)


# ---------------------------------------------------------------------------
# MOD-16: PlatformIntegrityCertificate.to_dict() returns a plain dict
# ---------------------------------------------------------------------------


def test_mod_16_to_dict_returns_plain_dict() -> None:
    """MOD-16: to_dict() returns a plain Python dict, not a Pydantic model."""
    data = _valid_certificate_data()
    cert = PlatformIntegrityCertificate(**data)
    result = cert.to_dict()

    assert isinstance(result, dict)
    assert not isinstance(result, PlatformIntegrityCertificate)


def test_mod_16b_to_dict_contains_expected_top_level_keys() -> None:
    """MOD-16b: to_dict() output contains all expected top-level keys."""
    data = _valid_certificate_data()
    cert = PlatformIntegrityCertificate(**data)
    result = cert.to_dict()

    assert "identity" in result
    assert "result" in result
    assert "report_reference" in result
    assert "audit_provenance" in result
    assert "domain_results" in result
    assert "certjob_id" in result


def test_mod_16c_to_dict_domain_results_is_list_of_dicts() -> None:
    """MOD-16c: domain_results in to_dict() output is a list of plain dicts."""
    data = _valid_certificate_data()
    cert = PlatformIntegrityCertificate(**data)
    result = cert.to_dict()

    assert isinstance(result["domain_results"], list)
    assert len(result["domain_results"]) == 8
    for dr in result["domain_results"]:
        assert isinstance(dr, dict)


# ---------------------------------------------------------------------------
# MOD-17: generate_certificate_id() returns string starting with cert_
# ---------------------------------------------------------------------------


def test_mod_17_generate_certificate_id_starts_with_cert_prefix() -> None:
    """MOD-17: generate_certificate_id() returns a string starting with 'cert_'."""
    cert_id = generate_certificate_id()
    assert cert_id.startswith("cert_")


def test_mod_17b_generate_certificate_id_returns_string() -> None:
    """MOD-17b: generate_certificate_id() returns a non-empty string."""
    cert_id = generate_certificate_id()
    assert isinstance(cert_id, str)
    assert len(cert_id) > len("cert_")


# ---------------------------------------------------------------------------
# MOD-18: generate_certjob_id() returns string starting with certjob_
# ---------------------------------------------------------------------------


def test_mod_18_generate_certjob_id_starts_with_certjob_prefix() -> None:
    """MOD-18: generate_certjob_id() returns a string starting with 'certjob_'."""
    certjob_id = generate_certjob_id()
    assert certjob_id.startswith("certjob_")


def test_mod_18b_generate_certjob_id_returns_string() -> None:
    """MOD-18b: generate_certjob_id() returns a non-empty string."""
    certjob_id = generate_certjob_id()
    assert isinstance(certjob_id, str)
    assert len(certjob_id) > len("certjob_")


# ---------------------------------------------------------------------------
# MOD-19: generate_certificate_id() returns unique values on repeated calls
# ---------------------------------------------------------------------------


def test_mod_19_generate_certificate_id_unique_on_repeated_calls() -> None:
    """MOD-19: generate_certificate_id() produces unique values across multiple calls."""
    ids = {generate_certificate_id() for _ in range(100)}
    assert len(ids) == 100


def test_mod_19b_generate_certjob_id_unique_on_repeated_calls() -> None:
    """MOD-19b: generate_certjob_id() produces unique values across multiple calls."""
    ids = {generate_certjob_id() for _ in range(100)}
    assert len(ids) == 100
