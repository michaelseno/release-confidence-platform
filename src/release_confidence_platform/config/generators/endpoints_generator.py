"""Generate safe starter endpoint configuration dictionaries."""

from __future__ import annotations

from typing import Any

from release_confidence_platform.config.generators.client_config_generator import (
    SAFE_TIMEOUT_SECONDS,
)


def generate_endpoints_config(
    *, client_id: str, audit_id: str, target_environment: str, include_sample: bool = False
) -> dict[str, Any]:
    endpoints: list[dict[str, Any]] = []
    if include_sample:
        endpoints.append(
            {
                "endpoint_id": "endpoint_health_check",
                "method": "GET",
                "url": "https://example.com/health",
                "target_environment": target_environment,
                "payload_strategy": "static",
                "payload": None,
                "payload_safety": {
                    "allow_generated_payloads": False,
                    "allow_data_pool_reuse": False,
                    "destructive_operation": False,
                    "allow_destructive_operation": False,
                },
                "auth_required": False,
                "headers": {},
                "timeout_seconds": SAFE_TIMEOUT_SECONDS,
                "retries": 0,
                "assertions": {"expected_status_codes": [200]},
            }
        )
    return {
        "config_version": "v1",
        "client_id": client_id,
        "audit_id": audit_id,
        "target_environment": target_environment,
        "endpoints": endpoints,
    }
