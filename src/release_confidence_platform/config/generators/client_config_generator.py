"""Generate safe starter client configuration dictionaries."""

from __future__ import annotations

from typing import Any

SAFE_MAX_CONCURRENCY = 5
SAFE_MAX_REQUESTS_PER_RUN = 100
SAFE_TIMEOUT_SECONDS = 10


def generate_client_config(
    *,
    client_id: str,
    client_name: str,
    target_environment: str,
    request_defaults: dict[str, Any] | None = None,
    rate_limits: dict[str, Any] | None = None,
    retention_defaults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_defaults = request_defaults or {}
    rate_limits = rate_limits or {}
    max_concurrency = rate_limits.get("max_concurrency", SAFE_MAX_CONCURRENCY)
    config = {
        "config_version": "v1",
        "client_id": client_id,
        "client_name": client_name,
        "execution_environment": {
            "target_environment": target_environment,
            "allow_production_execution": False,
            "allow_destructive_operation": False,
        },
        "request_defaults": {
            "timeout_seconds": request_defaults.get("timeout_seconds", SAFE_TIMEOUT_SECONDS),
            "retries": request_defaults.get("retries", 0),
            "max_concurrency": max_concurrency,
        },
        "safety": {
            "allowed_methods": ["GET", "HEAD", "OPTIONS"],
            "allow_destructive_operation": False,
        },
        "sanitization": {"enabled": True},
        "operational_caps": {
            "max_concurrency": max_concurrency,
            "max_requests_per_run": rate_limits.get(
                "max_requests_per_run", SAFE_MAX_REQUESTS_PER_RUN
            ),
        },
    }
    if retention_defaults:
        config["retention_defaults"] = dict(retention_defaults)
    return config
