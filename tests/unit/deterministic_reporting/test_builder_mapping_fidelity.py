"""Test: ReportBuilder field mapping fidelity regression suite.

MANDATORY mapping fidelity test. Uses a distinct-value fixture where every mapped field
carries a unique, recognisable value so that field transposition bugs (field A mapped
to slot B) are caught — not just presence tests.

Each assertion targets exactly one mapped field. Failure messages identify exactly
which mapping is broken without masking sibling failures.
"""

from __future__ import annotations

import pytest

from release_confidence_platform.deterministic_reporting.builder import ReportBuilder

# ---------------------------------------------------------------------------
# Distinct-value fixture
# ---------------------------------------------------------------------------
# Every field has a unique value. If any two fields were swapped in the builder
# the wrong-value assertion would fail immediately.

_DISTINCT_ARTIFACT: dict = {
    "intelligence_version": "intel_v1",
    "aggregation_version": "agg_v1_FIDELITY",
    "client_id": "client_FIDELITY_001",
    "audit_id": "audit_FIDELITY_002",
    "audit_execution_id": "exec_FIDELITY_003",
    "config_version": "cfg_FIDELITY_004",
    "intelligence_job_id": "intjob_FIDELITY_005",
    "generated_at": "2026-01-01T11:11:11Z",
    "generator_version": "1.0.0",
    "input_lineage": {
        "aggregate_set_hash": "HASH_FIDELITY_006",
        "aggregation_job_id": "aggjob_FIDELITY_007",
        "aggregation_version": "agg_v1_FIDELITY",
        "aggregate_set_completion_created_at": "2026-01-01T08:00:00Z",
        "endpoint_aggregate_count": 3,
        "source_raw_result_count": 777,
        "audit_lineage_manifest_ref": {"s3_key": "lineage/FIDELITY_008"},
    },
    "audit_reliability_summary": {
        "total_executions": 1001,
        "total_pass": 888,
        "total_fail": 77,
        "total_timeout": 22,
        "total_network_failure": 14,
        "audit_success_rate": "0.887",
        "endpoint_count": 3,
        "audit_latency_mean_ms": 111.1,
        "audit_latency_p95_ms": 222.2,
        "audit_latency_p99_ms": 333.3,
        "source_field_refs": {"_fidelity_marker": "source_field_refs_FIDELITY"},
    },
    "composite_score": {
        "value": "0.777",
        "score_label": "MODERATE_CONFIDENCE",
        "intelligence_version": "intel_v1",
        "aggregation_version": "agg_v1_FIDELITY",
        "aggregate_set_hash": "HASH_FIDELITY_006",
        "endpoint_count": 3,
        "component_breakdown": {"_fidelity": "component_breakdown_FIDELITY"},
    },
    "endpoints": [
        {
            "endpoint_id": "ep_FIDELITY_ALPHA",
            "reliability_metrics": {
                "execution_count": 500,
                "pass_count": 444,
                "fail_count": 40,
                "timeout_count": 11,
                "success_rate": "0.888",
                "success_rate_numerator": 444,
                "success_rate_denominator": 500,
                "latency_min_ms": 10.5,
                "latency_max_ms": 999.9,
                "latency_mean_ms": 55.5,
                "latency_median_ms": 44.4,
                "latency_p95_ms": 777.7,
                "latency_p99_ms": 888.8,
                "latency_count": 500,
                "failure_classification_breakdown": {"_fidelity": "fc_breakdown_FIDELITY"},
                "http_response_distribution": {"200": 444, "_fidelity": "http_dist_FIDELITY"},
                "source_field_refs": {"_fidelity": "ep_source_refs_FIDELITY"},
            },
            "stability_analysis": {
                "success_rate_stability_label": "STABLE_FIDELITY",
                "latency_stability_label": "VOLATILE_FIDELITY",
                "methodology_trace": {"_fidelity": "stability_trace_FIDELITY"},
            },
            "burst_analysis": {
                "failure_burst_label": "BURST_FIDELITY",
                "latency_spike_label": "SPIKE_FIDELITY",
                "methodology_trace": {"_fidelity": "burst_trace_FIDELITY"},
            },
            "consistency_analysis": {
                "consistency_label": "INCONSISTENT_FIDELITY",
                "methodology_trace": {"_fidelity": "consistency_trace_FIDELITY"},
            },
            "endpoint_score": {
                "composite_score": "0.456",
                "reliability_score": "0.567",
                "stability_score": "0.678",
                "burst_score": "0.789",
                "consistency_score": "0.890",
                "score_derivation": {"_fidelity": "score_derivation_FIDELITY"},
            },
        }
    ],
    "methodology_disclosure": {
        "intelligence_version": "intel_v1",
        "scoring": {"_fidelity": "scoring_FIDELITY"},
        "stability_label_definitions": {"_fidelity": "stability_defs_FIDELITY"},
        "burst_label_definitions": {"_fidelity": "burst_defs_FIDELITY"},
        "consistency_label_definitions": {"_fidelity": "consistency_defs_FIDELITY"},
        "label_to_score_mapping": {"_fidelity": "label_score_map_FIDELITY"},
        "limitations": ["limitation_FIDELITY_001", "limitation_FIDELITY_002"],
    },
}

_FIDELITY_GENERATED_AT = "2026-07-04T00:00:00Z"
_FIDELITY_REPORT_JOB_ID = "rptjob_fidelity_test"


@pytest.fixture(scope="module")
def report():
    builder = ReportBuilder()
    return builder.build(_DISTINCT_ARTIFACT, _FIDELITY_REPORT_JOB_ID, _FIDELITY_GENERATED_AT)


# ---------------------------------------------------------------------------
# Layer 1: Report Identity
# ---------------------------------------------------------------------------


def test_identity_generated_at_from_parameter(report):
    assert report.identity.generated_at == _FIDELITY_GENERATED_AT


def test_identity_report_id_starts_with_report_prefix(report):
    assert report.identity.report_id.startswith("report_")


# ---------------------------------------------------------------------------
# Layer 2: IntelligenceProvenance
# ---------------------------------------------------------------------------


def test_provenance_intelligence_version(report):
    assert report.intelligence_provenance.intelligence_version == "intel_v1"


def test_provenance_intelligence_job_id(report):
    assert report.intelligence_provenance.intelligence_job_id == "intjob_FIDELITY_005"


def test_provenance_client_id(report):
    assert report.intelligence_provenance.client_id == "client_FIDELITY_001"


def test_provenance_audit_id(report):
    assert report.intelligence_provenance.audit_id == "audit_FIDELITY_002"


def test_provenance_audit_execution_id(report):
    assert report.intelligence_provenance.audit_execution_id == "exec_FIDELITY_003"


def test_provenance_config_version(report):
    assert report.intelligence_provenance.config_version == "cfg_FIDELITY_004"


def test_provenance_aggregation_version(report):
    assert report.intelligence_provenance.aggregation_version == "agg_v1_FIDELITY"


def test_provenance_aggregate_set_hash(report):
    # Sourced from composite_score.aggregate_set_hash, not input_lineage
    assert report.intelligence_provenance.aggregate_set_hash == "HASH_FIDELITY_006"


def test_provenance_intelligence_completed_at(report):
    # Sourced from artifact["generated_at"], not the generated_at parameter
    assert report.intelligence_provenance.intelligence_completed_at == "2026-01-01T11:11:11Z"


# ---------------------------------------------------------------------------
# Layer 3: ExecutiveSummary
# ---------------------------------------------------------------------------


def test_executive_summary_score_label(report):
    assert report.executive_summary.score_label == "MODERATE_CONFIDENCE"


def test_executive_summary_composite_score_value(report):
    assert report.executive_summary.composite_score_value == float("0.777")


def test_executive_summary_endpoint_count(report):
    assert report.executive_summary.endpoint_count == 3


def test_executive_summary_audit_success_rate(report):
    assert report.executive_summary.audit_success_rate == float("0.887")


def test_executive_summary_total_executions(report):
    assert report.executive_summary.total_executions == 1001


# ---------------------------------------------------------------------------
# Layer 4: AuditReliabilityOverview
# ---------------------------------------------------------------------------


def test_overview_total_executions(report):
    assert report.audit_reliability_overview.total_executions == 1001


def test_overview_total_pass(report):
    assert report.audit_reliability_overview.total_pass == 888


def test_overview_total_fail(report):
    assert report.audit_reliability_overview.total_fail == 77


def test_overview_total_timeout(report):
    assert report.audit_reliability_overview.total_timeout == 22


def test_overview_total_network_failure(report):
    assert report.audit_reliability_overview.total_network_failure == 14


def test_overview_audit_success_rate(report):
    assert report.audit_reliability_overview.audit_success_rate == float("0.887")


def test_overview_endpoint_count(report):
    assert report.audit_reliability_overview.endpoint_count == 3


def test_overview_audit_latency_mean_ms(report):
    assert report.audit_reliability_overview.audit_latency_mean_ms == 111.1


def test_overview_audit_latency_p95_ms(report):
    assert report.audit_reliability_overview.audit_latency_p95_ms == 222.2


def test_overview_audit_latency_p99_ms(report):
    assert report.audit_reliability_overview.audit_latency_p99_ms == 333.3


def test_overview_source_field_refs_verbatim(report):
    assert report.audit_reliability_overview.source_field_refs == {
        "_fidelity_marker": "source_field_refs_FIDELITY"
    }


# ---------------------------------------------------------------------------
# Layer 4: CompositeScoreSection
# ---------------------------------------------------------------------------


def test_composite_score_value(report):
    assert report.composite_score.value == float("0.777")


def test_composite_score_score_label(report):
    assert report.composite_score.score_label == "MODERATE_CONFIDENCE"


def test_composite_score_aggregate_set_hash(report):
    assert report.composite_score.aggregate_set_hash == "HASH_FIDELITY_006"


def test_composite_score_endpoint_count(report):
    assert report.composite_score.endpoint_count == 3


def test_composite_score_component_breakdown_verbatim(report):
    assert report.composite_score.component_breakdown == {
        "_fidelity": "component_breakdown_FIDELITY"
    }


# ---------------------------------------------------------------------------
# Layer 4: Endpoints
# ---------------------------------------------------------------------------


def test_endpoint_list_length(report):
    assert len(report.endpoints) == 1


def test_endpoint_id(report):
    ep = report.endpoints[0]
    assert ep.endpoint_id == "ep_FIDELITY_ALPHA"


def test_endpoint_reliability_execution_count(report):
    assert report.endpoints[0].reliability_metrics.execution_count == 500


def test_endpoint_reliability_pass_count(report):
    assert report.endpoints[0].reliability_metrics.pass_count == 444


def test_endpoint_reliability_fail_count(report):
    assert report.endpoints[0].reliability_metrics.fail_count == 40


def test_endpoint_reliability_timeout_count(report):
    assert report.endpoints[0].reliability_metrics.timeout_count == 11


def test_endpoint_reliability_success_rate(report):
    assert report.endpoints[0].reliability_metrics.success_rate == float("0.888")


def test_endpoint_reliability_success_rate_numerator(report):
    assert report.endpoints[0].reliability_metrics.success_rate_numerator == 444


def test_endpoint_reliability_success_rate_denominator(report):
    assert report.endpoints[0].reliability_metrics.success_rate_denominator == 500


def test_endpoint_reliability_latency_min_ms(report):
    assert report.endpoints[0].reliability_metrics.latency_min_ms == 10.5


def test_endpoint_reliability_latency_max_ms(report):
    assert report.endpoints[0].reliability_metrics.latency_max_ms == 999.9


def test_endpoint_reliability_latency_mean_ms(report):
    assert report.endpoints[0].reliability_metrics.latency_mean_ms == 55.5


def test_endpoint_reliability_latency_median_ms(report):
    assert report.endpoints[0].reliability_metrics.latency_median_ms == 44.4


def test_endpoint_reliability_latency_p95_ms(report):
    assert report.endpoints[0].reliability_metrics.latency_p95_ms == 777.7


def test_endpoint_reliability_latency_p99_ms(report):
    assert report.endpoints[0].reliability_metrics.latency_p99_ms == 888.8


def test_endpoint_reliability_latency_count(report):
    assert report.endpoints[0].reliability_metrics.latency_count == 500


def test_endpoint_reliability_failure_classification_breakdown_verbatim(report):
    assert report.endpoints[0].reliability_metrics.failure_classification_breakdown == {
        "_fidelity": "fc_breakdown_FIDELITY"
    }


def test_endpoint_reliability_http_response_distribution_verbatim(report):
    assert report.endpoints[0].reliability_metrics.http_response_distribution == {
        "200": 444,
        "_fidelity": "http_dist_FIDELITY",
    }


def test_endpoint_stability_success_rate_label(report):
    assert (
        report.endpoints[0].stability_analysis.success_rate_stability_label == "STABLE_FIDELITY"
    )


def test_endpoint_stability_latency_label(report):
    assert report.endpoints[0].stability_analysis.latency_stability_label == "VOLATILE_FIDELITY"


def test_endpoint_stability_methodology_trace_verbatim(report):
    assert report.endpoints[0].stability_analysis.methodology_trace == {
        "_fidelity": "stability_trace_FIDELITY"
    }


def test_endpoint_burst_failure_label(report):
    assert report.endpoints[0].burst_analysis.failure_burst_label == "BURST_FIDELITY"


def test_endpoint_burst_latency_spike_label(report):
    assert report.endpoints[0].burst_analysis.latency_spike_label == "SPIKE_FIDELITY"


def test_endpoint_burst_methodology_trace_verbatim(report):
    assert report.endpoints[0].burst_analysis.methodology_trace == {
        "_fidelity": "burst_trace_FIDELITY"
    }


def test_endpoint_consistency_label(report):
    assert report.endpoints[0].consistency_analysis.consistency_label == "INCONSISTENT_FIDELITY"


def test_endpoint_consistency_methodology_trace_verbatim(report):
    assert report.endpoints[0].consistency_analysis.methodology_trace == {
        "_fidelity": "consistency_trace_FIDELITY"
    }


def test_endpoint_score_composite(report):
    assert report.endpoints[0].endpoint_score.composite_score == float("0.456")


def test_endpoint_score_reliability(report):
    assert report.endpoints[0].endpoint_score.reliability_score == float("0.567")


def test_endpoint_score_stability(report):
    assert report.endpoints[0].endpoint_score.stability_score == float("0.678")


def test_endpoint_score_burst(report):
    assert report.endpoints[0].endpoint_score.burst_score == float("0.789")


def test_endpoint_score_consistency(report):
    assert report.endpoints[0].endpoint_score.consistency_score == float("0.890")


def test_endpoint_score_derivation_verbatim(report):
    assert report.endpoints[0].endpoint_score.score_derivation == {
        "_fidelity": "score_derivation_FIDELITY"
    }


# ---------------------------------------------------------------------------
# Layers 4/5: InputLineageSection
# ---------------------------------------------------------------------------


def test_input_lineage_aggregate_set_hash(report):
    assert report.input_lineage.aggregate_set_hash == "HASH_FIDELITY_006"


def test_input_lineage_aggregation_job_id(report):
    assert report.input_lineage.aggregation_job_id == "aggjob_FIDELITY_007"


def test_input_lineage_aggregation_version(report):
    assert report.input_lineage.aggregation_version == "agg_v1_FIDELITY"


def test_input_lineage_aggregate_set_completion_created_at(report):
    assert report.input_lineage.aggregate_set_completion_created_at == "2026-01-01T08:00:00Z"


def test_input_lineage_endpoint_aggregate_count(report):
    assert report.input_lineage.endpoint_aggregate_count == 3


def test_input_lineage_source_raw_result_count(report):
    assert report.input_lineage.source_raw_result_count == 777


def test_input_lineage_audit_lineage_manifest_ref_verbatim(report):
    assert report.input_lineage.audit_lineage_manifest_ref == {
        "s3_key": "lineage/FIDELITY_008"
    }


# ---------------------------------------------------------------------------
# Layer 5: MethodologyDisclosure (verbatim equality)
# ---------------------------------------------------------------------------


def test_methodology_disclosure_intelligence_version(report):
    assert report.methodology_disclosure.intelligence_version == "intel_v1"


def test_methodology_disclosure_scoring_verbatim(report):
    assert report.methodology_disclosure.scoring == {"_fidelity": "scoring_FIDELITY"}


def test_methodology_disclosure_stability_label_definitions_verbatim(report):
    assert report.methodology_disclosure.stability_label_definitions == {
        "_fidelity": "stability_defs_FIDELITY"
    }


def test_methodology_disclosure_burst_label_definitions_verbatim(report):
    assert report.methodology_disclosure.burst_label_definitions == {
        "_fidelity": "burst_defs_FIDELITY"
    }


def test_methodology_disclosure_consistency_label_definitions_verbatim(report):
    assert report.methodology_disclosure.consistency_label_definitions == {
        "_fidelity": "consistency_defs_FIDELITY"
    }


def test_methodology_disclosure_label_to_score_mapping_verbatim(report):
    assert report.methodology_disclosure.label_to_score_mapping == {
        "_fidelity": "label_score_map_FIDELITY"
    }


def test_methodology_disclosure_limitations_verbatim(report):
    assert report.methodology_disclosure.limitations == [
        "limitation_FIDELITY_001",
        "limitation_FIDELITY_002",
    ]
