"""Unit tests for Phase 5.3 — Stability Analysis.

Covers success_rate_stability_v1 and latency_stability_v1 algorithms via
compute_stability_analysis(). Exercises all label paths, INSUFFICIENT_DATA paths,
threshold boundary conditions, methodology trace completeness, and required wording.

Test IDs map to QA plan docs/qa/phase_5_reliability_intelligence_test_plan.md Section 5.
"""

from decimal import Decimal

import pytest

from release_confidence_platform.reliability_intelligence.constants import (
    INTELLIGENCE_VERSION,
    LABEL_DEGRADED,
    LABEL_INSUFFICIENT_DATA,
    LABEL_STABLE,
    LATENCY_STABILITY_ALGORITHM,
    MAX_P95_RATIO_THRESHOLD,
    MIN_EXECUTION_COUNT,
    MIN_LATENCY_COUNT,
    P99_MEAN_RATIO_THRESHOLD,
    STABLE_THRESHOLD,
    SUCCESS_RATE_STABILITY_ALGORITHM,
)
from release_confidence_platform.reliability_intelligence.models import EndpointMetricsDTO
from release_confidence_platform.reliability_intelligence.stability import (
    compute_stability_analysis,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

_REQUIRED_WORDING_PHRASE = "distributional characterization, not temporal assessment"


def _make_endpoint_metrics(
    execution_count: int = 20,
    success_rate: Decimal | None = Decimal("0.950"),
    numerator: int = 19,
    denominator: int = 20,
    timeout_count: int = 0,
    latency_count: int = 10,
    latency_min: float | None = 50.0,
    latency_max: float | None = 300.0,
    latency_mean: float | None = 100.0,
    latency_median: float | None = 90.0,
    latency_p95: float | None = 200.0,
    latency_p99: float | None = 200.0,
    is_insufficient_data: bool = False,
) -> EndpointMetricsDTO:
    """Build an EndpointMetricsDTO for stability tests."""
    if latency_count > 0:
        latency_profile = {
            "count": latency_count,
            "min": latency_min,
            "max": latency_max,
            "mean": latency_mean,
            "median": latency_median,
            "p95": latency_p95,
            "p99": latency_p99,
        }
    else:
        latency_profile = None

    return EndpointMetricsDTO(
        endpoint_id="ep_test",
        execution_count=execution_count,
        success_rate=success_rate,
        success_inputs={"numerator": numerator, "denominator": denominator},
        failure_classification_counts={},
        latency_profile=latency_profile,
        timeout_count=timeout_count,
        is_insufficient_data=is_insufficient_data,
    )


def _insufficient_data_metrics() -> EndpointMetricsDTO:
    """Zero-execution endpoint — all fields at minimum."""
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
# success_rate_stability_v1 — STAB-SR01 through STAB-SR06
# ---------------------------------------------------------------------------


class TestSuccessRateStabilityAlgorithm:
    def test_stable_at_threshold_value(self):
        """STAB-SR01: success_rate = 0.950 exactly → STABLE."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(success_rate=Decimal("0.950"), numerator=19, denominator=20)
        )
        assert result.success_rate_stability_label == LABEL_STABLE

    def test_stable_above_threshold(self):
        """STAB-SR02: success_rate = 1.000 → STABLE."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(success_rate=Decimal("1.000"), numerator=20, denominator=20)
        )
        assert result.success_rate_stability_label == LABEL_STABLE

    def test_degraded_below_threshold(self):
        """STAB-SR03: success_rate = 0.949 → DEGRADED."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(success_rate=Decimal("0.949"), numerator=949, denominator=1000)
        )
        assert result.success_rate_stability_label == LABEL_DEGRADED

    def test_degraded_at_zero_success_rate(self):
        """STAB-SR04: success_rate = 0.000 → DEGRADED."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(success_rate=Decimal("0.000"), numerator=0, denominator=20)
        )
        assert result.success_rate_stability_label == LABEL_DEGRADED

    def test_insufficient_data_at_zero_executions(self):
        """STAB-SR05: execution_count = 0 → INSUFFICIENT_DATA."""
        result = compute_stability_analysis(_insufficient_data_metrics())
        assert result.success_rate_stability_label == LABEL_INSUFFICIENT_DATA

    def test_threshold_uses_rounded_success_rate(self):
        """STAB-SR06: 0.9499 rounds to 0.950 at 3dp → comparison uses rounded value → STABLE."""
        # metrics.py rounds 9499/10000 = 0.9499 → Decimal("0.950") with ROUND_HALF_UP
        # stability.py receives the already-rounded value and compares against STABLE_THRESHOLD
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                success_rate=Decimal("0.950"),  # post-rounding value from metrics.py
                numerator=9499,
                denominator=10000,
            )
        )
        assert result.success_rate_stability_label == LABEL_STABLE

    def test_insufficient_data_when_denominator_zero(self):
        """execution_count >= MIN but denominator = 0 → INSUFFICIENT_DATA."""
        dto = EndpointMetricsDTO(
            endpoint_id="ep_x",
            execution_count=15,
            success_rate=None,
            success_inputs={"numerator": 0, "denominator": 0},
            failure_classification_counts={},
            latency_profile=None,
            timeout_count=0,
            is_insufficient_data=True,
        )
        result = compute_stability_analysis(dto)
        assert result.success_rate_stability_label == LABEL_INSUFFICIENT_DATA

    def test_insufficient_data_below_min_execution_count(self):
        """execution_count = MIN_EXECUTION_COUNT - 1 → INSUFFICIENT_DATA."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                execution_count=MIN_EXECUTION_COUNT - 1,
                success_rate=Decimal("0.950"),
                numerator=9,
                denominator=9,
            )
        )
        assert result.success_rate_stability_label == LABEL_INSUFFICIENT_DATA

    def test_stable_at_minimum_execution_count(self):
        """execution_count exactly at MIN_EXECUTION_COUNT → eligible for label."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                execution_count=MIN_EXECUTION_COUNT,
                success_rate=Decimal("1.000"),
                numerator=10,
                denominator=10,
            )
        )
        assert result.success_rate_stability_label == LABEL_STABLE


# ---------------------------------------------------------------------------
# latency_stability_v1 — STAB-LAT01 through STAB-LAT04
# ---------------------------------------------------------------------------


class TestLatencyStabilityAlgorithm:
    def test_stable_when_both_ratios_within_threshold(self):
        """STAB-LAT01: p99/mean=2.0 (< 3.0), max/p95=1.5 (< 2.0) → STABLE."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                latency_count=10,
                latency_mean=100.0,
                latency_p99=200.0,  # ratio 2.0
                latency_max=300.0,
                latency_p95=200.0,  # ratio 1.5
            )
        )
        assert result.latency_stability_label == LABEL_STABLE

    def test_degraded_when_p99_mean_ratio_exceeds_threshold(self):
        """STAB-LAT02: p99/mean ratio > P99_MEAN_RATIO_THRESHOLD → DEGRADED."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                latency_count=10,
                latency_mean=100.0,
                latency_p99=400.0,  # ratio 4.0 > 3.0
                latency_max=500.0,
                latency_p95=300.0,
            )
        )
        assert result.latency_stability_label == LABEL_DEGRADED

    def test_degraded_when_max_p95_ratio_exceeds_threshold(self):
        """STAB-LAT02 variant: max/p95 ratio > MAX_P95_RATIO_THRESHOLD → DEGRADED."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                latency_count=10,
                latency_mean=100.0,
                latency_p99=250.0,  # ratio 2.5 ≤ 3.0 (does not trigger p99/mean)
                latency_max=600.0,
                latency_p95=200.0,  # ratio 3.0 > 2.0
            )
        )
        assert result.latency_stability_label == LABEL_DEGRADED

    def test_insufficient_data_at_zero_latency_count(self):
        """STAB-LAT03: latency_count = 0 → INSUFFICIENT_DATA."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(latency_count=0)
        )
        assert result.latency_stability_label == LABEL_INSUFFICIENT_DATA

    def test_insufficient_data_when_latency_fields_null(self):
        """STAB-LAT04: latency_profile = None (no latency data) → INSUFFICIENT_DATA."""
        dto = EndpointMetricsDTO(
            endpoint_id="ep_no_lat",
            execution_count=20,
            success_rate=Decimal("1.000"),
            success_inputs={"numerator": 20, "denominator": 20},
            failure_classification_counts={},
            latency_profile=None,
            timeout_count=0,
            is_insufficient_data=False,
        )
        result = compute_stability_analysis(dto)
        assert result.latency_stability_label == LABEL_INSUFFICIENT_DATA

    def test_insufficient_data_below_min_latency_count(self):
        """latency_count = MIN_LATENCY_COUNT - 1 → INSUFFICIENT_DATA."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(latency_count=MIN_LATENCY_COUNT - 1)
        )
        assert result.latency_stability_label == LABEL_INSUFFICIENT_DATA

    def test_eligible_at_min_latency_count(self):
        """latency_count exactly at MIN_LATENCY_COUNT → eligible for label."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                latency_count=MIN_LATENCY_COUNT,
                latency_mean=100.0,
                latency_p99=200.0,
                latency_max=300.0,
                latency_p95=200.0,
            )
        )
        assert result.latency_stability_label == LABEL_STABLE

    def test_stable_when_p99_mean_ratio_exactly_at_threshold(self):
        """p99/mean = P99_MEAN_RATIO_THRESHOLD (3.0) → STABLE (> required for DEGRADED)."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                latency_count=10,
                latency_mean=100.0,
                latency_p99=300.0,  # ratio exactly 3.0
                latency_max=300.0,
                latency_p95=200.0,  # max/p95 = 1.5 ≤ 2.0
            )
        )
        assert result.latency_stability_label == LABEL_STABLE

    def test_stable_when_max_p95_ratio_exactly_at_threshold(self):
        """max/p95 = MAX_P95_RATIO_THRESHOLD (2.0) → STABLE (> required for DEGRADED)."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                latency_count=10,
                latency_mean=100.0,
                latency_p99=200.0,  # ratio 2.0 ≤ 3.0
                latency_max=400.0,
                latency_p95=200.0,  # ratio exactly 2.0
            )
        )
        assert result.latency_stability_label == LABEL_STABLE

    def test_stable_skips_p99_mean_when_mean_is_zero(self):
        """mean = 0.0 → p99/mean skipped (division by zero guard) → proceeds to max/p95 check."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                latency_count=10,
                latency_mean=0.0,
                latency_p99=200.0,
                latency_max=300.0,
                latency_p95=200.0,  # ratio 1.5 ≤ 2.0
            )
        )
        assert result.latency_stability_label == LABEL_STABLE

    def test_degraded_via_max_p95_when_p99_mean_skipped(self):
        """mean = 0.0 → p99/mean skipped; max/p95 > threshold → DEGRADED."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                latency_count=10,
                latency_mean=0.0,
                latency_p99=200.0,
                latency_max=700.0,
                latency_p95=200.0,  # ratio 3.5 > 2.0
            )
        )
        assert result.latency_stability_label == LABEL_DEGRADED


# ---------------------------------------------------------------------------
# Methodology trace completeness — STAB-TR01 through STAB-TR06
# ---------------------------------------------------------------------------


class TestMethodologyTraceCompleteness:
    def setup_method(self):
        self.result = compute_stability_analysis(
            _make_endpoint_metrics(
                execution_count=20,
                success_rate=Decimal("0.950"),
                numerator=19,
                denominator=20,
                latency_count=10,
                latency_mean=100.0,
                latency_p99=200.0,
                latency_max=300.0,
                latency_p95=200.0,
            )
        )
        self.trace = self.result.methodology_trace

    def test_trace_contains_algorithm_name(self):
        """STAB-TR01: methodology_trace.algorithm equals success_rate_stability_v1."""
        assert "algorithm" in self.trace
        assert self.trace["algorithm"] == SUCCESS_RATE_STABILITY_ALGORITHM

    def test_trace_contains_algorithm_version(self):
        """STAB-TR02: methodology_trace.algorithm_version is intel_v1."""
        assert "algorithm_version" in self.trace
        assert self.trace["algorithm_version"] == INTELLIGENCE_VERSION

    def test_trace_contains_input_fields(self):
        """STAB-TR03: methodology_trace.inputs contains key input values."""
        assert "inputs" in self.trace
        inputs = self.trace["inputs"]
        assert "execution_count" in inputs
        assert "success_rate" in inputs
        assert "latency_p99_ms" in inputs
        assert "latency_mean_ms" in inputs

    def test_trace_contains_thresholds(self):
        """STAB-TR04: methodology_trace.thresholds contains threshold values."""
        assert "thresholds" in self.trace
        thresholds = self.trace["thresholds"]
        assert "STABLE_THRESHOLD" in thresholds
        assert thresholds["STABLE_THRESHOLD"] == float(STABLE_THRESHOLD)
        assert "P99_MEAN_RATIO_THRESHOLD" in thresholds
        assert thresholds["P99_MEAN_RATIO_THRESHOLD"] == float(P99_MEAN_RATIO_THRESHOLD)
        assert "MAX_P95_RATIO_THRESHOLD" in thresholds
        assert thresholds["MAX_P95_RATIO_THRESHOLD"] == float(MAX_P95_RATIO_THRESHOLD)
        assert "MIN_EXECUTION_COUNT" in thresholds
        assert "MIN_LATENCY_COUNT" in thresholds

    def test_trace_contains_intermediate_values(self):
        """STAB-TR05: methodology_trace.intermediate_values has computed latency ratios."""
        assert "intermediate_values" in self.trace
        intermediates = self.trace["intermediate_values"]
        assert "p99_mean_ratio" in intermediates
        assert "max_p95_ratio" in intermediates

    def test_trace_contains_label_determination(self):
        """STAB-TR06: methodology_trace.label_determination is a non-empty string."""
        assert "label_determination" in self.trace
        assert isinstance(self.trace["label_determination"], str)
        assert len(self.trace["label_determination"]) > 0

    def test_trace_intermediate_values_none_on_insufficient_latency(self):
        """Intermediate ratios are None when latency data is insufficient."""
        result = compute_stability_analysis(_make_endpoint_metrics(latency_count=0))
        intermediates = result.methodology_trace["intermediate_values"]
        assert intermediates["p99_mean_ratio"] is None
        assert intermediates["max_p95_ratio"] is None

    def test_trace_intermediate_values_computed_on_stable(self):
        """Intermediate ratios are Decimal values when latency is sufficient and STABLE."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                latency_count=10,
                latency_mean=100.0,
                latency_p99=200.0,
                latency_max=300.0,
                latency_p95=200.0,
            )
        )
        intermediates = result.methodology_trace["intermediate_values"]
        assert intermediates["p99_mean_ratio"] is not None
        assert isinstance(intermediates["p99_mean_ratio"], Decimal)
        assert intermediates["max_p95_ratio"] is not None
        assert isinstance(intermediates["max_p95_ratio"], Decimal)

    def test_trace_inputs_match_endpoint_metrics_fields(self):
        """methodology_trace.inputs.execution_count matches the DTO execution_count."""
        result = compute_stability_analysis(_make_endpoint_metrics(execution_count=25))
        assert result.methodology_trace["inputs"]["execution_count"] == 25

    def test_trace_inputs_success_rate_is_string_or_none(self):
        """methodology_trace.inputs.success_rate is a string representation or None."""
        result_with_rate = compute_stability_analysis(
            _make_endpoint_metrics(success_rate=Decimal("0.950"))
        )
        assert result_with_rate.methodology_trace["inputs"]["success_rate"] == "0.950"

        result_insufficient = compute_stability_analysis(_insufficient_data_metrics())
        assert result_insufficient.methodology_trace["inputs"]["success_rate"] is None


# ---------------------------------------------------------------------------
# Methodology trace wording — STAB-WD01 and STAB-WD02
# ---------------------------------------------------------------------------


class TestMethodologyTraceWording:
    def test_wording_includes_distributional_characterization_phrase(self):
        """STAB-WD01: label_determination includes the required phrase."""
        result = compute_stability_analysis(_make_endpoint_metrics())
        assert _REQUIRED_WORDING_PHRASE in result.methodology_trace["label_determination"]

    def test_wording_covers_both_algorithms(self):
        """STAB-WD02: combined trace label_determination covers both SR and latency algorithms."""
        result = compute_stability_analysis(_make_endpoint_metrics())
        label_determination = result.methodology_trace["label_determination"]
        assert _REQUIRED_WORDING_PHRASE in label_determination
        # Both algorithm names appear in the combined trace label determination.
        assert SUCCESS_RATE_STABILITY_ALGORITHM in label_determination
        assert LATENCY_STABILITY_ALGORITHM in label_determination

    def test_wording_present_when_all_insufficient_data(self):
        """Required phrase is present even when all labels are INSUFFICIENT_DATA."""
        result = compute_stability_analysis(_insufficient_data_metrics())
        assert _REQUIRED_WORDING_PHRASE in result.methodology_trace["label_determination"]

    def test_wording_present_when_degraded(self):
        """Required phrase is present when endpoint is DEGRADED."""
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                success_rate=Decimal("0.800"),
                numerator=8,
                denominator=10,
                latency_count=10,
                latency_mean=100.0,
                latency_p99=400.0,  # p99/mean=4.0 → DEGRADED
                latency_max=500.0,
                latency_p95=300.0,
            )
        )
        assert _REQUIRED_WORDING_PHRASE in result.methodology_trace["label_determination"]


# ---------------------------------------------------------------------------
# StabilityResult DTO structure
# ---------------------------------------------------------------------------


class TestStabilityResultStructure:
    def test_result_has_expected_fields(self):
        """StabilityResult has success_rate_stability_label, latency_stability_label, methodology_trace."""
        result = compute_stability_analysis(_make_endpoint_metrics())
        assert hasattr(result, "success_rate_stability_label")
        assert hasattr(result, "latency_stability_label")
        assert hasattr(result, "methodology_trace")

    def test_labels_are_bounded_values(self):
        """All labels are members of the bounded value set."""
        valid_labels = {LABEL_STABLE, LABEL_DEGRADED, LABEL_INSUFFICIENT_DATA}
        result = compute_stability_analysis(_make_endpoint_metrics())
        assert result.success_rate_stability_label in valid_labels
        assert result.latency_stability_label in valid_labels

    def test_result_is_frozen(self):
        """StabilityResult is immutable — reassigning a field raises AttributeError."""
        result = compute_stability_analysis(_make_endpoint_metrics())
        with pytest.raises(AttributeError):
            result.success_rate_stability_label = "STABLE"  # type: ignore[misc]

    def test_determinism_identical_inputs_produce_identical_result(self):
        """Same input produces identical output labels and trace (NFR-1)."""
        metrics = _make_endpoint_metrics(
            execution_count=20,
            success_rate=Decimal("0.950"),
            numerator=19,
            denominator=20,
            latency_count=10,
            latency_mean=100.0,
            latency_p99=200.0,
            latency_max=300.0,
            latency_p95=200.0,
        )
        result_a = compute_stability_analysis(metrics)
        result_b = compute_stability_analysis(metrics)
        assert result_a.success_rate_stability_label == result_b.success_rate_stability_label
        assert result_a.latency_stability_label == result_b.latency_stability_label
        assert result_a.methodology_trace == result_b.methodology_trace

    def test_mixed_labels_independent(self):
        """SR and latency labels are computed independently."""
        # Sufficient SR data (STABLE) but insufficient latency data.
        result = compute_stability_analysis(
            _make_endpoint_metrics(
                execution_count=20,
                success_rate=Decimal("1.000"),
                numerator=20,
                denominator=20,
                latency_count=0,  # latency: INSUFFICIENT_DATA
            )
        )
        assert result.success_rate_stability_label == LABEL_STABLE
        assert result.latency_stability_label == LABEL_INSUFFICIENT_DATA
