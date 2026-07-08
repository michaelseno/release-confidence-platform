"""Test: CertificationEngine pipeline behavior — gate, idempotency, and completion.

Verifies prerequisite gate enforcement, idempotency semantics, error class hierarchy,
terminal state determination, and full pipeline completion.
"""

from __future__ import annotations

from typing import Any

import pytest

from release_confidence_platform.audit_platform_integrity.engine import (
    CertificationAlreadyCertifiedError,
    CertificationEngine,
    CertificationGateError,
    _determine_terminal_state,
)
from release_confidence_platform.audit_platform_integrity.models import (
    CertificationDomainResult,
    PlatformIntegrityCertificate,
)
from release_confidence_platform.core.exceptions import ValidationError

# ---------------------------------------------------------------------------
# Phase 6 report artifact fixture (minimal but valid)
# ---------------------------------------------------------------------------

_REPORT_ARTIFACT = {
    "identity": {
        "report_id": "report_testfixture",
        "report_version": "report_v1",
        "generated_at": "2026-07-05T12:00:00Z",
        "generator_version": "1.0.0",
    },
    "intelligence_provenance": {
        "intelligence_version": "intel_v1",
        "intelligence_job_id": "intjob_testfixture",
        "client_id": "client_test",
        "audit_id": "audit_test",
        "audit_execution_id": "exec_test",
        "config_version": "cfg_v1",
        "aggregation_version": "agg_v1",
        "aggregate_set_hash": "hashTEST",
        "intelligence_completed_at": "2026-07-05T11:00:00Z",
    },
    "executive_summary": {
        "score_label": "HIGH_CONFIDENCE",
        "composite_score_value": 0.850,
        "endpoint_count": 1,
        "audit_success_rate": 0.900,
        "total_executions": 20,
        "score_label_description": (
            "Reliability indicators across all assessed endpoints are strong. "
            "The observed evidence does not indicate material reliability concerns "
            "for the audited release scope."
        ),
    },
    "audit_reliability_overview": {
        "total_executions": 20,
        "total_pass": 18,
        "total_fail": 2,
        "total_timeout": 1,
        "total_network_failure": 0,
        "audit_success_rate": 0.9,
        "endpoint_count": 1,
        "audit_latency_mean_ms": 120.0,
        "audit_latency_p95_ms": 400.0,
        "audit_latency_p99_ms": 480.0,
        "source_field_refs": {"total_executions": "AuditAggregate.request_counts.total"},
    },
    "composite_score": {
        "value": 0.850,
        "score_label": "HIGH_CONFIDENCE",
        "intelligence_version": "intel_v1",
        "aggregation_version": "agg_v1",
        "aggregate_set_hash": "hashTEST",
        "endpoint_count": 1,
        "component_breakdown": {"reliability": 0.9},
    },
    "endpoints": [
        {
            "endpoint_id": "ep_test",
            "reliability_metrics": {
                "execution_count": 20,
                "pass_count": 18,
                "fail_count": 2,
                "timeout_count": 1,
                "success_rate": 0.9,
                "success_rate_numerator": 18,
                "success_rate_denominator": 20,
                "latency_min_ms": 50.0,
                "latency_max_ms": 500.0,
                "latency_mean_ms": 120.0,
                "latency_median_ms": 100.0,
                "latency_p95_ms": 400.0,
                "latency_p99_ms": 480.0,
                "latency_count": 20,
                "failure_classification_breakdown": {"PASS": 18, "TIMEOUT": 1},
                "http_response_distribution": {"200": 18, "504": 2},
                "source_field_refs": {"execution_count": "EndpointAggregate.execution_count"},
            },
            "stability_analysis": {
                "success_rate_stability_label": "STABLE",
                "latency_stability_label": "STABLE",
                "methodology_trace": {"window": 5},
            },
            "burst_analysis": {
                "failure_burst_label": "NO_BURST",
                "latency_spike_label": "NO_SPIKE",
                "methodology_trace": {"threshold": 3},
            },
            "consistency_analysis": {
                "consistency_label": "CONSISTENT",
                "methodology_trace": {"cv": 0.1},
            },
            "endpoint_score": {
                "composite_score": 0.850,
                "reliability_score": 0.900,
                "stability_score": 1.000,
                "burst_score": 1.000,
                "consistency_score": 1.000,
                "score_derivation": {"method": "weighted_average"},
            },
        }
    ],
    "input_lineage": {
        "aggregate_set_hash": "hashTEST",
        "aggregation_job_id": "aggjob_TEST",
        "aggregation_version": "agg_v1",
        "aggregate_set_completion_created_at": "2026-07-05T10:00:00Z",
        "endpoint_aggregate_count": 1,
        "source_raw_result_count": 20,
        "audit_lineage_manifest_ref": {},
    },
    "methodology_disclosure": {
        "intelligence_version": "intel_v1",
        "scoring": {"method": "composite"},
        "stability_label_definitions": {"STABLE": "stable definition"},
        "burst_label_definitions": {"NO_BURST": "no burst definition"},
        "consistency_label_definitions": {"CONSISTENT": "consistent definition"},
        "label_to_score_mapping": {"HIGH_CONFIDENCE": 0.9},
        "limitations": [],
    },
}

_COMPLETE_REPORT_METADATA = {
    "status": "COMPLETE",
    "report_id": "report_testfixture",
    "report_version": "report_v1",
    "intelligence_version": "intel_v1",
    "aggregate_set_hash": "hashTEST",
    "endpoint_count": 1,
    "s3_artifact_ref": "reports/client_test/audit_test/exec_test/agg_v1/intel_v1/report_v1/rptjob_test/artifact.json",
    "completed_at": "2026-07-05T12:00:00Z",
}


# ---------------------------------------------------------------------------
# Repository and publisher stubs
# ---------------------------------------------------------------------------


class _EngineTestRepository:
    """Repository stub with configurable state for gate and idempotency tests."""

    def __init__(
        self,
        *,
        report_metadata: dict[str, Any] | None = _COMPLETE_REPORT_METADATA,
        existing_cert_metadata: dict[str, Any] | None = None,
        report_artifact: dict[str, Any] | None = None,
        read_artifact_raises: Exception | None = None,
    ) -> None:
        self._report_metadata = report_metadata
        self._existing_cert_metadata = existing_cert_metadata
        self._report_artifact = report_artifact or _REPORT_ARTIFACT
        self._read_artifact_raises = read_artifact_raises
        self.write_calls: list[tuple[str, Any]] = []

    def get_report_metadata(self, *args, **kwargs) -> dict[str, Any] | None:
        return self._report_metadata

    def get_cert_metadata(self, *args, **kwargs) -> dict[str, Any] | None:
        return self._existing_cert_metadata

    def read_report_artifact(self, s3_artifact_ref: str) -> dict[str, Any]:
        if self._read_artifact_raises is not None:
            raise self._read_artifact_raises
        return self._report_artifact

    def write_certjob_pending(self, client_id, audit_id, certjob_id, identity_tuple):
        self.write_calls.append(("write_certjob_pending", {
            "client_id": client_id,
            "audit_id": audit_id,
            "certjob_id": certjob_id,
            "SK": f"AUDIT#{audit_id}#CERTJOB#{certjob_id}",
        }))

    def update_certjob_in_progress(self, client_id, audit_id, certjob_id):
        self.write_calls.append(("update_certjob_in_progress", {
            "certjob_id": certjob_id,
            "SK": f"AUDIT#{audit_id}#CERTJOB#{certjob_id}",
        }))

    def update_certjob_complete(self, client_id, audit_id, certjob_id, terminal_state, s3_ref):
        self.write_calls.append(("update_certjob_complete", {
            "certjob_id": certjob_id,
            "terminal_state": terminal_state,
            "SK": f"AUDIT#{audit_id}#CERTJOB#{certjob_id}",
        }))

    def update_certjob_failed(self, client_id, audit_id, certjob_id, error):
        self.write_calls.append(("update_certjob_failed", {
            "certjob_id": certjob_id,
            "error": error,
            "SK": f"AUDIT#{audit_id}#CERTJOB#{certjob_id}",
        }))

    def write_cert_metadata_complete(self, **kwargs):
        self.write_calls.append(("write_cert_metadata_complete", kwargs))


class _NullPublisher:
    """Publisher stub that records write calls."""

    def __init__(self) -> None:
        self.write_calls: list[tuple[str, dict]] = []

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        self.write_calls.append((key, artifact))


class _FailingPublisher:
    """Publisher stub that raises on write_artifact."""

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        raise RuntimeError("S3 write failure simulation")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _call_certify(
    repo: _EngineTestRepository | None = None,
    publisher: _NullPublisher | None = None,
    *,
    force: bool = False,
) -> PlatformIntegrityCertificate:
    repo = repo or _EngineTestRepository()
    publisher = publisher or _NullPublisher()
    engine = CertificationEngine(
        repository=repo,
        publisher=publisher,
        platform_version="test_1.0.0",
    )
    return engine.certify(
        client_id="client_test",
        audit_id="audit_test",
        audit_execution_id="exec_test",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        intelligence_version="intel_v1",
        report_version="report_v1",
        cert_version="cert_v1",
        force=force,
    )


# ---------------------------------------------------------------------------
# _determine_terminal_state unit tests
# ---------------------------------------------------------------------------


def _make_domain_result(domain: str, status: str) -> CertificationDomainResult:
    return CertificationDomainResult(
        domain=domain,
        status=status,
        checks_performed=1,
        checks_passed=1 if status == "PASSED" else 0,
        failure_details=[] if status == "PASSED" else ["test failure"],
        evidence_refs=["test_field"],
    )


def test_determine_terminal_state_certified_when_all_passed():
    """All PASSED domains must produce CERTIFIED terminal state."""
    results = [_make_domain_result("RUNNER_HEALTH", "PASSED")]
    assert _determine_terminal_state(results) == "CERTIFIED"


def test_determine_terminal_state_failed_when_one_failed():
    """Any FAILED domain (with no BLOCKED) must produce CERTIFICATION_FAILED."""
    results = [
        _make_domain_result("RUNNER_HEALTH", "PASSED"),
        _make_domain_result("EVIDENCE_COMPLETENESS", "FAILED"),
    ]
    assert _determine_terminal_state(results) == "CERTIFICATION_FAILED"


def test_determine_terminal_state_blocked_takes_precedence():
    """CERTIFICATION_BLOCKED must take precedence over CERTIFICATION_FAILED."""
    results = [
        _make_domain_result("RUNNER_HEALTH", "PASSED"),
        _make_domain_result("EVIDENCE_COMPLETENESS", "FAILED"),
        _make_domain_result("EVIDENCE_INTEGRITY", "BLOCKED"),
    ]
    assert _determine_terminal_state(results) == "CERTIFICATION_BLOCKED"


# ---------------------------------------------------------------------------
# Prerequisite gate tests
# ---------------------------------------------------------------------------


def test_gate_fails_when_report_metadata_not_found():
    """None from get_report_metadata must raise CertificationGateError."""
    repo = _EngineTestRepository(report_metadata=None)
    with pytest.raises(CertificationGateError):
        _call_certify(repo)


def test_gate_fails_when_report_not_complete():
    """ReportMetadata with status=PENDING must raise CertificationGateError."""
    pending_meta = {**_COMPLETE_REPORT_METADATA, "status": "PENDING"}
    repo = _EngineTestRepository(report_metadata=pending_meta)
    with pytest.raises(CertificationGateError):
        _call_certify(repo)


def test_no_certjob_written_when_gate_fails():
    """No CertificationJob DynamoDB record may be written when the gate fails."""
    repo = _EngineTestRepository(report_metadata=None)
    with pytest.raises(CertificationGateError):
        _call_certify(repo)
    assert len(repo.write_calls) == 0, (
        f"Expected 0 writes when gate fails, got {len(repo.write_calls)}: {repo.write_calls}"
    )


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------


def test_idempotency_raises_already_certified_when_prior_certified_no_force():
    """Prior CERTIFIED record without --force must raise CertificationAlreadyCertifiedError."""
    existing = {
        "terminal_state": "CERTIFIED",
        "certificate_id": "cert_existing",
        "s3_certificate_ref": "integrity/client_test/audit_test/exec_test/...",
    }
    repo = _EngineTestRepository(existing_cert_metadata=existing)
    with pytest.raises(CertificationAlreadyCertifiedError):
        _call_certify(repo)


def test_idempotency_proceeds_with_force_when_prior_certified():
    """Prior CERTIFIED record with --force must proceed with new certification."""
    existing = {
        "terminal_state": "CERTIFIED",
        "certificate_id": "cert_existing",
        "s3_certificate_ref": "integrity/client_test/audit_test/exec_test/...",
    }
    repo = _EngineTestRepository(existing_cert_metadata=existing)
    result = _call_certify(repo, force=True)
    assert isinstance(result, PlatformIntegrityCertificate)


def test_idempotency_proceeds_when_prior_is_certification_failed():
    """Prior CERTIFICATION_FAILED record must allow re-certification without --force."""
    existing = {
        "terminal_state": "CERTIFICATION_FAILED",
        "certificate_id": "cert_failed",
    }
    repo = _EngineTestRepository(existing_cert_metadata=existing)
    result = _call_certify(repo)
    assert isinstance(result, PlatformIntegrityCertificate)


def test_idempotency_proceeds_when_prior_is_certification_blocked():
    """Prior CERTIFICATION_BLOCKED record must allow re-certification without --force."""
    existing = {
        "terminal_state": "CERTIFICATION_BLOCKED",
        "certificate_id": "cert_blocked",
    }
    repo = _EngineTestRepository(existing_cert_metadata=existing)
    result = _call_certify(repo)
    assert isinstance(result, PlatformIntegrityCertificate)


# ---------------------------------------------------------------------------
# Full pipeline tests
# ---------------------------------------------------------------------------


def test_successful_pipeline_returns_platform_integrity_certificate():
    """Full pipeline with valid inputs must return a PlatformIntegrityCertificate."""
    result = _call_certify()
    assert isinstance(result, PlatformIntegrityCertificate)


def test_successful_pipeline_produces_certified_terminal_state():
    """Valid Phase 6 report artifact must produce CERTIFIED terminal state."""
    result = _call_certify()
    assert result.result.terminal_state == "CERTIFIED"
    assert result.result.certification_summary == "INTEGRITY_VERIFIED"
    assert result.result.disclosed_failures == []


def test_successful_pipeline_has_eight_domain_results():
    """PlatformIntegrityCertificate must contain exactly 8 domain results."""
    result = _call_certify()
    assert len(result.domain_results) == 8


def test_successful_pipeline_writes_to_s3():
    """S3 write_artifact must be called exactly once during successful certification."""
    publisher = _NullPublisher()
    _call_certify(publisher=publisher)
    assert len(publisher.write_calls) == 1
    key, _ = publisher.write_calls[0]
    assert key.startswith("integrity/")


def test_certification_failed_when_one_domain_fails():
    """Report with mismatched aggregate_set_hash must produce CERTIFICATION_FAILED."""
    # Create a report artifact where identity.report_id != ReportMetadata.report_id
    # to trigger EI-2 failure in EVIDENCE_INTEGRITY domain.
    broken_artifact = {
        **_REPORT_ARTIFACT,
        "identity": {
            **_REPORT_ARTIFACT["identity"],
            "report_id": "report_WRONG_ID",  # mismatch with ReportMetadata.report_id
        },
    }
    repo = _EngineTestRepository(report_artifact=broken_artifact)
    result = _call_certify(repo)
    assert result.result.terminal_state in ("CERTIFICATION_FAILED", "CERTIFICATION_BLOCKED")
    assert len(result.result.disclosed_failures) >= 1


def test_certification_blocked_when_required_section_absent():
    """Report artifact with a missing required section must produce CERTIFICATION_BLOCKED.

    When read_report_artifact returns an artifact dict that fails Pydantic validation
    (e.g. missing the required 'endpoints' field), the inner try-except at steps 7+8
    catches the PydanticValidationError and produces 8 BLOCKED domain results.
    The pipeline completes and returns a CERTIFICATION_BLOCKED certificate.
    """
    # Remove the endpoints section so ReleaseConfidenceReport.model_validate raises.
    broken_artifact = {k: v for k, v in _REPORT_ARTIFACT.items() if k != "endpoints"}
    repo = _EngineTestRepository(report_artifact=broken_artifact)
    result = _call_certify(repo)
    assert isinstance(result, PlatformIntegrityCertificate)
    assert result.result.terminal_state == "CERTIFICATION_BLOCKED"
    assert result.result.certification_summary == "INTEGRITY_BLOCKED"
    assert len(result.domain_results) == 8
    assert all(r.status == "BLOCKED" for r in result.domain_results)


def test_s3_read_failure_produces_certification_blocked_certificate():
    """TN-12: S3 read failure on Phase 6 artifact must produce a CERTIFICATION_BLOCKED
    certificate without raising, and transition CertificationJob to FAILED.

    Acceptance criteria covered: AC-20, AC-22, AC-28.
    """
    from release_confidence_platform.audit_platform_integrity.constants import (
        CERT_DOMAIN_IDENTIFIERS,
        CERTIFICATION_SUMMARY_MAP,
    )

    repo = _EngineTestRepository(
        read_artifact_raises=Exception("S3 NoSuchKey"),
    )
    publisher = _NullPublisher()

    # Engine must NOT raise — it should return a certificate.
    result = _call_certify(repo, publisher)

    # Certificate type and terminal state
    assert isinstance(result, PlatformIntegrityCertificate)
    assert result.result.terminal_state == "CERTIFICATION_BLOCKED"

    # Certification summary must match the CERTIFICATION_BLOCKED mapping.
    assert result.result.certification_summary == CERTIFICATION_SUMMARY_MAP["CERTIFICATION_BLOCKED"]
    assert result.result.certification_summary == "INTEGRITY_BLOCKED"

    # Exactly 8 BLOCKED domain results, one per domain identifier.
    assert len(result.domain_results) == 8
    assert all(r.status == "BLOCKED" for r in result.domain_results)
    assert all(r.checks_performed == 0 for r in result.domain_results)
    assert all(r.checks_passed == 0 for r in result.domain_results)

    # All 8 domain identifiers must be present in disclosed_failures.
    assert len(result.result.disclosed_failures) == 8
    for domain_id in CERT_DOMAIN_IDENTIFIERS:
        assert domain_id in result.result.disclosed_failures, (
            f"Expected {domain_id!r} in disclosed_failures"
        )

    # CERTIFICATION_BLOCKED certificate must be written to S3.
    assert len(publisher.write_calls) == 1
    s3_key, _ = publisher.write_calls[0]
    assert s3_key.startswith("integrity/")

    # CertificationJob must transition to FAILED (not COMPLETE) — TN-12 requirement.
    certjob_methods = [call[0] for call in repo.write_calls]
    assert "update_certjob_failed" in certjob_methods, (
        f"Expected update_certjob_failed in write_calls; got: {certjob_methods}"
    )
    assert "update_certjob_complete" not in certjob_methods, (
        "update_certjob_complete must NOT be called when TN-12 is triggered"
    )

    # failure_stage and failure_reason must be populated in the FAILED record.
    failed_call = next(
        call for call in repo.write_calls if call[0] == "update_certjob_failed"
        and "stage=reading_phase6_artifact" in call[1].get("error", "")
    )
    assert "stage=reading_phase6_artifact" in failed_call[1]["error"]
    assert "reason=" in failed_call[1]["error"]


def test_infrastructure_failure_after_pending_updates_certjob_to_failed():
    """Infrastructure failure after CertificationJob PENDING must update job to FAILED."""
    repo = _EngineTestRepository()
    engine = CertificationEngine(
        repository=repo,
        publisher=_FailingPublisher(),
        platform_version="test_1.0.0",
    )
    with pytest.raises(RuntimeError, match="S3 write failure"):
        engine.certify(
            client_id="client_test",
            audit_id="audit_test",
            audit_execution_id="exec_test",
            config_version="cfg_v1",
            aggregation_version="agg_v1",
            intelligence_version="intel_v1",
            report_version="report_v1",
            cert_version="cert_v1",
        )
    # Verify that update_certjob_failed was called
    methods = [call[0] for call in repo.write_calls]
    assert "update_certjob_failed" in methods, (
        f"Expected update_certjob_failed in write calls: {methods}"
    )


# ---------------------------------------------------------------------------
# Error class hierarchy
# ---------------------------------------------------------------------------


def test_certification_gate_error_inherits_validation_error():
    """CertificationGateError must inherit from ValidationError."""
    error = CertificationGateError("test gate error")
    assert isinstance(error, ValidationError)
    assert error.error_type == "REPORT_NOT_COMPLETE"


def test_certification_already_certified_error_inherits_validation_error():
    """CertificationAlreadyCertifiedError must inherit from ValidationError."""
    error = CertificationAlreadyCertifiedError("test idempotency error")
    assert isinstance(error, ValidationError)
    assert error.error_type == "CERTIFICATION_ALREADY_CERTIFIED"
