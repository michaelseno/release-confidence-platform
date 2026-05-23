"""Phase 2 payload config and safety validators."""

from __future__ import annotations

import json
from typing import Any

from release_confidence_platform.core.exceptions import EngineError
from release_confidence_platform.data_generation.duplicate_checker import (
    normalize_duplicate_policy,
    normalize_duplicate_scope,
)
from release_confidence_platform.data_generation.templates import contains_template_token

SUPPORTED_STRATEGIES = {"static", "generated", "data_pool"}


class PayloadValidationError(EngineError):
    def __init__(
        self,
        message: str = "Payload validation failed",
        *,
        payload_metadata: dict[str, Any] | None = None,
    ):
        super().__init__("PAYLOAD_VALIDATION_ERROR", message)
        self.payload_metadata = payload_metadata


def validate_endpoint_payload_config(endpoint: dict[str, Any]) -> dict[str, Any]:
    strategy = endpoint.get("payload_strategy", "static")
    if strategy not in SUPPORTED_STRATEGIES:
        raise PayloadValidationError("Invalid payload_strategy")
    policy = _normalize_or_payload_error(
        normalize_duplicate_policy, endpoint.get("duplicate_policy")
    )
    scope = _normalize_or_payload_error(
        normalize_duplicate_scope, endpoint.get("duplicate_check_scope")
    )
    iterations = endpoint.get("payload_iterations", 1)
    if not isinstance(iterations, int) or iterations < 1:
        raise PayloadValidationError("Invalid payload_iterations")
    safety = endpoint.get("payload_safety") or {}
    if not isinstance(safety, dict):
        raise PayloadValidationError("Invalid payload_safety")
    if (
        safety.get("destructive_operation") is True
        and safety.get("allow_destructive_operation") is not True
    ):
        raise PayloadValidationError("Destructive operation is not explicitly allowed")
    if strategy == "generated" and safety.get("allow_generated_payloads") is not True:
        raise PayloadValidationError("Generated payloads are not explicitly allowed")
    if strategy == "generated" and endpoint.get("payload_template") is None:
        raise PayloadValidationError("Generated payload_template is required")
    if strategy == "data_pool" and endpoint.get("data_pool_name") is None:
        raise PayloadValidationError("data_pool_name is required")
    if strategy == "static" and contains_template_token(endpoint.get("payload")):
        raise PayloadValidationError("Static payload cannot contain template tokens")
    _assert_json_serializable(endpoint.get("payload_template"))
    _assert_json_serializable(endpoint.get("payload"))
    return {
        **endpoint,
        "payload_strategy": strategy,
        "duplicate_policy": policy,
        "duplicate_check_scope": scope,
        "payload_iterations": iterations,
        "payload_safety": {
            "allow_generated_payloads": safety.get("allow_generated_payloads") is True,
            "allow_data_pool_reuse": safety.get("allow_data_pool_reuse") is True,
            "destructive_operation": safety.get("destructive_operation") is True,
            "allow_destructive_operation": safety.get("allow_destructive_operation") is True,
        },
    }


def _normalize_or_payload_error(func: Any, value: Any) -> str:
    try:
        return func(value)
    except ValueError as exc:
        raise PayloadValidationError(str(exc)) from exc


def _assert_json_serializable(value: Any) -> None:
    try:
        json.dumps(value)
    except TypeError as exc:
        raise PayloadValidationError("Payload must be JSON serializable") from exc
