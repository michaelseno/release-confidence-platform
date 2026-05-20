"""Slow health endpoint Lambda handler."""

from __future__ import annotations

from typing import Any

from services.response_service import build_slow_response
from utils import deterministic_delay
from utils.response_helpers import (
    error_response,
    get_query_params,
    json_response,
    log_event,
    log_exception,
)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    endpoint = "slow"
    try:
        query_params = get_query_params(event)
        decision = deterministic_delay.resolve_slow_delay_ms(query_params)
        deterministic_delay.sleep_milliseconds(decision.delay_ms)
        body = build_slow_response(decision.delay_ms, decision.delay_source)
        log_event(
            "mock_target_api_response",
            endpoint=endpoint,
            status_code=200,
            delay_ms=decision.delay_ms,
            delay_source=decision.delay_source,
        )
        return json_response(200, body)
    except Exception:
        log_exception(endpoint)
        return error_response(endpoint)
