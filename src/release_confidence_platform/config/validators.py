"""Minimal executable config validation for Phase 1."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from release_confidence_platform.core.constants.engine import (
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_RETRIES,
    MAX_TIMEOUT_SECONDS,
    SUPPORTED_HTTP_METHODS,
)
from release_confidence_platform.core.exceptions import ConfigError
from release_confidence_platform.core.validators import validate_identifier
from release_confidence_platform.data_generation.validators import (
    PayloadValidationError,
    validate_endpoint_payload_config,
)

SECRET_BEARING_KEYS = (
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "password",
    "secret",
    "token",
)


def _has_secret_ref(value: Any) -> bool:
    return (
        isinstance(value, dict) and isinstance(value.get("secret_ref"), str) and value["secret_ref"]
    )


def _validate_no_literal_secret(key: str, value: Any) -> None:
    lowered = key.lower().replace("-", "_")
    if any(part in lowered for part in SECRET_BEARING_KEYS) and not _has_secret_ref(value):
        raise ConfigError("Secret-bearing fields must use secret_ref", "CONFIG_VALIDATION_ERROR")


def extract_endpoints(config: Any, *, allow_empty: bool = False) -> list[dict[str, Any]]:
    endpoints = config.get("endpoints") if isinstance(config, dict) else config
    if not isinstance(endpoints, list):
        raise ConfigError("Endpoint config must contain endpoints list", "CONFIG_VALIDATION_ERROR")
    if not endpoints and not allow_empty:
        raise ConfigError(
            "Endpoint config must include at least one endpoint", "CONFIG_VALIDATION_ERROR"
        )
    return endpoints


def validate_audit_config(config: dict[str, Any], audit_id: str) -> None:
    if not isinstance(config, dict):
        raise ConfigError("Audit config must be an object", "CONFIG_VALIDATION_ERROR")
    if config.get("audit_id") is not None and config["audit_id"] != audit_id:
        raise ConfigError("Audit config audit_id mismatch", "CONFIG_VALIDATION_ERROR")


def validate_endpoint(endpoint: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(endpoint, dict):
        raise ConfigError("Endpoint must be an object", "CONFIG_VALIDATION_ERROR")
    endpoint_id = validate_identifier("endpoint_id", endpoint.get("endpoint_id"))
    method = endpoint.get("method")
    if not isinstance(method, str) or method.upper() not in SUPPORTED_HTTP_METHODS:
        raise ConfigError("Unsupported HTTP method", "CONFIG_VALIDATION_ERROR")
    url = endpoint.get("url")
    parts = urlsplit(url) if isinstance(url, str) else None
    if not parts or parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ConfigError("Endpoint URL must be http or https", "CONFIG_VALIDATION_ERROR")
    headers = endpoint.get("headers", {})
    if headers is None:
        headers = {}
    if not isinstance(headers, dict):
        raise ConfigError("Headers must be an object", "CONFIG_VALIDATION_ERROR")
    for key, value in headers.items():
        if not isinstance(key, str):
            raise ConfigError("Header names must be strings", "CONFIG_VALIDATION_ERROR")
        _validate_no_literal_secret(key, value)
    payload = endpoint.get("payload", endpoint.get("body"))
    try:
        json.dumps(payload)
    except TypeError as exc:
        raise ConfigError("Payload must be JSON serializable", "CONFIG_VALIDATION_ERROR") from exc
    timeout = endpoint.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if not isinstance(timeout, (int, float)) or timeout <= 0 or timeout > MAX_TIMEOUT_SECONDS:
        raise ConfigError("Invalid timeout_seconds", "CONFIG_VALIDATION_ERROR")
    retries = endpoint.get("retries", DEFAULT_RETRIES)
    if not isinstance(retries, int) or retries < 0 or retries > MAX_RETRIES:
        raise ConfigError("Invalid retries", "CONFIG_VALIDATION_ERROR")
    try:
        phase2_endpoint = validate_endpoint_payload_config({**endpoint, "payload": payload})
    except PayloadValidationError as exc:
        raise ConfigError(exc.message, "CONFIG_VALIDATION_ERROR") from exc
    assertions = endpoint.get("assertions", {}) or {}
    if not isinstance(assertions, dict):
        raise ConfigError("Assertions must be an object", "CONFIG_VALIDATION_ERROR")
    allowed_assertions = {"expected_status_codes", "expect_json", "required_response_fields"}
    if any(key not in allowed_assertions for key in assertions):
        raise ConfigError("Unsupported assertion", "CONFIG_VALIDATION_ERROR")
    return {
        **phase2_endpoint,
        "endpoint_id": endpoint_id,
        "method": method.upper(),
        "headers": headers,
        "payload": payload,
        "timeout_seconds": timeout,
        "retries": retries,
        "assertions": assertions,
    }


def validate_endpoint_config(config: Any, *, allow_empty: bool = False) -> list[dict[str, Any]]:
    return [
        validate_endpoint(endpoint)
        for endpoint in extract_endpoints(config, allow_empty=allow_empty)
    ]
