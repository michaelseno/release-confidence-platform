"""Phase 3 audit finalization handler."""

from __future__ import annotations

import os
from typing import Any

import boto3

from packages.audit_lifecycle.constants import (
    LIFECYCLE_STATE_COMPLETED,
    LIFECYCLE_STATE_FAILED,
    LIFECYCLE_STATE_FINALIZING,
    TERMINAL_STATES,
)
from packages.audit_lifecycle.service import AuditLifecycleService, LifecycleTransition
from packages.audit_scheduling.events import validate_finalization_event
from packages.core.constants.engine import LOG_CATEGORY_CLIENT_SAFE
from packages.core.logging import StructuredLogger
from packages.core.time import utc_now_iso
from packages.sanitization.sanitizer import sanitize
from packages.storage.audit_metadata_client import AuditMetadataRepository


class AuditFinalizationHandler:
    def __init__(self, *, repository: Any, logger: StructuredLogger | None = None):
        self.repository = repository
        self.logger = logger or StructuredLogger()
        self.lifecycle = AuditLifecycleService(repository)

    def handle(self, event: dict[str, Any]) -> dict[str, Any]:
        validated = validate_finalization_event(event)
        audit = self.repository.get_audit_metadata(validated["client_id"], validated["audit_id"])
        current_state = audit["lifecycle_state"]

        if current_state in TERMINAL_STATES:
            self._log_finalization(
                "auditFinalization_skipped_terminal_state",
                validated,
                execution_count=_finalization_execution_count(audit),
                previous_state=current_state,
                next_state=current_state,
                reason="terminal_state_idempotent_skip",
                status="skipped",
            )
            return self._response(validated, status="skipped", lifecycle_state=current_state)

        if current_state == LIFECYCLE_STATE_FINALIZING:
            return self._handle_finalizing_retry(validated, audit)

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
        self._log_finalization(
            "auditFinalization_transition_requested",
            validated,
            execution_count=execution_count,
            previous_state=current_state,
            next_state=LIFECYCLE_STATE_FINALIZING,
            reason="finalization_trigger",
            status="transitioning",
        )
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
            self._fail_zero_execution_finalization(
                validated,
                execution_count=0,
                expected_current_state=LIFECYCLE_STATE_FINALIZING,
                reason="zero_executions_at_finalization",
            )
            return self._response(validated, status="failed", lifecycle_state=LIFECYCLE_STATE_FAILED)

        self._complete_finalization(
            validated,
            expected_current_state=LIFECYCLE_STATE_FINALIZING,
            execution_count=execution_count,
            reason="finalization_completed",
        )
        return self._response(validated, status="completed", lifecycle_state=LIFECYCLE_STATE_COMPLETED)

    def _handle_finalizing_retry(
        self, event: dict[str, Any], audit: dict[str, Any]
    ) -> dict[str, Any]:
        existing_execution_count = _finalization_execution_count(audit)
        if existing_execution_count and existing_execution_count > 0:
            self._complete_finalization(
                event,
                expected_current_state=LIFECYCLE_STATE_FINALIZING,
                execution_count=existing_execution_count,
                reason="finalization_retry_completed",
            )
            return self._response(event, status="completed", lifecycle_state=LIFECYCLE_STATE_COMPLETED)
        if existing_execution_count == 0:
            self._fail_zero_execution_finalization(
                event,
                execution_count=0,
                expected_current_state=LIFECYCLE_STATE_FINALIZING,
                reason="zero_executions_at_finalization",
            )
            return self._response(event, status="failed", lifecycle_state=LIFECYCLE_STATE_FAILED)

        self._log_finalization(
            "auditFinalization_skipped_finalizing_without_success_metadata",
            event,
            execution_count=existing_execution_count,
            previous_state=LIFECYCLE_STATE_FINALIZING,
            next_state=LIFECYCLE_STATE_FINALIZING,
            reason="finalizing_without_success_metadata",
            status="skipped",
        )
        return self._response(event, status="skipped", lifecycle_state=LIFECYCLE_STATE_FINALIZING)

    def _complete_finalization(
        self,
        event: dict[str, Any],
        *,
        expected_current_state: str,
        execution_count: int,
        reason: str,
    ) -> None:
        self.lifecycle.transition(
            LifecycleTransition(
                client_id=event["client_id"],
                audit_id=event["audit_id"],
                expected_current_state=expected_current_state,
                next_state=LIFECYCLE_STATE_COMPLETED,
                reason=reason,
                actor="finalization_handler",
                metadata={"execution_count": execution_count},
            )
        )
        self._log_finalization(
            "auditFinalization_completed",
            event,
            execution_count=execution_count,
            previous_state=expected_current_state,
            next_state=LIFECYCLE_STATE_COMPLETED,
            reason=reason,
            status="completed",
        )

    def _fail_zero_execution_finalization(
        self,
        event: dict[str, Any],
        *,
        execution_count: int,
        expected_current_state: str,
        reason: str,
    ) -> None:
        self.lifecycle.transition(
            LifecycleTransition(
                client_id=event["client_id"],
                audit_id=event["audit_id"],
                expected_current_state=expected_current_state,
                next_state=LIFECYCLE_STATE_FAILED,
                reason=reason,
                actor="finalization_handler",
                metadata={"execution_count": execution_count},
            )
        )
        self._log_finalization(
            "auditFinalization_failed_zero_executions",
            event,
            execution_count=execution_count,
            previous_state=expected_current_state,
            next_state=LIFECYCLE_STATE_FAILED,
            reason=reason,
            status="failed",
        )

    def _response(
        self, event: dict[str, Any], *, status: str, lifecycle_state: str
    ) -> dict[str, Any]:
        return sanitize(
            {
                "client_id": event["client_id"],
                "audit_id": event["audit_id"],
                "status": status,
                "lifecycle_state": lifecycle_state,
            }
        )

    def _log_finalization(
        self,
        message: str,
        event: dict[str, Any],
        *,
        execution_count: int | None,
        previous_state: str,
        next_state: str,
        reason: str,
        status: str,
    ) -> None:
        self.logger.log(
            message,
            log_category=LOG_CATEGORY_CLIENT_SAFE,
            client_id=event.get("client_id"),
            audit_id=event.get("audit_id"),
            schedule_name=event.get("schedule_name"),
            schedule_occurrence_id=event.get("schedule_occurrence_id"),
            execution_count=execution_count,
            previous_state=previous_state,
            next_state=next_state,
            reason=reason,
            status=status,
        )


def _finalization_execution_count(audit: dict[str, Any]) -> int | None:
    finalization = audit.get("finalization") or {}
    execution_count = finalization.get("execution_count")
    return execution_count if isinstance(execution_count, int) else None


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    table = boto3.resource("dynamodb").Table(os.environ["METADATA_TABLE"])
    repository = AuditMetadataRepository(os.environ["METADATA_TABLE"], table)
    return AuditFinalizationHandler(repository=repository).handle(event)
