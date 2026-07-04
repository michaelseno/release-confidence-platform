"""Test: ReportBuilder.build() basic correctness.

Verifies that the builder correctly maps Phase 5 intelligence artifact fields to
ReleaseConfidenceReport DTO fields, with correct type conversions.
"""

from __future__ import annotations

import pytest

from release_confidence_platform.deterministic_reporting.builder import ReportBuilder
from release_confidence_platform.deterministic_reporting.constants import (
    REPORT_VERSION,
    SCORE_LABEL_DESCRIPTIONS,
)

# ---------------------------------------------------------------------------
# Shared fixture: Phase 5 artifact with 2 endpoints
# ---------------------------------------------------------------------------

_SOURCE_FIELD_REFS = {
    "total_executions": "AuditAggregate.request_counts.total",
    "audit_success_rate": "AuditAggregate.request_counts.successful",
}

_EP_SOURCE_FIELD_REFS = {
    "execution_count": "EndpointAggregate.execution_count",
    "success_rate_numerator": "EndpointAggregate.success_inputs.numerator",
}


def _make_endpoint_entry(ep_id: str) -> dict:
    return {
        "endpoint_id": ep_id,
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
            "failure_classification_breakdown": {"PASS": 18, "TIMEOUT": 1, "CONNECTION_ERROR": 1},
            "http_response_distribution": {"200": 18, "504": 2},
            "source_field_refs": _EP_SOURCE_FIELD_REFS,
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
            "composite_score": "0.850",
            "reliability_score": "0.900",
            "stability_score": "1.000",
            "burst_score": "1.000",
            "consistency_score": "1.000",
            "score_derivation": {"method": "weighted_average"},
        },
    }


_PHASE5_ARTIFACT = {
    "intelligence_version": "intel_v1",
    "aggregation_version": "agg_v1",
    "client_id": "client_abc",
    "audit_id": "audit_xyz",
    "audit_execution_id": "exec_001",
    "config_version": "v1",
    "intelligence_job_id": "intjob_abc123",
    "generated_at": "2026-07-04T12:00:00Z",
    "generator_version": "1.0.0",
    "input_lineage": {
        "aggregate_set_hash": "hashABC123",
        "aggregation_job_id": "aggjob_XYZ",
        "aggregation_version": "agg_v1",
        "aggregate_set_completion_created_at": "2026-07-04T10:00:00Z",
        "endpoint_aggregate_count": 2,
        "source_raw_result_count": 40,
        "audit_lineage_manifest_ref": None,
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
        "source_field_refs": _SOURCE_FIELD_REFS,
    },
    "composite_score": {
        "value": "0.850",
        "score_label": "HIGH_CONFIDENCE",
        "intelligence_version": "intel_v1",
        "aggregation_version": "agg_v1",
        "aggregate_set_hash": "hashABC123",
        "endpoint_count": 2,
        "component_breakdown": {"reliability": 0.9, "stability": 1.0},
    },
    "endpoints": [
        _make_endpoint_entry("ep_alpha"),
        _make_endpoint_entry("ep_beta"),
    ],
    "methodology_disclosure": {
        "intelligence_version": "intel_v1",
        "scoring": {"method": "composite"},
        "stability_label_definitions": {"STABLE": "..."},
        "burst_label_definitions": {"NO_BURST": "..."},
        "consistency_label_definitions": {"CONSISTENT": "..."},
        "label_to_score_mapping": {"HIGH_CONFIDENCE": 0.9},
        "limitations": ["MVP limitation"],
    },
}

_GENERATED_AT = "2026-07-04T14:00:00Z"
_REPORT_JOB_ID = "rptjob_testjob001"


@pytest.fixture()
def report():
    builder = ReportBuilder()
    return builder.build(_PHASE5_ARTIFACT, _REPORT_JOB_ID, _GENERATED_AT)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_identity_report_version(report):
    """identity.report_version must equal REPORT_VERSION constant."""
    assert report.identity.report_version == REPORT_VERSION


def test_identity_generator_version(report):
    """identity.generator_version must equal the module-level constant '1.0.0'."""
    assert report.identity.generator_version == "1.0.0"


def test_intelligence_provenance_intelligence_version(report):
    """intelligence_provenance.intelligence_version must match artifact."""
    assert report.intelligence_provenance.intelligence_version == _PHASE5_ARTIFACT["intelligence_version"]


def test_executive_summary_score_label(report):
    """executive_summary.score_label must match artifact composite_score.score_label."""
    assert report.executive_summary.score_label == _PHASE5_ARTIFACT["composite_score"]["score_label"]


def test_executive_summary_composite_score_value_is_float(report):
    """executive_summary.composite_score_value must equal float of artifact string value."""
    assert report.executive_summary.composite_score_value == float(
        _PHASE5_ARTIFACT["composite_score"]["value"]
    )


def test_executive_summary_score_label_description_is_non_empty_str(report):
    """executive_summary.score_label_description must be a non-empty string from SCORE_LABEL_DESCRIPTIONS."""
    desc = report.executive_summary.score_label_description
    assert isinstance(desc, str)
    assert len(desc) > 0
    assert desc == SCORE_LABEL_DESCRIPTIONS[report.executive_summary.score_label]


def test_audit_reliability_overview_success_rate_is_float(report):
    """audit_reliability_overview.audit_success_rate must be float, not str."""
    rate = report.audit_reliability_overview.audit_success_rate
    assert isinstance(rate, float)
    assert rate == float(_PHASE5_ARTIFACT["audit_reliability_summary"]["audit_success_rate"])


def test_endpoints_list_length_matches_artifact(report):
    """endpoints list length must match the artifact endpoints list length."""
    assert len(report.endpoints) == len(_PHASE5_ARTIFACT["endpoints"])


def test_endpoints_sorted_by_endpoint_id(report):
    """Endpoints must remain sorted by endpoint_id."""
    ep_ids = [ep.endpoint_id for ep in report.endpoints]
    assert ep_ids == sorted(ep_ids)


def test_composite_score_value_is_float(report):
    """composite_score.value must be float, not str."""
    assert isinstance(report.composite_score.value, float)
    assert report.composite_score.value == float(_PHASE5_ARTIFACT["composite_score"]["value"])


def test_input_lineage_audit_lineage_manifest_ref_defaults_to_empty_dict_when_none(report):
    """input_lineage.audit_lineage_manifest_ref must default to {} when artifact field is None."""
    assert report.input_lineage.audit_lineage_manifest_ref == {}


def test_methodology_disclosure_intelligence_version(report):
    """methodology_disclosure.intelligence_version must be verbatim pass-through."""
    assert (
        report.methodology_disclosure.intelligence_version
        == _PHASE5_ARTIFACT["methodology_disclosure"]["intelligence_version"]
    )


def test_generated_at_parameter_used_not_datetime_now(report):
    """identity.generated_at must equal the generated_at parameter, not a live timestamp."""
    assert report.identity.generated_at == _GENERATED_AT


def test_identity_report_id_has_correct_prefix(report):
    """identity.report_id must start with 'report_' prefix."""
    assert report.identity.report_id.startswith("report_")
