"""Fast health endpoint Lambda handler."""

from __future__ import annotations

from typing import Any

from services.response_service import build_fast_response
from utils.response_helpers import error_response, json_response, log_event, log_exception


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    endpoint = "fast"
    try:
        body = build_fast_response()
        log_event("mock_target_api_response", endpoint=endpoint, status_code=200, status="healthy")
        return json_response(200, body)
    except Exception:
        log_exception(endpoint)
        return error_response(endpoint)
