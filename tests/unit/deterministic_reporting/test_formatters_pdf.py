"""Test: PdfFormatter.render() correctness and purity.

Verifies that the formatter produces valid PDF bytes from the ReleaseConfidenceReport
DTO, handles nullable latency fields without error, and satisfies purity constraints
(no AWS imports, accepts only the DTO type).

Note: PDF text is embedded in compressed binary content streams. Tests therefore
assert on output type, size, and magic bytes rather than string content presence.
"""
from __future__ import annotations

import importlib
import sys

import pytest

from release_confidence_platform.deterministic_reporting.builder import ReportBuilder
from release_confidence_platform.deterministic_reporting.formatters.pdf import PdfFormatter
from release_confidence_platform.deterministic_reporting.models import ReleaseConfidenceReport

# ---------------------------------------------------------------------------
# Phase 5 artifact fixture — two endpoints (ep_alpha has latency, ep_beta does not)
# Same fixture as test_formatters_markdown.py for consistency.
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
            "Minimum 5 executions required for reliable scoring.",
            "Latency data may be absent when all requests failed before response.",
        ],
    },
}

# Build the report once at module level — shared across all tests.
_REPORT: ReleaseConfidenceReport = ReportBuilder().build(
    _PHASE5_ARTIFACT,
    report_job_id="rptjob_pdf_test001",
    generated_at="2026-07-04T12:00:00Z",
)

_NULL_LATENCY_ARTIFACT: dict = {
    **_PHASE5_ARTIFACT,
    "audit_reliability_summary": {
        **_PHASE5_ARTIFACT["audit_reliability_summary"],
        "audit_latency_mean_ms": None,
        "audit_latency_p95_ms": None,
        "audit_latency_p99_ms": None,
    },
}

_NULL_LATENCY_REPORT: ReleaseConfidenceReport = ReportBuilder().build(
    _NULL_LATENCY_ARTIFACT,
    report_job_id="rptjob_pdf_null_lat001",
    generated_at="2026-07-04T12:05:00Z",
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_render_returns_bytes() -> None:
    result = PdfFormatter().render(_REPORT)
    assert isinstance(result, bytes)


def test_render_output_not_empty() -> None:
    result = PdfFormatter().render(_REPORT)
    assert len(result) > 0


def test_render_starts_with_pdf_magic() -> None:
    result = PdfFormatter().render(_REPORT)
    assert result[:5] == b"%PDF-"


def test_render_does_not_raise() -> None:
    PdfFormatter().render(_REPORT)


def test_render_produces_valid_pdf_size() -> None:
    result = PdfFormatter().render(_REPORT)
    assert 100 < len(result) < 10 * 1024 * 1024  # 100 bytes < size < 10 MB


def test_render_with_null_latency_fields_does_not_raise() -> None:
    PdfFormatter().render(_NULL_LATENCY_REPORT)


def test_render_with_null_latency_fields_returns_bytes() -> None:
    result = PdfFormatter().render(_NULL_LATENCY_REPORT)
    assert isinstance(result, bytes)
    assert result[:5] == b"%PDF-"


def test_render_returns_bytes_not_string() -> None:
    result = PdfFormatter().render(_REPORT)
    assert not isinstance(result, str)


def test_render_two_calls_same_length() -> None:
    formatter = PdfFormatter()
    first = formatter.render(_REPORT)
    second = formatter.render(_REPORT)
    assert len(first) == len(second)


def test_purity_no_aws_imports() -> None:
    mod_name = "release_confidence_platform.deterministic_reporting.formatters.pdf"
    mod = sys.modules.get(mod_name) or importlib.import_module(mod_name)
    prohibited = {"boto3", "botocore", "aiobotocore"}
    loaded = set(sys.modules.keys())
    # None of the prohibited AWS SDK modules should have been imported transitively
    # by loading the pdf formatter module alone. We check the module's own imports.
    source_file = mod.__file__ or ""
    with open(source_file) as f:
        source = f.read()
    for pkg in prohibited:
        assert pkg not in source, f"pdf.py must not import {pkg!r}"


def test_formatter_accepts_release_confidence_report_type() -> None:
    assert isinstance(_REPORT, ReleaseConfidenceReport)
    result = PdfFormatter().render(_REPORT)
    assert isinstance(result, bytes)


def test_single_endpoint_report_does_not_raise() -> None:
    single_ep_artifact = {**_PHASE5_ARTIFACT, "endpoints": [_PHASE5_ARTIFACT["endpoints"][0]]}
    single_ep_artifact["composite_score"] = {
        **_PHASE5_ARTIFACT["composite_score"],
        "endpoint_count": 1,
    }
    single_ep_artifact["audit_reliability_summary"] = {
        **_PHASE5_ARTIFACT["audit_reliability_summary"],
        "endpoint_count": 1,
        "total_executions": 20,
        "total_pass": 18,
        "total_fail": 2,
        "total_timeout": 1,
    }
    report = ReportBuilder().build(
        single_ep_artifact,
        report_job_id="rptjob_pdf_single001",
        generated_at="2026-07-04T13:00:00Z",
    )
    result = PdfFormatter().render(report)
    assert isinstance(result, bytes)
    assert result[:5] == b"%PDF-"
