"""Operational safeguard validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from release_confidence_platform.audit_lifecycle.constants import TERMINAL_STATES
from release_confidence_platform.audit_scheduling.constants import (
    DEFAULT_AUDIT_WINDOW_HOURS,
    MAX_AUDIT_WINDOW_HOURS,
    MAX_BURST_REQUESTS_PER_WINDOW,
    MAX_CONCURRENCY,
    MAX_REPEATED_ITERATIONS,
    MAX_REQUESTS_PER_RUN,
    PROD_MAX_BURST_REQUESTS_PER_WINDOW,
    PROD_MAX_CONCURRENCY,
    PROD_MAX_REQUESTS_PER_RUN,
)
from release_confidence_platform.core.exceptions import ValidationError


def parse_iso_datetime(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValidationError("Invalid datetime", "INVALID_DATETIME")
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValidationError("Invalid datetime", "INVALID_DATETIME") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def effective_caps(execution_environment: dict[str, Any] | None) -> dict[str, int]:
    env = execution_environment or {}
    if env.get("target_environment") == "production":
        if env.get("allow_production_execution") is not True:
            raise ValidationError(
                "Production execution requires explicit allow", "PRODUCTION_BLOCKED"
            )
        return {
            "max_requests_per_run": PROD_MAX_REQUESTS_PER_RUN,
            "max_concurrency": PROD_MAX_CONCURRENCY,
            "max_burst_requests_per_window": PROD_MAX_BURST_REQUESTS_PER_WINDOW,
            "max_repeated_iterations": MAX_REPEATED_ITERATIONS,
            "max_audit_window_hours": MAX_AUDIT_WINDOW_HOURS,
        }
    return {
        "max_requests_per_run": MAX_REQUESTS_PER_RUN,
        "max_concurrency": MAX_CONCURRENCY,
        "max_burst_requests_per_window": MAX_BURST_REQUESTS_PER_WINDOW,
        "max_repeated_iterations": MAX_REPEATED_ITERATIONS,
        "max_audit_window_hours": MAX_AUDIT_WINDOW_HOURS,
    }


def validate_audit_window(
    window: dict[str, Any] | None, *, now: datetime | None = None
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    window = dict(window or {})
    start = parse_iso_datetime(window.get("start_time")) if window.get("start_time") else now
    duration_hours = window.get("duration_hours", DEFAULT_AUDIT_WINDOW_HOURS)
    if not isinstance(duration_hours, int | float) or duration_hours <= 0:
        raise ValidationError("Invalid audit window duration", "INVALID_AUDIT_WINDOW")
    if duration_hours > MAX_AUDIT_WINDOW_HOURS:
        raise ValidationError("Audit window exceeds max", "AUDIT_WINDOW_TOO_LONG")
    end = (
        parse_iso_datetime(window["end_time"])
        if window.get("end_time")
        else start + timedelta(hours=duration_hours)
    )
    if end <= start:
        raise ValidationError("Invalid audit window", "INVALID_AUDIT_WINDOW")
    if (end - start).total_seconds() > MAX_AUDIT_WINDOW_HOURS * 3600:
        raise ValidationError("Audit window exceeds max", "AUDIT_WINDOW_TOO_LONG")
    return {
        "start_time": isoformat_z(start),
        "end_time": isoformat_z(end),
        "duration_hours": duration_hours,
        "timezone": window.get("timezone"),
    }


def validate_token_metadata(
    token: dict[str, Any] | None, audit_window: dict[str, Any]
) -> dict[str, Any] | None:
    if token is None:
        return None
    forbidden = {"token", "raw_token", "access_token", "authorization", "secret"}
    if forbidden.intersection(token):
        raise ValidationError("Raw token values are not allowed", "INVALID_TOKEN_METADATA")
    if not token.get("token_ref") or not token.get("expires_at"):
        raise ValidationError("Token reference and expiration required", "INVALID_TOKEN_METADATA")
    expires_at = parse_iso_datetime(token["expires_at"])
    if expires_at <= datetime.now(UTC):
        raise ValidationError("Token is expired", "EXPIRED_TOKEN")
    return {
        "token_ref": token["token_ref"],
        "expires_at": isoformat_z(expires_at),
        "issued_at": token.get("issued_at"),
        "scope": token.get("scope"),
        "least_privilege_description": token.get("least_privilege_description"),
        "expires_before_audit_end": expires_at < parse_iso_datetime(audit_window["end_time"]),
    }


def ensure_execution_allowed(audit: dict[str, Any], event: dict[str, Any]) -> None:
    if audit.get("lifecycle_state") in TERMINAL_STATES:
        raise ValidationError("Audit is terminal", "AUDIT_NOT_EXECUTABLE")
    caps = effective_caps(audit.get("execution_environment"))
    scheduled_at = parse_iso_datetime(event.get("scheduled_at"))
    window = audit.get("audit_window") or {}
    if scheduled_at < parse_iso_datetime(window["start_time"]) or scheduled_at > parse_iso_datetime(
        window["end_time"]
    ):
        raise ValidationError("Schedule occurrence outside audit window", "AUDIT_WINDOW_EXPIRED")
    token = audit.get("temporary_token")
    if token and parse_iso_datetime(token["expires_at"]) <= scheduled_at:
        raise ValidationError("Token expired for scheduled occurrence", "EXPIRED_TOKEN")
    burst = event.get("burst") or {}
    if burst:
        if burst.get("request_count", 0) > caps["max_requests_per_run"]:
            raise ValidationError("Request cap exceeded", "CAP_EXCEEDED")
        if burst.get("request_count", 0) > caps["max_burst_requests_per_window"]:
            raise ValidationError("Burst request cap exceeded", "CAP_EXCEEDED")
        if burst.get("concurrency", 0) > caps["max_concurrency"]:
            raise ValidationError("Concurrency cap exceeded", "CAP_EXCEEDED")
    repeated = event.get("repeated") or {}
    if repeated and repeated.get("iteration_count", 0) > caps["max_repeated_iterations"]:
        raise ValidationError("Repeated iteration cap exceeded", "CAP_EXCEEDED")
