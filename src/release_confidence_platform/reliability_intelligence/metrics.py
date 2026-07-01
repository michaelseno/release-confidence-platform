"""Phase 5.2 — Per-endpoint reliability metric derivation from Phase 4 aggregate fields.

Pure computation module: no I/O, no storage access, no network calls.

All inputs are dicts matching the Phase 4 consumer contract field names as defined in
docs/architecture/phase_4a_phase5_consumer_contract.md.

Reads only the following Phase 4 consumer contract stable fields:

  EndpointAggregate:
    - endpoint_id
    - execution_count
    - success_inputs.numerator
    - success_inputs.denominator
    - failure_classification_counts
    - latency_distribution_ms (count, min, max, mean, median, p95, p99)
    - timeout_count

  AuditAggregate:
    - request_counts.total
    - request_counts.successful
    - request_counts.failed
    - endpoint_execution_counts (distinct key count)

DESIGN NOTE — latency_distribution_ms field structure:
  The consumer contract (Section 3.3) specifies latency_distribution_ms as having the same
  schema as latency_summary_ms (i.e., fields count/min/max/mean/median/p95/p99 at the top
  level). The Phase 4 aggregation engine stores latency_distribution_ms with a nested
  "summary" sub-key (latency_distribution_ms.summary.count). This module follows the consumer
  contract specification and expects fields at the top level. Phase 5 engine.py (implemented
  in Phase 5.7) must normalize the DynamoDB record structure before passing it to this module.

Does NOT implement:
  - Stability analysis (Phase 5.3)
  - Burst analysis (Phase 5.4)
  - Consistency analysis (Phase 5.5)
  - Scoring (Phase 5.6)
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from release_confidence_platform.reliability_intelligence.models import (
    AuditMetricsSummaryDTO,
    EndpointMetricsDTO,
)

_PRECISION = Decimal("0.001")


def compute_endpoint_metrics(endpoint_aggregate: dict[str, Any]) -> EndpointMetricsDTO:
    """Derive per-endpoint reliability metrics from a Phase 4 EndpointAggregate dict.

    All numeric conversions use Decimal(str(value)) to preserve precision, matching
    the Phase 4 engine arithmetic pattern in aggregation/engine.py.

    Args:
        endpoint_aggregate: Dict matching EndpointAggregate Phase 4 consumer contract fields.

    Returns:
        EndpointMetricsDTO with derived metrics. is_insufficient_data=True when
        execution_count == 0 or success_inputs.denominator == 0. In those cases
        success_rate is None and no ZeroDivisionError is raised.
    """
    endpoint_id: str = endpoint_aggregate["endpoint_id"]
    execution_count: int = endpoint_aggregate.get("execution_count", 0)
    timeout_count: int = endpoint_aggregate.get("timeout_count", 0)

    # Success inputs — passthrough numerator and denominator for traceability.
    raw_success_inputs = endpoint_aggregate.get("success_inputs") or {}
    numerator: int = raw_success_inputs.get("numerator", 0)
    denominator: int = raw_success_inputs.get("denominator", 0)

    # Failure classification counts — passthrough; no re-classification.
    failure_classification_counts: dict[str, int] = dict(
        endpoint_aggregate.get("failure_classification_counts") or {}
    )

    # Latency profile — passthrough from latency_distribution_ms.
    # Consumer contract: fields at top level of latency_distribution_ms.
    latency_dist = endpoint_aggregate.get("latency_distribution_ms") or {}
    latency_count: int = latency_dist.get("count", 0)

    # Insufficient data guard: denominator == 0 or no executions.
    is_insufficient_data: bool = execution_count == 0 or denominator == 0

    # Success rate computation — Decimal arithmetic, ROUND_HALF_UP, 3 decimal places.
    if is_insufficient_data:
        success_rate: Decimal | None = None
    else:
        success_rate = (
            Decimal(str(numerator)) / Decimal(str(denominator))
        ).quantize(_PRECISION, rounding=ROUND_HALF_UP)

    # Latency profile — None when count == 0 (agg_v1 semantic: null values when count is 0).
    if latency_count > 0:
        latency_profile: dict[str, Any] | None = {
            "count": latency_count,
            "min": latency_dist.get("min"),
            "max": latency_dist.get("max"),
            "mean": latency_dist.get("mean"),
            "median": latency_dist.get("median"),
            "p95": latency_dist.get("p95"),
            "p99": latency_dist.get("p99"),
        }
    else:
        latency_profile = None

    return EndpointMetricsDTO(
        endpoint_id=endpoint_id,
        execution_count=execution_count,
        success_rate=success_rate,
        success_inputs={"numerator": numerator, "denominator": denominator},
        failure_classification_counts=failure_classification_counts,
        latency_profile=latency_profile,
        timeout_count=timeout_count,
        is_insufficient_data=is_insufficient_data,
    )


def compute_audit_metrics_summary(
    audit_aggregate: dict[str, Any],
    endpoint_metrics: list[EndpointMetricsDTO],
) -> AuditMetricsSummaryDTO:
    """Derive audit-level reliability summary from Phase 4 AuditAggregate and per-endpoint metrics.

    The mean_success_rate is the arithmetic mean of per-endpoint success rates for endpoints
    that are not marked is_insufficient_data. None when no endpoint has sufficient data.

    Args:
        audit_aggregate: Dict matching AuditAggregate Phase 4 consumer contract fields.
        endpoint_metrics: Per-endpoint metrics list produced by compute_endpoint_metrics().

    Returns:
        AuditMetricsSummaryDTO with audit-level counts and mean success rate.
    """
    request_counts = audit_aggregate.get("request_counts") or {}
    total_execution_count: int = request_counts.get("total", 0)
    total_successful: int = request_counts.get("successful", 0)
    total_failed: int = request_counts.get("failed", 0)

    # Endpoint count — distinct key count in endpoint_execution_counts (per consumer contract).
    endpoint_execution_counts = audit_aggregate.get("endpoint_execution_counts") or {}
    endpoint_count: int = len(endpoint_execution_counts)

    # Mean success rate — arithmetic mean of per-endpoint success rates for sufficient endpoints.
    sufficient_rates = [
        ep.success_rate
        for ep in endpoint_metrics
        if not ep.is_insufficient_data and ep.success_rate is not None
    ]

    if sufficient_rates:
        rate_sum = sum(sufficient_rates, Decimal(0))
        mean_success_rate: Decimal | None = (
            rate_sum / Decimal(str(len(sufficient_rates)))
        ).quantize(_PRECISION, rounding=ROUND_HALF_UP)
    else:
        mean_success_rate = None

    return AuditMetricsSummaryDTO(
        total_execution_count=total_execution_count,
        total_successful=total_successful,
        total_failed=total_failed,
        endpoint_count=endpoint_count,
        mean_success_rate=mean_success_rate,
        endpoint_metrics=list(endpoint_metrics),
    )
