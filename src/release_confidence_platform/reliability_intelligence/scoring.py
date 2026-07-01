"""Phase 5.6 — Release Confidence Scoring.

Pure computation module: no I/O, no storage access, no network calls.

Implements the intel_v1 composite scoring formula (Section 13 of Phase 5 technical design):

  Per-endpoint composite:
    composite_score = round(
        0.50 * reliability_score
      + 0.20 * stability_score
      + 0.15 * burst_score
      + 0.15 * consistency_score, 3)

  Audit-level rollup:
    audit_score = round(mean(endpoint_composite_scores), 3)

  Score label assignment (from the fully-rounded audit_score):
    HIGH_CONFIDENCE     : audit_score >= 0.80
    MODERATE_CONFIDENCE : audit_score >= 0.50
    LOW_CONFIDENCE      : audit_score  < 0.50

All arithmetic uses Python Decimal with ROUND_HALF_UP (NFR-1 determinism requirement).
No magic numbers: all thresholds, weights, and label constants imported from constants.py.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from release_confidence_platform.reliability_intelligence.constants import (
    HIGH_CONFIDENCE_THRESHOLD,
    INTELLIGENCE_VERSION,
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
    AuditScoreResult,
    BurstResult,
    ConsistencyResult,
    EndpointMetricsDTO,
    EndpointScoreResult,
    StabilityResult,
)

_PRECISION = Decimal("0.001")
_TWO = Decimal("2")
_ZERO = Decimal("0")

# Static formula strings for S3 artifact score_derivation field.
_SCORE_DERIVATION: dict[str, str] = {
    "reliability_score_source": "success_rate (or 0.0 when is_insufficient_data)",
    "stability_score_formula": "(label_to_value(sr_stability) + label_to_value(lat_stability)) / 2.0",
    "burst_score_formula": "(label_to_value(failure_burst) + label_to_value(spike)) / 2.0",
    "consistency_score_formula": "label_to_value(consistency)",
    "composite_score_formula": "0.50 * reliability_score + 0.20 * stability_score + 0.15 * burst_score + 0.15 * consistency_score",
}


def compute_endpoint_score(
    endpoint_metrics: EndpointMetricsDTO,
    stability_result: StabilityResult,
    burst_result: BurstResult,
    consistency_result: ConsistencyResult,
) -> EndpointScoreResult:
    """Compute the intel_v1 composite score for one endpoint (Section 13.3).

    Args:
        endpoint_metrics: EndpointMetricsDTO from metrics.py.
        stability_result: StabilityResult from stability.py.
        burst_result: BurstResult from burst.py.
        consistency_result: ConsistencyResult from consistency.py.

    Returns:
        EndpointScoreResult with composite and component scores.
    """
    reliability_score = _reliability_score(endpoint_metrics)
    stability_score = _stability_score(stability_result)
    burst_score = _burst_score(burst_result)
    consistency_score = _consistency_score(consistency_result)

    composite = (
        WEIGHT_RELIABILITY * reliability_score
        + WEIGHT_STABILITY * stability_score
        + WEIGHT_BURST * burst_score
        + WEIGHT_CONSISTENCY * consistency_score
    ).quantize(_PRECISION, rounding=ROUND_HALF_UP)

    return EndpointScoreResult(
        endpoint_id=endpoint_metrics.endpoint_id,
        composite_score=composite,
        reliability_score=reliability_score,
        stability_score=stability_score,
        burst_score=burst_score,
        consistency_score=consistency_score,
        score_derivation=dict(_SCORE_DERIVATION),
    )


def compute_audit_score(
    endpoint_scores: list[EndpointScoreResult],
    aggregate_set_hash: str | None = None,
) -> AuditScoreResult:
    """Compute the audit-level composite score rollup (Section 13.4).

    Unweighted arithmetic mean of per-endpoint composite scores. All endpoints
    contribute equally regardless of execution volume. Returns 0.0 when no
    endpoint scores are provided.

    Args:
        endpoint_scores: Per-endpoint EndpointScoreResult list.
        aggregate_set_hash: AggregateSetCompletion hash for lineage tracing.

    Returns:
        AuditScoreResult with composite score, label, component breakdown, and endpoint list.
    """
    if not endpoint_scores:
        return AuditScoreResult(
            composite_score=_ZERO.quantize(_PRECISION, rounding=ROUND_HALF_UP),
            score_label=SCORE_LABEL_LOW_CONFIDENCE,
            endpoint_count=0,
            aggregate_set_hash=aggregate_set_hash,
            component_breakdown=_empty_component_breakdown(),
            endpoint_scores=[],
        )

    n = Decimal(str(len(endpoint_scores)))
    composite = (
        sum((ep.composite_score for ep in endpoint_scores), _ZERO) / n
    ).quantize(_PRECISION, rounding=ROUND_HALF_UP)

    score_label = assign_score_label(composite)
    component_breakdown = _build_component_breakdown(endpoint_scores)

    return AuditScoreResult(
        composite_score=composite,
        score_label=score_label,
        endpoint_count=len(endpoint_scores),
        aggregate_set_hash=aggregate_set_hash,
        component_breakdown=component_breakdown,
        endpoint_scores=list(endpoint_scores),
    )


def assign_score_label(score: Decimal) -> str:
    """Assign HIGH_CONFIDENCE / MODERATE_CONFIDENCE / LOW_CONFIDENCE from a rounded score.

    Assignment order is invariant per Section 13.6: HIGH first, then MODERATE, else LOW.

    Args:
        score: Already-rounded Decimal score (3 decimal places).

    Returns:
        One of SCORE_LABEL_HIGH_CONFIDENCE, SCORE_LABEL_MODERATE_CONFIDENCE,
        SCORE_LABEL_LOW_CONFIDENCE.
    """
    if score >= HIGH_CONFIDENCE_THRESHOLD:
        return SCORE_LABEL_HIGH_CONFIDENCE
    if score >= MODERATE_CONFIDENCE_THRESHOLD:
        return SCORE_LABEL_MODERATE_CONFIDENCE
    return SCORE_LABEL_LOW_CONFIDENCE


def build_methodology_disclosure() -> dict[str, Any]:
    """Build the methodology_disclosure section of the S3 intelligence artifact.

    Includes the complete intel_v1 scoring specification: formula, weights, label
    definitions, label-to-score mapping, and known limitations. Referenced by
    SCORE-DISC01, SCORE-DISC02, and SCORE-DISC03 in the QA plan.

    Returns:
        Dict suitable for the S3 artifact methodology_disclosure field.
    """
    return {
        "intelligence_version": INTELLIGENCE_VERSION,
        "scoring": {
            "composite_score_range": "[0.0, 1.0]",
            "rollup": "Unweighted arithmetic mean of per-endpoint composite scores",
            "precision": "3 decimal places, half-up rounding via Python Decimal",
            "component_weights": {
                "reliability": float(WEIGHT_RELIABILITY),
                "stability": float(WEIGHT_STABILITY),
                "burst": float(WEIGHT_BURST),
                "consistency": float(WEIGHT_CONSISTENCY),
            },
            "per_endpoint_formula": (
                "0.50 * reliability_score + 0.20 * stability_score "
                "+ 0.15 * burst_score + 0.15 * consistency_score"
            ),
        },
        "stability_label_definitions": {
            "STABLE": "success_rate >= 0.95 and no high-spread latency ratios detected",
            "DEGRADED": "success_rate < 0.95 or p99/mean > 3.0 or max/p95 > 2.0",
            "INSUFFICIENT_DATA": "execution_count < 10 or latency_count < 5",
        },
        "burst_label_definitions": {
            "NO_BURST_DETECTED": "timeout proportion <= 0.20",
            "BURST_SUSPECTED": "timeout proportion > 0.20",
            "INSUFFICIENT_DATA": "execution_count < 10; spike: latency_count < 5 or p99/max not available",
        },
        "consistency_label_definitions": {
            "CONSISTENT": "Bernoulli variance p*(1-p) <= 0.05",
            "INCONSISTENT": "Bernoulli variance p*(1-p) > 0.05",
            "INSUFFICIENT_DATA": "execution_count < 10",
        },
        "label_to_score_mapping": {
            label: float(value) for label, value in LABEL_TO_SCORE.items()
        },
        "limitations": [
            "burst timing attribution cannot be determined from agg_v1 inputs",
            "per-run or per-scenario consistency is not assessable from agg_v1",
            "stability characterization is distributional, not temporal",
            "all intel_v1 labels reflect distributional characterization, not temporal assessment",
            "endpoint rollup assigns equal weight to all endpoints regardless of execution volume",
        ],
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _reliability_score(endpoint_metrics: EndpointMetricsDTO) -> Decimal:
    """Return success_rate as the reliability component, or 0.0 if no executable reliability evidence.

    Per Technical Design Section 13.3 Step 1: when denominator = 0 or execution_count = 0,
    reliability_score = 0.0. Reliability is the primary direct evidence component — the 0.5
    neutral INSUFFICIENT_DATA score is appropriate for secondary derived labels (stability,
    burst, consistency) but not for reliability, where no evidence means zero demonstrated
    successful outcomes.
    """
    if endpoint_metrics.is_insufficient_data or endpoint_metrics.success_rate is None:
        return _ZERO.quantize(_PRECISION, rounding=ROUND_HALF_UP)
    return endpoint_metrics.success_rate.quantize(_PRECISION, rounding=ROUND_HALF_UP)


def _stability_score(stability_result: StabilityResult) -> Decimal:
    """Average success_rate_stability and latency_stability label scores."""
    sr_val = LABEL_TO_SCORE[stability_result.success_rate_stability_label]
    lat_val = LABEL_TO_SCORE[stability_result.latency_stability_label]
    return ((sr_val + lat_val) / _TWO).quantize(_PRECISION, rounding=ROUND_HALF_UP)


def _burst_score(burst_result: BurstResult) -> Decimal:
    """Average failure_burst and latency_spike label scores."""
    fb_val = LABEL_TO_SCORE[burst_result.failure_burst_label]
    spike_val = LABEL_TO_SCORE[burst_result.latency_spike_label]
    return ((fb_val + spike_val) / _TWO).quantize(_PRECISION, rounding=ROUND_HALF_UP)


def _consistency_score(consistency_result: ConsistencyResult) -> Decimal:
    """Map consistency label to its numeric score."""
    return LABEL_TO_SCORE[consistency_result.consistency_label].quantize(
        _PRECISION, rounding=ROUND_HALF_UP
    )


def _build_component_breakdown(
    endpoint_scores: list[EndpointScoreResult],
) -> dict[str, Any]:
    """Build per-component mean scores for the S3 composite_score.component_breakdown."""
    n = Decimal(str(len(endpoint_scores)))
    mean_reliability = (
        sum((ep.reliability_score for ep in endpoint_scores), _ZERO) / n
    ).quantize(_PRECISION, rounding=ROUND_HALF_UP)
    mean_stability = (
        sum((ep.stability_score for ep in endpoint_scores), _ZERO) / n
    ).quantize(_PRECISION, rounding=ROUND_HALF_UP)
    mean_burst = (
        sum((ep.burst_score for ep in endpoint_scores), _ZERO) / n
    ).quantize(_PRECISION, rounding=ROUND_HALF_UP)
    mean_consistency = (
        sum((ep.consistency_score for ep in endpoint_scores), _ZERO) / n
    ).quantize(_PRECISION, rounding=ROUND_HALF_UP)

    return {
        "reliability": {
            "weight": float(WEIGHT_RELIABILITY),
            "value": str(mean_reliability),
            "description": "Unweighted arithmetic mean of per-endpoint success rates",
        },
        "stability": {
            "weight": float(WEIGHT_STABILITY),
            "value": str(mean_stability),
            "description": "Mean of per-endpoint stability scores derived from stability label mappings",
        },
        "burst": {
            "weight": float(WEIGHT_BURST),
            "value": str(mean_burst),
            "description": "Mean of per-endpoint burst scores derived from burst and spike label mappings",
        },
        "consistency": {
            "weight": float(WEIGHT_CONSISTENCY),
            "value": str(mean_consistency),
            "description": "Mean of per-endpoint consistency scores derived from consistency label mappings",
        },
    }


def _empty_component_breakdown() -> dict[str, Any]:
    """Component breakdown for the zero-endpoint edge case."""
    return {
        "reliability": {"weight": float(WEIGHT_RELIABILITY), "value": "0.000", "description": "No endpoints"},
        "stability": {"weight": float(WEIGHT_STABILITY), "value": "0.000", "description": "No endpoints"},
        "burst": {"weight": float(WEIGHT_BURST), "value": "0.000", "description": "No endpoints"},
        "consistency": {"weight": float(WEIGHT_CONSISTENCY), "value": "0.000", "description": "No endpoints"},
    }
