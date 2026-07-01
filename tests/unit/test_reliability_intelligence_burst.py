"""Unit tests for Phase 5.4 — Burst Analysis.

Covers failure_burst_v1 and latency_spike_v1 algorithms via compute_burst_analysis().
Exercises all label paths, INSUFFICIENT_DATA paths, threshold boundary conditions,
methodology trace completeness, and required wording.

Test IDs map to QA plan docs/qa/phase_5_reliability_intelligence_test_plan.md Section 6.
"""

from decimal import Decimal

import pytest

from release_confidence_platform.reliability_intelligence.burst import (
    compute_burst_analysis,
)
from release_confidence_platform.reliability_intelligence.constants import (
    FAILURE_BURST_ALGORITHM,
    INTELLIGENCE_VERSION,
    LABEL_BURST_SUSPECTED,
    LABEL_INSUFFICIENT_DATA,
    LABEL_NO_BURST_DETECTED,
    LABEL_NO_SPIKE_DETECTED,
    LABEL_SPIKE_SUSPECTED,
    LATENCY_SPIKE_ALGORITHM,
    MAX_P99_RATIO_THRESHOLD,
    MIN_EXECUTION_COUNT,
    MIN_LATENCY_COUNT,
    TIMEOUT_BURST_THRESHOLD,
)
from release_confidence_platform.reliability_intelligence.models import EndpointMetricsDTO

# ---------------------------------------------------------------------------
# Required wording phrase (Section 11 / methodology_disclosure limitations line 577)
# ---------------------------------------------------------------------------

_REQUIRED_WORDING_PHRASE = "burst timing attribution cannot be determined from agg_v1 inputs"

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_endpoint_metrics(
    execution_count: int = 50,
    timeout_count: int = 0,
    latency_count: int = 10,
    latency_max: float | None = 200.0,
    latency_p99: float | None = 150.0,
    success_rate: Decimal | None = Decimal("1.000"),
    numerator: int = 50,
    denominator: int = 50,
    is_insufficient_data: bool = False,
) -> EndpointMetricsDTO:
    """Build an EndpointMetricsDTO for burst tests."""
    if latency_count > 0:
        latency_profile = {
            "count": latency_count,
            "min": 50.0,
            "max": latency_max,
            "mean": 100.0,
            "median": 90.0,
            "p95": 140.0,
            "p99": latency_p99,
        }
    else:
        latency_profile = None

    return EndpointMetricsDTO(
        endpoint_id="ep_burst_test",
        execution_count=execution_count,
        success_rate=success_rate,
        success_inputs={"numerator": numerator, "denominator": denominator},
        failure_classification_counts={},
        latency_profile=latency_profile,
        timeout_count=timeout_count,
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
# failure_burst_v1 — BURST-FB01 through BURST-FB07
# ---------------------------------------------------------------------------


class TestFailureBurstAlgorithm:
    def test_no_burst_detected_at_exactly_threshold(self):
        """BURST-FB01: timeout_proportion = 0.200 exactly → NO_BURST_DETECTED (not > threshold)."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(execution_count=100, timeout_count=20)
        )
        assert result.failure_burst_label == LABEL_NO_BURST_DETECTED

    def test_burst_suspected_above_threshold(self):
        """BURST-FB02: timeout_proportion = 0.210 → BURST_SUSPECTED."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(execution_count=100, timeout_count=21)
        )
        assert result.failure_burst_label == LABEL_BURST_SUSPECTED

    def test_no_burst_detected_zero_timeouts(self):
        """BURST-FB03: timeout_count = 0 → NO_BURST_DETECTED."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(execution_count=50, timeout_count=0)
        )
        assert result.failure_burst_label == LABEL_NO_BURST_DETECTED

    def test_burst_suspected_high_timeout_proportion(self):
        """BURST-FB04: timeout_count=10, execution_count=30 (ratio 0.333) → BURST_SUSPECTED."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(execution_count=30, timeout_count=10)
        )
        assert result.failure_burst_label == LABEL_BURST_SUSPECTED

    def test_insufficient_data_below_min_execution_count(self):
        """BURST-FB05: execution_count = 9 (below MIN_EXECUTION_COUNT=10) → INSUFFICIENT_DATA."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(execution_count=9, timeout_count=2)
        )
        assert result.failure_burst_label == LABEL_INSUFFICIENT_DATA

    def test_insufficient_data_at_zero_executions(self):
        """BURST-FB06: execution_count = 0 → INSUFFICIENT_DATA."""
        result = compute_burst_analysis(_insufficient_data_metrics())
        assert result.failure_burst_label == LABEL_INSUFFICIENT_DATA

    def test_threshold_is_exclusive_boundary(self):
        """BURST-FB07: timeout_proportion 0.2002 → BURST_SUSPECTED; exactly 0.200 → NO_BURST_DETECTED."""  # noqa: E501
        result_just_above = compute_burst_analysis(
            _make_endpoint_metrics(execution_count=999, timeout_count=200)
        )
        assert result_just_above.failure_burst_label == LABEL_BURST_SUSPECTED

        result_at_threshold = compute_burst_analysis(
            _make_endpoint_metrics(execution_count=100, timeout_count=20)
        )
        assert result_at_threshold.failure_burst_label == LABEL_NO_BURST_DETECTED

    def test_eligible_at_min_execution_count(self):
        """execution_count exactly at MIN_EXECUTION_COUNT → eligible for label."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(execution_count=MIN_EXECUTION_COUNT, timeout_count=0)
        )
        assert result.failure_burst_label == LABEL_NO_BURST_DETECTED


# ---------------------------------------------------------------------------
# latency_spike_v1 — BURST-LS01 through BURST-LS05
# ---------------------------------------------------------------------------


class TestLatencySpikeAlgorithm:
    def test_no_spike_detected_at_exactly_threshold(self):
        """BURST-LS01: max/p99 ratio = 3.0 exactly → NO_SPIKE_DETECTED (not > threshold)."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(latency_count=10, latency_max=300.0, latency_p99=100.0)
        )
        assert result.latency_spike_label == LABEL_NO_SPIKE_DETECTED

    def test_spike_suspected_above_threshold(self):
        """BURST-LS02: max/p99 ratio = 3.01 → SPIKE_SUSPECTED."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(latency_count=10, latency_max=301.0, latency_p99=100.0)
        )
        assert result.latency_spike_label == LABEL_SPIKE_SUSPECTED

    def test_no_spike_detected_low_ratio(self):
        """BURST-LS03: max/p99 ratio = 1.33 → NO_SPIKE_DETECTED."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(latency_count=10, latency_max=200.0, latency_p99=150.0)
        )
        assert result.latency_spike_label == LABEL_NO_SPIKE_DETECTED

    def test_insufficient_data_below_min_latency_count(self):
        """BURST-LS04: latency count below minimum → INSUFFICIENT_DATA."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(latency_count=MIN_LATENCY_COUNT - 1)
        )
        assert result.latency_spike_label == LABEL_INSUFFICIENT_DATA

    def test_insufficient_data_when_latency_fields_null(self):
        """BURST-LS05: latency_p99_ms = null → INSUFFICIENT_DATA."""
        dto = EndpointMetricsDTO(
            endpoint_id="ep_no_lat",
            execution_count=50,
            success_rate=Decimal("1.000"),
            success_inputs={"numerator": 50, "denominator": 50},
            failure_classification_counts={},
            latency_profile=None,
            timeout_count=0,
            is_insufficient_data=False,
        )
        result = compute_burst_analysis(dto)
        assert result.latency_spike_label == LABEL_INSUFFICIENT_DATA

    def test_insufficient_data_at_zero_latency_count(self):
        """latency_count = 0 → INSUFFICIENT_DATA."""
        result = compute_burst_analysis(_make_endpoint_metrics(latency_count=0))
        assert result.latency_spike_label == LABEL_INSUFFICIENT_DATA

    def test_insufficient_data_when_p99_is_zero(self):
        """latency_p99_ms = 0 → INSUFFICIENT_DATA (division-by-zero guard)."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(latency_count=10, latency_max=300.0, latency_p99=0.0)
        )
        assert result.latency_spike_label == LABEL_INSUFFICIENT_DATA

    def test_eligible_at_min_latency_count(self):
        """latency_count exactly at MIN_LATENCY_COUNT → eligible for label."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(
                latency_count=MIN_LATENCY_COUNT,
                latency_max=200.0,
                latency_p99=100.0,
            )
        )
        assert result.latency_spike_label == LABEL_NO_SPIKE_DETECTED

    def test_spike_suspected_high_ratio(self):
        """max/p99 well above threshold → SPIKE_SUSPECTED."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(latency_count=10, latency_max=1000.0, latency_p99=100.0)
        )
        assert result.latency_spike_label == LABEL_SPIKE_SUSPECTED


# ---------------------------------------------------------------------------
# Methodology trace completeness — BURST-TR01 through BURST-TR05
# ---------------------------------------------------------------------------


class TestBurstMethodologyTraceCompleteness:
    def setup_method(self):
        self.result = compute_burst_analysis(
            _make_endpoint_metrics(
                execution_count=50,
                timeout_count=5,
                latency_count=10,
                latency_max=200.0,
                latency_p99=100.0,
            )
        )
        self.trace = self.result.methodology_trace

    def test_trace_contains_algorithm_name(self):
        """BURST-TR01: methodology_trace.algorithm equals failure_burst_v1."""
        assert "algorithm" in self.trace
        assert self.trace["algorithm"] == FAILURE_BURST_ALGORITHM

    def test_trace_contains_algorithm_version(self):
        """algorithm_version is intel_v1."""
        assert "algorithm_version" in self.trace
        assert self.trace["algorithm_version"] == INTELLIGENCE_VERSION

    def test_trace_contains_input_values(self):
        """BURST-TR02: inputs include timeout_count, execution_count, and latency values."""
        assert "inputs" in self.trace
        inputs = self.trace["inputs"]
        assert "execution_count" in inputs
        assert "timeout_count" in inputs
        assert "latency_count" in inputs
        assert "latency_p99_ms" in inputs
        assert "latency_max_ms" in inputs

    def test_trace_contains_thresholds(self):
        """BURST-TR03: thresholds include TIMEOUT_BURST_THRESHOLD and MAX_P99_RATIO_THRESHOLD."""
        assert "thresholds" in self.trace
        thresholds = self.trace["thresholds"]
        assert "TIMEOUT_BURST_THRESHOLD" in thresholds
        assert thresholds["TIMEOUT_BURST_THRESHOLD"] == float(TIMEOUT_BURST_THRESHOLD)
        assert "MAX_P99_RATIO_THRESHOLD" in thresholds
        assert thresholds["MAX_P99_RATIO_THRESHOLD"] == float(MAX_P99_RATIO_THRESHOLD)
        assert "MIN_EXECUTION_COUNT" in thresholds
        assert "MIN_LATENCY_COUNT" in thresholds

    def test_trace_contains_intermediate_ratios(self):
        """BURST-TR04: intermediate_values contains timeout_proportion and max_p99_ratio."""
        assert "intermediate_values" in self.trace
        intermediates = self.trace["intermediate_values"]
        assert "timeout_proportion" in intermediates
        assert "max_p99_ratio" in intermediates

    def test_trace_contains_label_determination(self):
        """BURST-TR05: label_determination is a non-empty string."""
        assert "label_determination" in self.trace
        assert isinstance(self.trace["label_determination"], str)
        assert len(self.trace["label_determination"]) > 0

    def test_intermediate_timeout_proportion_computed(self):
        """timeout_proportion is a Decimal when execution_count >= MIN_EXECUTION_COUNT."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(execution_count=100, timeout_count=10)
        )
        tp = result.methodology_trace["intermediate_values"]["timeout_proportion"]
        assert tp is not None
        assert isinstance(tp, Decimal)
        assert tp == Decimal("10") / Decimal("100")

    def test_intermediate_timeout_proportion_none_on_insufficient(self):
        """timeout_proportion is None when execution_count < MIN_EXECUTION_COUNT."""
        result = compute_burst_analysis(_insufficient_data_metrics())
        assert result.methodology_trace["intermediate_values"]["timeout_proportion"] is None

    def test_intermediate_max_p99_ratio_computed(self):
        """max_p99_ratio is a Decimal when latency data is sufficient."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(latency_count=10, latency_max=300.0, latency_p99=100.0)
        )
        ratio = result.methodology_trace["intermediate_values"]["max_p99_ratio"]
        assert ratio is not None
        assert isinstance(ratio, Decimal)
        assert ratio == Decimal("3.0")

    def test_intermediate_max_p99_ratio_none_on_insufficient_latency(self):
        """max_p99_ratio is None when latency data is insufficient."""
        result = compute_burst_analysis(_make_endpoint_metrics(latency_count=0))
        assert result.methodology_trace["intermediate_values"]["max_p99_ratio"] is None

    def test_trace_inputs_match_endpoint_metrics(self):
        """inputs.execution_count and timeout_count match DTO fields."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(execution_count=75, timeout_count=3)
        )
        assert result.methodology_trace["inputs"]["execution_count"] == 75
        assert result.methodology_trace["inputs"]["timeout_count"] == 3

    def test_both_labels_independent_algorithms(self):
        """failure_burst and latency_spike labels are computed independently."""
        # Burst: INSUFFICIENT_DATA (low execution_count); Spike: sufficient latency → label assigned
        dto = EndpointMetricsDTO(
            endpoint_id="ep_mixed",
            execution_count=5,  # below MIN_EXECUTION_COUNT → burst: INSUFFICIENT_DATA
            success_rate=Decimal("1.000"),
            success_inputs={"numerator": 5, "denominator": 5},
            failure_classification_counts={},
            latency_profile={
                "count": 10,
                "min": 50.0,
                "max": 200.0,
                "mean": 100.0,
                "median": 90.0,
                "p95": 140.0,
                "p99": 150.0,  # max/p99 = 200/150 = 1.33 → NO_SPIKE_DETECTED
            },
            timeout_count=0,
            is_insufficient_data=False,
        )
        result = compute_burst_analysis(dto)
        assert result.failure_burst_label == LABEL_INSUFFICIENT_DATA
        assert result.latency_spike_label == LABEL_NO_SPIKE_DETECTED


# ---------------------------------------------------------------------------
# Methodology trace wording — BURST-WD01 and BURST-WD02
# ---------------------------------------------------------------------------


class TestBurstMethodologyTraceWording:
    def test_wording_includes_required_burst_phrase(self):
        """BURST-WD01: label_determination includes the required burst timing phrase."""
        result = compute_burst_analysis(_make_endpoint_metrics())
        assert _REQUIRED_WORDING_PHRASE in result.methodology_trace["label_determination"]

    def test_wording_covers_both_algorithms(self):
        """BURST-WD02: combined trace label_determination covers both FB and LS algorithms."""
        result = compute_burst_analysis(_make_endpoint_metrics())
        label_determination = result.methodology_trace["label_determination"]
        assert _REQUIRED_WORDING_PHRASE in label_determination
        assert FAILURE_BURST_ALGORITHM in label_determination
        assert LATENCY_SPIKE_ALGORITHM in label_determination

    def test_wording_present_when_all_insufficient_data(self):
        """Required phrase is present even when all labels are INSUFFICIENT_DATA."""
        result = compute_burst_analysis(_insufficient_data_metrics())
        assert _REQUIRED_WORDING_PHRASE in result.methodology_trace["label_determination"]

    def test_wording_present_when_burst_suspected(self):
        """Required phrase is present when failure_burst_label = BURST_SUSPECTED."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(execution_count=100, timeout_count=30)
        )
        assert result.failure_burst_label == LABEL_BURST_SUSPECTED
        assert _REQUIRED_WORDING_PHRASE in result.methodology_trace["label_determination"]

    def test_wording_present_when_spike_suspected(self):
        """Required phrase is present when latency_spike_label = SPIKE_SUSPECTED."""
        result = compute_burst_analysis(
            _make_endpoint_metrics(latency_count=10, latency_max=500.0, latency_p99=100.0)
        )
        assert result.latency_spike_label == LABEL_SPIKE_SUSPECTED
        assert _REQUIRED_WORDING_PHRASE in result.methodology_trace["label_determination"]


# ---------------------------------------------------------------------------
# BurstResult DTO structure
# ---------------------------------------------------------------------------


class TestBurstResultStructure:
    def test_result_has_expected_fields(self):
        """BurstResult has failure_burst_label, latency_spike_label, methodology_trace."""
        result = compute_burst_analysis(_make_endpoint_metrics())
        assert hasattr(result, "failure_burst_label")
        assert hasattr(result, "latency_spike_label")
        assert hasattr(result, "methodology_trace")

    def test_failure_burst_labels_are_bounded(self):
        """failure_burst_label is a member of the bounded value set."""
        valid = {LABEL_NO_BURST_DETECTED, LABEL_BURST_SUSPECTED, LABEL_INSUFFICIENT_DATA}
        result = compute_burst_analysis(_make_endpoint_metrics())
        assert result.failure_burst_label in valid

    def test_latency_spike_labels_are_bounded(self):
        """latency_spike_label is a member of the bounded value set."""
        valid = {LABEL_NO_SPIKE_DETECTED, LABEL_SPIKE_SUSPECTED, LABEL_INSUFFICIENT_DATA}
        result = compute_burst_analysis(_make_endpoint_metrics())
        assert result.latency_spike_label in valid

    def test_result_is_frozen(self):
        """BurstResult is immutable."""
        result = compute_burst_analysis(_make_endpoint_metrics())
        with pytest.raises(AttributeError):
            result.failure_burst_label = "NO_BURST_DETECTED"  # type: ignore[misc]

    def test_determinism_identical_inputs_produce_identical_result(self):
        """Same input produces identical output labels and trace (NFR-1)."""
        metrics = _make_endpoint_metrics(
            execution_count=100,
            timeout_count=10,
            latency_count=10,
            latency_max=250.0,
            latency_p99=100.0,
        )
        result_a = compute_burst_analysis(metrics)
        result_b = compute_burst_analysis(metrics)
        assert result_a.failure_burst_label == result_b.failure_burst_label
        assert result_a.latency_spike_label == result_b.latency_spike_label
        assert result_a.methodology_trace == result_b.methodology_trace
