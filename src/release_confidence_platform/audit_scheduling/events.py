"""Phase 3 scheduler event contracts."""

from __future__ import annotations

from typing import Any

from release_confidence_platform.audit_scheduling.constants import EXECUTION_SCHEDULE_TYPES
from release_confidence_platform.audit_scheduling.taxonomy import validate_scenario_type
from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.core.validators import validate_identifier


def validate_occurrence_id(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ValidationError("Invalid schedule_occurrence_id", "INVALID_SCHEDULE_EVENT")
    if any(part in value.lower() for part in ("token", "secret", "password")):
        raise ValidationError("Invalid schedule_occurrence_id", "INVALID_SCHEDULE_EVENT")
    return value


def validate_scheduled_execution_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValidationError("Scheduled event must be an object", "INVALID_SCHEDULE_EVENT")
    if "run_id" in event:
        raise ValidationError("Scheduled events must omit run_id", "INVALID_SCHEDULE_EVENT")
    required = (
        "event_type",
        "schema_version",
        "client_id",
        "audit_id",
        "schedule_name",
        "schedule_type",
        "scenario_type",
        "triggered_by",
        "schedule_occurrence_id",
        "scheduled_at",
    )
    for field in required:
        if field not in event:
            raise ValidationError(f"Missing {field}", "INVALID_SCHEDULE_EVENT")
    if event["event_type"] != "audit_schedule_execution":
        raise ValidationError("Invalid scheduled event type", "INVALID_SCHEDULE_EVENT")
    schedule_type = event["schedule_type"]
    if schedule_type not in EXECUTION_SCHEDULE_TYPES:
        raise ValidationError("Invalid schedule type", "INVALID_SCHEDULE_EVENT")
    return {
        **event,
        "client_id": validate_identifier("client_id", event["client_id"]),
        "audit_id": validate_identifier("audit_id", event["audit_id"]),
        "schedule_name": validate_identifier("schedule_name", event["schedule_name"]),
        "schedule_occurrence_id": validate_occurrence_id(event["schedule_occurrence_id"]),
        "scenario_type": validate_scenario_type(event["scenario_type"]),
        "triggered_by": validate_identifier("triggered_by", event["triggered_by"]),
    }


def validate_finalization_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict) or event.get("event_type") != "audit_finalization":
        raise ValidationError("Invalid finalization event", "INVALID_FINALIZATION_EVENT")
    required = (
        "client_id",
        "audit_id",
        "schedule_name",
        "triggered_by",
        "audit_window_end",
        "schedule_occurrence_id",
    )
    for field in required:
        if field not in event:
            raise ValidationError(f"Missing {field}", "INVALID_FINALIZATION_EVENT")
    return {
        **event,
        "client_id": validate_identifier("client_id", event["client_id"]),
        "audit_id": validate_identifier("audit_id", event["audit_id"]),
        "schedule_name": validate_identifier("schedule_name", event["schedule_name"]),
        "schedule_occurrence_id": validate_occurrence_id(event["schedule_occurrence_id"]),
    }
