"""Inconsistent health endpoint Lambda handler."""

from __future__ import annotations

from typing import Any

from services.inconsistency_service import resolve_variant
from services.response_service import build_inconsistent_response
from utils.response_helpers import (
    error_response,
    get_headers,
    get_query_params,
    json_response,
    log_event,
    log_exception,
)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    endpoint = "inconsistent"
    try:
        decision = resolve_variant(get_query_params(event), get_headers(event))
        body = build_inconsistent_response(decision.variant)
        log_event(
            "mock_target_api_response",
            endpoint=endpoint,
            status_code=200,
            variant=decision.variant,
            variant_source=decision.variant_source,
        )
        return json_response(200, body)
    except Exception:
        log_exception(endpoint)
        return error_response(endpoint)
