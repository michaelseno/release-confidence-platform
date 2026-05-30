"""Validation helpers for Phase 1 engine contracts."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any

from release_confidence_platform.core.exceptions import ValidationError

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


@dataclass(frozen=True)
class OrchestratorEvent:
    client_id: str
    audit_id: str
    scenario_type: str
    triggered_by: str
    run_id: str
    schedule_iteration_number: int | None = None
    schedule_iteration_count: int | None = None
    schedule_type: str | None = None
    scheduled_at: str | None = None
    burst: dict[str, Any] | None = None


def generate_run_id() -> str:
    return str(uuid.uuid4())


def validate_run_id(value: Any) -> str:
    if not isinstance(value, str) or not RUN_ID_PATTERN.fullmatch(value):
        raise ValidationError("Invalid run_id", "INVALID_RUN_ID")
    return value


def validate_identifier(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value or not IDENTIFIER_PATTERN.fullmatch(value):
        raise ValidationError(f"Invalid {name}", "INVALID_EVENT")
    return value


def normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValidationError("Event must be an object", "INVALID_EVENT")
    if "detail" in event:
        detail = event.get("detail")
        if not isinstance(detail, dict):
            raise ValidationError("Event detail must be an object", "INVALID_EVENT")
        return detail
    return event


def validate_event(event: dict[str, Any]) -> OrchestratorEvent:
    normalized = normalize_event(event)
    client_id = validate_identifier("client_id", normalized.get("client_id"))
    audit_id = validate_identifier("audit_id", normalized.get("audit_id"))
    scenario_type = validate_identifier("scenario_type", normalized.get("scenario_type"))
    triggered_by = validate_identifier("triggered_by", normalized.get("triggered_by"))
    run_id = (
        generate_run_id()
        if "run_id" not in normalized
        else validate_run_id(normalized.get("run_id"))
    )
    schedule_iteration_number = _optional_positive_int(
        normalized.get("iteration"), "Invalid repeated iteration"
    )
    repeated = normalized.get("repeated")
    if repeated is None:
        repeated = {}
    if not isinstance(repeated, dict):
        raise ValidationError("Invalid repeated metadata", "INVALID_EVENT")
    schedule_iteration_count = _optional_positive_int(
        repeated.get("iteration_count"),
        "Invalid repeated iteration count",
    )
    schedule_type = _optional_identifier("schedule_type", normalized.get("schedule_type"))
    scheduled_at = normalized.get("scheduled_at")
    if scheduled_at is not None and not isinstance(scheduled_at, str):
        raise ValidationError("Invalid scheduled_at", "INVALID_EVENT")
    burst = _optional_burst_metadata(normalized.get("burst"))
    return OrchestratorEvent(
        client_id,
        audit_id,
        scenario_type,
        triggered_by,
        run_id,
        schedule_iteration_number,
        schedule_iteration_count,
        schedule_type,
        scheduled_at,
        burst,
    )


def _optional_positive_int(value: Any, message: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValidationError(message, "INVALID_EVENT")
    return value


def _optional_identifier(name: str, value: Any) -> str | None:
    if value is None:
        return None
    return validate_identifier(name, value)


def _optional_burst_metadata(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValidationError("Invalid burst metadata", "INVALID_EVENT")
    burst = dict(value)
    for key in ("request_count", "concurrency"):
        if key in burst:
            burst[key] = _optional_positive_int(burst[key], f"Invalid burst {key}")
        else:
            raise ValidationError(f"Missing burst {key}", "INVALID_EVENT")
    for key in ("window_id", "window_start", "window_end"):
        if key in burst and burst[key] is not None and not isinstance(burst[key], str):
            raise ValidationError(f"Invalid burst {key}", "INVALID_EVENT")
    return burst
