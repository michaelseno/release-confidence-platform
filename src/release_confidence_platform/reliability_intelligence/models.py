"""DTO models for Phase 5 Reliability Intelligence (Phase 5.2).

These dataclasses carry typed derivation outputs from metrics.py and serve as inputs
to stability.py, burst.py, consistency.py, and scoring.py in later phases.

Frozen where practical. Dicts are used for passthrough fields (failure classifications,
latency profile) where full structural immutability is not required by the pipeline.
Note: hash() on EndpointMetricsDTO will raise TypeError because dict fields are unhashable.
These DTOs are never used as dict keys or set members.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class EndpointMetricsDTO:
    """Per-endpoint reliability metrics derived from Phase 4 EndpointAggregate fields.

    Produced by metrics.py. Consumed by stability.py, burst.py, consistency.py,
    scoring.py, and engine.py for S3 artifact assembly.

    Fields:
        endpoint_id: Sanitized opaque endpoint identifier (passthrough from Phase 4).
        execution_count: Total raw result records for this endpoint.
        success_rate: PASS / denominator rounded to 3 decimal places (ROUND_HALF_UP).
            None when is_insufficient_data is True.
        success_inputs: Dict with numerator and denominator retained for traceability.
        failure_classification_counts: Failure bucket → count passthrough from Phase 4.
            Not re-classified or re-mapped.
        latency_profile: Dict with count, min, max, mean, median, p95, p99 from
            EndpointAggregate.latency_distribution_ms. None when latency count is 0.
        timeout_count: TIMEOUT count for this endpoint (passthrough from Phase 4).
        is_insufficient_data: True when execution_count == 0 or denominator == 0.
            When True, success_rate is None and all analysis labels must be INSUFFICIENT_DATA.
    """

    endpoint_id: str
    execution_count: int
    success_rate: Decimal | None
    success_inputs: dict[str, int]
    failure_classification_counts: dict[str, int]
    latency_profile: dict[str, Any] | None
    timeout_count: int
    is_insufficient_data: bool


@dataclass(frozen=True)
class StabilityResult:
    """Per-endpoint stability analysis result from Phase 5.3.

    Produced by stability.py. Consumed by scoring.py and engine.py
    for S3 artifact assembly.

    Fields:
        success_rate_stability_label: STABLE | DEGRADED | INSUFFICIENT_DATA
        latency_stability_label: STABLE | DEGRADED | INSUFFICIENT_DATA
        methodology_trace: Combined trace dict for both success_rate_stability_v1 and
            latency_stability_v1 — inputs, thresholds, intermediate values, and label
            determination. Persisted in the S3 intelligence artifact.
    Note: hash() raises TypeError because methodology_trace is a dict.
    StabilityResult is never used as a dict key or set member.
    """

    success_rate_stability_label: str
    latency_stability_label: str
    methodology_trace: dict


@dataclass(frozen=True)
class BurstResult:
    """Per-endpoint burst analysis result from Phase 5.4.

    Produced by burst.py. Consumed by scoring.py and engine.py
    for S3 artifact assembly.

    Fields:
        failure_burst_label: NO_BURST_DETECTED | BURST_SUSPECTED | INSUFFICIENT_DATA
        latency_spike_label: NO_SPIKE_DETECTED | SPIKE_SUSPECTED | INSUFFICIENT_DATA
        methodology_trace: Combined trace dict for both failure_burst_v1 and
            latency_spike_v1 — inputs, thresholds, intermediate values, and label
            determination. Persisted in the S3 intelligence artifact.
    Note: hash() raises TypeError because methodology_trace is a dict.
    BurstResult is never used as a dict key or set member.
    """

    failure_burst_label: str
    latency_spike_label: str
    methodology_trace: dict


@dataclass(frozen=True)
class ConsistencyResult:
    """Per-endpoint consistency analysis result from Phase 5.5.

    Produced by consistency.py. Consumed by scoring.py and engine.py
    for S3 artifact assembly.

    Fields:
        consistency_label: CONSISTENT | INCONSISTENT | INSUFFICIENT_DATA
        methodology_trace: Trace dict for outcome_consistency_v1 — inputs, thresholds,
            intermediate Bernoulli variance, and label determination explanation.
            Persisted in the S3 intelligence artifact.
    Note: hash() raises TypeError because methodology_trace is a dict.
    ConsistencyResult is never used as a dict key or set member.
    """

    consistency_label: str
    methodology_trace: dict


@dataclass
class AuditMetricsSummaryDTO:
    """Audit-level reliability summary aggregated from Phase 4 AuditAggregate and per-endpoint metrics.

    Produced by metrics.py. Consumed by engine.py for S3 artifact assembly.

    Not frozen: contains a list of EndpointMetricsDTO which is mutable.

    Fields:
        total_execution_count: Total raw result records across all endpoints
            (AuditAggregate.request_counts.total).
        total_successful: Total PASS outcomes (AuditAggregate.request_counts.successful).
        total_failed: Total non-PASS outcomes (AuditAggregate.request_counts.failed).
        endpoint_count: Distinct endpoint count from AuditAggregate.endpoint_execution_counts.
        mean_success_rate: Arithmetic mean of per-endpoint success rates for endpoints
            with sufficient data. None when no endpoint has sufficient data.
            Rounded to 3 decimal places (ROUND_HALF_UP).
        endpoint_metrics: Per-endpoint EndpointMetricsDTO list, sorted by endpoint_id
            (canonical ordering for determinism).
    """

    total_execution_count: int
    total_successful: int
    total_failed: int
    endpoint_count: int
    mean_success_rate: Decimal | None
    endpoint_metrics: list[EndpointMetricsDTO] = field(default_factory=list)
