"""Generate safe starter client configuration dictionaries."""

from __future__ import annotations

from typing import Any

SAFE_MAX_CONCURRENCY = 5
SAFE_MAX_REQUESTS_PER_RUN = 100
SAFE_TIMEOUT_SECONDS = 10


def generate_client_config(
    *, client_id: str, client_name: str, target_environment: str
) -> dict[str, Any]:
    return {
        "config_version": "v1",
        "client_id": client_id,
        "client_name": client_name,
        "execution_environment": {
            "target_environment": target_environment,
            "allow_production_execution": False,
            "allow_destructive_operation": False,
        },
        "request_defaults": {
            "timeout_seconds": SAFE_TIMEOUT_SECONDS,
            "retries": 0,
            "max_concurrency": SAFE_MAX_CONCURRENCY,
        },
        "safety": {
            "allowed_methods": ["GET", "HEAD", "OPTIONS"],
            "allow_destructive_operation": False,
        },
        "sanitization": {"enabled": True},
        "operational_caps": {
            "max_concurrency": SAFE_MAX_CONCURRENCY,
            "max_requests_per_run": SAFE_MAX_REQUESTS_PER_RUN,
        },
    }
