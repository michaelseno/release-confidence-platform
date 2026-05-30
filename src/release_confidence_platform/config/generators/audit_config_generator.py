"""Generate safe starter audit configuration dictionaries."""

from __future__ import annotations

from typing import Any

from release_confidence_platform.config.generators.client_config_generator import (
    SAFE_MAX_CONCURRENCY,
    SAFE_MAX_REQUESTS_PER_RUN,
)


def generate_audit_config(
    *,
    client_id: str,
    audit_id: str,
    target_environment: str,
    timezone: str = "UTC",
    schedule_defaults: dict[str, Any] | None = None,
    rate_limits: dict[str, Any] | None = None,
) -> dict[str, Any]:
    schedule_defaults = schedule_defaults or {}
    rate_limits = rate_limits or {}
    audit_window = dict(schedule_defaults.get("audit_window") or {"duration_hours": 48})
    audit_window["timezone"] = timezone
    max_concurrency = rate_limits.get("max_concurrency", SAFE_MAX_CONCURRENCY)
    burst_schedule = dict(
        schedule_defaults.get("burst_schedule") or {"enabled": False, "windows": []}
    )
    burst_schedule.setdefault(
        "manual_burst_defaults", {"enabled": True, "request_count": 10, "concurrency": 2}
    )
    return {
        "config_version": "v1",
        "client_id": client_id,
        "audit_id": audit_id,
        "timezone": timezone,
        "audit_window": audit_window,
        "execution_environment": {
            "target_environment": target_environment,
            "allow_production_execution": False,
            "allow_destructive_operation": False,
            "max_concurrency": max_concurrency,
            "max_requests_per_run": rate_limits.get(
                "max_requests_per_run", SAFE_MAX_REQUESTS_PER_RUN
            ),
        },
        "baseline_schedule": schedule_defaults.get("baseline_schedule")
        or {
            "enabled": True,
            "interval_minutes": 15,
            "scenario_type": "baseline_health",
            "requests_per_run": 1,
        },
        "burst_schedule": burst_schedule,
        "repeated_schedule": schedule_defaults.get("repeated_schedule")
        or {
            "enabled": True,
            "runs_per_day": 1,
            "iteration_count": 1,
            "scenario_type": "repeated_stability",
        },
        "finalization_schedule": schedule_defaults.get("finalization_schedule")
        or {"enabled": True},
        "operational_caps": {
            "max_concurrency": max_concurrency,
            "max_requests_per_run": rate_limits.get(
                "max_requests_per_run", SAFE_MAX_REQUESTS_PER_RUN
            ),
        },
    }
