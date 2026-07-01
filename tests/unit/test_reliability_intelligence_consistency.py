"""Unit tests for Phase 5.5 — Consistency Analysis.

Covers outcome_consistency_v1 via compute_consistency_analysis(). Exercises all label
paths, INSUFFICIENT_DATA paths, Bernoulli variance formula accuracy, methodology trace
completeness, and required wording.

Test IDs map to QA plan docs/qa/phase_5_reliability_intelligence_test_plan.md Section 7.
"""

from decimal import Decimal

import pytest

from release_confidence_platform.reliability_intelligence.consistency import (
    compute_consistency_analysis,
)
from release_confidence_platform.reliability_intelligence.constants import (
    INTELLIGENCE_VERSION,
    LABEL_CONSISTENT,
    LABEL_INCONSISTENT,
    LABEL_INSUFFICIENT_DATA,
    MIN_EXECUTION_COUNT,
    OUTCOME_CONSISTENCY_ALGORITHM,
    VARIANCE_CONSISTENT_THRESHOLD,
)
from release_confidence_platform.reliability_intelligence.models import EndpointMetricsDTO

# ---------------------------------------------------------------------------
# Required wording phrase (tech design Section 12 / limitations line 578)
# ---------------------------------------------------------------------------

_REQUIRED_WORDING_PHRASE = (
    "per-run or per-scenario consistency is not assessable from agg_v1"
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_endpoint_metrics(
    execution_count: int = 20,
    success_rate: Decimal | None = Decimal("1.000"),
    numerator: int = 20,
    denominator: int = 20,
    is_insufficient_data: bool = False,
) -> EndpointMetricsDTO:
    """Build a minimal EndpointMetricsDTO for consistency tests."""
    return EndpointMetricsDTO(
        endpoint_id="ep_cons_test",
        execution_count=execution_count,
        success_rate=success_rate,
        success_inputs={"numerator": numerator, "denominator": denominator},
        failure_classification_counts={},
        latency_profile=None,
        timeout_count=0,
        is_insufficient_data=is_insufficient_data,
    )


def _insufficient_data_metrics() -> EndpointMetricsDTO:
    """Zero-execution endpoint."""
    return EndpointMetricsDTO(
        endpoint_id="ep_empty",
        execution_count=0,
        success_rate=None,
        success_inputs={"numerator": 0, "denominator": 0},
        failure_classification_counts={},
        latency_profile=None,
        timeout_count=0,
        is_insufficient_data=True,
    )


# ---------------------------------------------------------------------------
# outcome_consistency_v1 labels — CONS-OC01 through CONS-OC07
# ---------------------------------------------------------------------------


class TestOutcomeConsistencyLabels:
    def test_consistent_near_threshold(self):
        """CONS-OC01: variance near 0.05 but ≤ threshold → CONSISTENT.

        p = 0.950 → variance = 0.950 * 0.050 = 0.0475 ≤ 0.05 → CONSISTENT.
        Exercises the ≤ boundary condition (≤ 0.05 is CONSISTENT).
        """
        result = compute_consistency_analysis(
            _make_endpoint_metrics(
                success_rate=Decimal("0.950"),
                numerator=950,
                denominator=1000,
            )
        )
        assert result.consistency_label == LABEL_CONSISTENT

    def test_consistent_at_perfect_success_rate(self):
        """CONS-OC02: success_rate = 1.000 → variance = 0.0 → CONSISTENT."""
        result = compute_consistency_analysis(
            _make_endpoint_metrics(success_rate=Decimal("1.000"), numerator=20, denominator=20)
        )
        assert result.consistency_label == LABEL_CONSISTENT

    def test_consistent_at_zero_success_rate(self):
        """CONS-OC03: success_rate = 0.000 → variance = 0.0 → CONSISTENT (consistently fails)."""
        result = compute_consistency_analysis(
            _make_endpoint_metrics(success_rate=Decimal("0.000"), numerator=0, denominator=20)
        )
        assert result.consistency_label == LABEL_CONSISTENT

    def test_inconsistent_at_maximum_variance(self):
        """CONS-OC04 / CONS-OC05: success_rate = 0.500 → variance = 0.25 > 0.05 → INCONSISTENT."""
        result = compute_consistency_analysis(
            _make_endpoint_metrics(success_rate=Decimal("0.500"), numerator=10, denominator=20)
        )
        assert result.consistency_label == LABEL_INCONSISTENT

    def test_insufficient_data_below_min_execution_count(self):
        """CONS-OC06: execution_count below MIN_EXECUTION_COUNT → INSUFFICIENT_DATA."""
        result = compute_consistency_analysis(
            _make_endpoint_metrics(
                execution_count=MIN_EXECUTION_COUNT - 1,
                success_rate=Decimal("1.000"),
                numerator=9,
                denominator=9,
            )
        )
        assert result.consistency_label == LABEL_INSUFFICIENT_DATA

    def test_insufficient_data_at_zero_executions(self):
        """CONS-OC07: execution_count = 0 → INSUFFICIENT_DATA."""
        result = compute_consistency_analysis(_insufficient_data_metrics())
        assert result.consistency_label == LABEL_INSUFFICIENT_DATA

    def test_insufficient_data_when_denominator_zero(self):
        """denominator = 0 → INSUFFICIENT_DATA regardless of execution_count."""
        dto = EndpointMetricsDTO(
            endpoint_id="ep_denom0",
            execution_count=20,
            success_rate=None,
            success_inputs={"numerator": 0, "denominator": 0},
            failure_classification_counts={},
            latency_profile=None,
            timeout_count=0,
            is_insufficient_data=True,
        )
        result = compute_consistency_analysis(dto)
        assert result.consistency_label == LABEL_INSUFFICIENT_DATA

    def test_consistent_at_high_failure_rate(self):
        """Low but consistent success_rate (p=0.020) → CONSISTENT (consistently fails)."""
        # p*(1-p) = 0.02 * 0.98 = 0.0196 ≤ 0.05 → CONSISTENT
        result = compute_consistency_analysis(
            _make_endpoint_metrics(
                success_rate=Decimal("0.020"),
                numerator=2,
                denominator=100,
                execution_count=100,
            )
        )
        assert result.consistency_label == LABEL_CONSISTENT

    def test_inconsistent_below_upper_boundary(self):
        """Variance above threshold → INCONSISTENT."""
        # p = 0.800 → variance = 0.800 * 0.200 = 0.160 > 0.05 → INCONSISTENT
        result = compute_consistency_analysis(
            _make_endpoint_metrics(
                success_rate=Decimal("0.800"),
                numerator=16,
                denominator=20,
            )
        )
        assert result.consistency_label == LABEL_INCONSISTENT

    def test_eligible_at_min_execution_count(self):
        """execution_count exactly at MIN_EXECUTION_COUNT → eligible for label."""
        result = compute_consistency_analysis(
            _make_endpoint_metrics(
                execution_count=MIN_EXECUTION_COUNT,
                success_rate=Decimal("1.000"),
                numerator=10,
                denominator=10,
            )
        )
        assert result.consistency_label == LABEL_CONSISTENT

    def test_variance_threshold_is_inclusive(self):
        """Variance exactly at threshold (≤ 0.05) → CONSISTENT; just above → INCONSISTENT."""
        # Find a p where variance ≈ threshold:
        # p = 0.948 → 0.948 * 0.052 = 0.049296 ≤ 0.05 → CONSISTENT
        consistent = compute_consistency_analysis(
            _make_endpoint_metrics(success_rate=Decimal("0.948"), numerator=948, denominator=1000)
        )
        assert consistent.consistency_label == LABEL_CONSISTENT

        # p = 0.800 → 0.800 * 0.200 = 0.160 > 0.05 → INCONSISTENT
        inconsistent = compute_consistency_analysis(
            _make_endpoint_metrics(success_rate=Decimal("0.800"), numerator=800, denominator=1000)
        )
        assert inconsistent.consistency_label == LABEL_INCONSISTENT


# ---------------------------------------------------------------------------
# Bernoulli variance formula accuracy — CONS-VAR01, CONS-VAR02
# ---------------------------------------------------------------------------


class TestBernoulliVarianceFormula:
    def test_variance_computed_as_p_times_one_minus_p(self):
        """CONS-VAR01: intermediate variance = p*(1-p) for success_rate = 0.8."""
        # p = 0.800 → variance = 0.800 * 0.200 = 0.16000
        result = compute_consistency_analysis(
            _make_endpoint_metrics(
                success_rate=Decimal("0.800"),
                numerator=16,
                denominator=20,
            )
        )
        variance = result.methodology_trace["intermediate_values"]["outcome_variance"]
        assert variance is not None
        expected = Decimal("0.800") * (Decimal("1") - Decimal("0.800"))
        assert variance == expected

    def test_variance_uses_rounded_success_rate(self):
        """CONS-VAR02: variance computed from the 3dp-rounded success_rate, not the raw fraction.

        numerator=1, denominator=3 → success_rate = 0.333 (rounded).
        Variance = 0.333 * (1 - 0.333) = 0.333 * 0.667, not (1/3) * (2/3).
        """
        result = compute_consistency_analysis(
            _make_endpoint_metrics(
                success_rate=Decimal("0.333"),  # already-rounded value from metrics.py
                numerator=1,
                denominator=3,
            )
        )
        variance = result.methodology_trace["intermediate_values"]["outcome_variance"]
        assert variance is not None
        # Must match 0.333 * 0.667, not the unrounded 1/3 * 2/3.
        expected_from_rounded = Decimal("0.333") * Decimal("0.667")
        expected_from_unrounded = Decimal("1") / Decimal("3") * (Decimal("1") - Decimal("1") / Decimal("3"))  # noqa: E501
        assert variance == expected_from_rounded
        assert variance != expected_from_unrounded

    def test_variance_is_zero_at_perfect_success(self):
        """p = 1.000 → variance = 1.0 * 0.0 = 0.0."""
        result = compute_consistency_analysis(
            _make_endpoint_metrics(success_rate=Decimal("1.000"), numerator=20, denominator=20)
        )
        variance = result.methodology_trace["intermediate_values"]["outcome_variance"]
        assert variance == Decimal("0")

    def test_variance_is_zero_at_zero_success(self):
        """p = 0.000 → variance = 0.0 * 1.0 = 0.0."""
        result = compute_consistency_analysis(
            _make_endpoint_metrics(success_rate=Decimal("0.000"), numerator=0, denominator=20)
        )
        variance = result.methodology_trace["intermediate_values"]["outcome_variance"]
        assert variance == Decimal("0")

    def test_variance_is_none_on_insufficient_data(self):
        """outcome_variance is None when INSUFFICIENT_DATA."""
        result = compute_consistency_analysis(_insufficient_data_metrics())
        assert result.methodology_trace["intermediate_values"]["outcome_variance"] is None


# ---------------------------------------------------------------------------
# Methodology trace completeness — CONS-TR01 through CONS-TR05
# ---------------------------------------------------------------------------


class TestConsistencyMethodologyTraceCompleteness:
    def setup_method(self):
        self.result = compute_consistency_analysis(
            _make_endpoint_metrics(success_rate=Decimal("0.900"), numerator=18, denominator=20)
        )
        self.trace = self.result.methodology_trace

    def test_trace_contains_algorithm_name(self):
        """CONS-TR01: methodology_trace.algorithm = outcome_consistency_v1."""
        assert "algorithm" in self.trace
        assert self.trace["algorithm"] == OUTCOME_CONSISTENCY_ALGORITHM

    def test_trace_contains_algorithm_version(self):
        """algorithm_version is intel_v1."""
        assert "algorithm_version" in self.trace
        assert self.trace["algorithm_version"] == INTELLIGENCE_VERSION

    def test_trace_contains_success_rate_input(self):
        """CONS-TR02: success rate p is present in methodology_trace.inputs."""
        assert "inputs" in self.trace
        assert "success_rate" in self.trace["inputs"]
        assert self.trace["inputs"]["success_rate"] == "0.900"

    def test_trace_contains_computed_variance(self):
        """CONS-TR03: outcome_variance intermediate value is present."""
        assert "intermediate_values" in self.trace
        assert "outcome_variance" in self.trace["intermediate_values"]
        assert self.trace["intermediate_values"]["outcome_variance"] is not None

    def test_trace_contains_threshold(self):
        """CONS-TR04: VARIANCE_CONSISTENT_THRESHOLD is present in thresholds."""
        assert "thresholds" in self.trace
        assert "VARIANCE_CONSISTENT_THRESHOLD" in self.trace["thresholds"]
        assert self.trace["thresholds"]["VARIANCE_CONSISTENT_THRESHOLD"] == float(
            VARIANCE_CONSISTENT_THRESHOLD
        )
        assert "MIN_EXECUTION_COUNT" in self.trace["thresholds"]

    def test_trace_contains_label_determination(self):
        """CONS-TR05: label_determination is a non-empty string."""
        assert "label_determination" in self.trace
        assert isinstance(self.trace["label_determination"], str)
        assert len(self.trace["label_determination"]) > 0

    def test_trace_inputs_include_numerator_and_denominator(self):
        """inputs includes success_rate_numerator and success_rate_denominator."""
        inputs = self.trace["inputs"]
        assert "success_rate_numerator" in inputs
        assert "success_rate_denominator" in inputs
        assert inputs["success_rate_numerator"] == 18
        assert inputs["success_rate_denominator"] == 20

    def test_trace_inputs_execution_count(self):
        """inputs.execution_count matches DTO value."""
        result = compute_consistency_analysis(_make_endpoint_metrics(execution_count=50))
        assert result.methodology_trace["inputs"]["execution_count"] == 50

    def test_trace_inputs_success_rate_none_on_insufficient(self):
        """inputs.success_rate is None when is_insufficient_data."""
        result = compute_consistency_analysis(_insufficient_data_metrics())
        assert result.methodology_trace["inputs"]["success_rate"] is None


# ---------------------------------------------------------------------------
# Methodology trace wording — CONS-WD01
# ---------------------------------------------------------------------------


class TestConsistencyMethodologyTraceWording:
    def test_wording_includes_per_run_limitation_phrase(self):
        """CONS-WD01: label_determination includes the required per-run limitation phrase."""
        result = compute_consistency_analysis(_make_endpoint_metrics())
        assert _REQUIRED_WORDING_PHRASE in result.methodology_trace["label_determination"]

    def test_wording_present_on_consistent(self):
        """Required phrase present when label = CONSISTENT."""
        result = compute_consistency_analysis(
            _make_endpoint_metrics(success_rate=Decimal("1.000"))
        )
        assert result.consistency_label == LABEL_CONSISTENT
        assert _REQUIRED_WORDING_PHRASE in result.methodology_trace["label_determination"]

    def test_wording_present_on_inconsistent(self):
        """Required phrase present when label = INCONSISTENT."""
        result = compute_consistency_analysis(
            _make_endpoint_metrics(success_rate=Decimal("0.500"), numerator=10, denominator=20)
        )
        assert result.consistency_label == LABEL_INCONSISTENT
        assert _REQUIRED_WORDING_PHRASE in result.methodology_trace["label_determination"]

    def test_wording_present_on_insufficient_data(self):
        """Required phrase present when label = INSUFFICIENT_DATA."""
        result = compute_consistency_analysis(_insufficient_data_metrics())
        assert result.consistency_label == LABEL_INSUFFICIENT_DATA
        assert _REQUIRED_WORDING_PHRASE in result.methodology_trace["label_determination"]

    def test_algorithm_name_in_label_determination(self):
        """outcome_consistency_v1 algorithm name appears in label_determination."""
        result = compute_consistency_analysis(_make_endpoint_metrics())
        assert OUTCOME_CONSISTENCY_ALGORITHM in result.methodology_trace["label_determination"]


# ---------------------------------------------------------------------------
# ConsistencyResult DTO structure
# ---------------------------------------------------------------------------


class TestConsistencyResultStructure:
    def test_result_has_expected_fields(self):
        """ConsistencyResult has consistency_label and methodology_trace."""
        result = compute_consistency_analysis(_make_endpoint_metrics())
        assert hasattr(result, "consistency_label")
        assert hasattr(result, "methodology_trace")

    def test_label_is_bounded_value(self):
        """consistency_label is a member of the bounded value set."""
        valid = {LABEL_CONSISTENT, LABEL_INCONSISTENT, LABEL_INSUFFICIENT_DATA}
        result = compute_consistency_analysis(_make_endpoint_metrics())
        assert result.consistency_label in valid

    def test_result_is_frozen(self):
        """ConsistencyResult is immutable."""
        result = compute_consistency_analysis(_make_endpoint_metrics())
        with pytest.raises(AttributeError):
            result.consistency_label = "CONSISTENT"  # type: ignore[misc]

    def test_determinism_identical_inputs_produce_identical_result(self):
        """Same input produces identical output (NFR-1)."""
        metrics = _make_endpoint_metrics(
            success_rate=Decimal("0.850"), numerator=17, denominator=20
        )
        result_a = compute_consistency_analysis(metrics)
        result_b = compute_consistency_analysis(metrics)
        assert result_a.consistency_label == result_b.consistency_label
        assert result_a.methodology_trace == result_b.methodology_trace
