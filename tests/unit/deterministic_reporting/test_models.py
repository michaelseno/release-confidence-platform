"""Unit tests for Phase 6 Canonical Report DTO schema validation (Phase 6.2).

Covers QA test plan Section 4.1 test cases:
  MOD-01  Valid complete DTO constructs without error
  MOD-02  Missing report_id raises ValidationError
  MOD-03  Missing methodology_disclosure raises ValidationError
  MOD-04  Missing endpoints raises ValidationError
  MOD-05  composite_score_value out of range raises ValidationError
  MOD-06  score_label not in bounded set raises ValidationError
  MOD-07  report_version not report_v1 raises ValidationError
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from release_confidence_platform.deterministic_reporting.constants import (
    SCORE_LABEL_BOUNDED_SET,
    SCORE_LABEL_DESCRIPTIONS,
)
from release_confidence_platform.deterministic_reporting.models import ReleaseConfidenceReport


# ---------------------------------------------------------------------------
# Minimal valid fixture builder
# ---------------------------------------------------------------------------


def _base_report_data() -> dict[str, Any]:
    """Return a minimal dict that satisfies all required fields of ReleaseConfidenceReport."""
    return {
        "identity": {
            "report_id": "report_abc1234567890abcdef1234567890ab",
            "report_version": "report_v1",
            "generated_at": "2026-07-04T00:00:00.000Z",
            "generator_version": "0.0.0",
        },
        "intelligence_provenance": {
            "intelligence_version": "intel_v1",
            "intelligence_job_id": "intjob_abc1234567890abcdef1234567890ab",
            "client_id": "client_test",
            "audit_id": "audit_test",
            "audit_execution_id": "audexec_test",
            "config_version": "v1",
            "aggregation_version": "agg_v1",
            "aggregate_set_hash": "deadbeef" * 8,
            "intelligence_completed_at": "2026-07-04T00:00:00.000Z",
        },
        "executive_summary": {
            "score_label": "HIGH_CONFIDENCE",
            "composite_score_value": 0.900,
            "endpoint_count": 1,
            "audit_success_rate": 0.950,
            "total_executions": 20,
            "score_label_description": SCORE_LABEL_DESCRIPTIONS["HIGH_CONFIDENCE"],
        },
        "audit_reliability_overview": {
            "total_executions": 20,
            "total_pass": 19,
            "total_fail": 1,
            "total_timeout": 0,
            "total_network_failure": 0,
            "audit_success_rate": 0.950,
            "endpoint_count": 1,
            "source_field_refs": {"total_executions": "audit_aggregate.request_counts.total"},
        },
        "composite_score": {
            "value": 0.900,
            "score_label": "HIGH_CONFIDENCE",
            "intelligence_version": "intel_v1",
            "aggregation_version": "agg_v1",
            "aggregate_set_hash": "deadbeef" * 8,
            "endpoint_count": 1,
            "component_breakdown": {
                "reliability": {
                    "weight": 0.50,
                    "value": 0.950,
                    "description": "Unweighted mean of per-endpoint success rates",
                },
                "stability": {
                    "weight": 0.20,
                    "value": 1.0,
                    "description": "Mean of per-endpoint stability scores",
                },
                "burst": {
                    "weight": 0.15,
                    "value": 1.0,
                    "description": "Mean of per-endpoint burst scores",
                },
                "consistency": {
                    "weight": 0.15,
                    "value": 1.0,
                    "description": "Mean of per-endpoint consistency scores",
                },
            },
        },
        "endpoints": [
            {
                "endpoint_id": "ep_test",
                "reliability_metrics": {
                    "execution_count": 20,
                    "pass_count": 19,
                    "fail_count": 1,
                    "timeout_count": 0,
                    "success_rate": 0.950,
                    "success_rate_numerator": 19,
                    "success_rate_denominator": 20,
                    "latency_count": 20,
                    "failure_classification_breakdown": {"PASS": 19, "HTTP_ERROR": 1},
                    "http_response_distribution": {"200": 19, "500": 1},
                    "source_field_refs": {"execution_count": "endpoint_aggregate.execution_count"},
                },
                "stability_analysis": {
                    "success_rate_stability_label": "STABLE",
                    "latency_stability_label": "STABLE",
                    "methodology_trace": {
                        "algorithm": "success_rate_stability_v1",
                        "algorithm_version": "1",
                        "inputs": {},
                        "thresholds": {},
                        "intermediate_values": {},
                        "label_determination": "threshold met",
                    },
                },
                "burst_analysis": {
                    "failure_burst_label": "NO_BURST_DETECTED",
                    "latency_spike_label": "NO_SPIKE_DETECTED",
                    "methodology_trace": {
                        "algorithm": "failure_burst_v1",
                        "algorithm_version": "1",
                        "inputs": {},
                        "thresholds": {},
                        "intermediate_values": {},
                        "label_determination": "below threshold",
                    },
                },
                "consistency_analysis": {
                    "consistency_label": "CONSISTENT",
                    "methodology_trace": {
                        "algorithm": "outcome_consistency_v1",
                        "algorithm_version": "1",
                        "inputs": {},
                        "thresholds": {},
                        "intermediate_values": {},
                        "label_determination": "variance at or below threshold",
                    },
                },
                "endpoint_score": {
                    "composite_score": 0.925,
                    "reliability_score": 0.950,
                    "stability_score": 1.0,
                    "burst_score": 1.0,
                    "consistency_score": 1.0,
                    "score_derivation": {
                        "reliability_score_source": "success_rate",
                        "stability_score_formula": "mean(label_scores)",
                        "burst_score_formula": "mean(label_scores)",
                        "consistency_score_formula": "label_score",
                        "composite_score_formula": "weighted_sum",
                    },
                },
            }
        ],
        "input_lineage": {
            "aggregate_set_hash": "deadbeef" * 8,
            "aggregation_job_id": "aggjob_test",
            "aggregation_version": "agg_v1",
            "aggregate_set_completion_created_at": "2026-07-04T00:00:00.000Z",
            "endpoint_aggregate_count": 1,
            "source_raw_result_count": 20,
            "audit_lineage_manifest_ref": {
                "manifest_scope": "audit",
                "source_ref_count": 20,
                "manifest_hash": "aabbccdd" * 8,
            },
        },
        "methodology_disclosure": {
            "intelligence_version": "intel_v1",
            "scoring": {
                "composite_score_range": "[0.0, 1.0]",
                "rollup": "Unweighted arithmetic mean of per-endpoint composite scores",
                "precision": "3 decimal places, half-up rounding via Python Decimal",
                "component_weights": {
                    "reliability": 0.50,
                    "stability": 0.20,
                    "burst": 0.15,
                    "consistency": 0.15,
                },
                "per_endpoint_formula": (
                    "reliability*0.50 + stability*0.20 + burst*0.15 + consistency*0.15"
                ),
            },
            "stability_label_definitions": {
                "STABLE": "Distributional indicators consistent with stable behavior",
                "DEGRADED": "Distributional indicators inconsistent with stable behavior",
                "INSUFFICIENT_DATA": "Below minimum threshold for characterization",
            },
            "burst_label_definitions": {
                "NO_BURST_DETECTED": "Timeout proportion does not exceed burst threshold",
                "BURST_SUSPECTED": "Timeout proportion consistent with concentrated outage",
                "INSUFFICIENT_DATA": "Below minimum threshold for burst characterization",
            },
            "consistency_label_definitions": {
                "CONSISTENT": "Bernoulli variance at or below 0.05",
                "INCONSISTENT": "Bernoulli variance exceeds 0.05",
                "INSUFFICIENT_DATA": "Below minimum threshold for consistency estimation",
            },
            "label_to_score_mapping": {
                "STABLE": 1.0,
                "DEGRADED": 0.0,
                "INSUFFICIENT_DATA": 0.5,
                "CONSISTENT": 1.0,
                "INCONSISTENT": 0.0,
                "NO_BURST_DETECTED": 1.0,
                "BURST_SUSPECTED": 0.0,
                "NO_SPIKE_DETECTED": 1.0,
                "SPIKE_SUSPECTED": 0.0,
            },
            "limitations": [
                "Minimum 10 executions required per endpoint for characterization.",
                "Minimum 5 latency measurements required for latency analysis.",
            ],
        },
    }


# ---------------------------------------------------------------------------
# MOD-01: Valid complete DTO constructs without error
# ---------------------------------------------------------------------------


def test_mod_01_valid_complete_dto_constructs_without_error() -> None:
    """MOD-01: A complete, valid fixture produces a ReleaseConfidenceReport without error."""
    data = _base_report_data()
    report = ReleaseConfidenceReport(**data)

    assert report.identity.report_version == "report_v1"
    assert report.identity.report_id == "report_abc1234567890abcdef1234567890ab"
    assert report.executive_summary.score_label == "HIGH_CONFIDENCE"
    assert report.executive_summary.composite_score_value == 0.900
    assert report.intelligence_provenance.intelligence_version == "intel_v1"
    assert len(report.endpoints) == 1
    assert report.endpoints[0].endpoint_id == "ep_test"
    assert report.methodology_disclosure.intelligence_version == "intel_v1"
    assert isinstance(report.methodology_disclosure.limitations, list)
    assert len(report.methodology_disclosure.limitations) > 0


# ---------------------------------------------------------------------------
# MOD-02: Missing report_id raises ValidationError
# ---------------------------------------------------------------------------


def test_mod_02_missing_report_id_raises_validation_error() -> None:
    """MOD-02: Omitting report_id from identity raises ValidationError."""
    data = _base_report_data()
    del data["identity"]["report_id"]
    with pytest.raises(ValidationError):
        ReleaseConfidenceReport(**data)


# ---------------------------------------------------------------------------
# MOD-03: Missing methodology_disclosure raises ValidationError
# ---------------------------------------------------------------------------


def test_mod_03_missing_methodology_disclosure_raises_validation_error() -> None:
    """MOD-03: Omitting methodology_disclosure entirely raises ValidationError."""
    data = _base_report_data()
    del data["methodology_disclosure"]
    with pytest.raises(ValidationError):
        ReleaseConfidenceReport(**data)


# ---------------------------------------------------------------------------
# MOD-04: Missing endpoints raises ValidationError
# ---------------------------------------------------------------------------


def test_mod_04_missing_endpoints_raises_validation_error() -> None:
    """MOD-04: Omitting endpoints raises ValidationError."""
    data = _base_report_data()
    del data["endpoints"]
    with pytest.raises(ValidationError):
        ReleaseConfidenceReport(**data)


# ---------------------------------------------------------------------------
# MOD-05: composite_score_value out of range raises ValidationError
# ---------------------------------------------------------------------------


def test_mod_05a_composite_score_value_above_one_raises_validation_error() -> None:
    """MOD-05a: composite_score_value > 1.0 raises ValidationError."""
    data = _base_report_data()
    data["executive_summary"]["composite_score_value"] = 1.001
    with pytest.raises(ValidationError):
        ReleaseConfidenceReport(**data)


def test_mod_05b_composite_score_value_below_zero_raises_validation_error() -> None:
    """MOD-05b: composite_score_value < 0.0 raises ValidationError."""
    data = _base_report_data()
    data["executive_summary"]["composite_score_value"] = -0.001
    with pytest.raises(ValidationError):
        ReleaseConfidenceReport(**data)


def test_mod_05c_composite_score_value_at_boundaries_accepted() -> None:
    """MOD-05c: composite_score_value at exactly 0.0 and 1.0 are accepted (inclusive bounds)."""
    for boundary in (0.0, 1.0):
        data = _base_report_data()
        data["executive_summary"]["composite_score_value"] = boundary
        data["executive_summary"]["score_label"] = (
            "HIGH_CONFIDENCE" if boundary == 1.0 else "LOW_CONFIDENCE"
        )
        report = ReleaseConfidenceReport(**data)
        assert report.executive_summary.composite_score_value == boundary


# ---------------------------------------------------------------------------
# MOD-06: score_label not in bounded set raises ValidationError
# ---------------------------------------------------------------------------


def test_mod_06_score_label_invalid_raises_validation_error() -> None:
    """MOD-06: score_label value outside the bounded set raises ValidationError."""
    data = _base_report_data()
    data["executive_summary"]["score_label"] = "INVALID_LABEL"
    with pytest.raises(ValidationError):
        ReleaseConfidenceReport(**data)


def test_mod_06b_all_valid_score_labels_accepted() -> None:
    """MOD-06b: All three valid score_label values are accepted by the validator."""
    for label in SCORE_LABEL_BOUNDED_SET:
        data = _base_report_data()
        data["executive_summary"]["score_label"] = label
        report = ReleaseConfidenceReport(**data)
        assert report.executive_summary.score_label == label


# ---------------------------------------------------------------------------
# MOD-07: report_version not report_v1 raises ValidationError
# ---------------------------------------------------------------------------


def test_mod_07_report_version_invalid_raises_validation_error() -> None:
    """MOD-07: report_version != 'report_v1' raises ValidationError."""
    data = _base_report_data()
    data["identity"]["report_version"] = "report_v2"
    with pytest.raises(ValidationError):
        ReleaseConfidenceReport(**data)


def test_mod_07b_report_version_report_v1_accepted() -> None:
    """MOD-07b: report_version = 'report_v1' is accepted."""
    data = _base_report_data()
    data["identity"]["report_version"] = "report_v1"
    report = ReleaseConfidenceReport(**data)
    assert report.identity.report_version == "report_v1"


# ---------------------------------------------------------------------------
# Additional: missing other required top-level fields
# ---------------------------------------------------------------------------


def test_missing_identity_raises_validation_error() -> None:
    """Omitting top-level identity field raises ValidationError."""
    data = _base_report_data()
    del data["identity"]
    with pytest.raises(ValidationError):
        ReleaseConfidenceReport(**data)


def test_missing_intelligence_provenance_raises_validation_error() -> None:
    """Omitting top-level intelligence_provenance raises ValidationError."""
    data = _base_report_data()
    del data["intelligence_provenance"]
    with pytest.raises(ValidationError):
        ReleaseConfidenceReport(**data)


def test_missing_executive_summary_raises_validation_error() -> None:
    """Omitting top-level executive_summary raises ValidationError."""
    data = _base_report_data()
    del data["executive_summary"]
    with pytest.raises(ValidationError):
        ReleaseConfidenceReport(**data)


def test_missing_input_lineage_raises_validation_error() -> None:
    """Omitting top-level input_lineage raises ValidationError."""
    data = _base_report_data()
    del data["input_lineage"]
    with pytest.raises(ValidationError):
        ReleaseConfidenceReport(**data)
