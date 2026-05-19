"""Phase 3 audit finalization handler."""

from __future__ import annotations

import os
from typing import Any

import boto3

from packages.audit_lifecycle.constants import (
    LIFECYCLE_STATE_FAILED,
    LIFECYCLE_STATE_FINALIZING,
    TERMINAL_STATES,
)
from packages.audit_lifecycle.service import AuditLifecycleService, LifecycleTransition
from packages.audit_scheduling.events import validate_finalization_event
from packages.core.time import utc_now_iso
from packages.sanitization.sanitizer import sanitize
from packages.storage.audit_metadata_client import AuditMetadataRepository


class AuditFinalizationHandler:
    def __init__(self, *, repository: Any):
        self.repository = repository
        self.lifecycle = AuditLifecycleService(repository)

    def handle(self, event: dict[str, Any]) -> dict[str, Any]:
        validated = validate_finalization_event(event)
        audit = self.repository.get_audit_metadata(validated["client_id"], validated["audit_id"])
        current_state = audit["lifecycle_state"]
        if current_state == LIFECYCLE_STATE_FINALIZING or current_state in TERMINAL_STATES:
            return sanitize(
                {
                    "client_id": validated["client_id"],
                    "audit_id": validated["audit_id"],
                    "status": "skipped",
                    "lifecycle_state": current_state,
                }
            )
        execution_count = (audit.get("execution_counters") or {}).get("total_completed", 0)
        metadata = {
            "client_id": validated["client_id"],
            "audit_id": validated["audit_id"],
            "triggered_at": utc_now_iso(),
            "audit_window_start": (audit.get("audit_window") or {}).get("start_time"),
            "audit_window_end": validated["audit_window_end"],
            "execution_count": execution_count,
            "zero_execution": execution_count == 0,
            "source": "eventbridge_scheduler",
            "schedule_name": validated["schedule_name"],
            "schedule_occurrence_id": validated["schedule_occurrence_id"],
        }
        self.lifecycle.transition(
            LifecycleTransition(
                client_id=validated["client_id"],
                audit_id=validated["audit_id"],
                expected_current_state=current_state,
                next_state=LIFECYCLE_STATE_FINALIZING,
                reason="finalization_trigger",
                actor="finalization_handler",
                metadata={"execution_count": execution_count},
            )
        )
        self.repository.record_finalization(validated["client_id"], validated["audit_id"], metadata)
        if execution_count == 0:
            self.lifecycle.transition(
                LifecycleTransition(
                    client_id=validated["client_id"],
                    audit_id=validated["audit_id"],
                    expected_current_state=LIFECYCLE_STATE_FINALIZING,
                    next_state=LIFECYCLE_STATE_FAILED,
                    reason="zero_executions_at_finalization",
                    actor="finalization_handler",
                    metadata={"execution_count": 0},
                )
            )
            return sanitize(
                {
                    "client_id": validated["client_id"],
                    "audit_id": validated["audit_id"],
                    "status": "failed",
                    "lifecycle_state": LIFECYCLE_STATE_FAILED,
                }
            )
        return sanitize(
            {
                "client_id": validated["client_id"],
                "audit_id": validated["audit_id"],
                "status": "finalizing",
                "lifecycle_state": LIFECYCLE_STATE_FINALIZING,
            }
        )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    table = boto3.resource("dynamodb").Table(os.environ["METADATA_TABLE"])
    repository = AuditMetadataRepository(os.environ["METADATA_TABLE"], table)
    return AuditFinalizationHandler(repository=repository).handle(event)
