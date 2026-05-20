"""Flaky health endpoint Lambda handler."""

from __future__ import annotations

from typing import Any

from services.flaky_service import evaluate_flaky_status, resolve_seed
from services.response_service import build_flaky_response
from utils.response_helpers import (
    error_response,
    get_headers,
    get_query_params,
    json_response,
    log_event,
    log_exception,
)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    endpoint = "flaky"
    try:
        seed, seed_source = resolve_seed(get_query_params(event), get_headers(event))
        decision = evaluate_flaky_status(seed, seed_source)
        body = build_flaky_response(decision.status, decision.seed_source, decision.hash_mod)
        log_event(
            "mock_target_api_response",
            endpoint=endpoint,
            status_code=decision.http_status,
            status=decision.status,
            seed_source=decision.seed_source,
            hash_mod=decision.hash_mod,
        )
        return json_response(decision.http_status, body)
    except Exception:
        log_exception(endpoint)
        return error_response(endpoint)
