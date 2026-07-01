"""Phase 5.3 — Distributional stability characterization of success rate and latency.

Pure computation module: no I/O, no storage access, no network calls.

Implements two distributional proxy algorithms over full-window agg_v1 aggregate fields:

  success_rate_stability_v1:
    Uses aggregate success_rate against a fixed threshold. Does not assess temporal trends.

  latency_stability_v1:
    Uses p99/mean and max/p95 spread ratios as distributional proxies. Does not assess
    whether latency changed over time.

DESIGN NOTE — distributional proxies:
  agg_v1 provides full-window summary statistics only. No time-bucketed sub-totals exist.
  Stability labels characterize distributional properties of the full observation window.
  Temporal claims (degradation onset, ordering within the window) are not possible from
  agg_v1 and must not be made. This is an explicit documented boundary of intel_v1.

All thresholds are imported from constants.py. No magic numbers in this module.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

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
from release_confidence_platform.reliability_intelligence.models import (
    EndpointMetricsDTO,
    StabilityResult,
)


def compute_stability_analysis(endpoint_metrics: EndpointMetricsDTO) -> StabilityResult:
    """Run success_rate_stability_v1 and latency_stability_v1 for one endpoint.

    Both algorithms use distributional proxies from full-window agg_v1 aggregate fields.
    Neither makes temporal claims about when within the window any degradation occurred.

    Args:
        endpoint_metrics: EndpointMetricsDTO produced by metrics.py for this endpoint.

    Returns:
        StabilityResult with both stability labels and a combined methodology trace.
    """
    sr_label, sr_determination = _success_rate_stability_v1(endpoint_metrics)
    lat_label, lat_determination, lat_intermediate = _latency_stability_v1(endpoint_metrics)

    methodology_trace = _build_methodology_trace(
        endpoint_metrics=endpoint_metrics,
        sr_determination=sr_determination,
        lat_determination=lat_determination,
        lat_intermediate=lat_intermediate,
    )

    return StabilityResult(
        success_rate_stability_label=sr_label,
        latency_stability_label=lat_label,
        methodology_trace=methodology_trace,
    )


# ---------------------------------------------------------------------------
# Algorithm: success_rate_stability_v1
# ---------------------------------------------------------------------------


def _success_rate_stability_v1(
    endpoint_metrics: EndpointMetricsDTO,
) -> tuple[str, str]:
    """success_rate_stability_v1 — Section 10.1 of Phase 5 technical design.

    Returns (label, determination_text).
    """
    execution_count = endpoint_metrics.execution_count
    denominator = endpoint_metrics.success_inputs.get("denominator", 0)
    success_rate = endpoint_metrics.success_rate

    if execution_count < MIN_EXECUTION_COUNT:
        return (
            LABEL_INSUFFICIENT_DATA,
            (
                f"execution_count {execution_count} < MIN_EXECUTION_COUNT "
                f"{MIN_EXECUTION_COUNT} → {LABEL_INSUFFICIENT_DATA}"
            ),
        )

    if denominator == 0:
        return (
            LABEL_INSUFFICIENT_DATA,
            f"success_inputs.denominator = 0 → {LABEL_INSUFFICIENT_DATA}",
        )

    if success_rate >= STABLE_THRESHOLD:
        return (
            LABEL_STABLE,
            (
                f"success_rate {success_rate} >= STABLE_THRESHOLD "
                f"{STABLE_THRESHOLD} → {LABEL_STABLE}"
            ),
        )

    return (
        LABEL_DEGRADED,
        (
            f"success_rate {success_rate} < STABLE_THRESHOLD "
            f"{STABLE_THRESHOLD} → {LABEL_DEGRADED}"
        ),
    )


# ---------------------------------------------------------------------------
# Algorithm: latency_stability_v1
# ---------------------------------------------------------------------------


def _latency_stability_v1(
    endpoint_metrics: EndpointMetricsDTO,
) -> tuple[str, str, dict[str, Any]]:
    """latency_stability_v1 — Section 10.2 of Phase 5 technical design.

    Returns (label, determination_text, intermediate_values).
    intermediate_values keys: p99_mean_ratio, max_p95_ratio (Decimal or None).
    """
    latency_profile = endpoint_metrics.latency_profile or {}
    latency_count: int = latency_profile.get("count", 0)
    mean_raw = latency_profile.get("mean")
    p99_raw = latency_profile.get("p99")
    max_raw = latency_profile.get("max")
    p95_raw = latency_profile.get("p95")

    if latency_count < MIN_LATENCY_COUNT or mean_raw is None:
        return (
            LABEL_INSUFFICIENT_DATA,
            (
                f"latency_count {latency_count} < MIN_LATENCY_COUNT {MIN_LATENCY_COUNT} "
                f"or latency_mean_ms is null → {LABEL_INSUFFICIENT_DATA}"
            ),
            {"p99_mean_ratio": None, "max_p95_ratio": None},
        )

    mean_dec = Decimal(str(mean_raw))
    p99_dec = Decimal(str(p99_raw)) if p99_raw is not None else None
    max_dec = Decimal(str(max_raw)) if max_raw is not None else None
    p95_dec = Decimal(str(p95_raw)) if p95_raw is not None else None

    p99_mean_ratio: Decimal | None = None
    max_p95_ratio: Decimal | None = None

    # Step 2 — p99/mean spread ratio.
    if mean_dec > 0 and p99_dec is not None:
        p99_mean_ratio = p99_dec / mean_dec
        if p99_mean_ratio > P99_MEAN_RATIO_THRESHOLD:
            return (
                LABEL_DEGRADED,
                (
                    f"p99_mean_ratio {p99_mean_ratio} > P99_MEAN_RATIO_THRESHOLD "
                    f"{P99_MEAN_RATIO_THRESHOLD} → {LABEL_DEGRADED}"
                ),
                {"p99_mean_ratio": p99_mean_ratio, "max_p95_ratio": None},
            )

    # Step 4 — max/p95 outlier tail ratio.
    if p95_dec is not None and p95_dec > 0 and max_dec is not None:
        max_p95_ratio = max_dec / p95_dec
        if max_p95_ratio > MAX_P95_RATIO_THRESHOLD:
            return (
                LABEL_DEGRADED,
                (
                    f"max_p95_ratio {max_p95_ratio} > MAX_P95_RATIO_THRESHOLD "
                    f"{MAX_P95_RATIO_THRESHOLD} → {LABEL_DEGRADED}"
                ),
                {"p99_mean_ratio": p99_mean_ratio, "max_p95_ratio": max_p95_ratio},
            )

    return (
        LABEL_STABLE,
        (
            f"p99_mean_ratio {p99_mean_ratio} <= {P99_MEAN_RATIO_THRESHOLD} and "
            f"max_p95_ratio {max_p95_ratio} <= {MAX_P95_RATIO_THRESHOLD} → {LABEL_STABLE}"
        ),
        {"p99_mean_ratio": p99_mean_ratio, "max_p95_ratio": max_p95_ratio},
    )


# ---------------------------------------------------------------------------
# Methodology trace builder
# ---------------------------------------------------------------------------


def _build_methodology_trace(
    endpoint_metrics: EndpointMetricsDTO,
    sr_determination: str,
    lat_determination: str,
    lat_intermediate: dict[str, Any],
) -> dict[str, Any]:
    """Build the combined methodology trace dict for the S3 artifact.

    Structure matches docs/architecture/phase_5_reliability_intelligence_technical_design.md
    Section 8.2 stability_analysis.methodology_trace schema.
    """
    latency_profile = endpoint_metrics.latency_profile or {}

    inputs: dict[str, Any] = {
        "execution_count": endpoint_metrics.execution_count,
        "success_rate": (
            str(endpoint_metrics.success_rate)
            if endpoint_metrics.success_rate is not None
            else None
        ),
        "latency_count": latency_profile.get("count", 0),
        "latency_p99_ms": latency_profile.get("p99"),
        "latency_mean_ms": latency_profile.get("mean"),
        "latency_max_ms": latency_profile.get("max"),
        "latency_p95_ms": latency_profile.get("p95"),
    }

    thresholds: dict[str, Any] = {
        "MIN_EXECUTION_COUNT": int(MIN_EXECUTION_COUNT),
        "STABLE_THRESHOLD": float(STABLE_THRESHOLD),
        "MIN_LATENCY_COUNT": int(MIN_LATENCY_COUNT),
        "P99_MEAN_RATIO_THRESHOLD": float(P99_MEAN_RATIO_THRESHOLD),
        "MAX_P95_RATIO_THRESHOLD": float(MAX_P95_RATIO_THRESHOLD),
    }

    label_determination = (
        f"{SUCCESS_RATE_STABILITY_ALGORITHM}: {sr_determination}. "
        f"{LATENCY_STABILITY_ALGORITHM}: {lat_determination}. "
        "Both labels reflect distributional characterization, not temporal assessment."
    )

    return {
        "algorithm": SUCCESS_RATE_STABILITY_ALGORITHM,
        "algorithm_version": INTELLIGENCE_VERSION,
        "inputs": inputs,
        "thresholds": thresholds,
        "intermediate_values": lat_intermediate,
        "label_determination": label_determination,
    }
