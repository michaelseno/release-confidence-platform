"""Phase 5.5 — Outcome consistency estimation from aggregate success rate.

Pure computation module: no I/O, no storage access, no network calls.

Implements one algorithm:

  outcome_consistency_v1:
    Uses the Bernoulli variance formula p*(1-p) applied to the aggregate-level
    success rate p. Endpoints near p=0 or p=1 are CONSISTENT (uniform outcomes).
    Endpoints near p=0.5 are INCONSISTENT (mixed outcomes).

DESIGN NOTE — agg_v1 limitations:
  agg_v1 provides full-window aggregate counts only. Per-run or per-scenario
  consistency — whether the same endpoint consistently passes or fails across
  independent runs — is not assessable from agg_v1. The Bernoulli variance
  formula is a proxy for aggregate-level outcome uniformity only.

All thresholds are imported from constants.py. No magic numbers in this module.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from release_confidence_platform.reliability_intelligence.constants import (
    INTELLIGENCE_VERSION,
    LABEL_CONSISTENT,
    LABEL_INCONSISTENT,
    LABEL_INSUFFICIENT_DATA,
    MIN_EXECUTION_COUNT,
    OUTCOME_CONSISTENCY_ALGORITHM,
    VARIANCE_CONSISTENT_THRESHOLD,
)
from release_confidence_platform.reliability_intelligence.models import (
    ConsistencyResult,
    EndpointMetricsDTO,
)


def compute_consistency_analysis(endpoint_metrics: EndpointMetricsDTO) -> ConsistencyResult:
    """Run outcome_consistency_v1 for one endpoint.

    Uses Bernoulli variance p*(1-p) as a proxy for aggregate-level outcome
    uniformity. Per-run consistency is not assessable from agg_v1.

    Args:
        endpoint_metrics: EndpointMetricsDTO produced by metrics.py for this endpoint.

    Returns:
        ConsistencyResult with the consistency label and methodology trace.
    """
    label, determination, outcome_variance = _outcome_consistency_v1(endpoint_metrics)

    methodology_trace = _build_methodology_trace(
        endpoint_metrics=endpoint_metrics,
        determination=determination,
        outcome_variance=outcome_variance,
    )

    return ConsistencyResult(
        consistency_label=label,
        methodology_trace=methodology_trace,
    )


# ---------------------------------------------------------------------------
# Algorithm: outcome_consistency_v1
# ---------------------------------------------------------------------------


def _outcome_consistency_v1(
    endpoint_metrics: EndpointMetricsDTO,
) -> tuple[str, str, Decimal | None]:
    """outcome_consistency_v1 — Section 12.1 of Phase 5 technical design.

    Returns (label, determination_text, outcome_variance).
    outcome_variance is None when INSUFFICIENT_DATA.
    """
    execution_count = endpoint_metrics.execution_count
    denominator = endpoint_metrics.success_inputs.get("denominator", 0)
    success_rate = endpoint_metrics.success_rate

    if execution_count < MIN_EXECUTION_COUNT or denominator == 0:
        return (
            LABEL_INSUFFICIENT_DATA,
            (
                f"execution_count {execution_count} < MIN_EXECUTION_COUNT "
                f"{MIN_EXECUTION_COUNT} or denominator = 0 → {LABEL_INSUFFICIENT_DATA}"
            ),
            None,
        )

    # p is the rounded success_rate produced by metrics.py (Decimal, 3 places).
    p = success_rate
    outcome_variance = p * (Decimal("1") - p)

    if outcome_variance <= VARIANCE_CONSISTENT_THRESHOLD:
        return (
            LABEL_CONSISTENT,
            (
                f"outcome_variance {outcome_variance} <= VARIANCE_CONSISTENT_THRESHOLD "
                f"{VARIANCE_CONSISTENT_THRESHOLD} → {LABEL_CONSISTENT}"
            ),
            outcome_variance,
        )

    return (
        LABEL_INCONSISTENT,
        (
            f"outcome_variance {outcome_variance} > VARIANCE_CONSISTENT_THRESHOLD "
            f"{VARIANCE_CONSISTENT_THRESHOLD} → {LABEL_INCONSISTENT}"
        ),
        outcome_variance,
    )


# ---------------------------------------------------------------------------
# Methodology trace builder
# ---------------------------------------------------------------------------


def _build_methodology_trace(
    endpoint_metrics: EndpointMetricsDTO,
    determination: str,
    outcome_variance: Decimal | None,
) -> dict[str, Any]:
    """Build the methodology trace dict for the S3 artifact.

    Structure matches docs/architecture/phase_5_reliability_intelligence_technical_design.md
    Section 8.2 consistency_analysis.methodology_trace schema.
    """
    inputs: dict[str, Any] = {
        "execution_count": endpoint_metrics.execution_count,
        "success_rate": (
            str(endpoint_metrics.success_rate)
            if endpoint_metrics.success_rate is not None
            else None
        ),
        "success_rate_numerator": endpoint_metrics.success_inputs.get("numerator"),
        "success_rate_denominator": endpoint_metrics.success_inputs.get("denominator"),
    }

    thresholds: dict[str, Any] = {
        "MIN_EXECUTION_COUNT": int(MIN_EXECUTION_COUNT),
        "VARIANCE_CONSISTENT_THRESHOLD": float(VARIANCE_CONSISTENT_THRESHOLD),
    }

    label_determination = (
        f"{OUTCOME_CONSISTENCY_ALGORITHM}: {determination}. "
        "per-run or per-scenario consistency is not assessable from agg_v1."
    )

    return {
        "algorithm": OUTCOME_CONSISTENCY_ALGORITHM,
        "algorithm_version": INTELLIGENCE_VERSION,
        "inputs": inputs,
        "thresholds": thresholds,
        "intermediate_values": {"outcome_variance": outcome_variance},
        "label_determination": label_determination,
    }
