"""Timeout health endpoint Lambda handler."""

from __future__ import annotations

from typing import Any

from services.response_service import build_timeout_response
from services.timeout_service import resolve_timeout_delay_seconds
from utils import deterministic_delay
from utils.response_helpers import error_response, json_response, log_event, log_exception


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    endpoint = "timeout"
    try:
        decision = resolve_timeout_delay_seconds()
        deterministic_delay.sleep_seconds(decision.delay_seconds)
        body = build_timeout_response(decision.delay_seconds, decision.timeout_mode)
        log_event(
            "mock_target_api_response",
            endpoint=endpoint,
            status_code=200,
            delay_seconds=decision.delay_seconds,
            timeout_mode=decision.timeout_mode,
        )
        return json_response(200, body)
    except Exception:
        log_exception(endpoint)
        return error_response(endpoint)
