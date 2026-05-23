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


def validate_event(event: dict[str, Any]) -> OrchestratorEvent:
    if not isinstance(event, dict):
        raise ValidationError("Event must be an object", "INVALID_EVENT")
    client_id = validate_identifier("client_id", event.get("client_id"))
    audit_id = validate_identifier("audit_id", event.get("audit_id"))
    scenario_type = validate_identifier("scenario_type", event.get("scenario_type"))
    triggered_by = validate_identifier("triggered_by", event.get("triggered_by"))
    run_id = generate_run_id() if "run_id" not in event else validate_run_id(event.get("run_id"))
    return OrchestratorEvent(client_id, audit_id, scenario_type, triggered_by, run_id)
