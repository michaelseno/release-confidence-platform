"""Phase 6 Consumer Contract Compatibility Gate.

CON-01 through CON-24 — validates that all stable fields defined in
docs/architecture/phase_5_phase6_consumer_contract.md Section 3 are present,
correctly typed, and semantically consistent in the current Phase 5
intelligence artifact output for a known fixture.

This test must pass for all intel_v1 Phase 5 output. Failure blocks
Phase 5 implementation changes per Section 7 of the consumer contract.
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from release_confidence_platform.reliability_intelligence.engine import IntelligenceEngine

# ---------------------------------------------------------------------------
# Minimal Phase 4 fixture (two endpoints, enough for all label paths)
# ---------------------------------------------------------------------------

_AGG_SET_COMPLETION = {
    "record_type": "aggregate_set_completion",
    "completion_status": "COMPLETE",
    "aggregate_set_hash": "deadbeef0123456789abcdef01234567deadbeef0123456789abcdef01234567",
    "aggregation_job_id": "aggjob_con_test_fixture",
    "created_at": "2026-07-01T00:00:00.000Z",
    "endpoint_aggregate_count": 2,
    "source_raw_result_count": 40,
    "audit_lineage_manifest_ref": {
        "manifest_scope": "audit",
        "source_ref_count": 40,
        "manifest_hash": "aabbccdd" * 8,
    },
}

_AUDIT_AGGREGATE = {
    "record_type": "audit_aggregate",
    "aggregate_type": "audit",
    "record_kind": "aggregate",
    "request_counts": {
        "total": 40, "successful": 38, "failed": 2, "timeout": 1, "network_failure": 1,
    },
    "latency_summary_ms": {
        "count": 40, "min": 50.0, "max": 500.0, "mean": 120.0,
        "median": 100.0, "p95": 400.0, "p99": 480.0,
    },
    "endpoint_execution_counts": {"ep_alpha": 20, "ep_beta": 20},
    "lineage": {"audit_execution_id": "exec_con_01", "config_version": "v1"},
}

_EP_ALPHA_AGGREGATE = {
    "record_type": "endpoint_aggregate",
    "aggregate_type": "endpoint",
    "record_kind": "aggregate",
    "endpoint_id": "ep_alpha",
    "execution_count": 20,
    "timeout_count": 1,
    "success_inputs": {"numerator": 19, "denominator": 20},
    "latency_distribution_ms": {
        "count": 20, "min": 50, "max": 500, "mean": 120.0,
        "median": 100, "p95": 400, "p99": 480,
    },
    "http_response_distribution": {"200": 19, "500": 1},
    "lineage": {"audit_execution_id": "exec_con_01", "config_version": "v1"},
}

_EP_BETA_AGGREGATE = {
    "record_type": "endpoint_aggregate",
    "aggregate_type": "endpoint",
    "record_kind": "aggregate",
    "endpoint_id": "ep_beta",
    "execution_count": 20,
    "timeout_count": 0,
    "success_inputs": {"numerator": 19, "denominator": 20},
    "latency_distribution_ms": {
        "count": 20, "min": 30, "max": 200, "mean": 80.0,
        "median": 75, "p95": 150, "p99": 190,
    },
    "http_response_distribution": {"200": 19, "404": 1},
    "lineage": {"audit_execution_id": "exec_con_01", "config_version": "v1"},
}

_FC_ALPHA = {
    "record_type": "failure_classification_aggregate",
    "aggregate_type": "failure_classification",
    "endpoint_id": "ep_alpha",
    "scope": "endpoint",
    "classification_counts": {"PASS": 19, "TIMEOUT": 1},
}

_FC_BETA = {
    "record_type": "failure_classification_aggregate",
    "aggregate_type": "failure_classification",
    "endpoint_id": "ep_beta",
    "scope": "endpoint",
    "classification_counts": {"PASS": 19, "HTTP_ERROR": 1},
}


# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


class _FakeRepository:
    def __init__(self) -> None:
        self.write_calls: list[tuple[str, Any]] = []

    def get_intelligence_metadata(self, *args: Any, **kwargs: Any) -> None:
        return None

    def get_aggregate_set_completion(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return _AGG_SET_COMPLETION

    def list_phase4_aggregate_records(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            _AGG_SET_COMPLETION,
            _AUDIT_AGGREGATE,
            _EP_ALPHA_AGGREGATE,
            _EP_BETA_AGGREGATE,
            _FC_ALPHA,
            _FC_BETA,
        ]

    def intelligence_job_keys(self, client_id: str, audit_id: str, job_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#INTJOB#{job_id}"}

    def intelligence_metadata_keys(
        self, client_id: str, audit_id: str, exec_id: str, cfg: str, agg_ver: str, intel_ver: str
    ) -> dict[str, str]:
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": (
                f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}"
                f"#AGG#{agg_ver}#INTEL#{intel_ver}#META"
            ),
        }

    def put_intelligence_job_once(self, item: dict[str, Any]) -> None:
        self.write_calls.append(("put_intelligence_job_once", item))

    def put_intelligence_metadata_once(self, item: dict[str, Any]) -> None:
        self.write_calls.append(("put_intelligence_metadata_once", item))

    def update_intelligence_job(self, key: dict[str, Any], updates: dict[str, Any]) -> None:
        self.write_calls.append(("update_intelligence_job", {**key, **updates}))

    def update_intelligence_metadata_fields(
        self, key: dict[str, Any], updates: dict[str, Any]
    ) -> None:
        self.write_calls.append(("update_intelligence_metadata_fields", {**key, **updates}))


class _FakePublisher:
    def __init__(self) -> None:
        self.written: dict[str, dict[str, Any]] = {}

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        self.written[key] = artifact


# ---------------------------------------------------------------------------
# Module-level fixture: run engine once, share across all tests
# ---------------------------------------------------------------------------


def _run_engine() -> tuple[dict[str, Any], dict[str, Any], list[tuple[str, Any]]]:
    repo = _FakeRepository()
    pub = _FakePublisher()
    engine = IntelligenceEngine(repo, pub)
    result = engine.generate(
        client_id="client_contract_test",
        audit_id="audit_contract_test",
        audit_execution_id="exec_con_01",
        config_version="v1",
        aggregation_version="agg_v1",
    )
    assert pub.written, "Engine must write an S3 artifact"
    artifact = list(pub.written.values())[0]
    return result, artifact, repo.write_calls


@pytest.fixture(scope="module")
def contract_fixture() -> tuple[dict[str, Any], dict[str, Any], list[tuple[str, Any]]]:
    return _run_engine()


@pytest.fixture(scope="module")
def artifact(contract_fixture: tuple) -> dict[str, Any]:
    return contract_fixture[1]


@pytest.fixture(scope="module")
def result(contract_fixture: tuple) -> dict[str, Any]:
    return contract_fixture[0]


@pytest.fixture(scope="module")
def write_calls(contract_fixture: tuple) -> list[tuple[str, Any]]:
    return contract_fixture[2]


@pytest.fixture(scope="module")
def meta_item(write_calls: list[tuple[str, Any]]) -> dict[str, Any]:
    # Reconstruct the full DynamoDB IntelligenceMetadata record as Phase 6 would read it:
    # start from the initial PUT (all fields) then apply the COMPLETE update.
    initial_puts = [
        item for method, item in write_calls if method == "put_intelligence_metadata_once"
    ]
    assert initial_puts, "Must have put_intelligence_metadata_once call"
    full_record = dict(initial_puts[-1])

    complete_updates = [
        item for method, item in write_calls
        if method == "update_intelligence_metadata_fields" and item.get("status") == "COMPLETE"
    ]
    assert complete_updates, "Must have at least one COMPLETE update for IntelligenceMetadata"
    full_record.update(complete_updates[-1])
    return full_record


# ---------------------------------------------------------------------------
# CON-01: IntelligenceMetadata has all 15 stable fields
# ---------------------------------------------------------------------------

_STABLE_METADATA_FIELDS = [
    "intelligence_version",
    "intelligence_job_id",
    "client_id",
    "audit_id",
    "audit_execution_id",
    "config_version",
    "aggregation_version",
    "status",
    "composite_score",
    "score_label",
    "endpoint_count",
    "s3_artifact_ref",
    "aggregate_set_hash",
    "created_at",
    "completed_at",
]


def test_con_01_intelligence_metadata_all_stable_fields_present(meta_item: dict) -> None:
    """CON-01: IntelligenceMetadata COMPLETE update includes all 15 stable Phase 6 fields."""
    missing = [f for f in _STABLE_METADATA_FIELDS if f not in meta_item]
    assert not missing, f"IntelligenceMetadata missing stable fields: {missing}"


# ---------------------------------------------------------------------------
# CON-02: IntelligenceMetadata field types
# ---------------------------------------------------------------------------


def test_con_02_intelligence_metadata_field_types(meta_item: dict) -> None:
    """CON-02: IntelligenceMetadata stable fields are correct types."""
    assert isinstance(meta_item["intelligence_version"], str)
    assert isinstance(meta_item["intelligence_job_id"], str)
    assert isinstance(meta_item["client_id"], str)
    assert isinstance(meta_item["audit_id"], str)
    assert isinstance(meta_item["audit_execution_id"], str)
    assert isinstance(meta_item["config_version"], str)
    assert isinstance(meta_item["aggregation_version"], str)
    assert isinstance(meta_item["status"], str)
    assert isinstance(meta_item["composite_score"], str), "composite_score must be string"
    assert isinstance(meta_item["score_label"], str)
    assert isinstance(meta_item["endpoint_count"], int)
    assert isinstance(meta_item["s3_artifact_ref"], str)
    assert isinstance(meta_item["aggregate_set_hash"], str)
    assert isinstance(meta_item["created_at"], str)
    assert isinstance(meta_item["completed_at"], str)


# ---------------------------------------------------------------------------
# CON-03: intelligence_version = "intel_v1"
# ---------------------------------------------------------------------------


def test_con_03_intelligence_version_is_intel_v1(artifact: dict, meta_item: dict) -> None:
    """CON-03: Both artifact and IntelligenceMetadata use intelligence_version = intel_v1."""
    assert artifact["intelligence_version"] == "intel_v1"
    assert meta_item["intelligence_version"] == "intel_v1"


# ---------------------------------------------------------------------------
# CON-04: audit_reliability_summary completeness
# ---------------------------------------------------------------------------

_AUDIT_SUMMARY_REQUIRED = [
    "total_executions", "total_pass", "total_fail", "total_timeout",
    "total_network_failure", "audit_success_rate", "endpoint_count",
    "audit_latency_mean_ms", "audit_latency_p95_ms", "audit_latency_p99_ms",
    "source_field_refs",
]


def test_con_04_audit_reliability_summary_completeness(artifact: dict) -> None:
    """CON-04: audit_reliability_summary has all required fields."""
    summary = artifact.get("audit_reliability_summary", {})
    missing = [f for f in _AUDIT_SUMMARY_REQUIRED if f not in summary]
    assert not missing, f"audit_reliability_summary missing fields: {missing}"


# ---------------------------------------------------------------------------
# CON-05: composite_score.component_breakdown sub-field completeness
# ---------------------------------------------------------------------------

_BREAKDOWN_LAYERS = ["reliability", "stability", "burst", "consistency"]
_BREAKDOWN_SUBFIELDS = ["weight", "value", "description"]


def test_con_05_composite_score_component_breakdown_completeness(artifact: dict) -> None:
    """CON-05: composite_score.component_breakdown has all 4 layers with weight/value/description."""  # noqa: E501
    breakdown = artifact.get("composite_score", {}).get("component_breakdown", {})
    for layer in _BREAKDOWN_LAYERS:
        assert layer in breakdown, f"component_breakdown missing layer: {layer}"
        for sub in _BREAKDOWN_SUBFIELDS:
            assert sub in breakdown[layer], (
                f"component_breakdown.{layer} missing sub-field: {sub}"
            )
        assert isinstance(breakdown[layer]["description"], str)
        assert len(breakdown[layer]["description"]) > 0


# ---------------------------------------------------------------------------
# CON-06: input_lineage completeness
# ---------------------------------------------------------------------------

_INPUT_LINEAGE_REQUIRED = [
    "aggregate_set_hash", "aggregation_job_id", "aggregation_version",
    "aggregate_set_completion_created_at", "endpoint_aggregate_count",
    "source_raw_result_count",
]

_LINEAGE_MANIFEST_REQUIRED = ["manifest_scope", "source_ref_count", "manifest_hash"]


def test_con_06_input_lineage_completeness(artifact: dict) -> None:
    """CON-06: input_lineage has all required fields including audit_lineage_manifest_ref."""
    lineage = artifact.get("input_lineage", {})
    missing = [f for f in _INPUT_LINEAGE_REQUIRED if f not in lineage]
    assert not missing, f"input_lineage missing fields: {missing}"
    manifest = lineage.get("audit_lineage_manifest_ref", {})
    missing_manifest = [f for f in _LINEAGE_MANIFEST_REQUIRED if f not in manifest]
    assert not missing_manifest, (
        f"input_lineage.audit_lineage_manifest_ref missing: {missing_manifest}"
    )


# ---------------------------------------------------------------------------
# CON-07: endpoints[*].reliability_metrics completeness
# ---------------------------------------------------------------------------

_RELIABILITY_METRICS_REQUIRED = [
    "execution_count", "pass_count", "fail_count", "timeout_count",
    "success_rate", "success_rate_numerator", "success_rate_denominator",
    "latency_min_ms", "latency_max_ms", "latency_mean_ms", "latency_median_ms",
    "latency_p95_ms", "latency_p99_ms", "latency_count",
    "failure_classification_breakdown", "http_response_distribution", "source_field_refs",
]


def test_con_07_endpoint_reliability_metrics_completeness(artifact: dict) -> None:
    """CON-07: Every endpoint has reliability_metrics with all required fields."""
    endpoints = artifact.get("endpoints", [])
    assert endpoints, "endpoints array must be non-empty"
    for ep in endpoints:
        metrics = ep.get("reliability_metrics", {})
        missing = [f for f in _RELIABILITY_METRICS_REQUIRED if f not in metrics]
        assert not missing, (
            f"endpoint {ep.get('endpoint_id')} reliability_metrics missing: {missing}"
        )


# ---------------------------------------------------------------------------
# CON-08: endpoints[*].stability_analysis completeness
# ---------------------------------------------------------------------------

_STABILITY_ANALYSIS_REQUIRED = [
    "success_rate_stability_label", "latency_stability_label", "methodology_trace",
]

_METHODOLOGY_TRACE_REQUIRED = [
    "algorithm", "algorithm_version", "inputs", "thresholds",
    "intermediate_values", "label_determination",
]


def test_con_08_endpoint_stability_analysis_completeness(artifact: dict) -> None:
    """CON-08: Every endpoint has stability_analysis with labels and methodology_trace."""
    for ep in artifact.get("endpoints", []):
        analysis = ep.get("stability_analysis", {})
        missing = [f for f in _STABILITY_ANALYSIS_REQUIRED if f not in analysis]
        assert not missing, (
            f"endpoint {ep.get('endpoint_id')} stability_analysis missing: {missing}"
        )
        trace = analysis.get("methodology_trace", {})
        missing_trace = [f for f in _METHODOLOGY_TRACE_REQUIRED if f not in trace]
        assert not missing_trace, (
            f"endpoint {ep.get('endpoint_id')} stability methodology_trace missing: {missing_trace}"
        )


# ---------------------------------------------------------------------------
# CON-09: endpoints[*].burst_analysis completeness
# ---------------------------------------------------------------------------

_BURST_ANALYSIS_REQUIRED = [
    "failure_burst_label", "latency_spike_label", "methodology_trace",
]


def test_con_09_endpoint_burst_analysis_completeness(artifact: dict) -> None:
    """CON-09: Every endpoint has burst_analysis with labels and methodology_trace."""
    for ep in artifact.get("endpoints", []):
        analysis = ep.get("burst_analysis", {})
        missing = [f for f in _BURST_ANALYSIS_REQUIRED if f not in analysis]
        assert not missing, (
            f"endpoint {ep.get('endpoint_id')} burst_analysis missing: {missing}"
        )
        trace = analysis.get("methodology_trace", {})
        missing_trace = [f for f in _METHODOLOGY_TRACE_REQUIRED if f not in trace]
        assert not missing_trace, (
            f"endpoint {ep.get('endpoint_id')} burst methodology_trace missing: {missing_trace}"
        )


# ---------------------------------------------------------------------------
# CON-10: endpoints[*].consistency_analysis completeness
# ---------------------------------------------------------------------------

_CONSISTENCY_ANALYSIS_REQUIRED = ["consistency_label", "methodology_trace"]


def test_con_10_endpoint_consistency_analysis_completeness(artifact: dict) -> None:
    """CON-10: Every endpoint has consistency_analysis with label and methodology_trace."""
    for ep in artifact.get("endpoints", []):
        analysis = ep.get("consistency_analysis", {})
        missing = [f for f in _CONSISTENCY_ANALYSIS_REQUIRED if f not in analysis]
        assert not missing, (
            f"endpoint {ep.get('endpoint_id')} consistency_analysis missing: {missing}"
        )
        trace = analysis.get("methodology_trace", {})
        missing_trace = [f for f in _METHODOLOGY_TRACE_REQUIRED if f not in trace]
        assert not missing_trace, (
            f"endpoint {ep.get('endpoint_id')} consistency methodology_trace missing: "
            f"{missing_trace}"
        )


# ---------------------------------------------------------------------------
# CON-11: endpoints[*].endpoint_score completeness
# ---------------------------------------------------------------------------

_ENDPOINT_SCORE_REQUIRED = [
    "composite_score", "reliability_score", "stability_score",
    "burst_score", "consistency_score", "score_derivation",
]

_SCORE_DERIVATION_REQUIRED = [
    "reliability_score_source", "stability_score_formula",
    "burst_score_formula", "consistency_score_formula", "composite_score_formula",
]


def test_con_11_endpoint_score_completeness(artifact: dict) -> None:
    """CON-11: Every endpoint has endpoint_score with all score components and derivation."""
    for ep in artifact.get("endpoints", []):
        score = ep.get("endpoint_score", {})
        missing = [f for f in _ENDPOINT_SCORE_REQUIRED if f not in score]
        assert not missing, (
            f"endpoint {ep.get('endpoint_id')} endpoint_score missing: {missing}"
        )
        derivation = score.get("score_derivation", {})
        missing_deriv = [f for f in _SCORE_DERIVATION_REQUIRED if f not in derivation]
        assert not missing_deriv, (
            f"endpoint {ep.get('endpoint_id')} score_derivation missing: {missing_deriv}"
        )


# ---------------------------------------------------------------------------
# CON-12: score_label bounded value set
# ---------------------------------------------------------------------------

_VALID_SCORE_LABELS = {"HIGH_CONFIDENCE", "MODERATE_CONFIDENCE", "LOW_CONFIDENCE"}


def test_con_12_score_label_in_bounded_set(artifact: dict, meta_item: dict) -> None:
    """CON-12: score_label at both artifact and metadata level is in the bounded set."""
    cs_label = artifact.get("composite_score", {}).get("score_label")
    assert cs_label in _VALID_SCORE_LABELS, (
        f"composite_score.score_label {cs_label!r} not in {_VALID_SCORE_LABELS}"
    )
    meta_label = meta_item.get("score_label")
    assert meta_label in _VALID_SCORE_LABELS, (
        f"IntelligenceMetadata.score_label {meta_label!r} not in {_VALID_SCORE_LABELS}"
    )


# ---------------------------------------------------------------------------
# CON-13: composite_score.value in [0.0, 1.0]
# ---------------------------------------------------------------------------


def test_con_13_composite_score_value_in_range(artifact: dict, result: dict) -> None:
    """CON-13: composite_score.value and result composite_score are in [0.0, 1.0]."""
    value_str = artifact.get("composite_score", {}).get("value")
    assert value_str is not None, "composite_score.value must be present"
    value = Decimal(str(value_str))
    assert Decimal("0.0") <= value <= Decimal("1.0"), (
        f"composite_score.value {value} out of [0.0, 1.0]"
    )
    result_score = Decimal(str(result.get("composite_score", "0")))
    assert Decimal("0.0") <= result_score <= Decimal("1.0"), (
        f"result composite_score {result_score} out of [0.0, 1.0]"
    )


# ---------------------------------------------------------------------------
# CON-14: stability labels in bounded set
# ---------------------------------------------------------------------------

_VALID_STABILITY_LABELS = {"STABLE", "DEGRADED", "INSUFFICIENT_DATA"}


def test_con_14_stability_labels_in_bounded_set(artifact: dict) -> None:
    """CON-14: All stability labels are within the bounded set from Section 6."""
    for ep in artifact.get("endpoints", []):
        analysis = ep.get("stability_analysis", {})
        for field in ("success_rate_stability_label", "latency_stability_label"):
            label = analysis.get(field)
            assert label in _VALID_STABILITY_LABELS, (
                f"endpoint {ep.get('endpoint_id')} {field}={label!r} not in "
                f"{_VALID_STABILITY_LABELS}"
            )


# ---------------------------------------------------------------------------
# CON-15: burst labels in bounded set
# ---------------------------------------------------------------------------

_VALID_BURST_LABELS = {"NO_BURST_DETECTED", "BURST_SUSPECTED", "INSUFFICIENT_DATA"}
_VALID_SPIKE_LABELS = {"NO_SPIKE_DETECTED", "SPIKE_SUSPECTED", "INSUFFICIENT_DATA"}


def test_con_15_burst_labels_in_bounded_set(artifact: dict) -> None:
    """CON-15: All failure_burst_label and latency_spike_label are within bounded sets."""
    for ep in artifact.get("endpoints", []):
        analysis = ep.get("burst_analysis", {})
        burst_label = analysis.get("failure_burst_label")
        assert burst_label in _VALID_BURST_LABELS, (
            f"endpoint {ep.get('endpoint_id')} failure_burst_label={burst_label!r} not in "
            f"{_VALID_BURST_LABELS}"
        )
        spike_label = analysis.get("latency_spike_label")
        assert spike_label in _VALID_SPIKE_LABELS, (
            f"endpoint {ep.get('endpoint_id')} latency_spike_label={spike_label!r} not in "
            f"{_VALID_SPIKE_LABELS}"
        )


# ---------------------------------------------------------------------------
# CON-16: consistency label in bounded set
# ---------------------------------------------------------------------------

_VALID_CONSISTENCY_LABELS = {"CONSISTENT", "INCONSISTENT", "INSUFFICIENT_DATA"}


def test_con_16_consistency_label_in_bounded_set(artifact: dict) -> None:
    """CON-16: All consistency_label values are within the bounded set."""
    for ep in artifact.get("endpoints", []):
        analysis = ep.get("consistency_analysis", {})
        label = analysis.get("consistency_label")
        assert label in _VALID_CONSISTENCY_LABELS, (
            f"endpoint {ep.get('endpoint_id')} consistency_label={label!r} not in "
            f"{_VALID_CONSISTENCY_LABELS}"
        )


# ---------------------------------------------------------------------------
# CON-17: endpoints sorted lexicographically by endpoint_id
# ---------------------------------------------------------------------------


def test_con_17_endpoints_sorted_lexicographically(artifact: dict) -> None:
    """CON-17: endpoints array is in lexicographic ascending order by endpoint_id."""
    endpoint_ids = [ep.get("endpoint_id") for ep in artifact.get("endpoints", [])]
    assert endpoint_ids == sorted(endpoint_ids), (
        f"endpoints not sorted lexicographically: {endpoint_ids}"
    )
    # Verify: ep_alpha before ep_beta
    assert endpoint_ids == ["ep_alpha", "ep_beta"]


# ---------------------------------------------------------------------------
# CON-18: 3 decimal places for all score fields
# ---------------------------------------------------------------------------

_THREE_DECIMAL_PATTERN = r"^\d+\.\d{3}$"


def _is_three_decimal(val: Any) -> bool:
    if not isinstance(val, str):
        return False
    import re
    return bool(re.match(_THREE_DECIMAL_PATTERN, val))


def test_con_18_three_decimal_places_precision(artifact: dict) -> None:
    """CON-18: All score fields (composite_score.value, success_rate, endpoint scores) use 3dp."""
    import re
    pat = re.compile(r"^\d+\.\d{3}$")

    # Audit composite
    cs_value = artifact.get("composite_score", {}).get("value")
    assert pat.match(str(cs_value)), f"composite_score.value {cs_value!r} not 3dp"

    # Per-endpoint scores
    for ep in artifact.get("endpoints", []):
        score = ep.get("endpoint_score", {})
        for field in ("composite_score", "reliability_score", "stability_score",
                      "burst_score", "consistency_score"):
            val = score.get(field)
            assert pat.match(str(val)), (
                f"endpoint {ep.get('endpoint_id')} {field}={val!r} not 3dp"
            )
        metrics = ep.get("reliability_metrics", {})
        sr = metrics.get("success_rate")
        assert pat.match(str(sr)), (
            f"endpoint {ep.get('endpoint_id')} success_rate={sr!r} not 3dp"
        )

    # Audit success rate
    audit_sr = artifact.get("audit_reliability_summary", {}).get("audit_success_rate")
    assert pat.match(str(audit_sr)), f"audit_reliability_summary.audit_success_rate={audit_sr!r} not 3dp"  # noqa: E501


# ---------------------------------------------------------------------------
# CON-19: methodology_disclosure completeness
# ---------------------------------------------------------------------------

_METHODOLOGY_DISCLOSURE_REQUIRED = [
    "intelligence_version",
    "scoring",
    "stability_label_definitions",
    "burst_label_definitions",
    "consistency_label_definitions",
    "label_to_score_mapping",
    "limitations",
]

_SCORING_REQUIRED = [
    "composite_score_range",
    "rollup",
    "precision",
    "component_weights",
    "per_endpoint_formula",
]


def test_con_19_methodology_disclosure_completeness(artifact: dict) -> None:
    """CON-19: methodology_disclosure has all required sub-sections per Section 3.2."""
    disclosure = artifact.get("methodology_disclosure", {})
    missing = [f for f in _METHODOLOGY_DISCLOSURE_REQUIRED if f not in disclosure]
    assert not missing, f"methodology_disclosure missing fields: {missing}"
    scoring = disclosure.get("scoring", {})
    missing_scoring = [f for f in _SCORING_REQUIRED if f not in scoring]
    assert not missing_scoring, f"methodology_disclosure.scoring missing: {missing_scoring}"
    assert disclosure.get("limitations") is not None, "limitations must be present"
    assert isinstance(disclosure["limitations"], list), "limitations must be a list"


# ---------------------------------------------------------------------------
# CON-20: Breaking change detection — field removal
# ---------------------------------------------------------------------------


def _validate_artifact_structure(a: dict[str, Any]) -> None:
    """Compatibility gate guard: raise if any Section 3.2 stable field is absent."""
    _REQUIRED_TOP_LEVEL = [
        "intelligence_version", "aggregation_version", "client_id", "audit_id",
        "audit_execution_id", "config_version", "intelligence_job_id", "generated_at",
        "generator_version", "audit_reliability_summary", "composite_score",
        "input_lineage", "endpoints", "methodology_disclosure",
    ]
    missing = [f for f in _REQUIRED_TOP_LEVEL if f not in a]
    if missing:
        raise AssertionError(f"Breaking change: removed stable fields {missing}")

    cs = a.get("composite_score", {})
    cs_required = [
        "value", "score_label", "intelligence_version", "aggregation_version",
        "aggregate_set_hash", "endpoint_count", "component_breakdown",
    ]
    cs_missing = [f for f in cs_required if f not in cs]
    if cs_missing:
        raise AssertionError(f"Breaking change: composite_score missing {cs_missing}")


def test_con_20_breaking_change_detection_field_removal(artifact: dict) -> None:
    """CON-20: The compatibility guard detects removal of a stable field."""
    # Baseline: artifact passes guard
    _validate_artifact_structure(artifact)

    # Simulate breaking change: remove a stable top-level field
    mutated = {k: v for k, v in artifact.items() if k != "composite_score"}
    with pytest.raises(AssertionError, match="Breaking change"):
        _validate_artifact_structure(mutated)


# ---------------------------------------------------------------------------
# CON-21: Breaking change detection — type change
# ---------------------------------------------------------------------------


def test_con_21_breaking_change_detection_type_change(artifact: dict) -> None:
    """CON-21: The compatibility guard detects when a stable field changes type."""
    def _guard_composite_score_value_is_string(a: dict[str, Any]) -> None:
        cs_value = a.get("composite_score", {}).get("value")
        if not isinstance(cs_value, str):
            raise AssertionError(
                f"Breaking change: composite_score.value must be str, got {type(cs_value)}"
            )

    # Baseline passes
    _guard_composite_score_value_is_string(artifact)

    # Type change: value becomes int
    mutated_cs = {**artifact["composite_score"], "value": 1}
    mutated = {**artifact, "composite_score": mutated_cs}
    with pytest.raises(AssertionError, match="Breaking change"):
        _guard_composite_score_value_is_string(mutated)


# ---------------------------------------------------------------------------
# CON-22: Non-breaking addition does not trigger the guard
# ---------------------------------------------------------------------------


def test_con_22_non_breaking_addition_allowed(artifact: dict) -> None:
    """CON-22: Adding a new field to the artifact does not trigger the compatibility guard."""
    extended = {**artifact, "future_field": "new_value_not_in_contract_v1"}
    _validate_artifact_structure(extended)  # Must NOT raise


# ---------------------------------------------------------------------------
# CON-23: methodology_disclosure.scoring.component_weights correct
# ---------------------------------------------------------------------------

_EXPECTED_WEIGHTS: dict[str, float] = {
    "reliability": 0.50,
    "stability": 0.20,
    "burst": 0.15,
    "consistency": 0.15,
}


def test_con_23_component_weights_in_methodology_disclosure(artifact: dict) -> None:
    """CON-23: methodology_disclosure.scoring.component_weights matches intel_v1 spec."""
    weights = (
        artifact.get("methodology_disclosure", {})
        .get("scoring", {})
        .get("component_weights", {})
    )
    for component, expected in _EXPECTED_WEIGHTS.items():
        actual = weights.get(component)
        assert actual is not None, f"component_weights.{component} missing"
        assert abs(float(actual) - expected) < 1e-9, (
            f"component_weights.{component}: expected {expected}, got {actual}"
        )


# ---------------------------------------------------------------------------
# CON-24: INSUFFICIENT_DATA label-to-score = 0.5 in methodology_disclosure
# ---------------------------------------------------------------------------


def test_con_24_insufficient_data_label_to_score_is_neutral(artifact: dict) -> None:
    """CON-24: INSUFFICIENT_DATA maps to 0.5 (neutral) in methodology_disclosure."""
    mapping = artifact.get("methodology_disclosure", {}).get("label_to_score_mapping", {})
    insufficient_data_score = mapping.get("INSUFFICIENT_DATA")
    assert insufficient_data_score is not None, (
        "label_to_score_mapping.INSUFFICIENT_DATA must be present"
    )
    score_val = Decimal(str(insufficient_data_score))
    assert score_val == Decimal("0.5"), (
        f"INSUFFICIENT_DATA must map to 0.5 (neutral), got {insufficient_data_score!r}"
    )


# ---------------------------------------------------------------------------
# Contract serialization: artifact must be JSON-serializable (for S3 write)
# ---------------------------------------------------------------------------


def test_artifact_json_serializable(artifact: dict) -> None:
    """Artifact must be serializable with json.dumps(sort_keys=True, default=str)."""
    serialized = json.dumps(artifact, sort_keys=True, default=str)
    assert serialized, "Artifact must serialize to non-empty JSON"
    round_trip = json.loads(serialized)
    assert round_trip.get("intelligence_version") == "intel_v1"
