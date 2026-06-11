"""Eligibility checks for Phase 4 aggregation."""

from __future__ import annotations

from typing import Any

from release_confidence_platform.audit_lifecycle.constants import LIFECYCLE_STATE_COMPLETED
from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.core.validators import validate_identifier


class AggregationIneligibleError(ValidationError):
    def __init__(self, reason_code: str):
        super().__init__("Audit is not eligible for aggregation", reason_code)


def validate_eligibility(audit: dict[str, Any]) -> None:
    if audit.get("lifecycle_state") != LIFECYCLE_STATE_COMPLETED:
        raise AggregationIneligibleError("AUDIT_NOT_COMPLETED")
    finalization = audit.get("finalization")
    if not isinstance(finalization, dict):
        raise AggregationIneligibleError("MISSING_FINALIZATION")
    execution_count = finalization.get("execution_count")
    if (
        not isinstance(execution_count, int)
        or isinstance(execution_count, bool)
        or execution_count <= 0
    ):
        raise AggregationIneligibleError("ZERO_EXECUTION_AUDIT_INELIGIBLE")
    if finalization.get("zero_execution") is not False:
        raise AggregationIneligibleError("ZERO_EXECUTION_AUDIT_INELIGIBLE")
    if not _has_successful_completion_transition(audit.get("lifecycle_history")):
        raise AggregationIneligibleError("MISSING_SUCCESSFUL_FINALIZATION_TRANSITION")


def resolve_config_version(audit: dict[str, Any]) -> str:
    for container in (
        audit,
        audit.get("finalization") if isinstance(audit.get("finalization"), dict) else {},
    ):
        value = container.get("config_version") if isinstance(container, dict) else None
        if value is not None:
            return validate_identifier("config_version", value)
    raise ValidationError("Missing config_version", "MISSING_CONFIG_VERSION")


def _has_successful_completion_transition(history: Any) -> bool:
    if not isinstance(history, list):
        return False
    for entry in history:
        if not isinstance(entry, dict):
            continue
        if entry.get("to_state") != LIFECYCLE_STATE_COMPLETED:
            continue
        reason = entry.get("reason")
        actor = entry.get("actor")
        if isinstance(reason, str) and reason.startswith("finalization_"):
            return True
        if actor == "finalization_handler":
            return True
    return False
