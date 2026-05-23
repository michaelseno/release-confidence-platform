"""Generate safe starter audit configuration dictionaries."""

from __future__ import annotations

from typing import Any

from release_confidence_platform.config.generators.client_config_generator import (
    SAFE_MAX_CONCURRENCY,
    SAFE_MAX_REQUESTS_PER_RUN,
)


def generate_audit_config(
    *, client_id: str, audit_id: str, target_environment: str, timezone: str = "UTC"
) -> dict[str, Any]:
    return {
        "config_version": "v1",
        "client_id": client_id,
        "audit_id": audit_id,
        "timezone": timezone,
        "audit_window": {"duration_hours": 48, "timezone": timezone},
        "execution_environment": {
            "target_environment": target_environment,
            "allow_production_execution": False,
            "allow_destructive_operation": False,
            "max_concurrency": SAFE_MAX_CONCURRENCY,
            "max_requests_per_run": SAFE_MAX_REQUESTS_PER_RUN,
        },
        "baseline_schedule": {
            "enabled": True,
            "interval_minutes": 15,
            "scenario_type": "baseline_health",
            "requests_per_run": 1,
        },
        "burst_schedule": {"enabled": False, "windows": []},
        "repeated_schedule": {
            "enabled": True,
            "runs_per_day": 1,
            "iteration_count": 1,
            "scenario_type": "repeated_stability",
        },
        "finalization_schedule": {"enabled": True},
        "operational_caps": {
            "max_concurrency": SAFE_MAX_CONCURRENCY,
            "max_requests_per_run": SAFE_MAX_REQUESTS_PER_RUN,
        },
    }
