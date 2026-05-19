"""Audit scheduling service."""

from __future__ import annotations

from typing import Any

from packages.audit_lifecycle.constants import (
    LIFECYCLE_STATE_DRAFT,
    LIFECYCLE_STATE_FAILED,
    LIFECYCLE_STATE_SCHEDULED,
)
from packages.audit_lifecycle.service import AuditLifecycleService, LifecycleTransition
from packages.audit_scheduling.builders import ScheduleBuilder
from packages.audit_scheduling.safeguards import effective_caps, validate_audit_window
from packages.audit_scheduling.validators import validate_schedule_config
from packages.core.time import utc_now_iso
from packages.sanitization.sanitizer import sanitize


class AuditSchedulingService:
    def __init__(self, *, repository: Any, scheduler_client: Any, stage: str):
        self.repository = repository
        self.scheduler_client = scheduler_client
        self.builder = ScheduleBuilder(stage=stage)
        self.lifecycle = AuditLifecycleService(repository)

    def schedule_audit(self, config: dict[str, Any]) -> dict[str, Any]:
        audit_window = validate_audit_window(config.get("audit_window"))
        config = validate_schedule_config(config, audit_window)
        now = utc_now_iso()
        initial_item = sanitize(
            {
                **self.repository.audit_keys(config["client_id"], config["audit_id"]),
                "client_id": config["client_id"],
                "audit_id": config["audit_id"],
                "lifecycle_state": LIFECYCLE_STATE_DRAFT,
                "lifecycle_history": [],
                "audit_window": audit_window,
                "schedules": [],
                "execution_environment": config.get(
                    "execution_environment",
                    {"target_environment": "staging", "allow_production_execution": False},
                ),
                "operational_caps": effective_caps(config.get("execution_environment")),
                "temporary_token": config.get("temporary_token"),
                "execution_counters": {
                    "total_started": 0,
                    "total_completed": 0,
                    "total_failed": 0,
                    "total_skipped": 0,
                    "last_execution_at": None,
                },
                "finalization": None,
                "cleanup_errors": [],
                "created_at": now,
                "updated_at": now,
            }
        )
        try:
            self.repository.put_audit_metadata_once(initial_item)
        except Exception:
            # Existing DRAFT audits can be loaded by tests/operator tooling.
            # Other states fail through transition validation/conflict handling.
            initial_item = self.repository.get_audit_metadata(
                config["client_id"], config["audit_id"]
            )
        definitions = self.builder.build_all(config, audit_window)
        created: list[dict[str, Any]] = []
        try:
            for definition in definitions:
                created.append(self.scheduler_client.create_schedule(definition))
            self.repository.set_schedules(config["client_id"], config["audit_id"], created)
            self.lifecycle.transition(
                LifecycleTransition(
                    client_id=config["client_id"],
                    audit_id=config["audit_id"],
                    expected_current_state=initial_item["lifecycle_state"],
                    next_state=LIFECYCLE_STATE_SCHEDULED,
                    reason="schedules_created",
                    actor="scheduler",
                    metadata={"schedule_count": len(created)},
                )
            )
        except Exception as exc:
            cleanup_errors = self._rollback(created)
            self.repository.set_schedules(config["client_id"], config["audit_id"], created)
            if cleanup_errors:
                self.repository.record_cleanup_errors(
                    config["client_id"], config["audit_id"], cleanup_errors
                )
            try:
                current = self.repository.get_audit_metadata(
                    config["client_id"], config["audit_id"]
                )["lifecycle_state"]
                self.lifecycle.transition(
                    LifecycleTransition(
                        client_id=config["client_id"],
                        audit_id=config["audit_id"],
                        expected_current_state=current,
                        next_state=LIFECYCLE_STATE_FAILED,
                        reason="schedule_creation_failed",
                        actor="system_failure_handler",
                        metadata={
                            "error_code": "SCHEDULE_CREATE_FAILED",
                            "cleanup_errors_count": len(cleanup_errors),
                        },
                    )
                )
            finally:
                raise exc
        return sanitize(
            {
                "client_id": config["client_id"],
                "audit_id": config["audit_id"],
                "lifecycle_state": LIFECYCLE_STATE_SCHEDULED,
                "schedule_count": len(created),
                "audit_window": {
                    "start_time": audit_window["start_time"],
                    "end_time": audit_window["end_time"],
                },
            }
        )

    def _rollback(self, created: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleanup_errors = []
        for schedule in created:
            try:
                self.scheduler_client.delete_schedule(
                    schedule["schedule_name"], schedule.get("schedule_group")
                )
                schedule["status"] = "rollback_deleted"
            except Exception:
                try:
                    self.scheduler_client.disable_schedule(
                        schedule["schedule_name"], schedule.get("schedule_group")
                    )
                    schedule["status"] = "rollback_disabled"
                except Exception:
                    schedule["status"] = "rollback_failed"
                    cleanup_errors.append(
                        {
                            "schedule_name": schedule.get("schedule_name"),
                            "schedule_type": schedule.get("schedule_type"),
                            "cleanup_action": "rollback_delete_then_disable",
                            "error_code": "SCHEDULE_ROLLBACK_FAILED",
                            "timestamp": utc_now_iso(),
                        }
                    )
        return sanitize(cleanup_errors)
