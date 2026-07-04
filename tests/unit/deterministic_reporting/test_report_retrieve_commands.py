"""Tests for Phase 6.7 Engineering Retrieval CLI — report retrieve commands.

Covers argument parsing, dispatch routing, provenance envelope presence,
per-command output content, and not-found error behaviour.

Fixtures use a minimal Phase 5 intelligence artifact (same structure as
test_builder.py) to build a real ReleaseConfidenceReport DTO.
"""

from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock

import pytest

from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.deterministic_reporting.builder import ReportBuilder
from release_confidence_platform.deterministic_reporting.formatters.markdown import (
    MarkdownFormatter,
)
from release_confidence_platform.deterministic_reporting.report_retrieve_commands import (
    build_report_retrieve_parser,
    dispatch_report_retrieve,
)

# ---------------------------------------------------------------------------
# Shared Phase 5 artifact fixture (minimal but valid)
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
            "failure_classification_breakdown": {"PASS": 18, "TIMEOUT": 1},
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

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def report_dto():
    """Real ReleaseConfidenceReport built from the minimal Phase 5 artifact."""
    return ReportBuilder().build(_PHASE5_ARTIFACT, _REPORT_JOB_ID, _GENERATED_AT)


@pytest.fixture(scope="module")
def report_artifact(report_dto):
    """Serialised report dict (report.model_dump()) — the Phase 6 S3 artifact format."""
    return report_dto.model_dump()


_STATUS_DICT = {
    "report_id": "report_testid001",
    "report_version": "report_v1",
    "intelligence_version": "intel_v1",
    "audit_id": "audit_xyz",
    "completed_at": "2026-07-04T14:00:00Z",
    "status": "COMPLETE",
    "score_label": "HIGH_CONFIDENCE",
    "report_job_id": "rptjob_test001",
}


def _make_args(command: str) -> argparse.Namespace:
    return argparse.Namespace(
        retrieve_command=command,
        client_id="client_abc",
        audit_id="audit_xyz",
        execution="exec_001",
        config_version="v1",
        aggregation_version="agg_v1",
        intelligence_version="intel_v1",
        report_version="report_v1",
        stage="dev",
        output="text",
    )


def _make_svc(report_dto=None, report_artifact=None, status_dict=None):
    """Build a mock svc with sensible return values."""
    svc = MagicMock()
    svc.get_report_status.return_value = status_dict
    svc.get_report_dto.return_value = report_dto
    svc.get_report_artifact.return_value = report_artifact
    return svc


# ---------------------------------------------------------------------------
# 1. report-status returns string
# ---------------------------------------------------------------------------


def test_report_status_returns_string():
    svc = _make_svc(status_dict=_STATUS_DICT)
    result = dispatch_report_retrieve(_make_args("report-status"), svc)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# 2. report-status output contains provenance fields
# ---------------------------------------------------------------------------


def test_report_status_contains_provenance_fields():
    svc = _make_svc(status_dict=_STATUS_DICT)
    result = dispatch_report_retrieve(_make_args("report-status"), svc)
    assert "Report ID:" in result
    assert "Report Version:" in result
    assert "Intelligence Version:" in result


# ---------------------------------------------------------------------------
# 3. report-status raises ValidationError when svc returns None
# ---------------------------------------------------------------------------


def test_report_status_not_found_raises():
    svc = _make_svc(status_dict=None)
    with pytest.raises(ValidationError):
        dispatch_report_retrieve(_make_args("report-status"), svc)


# ---------------------------------------------------------------------------
# 4. report-summary returns string
# ---------------------------------------------------------------------------


def test_report_summary_returns_string(report_dto):
    svc = _make_svc(report_dto=report_dto)
    result = dispatch_report_retrieve(_make_args("report-summary"), svc)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# 5. report-summary output contains score_label
# ---------------------------------------------------------------------------


def test_report_summary_contains_score_label(report_dto):
    svc = _make_svc(report_dto=report_dto)
    result = dispatch_report_retrieve(_make_args("report-summary"), svc)
    assert report_dto.executive_summary.score_label in result


# ---------------------------------------------------------------------------
# 6. report-endpoints returns string
# ---------------------------------------------------------------------------


def test_report_endpoints_returns_string(report_dto):
    svc = _make_svc(report_dto=report_dto)
    result = dispatch_report_retrieve(_make_args("report-endpoints"), svc)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# 7. report-endpoints output contains endpoint_id
# ---------------------------------------------------------------------------


def test_report_endpoints_contains_endpoint_id(report_dto):
    svc = _make_svc(report_dto=report_dto)
    result = dispatch_report_retrieve(_make_args("report-endpoints"), svc)
    assert "ep_alpha" in result


# ---------------------------------------------------------------------------
# 8. report-methodology returns string
# ---------------------------------------------------------------------------


def test_report_methodology_returns_string(report_dto):
    svc = _make_svc(report_dto=report_dto)
    result = dispatch_report_retrieve(_make_args("report-methodology"), svc)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# 9. report-lineage returns string
# ---------------------------------------------------------------------------


def test_report_lineage_returns_string(report_dto):
    svc = _make_svc(report_dto=report_dto)
    result = dispatch_report_retrieve(_make_args("report-lineage"), svc)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# 10. report-json returns valid JSON
# ---------------------------------------------------------------------------


def test_report_json_returns_valid_json(report_artifact):
    svc = _make_svc(report_artifact=report_artifact)
    result = dispatch_report_retrieve(_make_args("report-json"), svc)
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


# ---------------------------------------------------------------------------
# 11. report-json does NOT include provenance envelope
# ---------------------------------------------------------------------------


def test_report_json_no_provenance_envelope(report_artifact):
    svc = _make_svc(report_artifact=report_artifact)
    result = dispatch_report_retrieve(_make_args("report-json"), svc)
    assert "Report ID:" not in result


# ---------------------------------------------------------------------------
# 12. report-markdown returns string
# ---------------------------------------------------------------------------


def test_report_markdown_returns_string(report_dto):
    svc = _make_svc(report_dto=report_dto)
    formatter = MarkdownFormatter()
    result = dispatch_report_retrieve(_make_args("report-markdown"), svc, formatter)
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# 13. report-markdown output starts with the MarkdownFormatter header (no extra envelope)
# ---------------------------------------------------------------------------


def test_report_markdown_no_extra_envelope(report_dto):
    svc = _make_svc(report_dto=report_dto)
    formatter = MarkdownFormatter()
    result = dispatch_report_retrieve(_make_args("report-markdown"), svc, formatter)
    assert result.startswith("# Release Confidence Report")


# ---------------------------------------------------------------------------
# 14. dispatch routes all seven commands without raising
# ---------------------------------------------------------------------------


def test_dispatch_routes_all_seven_commands(report_dto, report_artifact):
    commands = [
        "report-status",
        "report-summary",
        "report-endpoints",
        "report-methodology",
        "report-lineage",
        "report-json",
        "report-markdown",
    ]
    formatter = MarkdownFormatter()
    for command in commands:
        svc = _make_svc(
            status_dict=_STATUS_DICT,
            report_dto=report_dto,
            report_artifact=report_artifact,
        )
        result = dispatch_report_retrieve(_make_args(command), svc, formatter)
        assert isinstance(result, str), f"dispatch for {command!r} did not return a string"


# ---------------------------------------------------------------------------
# 15. parser registers all seven subcommand names
# ---------------------------------------------------------------------------


def test_parser_registers_all_seven_subcommands():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="retrieve_command")
    build_report_retrieve_parser(sub)
    expected = {
        "report-status",
        "report-summary",
        "report-endpoints",
        "report-methodology",
        "report-lineage",
        "report-json",
        "report-markdown",
    }
    registered = set(sub.choices.keys())
    assert expected == registered, (
        f"Subcommand mismatch. Missing: {expected - registered}, "
        f"Extra: {registered - expected}"
    )
