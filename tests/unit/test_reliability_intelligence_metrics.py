"""Unit tests for Phase 5.2 — Reliability Metrics Core.

Tests the pure computation functions in metrics.py using fixture dicts that match the
Phase 4 consumer contract field specification
(docs/architecture/phase_4a_phase5_consumer_contract.md).

Fixture format for latency_distribution_ms follows the consumer contract (Section 3.3):
fields at the top level of latency_distribution_ms (count, min, max, mean, median, p95, p99).
This is the stable field set that Phase 5 may consume, regardless of how Phase 4 stores
the fields internally.
"""

from decimal import Decimal

import pytest

from release_confidence_platform.reliability_intelligence.metrics import (
    compute_audit_metrics_summary,
    compute_endpoint_metrics,
)
from release_confidence_platform.reliability_intelligence.models import (
    AuditMetricsSummaryDTO,
    EndpointMetricsDTO,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _endpoint_aggregate(
    endpoint_id="ep_1",
    execution_count=10,
    numerator=9,
    denominator=10,
    timeout_count=1,
    failure_classification_counts=None,
    latency_distribution_ms=None,
):
    """Build a minimal EndpointAggregate dict matching the Phase 4 consumer contract."""
    return {
        "endpoint_id": endpoint_id,
        "execution_count": execution_count,
        "success_inputs": {
            "numerator": numerator,
            "denominator": denominator,
        },
        "timeout_count": timeout_count,
        "failure_classification_counts": failure_classification_counts or {"PASS": 9, "TIMEOUT": 1},
        "latency_distribution_ms": latency_distribution_ms or {
            "count": 10,
            "min": 50.0,
            "max": 500.0,
            "mean": 100.0,
            "median": 90.0,
            "p95": 400.0,
            "p99": 480.0,
        },
    }


def _audit_aggregate(
    total=20,
    successful=18,
    failed=2,
    endpoint_execution_counts=None,
):
    """Build a minimal AuditAggregate dict matching the Phase 4 consumer contract."""
    return {
        "request_counts": {
            "total": total,
            "successful": successful,
            "failed": failed,
            "skipped": 0,
            "timeout": 1,
            "network_failure": 0,
        },
        "endpoint_execution_counts": endpoint_execution_counts or {"ep_1": 10, "ep_2": 10},
    }


# ---------------------------------------------------------------------------
# Success rate computation tests
# ---------------------------------------------------------------------------


def test_success_rate_correct_computation():
    """Success rate is numerator / denominator, rounded to 3 decimal places."""
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(numerator=9, denominator=10, execution_count=10)
    )
    assert ep.success_rate == Decimal("0.900")
    assert not ep.is_insufficient_data


def test_success_rate_two_thirds_rounds_half_up():
    """2/3 must round to 0.667 (ROUND_HALF_UP), not 0.666 (truncation or floor)."""
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(numerator=2, denominator=3, execution_count=3)
    )
    assert ep.success_rate == Decimal("0.667")


def test_success_rate_one_third_rounds_down():
    """1/3 rounds to 0.333 with ROUND_HALF_UP (0.3333... → nearest 3dp)."""
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(numerator=1, denominator=3, execution_count=3)
    )
    assert ep.success_rate == Decimal("0.333")


def test_success_rate_three_decimal_places():
    """Success rate must be exactly 3 decimal places."""
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(numerator=7, denominator=10, execution_count=10)
    )
    assert ep.success_rate == Decimal("0.700")
    # Confirm the exponent indicates 3 decimal places
    assert ep.success_rate.as_tuple().exponent == -3


# ---------------------------------------------------------------------------
# Zero execution count tests
# ---------------------------------------------------------------------------


def test_zero_execution_count_returns_insufficient_data():
    """An endpoint with execution_count=0 must have is_insufficient_data=True."""
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(execution_count=0, numerator=0, denominator=0)
    )
    assert ep.is_insufficient_data is True
    assert ep.success_rate is None
    assert ep.execution_count == 0


def test_zero_execution_count_does_not_raise():
    """compute_endpoint_metrics must not raise ZeroDivisionError for execution_count=0."""
    try:
        compute_endpoint_metrics(
            _endpoint_aggregate(execution_count=0, numerator=0, denominator=0)
        )
    except ZeroDivisionError:
        pytest.fail("ZeroDivisionError raised for execution_count=0")


# ---------------------------------------------------------------------------
# Zero denominator tests
# ---------------------------------------------------------------------------


def test_zero_denominator_returns_insufficient_data():
    """An endpoint with denominator=0 must have is_insufficient_data=True."""
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(execution_count=5, numerator=0, denominator=0)
    )
    assert ep.is_insufficient_data is True
    assert ep.success_rate is None


def test_zero_denominator_does_not_raise():
    """compute_endpoint_metrics must not raise ZeroDivisionError for denominator=0."""
    try:
        compute_endpoint_metrics(
            _endpoint_aggregate(execution_count=5, numerator=0, denominator=0)
        )
    except ZeroDivisionError:
        pytest.fail("ZeroDivisionError raised for denominator=0")


# ---------------------------------------------------------------------------
# Edge case: zero failures (100% pass)
# ---------------------------------------------------------------------------


def test_zero_failures_gives_full_success_rate():
    """When all executions pass, success_rate must be exactly Decimal('1.000')."""
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(
            execution_count=10,
            numerator=10,
            denominator=10,
            failure_classification_counts={"PASS": 10},
        )
    )
    assert ep.success_rate == Decimal("1.000")
    assert not ep.is_insufficient_data


# ---------------------------------------------------------------------------
# Edge case: 100% failure
# ---------------------------------------------------------------------------


def test_all_failures_gives_zero_success_rate():
    """When no executions pass, success_rate must be exactly Decimal('0.000')."""
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(
            execution_count=10,
            numerator=0,
            denominator=10,
            failure_classification_counts={"TIMEOUT": 10},
        )
    )
    assert ep.success_rate == Decimal("0.000")
    assert not ep.is_insufficient_data


# ---------------------------------------------------------------------------
# Failure classification passthrough tests
# ---------------------------------------------------------------------------


def test_failure_classification_passthrough_unchanged():
    """failure_classification_counts must be passed through without modification."""
    classification = {
        "PASS": 7,
        "TIMEOUT": 2,
        "CONNECTION_ERROR": 1,
    }
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(
            execution_count=10,
            numerator=7,
            denominator=10,
            failure_classification_counts=classification,
        )
    )
    assert ep.failure_classification_counts == classification


def test_failure_classification_passthrough_preserves_all_keys():
    """All keys in failure_classification_counts are preserved, including unusual labels."""
    classification = {
        "PASS": 5,
        "ASSERTION_FAILURE": 3,
        "PAYLOAD_VALIDATION_ERROR": 1,
        "MISSING_FAILURE_CLASSIFICATION": 1,
    }
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(
            execution_count=10,
            numerator=5,
            denominator=10,
            failure_classification_counts=classification,
        )
    )
    assert ep.failure_classification_counts == classification


# ---------------------------------------------------------------------------
# Latency profile passthrough tests
# ---------------------------------------------------------------------------


def test_latency_profile_passthrough_all_six_fields():
    """When latency count > 0, all 6 latency measurement fields must be present and unchanged."""
    latency = {
        "count": 10,
        "min": 45.5,
        "max": 620.0,
        "mean": 110.333,
        "median": 95.0,
        "p95": 500.0,
        "p99": 600.0,
    }
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(latency_distribution_ms=latency)
    )
    assert ep.latency_profile is not None
    assert ep.latency_profile["min"] == 45.5
    assert ep.latency_profile["max"] == 620.0
    assert ep.latency_profile["mean"] == 110.333
    assert ep.latency_profile["median"] == 95.0
    assert ep.latency_profile["p95"] == 500.0
    assert ep.latency_profile["p99"] == 600.0


def test_latency_profile_count_carried_through():
    """latency_profile must include the count field from latency_distribution_ms."""
    latency = {
        "count": 10,
        "min": 50.0,
        "max": 500.0,
        "mean": 100.0,
        "median": 90.0,
        "p95": 400.0,
        "p99": 480.0,
    }
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(latency_distribution_ms=latency)
    )
    assert ep.latency_profile is not None
    assert ep.latency_profile["count"] == 10


def test_null_latency_count_gives_none_profile():
    """When latency_distribution_ms.count is 0, latency_profile must be None."""
    latency = {
        "count": 0,
        "min": None,
        "max": None,
        "mean": None,
        "median": None,
        "p95": None,
        "p99": None,
    }
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(latency_distribution_ms=latency)
    )
    assert ep.latency_profile is None


def test_missing_latency_distribution_ms_gives_none_profile():
    """When latency_distribution_ms is absent from the record, latency_profile must be None."""
    aggregate = {
        "endpoint_id": "ep_1",
        "execution_count": 10,
        "success_inputs": {"numerator": 9, "denominator": 10},
        "timeout_count": 1,
        "failure_classification_counts": {"PASS": 9, "TIMEOUT": 1},
        # latency_distribution_ms intentionally absent
    }
    ep = compute_endpoint_metrics(aggregate)
    assert ep.latency_profile is None


def test_none_latency_distribution_ms_handled_without_error():
    """When latency_distribution_ms is None, must handle without raising AttributeError."""
    aggregate = {
        "endpoint_id": "ep_1",
        "execution_count": 10,
        "success_inputs": {"numerator": 9, "denominator": 10},
        "timeout_count": 0,
        "failure_classification_counts": {"PASS": 9},
        "latency_distribution_ms": None,
    }
    try:
        ep = compute_endpoint_metrics(aggregate)
        assert ep.latency_profile is None
    except (AttributeError, TypeError) as exc:
        pytest.fail(f"Unexpected error for None latency_distribution_ms: {exc}")


# ---------------------------------------------------------------------------
# AuditMetricsSummaryDTO aggregation tests
# ---------------------------------------------------------------------------


def test_audit_summary_aggregation_across_endpoints():
    """AuditMetricsSummaryDTO correctly aggregates counts from AuditAggregate."""
    audit_agg = _audit_aggregate(
        total=20, successful=18, failed=2,
        endpoint_execution_counts={"ep_1": 10, "ep_2": 10},
    )
    ep_metrics = [
        compute_endpoint_metrics(_endpoint_aggregate("ep_1", numerator=9, denominator=10)),
        compute_endpoint_metrics(_endpoint_aggregate("ep_2", numerator=10, denominator=10)),
    ]
    summary = compute_audit_metrics_summary(audit_agg, ep_metrics)

    assert isinstance(summary, AuditMetricsSummaryDTO)
    assert summary.total_execution_count == 20
    assert summary.total_successful == 18
    assert summary.total_failed == 2
    assert summary.endpoint_count == 2


def test_audit_summary_endpoint_count_from_execution_counts_keys():
    """endpoint_count is the distinct key count in endpoint_execution_counts."""
    audit_agg = _audit_aggregate(
        endpoint_execution_counts={"ep_a": 5, "ep_b": 5, "ep_c": 5}
    )
    ep_metrics = [
        compute_endpoint_metrics(_endpoint_aggregate("ep_a")),
        compute_endpoint_metrics(_endpoint_aggregate("ep_b")),
        compute_endpoint_metrics(_endpoint_aggregate("ep_c")),
    ]
    summary = compute_audit_metrics_summary(audit_agg, ep_metrics)
    assert summary.endpoint_count == 3


def test_audit_summary_mean_success_rate_across_endpoints():
    """mean_success_rate is the arithmetic mean of per-endpoint success rates."""
    # ep_1: 9/10 = 0.900, ep_2: 10/10 = 1.000 → mean = 0.950
    audit_agg = _audit_aggregate(
        endpoint_execution_counts={"ep_1": 10, "ep_2": 10},
    )
    ep_metrics = [
        compute_endpoint_metrics(_endpoint_aggregate("ep_1", numerator=9, denominator=10)),
        compute_endpoint_metrics(_endpoint_aggregate("ep_2", numerator=10, denominator=10)),
    ]
    summary = compute_audit_metrics_summary(audit_agg, ep_metrics)
    assert summary.mean_success_rate == Decimal("0.950")


def test_audit_summary_mean_success_rate_excludes_insufficient_data_endpoints():
    """Endpoints with is_insufficient_data=True are excluded from mean_success_rate calculation."""
    audit_agg = _audit_aggregate(
        endpoint_execution_counts={"ep_1": 10, "ep_2": 0},
    )
    ep_metrics = [
        compute_endpoint_metrics(_endpoint_aggregate("ep_1", numerator=8, denominator=10)),
        compute_endpoint_metrics(
            _endpoint_aggregate("ep_2", execution_count=0, numerator=0, denominator=0)
        ),
    ]
    summary = compute_audit_metrics_summary(audit_agg, ep_metrics)
    # Only ep_1 is included: 8/10 = 0.800
    assert summary.mean_success_rate == Decimal("0.800")


def test_audit_summary_mean_success_rate_none_when_all_insufficient():
    """mean_success_rate is None when all endpoints have is_insufficient_data=True."""
    audit_agg = _audit_aggregate(
        total=0, successful=0, failed=0,
        endpoint_execution_counts={"ep_1": 0},
    )
    ep_metrics = [
        compute_endpoint_metrics(
            _endpoint_aggregate("ep_1", execution_count=0, numerator=0, denominator=0)
        )
    ]
    summary = compute_audit_metrics_summary(audit_agg, ep_metrics)
    assert summary.mean_success_rate is None


def test_audit_summary_carries_endpoint_metrics_list():
    """AuditMetricsSummaryDTO carries the endpoint_metrics list unchanged."""
    audit_agg = _audit_aggregate(endpoint_execution_counts={"ep_1": 10})
    ep_metric = compute_endpoint_metrics(_endpoint_aggregate("ep_1"))
    summary = compute_audit_metrics_summary(audit_agg, [ep_metric])

    assert len(summary.endpoint_metrics) == 1
    assert summary.endpoint_metrics[0].endpoint_id == "ep_1"


# ---------------------------------------------------------------------------
# Decimal precision validation
# ---------------------------------------------------------------------------


def test_success_rate_has_exactly_three_decimal_places():
    """success_rate Decimal must have exactly 3 decimal places (exponent == -3)."""
    cases = [
        (1, 1),    # 1.000
        (0, 1),    # 0.000
        (1, 3),    # 0.333
        (2, 3),    # 0.667
        (19, 20),  # 0.950
        (7, 8),    # 0.875
    ]
    for numerator, denominator in cases:
        ep = compute_endpoint_metrics(
            _endpoint_aggregate(
                execution_count=denominator,
                numerator=numerator,
                denominator=denominator,
            )
        )
        assert ep.success_rate is not None, f"Unexpected None for {numerator}/{denominator}"
        assert ep.success_rate.as_tuple().exponent == -3, (
            f"Expected exponent -3 for {numerator}/{denominator}, "
            f"got {ep.success_rate.as_tuple().exponent} (value={ep.success_rate})"
        )


def test_mean_success_rate_has_exactly_three_decimal_places():
    """mean_success_rate must be rounded to exactly 3 decimal places."""
    # Three endpoints: 1/3, 1/3, 1/3 → each 0.333, mean = 0.333 (uniform)
    audit_agg = _audit_aggregate(
        endpoint_execution_counts={"ep_1": 3, "ep_2": 3, "ep_3": 3}
    )
    ep_metrics = [
        compute_endpoint_metrics(_endpoint_aggregate("ep_1", execution_count=3, numerator=1, denominator=3)),  # noqa: E501
        compute_endpoint_metrics(_endpoint_aggregate("ep_2", execution_count=3, numerator=1, denominator=3)),  # noqa: E501
        compute_endpoint_metrics(_endpoint_aggregate("ep_3", execution_count=3, numerator=1, denominator=3)),  # noqa: E501
    ]
    summary = compute_audit_metrics_summary(audit_agg, ep_metrics)
    assert summary.mean_success_rate is not None
    assert summary.mean_success_rate.as_tuple().exponent == -3


# ---------------------------------------------------------------------------
# DTO type validation
# ---------------------------------------------------------------------------


def test_compute_endpoint_metrics_returns_dto():
    """compute_endpoint_metrics must return an EndpointMetricsDTO instance."""
    result = compute_endpoint_metrics(_endpoint_aggregate())
    assert isinstance(result, EndpointMetricsDTO)


def test_compute_audit_metrics_summary_returns_dto():
    """compute_audit_metrics_summary must return an AuditMetricsSummaryDTO instance."""
    result = compute_audit_metrics_summary(
        _audit_aggregate(), [compute_endpoint_metrics(_endpoint_aggregate())]
    )
    assert isinstance(result, AuditMetricsSummaryDTO)


def test_endpoint_metrics_dto_success_inputs_preserved():
    """success_inputs dict must carry original numerator and denominator."""
    ep = compute_endpoint_metrics(
        _endpoint_aggregate(numerator=7, denominator=10, execution_count=10)
    )
    assert ep.success_inputs == {"numerator": 7, "denominator": 10}


def test_endpoint_metrics_dto_is_frozen():
    """EndpointMetricsDTO must be frozen (attribute reassignment raises FrozenInstanceError)."""
    ep = compute_endpoint_metrics(_endpoint_aggregate())
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        ep.endpoint_id = "mutated"  # type: ignore[misc]
