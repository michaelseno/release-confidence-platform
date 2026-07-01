"""Unit tests for Phase 5.6 — Release Confidence Scoring.

Covers compute_endpoint_score(), compute_audit_score(), assign_score_label(), and
build_methodology_disclosure() via scoring.py. Exercises all weight paths, boundary
conditions for label assignment, audit rollup, evidence trace, and methodology disclosure.

Test IDs map to QA plan docs/qa/phase_5_reliability_intelligence_test_plan.md Section 8.
"""

from decimal import Decimal

import pytest

from release_confidence_platform.reliability_intelligence.constants import (
    HIGH_CONFIDENCE_THRESHOLD,
    LABEL_BURST_SUSPECTED,
    LABEL_CONSISTENT,
    LABEL_DEGRADED,
    LABEL_INCONSISTENT,
    LABEL_INSUFFICIENT_DATA,
    LABEL_NO_BURST_DETECTED,
    LABEL_NO_SPIKE_DETECTED,
    LABEL_SPIKE_SUSPECTED,
    LABEL_STABLE,
    LABEL_TO_SCORE,
    MODERATE_CONFIDENCE_THRESHOLD,
    SCORE_LABEL_HIGH_CONFIDENCE,
    SCORE_LABEL_LOW_CONFIDENCE,
    SCORE_LABEL_MODERATE_CONFIDENCE,
    WEIGHT_BURST,
    WEIGHT_CONSISTENCY,
    WEIGHT_RELIABILITY,
    WEIGHT_STABILITY,
)
from release_confidence_platform.reliability_intelligence.models import (
    BurstResult,
    ConsistencyResult,
    EndpointMetricsDTO,
    EndpointScoreResult,
    StabilityResult,
)
from release_confidence_platform.reliability_intelligence.scoring import (
    assign_score_label,
    build_methodology_disclosure,
    compute_audit_score,
    compute_endpoint_score,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_metrics(
    endpoint_id: str = "ep_test",
    execution_count: int = 20,
    success_rate: Decimal | None = Decimal("1.000"),
    numerator: int = 20,
    denominator: int = 20,
    timeout_count: int = 0,
    is_insufficient_data: bool = False,
) -> EndpointMetricsDTO:
    return EndpointMetricsDTO(
        endpoint_id=endpoint_id,
        execution_count=execution_count,
        success_rate=success_rate,
        success_inputs={"numerator": numerator, "denominator": denominator},
        failure_classification_counts={},
        latency_profile=None,
        timeout_count=timeout_count,
        is_insufficient_data=is_insufficient_data,
    )


def _make_stability(
    sr_label: str = LABEL_STABLE,
    lat_label: str = LABEL_STABLE,
) -> StabilityResult:
    return StabilityResult(
        success_rate_stability_label=sr_label,
        latency_stability_label=lat_label,
        methodology_trace={},
    )


def _make_burst(
    fb_label: str = LABEL_NO_BURST_DETECTED,
    spike_label: str = LABEL_NO_SPIKE_DETECTED,
) -> BurstResult:
    return BurstResult(
        failure_burst_label=fb_label,
        latency_spike_label=spike_label,
        methodology_trace={},
    )


def _make_consistency(label: str = LABEL_CONSISTENT) -> ConsistencyResult:
    return ConsistencyResult(consistency_label=label, methodology_trace={})


def _all_passing_score() -> tuple:
    """Returns (metrics, stability, burst, consistency) for all-passing endpoint."""
    return (
        _make_metrics(success_rate=Decimal("1.000")),
        _make_stability(LABEL_STABLE, LABEL_STABLE),
        _make_burst(LABEL_NO_BURST_DETECTED, LABEL_NO_SPIKE_DETECTED),
        _make_consistency(LABEL_CONSISTENT),
    )


def _all_insufficient() -> tuple:
    """Returns (metrics, stability, burst, consistency) for all-INSUFFICIENT_DATA endpoint."""
    return (
        _make_metrics(success_rate=None, is_insufficient_data=True, execution_count=0, numerator=0, denominator=0),  # noqa: E501
        _make_stability(LABEL_INSUFFICIENT_DATA, LABEL_INSUFFICIENT_DATA),
        _make_burst(LABEL_INSUFFICIENT_DATA, LABEL_INSUFFICIENT_DATA),
        _make_consistency(LABEL_INSUFFICIENT_DATA),
    )


# ---------------------------------------------------------------------------
# Per-endpoint composite score — SCORE-EP01 through SCORE-EP07
# ---------------------------------------------------------------------------


class TestPerEndpointScore:
    def test_all_labels_passing_yields_1_000(self):
        """SCORE-EP01: all components = 1.0 → composite = 1.000."""
        result = compute_endpoint_score(*_all_passing_score())
        assert result.composite_score == Decimal("1.000")

    def test_all_insufficient_data_yields_0_250(self):
        """SCORE-EP02 (corrected per Technical Design Section 13.3 Step 1): all INSUFFICIENT_DATA.

        reliability_score = 0.0 (no executable reliability evidence; tech design strict rule).
        stability_score = burst_score = consistency_score = 0.5 (INSUFFICIENT_DATA neutral).
        composite = 0.50 * 0.0 + 0.20 * 0.5 + 0.15 * 0.5 + 0.15 * 0.5
                  = 0.000 + 0.100 + 0.075 + 0.075 = 0.250

        The QA plan draft listed 0.500 assuming reliability also uses neutral 0.5, but
        the Technical Design is authoritative: reliability_score = 0.0 when no data.
        """
        result = compute_endpoint_score(*_all_insufficient())
        assert result.composite_score == Decimal("0.250")

    def test_mixed_reliability_and_insufficient_data(self):
        """SCORE-EP03: reliability=0.9, all others INSUFFICIENT_DATA → 0.700.

        = 0.9 * 0.50 + 0.5 * 0.20 + 0.5 * 0.15 + 0.5 * 0.15
        = 0.450 + 0.100 + 0.075 + 0.075 = 0.700
        """
        result = compute_endpoint_score(
            _make_metrics(success_rate=Decimal("0.900"), numerator=18, denominator=20),
            _make_stability(LABEL_INSUFFICIENT_DATA, LABEL_INSUFFICIENT_DATA),
            _make_burst(LABEL_INSUFFICIENT_DATA, LABEL_INSUFFICIENT_DATA),
            _make_consistency(LABEL_INSUFFICIENT_DATA),
        )
        assert result.composite_score == Decimal("0.700")

    def test_weights_sum_to_one(self):
        """SCORE-EP04: weight constants sum to exactly 1.0."""
        weight_sum = WEIGHT_RELIABILITY + WEIGHT_STABILITY + WEIGHT_BURST + WEIGHT_CONSISTENCY
        assert weight_sum == Decimal("1.00")

    def test_score_precision_is_three_decimal_places(self):
        """SCORE-EP05: composite with unrounded intermediate is rounded to 3dp half-up.

        reliability_score = 0.333, stability/burst/consistency all INSUFFICIENT_DATA (0.5):
        = 0.50 * 0.333 + 0.20 * 0.500 + 0.15 * 0.500 + 0.15 * 0.500
        = 0.1665 + 0.1000 + 0.0750 + 0.0750 = 0.4165 → ROUND_HALF_UP → 0.417
        """
        result = compute_endpoint_score(
            _make_metrics(success_rate=Decimal("0.333"), numerator=1, denominator=3, execution_count=10),  # noqa: E501
            _make_stability(LABEL_INSUFFICIENT_DATA, LABEL_INSUFFICIENT_DATA),
            _make_burst(LABEL_INSUFFICIENT_DATA, LABEL_INSUFFICIENT_DATA),
            _make_consistency(LABEL_INSUFFICIENT_DATA),
        )
        assert result.composite_score == Decimal("0.417")
        assert str(result.composite_score) == "0.417"

    def test_score_not_below_zero(self):
        """SCORE-EP06a: no input combination can push composite below 0.0."""
        # Worst case: all DEGRADED / BURST_SUSPECTED / SPIKE_SUSPECTED / INCONSISTENT
        result = compute_endpoint_score(
            _make_metrics(success_rate=Decimal("0.000"), numerator=0, denominator=20, execution_count=20),  # noqa: E501
            _make_stability(LABEL_DEGRADED, LABEL_DEGRADED),
            _make_burst(LABEL_BURST_SUSPECTED, LABEL_SPIKE_SUSPECTED),
            _make_consistency(LABEL_INCONSISTENT),
        )
        assert result.composite_score >= Decimal("0.000")

    def test_score_not_above_one(self):
        """SCORE-EP06b: no input combination can push composite above 1.0."""
        result = compute_endpoint_score(*_all_passing_score())
        assert result.composite_score <= Decimal("1.000")

    def test_reliability_score_equals_success_rate(self):
        """SCORE-EP07: reliability_score is the success_rate value from metrics."""
        result = compute_endpoint_score(
            _make_metrics(success_rate=Decimal("0.870"), numerator=87, denominator=100),
            _make_stability(),
            _make_burst(),
            _make_consistency(),
        )
        assert result.reliability_score == Decimal("0.870")

    def test_reliability_score_zero_when_insufficient_data(self):
        """reliability_score = 0.0 when is_insufficient_data — no executable reliability evidence.

        Reliability is the primary direct evidence signal. 0.5 neutral is appropriate for
        derived analysis labels (stability/burst/consistency); reliability uses strict 0.0
        per Technical Design Section 13.3 Step 1.
        """
        result = compute_endpoint_score(*_all_insufficient())
        assert result.reliability_score == Decimal("0.000")

    def test_stability_score_is_mean_of_both_labels(self):
        """stability_score = (STABLE + DEGRADED) / 2 = (1.0 + 0.0) / 2 = 0.500."""
        result = compute_endpoint_score(
            _make_metrics(),
            _make_stability(LABEL_STABLE, LABEL_DEGRADED),
            _make_burst(),
            _make_consistency(),
        )
        assert result.stability_score == Decimal("0.500")

    def test_burst_score_is_mean_of_both_labels(self):
        """burst_score = (NO_BURST_DETECTED + SPIKE_SUSPECTED) / 2 = (1.0 + 0.0) / 2 = 0.500."""
        result = compute_endpoint_score(
            _make_metrics(),
            _make_stability(),
            _make_burst(LABEL_NO_BURST_DETECTED, LABEL_SPIKE_SUSPECTED),
            _make_consistency(),
        )
        assert result.burst_score == Decimal("0.500")

    def test_consistency_score_maps_label_directly(self):
        """consistency_score = LABEL_TO_SCORE[consistency_label]."""
        for label, expected_score in [
            (LABEL_CONSISTENT, Decimal("1.000")),
            (LABEL_INCONSISTENT, Decimal("0.000")),
            (LABEL_INSUFFICIENT_DATA, Decimal("0.500")),
        ]:
            result = compute_endpoint_score(
                _make_metrics(), _make_stability(), _make_burst(), _make_consistency(label)
            )
            assert result.consistency_score == expected_score, f"label={label}"

    def test_endpoint_id_passthrough(self):
        """endpoint_id in result matches input endpoint_id."""
        result = compute_endpoint_score(
            _make_metrics(endpoint_id="ep_specific"),
            _make_stability(), _make_burst(), _make_consistency(),
        )
        assert result.endpoint_id == "ep_specific"

    def test_all_degraded_worst_case_zero(self):
        """All DEGRADED/SUSPECTED/INCONSISTENT labels + success_rate 0.0 → composite = 0.000."""
        result = compute_endpoint_score(
            _make_metrics(success_rate=Decimal("0.000"), numerator=0, denominator=20),
            _make_stability(LABEL_DEGRADED, LABEL_DEGRADED),
            _make_burst(LABEL_BURST_SUSPECTED, LABEL_SPIKE_SUSPECTED),
            _make_consistency(LABEL_INCONSISTENT),
        )
        assert result.composite_score == Decimal("0.000")


# ---------------------------------------------------------------------------
# Score label assignment at boundaries — SCORE-LB01 through SCORE-LB08
# ---------------------------------------------------------------------------


class TestScoreLabelAssignment:
    def test_high_confidence_at_exact_threshold(self):
        """SCORE-LB01: 0.800 → HIGH_CONFIDENCE."""
        assert assign_score_label(Decimal("0.800")) == SCORE_LABEL_HIGH_CONFIDENCE

    def test_high_confidence_above_threshold(self):
        """SCORE-LB02: 0.801 → HIGH_CONFIDENCE."""
        assert assign_score_label(Decimal("0.801")) == SCORE_LABEL_HIGH_CONFIDENCE

    def test_high_confidence_at_perfect_score(self):
        """SCORE-LB03: 1.000 → HIGH_CONFIDENCE."""
        assert assign_score_label(Decimal("1.000")) == SCORE_LABEL_HIGH_CONFIDENCE

    def test_moderate_confidence_just_below_high_threshold(self):
        """SCORE-LB04: 0.799 → MODERATE_CONFIDENCE."""
        assert assign_score_label(Decimal("0.799")) == SCORE_LABEL_MODERATE_CONFIDENCE

    def test_moderate_confidence_at_lower_threshold(self):
        """SCORE-LB05: 0.500 → MODERATE_CONFIDENCE."""
        assert assign_score_label(Decimal("0.500")) == SCORE_LABEL_MODERATE_CONFIDENCE

    def test_low_confidence_just_below_moderate_threshold(self):
        """SCORE-LB06: 0.499 → LOW_CONFIDENCE."""
        assert assign_score_label(Decimal("0.499")) == SCORE_LABEL_LOW_CONFIDENCE

    def test_low_confidence_at_zero(self):
        """SCORE-LB07: 0.000 → LOW_CONFIDENCE."""
        assert assign_score_label(Decimal("0.000")) == SCORE_LABEL_LOW_CONFIDENCE

    def test_only_three_valid_label_values(self):
        """SCORE-LB08: only HIGH_CONFIDENCE, MODERATE_CONFIDENCE, LOW_CONFIDENCE are produced."""
        valid_labels = {SCORE_LABEL_HIGH_CONFIDENCE, SCORE_LABEL_MODERATE_CONFIDENCE, SCORE_LABEL_LOW_CONFIDENCE}  # noqa: E501
        probe_scores = [
            Decimal("0.000"), Decimal("0.001"), Decimal("0.499"), Decimal("0.500"),
            Decimal("0.501"), Decimal("0.799"), Decimal("0.800"), Decimal("0.801"),
            Decimal("1.000"),
        ]
        for score in probe_scores:
            label = assign_score_label(score)
            assert label in valid_labels, f"Unexpected label {label!r} for score {score}"

    def test_boundary_rounding_example_from_tech_design(self):
        """Section 13.6 example: 0.7995 rounds to 0.800 → HIGH_CONFIDENCE.

        The label is assigned AFTER rounding. This test verifies scoring produces
        the correct rounded value, then calls assign_score_label on the rounded score.
        """
        rounded = Decimal("0.7995").quantize(Decimal("0.001"), rounding=__import__("decimal").ROUND_HALF_UP)  # noqa: E501
        assert rounded == Decimal("0.800")
        assert assign_score_label(rounded) == SCORE_LABEL_HIGH_CONFIDENCE

    def test_high_confidence_threshold_constant_value(self):
        """HIGH_CONFIDENCE_THRESHOLD constant is exactly 0.80."""
        assert HIGH_CONFIDENCE_THRESHOLD == Decimal("0.80")

    def test_moderate_confidence_threshold_constant_value(self):
        """MODERATE_CONFIDENCE_THRESHOLD constant is exactly 0.50."""
        assert MODERATE_CONFIDENCE_THRESHOLD == Decimal("0.50")


# ---------------------------------------------------------------------------
# Audit-level composite rollup — SCORE-ROLL01 through SCORE-ROLL05
# ---------------------------------------------------------------------------


def _ep_score_from_composite(composite: Decimal, endpoint_id: str = "ep") -> "EndpointScoreResult":
    """Helper: build an EndpointScoreResult with a known composite_score by running the actual scorer."""  # noqa: E501
    # We need a real EndpointScoreResult; construct via compute_endpoint_score
    # with inputs that yield the desired composite. For exact control, use
    # reliability only (set analysis labels to INSUFFICIENT_DATA to neutralize them).
    # composite = 0.50*rel + 0.20*0.5 + 0.15*0.5 + 0.15*0.5 = 0.50*rel + 0.25
    # rel = (composite - 0.25) / 0.50
    from decimal import ROUND_HALF_UP as _RHU
    from decimal import Decimal as _D
    rel = (composite - _D("0.25")) / _D("0.50")
    rel = rel.quantize(_D("0.001"), rounding=_RHU)
    from release_confidence_platform.reliability_intelligence.constants import (
        LABEL_INSUFFICIENT_DATA as _LID,
    )
    from release_confidence_platform.reliability_intelligence.models import (
        BurstResult,
        ConsistencyResult,
        EndpointMetricsDTO,
        StabilityResult,
    )
    m = EndpointMetricsDTO(
        endpoint_id=endpoint_id,
        execution_count=20,
        success_rate=rel,
        success_inputs={"numerator": 0, "denominator": 20},
        failure_classification_counts={},
        latency_profile=None,
        timeout_count=0,
        is_insufficient_data=False,
    )
    s = StabilityResult(success_rate_stability_label=_LID, latency_stability_label=_LID, methodology_trace={})  # noqa: E501
    b = BurstResult(failure_burst_label=_LID, latency_spike_label=_LID, methodology_trace={})
    c = ConsistencyResult(consistency_label=_LID, methodology_trace={})
    return compute_endpoint_score(m, s, b, c)


class TestAuditRollup:
    def test_two_endpoint_unweighted_mean(self):
        """SCORE-ROLL01: (0.900 + 0.700) / 2 = 0.800."""
        ep1 = _ep_score_from_composite(Decimal("0.900"), "ep1")
        ep2 = _ep_score_from_composite(Decimal("0.700"), "ep2")
        audit = compute_audit_score([ep1, ep2])
        assert audit.composite_score == Decimal("0.800")

    def test_single_endpoint_rollup_equals_its_score(self):
        """SCORE-ROLL02: single endpoint → audit composite = that endpoint's composite."""
        ep = _ep_score_from_composite(Decimal("0.750"), "ep")
        audit = compute_audit_score([ep])
        assert audit.composite_score == Decimal("0.750")

    def test_three_endpoint_arithmetic_mean(self):
        """SCORE-ROLL03: (0.900 + 0.800 + 0.700) / 3 = 0.800."""
        ep1 = _ep_score_from_composite(Decimal("0.900"), "ep1")
        ep2 = _ep_score_from_composite(Decimal("0.800"), "ep2")
        ep3 = _ep_score_from_composite(Decimal("0.700"), "ep3")
        audit = compute_audit_score([ep1, ep2, ep3])
        assert audit.composite_score == Decimal("0.800")

    def test_rollup_result_has_three_decimal_places(self):
        """SCORE-ROLL04: rollup is rounded to 3 decimal places."""
        ep = _ep_score_from_composite(Decimal("0.750"), "ep")
        audit = compute_audit_score([ep])
        # Result must have exactly 3 decimal places
        assert audit.composite_score == audit.composite_score.quantize(Decimal("0.001"))

    def test_endpoint_count_matches_scored_endpoints(self):
        """SCORE-ROLL05: endpoint_count in result equals number of scored endpoints."""
        eps = [
            _ep_score_from_composite(Decimal("0.900"), "ep1"),
            _ep_score_from_composite(Decimal("0.800"), "ep2"),
            _ep_score_from_composite(Decimal("0.700"), "ep3"),
        ]
        audit = compute_audit_score(eps)
        assert audit.endpoint_count == 3

    def test_empty_endpoint_list_yields_zero_and_low_confidence(self):
        """Zero endpoints edge case: composite = 0.000, LOW_CONFIDENCE."""
        audit = compute_audit_score([])
        assert audit.composite_score == Decimal("0.000")
        assert audit.score_label == SCORE_LABEL_LOW_CONFIDENCE
        assert audit.endpoint_count == 0

    def test_rollup_score_label_reflects_final_composite(self):
        """Score label is assigned from the rolled-up composite, not per-endpoint labels."""
        ep = _ep_score_from_composite(Decimal("0.900"), "ep")
        audit = compute_audit_score([ep])
        assert audit.score_label == SCORE_LABEL_HIGH_CONFIDENCE

    def test_rollup_moderate_confidence_label(self):
        """Audit score in [0.50, 0.80) → MODERATE_CONFIDENCE."""
        ep = _ep_score_from_composite(Decimal("0.700"), "ep")
        audit = compute_audit_score([ep])
        assert audit.score_label == SCORE_LABEL_MODERATE_CONFIDENCE

    def test_rollup_low_confidence_label(self):
        """Audit score < 0.50 → LOW_CONFIDENCE."""
        # All DEGRADED/SUSPECTED/INCONSISTENT with success_rate 0.0
        result = compute_endpoint_score(
            _make_metrics(success_rate=Decimal("0.000"), numerator=0, denominator=20),
            _make_stability(LABEL_DEGRADED, LABEL_DEGRADED),
            _make_burst(LABEL_BURST_SUSPECTED, LABEL_SPIKE_SUSPECTED),
            _make_consistency(LABEL_INCONSISTENT),
        )
        audit = compute_audit_score([result])
        assert audit.score_label == SCORE_LABEL_LOW_CONFIDENCE

    def test_rollup_rounding_half_up(self):
        """Rollup rounding: mean that rounds half-up at 4th decimal."""
        # Need 3 scores that average to X.XXX5 exactly
        # 0.601 + 0.601 + 0.600 = 1.802 / 3 = 0.60066... which doesn't help
        # Use 2 endpoints: 0.501 + 0.500 / 2 = 0.5005 → ROUND_HALF_UP → 0.501? No, 0.5005 → 0.501
        # Actually: 0.5005 → 4th decimal is 5 → round up 3rd decimal from 0 to 1 → 0.501
        ep1 = _ep_score_from_composite(Decimal("0.501"), "ep1")
        ep2 = _ep_score_from_composite(Decimal("0.500"), "ep2")
        audit = compute_audit_score([ep1, ep2])
        # mean = 0.5005 → rounds to 0.501 with ROUND_HALF_UP
        assert audit.composite_score == Decimal("0.501")

    def test_endpoint_scores_list_in_result(self):
        """AuditScoreResult.endpoint_scores contains the per-endpoint results."""
        eps = [
            _ep_score_from_composite(Decimal("0.900"), "ep1"),
            _ep_score_from_composite(Decimal("0.800"), "ep2"),
        ]
        audit = compute_audit_score(eps)
        assert len(audit.endpoint_scores) == 2

    def test_component_breakdown_present(self):
        """AuditScoreResult has a component_breakdown dict with four components."""
        audit = compute_audit_score([_ep_score_from_composite(Decimal("0.800"), "ep")])
        assert "reliability" in audit.component_breakdown
        assert "stability" in audit.component_breakdown
        assert "burst" in audit.component_breakdown
        assert "consistency" in audit.component_breakdown

    def test_component_breakdown_has_weight_value_description(self):
        """Each component_breakdown entry has weight, value, and description keys."""
        audit = compute_audit_score([_ep_score_from_composite(Decimal("0.800"), "ep")])
        for component in ["reliability", "stability", "burst", "consistency"]:
            entry = audit.component_breakdown[component]
            assert "weight" in entry, f"Missing weight in {component}"
            assert "value" in entry, f"Missing value in {component}"
            assert "description" in entry, f"Missing description in {component}"


# ---------------------------------------------------------------------------
# Evidence trace — SCORE-EV01, SCORE-EV02
# ---------------------------------------------------------------------------


class TestEvidenceTrace:
    def test_audit_result_preserves_aggregate_set_hash(self):
        """SCORE-EV01: aggregate_set_hash passed to compute_audit_score is present in result."""
        known_hash = "abc123def456"
        ep = _ep_score_from_composite(Decimal("0.800"), "ep")
        audit = compute_audit_score([ep], aggregate_set_hash=known_hash)
        assert audit.aggregate_set_hash == known_hash

    def test_audit_result_hash_none_when_not_provided(self):
        """aggregate_set_hash is None when not provided (default)."""
        ep = _ep_score_from_composite(Decimal("0.800"), "ep")
        audit = compute_audit_score([ep])
        assert audit.aggregate_set_hash is None

    def test_per_endpoint_score_derivation_includes_component_scores(self):
        """SCORE-EV02: endpoint result has all four component scores."""
        result = compute_endpoint_score(*_all_passing_score())
        assert hasattr(result, "reliability_score")
        assert hasattr(result, "stability_score")
        assert hasattr(result, "burst_score")
        assert hasattr(result, "consistency_score")

    def test_per_endpoint_score_derivation_dict_present(self):
        """score_derivation dict is present and contains formula strings."""
        result = compute_endpoint_score(*_all_passing_score())
        assert isinstance(result.score_derivation, dict)
        assert "reliability_score_source" in result.score_derivation
        assert "composite_score_formula" in result.score_derivation

    def test_score_derivation_contains_stability_formula(self):
        """score_derivation includes the stability formula string."""
        result = compute_endpoint_score(*_all_passing_score())
        assert "stability_score_formula" in result.score_derivation

    def test_score_derivation_contains_burst_formula(self):
        """score_derivation includes the burst formula string."""
        result = compute_endpoint_score(*_all_passing_score())
        assert "burst_score_formula" in result.score_derivation

    def test_score_derivation_contains_consistency_formula(self):
        """score_derivation includes the consistency formula string."""
        result = compute_endpoint_score(*_all_passing_score())
        assert "consistency_score_formula" in result.score_derivation


# ---------------------------------------------------------------------------
# Methodology disclosure — SCORE-DISC01, SCORE-DISC02, SCORE-DISC03
# ---------------------------------------------------------------------------


class TestMethodologyDisclosure:
    def setup_method(self):
        self.disclosure = build_methodology_disclosure()

    def test_methodology_disclosure_is_a_dict(self):
        """SCORE-DISC01: build_methodology_disclosure() returns a dict (the disclosure section)."""
        assert isinstance(self.disclosure, dict)

    def test_scoring_section_present(self):
        """SCORE-DISC01: disclosure includes a 'scoring' top-level key."""
        assert "scoring" in self.disclosure

    def test_limitations_array_present_and_non_empty(self):
        """SCORE-DISC02: methodology_disclosure.limitations is a non-empty array."""
        assert "limitations" in self.disclosure
        limitations = self.disclosure["limitations"]
        assert isinstance(limitations, list)
        assert len(limitations) > 0

    def test_per_endpoint_formula_present(self):
        """SCORE-DISC03: scoring.per_endpoint_formula is present with the exact weighted formula."""
        scoring = self.disclosure["scoring"]
        assert "per_endpoint_formula" in scoring
        formula = scoring["per_endpoint_formula"]
        assert isinstance(formula, str)
        assert len(formula) > 0
        # Must contain the four weight values
        assert "0.50" in formula
        assert "0.20" in formula
        assert "0.15" in formula

    def test_label_to_score_mapping_present(self):
        """methodology_disclosure contains label_to_score_mapping."""
        assert "label_to_score_mapping" in self.disclosure
        mapping = self.disclosure["label_to_score_mapping"]
        assert isinstance(mapping, dict)
        assert len(mapping) > 0

    def test_label_to_score_mapping_values_match_constants(self):
        """label_to_score_mapping values agree with LABEL_TO_SCORE constants."""
        mapping = self.disclosure["label_to_score_mapping"]
        for label, expected_decimal in LABEL_TO_SCORE.items():
            assert label in mapping, f"Missing label {label} in disclosure mapping"
            assert mapping[label] == float(expected_decimal)

    def test_component_weights_present(self):
        """methodology_disclosure.scoring.component_weights has all four components."""
        weights = self.disclosure["scoring"]["component_weights"]
        assert "reliability" in weights
        assert "stability" in weights
        assert "burst" in weights
        assert "consistency" in weights

    def test_component_weights_sum_to_one(self):
        """Component weights in disclosure sum to 1.0."""
        weights = self.disclosure["scoring"]["component_weights"]
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-10

    def test_intelligence_version_present(self):
        """methodology_disclosure includes intelligence_version."""
        assert "intelligence_version" in self.disclosure
        assert self.disclosure["intelligence_version"] == "intel_v1"

    def test_limitations_include_burst_timing_phrase(self):
        """Limitations include the required burst timing wording from tech design."""
        phrase = "burst timing attribution cannot be determined from agg_v1 inputs"
        limitations = self.disclosure["limitations"]
        assert any(phrase in lim for lim in limitations)

    def test_limitations_include_per_run_consistency_phrase(self):
        """Limitations include the required per-run consistency wording from tech design."""
        phrase = "per-run or per-scenario consistency is not assessable from agg_v1"
        limitations = self.disclosure["limitations"]
        assert any(phrase in lim for lim in limitations)


# ---------------------------------------------------------------------------
# Label-to-score constant — LABEL_TO_SCORE validation
# ---------------------------------------------------------------------------


class TestLabelToScoreConstant:
    def test_stable_maps_to_1_0(self):
        assert LABEL_TO_SCORE[LABEL_STABLE] == Decimal("1.0")

    def test_degraded_maps_to_0_0(self):
        assert LABEL_TO_SCORE[LABEL_DEGRADED] == Decimal("0.0")

    def test_insufficient_data_maps_to_0_5(self):
        assert LABEL_TO_SCORE[LABEL_INSUFFICIENT_DATA] == Decimal("0.5")

    def test_consistent_maps_to_1_0(self):
        assert LABEL_TO_SCORE[LABEL_CONSISTENT] == Decimal("1.0")

    def test_inconsistent_maps_to_0_0(self):
        assert LABEL_TO_SCORE[LABEL_INCONSISTENT] == Decimal("0.0")

    def test_no_burst_detected_maps_to_1_0(self):
        assert LABEL_TO_SCORE[LABEL_NO_BURST_DETECTED] == Decimal("1.0")

    def test_burst_suspected_maps_to_0_0(self):
        assert LABEL_TO_SCORE[LABEL_BURST_SUSPECTED] == Decimal("0.0")

    def test_no_spike_detected_maps_to_1_0(self):
        assert LABEL_TO_SCORE[LABEL_NO_SPIKE_DETECTED] == Decimal("1.0")

    def test_spike_suspected_maps_to_0_0(self):
        assert LABEL_TO_SCORE[LABEL_SPIKE_SUSPECTED] == Decimal("0.0")

    def test_nine_labels_total(self):
        """LABEL_TO_SCORE has exactly 9 entries."""
        assert len(LABEL_TO_SCORE) == 9


# ---------------------------------------------------------------------------
# EndpointScoreResult DTO structure
# ---------------------------------------------------------------------------


class TestEndpointScoreResultStructure:
    def test_result_has_all_expected_fields(self):
        """EndpointScoreResult has all required fields."""
        result = compute_endpoint_score(*_all_passing_score())
        for field in [
            "endpoint_id", "composite_score", "reliability_score",
            "stability_score", "burst_score", "consistency_score", "score_derivation",
        ]:
            assert hasattr(result, field), f"Missing field: {field}"

    def test_result_is_frozen(self):
        """EndpointScoreResult is immutable."""
        result = compute_endpoint_score(*_all_passing_score())
        with pytest.raises(AttributeError):
            result.composite_score = Decimal("0.000")  # type: ignore[misc]

    def test_determinism_same_inputs_produce_same_result(self):
        """Same inputs produce identical output (NFR-1)."""
        metrics = _make_metrics(success_rate=Decimal("0.850"), numerator=17, denominator=20)
        stab = _make_stability(LABEL_STABLE, LABEL_DEGRADED)
        burst = _make_burst(LABEL_NO_BURST_DETECTED, LABEL_INSUFFICIENT_DATA)
        cons = _make_consistency(LABEL_INCONSISTENT)
        result_a = compute_endpoint_score(metrics, stab, burst, cons)
        result_b = compute_endpoint_score(metrics, stab, burst, cons)
        assert result_a.composite_score == result_b.composite_score
        assert result_a.reliability_score == result_b.reliability_score
        assert result_a.stability_score == result_b.stability_score
        assert result_a.burst_score == result_b.burst_score
        assert result_a.consistency_score == result_b.consistency_score


# ---------------------------------------------------------------------------
# AuditScoreResult DTO structure
# ---------------------------------------------------------------------------


class TestAuditScoreResultStructure:
    def test_result_has_all_expected_fields(self):
        """AuditScoreResult has all required fields."""
        ep = _ep_score_from_composite(Decimal("0.800"), "ep")
        audit = compute_audit_score([ep])
        for field_name in [
            "composite_score", "score_label", "endpoint_count",
            "aggregate_set_hash", "component_breakdown", "endpoint_scores",
        ]:
            assert hasattr(audit, field_name), f"Missing field: {field_name}"

    def test_score_label_is_string(self):
        """score_label is one of the three valid string labels."""
        ep = _ep_score_from_composite(Decimal("0.800"), "ep")
        audit = compute_audit_score([ep])
        assert audit.score_label in {
            SCORE_LABEL_HIGH_CONFIDENCE, SCORE_LABEL_MODERATE_CONFIDENCE, SCORE_LABEL_LOW_CONFIDENCE
        }

    def test_composite_score_is_decimal(self):
        """composite_score is a Decimal."""
        ep = _ep_score_from_composite(Decimal("0.800"), "ep")
        audit = compute_audit_score([ep])
        assert isinstance(audit.composite_score, Decimal)

    def test_determinism_same_endpoint_scores_produce_same_audit(self):
        """Same endpoint scores produce identical audit result (NFR-1)."""
        eps = [
            _ep_score_from_composite(Decimal("0.900"), "ep1"),
            _ep_score_from_composite(Decimal("0.700"), "ep2"),
        ]
        audit_a = compute_audit_score(eps)
        audit_b = compute_audit_score(eps)
        assert audit_a.composite_score == audit_b.composite_score
        assert audit_a.score_label == audit_b.score_label
        assert audit_a.endpoint_count == audit_b.endpoint_count
