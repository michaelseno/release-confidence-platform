"""Pure deterministic aggregation engine for agg_v1."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from release_confidence_platform.aggregation.constants import NO_STATUS
from release_confidence_platform.aggregation.models import RawAggregationRecord
from release_confidence_platform.core.constants.engine import (
    ENDPOINT_FAILURE_TYPES,
    FAILURE_CONNECTION,
    FAILURE_PASS,
    FAILURE_TIMEOUT,
)


def build_aggregates(records: list[RawAggregationRecord]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda record: record.ref_identity)
    audit_counts = _request_counts(ordered)
    return {
        "audit": {
            "request_counts": audit_counts,
            "status_code_distribution": _status_distribution(ordered),
            "execution_duration_ms": _execution_duration_ms(ordered),
            "latency_summary_ms": latency_summary([r.duration_ms for r in ordered]),
            "endpoint_execution_counts": dict(
                sorted(Counter(r.endpoint_id for r in ordered).items())
            ),
            "failure_classification_counts": _classification_counts(ordered),
        },
        "endpoints": _endpoint_aggregates(ordered),
    }


def latency_summary(values: list[Any]) -> dict[str, Any]:
    numeric = sorted(
        Decimal(str(value))
        for value in values
        if isinstance(value, int | float | Decimal) and not isinstance(value, bool) and value >= 0
    )
    count = len(numeric)
    if count == 0:
        return {
            "count": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "p95": None,
            "p99": None,
        }
    mean = sum(numeric) / Decimal(count)
    median = (
        numeric[count // 2]
        if count % 2
        else (numeric[count // 2 - 1] + numeric[count // 2]) / Decimal(2)
    )
    return {
        "count": count,
        "min": _round(numeric[0]),
        "max": _round(numeric[-1]),
        "mean": _round(mean),
        "median": _round(median),
        "p95": _round(_nearest_rank(numeric, 95)),
        "p99": _round(_nearest_rank(numeric, 99)),
    }


def _request_counts(records: list[RawAggregationRecord]) -> dict[str, int]:
    return {
        "total": len(records),
        "successful": sum(1 for r in records if r.failure_type == FAILURE_PASS),
        "failed": sum(1 for r in records if r.failure_type != FAILURE_PASS),
        "skipped": 0,
        "timeout": sum(1 for r in records if r.failure_type == FAILURE_TIMEOUT),
        "network_failure": sum(1 for r in records if r.failure_type == FAILURE_CONNECTION),
    }


def _endpoint_aggregates(records: list[RawAggregationRecord]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[RawAggregationRecord]] = defaultdict(list)
    for record in records:
        grouped[record.endpoint_id].append(record)
    output = {}
    for endpoint_id, endpoint_records in sorted(grouped.items()):
        counts = _request_counts(endpoint_records)
        output[endpoint_id] = {
            "endpoint_id": endpoint_id,
            "execution_count": len(endpoint_records),
            "success_inputs": {
                "numerator": counts["successful"],
                "denominator": len(endpoint_records),
            },
            "latency_distribution_ms": {
                "summary": latency_summary([r.duration_ms for r in endpoint_records])
            },
            "timeout_count": counts["timeout"],
            "failure_classification_counts": _classification_counts(endpoint_records),
            "http_response_distribution": _status_distribution(endpoint_records),
        }
    return output


def _classification_counts(records: list[RawAggregationRecord]) -> dict[str, int]:
    return dict(sorted(Counter(record.failure_type for record in records).items()))


def _status_distribution(records: list[RawAggregationRecord]) -> dict[str, int]:
    distribution: Counter[str] = Counter()
    for record in records:
        distribution[
            str(record.status_code) if isinstance(record.status_code, int) else NO_STATUS
        ] += 1
    return dict(sorted(distribution.items()))


def _execution_duration_ms(records: list[RawAggregationRecord]) -> int:
    timestamps = [_parse_timestamp(record.result_timestamp) for record in records]
    valid = sorted(timestamp for timestamp in timestamps if timestamp is not None)
    if len(valid) < 2:
        return 0
    return int((valid[-1] - valid[0]).total_seconds() * 1000)


def normalize_failure_type(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        from release_confidence_platform.aggregation.constants import MISSING_CLASSIFICATION

        return MISSING_CLASSIFICATION
    value = value.strip()
    if value in ENDPOINT_FAILURE_TYPES:
        return value
    from release_confidence_platform.aggregation.constants import UNKNOWN_CLASSIFICATION

    return UNKNOWN_CLASSIFICATION


def _nearest_rank(values: list[Decimal], percentile: int) -> Decimal:
    rank = max(1, min(len(values), math.ceil(percentile / 100 * len(values))))
    return values[rank - 1]


def _round(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def _parse_timestamp(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
