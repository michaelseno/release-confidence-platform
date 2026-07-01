"""Phase 5.4 — Distributional burst and latency spike characterization.

Pure computation module: no I/O, no storage access, no network calls.

Implements two distributional proxy algorithms over full-window agg_v1 aggregate fields:

  failure_burst_v1:
    Uses aggregate timeout proportion as a proxy for concentrated failure events.
    A timeout proportion > 20% is consistent with burst-like service unavailability.

  latency_spike_v1:
    Uses max/p99 latency ratio as a proxy for isolated spike events.
    A max/p99 ratio > 3.0 indicates extreme outlier presence.

DESIGN NOTE — agg_v1 limitations:
  agg_v1 provides full-window summary statistics only. Burst timing attribution —
  when within the observation window a burst occurred, how many distinct events occurred,
  or whether failures were genuinely clustered vs uniformly distributed — cannot be
  determined from agg_v1 inputs. This is an explicit documented boundary of intel_v1.

All thresholds are imported from constants.py. No magic numbers in this module.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

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
from release_confidence_platform.reliability_intelligence.models import (
    BurstResult,
    EndpointMetricsDTO,
)


def compute_burst_analysis(endpoint_metrics: EndpointMetricsDTO) -> BurstResult:
    """Run failure_burst_v1 and latency_spike_v1 for one endpoint.

    Both algorithms use distributional proxies from full-window agg_v1 aggregate fields.
    Neither makes temporal claims about when within the window any burst or spike occurred.

    Args:
        endpoint_metrics: EndpointMetricsDTO produced by metrics.py for this endpoint.

    Returns:
        BurstResult with both burst labels and a combined methodology trace.
    """
    fb_label, fb_determination, fb_intermediate = _failure_burst_v1(endpoint_metrics)
    ls_label, ls_determination, ls_intermediate = _latency_spike_v1(endpoint_metrics)

    methodology_trace = _build_methodology_trace(
        endpoint_metrics=endpoint_metrics,
        fb_determination=fb_determination,
        ls_determination=ls_determination,
        fb_intermediate=fb_intermediate,
        ls_intermediate=ls_intermediate,
    )

    return BurstResult(
        failure_burst_label=fb_label,
        latency_spike_label=ls_label,
        methodology_trace=methodology_trace,
    )


# ---------------------------------------------------------------------------
# Algorithm: failure_burst_v1
# ---------------------------------------------------------------------------


def _failure_burst_v1(
    endpoint_metrics: EndpointMetricsDTO,
) -> tuple[str, str, dict[str, Any]]:
    """failure_burst_v1 — Section 11.1 of Phase 5 technical design.

    Returns (label, determination_text, intermediate_values).
    intermediate_values key: timeout_proportion (Decimal or None).
    """
    execution_count = endpoint_metrics.execution_count
    timeout_count = endpoint_metrics.timeout_count

    if execution_count < MIN_EXECUTION_COUNT:
        return (
            LABEL_INSUFFICIENT_DATA,
            (
                f"execution_count {execution_count} < MIN_EXECUTION_COUNT "
                f"{MIN_EXECUTION_COUNT} → {LABEL_INSUFFICIENT_DATA}"
            ),
            {"timeout_proportion": None},
        )

    timeout_proportion = Decimal(str(timeout_count)) / Decimal(str(execution_count))

    if timeout_proportion > TIMEOUT_BURST_THRESHOLD:
        return (
            LABEL_BURST_SUSPECTED,
            (
                f"timeout_proportion {timeout_proportion} > TIMEOUT_BURST_THRESHOLD "
                f"{TIMEOUT_BURST_THRESHOLD} → {LABEL_BURST_SUSPECTED}"
            ),
            {"timeout_proportion": timeout_proportion},
        )

    return (
        LABEL_NO_BURST_DETECTED,
        (
            f"timeout_proportion {timeout_proportion} <= TIMEOUT_BURST_THRESHOLD "
            f"{TIMEOUT_BURST_THRESHOLD} → {LABEL_NO_BURST_DETECTED}"
        ),
        {"timeout_proportion": timeout_proportion},
    )


# ---------------------------------------------------------------------------
# Algorithm: latency_spike_v1
# ---------------------------------------------------------------------------


def _latency_spike_v1(
    endpoint_metrics: EndpointMetricsDTO,
) -> tuple[str, str, dict[str, Any]]:
    """latency_spike_v1 — Section 11.2 of Phase 5 technical design.

    Returns (label, determination_text, intermediate_values).
    intermediate_values key: max_p99_ratio (Decimal or None).
    """
    latency_profile = endpoint_metrics.latency_profile or {}
    latency_count: int = latency_profile.get("count", 0)
    p99_raw = latency_profile.get("p99")
    max_raw = latency_profile.get("max")

    if latency_count < MIN_LATENCY_COUNT or p99_raw is None or max_raw is None:
        return (
            LABEL_INSUFFICIENT_DATA,
            (
                f"latency_count {latency_count} < MIN_LATENCY_COUNT {MIN_LATENCY_COUNT} "
                f"or latency_p99_ms is null → {LABEL_INSUFFICIENT_DATA}"
            ),
            {"max_p99_ratio": None},
        )

    p99_dec = Decimal(str(p99_raw))

    if p99_dec == 0:
        return (
            LABEL_INSUFFICIENT_DATA,
            f"latency_p99_ms = 0 (division by zero guard) → {LABEL_INSUFFICIENT_DATA}",
            {"max_p99_ratio": None},
        )

    max_dec = Decimal(str(max_raw))
    max_p99_ratio = max_dec / p99_dec

    if max_p99_ratio > MAX_P99_RATIO_THRESHOLD:
        return (
            LABEL_SPIKE_SUSPECTED,
            (
                f"max_p99_ratio {max_p99_ratio} > MAX_P99_RATIO_THRESHOLD "
                f"{MAX_P99_RATIO_THRESHOLD} → {LABEL_SPIKE_SUSPECTED}"
            ),
            {"max_p99_ratio": max_p99_ratio},
        )

    return (
        LABEL_NO_SPIKE_DETECTED,
        (
            f"max_p99_ratio {max_p99_ratio} <= MAX_P99_RATIO_THRESHOLD "
            f"{MAX_P99_RATIO_THRESHOLD} → {LABEL_NO_SPIKE_DETECTED}"
        ),
        {"max_p99_ratio": max_p99_ratio},
    )


# ---------------------------------------------------------------------------
# Methodology trace builder
# ---------------------------------------------------------------------------


def _build_methodology_trace(
    endpoint_metrics: EndpointMetricsDTO,
    fb_determination: str,
    ls_determination: str,
    fb_intermediate: dict[str, Any],
    ls_intermediate: dict[str, Any],
) -> dict[str, Any]:
    """Build the combined methodology trace dict for the S3 artifact.

    Structure matches docs/architecture/phase_5_reliability_intelligence_technical_design.md
    Section 8.2 burst_analysis.methodology_trace schema.
    """
    latency_profile = endpoint_metrics.latency_profile or {}

    inputs: dict[str, Any] = {
        "execution_count": endpoint_metrics.execution_count,
        "timeout_count": endpoint_metrics.timeout_count,
        "latency_count": latency_profile.get("count", 0),
        "latency_p99_ms": latency_profile.get("p99"),
        "latency_max_ms": latency_profile.get("max"),
    }

    thresholds: dict[str, Any] = {
        "MIN_EXECUTION_COUNT": int(MIN_EXECUTION_COUNT),
        "TIMEOUT_BURST_THRESHOLD": float(TIMEOUT_BURST_THRESHOLD),
        "MIN_LATENCY_COUNT": int(MIN_LATENCY_COUNT),
        "MAX_P99_RATIO_THRESHOLD": float(MAX_P99_RATIO_THRESHOLD),
    }

    intermediate_values: dict[str, Any] = {
        "timeout_proportion": fb_intermediate.get("timeout_proportion"),
        "max_p99_ratio": ls_intermediate.get("max_p99_ratio"),
    }

    label_determination = (
        f"{FAILURE_BURST_ALGORITHM}: {fb_determination}. "
        f"{LATENCY_SPIKE_ALGORITHM}: {ls_determination}. "
        "burst timing attribution cannot be determined from agg_v1 inputs."
    )

    return {
        "algorithm": FAILURE_BURST_ALGORITHM,
        "algorithm_version": INTELLIGENCE_VERSION,
        "inputs": inputs,
        "thresholds": thresholds,
        "intermediate_values": intermediate_values,
        "label_determination": label_determination,
    }
