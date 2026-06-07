"""Internal aggregation event validation."""

from __future__ import annotations

from typing import Any

from release_confidence_platform.aggregation.constants import (
    AGGREGATION_EVENT_SCHEMA_VERSION,
    AGGREGATION_EVENT_TYPE,
    AGGREGATION_VERSION,
)
from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.core.validators import validate_identifier

_ALLOWED_FIELDS = {
    "event_type",
    "schema_version",
    "client_id",
    "audit_id",
    "aggregation_version",
    "aggregation_job_id",
}


def validate_aggregation_event(event: dict[str, Any]) -> dict[str, str | None]:
    if not isinstance(event, dict):
        raise ValidationError("Aggregation event must be an object", "INVALID_AGGREGATION_EVENT")
    unknown = set(event) - _ALLOWED_FIELDS
    if unknown:
        raise ValidationError("Unsupported aggregation event fields", "INVALID_AGGREGATION_EVENT")
    required = ("event_type", "schema_version", "client_id", "audit_id", "aggregation_version")
    for field in required:
        if field not in event:
            raise ValidationError(f"Missing {field}", "INVALID_AGGREGATION_EVENT")
    if event["event_type"] != AGGREGATION_EVENT_TYPE:
        raise ValidationError("Invalid aggregation event type", "INVALID_AGGREGATION_EVENT")
    if event["schema_version"] != AGGREGATION_EVENT_SCHEMA_VERSION:
        raise ValidationError("Invalid aggregation event schema", "INVALID_AGGREGATION_EVENT")
    if event["aggregation_version"] != AGGREGATION_VERSION:
        raise ValidationError("Unsupported aggregation version", "UNSUPPORTED_AGGREGATION_VERSION")
    job_id = event.get("aggregation_job_id")
    return {
        "client_id": validate_identifier("client_id", event["client_id"]),
        "audit_id": validate_identifier("audit_id", event["audit_id"]),
        "aggregation_version": AGGREGATION_VERSION,
        "aggregation_job_id": (
            validate_identifier("aggregation_job_id", job_id) if job_id is not None else None
        ),
    }
