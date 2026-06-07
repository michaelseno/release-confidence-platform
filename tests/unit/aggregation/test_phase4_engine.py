from release_confidence_platform.aggregation.engine import build_aggregates, latency_summary
from release_confidence_platform.aggregation.models import RawAggregationRecord


def rec(
    index, endpoint="ep1", failure="PASS", status=200, duration=1, timestamp="2026-06-07T00:00:00Z"
):
    return RawAggregationRecord(
        "v1",
        "run_12345678",
        "raw-results/client/audit/run/results.json",
        None,
        index,
        endpoint,
        timestamp,
        duration,
        status,
        failure,
    )


def test_latency_summary_uses_half_up_and_nearest_rank():
    summary = latency_summary([0, 1, 2, 3, 4, 5, 100, None, -1, "bad"])
    assert summary == {
        "count": 7,
        "min": 0.0,
        "max": 100.0,
        "mean": 16.429,
        "median": 3.0,
        "p95": 100.0,
        "p99": 100.0,
    }


def test_agg_v1_counts_payload_validation_as_failed_and_skipped_zero():
    aggregates = build_aggregates(
        [
            rec(0, failure="PASS"),
            rec(1, failure="PAYLOAD_VALIDATION_ERROR", status=None, duration=None),
            rec(2, failure="TIMEOUT", status=None, duration=-1),
            rec(3, endpoint="ep2", failure="CONNECTION_ERROR", status=None),
        ]
    )
    audit = aggregates["audit"]
    assert audit["request_counts"] == {
        "total": 4,
        "successful": 1,
        "failed": 3,
        "skipped": 0,
        "timeout": 1,
        "network_failure": 1,
    }
    assert audit["status_code_distribution"] == {"200": 1, "NO_STATUS": 3}
    assert audit["failure_classification_counts"]["PAYLOAD_VALIDATION_ERROR"] == 1
    assert aggregates["endpoints"]["ep1"]["success_inputs"] == {"numerator": 1, "denominator": 3}
