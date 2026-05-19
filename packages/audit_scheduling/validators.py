"""Schedule-time configuration validation."""

from __future__ import annotations

from typing import Any

from packages.audit_scheduling.safeguards import (
    effective_caps,
    parse_iso_datetime,
    validate_token_metadata,
)
from packages.audit_scheduling.taxonomy import validate_scenario_type
from packages.core.exceptions import ValidationError
from packages.core.validators import validate_identifier


def validate_schedule_config(
    config: dict[str, Any], audit_window: dict[str, Any]
) -> dict[str, Any]:
    config = dict(config)
    config["client_id"] = validate_identifier("client_id", config.get("client_id"))
    config["audit_id"] = validate_identifier("audit_id", config.get("audit_id"))
    caps = effective_caps(config.get("execution_environment"))
    baseline = config.get("baseline") or {}
    if baseline.get("scenario_type"):
        validate_scenario_type(baseline["scenario_type"])
    if baseline.get("requests_per_run", 1) > caps["max_requests_per_run"]:
        raise ValidationError("Request cap exceeded", "CAP_EXCEEDED")
    for window in (config.get("burst_schedule") or {}).get("windows", []):
        validate_scenario_type(window.get("scenario_type", "burst_stability"))
        if window.get("request_count", 0) > caps["max_burst_requests_per_window"]:
            raise ValidationError("Burst request cap exceeded", "CAP_EXCEEDED")
        if (
            window.get("request_count", 0) > caps["max_requests_per_run"]
            and config.get("execution_environment", {}).get("target_environment") == "production"
        ):
            raise ValidationError("Production request cap exceeded", "CAP_EXCEEDED")
        if window.get("concurrency", 0) > caps["max_concurrency"]:
            raise ValidationError("Concurrency cap exceeded", "CAP_EXCEEDED")
    for repeated in config.get("repeated") or []:
        validate_scenario_type(repeated.get("scenario_type", "repeated_stability"))
        iterations = repeated.get("iteration_count")
        if not isinstance(iterations, int) or iterations <= 0:
            raise ValidationError("Invalid repeated iterations", "INVALID_SCHEDULE_CONFIG")
        if iterations > caps["max_repeated_iterations"]:
            raise ValidationError("Repeated iteration cap exceeded", "CAP_EXCEEDED")
        schedule_time = parse_iso_datetime(
            repeated.get("schedule_time", audit_window["start_time"])
        )
        # Conservative no-chaining estimate: one minute per iteration must fit before audit end.
        if (
            schedule_time.timestamp() + iterations * 60
            > parse_iso_datetime(audit_window["end_time"]).timestamp()
        ):
            raise ValidationError("Unsafe repeated execution estimate", "UNSAFE_REPEATED_ESTIMATE")
    config["temporary_token"] = validate_token_metadata(config.get("temporary_token"), audit_window)
    return config
