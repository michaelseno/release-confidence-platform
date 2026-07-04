"""Test: MarkdownFormatter.render() correctness and purity.

Verifies that the formatter renders all eight report sections verbatim from the
ReleaseConfidenceReport DTO, handles nullable fields correctly, and is
deterministic across repeated calls.
"""
from __future__ import annotations

from release_confidence_platform.deterministic_reporting.builder import ReportBuilder
from release_confidence_platform.deterministic_reporting.constants import (
    REPORT_VERSION,
    SCORE_LABEL_DESCRIPTIONS,
)
from release_confidence_platform.deterministic_reporting.formatters.markdown import (
    MarkdownFormatter,
)

# ---------------------------------------------------------------------------
# Phase 5 artifact fixture — two endpoints (ep_alpha has latency, ep_beta does not)
# ---------------------------------------------------------------------------

_PHASE5_ARTIFACT: dict = {
    "intelligence_version": "intel_v1",
    "aggregation_version": "agg_v1",
    "client_id": "client_test",
    "audit_id": "audit_test",
    "audit_execution_id": "exec_test",
    "config_version": "cfg_v1",
    "intelligence_job_id": "intjob_test001",
    "generated_at": "2026-07-04T10:00:00Z",
    "generator_version": "1.0.0",
    "input_lineage": {
        "aggregate_set_hash": "hash_test_abc",
        "aggregation_job_id": "aggjob_test002",
        "aggregation_version": "agg_v1",
        "aggregate_set_completion_created_at": "2026-07-04T09:00:00Z",
        "endpoint_aggregate_count": 2,
        "source_raw_result_count": 40,
        "audit_lineage_manifest_ref": {"s3_key": "lineage/test"},
    },
    "audit_reliability_summary": {
        "total_executions": 40,
        "total_pass": 36,
        "total_fail": 3,
        "total_timeout": 1,
        "total_network_failure": 0,
        "audit_success_rate": "0.900",
        "endpoint_count": 2,
        "audit_latency_mean_ms": 120.0,
        "audit_latency_p95_ms": 400.0,
        "audit_latency_p99_ms": 480.0,
        "source_field_refs": {"total_executions": "AuditAggregate.request_counts.total"},
    },
    "composite_score": {
        "value": "0.850",
        "score_label": "HIGH_CONFIDENCE",
        "intelligence_version": "intel_v1",
        "aggregation_version": "agg_v1",
        "aggregate_set_hash": "hash_test_abc",
        "endpoint_count": 2,
        "component_breakdown": {
            "reliability": "0.900",
            "stability": "1.000",
            "burst": "1.000",
            "consistency": "0.700",
        },
    },
    "endpoints": [
        {
            "endpoint_id": "ep_alpha",
            "reliability_metrics": {
                "execution_count": 20,
                "pass_count": 18,
                "fail_count": 2,
                "timeout_count": 1,
                "success_rate": "0.900",
                "success_rate_numerator": 18,
                "success_rate_denominator": 20,
                "latency_min_ms": 50.0,
                "latency_max_ms": 500.0,
                "latency_mean_ms": 120.0,
                "latency_median_ms": 100.0,
                "latency_p95_ms": 400.0,
                "latency_p99_ms": 480.0,
                "latency_count": 20,
                "failure_classification_breakdown": {
                    "PASS": 18,
                    "TIMEOUT": 1,
                    "CONNECTION_ERROR": 1,
                },
                "http_response_distribution": {"200": 18, "504": 2},
                "source_field_refs": {
                    "execution_count": "EndpointAggregate.execution_count"
                },
            },
            "stability_analysis": {
                "success_rate_stability_label": "STABLE",
                "latency_stability_label": "STABLE",
                "methodology_trace": {"window": 5, "variance": 0.002},
            },
            "burst_analysis": {
                "failure_burst_label": "NO_BURST",
                "latency_spike_label": "NO_SPIKE",
                "methodology_trace": {"max_consecutive": 1},
            },
            "consistency_analysis": {
                "consistency_label": "CONSISTENT",
                "methodology_trace": {"cv": 0.15},
            },
            "endpoint_score": {
                "composite_score": "0.850",
                "reliability_score": "0.900",
                "stability_score": "1.000",
                "burst_score": "1.000",
                "consistency_score": "0.700",
                "score_derivation": {"method": "weighted_average"},
            },
        },
        {
            "endpoint_id": "ep_beta",
            "reliability_metrics": {
                "execution_count": 20,
                "pass_count": 18,
                "fail_count": 2,
                "timeout_count": 0,
                "success_rate": "0.900",
                "success_rate_numerator": 18,
                "success_rate_denominator": 20,
                "latency_min_ms": None,
                "latency_max_ms": None,
                "latency_mean_ms": None,
                "latency_median_ms": None,
                "latency_p95_ms": None,
                "latency_p99_ms": None,
                "latency_count": 0,
                "failure_classification_breakdown": {"PASS": 18, "FAIL": 2},
                "http_response_distribution": {"200": 18, "500": 2},
                "source_field_refs": {
                    "execution_count": "EndpointAggregate.execution_count"
                },
            },
            "stability_analysis": {
                "success_rate_stability_label": "STABLE",
                "latency_stability_label": "INSUFFICIENT_DATA",
                "methodology_trace": {"window": 5},
            },
            "burst_analysis": {
                "failure_burst_label": "NO_BURST",
                "latency_spike_label": "INSUFFICIENT_DATA",
                "methodology_trace": {"max_consecutive": 0},
            },
            "consistency_analysis": {
                "consistency_label": "INSUFFICIENT_DATA",
                "methodology_trace": {"cv": None},
            },
            "endpoint_score": {
                "composite_score": "0.850",
                "reliability_score": "0.900",
                "stability_score": "1.000",
                "burst_score": "1.000",
                "consistency_score": "0.700",
                "score_derivation": {"method": "weighted_average"},
            },
        },
    ],
    "methodology_disclosure": {
        "intelligence_version": "intel_v1",
        "scoring": {
            "composite_weight": {
                "reliability": 0.4,
                "stability": 0.2,
                "burst": 0.2,
                "consistency": 0.2,
            }
        },
        "stability_label_definitions": {"STABLE": "variance < 0.01"},
        "burst_label_definitions": {"NO_BURST": "max_consecutive < 3"},
        "consistency_label_definitions": {"CONSISTENT": "cv < 0.3"},
        "label_to_score_mapping": {"STABLE": 1.0, "VOLATILE": 0.0},
        "limitations": [
            "Minimum 5 executions required for stability analysis.",
            "Latency data may be absent.",
        ],
    },
}

# ---------------------------------------------------------------------------
# Module-level shared instances — build once, render once
# ---------------------------------------------------------------------------

_BUILDER = ReportBuilder()
_REPORT = _BUILDER.build(
    _PHASE5_ARTIFACT,
    report_job_id="rptjob_test001",
    generated_at="2026-07-04T12:00:00Z",
)
_FORMATTER = MarkdownFormatter()
_OUTPUT = _FORMATTER.render(_REPORT)


# ---------------------------------------------------------------------------
# Purity / type
# ---------------------------------------------------------------------------


def test_render_returns_str() -> None:
    assert isinstance(_OUTPUT, str)


def test_formatter_is_stateless() -> None:
    second_render = _FORMATTER.render(_REPORT)
    assert second_render == _OUTPUT


# ---------------------------------------------------------------------------
# Section 1 — Header
# ---------------------------------------------------------------------------


def test_header_contains_audit_id() -> None:
    assert "audit_test" in _OUTPUT


def test_header_contains_report_id() -> None:
    # report_id is a generated UUID with "report_" prefix, NOT the report_job_id
    assert "rptjob_test001" not in _OUTPUT
    assert "report_" in _OUTPUT


def test_header_contains_generated_at() -> None:
    assert "2026-07-04T12:00:00Z" in _OUTPUT


def test_header_contains_report_version() -> None:
    assert REPORT_VERSION in _OUTPUT  # "report_v1"


# ---------------------------------------------------------------------------
# Section 2 — Executive Summary
# ---------------------------------------------------------------------------


def test_executive_summary_contains_score_label() -> None:
    assert "HIGH_CONFIDENCE" in _OUTPUT


def test_executive_summary_contains_composite_score() -> None:
    # composite_score_value = float("0.850") = 0.85 → formatted as "0.850"
    assert "0.850" in _OUTPUT


def test_executive_summary_contains_score_label_description() -> None:
    description = SCORE_LABEL_DESCRIPTIONS["HIGH_CONFIDENCE"]
    # Check a distinctive portion to avoid false match on partial substrings
    assert "Reliability indicators across all assessed endpoints are strong" in _OUTPUT
    assert description in _OUTPUT


def test_executive_summary_contains_endpoint_count() -> None:
    assert "2" in _OUTPUT


def test_executive_summary_contains_total_executions() -> None:
    assert "40" in _OUTPUT


# ---------------------------------------------------------------------------
# Section 3 — Release Confidence Score
# ---------------------------------------------------------------------------


def test_composite_score_section_present() -> None:
    assert "## Release Confidence Score" in _OUTPUT


def test_composite_score_aggregate_set_hash_present() -> None:
    assert "hash_test_abc" in _OUTPUT


# ---------------------------------------------------------------------------
# Section 4 — Audit Reliability Overview
# ---------------------------------------------------------------------------


def test_audit_reliability_overview_heading_present() -> None:
    assert "## Audit Reliability Overview" in _OUTPUT


def test_audit_reliability_overview_total_pass_present() -> None:
    assert "36" in _OUTPUT


# ---------------------------------------------------------------------------
# Section 5 — Per-Endpoint Analysis
# ---------------------------------------------------------------------------


def test_per_endpoint_heading_present() -> None:
    assert "## Per-Endpoint Analysis" in _OUTPUT


def test_both_endpoint_ids_present() -> None:
    assert "ep_alpha" in _OUTPUT
    assert "ep_beta" in _OUTPUT


def test_endpoint_stability_labels_present() -> None:
    assert "STABLE" in _OUTPUT


def test_endpoint_burst_labels_present() -> None:
    assert "NO_BURST" in _OUTPUT


def test_endpoint_consistency_label_present() -> None:
    assert "CONSISTENT" in _OUTPUT


def test_endpoint_with_null_latency_renders_na() -> None:
    # ep_beta has all latency fields as None; formatter must render "N/A"
    assert "N/A" in _OUTPUT


# ---------------------------------------------------------------------------
# Section 6 — Methodology Disclosure
# ---------------------------------------------------------------------------


def test_methodology_disclosure_heading_present() -> None:
    assert "## Methodology Disclosure" in _OUTPUT


def test_methodology_disclosure_intelligence_version() -> None:
    assert "intel_v1" in _OUTPUT


def test_limitations_rendered_as_list() -> None:
    assert "Minimum 5 executions" in _OUTPUT
    assert "Latency data" in _OUTPUT


# ---------------------------------------------------------------------------
# Section 7 — Evidence Lineage
# ---------------------------------------------------------------------------


def test_evidence_lineage_heading_present() -> None:
    assert "## Evidence Lineage" in _OUTPUT


def test_evidence_lineage_aggregate_set_hash() -> None:
    assert "hash_test_abc" in _OUTPUT


def test_evidence_lineage_aggregation_job_id() -> None:
    assert "aggjob_test002" in _OUTPUT


# ---------------------------------------------------------------------------
# Section 8 — Report Provenance
# ---------------------------------------------------------------------------


def test_report_provenance_heading_present() -> None:
    assert "## Report Provenance" in _OUTPUT


def test_report_provenance_intelligence_job_id() -> None:
    assert "intjob_test001" in _OUTPUT


def test_report_provenance_client_id() -> None:
    assert "client_test" in _OUTPUT


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_determinism_two_renders_identical() -> None:
    first = _FORMATTER.render(_REPORT)
    second = _FORMATTER.render(_REPORT)
    assert first == second


# ---------------------------------------------------------------------------
# All eight section headings present
# ---------------------------------------------------------------------------


def test_all_eight_section_headings_present() -> None:
    expected_headings = [
        "# Release Confidence Report",
        "## Executive Summary",
        "## Release Confidence Score",
        "## Audit Reliability Overview",
        "## Per-Endpoint Analysis",
        "## Methodology Disclosure",
        "## Evidence Lineage",
        "## Report Provenance",
    ]
    for heading in expected_headings:
        assert heading in _OUTPUT, f"Missing heading: {heading!r}"
