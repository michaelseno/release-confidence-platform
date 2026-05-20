"""API Gateway HTTP API response and event helpers."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any

LOGGER = logging.getLogger("mock-target-api")
if not LOGGER.handlers:
    logging.basicConfig(level=logging.INFO)


def get_query_params(event: Mapping[str, Any] | None) -> dict[str, str | None]:
    params = (event or {}).get("queryStringParameters") or {}
    return dict(params) if isinstance(params, Mapping) else {}


def get_headers(event: Mapping[str, Any] | None) -> dict[str, str]:
    headers = (event or {}).get("headers") or {}
    if not isinstance(headers, Mapping):
        return {}
    return {str(key).lower(): str(value) for key, value in headers.items() if value is not None}


def json_response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body, sort_keys=True, separators=(",", ":")),
    }


def error_response(endpoint: str) -> dict[str, Any]:
    return json_response(
        500,
        {
            "service": "mock-target-api",
            "endpoint": endpoint,
            "status": "error",
            "error": "internal_error",
        },
    )


def log_event(message: str, **fields: Any) -> None:
    """Emit a compact structured log without raw event/header/seed data."""
    safe_fields = {key: value for key, value in fields.items() if value is not None}
    LOGGER.info(message, extra={"mock_target_api": safe_fields})


def log_exception(endpoint: str) -> None:
    LOGGER.exception(
        "mock_target_api_unexpected_error",
        extra={"mock_target_api": {"endpoint": endpoint}},
    )
