"""Audit cancellation and schedule cleanup."""

from __future__ import annotations

from typing import Any

from packages.audit_lifecycle.constants import LIFECYCLE_STATE_CANCELLED
from packages.audit_lifecycle.service import AuditLifecycleService, LifecycleTransition
from packages.core.time import utc_now_iso
from packages.core.validators import validate_identifier
from packages.sanitization.sanitizer import sanitize


class AuditCancellationService:
    def __init__(self, *, repository: Any, scheduler_client: Any):
        self.repository = repository
        self.scheduler_client = scheduler_client
        self.lifecycle = AuditLifecycleService(repository)

    def cancel(
        self, *, client_id: str, audit_id: str, reason: str = "operator_cancelled"
    ) -> dict[str, Any]:
        client_id = validate_identifier("client_id", client_id)
        audit_id = validate_identifier("audit_id", audit_id)
        audit = self.repository.get_audit_metadata(client_id, audit_id)
        cleanup_errors: list[dict[str, Any]] = []
        cleanup_results = []
        for schedule in audit.get("schedules", []):
            result = self._cleanup_schedule(schedule)
            cleanup_results.append(result)
            if result["status"] == "cancel_cleanup_failed":
                cleanup_errors.append(result["cleanup_error"])
        if cleanup_errors:
            self.repository.record_cleanup_errors(client_id, audit_id, cleanup_errors)
        self.lifecycle.transition(
            LifecycleTransition(
                client_id=client_id,
                audit_id=audit_id,
                expected_current_state=audit["lifecycle_state"],
                next_state=LIFECYCLE_STATE_CANCELLED,
                reason=reason,
                actor="cancellation_handler",
                metadata={"cleanup_errors_count": len(cleanup_errors)},
            )
        )
        return sanitize(
            {
                "client_id": client_id,
                "audit_id": audit_id,
                "lifecycle_state": LIFECYCLE_STATE_CANCELLED,
                "cleanup_errors": cleanup_errors,
                "cleanup_results": cleanup_results,
            }
        )

    def _cleanup_schedule(self, schedule: dict[str, Any]) -> dict[str, Any]:
        schedule_name = schedule.get("schedule_name")
        group = schedule.get("schedule_group")
        try:
            self.scheduler_client.delete_schedule(schedule_name, group)
            status = "cancel_deleted"
            error = None
        except Exception:
            try:
                self.scheduler_client.disable_schedule(schedule_name, group)
                status = "cancel_disabled"
                error = None
            except Exception:
                status = "cancel_cleanup_failed"
                error = {
                    "schedule_name": schedule_name,
                    "schedule_type": schedule.get("schedule_type"),
                    "cleanup_action": "delete_then_disable",
                    "error_code": "SCHEDULE_CLEANUP_FAILED",
                    "timestamp": utc_now_iso(),
                }
        return sanitize({"schedule_name": schedule_name, "status": status, "cleanup_error": error})
