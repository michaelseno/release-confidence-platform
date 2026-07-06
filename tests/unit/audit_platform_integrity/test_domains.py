"""Unit tests for Phase 7.3 certification domain executor functions.

Covers all eight certification domain check functions defined in
audit_platform_integrity.domains. For each domain, tests:
  - Happy path: valid Phase 6 fixture → PASSED
  - At least one failure injection → FAILED with non-empty failure_details
  - At least one blocked condition → BLOCKED

Fixture shape: 5 endpoints, HIGH_CONFIDENCE, composite_score=1.000 (Phase 6.8
campaign shape). All 8 domains pass against the base fixture.

BLOCKED conditions are created using Pydantic model_construct() to bypass
validation and set required sections to None.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from release_confidence_platform.audit_platform_integrity.domains import (
    check_evidence_completeness,
    check_evidence_integrity,
    check_evidence_lineage,
    check_methodology_compliance,
    check_observation_coverage,
    check_report_integrity,
    check_runner_health,
    check_scheduler_integrity,
)
from release_confidence_platform.deterministic_reporting.constants import (
    SCORE_LABEL_DESCRIPTIONS,
)
from release_confidence_platform.deterministic_reporting.models import (
    BurstAnalysis,
    ConsistencyAnalysis,
    EndpointScore,
    EndpointSection,
    ExecutiveSummary,
    InputLineageSection,
    IntelligenceProvenance,
    MethodologyDisclosure,
    ReliabilityMetrics,
    ReleaseConfidenceReport,
    ReportIdentity,
    StabilityAnalysis,
)

# ---------------------------------------------------------------------------
# Shared fixture constants
# ---------------------------------------------------------------------------

_AGGREGATE_SET_HASH = "deadbeef" * 8
_REPORT_ID = "report_abc1234567890abcdef1234567890ab"
_REPORT_VERSION = "report_v1"
_INTEL_VERSION = "intel_v1"
_INTEL_JOB_ID = "intjob_abc1234567890abcdef1234567890ab"
_INTELLIGENCE_COMPLETED_AT = "2026-07-05T12:00:00.000Z"
_AGG_VERSION = "agg_v1"
_AGG_JOB_ID = "aggjob_test"

_ENDPOINT_IDS = [
    "endpoint_1",
    "endpoint_2",
    "endpoint_3",
    "endpoint_4",
    "endpoint_5",
]

# 5 endpoints × 20 executions = 100 total
_EXECUTIONS_PER_ENDPOINT = 20
_TOTAL_EXECUTIONS = len(_ENDPOINT_IDS) * _EXECUTIONS_PER_ENDPOINT


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_methodology_trace() -> dict[str, Any]:
    return {
        "algorithm": "test_v1",
        "algorithm_version": "1",
        "inputs": {},
        "thresholds": {},
        "intermediate_values": {},
        "label_determination": "passed",
    }


def _make_score_derivation() -> dict[str, Any]:
    return {
        "reliability_score_source": "success_rate",
        "composite_score_formula": "weighted_sum",
    }


def _make_reliability_metrics(
    execution_count: int = _EXECUTIONS_PER_ENDPOINT,
    pass_count: int = _EXECUTIONS_PER_ENDPOINT,
    fail_count: int = 0,
    success_rate: float | None = 1.000,
) -> ReliabilityMetrics:
    return ReliabilityMetrics(
        execution_count=execution_count,
        pass_count=pass_count,
        fail_count=fail_count,
        timeout_count=0,
        success_rate=success_rate,
        success_rate_numerator=pass_count,
        success_rate_denominator=execution_count,
        latency_count=execution_count,
        failure_classification_breakdown={"PASS": pass_count},
        http_response_distribution={"200": pass_count},
        source_field_refs={"execution_count": "endpoint_aggregate.execution_count"},
    )


def _make_endpoint_section(endpoint_id: str) -> EndpointSection:
    return EndpointSection(
        endpoint_id=endpoint_id,
        reliability_metrics=_make_reliability_metrics(),
        stability_analysis=StabilityAnalysis(
            success_rate_stability_label="STABLE",
            latency_stability_label="STABLE",
            methodology_trace=_make_methodology_trace(),
        ),
        burst_analysis=BurstAnalysis(
            failure_burst_label="NO_BURST_DETECTED",
            latency_spike_label="NO_SPIKE_DETECTED",
            methodology_trace=_make_methodology_trace(),
        ),
        consistency_analysis=ConsistencyAnalysis(
            consistency_label="CONSISTENT",
            methodology_trace=_make_methodology_trace(),
        ),
        endpoint_score=EndpointScore(
            composite_score=1.000,
            reliability_score=1.000,
            stability_score=1.000,
            burst_score=1.000,
            consistency_score=1.000,
            score_derivation=_make_score_derivation(),
        ),
    )


def _make_methodology_disclosure() -> MethodologyDisclosure:
    return MethodologyDisclosure(
        intelligence_version=_INTEL_VERSION,
        scoring={
            "composite_score_range": "[0.0, 1.0]",
            "rollup": "mean",
            "precision": "3 decimal places",
            "component_weights": {
                "reliability": 0.50,
                "stability": 0.20,
                "burst": 0.15,
                "consistency": 0.15,
            },
            "per_endpoint_formula": "reliability*0.50 + stability*0.20 + burst*0.15 + consistency*0.15",
        },
        stability_label_definitions={"STABLE": "ok", "DEGRADED": "not ok"},
        burst_label_definitions={"NO_BURST_DETECTED": "ok", "BURST_SUSPECTED": "not ok"},
        consistency_label_definitions={"CONSISTENT": "ok", "INCONSISTENT": "not ok"},
        label_to_score_mapping={"STABLE": 1.0, "CONSISTENT": 1.0, "NO_BURST_DETECTED": 1.0},
        limitations=[],
    )


def _make_report() -> ReleaseConfidenceReport:
    """Build a minimal valid ReleaseConfidenceReport that passes all 8 domains.

    Shape: 5 endpoints, HIGH_CONFIDENCE, composite_score=1.000.
    """
    endpoints = [_make_endpoint_section(eid) for eid in _ENDPOINT_IDS]
    return ReleaseConfidenceReport(
        identity=ReportIdentity(
            report_id=_REPORT_ID,
            report_version=_REPORT_VERSION,
            generated_at="2026-07-05T12:00:00.000Z",
            generator_version="0.0.0",
        ),
        intelligence_provenance=IntelligenceProvenance(
            intelligence_version=_INTEL_VERSION,
            intelligence_job_id=_INTEL_JOB_ID,
            client_id="client_test",
            audit_id="audit_test",
            audit_execution_id="audexec_test",
            config_version="v1",
            aggregation_version=_AGG_VERSION,
            aggregate_set_hash=_AGGREGATE_SET_HASH,
            intelligence_completed_at=_INTELLIGENCE_COMPLETED_AT,
        ),
        executive_summary=ExecutiveSummary(
            score_label="HIGH_CONFIDENCE",
            composite_score_value=1.000,
            endpoint_count=len(_ENDPOINT_IDS),
            audit_success_rate=1.000,
            total_executions=_TOTAL_EXECUTIONS,
            score_label_description=SCORE_LABEL_DESCRIPTIONS["HIGH_CONFIDENCE"],
        ),
        audit_reliability_overview={  # type: ignore[arg-type]
            "total_executions": _TOTAL_EXECUTIONS,
            "total_pass": _TOTAL_EXECUTIONS,
            "total_fail": 0,
            "total_timeout": 0,
            "total_network_failure": 0,
            "audit_success_rate": 1.000,
            "endpoint_count": len(_ENDPOINT_IDS),
            "source_field_refs": {"total_executions": "audit_aggregate.request_counts.total"},
        },
        composite_score={  # type: ignore[arg-type]
            "value": 1.000,
            "score_label": "HIGH_CONFIDENCE",
            "intelligence_version": _INTEL_VERSION,
            "aggregation_version": _AGG_VERSION,
            "aggregate_set_hash": _AGGREGATE_SET_HASH,
            "endpoint_count": len(_ENDPOINT_IDS),
            "component_breakdown": {},
        },
        endpoints=endpoints,
        input_lineage=InputLineageSection(
            aggregate_set_hash=_AGGREGATE_SET_HASH,
            aggregation_job_id=_AGG_JOB_ID,
            aggregation_version=_AGG_VERSION,
            aggregate_set_completion_created_at="2026-07-05T11:00:00.000Z",
            endpoint_aggregate_count=len(_ENDPOINT_IDS),
            source_raw_result_count=_TOTAL_EXECUTIONS,
            audit_lineage_manifest_ref={
                "manifest_scope": "audit",
                "source_ref_count": _TOTAL_EXECUTIONS,
                "manifest_hash": "aabbccdd" * 8,
            },
        ),
        methodology_disclosure=_make_methodology_disclosure(),
    )


def _make_report_metadata() -> dict[str, Any]:
    """Return stable ReportMetadata fields matching the base fixture."""
    return {
        "report_id": _REPORT_ID,
        "report_version": _REPORT_VERSION,
        "intelligence_version": _INTEL_VERSION,
        "aggregate_set_hash": _AGGREGATE_SET_HASH,
        "endpoint_count": len(_ENDPOINT_IDS),
        "client_id": "client_test",
        "audit_id": "audit_test",
        "audit_execution_id": "audexec_test",
    }


# ===========================================================================
# RUNNER_HEALTH
# ===========================================================================


class TestRunnerHealth:
    """Tests for check_runner_health."""

    def test_happy_path_returns_passed(self) -> None:
        """Valid fixture returns RUNNER_HEALTH PASSED with 4/4 checks."""
        report = _make_report()
        result = check_runner_health(report)

        assert result.domain == "RUNNER_HEALTH"
        assert result.status == "PASSED"
        assert result.checks_performed == 4
        assert result.checks_passed == 4
        assert result.failure_details == []
        assert len(result.evidence_refs) > 0

    def test_rh1_fails_when_total_executions_zero(self) -> None:
        """RH-1 fails when executive_summary.total_executions == 0."""
        report = _make_report()
        es = report.executive_summary
        report = report.model_copy(
            update={
                "executive_summary": ExecutiveSummary(
                    score_label=es.score_label,
                    composite_score_value=es.composite_score_value,
                    endpoint_count=es.endpoint_count,
                    audit_success_rate=es.audit_success_rate,
                    total_executions=0,
                    score_label_description=es.score_label_description,
                )
            }
        )
        result = check_runner_health(report)

        assert result.status == "FAILED"
        assert any("RH-1" in d for d in result.failure_details)
        assert result.checks_passed < result.checks_performed

    def test_rh2_fails_when_endpoint_has_zero_execution_count(self) -> None:
        """RH-2 fails when an endpoint has reliability_metrics.execution_count == 0."""
        report = _make_report()
        endpoints = list(report.endpoints)
        bad_metrics = _make_reliability_metrics(
            execution_count=0, pass_count=0, fail_count=0, success_rate=None
        )
        bad_ep = EndpointSection.model_construct(
            endpoint_id=endpoints[0].endpoint_id,
            reliability_metrics=bad_metrics,
            stability_analysis=endpoints[0].stability_analysis,
            burst_analysis=endpoints[0].burst_analysis,
            consistency_analysis=endpoints[0].consistency_analysis,
            endpoint_score=endpoints[0].endpoint_score,
        )
        endpoints[0] = bad_ep
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_runner_health(report)

        assert result.status == "FAILED"
        assert any("RH-2" in d for d in result.failure_details)

    def test_rh3_fails_when_failure_rate_exceeds_one(self) -> None:
        """RH-3 fails when fail_count > execution_count (invalid failure rate > 1.0)."""
        report = _make_report()
        endpoints = list(report.endpoints)
        bad_metrics = ReliabilityMetrics.model_construct(
            execution_count=10,
            pass_count=0,
            fail_count=20,  # fail_count > execution_count → rate > 1.0
            timeout_count=0,
            success_rate=0.0,
            success_rate_numerator=0,
            success_rate_denominator=10,
            latency_count=10,
            failure_classification_breakdown={},
            http_response_distribution={},
            source_field_refs={},
        )
        bad_ep = EndpointSection.model_construct(
            endpoint_id=endpoints[2].endpoint_id,
            reliability_metrics=bad_metrics,
            stability_analysis=endpoints[2].stability_analysis,
            burst_analysis=endpoints[2].burst_analysis,
            consistency_analysis=endpoints[2].consistency_analysis,
            endpoint_score=endpoints[2].endpoint_score,
        )
        endpoints[2] = bad_ep
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_runner_health(report)

        assert result.status == "FAILED"
        assert any("RH-3" in d for d in result.failure_details)

    def test_rh4_fails_when_methodology_trace_absent(self) -> None:
        """RH-4 fails when stability_analysis.methodology_trace is None."""
        report = _make_report()
        endpoints = list(report.endpoints)
        bad_stability = StabilityAnalysis.model_construct(
            success_rate_stability_label="STABLE",
            latency_stability_label="STABLE",
            methodology_trace=None,
        )
        bad_ep = EndpointSection.model_construct(
            endpoint_id=endpoints[1].endpoint_id,
            reliability_metrics=endpoints[1].reliability_metrics,
            stability_analysis=bad_stability,
            burst_analysis=endpoints[1].burst_analysis,
            consistency_analysis=endpoints[1].consistency_analysis,
            endpoint_score=endpoints[1].endpoint_score,
        )
        endpoints[1] = bad_ep
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_runner_health(report)

        assert result.status == "FAILED"
        assert any("RH-4" in d for d in result.failure_details)

    def test_blocked_when_endpoints_is_none(self) -> None:
        """BLOCKED when endpoints is None (model_construct bypass)."""
        report = ReleaseConfidenceReport.model_construct(
            identity=_make_report().identity,
            intelligence_provenance=_make_report().intelligence_provenance,
            executive_summary=_make_report().executive_summary,
            audit_reliability_overview=_make_report().audit_reliability_overview,
            composite_score=_make_report().composite_score,
            endpoints=None,
            input_lineage=_make_report().input_lineage,
            methodology_disclosure=_make_report().methodology_disclosure,
        )
        result = check_runner_health(report)

        assert result.status == "BLOCKED"
        assert result.checks_performed == 0
        assert result.checks_passed == 0
        assert len(result.failure_details) > 0

    def test_blocked_when_methodology_disclosure_is_none(self) -> None:
        """BLOCKED when methodology_disclosure is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=base.executive_summary,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=base.endpoints,
            input_lineage=base.input_lineage,
            methodology_disclosure=None,
        )
        result = check_runner_health(report)

        assert result.status == "BLOCKED"

    def test_checks_performed_and_passed_consistent(self) -> None:
        """checks_passed is always <= checks_performed."""
        report = _make_report()
        result = check_runner_health(report)
        assert result.checks_passed <= result.checks_performed


# ===========================================================================
# EVIDENCE_COMPLETENESS
# ===========================================================================


class TestEvidenceCompleteness:
    """Tests for check_evidence_completeness."""

    def test_happy_path_returns_passed(self) -> None:
        """Valid fixture returns EVIDENCE_COMPLETENESS PASSED with 4/4 checks."""
        report = _make_report()
        result = check_evidence_completeness(report)

        assert result.domain == "EVIDENCE_COMPLETENESS"
        assert result.status == "PASSED"
        assert result.checks_performed == 4
        assert result.checks_passed == 4
        assert result.failure_details == []

    def test_ec1_fails_when_total_executions_zero(self) -> None:
        """EC-1 fails when total_executions == 0."""
        report = _make_report()
        es = report.executive_summary
        report = report.model_copy(
            update={
                "executive_summary": ExecutiveSummary(
                    score_label=es.score_label,
                    composite_score_value=es.composite_score_value,
                    endpoint_count=es.endpoint_count,
                    audit_success_rate=es.audit_success_rate,
                    total_executions=0,
                    score_label_description=es.score_label_description,
                )
            }
        )
        result = check_evidence_completeness(report)

        assert result.status == "FAILED"
        assert any("EC-1" in d for d in result.failure_details)

    def test_ec2_fails_when_endpoint_has_zero_execution_count(self) -> None:
        """EC-2 fails when an endpoint has execution_count == 0."""
        report = _make_report()
        endpoints = list(report.endpoints)
        bad_metrics = _make_reliability_metrics(
            execution_count=0, pass_count=0, fail_count=0, success_rate=None
        )
        bad_ep = EndpointSection.model_construct(
            endpoint_id=endpoints[0].endpoint_id,
            reliability_metrics=bad_metrics,
            stability_analysis=endpoints[0].stability_analysis,
            burst_analysis=endpoints[0].burst_analysis,
            consistency_analysis=endpoints[0].consistency_analysis,
            endpoint_score=endpoints[0].endpoint_score,
        )
        endpoints[0] = bad_ep
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_evidence_completeness(report)

        assert result.status == "FAILED"
        assert any("EC-2" in d for d in result.failure_details)

    def test_ec3_fails_when_success_rate_is_none(self) -> None:
        """EC-3 fails when reliability_metrics.success_rate is None."""
        report = _make_report()
        endpoints = list(report.endpoints)
        bad_metrics = _make_reliability_metrics(success_rate=None)
        bad_ep = EndpointSection.model_construct(
            endpoint_id=endpoints[3].endpoint_id,
            reliability_metrics=bad_metrics,
            stability_analysis=endpoints[3].stability_analysis,
            burst_analysis=endpoints[3].burst_analysis,
            consistency_analysis=endpoints[3].consistency_analysis,
            endpoint_score=endpoints[3].endpoint_score,
        )
        endpoints[3] = bad_ep
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_evidence_completeness(report)

        assert result.status == "FAILED"
        assert any("EC-3" in d for d in result.failure_details)

    def test_ec4_fails_when_endpoint_count_zero(self) -> None:
        """EC-4 fails when executive_summary.endpoint_count == 0."""
        report = _make_report()
        es = report.executive_summary
        bad_es = ExecutiveSummary.model_construct(
            score_label=es.score_label,
            composite_score_value=es.composite_score_value,
            endpoint_count=0,
            audit_success_rate=es.audit_success_rate,
            total_executions=es.total_executions,
            score_label_description=es.score_label_description,
        )
        report = report.model_copy(update={"executive_summary": bad_es})

        result = check_evidence_completeness(report)

        assert result.status == "FAILED"
        assert any("EC-4" in d for d in result.failure_details)

    def test_blocked_when_executive_summary_is_none(self) -> None:
        """BLOCKED when executive_summary is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=None,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=base.endpoints,
            input_lineage=base.input_lineage,
            methodology_disclosure=base.methodology_disclosure,
        )
        result = check_evidence_completeness(report)

        assert result.status == "BLOCKED"
        assert result.checks_performed == 0

    def test_blocked_when_endpoints_is_none(self) -> None:
        """BLOCKED when endpoints is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=base.executive_summary,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=None,
            input_lineage=base.input_lineage,
            methodology_disclosure=base.methodology_disclosure,
        )
        result = check_evidence_completeness(report)

        assert result.status == "BLOCKED"


# ===========================================================================
# EVIDENCE_INTEGRITY
# ===========================================================================


class TestEvidenceIntegrity:
    """Tests for check_evidence_integrity."""

    def test_happy_path_returns_passed(self) -> None:
        """Valid fixture with matching report_metadata returns EVIDENCE_INTEGRITY PASSED."""
        report = _make_report()
        meta = _make_report_metadata()
        result = check_evidence_integrity(report, meta)

        assert result.domain == "EVIDENCE_INTEGRITY"
        assert result.status == "PASSED"
        assert result.checks_performed == 5
        assert result.checks_passed == 5
        assert result.failure_details == []

    def test_ei1_fails_when_aggregate_hash_mismatch(self) -> None:
        """EI-1 fails when aggregate_set_hash in artifact != ReportMetadata."""
        report = _make_report()
        meta = _make_report_metadata()
        meta["aggregate_set_hash"] = "00000000" * 8  # deliberately wrong

        result = check_evidence_integrity(report, meta)

        assert result.status == "FAILED"
        assert any("EI-1" in d for d in result.failure_details)

    def test_ei2_fails_when_report_id_mismatch(self) -> None:
        """EI-2 fails when identity.report_id != ReportMetadata.report_id."""
        report = _make_report()
        meta = _make_report_metadata()
        meta["report_id"] = "report_different_id"

        result = check_evidence_integrity(report, meta)

        assert result.status == "FAILED"
        assert any("EI-2" in d for d in result.failure_details)

    def test_ei3_fails_when_report_version_mismatch(self) -> None:
        """EI-3 fails when identity.report_version != ReportMetadata.report_version."""
        report = _make_report()
        meta = _make_report_metadata()
        meta["report_version"] = "report_v2"

        result = check_evidence_integrity(report, meta)

        assert result.status == "FAILED"
        assert any("EI-3" in d for d in result.failure_details)

    def test_ei4_fails_when_intelligence_version_mismatch(self) -> None:
        """EI-4 fails when intelligence_provenance.intelligence_version != ReportMetadata."""
        report = _make_report()
        meta = _make_report_metadata()
        meta["intelligence_version"] = "intel_v2"

        result = check_evidence_integrity(report, meta)

        assert result.status == "FAILED"
        assert any("EI-4" in d for d in result.failure_details)

    def test_ei5_fails_when_endpoint_count_mismatch(self) -> None:
        """EI-5 fails when ReportMetadata.endpoint_count != executive_summary.endpoint_count."""
        report = _make_report()
        meta = _make_report_metadata()
        meta["endpoint_count"] = 99  # deliberately wrong

        result = check_evidence_integrity(report, meta)

        assert result.status == "FAILED"
        assert any("EI-5" in d for d in result.failure_details)

    def test_blocked_when_report_metadata_missing_required_keys(self) -> None:
        """BLOCKED when report_metadata is missing required keys."""
        report = _make_report()
        result = check_evidence_integrity(report, {})  # empty metadata

        assert result.status == "BLOCKED"
        assert result.checks_performed == 0

    def test_blocked_when_identity_is_none(self) -> None:
        """BLOCKED when report.identity is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=None,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=base.executive_summary,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=base.endpoints,
            input_lineage=base.input_lineage,
            methodology_disclosure=base.methodology_disclosure,
        )
        result = check_evidence_integrity(report, _make_report_metadata())

        assert result.status == "BLOCKED"

    def test_checks_performed_is_five(self) -> None:
        """checks_performed is exactly 5 on a valid fixture."""
        report = _make_report()
        result = check_evidence_integrity(report, _make_report_metadata())
        assert result.checks_performed == 5


# ===========================================================================
# EVIDENCE_LINEAGE
# ===========================================================================


class TestEvidenceLineage:
    """Tests for check_evidence_lineage."""

    def test_happy_path_returns_passed(self) -> None:
        """Valid fixture returns EVIDENCE_LINEAGE PASSED with 5/5 checks."""
        report = _make_report()
        meta = _make_report_metadata()
        result = check_evidence_lineage(report, meta)

        assert result.domain == "EVIDENCE_LINEAGE"
        assert result.status == "PASSED"
        assert result.checks_performed == 5
        assert result.checks_passed == 5
        assert result.failure_details == []

    def test_el1_fails_when_artifact_hash_empty(self) -> None:
        """EL-1 fails when intelligence_provenance.aggregate_set_hash is empty string."""
        report = _make_report()
        ip = report.intelligence_provenance
        bad_ip = IntelligenceProvenance.model_construct(
            intelligence_version=ip.intelligence_version,
            intelligence_job_id=ip.intelligence_job_id,
            client_id=ip.client_id,
            audit_id=ip.audit_id,
            audit_execution_id=ip.audit_execution_id,
            config_version=ip.config_version,
            aggregation_version=ip.aggregation_version,
            aggregate_set_hash="",
            intelligence_completed_at=ip.intelligence_completed_at,
        )
        report = report.model_copy(update={"intelligence_provenance": bad_ip})

        result = check_evidence_lineage(report, _make_report_metadata())

        assert result.status == "FAILED"
        assert any("EL-1" in d for d in result.failure_details)

    def test_el2_fails_when_hash_mismatch(self) -> None:
        """EL-2 fails when aggregate_set_hash differs between artifact and ReportMetadata."""
        report = _make_report()
        meta = _make_report_metadata()
        meta["aggregate_set_hash"] = "ffffffff" * 8

        result = check_evidence_lineage(report, meta)

        assert result.status == "FAILED"
        assert any("EL-2" in d for d in result.failure_details)

    def test_el3_fails_when_intelligence_job_id_empty(self) -> None:
        """EL-3 fails when intelligence_job_id is empty string."""
        report = _make_report()
        ip = report.intelligence_provenance
        bad_ip = IntelligenceProvenance.model_construct(
            intelligence_version=ip.intelligence_version,
            intelligence_job_id="",
            client_id=ip.client_id,
            audit_id=ip.audit_id,
            audit_execution_id=ip.audit_execution_id,
            config_version=ip.config_version,
            aggregation_version=ip.aggregation_version,
            aggregate_set_hash=ip.aggregate_set_hash,
            intelligence_completed_at=ip.intelligence_completed_at,
        )
        report = report.model_copy(update={"intelligence_provenance": bad_ip})

        result = check_evidence_lineage(report, _make_report_metadata())

        assert result.status == "FAILED"
        assert any("EL-3" in d for d in result.failure_details)

    def test_el4_fails_when_input_lineage_field_is_null(self) -> None:
        """EL-4 fails when an input_lineage required field is None."""
        report = _make_report()
        bad_lineage = InputLineageSection.model_construct(
            aggregate_set_hash=_AGGREGATE_SET_HASH,
            aggregation_job_id=None,  # required field set to None
            aggregation_version=_AGG_VERSION,
            aggregate_set_completion_created_at="2026-07-05T11:00:00.000Z",
            endpoint_aggregate_count=len(_ENDPOINT_IDS),
            source_raw_result_count=_TOTAL_EXECUTIONS,
            audit_lineage_manifest_ref={},
        )
        report = report.model_copy(update={"input_lineage": bad_lineage})

        result = check_evidence_lineage(report, _make_report_metadata())

        assert result.status == "FAILED"
        assert any("EL-4" in d for d in result.failure_details)

    def test_el5_fails_when_timestamp_not_parseable(self) -> None:
        """EL-5 fails when intelligence_completed_at is not a valid UTC ISO-8601 timestamp."""
        report = _make_report()
        ip = report.intelligence_provenance
        bad_ip = IntelligenceProvenance.model_construct(
            intelligence_version=ip.intelligence_version,
            intelligence_job_id=ip.intelligence_job_id,
            client_id=ip.client_id,
            audit_id=ip.audit_id,
            audit_execution_id=ip.audit_execution_id,
            config_version=ip.config_version,
            aggregation_version=ip.aggregation_version,
            aggregate_set_hash=ip.aggregate_set_hash,
            intelligence_completed_at="not-a-valid-timestamp",
        )
        report = report.model_copy(update={"intelligence_provenance": bad_ip})

        result = check_evidence_lineage(report, _make_report_metadata())

        assert result.status == "FAILED"
        assert any("EL-5" in d for d in result.failure_details)

    def test_el5_fails_when_timestamp_has_no_timezone(self) -> None:
        """EL-5 fails when intelligence_completed_at has no timezone info (naive datetime)."""
        report = _make_report()
        ip = report.intelligence_provenance
        bad_ip = IntelligenceProvenance.model_construct(
            intelligence_version=ip.intelligence_version,
            intelligence_job_id=ip.intelligence_job_id,
            client_id=ip.client_id,
            audit_id=ip.audit_id,
            audit_execution_id=ip.audit_execution_id,
            config_version=ip.config_version,
            aggregation_version=ip.aggregation_version,
            aggregate_set_hash=ip.aggregate_set_hash,
            intelligence_completed_at="2026-07-05T12:00:00",  # no timezone
        )
        report = report.model_copy(update={"intelligence_provenance": bad_ip})

        result = check_evidence_lineage(report, _make_report_metadata())

        assert result.status == "FAILED"
        assert any("EL-5" in d for d in result.failure_details)

    def test_blocked_when_intelligence_provenance_is_none(self) -> None:
        """BLOCKED when intelligence_provenance is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=None,
            executive_summary=base.executive_summary,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=base.endpoints,
            input_lineage=base.input_lineage,
            methodology_disclosure=base.methodology_disclosure,
        )
        result = check_evidence_lineage(report, _make_report_metadata())

        assert result.status == "BLOCKED"
        assert result.checks_performed == 0

    def test_blocked_when_input_lineage_is_none(self) -> None:
        """BLOCKED when input_lineage is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=base.executive_summary,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=base.endpoints,
            input_lineage=None,
            methodology_disclosure=base.methodology_disclosure,
        )
        result = check_evidence_lineage(report, _make_report_metadata())

        assert result.status == "BLOCKED"

    def test_blocked_when_metadata_missing_aggregate_set_hash(self) -> None:
        """BLOCKED when report_metadata missing aggregate_set_hash key."""
        report = _make_report()
        result = check_evidence_lineage(report, {})

        assert result.status == "BLOCKED"


# ===========================================================================
# OBSERVATION_COVERAGE
# ===========================================================================


class TestObservationCoverage:
    """Tests for check_observation_coverage."""

    def test_happy_path_returns_passed(self) -> None:
        """Valid fixture returns OBSERVATION_COVERAGE PASSED with 5/5 checks."""
        report = _make_report()
        meta = _make_report_metadata()
        result = check_observation_coverage(report, meta)

        assert result.domain == "OBSERVATION_COVERAGE"
        assert result.status == "PASSED"
        assert result.checks_performed == 5
        assert result.checks_passed == 5
        assert result.failure_details == []

    def test_oc1_fails_when_endpoint_subsection_is_none(self) -> None:
        """OC-1 fails when an endpoint's stability_analysis is None."""
        report = _make_report()
        endpoints = list(report.endpoints)
        bad_ep = EndpointSection.model_construct(
            endpoint_id=endpoints[0].endpoint_id,
            reliability_metrics=endpoints[0].reliability_metrics,
            stability_analysis=None,  # absent sub-section
            burst_analysis=endpoints[0].burst_analysis,
            consistency_analysis=endpoints[0].consistency_analysis,
            endpoint_score=endpoints[0].endpoint_score,
        )
        endpoints[0] = bad_ep
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_observation_coverage(report, _make_report_metadata())

        assert result.status == "FAILED"
        assert any("OC-1" in d for d in result.failure_details)

    def test_oc2_fails_when_endpoint_count_mismatch_in_summary(self) -> None:
        """OC-2 fails when executive_summary.endpoint_count != len(endpoints)."""
        report = _make_report()
        es = report.executive_summary
        bad_es = ExecutiveSummary.model_construct(
            score_label=es.score_label,
            composite_score_value=es.composite_score_value,
            endpoint_count=99,  # does not match len(endpoints) = 5
            audit_success_rate=es.audit_success_rate,
            total_executions=es.total_executions,
            score_label_description=es.score_label_description,
        )
        report = report.model_copy(update={"executive_summary": bad_es})

        result = check_observation_coverage(report, _make_report_metadata())

        assert result.status == "FAILED"
        assert any("OC-2" in d for d in result.failure_details)

    def test_oc3_fails_when_metadata_endpoint_count_mismatch(self) -> None:
        """OC-3 fails when ReportMetadata.endpoint_count != len(endpoints)."""
        report = _make_report()
        meta = _make_report_metadata()
        meta["endpoint_count"] = 99

        result = check_observation_coverage(report, meta)

        assert result.status == "FAILED"
        assert any("OC-3" in d for d in result.failure_details)

    def test_oc4_fails_when_audit_success_rate_out_of_range(self) -> None:
        """OC-4 fails when audit_success_rate > 1.0."""
        report = _make_report()
        es = report.executive_summary
        bad_es = ExecutiveSummary.model_construct(
            score_label=es.score_label,
            composite_score_value=es.composite_score_value,
            endpoint_count=es.endpoint_count,
            audit_success_rate=1.5,  # > 1.0
            total_executions=es.total_executions,
            score_label_description=es.score_label_description,
        )
        report = report.model_copy(update={"executive_summary": bad_es})

        result = check_observation_coverage(report, _make_report_metadata())

        assert result.status == "FAILED"
        assert any("OC-4" in d for d in result.failure_details)

    def test_oc5_fails_when_total_executions_mismatch(self) -> None:
        """OC-5 fails when total_executions != sum of per-endpoint execution_counts."""
        report = _make_report()
        es = report.executive_summary
        bad_es = ExecutiveSummary.model_construct(
            score_label=es.score_label,
            composite_score_value=es.composite_score_value,
            endpoint_count=es.endpoint_count,
            audit_success_rate=es.audit_success_rate,
            total_executions=999,  # does not match 5 * 20 = 100
            score_label_description=es.score_label_description,
        )
        report = report.model_copy(update={"executive_summary": bad_es})

        result = check_observation_coverage(report, _make_report_metadata())

        assert result.status == "FAILED"
        assert any("OC-5" in d for d in result.failure_details)

    def test_blocked_when_endpoints_is_none(self) -> None:
        """BLOCKED when endpoints is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=base.executive_summary,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=None,
            input_lineage=base.input_lineage,
            methodology_disclosure=base.methodology_disclosure,
        )
        result = check_observation_coverage(report, _make_report_metadata())

        assert result.status == "BLOCKED"
        assert result.checks_performed == 0

    def test_blocked_when_metadata_missing_endpoint_count(self) -> None:
        """BLOCKED when report_metadata missing endpoint_count key."""
        report = _make_report()
        result = check_observation_coverage(report, {})

        assert result.status == "BLOCKED"


# ===========================================================================
# SCHEDULER_INTEGRITY
# ===========================================================================


class TestSchedulerIntegrity:
    """Tests for check_scheduler_integrity."""

    def test_happy_path_returns_passed(self) -> None:
        """Valid fixture returns SCHEDULER_INTEGRITY PASSED with 3/3 checks."""
        report = _make_report()
        result = check_scheduler_integrity(report)

        assert result.domain == "SCHEDULER_INTEGRITY"
        assert result.status == "PASSED"
        assert result.checks_performed == 3
        assert result.checks_passed == 3
        assert result.failure_details == []

    def test_si1_fails_when_total_executions_zero(self) -> None:
        """SI-1 fails when total_executions == 0."""
        report = _make_report()
        es = report.executive_summary
        bad_es = ExecutiveSummary.model_construct(
            score_label=es.score_label,
            composite_score_value=es.composite_score_value,
            endpoint_count=es.endpoint_count,
            audit_success_rate=es.audit_success_rate,
            total_executions=0,
            score_label_description=es.score_label_description,
        )
        report = report.model_copy(update={"executive_summary": bad_es})

        result = check_scheduler_integrity(report)

        assert result.status == "FAILED"
        assert any("SI-1" in d for d in result.failure_details)

    def test_si2_fails_when_execution_density_inconsistent(self) -> None:
        """SI-2 fails when an endpoint's execution_count is far from the mean."""
        report = _make_report()
        endpoints = list(report.endpoints)
        # Set one endpoint to 200 executions vs expected 20 — far outside [floor, ceil]
        bad_metrics = _make_reliability_metrics(execution_count=200, pass_count=200)
        bad_ep = EndpointSection.model_construct(
            endpoint_id=endpoints[0].endpoint_id,
            reliability_metrics=bad_metrics,
            stability_analysis=endpoints[0].stability_analysis,
            burst_analysis=endpoints[0].burst_analysis,
            consistency_analysis=endpoints[0].consistency_analysis,
            endpoint_score=endpoints[0].endpoint_score,
        )
        endpoints[0] = bad_ep
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_scheduler_integrity(report)

        assert result.status == "FAILED"
        assert any("SI-2" in d for d in result.failure_details)

    def test_si3_fails_when_limitations_is_none(self) -> None:
        """SI-3 fails when methodology_disclosure.limitations is None."""
        report = _make_report()
        md = report.methodology_disclosure
        bad_md = MethodologyDisclosure.model_construct(
            intelligence_version=md.intelligence_version,
            scoring=md.scoring,
            stability_label_definitions=md.stability_label_definitions,
            burst_label_definitions=md.burst_label_definitions,
            consistency_label_definitions=md.consistency_label_definitions,
            label_to_score_mapping=md.label_to_score_mapping,
            limitations=None,
        )
        report = report.model_copy(update={"methodology_disclosure": bad_md})

        result = check_scheduler_integrity(report)

        assert result.status == "FAILED"
        assert any("SI-3" in d for d in result.failure_details)

    def test_blocked_when_methodology_disclosure_is_none(self) -> None:
        """BLOCKED when methodology_disclosure is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=base.executive_summary,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=base.endpoints,
            input_lineage=base.input_lineage,
            methodology_disclosure=None,
        )
        result = check_scheduler_integrity(report)

        assert result.status == "BLOCKED"
        assert result.checks_performed == 0

    def test_blocked_when_executive_summary_is_none(self) -> None:
        """BLOCKED when executive_summary is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=None,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=base.endpoints,
            input_lineage=base.input_lineage,
            methodology_disclosure=base.methodology_disclosure,
        )
        result = check_scheduler_integrity(report)

        assert result.status == "BLOCKED"

    def test_checks_performed_is_three(self) -> None:
        """checks_performed is exactly 3 on a valid fixture."""
        report = _make_report()
        result = check_scheduler_integrity(report)
        assert result.checks_performed == 3


# ===========================================================================
# METHODOLOGY_COMPLIANCE
# ===========================================================================


class TestMethodologyCompliance:
    """Tests for check_methodology_compliance."""

    def test_happy_path_returns_passed(self) -> None:
        """Valid fixture returns METHODOLOGY_COMPLIANCE PASSED with 5/5 checks."""
        report = _make_report()
        result = check_methodology_compliance(report)

        assert result.domain == "METHODOLOGY_COMPLIANCE"
        assert result.status == "PASSED"
        assert result.checks_performed == 5
        assert result.checks_passed == 5
        assert result.failure_details == []

    def test_mc1_fails_when_intelligence_version_none(self) -> None:
        """MC-1 fails when methodology_disclosure.intelligence_version is None."""
        report = _make_report()
        md = report.methodology_disclosure
        bad_md = MethodologyDisclosure.model_construct(
            intelligence_version=None,
            scoring=md.scoring,
            stability_label_definitions=md.stability_label_definitions,
            burst_label_definitions=md.burst_label_definitions,
            consistency_label_definitions=md.consistency_label_definitions,
            label_to_score_mapping=md.label_to_score_mapping,
            limitations=md.limitations,
        )
        report = report.model_copy(update={"methodology_disclosure": bad_md})

        result = check_methodology_compliance(report)

        assert result.status == "FAILED"
        assert any("MC-1" in d for d in result.failure_details)

    def test_mc2_fails_when_scoring_is_none(self) -> None:
        """MC-2 fails when methodology_disclosure.scoring is None (with intelligence_version present)."""
        report = _make_report()
        md = report.methodology_disclosure
        bad_md = MethodologyDisclosure.model_construct(
            intelligence_version=md.intelligence_version,  # MC-1 still passes
            scoring=None,  # MC-2 fails
            stability_label_definitions=md.stability_label_definitions,
            burst_label_definitions=md.burst_label_definitions,
            consistency_label_definitions=md.consistency_label_definitions,
            label_to_score_mapping=md.label_to_score_mapping,
            limitations=md.limitations,
        )
        report = report.model_copy(update={"methodology_disclosure": bad_md})

        result = check_methodology_compliance(report)

        assert result.status == "FAILED"
        assert any("MC-2" in d for d in result.failure_details)

    def test_mc3_fails_when_limitations_is_none(self) -> None:
        """MC-3 fails when methodology_disclosure.limitations is None."""
        report = _make_report()
        md = report.methodology_disclosure
        bad_md = MethodologyDisclosure.model_construct(
            intelligence_version=md.intelligence_version,
            scoring=md.scoring,
            stability_label_definitions=md.stability_label_definitions,
            burst_label_definitions=md.burst_label_definitions,
            consistency_label_definitions=md.consistency_label_definitions,
            label_to_score_mapping=md.label_to_score_mapping,
            limitations=None,
        )
        report = report.model_copy(update={"methodology_disclosure": bad_md})

        result = check_methodology_compliance(report)

        assert result.status == "FAILED"
        assert any("MC-3" in d for d in result.failure_details)

    def test_mc3_passes_when_limitations_is_empty_list(self) -> None:
        """MC-3 passes when limitations is an empty list (not absent)."""
        report = _make_report()
        # Base fixture already has limitations=[] — should pass
        result = check_methodology_compliance(report)

        assert result.status == "PASSED"

    def test_mc4_fails_when_burst_methodology_trace_is_none(self) -> None:
        """MC-4 fails when an endpoint's burst_analysis.methodology_trace is None."""
        report = _make_report()
        endpoints = list(report.endpoints)
        bad_burst = BurstAnalysis.model_construct(
            failure_burst_label="NO_BURST_DETECTED",
            latency_spike_label="NO_SPIKE_DETECTED",
            methodology_trace=None,
        )
        bad_ep = EndpointSection.model_construct(
            endpoint_id=endpoints[4].endpoint_id,
            reliability_metrics=endpoints[4].reliability_metrics,
            stability_analysis=endpoints[4].stability_analysis,
            burst_analysis=bad_burst,
            consistency_analysis=endpoints[4].consistency_analysis,
            endpoint_score=endpoints[4].endpoint_score,
        )
        endpoints[4] = bad_ep
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_methodology_compliance(report)

        assert result.status == "FAILED"
        assert any("MC-4" in d for d in result.failure_details)

    def test_mc5_fails_when_score_derivation_is_none(self) -> None:
        """MC-5 fails when endpoint_score.score_derivation is None."""
        report = _make_report()
        endpoints = list(report.endpoints)
        bad_score = EndpointScore.model_construct(
            composite_score=1.000,
            reliability_score=1.000,
            stability_score=1.000,
            burst_score=1.000,
            consistency_score=1.000,
            score_derivation=None,
        )
        bad_ep = EndpointSection.model_construct(
            endpoint_id=endpoints[2].endpoint_id,
            reliability_metrics=endpoints[2].reliability_metrics,
            stability_analysis=endpoints[2].stability_analysis,
            burst_analysis=endpoints[2].burst_analysis,
            consistency_analysis=endpoints[2].consistency_analysis,
            endpoint_score=bad_score,
        )
        endpoints[2] = bad_ep
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_methodology_compliance(report)

        assert result.status == "FAILED"
        assert any("MC-5" in d for d in result.failure_details)

    def test_blocked_when_methodology_disclosure_is_none(self) -> None:
        """BLOCKED when methodology_disclosure is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=base.executive_summary,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=base.endpoints,
            input_lineage=base.input_lineage,
            methodology_disclosure=None,
        )
        result = check_methodology_compliance(report)

        assert result.status == "BLOCKED"
        assert result.checks_performed == 0

    def test_blocked_when_endpoints_is_none(self) -> None:
        """BLOCKED when endpoints is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=base.executive_summary,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=None,
            input_lineage=base.input_lineage,
            methodology_disclosure=base.methodology_disclosure,
        )
        result = check_methodology_compliance(report)

        assert result.status == "BLOCKED"


# ===========================================================================
# REPORT_INTEGRITY
# ===========================================================================


class TestReportIntegrity:
    """Tests for check_report_integrity."""

    def test_happy_path_returns_passed(self) -> None:
        """Valid fixture returns REPORT_INTEGRITY PASSED with 9/9 checks."""
        report = _make_report()
        result = check_report_integrity(report)

        assert result.domain == "REPORT_INTEGRITY"
        assert result.status == "PASSED"
        assert result.checks_performed == 9
        assert result.checks_passed == 9
        assert result.failure_details == []

    def test_ri1_fails_when_report_version_wrong(self) -> None:
        """RI-1 fails when identity.report_version != 'report_v1'."""
        report = _make_report()
        bad_identity = ReportIdentity.model_construct(
            report_id=report.identity.report_id,
            report_version="report_v2",
            generated_at=report.identity.generated_at,
            generator_version=report.identity.generator_version,
        )
        report = report.model_copy(update={"identity": bad_identity})

        result = check_report_integrity(report)

        assert result.status == "FAILED"
        assert any("RI-1" in d for d in result.failure_details)

    def test_ri2_fails_when_intelligence_version_wrong(self) -> None:
        """RI-2 fails when intelligence_provenance.intelligence_version != 'intel_v1'."""
        report = _make_report()
        ip = report.intelligence_provenance
        bad_ip = IntelligenceProvenance.model_construct(
            intelligence_version="intel_v2",
            intelligence_job_id=ip.intelligence_job_id,
            client_id=ip.client_id,
            audit_id=ip.audit_id,
            audit_execution_id=ip.audit_execution_id,
            config_version=ip.config_version,
            aggregation_version=ip.aggregation_version,
            aggregate_set_hash=ip.aggregate_set_hash,
            intelligence_completed_at=ip.intelligence_completed_at,
        )
        report = report.model_copy(update={"intelligence_provenance": bad_ip})

        result = check_report_integrity(report)

        assert result.status == "FAILED"
        assert any("RI-2" in d for d in result.failure_details)

    def test_ri3_fails_when_score_label_invalid(self) -> None:
        """RI-3 fails when score_label is not in the bounded set."""
        report = _make_report()
        es = report.executive_summary
        bad_es = ExecutiveSummary.model_construct(
            score_label="UNKNOWN_LABEL",
            composite_score_value=es.composite_score_value,
            endpoint_count=es.endpoint_count,
            audit_success_rate=es.audit_success_rate,
            total_executions=es.total_executions,
            score_label_description=es.score_label_description,
        )
        report = report.model_copy(update={"executive_summary": bad_es})

        result = check_report_integrity(report)

        assert result.status == "FAILED"
        assert any("RI-3" in d for d in result.failure_details)

    def test_ri4_fails_when_composite_score_out_of_range(self) -> None:
        """RI-4 fails when composite_score_value > 1.0."""
        report = _make_report()
        es = report.executive_summary
        bad_es = ExecutiveSummary.model_construct(
            score_label=es.score_label,
            composite_score_value=1.5,  # > 1.0
            endpoint_count=es.endpoint_count,
            audit_success_rate=es.audit_success_rate,
            total_executions=es.total_executions,
            score_label_description=es.score_label_description,
        )
        report = report.model_copy(update={"executive_summary": bad_es})

        result = check_report_integrity(report)

        assert result.status == "FAILED"
        assert any("RI-4" in d for d in result.failure_details)

    def test_ri5_fails_when_endpoints_not_sorted(self) -> None:
        """RI-5 fails when endpoints[] is not sorted by endpoint_id."""
        report = _make_report()
        endpoints = list(report.endpoints)
        # Swap first two to break sort order
        endpoints[0], endpoints[1] = endpoints[1], endpoints[0]
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_report_integrity(report)

        assert result.status == "FAILED"
        assert any("RI-5" in d for d in result.failure_details)

    def test_ri6_fails_when_duplicate_endpoint_ids(self) -> None:
        """RI-6 fails when duplicate endpoint_id values exist."""
        report = _make_report()
        endpoints = list(report.endpoints)
        # Make endpoint_1 appear twice
        dup = EndpointSection.model_construct(
            endpoint_id="endpoint_1",  # duplicate
            reliability_metrics=endpoints[4].reliability_metrics,
            stability_analysis=endpoints[4].stability_analysis,
            burst_analysis=endpoints[4].burst_analysis,
            consistency_analysis=endpoints[4].consistency_analysis,
            endpoint_score=endpoints[4].endpoint_score,
        )
        endpoints[4] = dup
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_report_integrity(report)

        assert result.status == "FAILED"
        assert any("RI-6" in d for d in result.failure_details)

    def test_ri7_fails_when_endpoint_id_is_empty(self) -> None:
        """RI-7 fails when an endpoint_id is empty string."""
        report = _make_report()
        endpoints = list(report.endpoints)
        bad_ep = EndpointSection.model_construct(
            endpoint_id="",  # empty
            reliability_metrics=endpoints[0].reliability_metrics,
            stability_analysis=endpoints[0].stability_analysis,
            burst_analysis=endpoints[0].burst_analysis,
            consistency_analysis=endpoints[0].consistency_analysis,
            endpoint_score=endpoints[0].endpoint_score,
        )
        endpoints[0] = bad_ep
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_report_integrity(report)

        assert result.status == "FAILED"
        assert any("RI-7" in d for d in result.failure_details)

    def test_ri8_fails_when_endpoint_score_field_out_of_range(self) -> None:
        """RI-8 fails when an endpoint score field is > 1.0."""
        report = _make_report()
        endpoints = list(report.endpoints)
        bad_score = EndpointScore.model_construct(
            composite_score=1.5,  # > 1.0
            reliability_score=1.000,
            stability_score=1.000,
            burst_score=1.000,
            consistency_score=1.000,
            score_derivation=_make_score_derivation(),
        )
        bad_ep = EndpointSection.model_construct(
            endpoint_id=endpoints[2].endpoint_id,
            reliability_metrics=endpoints[2].reliability_metrics,
            stability_analysis=endpoints[2].stability_analysis,
            burst_analysis=endpoints[2].burst_analysis,
            consistency_analysis=endpoints[2].consistency_analysis,
            endpoint_score=bad_score,
        )
        endpoints[2] = bad_ep
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_report_integrity(report)

        assert result.status == "FAILED"
        assert any("RI-8" in d for d in result.failure_details)

    def test_ri9_fails_when_score_label_description_invalid(self) -> None:
        """RI-9 fails when score_label_description is not in the bounded value set."""
        report = _make_report()
        es = report.executive_summary
        bad_es = ExecutiveSummary.model_construct(
            score_label=es.score_label,
            composite_score_value=es.composite_score_value,
            endpoint_count=es.endpoint_count,
            audit_success_rate=es.audit_success_rate,
            total_executions=es.total_executions,
            score_label_description="This description is not in the bounded set.",
        )
        report = report.model_copy(update={"executive_summary": bad_es})

        result = check_report_integrity(report)

        assert result.status == "FAILED"
        assert any("RI-9" in d for d in result.failure_details)

    def test_blocked_when_identity_is_none(self) -> None:
        """BLOCKED when identity is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=None,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=base.executive_summary,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=base.endpoints,
            input_lineage=base.input_lineage,
            methodology_disclosure=base.methodology_disclosure,
        )
        result = check_report_integrity(report)

        assert result.status == "BLOCKED"
        assert result.checks_performed == 0

    def test_blocked_when_executive_summary_is_none(self) -> None:
        """BLOCKED when executive_summary is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=None,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=base.endpoints,
            input_lineage=base.input_lineage,
            methodology_disclosure=base.methodology_disclosure,
        )
        result = check_report_integrity(report)

        assert result.status == "BLOCKED"

    def test_blocked_when_endpoints_is_none(self) -> None:
        """BLOCKED when endpoints is None."""
        base = _make_report()
        report = ReleaseConfidenceReport.model_construct(
            identity=base.identity,
            intelligence_provenance=base.intelligence_provenance,
            executive_summary=base.executive_summary,
            audit_reliability_overview=base.audit_reliability_overview,
            composite_score=base.composite_score,
            endpoints=None,
            input_lineage=base.input_lineage,
            methodology_disclosure=base.methodology_disclosure,
        )
        result = check_report_integrity(report)

        assert result.status == "BLOCKED"

    def test_checks_performed_is_nine(self) -> None:
        """checks_performed is exactly 9 on a valid fixture."""
        report = _make_report()
        result = check_report_integrity(report)
        assert result.checks_performed == 9


# ===========================================================================
# Cross-domain invariants
# ===========================================================================


class TestCrossDomainInvariants:
    """Cross-domain invariant tests."""

    def test_all_eight_domains_pass_on_base_fixture(self) -> None:
        """The base fixture passes all 8 domain checks."""
        report = _make_report()
        meta = _make_report_metadata()

        results = [
            check_runner_health(report),
            check_evidence_completeness(report),
            check_evidence_integrity(report, meta),
            check_evidence_lineage(report, meta),
            check_observation_coverage(report, meta),
            check_scheduler_integrity(report),
            check_methodology_compliance(report),
            check_report_integrity(report),
        ]

        for result in results:
            assert result.status == "PASSED", (
                f"Domain {result.domain} expected PASSED but got {result.status}: "
                f"{result.failure_details}"
            )

    def test_all_domains_return_correct_domain_identifier(self) -> None:
        """Each domain function returns the correct domain identifier."""
        report = _make_report()
        meta = _make_report_metadata()

        expected_pairs = [
            ("RUNNER_HEALTH", check_runner_health(report)),
            ("EVIDENCE_COMPLETENESS", check_evidence_completeness(report)),
            ("EVIDENCE_INTEGRITY", check_evidence_integrity(report, meta)),
            ("EVIDENCE_LINEAGE", check_evidence_lineage(report, meta)),
            ("OBSERVATION_COVERAGE", check_observation_coverage(report, meta)),
            ("SCHEDULER_INTEGRITY", check_scheduler_integrity(report)),
            ("METHODOLOGY_COMPLIANCE", check_methodology_compliance(report)),
            ("REPORT_INTEGRITY", check_report_integrity(report)),
        ]

        for expected_domain, result in expected_pairs:
            assert result.domain == expected_domain

    def test_blocked_domains_have_zero_checks_performed(self) -> None:
        """BLOCKED results always have checks_performed == 0."""
        base = _make_report()
        blocked_report = ReleaseConfidenceReport.model_construct(
            identity=None,
            intelligence_provenance=None,
            executive_summary=None,
            audit_reliability_overview=None,
            composite_score=None,
            endpoints=None,
            input_lineage=None,
            methodology_disclosure=None,
        )

        results = [
            check_runner_health(blocked_report),
            check_evidence_completeness(blocked_report),
            check_scheduler_integrity(blocked_report),
            check_methodology_compliance(blocked_report),
            check_report_integrity(blocked_report),
        ]

        for result in results:
            assert result.status == "BLOCKED"
            assert result.checks_performed == 0
            assert result.checks_passed == 0

    def test_failure_details_non_empty_when_failed(self) -> None:
        """Any FAILED result has non-empty failure_details."""
        report = _make_report()
        # Inject a failure: swap endpoint order to fail RI-5
        endpoints = list(report.endpoints)
        endpoints[0], endpoints[1] = endpoints[1], endpoints[0]
        report = report.model_copy(update={"endpoints": endpoints})

        result = check_report_integrity(report)

        assert result.status == "FAILED"
        assert len(result.failure_details) > 0

    def test_evidence_refs_non_empty_for_all_domains(self) -> None:
        """evidence_refs is non-empty for all domain results."""
        report = _make_report()
        meta = _make_report_metadata()

        results = [
            check_runner_health(report),
            check_evidence_completeness(report),
            check_evidence_integrity(report, meta),
            check_evidence_lineage(report, meta),
            check_observation_coverage(report, meta),
            check_scheduler_integrity(report),
            check_methodology_compliance(report),
            check_report_integrity(report),
        ]

        for result in results:
            assert len(result.evidence_refs) > 0, (
                f"Domain {result.domain} has empty evidence_refs"
            )

    def test_checks_passed_le_checks_performed_for_all_domains(self) -> None:
        """checks_passed <= checks_performed invariant holds across all domains."""
        report = _make_report()
        meta = _make_report_metadata()

        results = [
            check_runner_health(report),
            check_evidence_completeness(report),
            check_evidence_integrity(report, meta),
            check_evidence_lineage(report, meta),
            check_observation_coverage(report, meta),
            check_scheduler_integrity(report),
            check_methodology_compliance(report),
            check_report_integrity(report),
        ]

        for result in results:
            assert result.checks_passed <= result.checks_performed, (
                f"Domain {result.domain}: checks_passed ({result.checks_passed}) > "
                f"checks_performed ({result.checks_performed})"
            )
