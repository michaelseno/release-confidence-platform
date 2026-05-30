"""Audit scheduling service."""

from __future__ import annotations

from typing import Any

from release_confidence_platform.audit_lifecycle.constants import (
    LIFECYCLE_STATE_DRAFT,
    LIFECYCLE_STATE_FAILED,
    LIFECYCLE_STATE_SCHEDULED,
)
from release_confidence_platform.audit_lifecycle.service import (
    AuditLifecycleService,
    LifecycleTransition,
)
from release_confidence_platform.audit_scheduling.builders import ScheduleBuilder
from release_confidence_platform.audit_scheduling.safeguards import (
    effective_caps,
    validate_audit_window,
)
from release_confidence_platform.audit_scheduling.validators import validate_schedule_config
from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.sanitization.sanitizer import sanitize


class AuditSchedulingService:
    def __init__(
        self,
        *,
        repository: Any,
        scheduler_client: Any,
        stage: str,
        schedule_name_prefix: str | None = None,
    ):
        self.repository = repository
        self.scheduler_client = scheduler_client
        self.stage = stage
        self.builder = ScheduleBuilder(stage=stage, name_prefix=schedule_name_prefix)
        self.lifecycle = AuditLifecycleService(repository)

    def schedule_from_persisted_audit(
        self,
        *,
        client_id: str,
        audit_id: str,
        s3_storage: Any,
        allow_production: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        audit = self.repository.get_audit_metadata(client_id, audit_id)
        current_state = audit.get("lifecycle_state") or "UNKNOWN"
        if current_state != LIFECYCLE_STATE_DRAFT:
            raise ValidationError(
                "Audit lifecycle does not allow scheduling "
                f"(client_id={client_id}, audit_id={audit_id}, "
                f"current_state={current_state}, required_state={LIFECYCLE_STATE_DRAFT})",
                "INVALID_LIFECYCLE_STATE",
            )
        keys = audit.get("config_s3_keys") or {}
        audit_config = s3_storage.read_json(
            keys.get("audit_config") or f"configs/{client_id}/audits/{audit_id}/audit_config.json"
        )
        config = _normalize_product_schedule_config(audit_config, client_id, audit_id)
        env = config.get("execution_environment") or audit.get("execution_environment") or {}
        if (
            self.stage == "prod" or env.get("target_environment") == "production"
        ) and not allow_production:
            raise ValidationError(
                "production scheduling requires explicit --allow-production",
                "PRODUCTION_APPROVAL_REQUIRED",
            )
        config["execution_environment"] = env
        audit_window = validate_audit_window(config.get("audit_window"))
        config = validate_schedule_config(config, audit_window)
        definitions = self.builder.build_all(config, audit_window)
        planned = [
            sanitize({**definition.metadata, "schedule_name": definition.name})
            for definition in definitions
        ]
        if dry_run:
            return sanitize(
                {
                    "status": "dry_run",
                    "client_id": client_id,
                    "audit_id": audit_id,
                    "planned_schedules": planned,
                    "planned_lifecycle_state": LIFECYCLE_STATE_SCHEDULED,
                }
            )
        created: list[dict[str, Any]] = []
        try:
            for definition in definitions:
                created.append(self.scheduler_client.create_schedule(definition))
            self.repository.set_schedules(client_id, audit_id, created)
            self.lifecycle.transition(
                LifecycleTransition(
                    client_id=client_id,
                    audit_id=audit_id,
                    expected_current_state=audit["lifecycle_state"],
                    next_state=LIFECYCLE_STATE_SCHEDULED,
                    reason="schedules_created",
                    actor="operator_cli",
                    metadata={"schedule_count": len(created)},
                )
            )
        except Exception as exc:
            cleanup_errors = self._rollback(created)
            self.repository.set_schedules(client_id, audit_id, created)
            if cleanup_errors:
                self.repository.record_cleanup_errors(client_id, audit_id, cleanup_errors)
            self.lifecycle.transition(
                LifecycleTransition(
                    client_id=client_id,
                    audit_id=audit_id,
                    expected_current_state=audit["lifecycle_state"],
                    next_state=LIFECYCLE_STATE_FAILED,
                    reason="schedule_creation_failed",
                    actor="operator_cli",
                    metadata={"error_code": "SCHEDULE_CREATE_FAILED"},
                )
            )
            raise exc
        return sanitize(
            {
                "status": "success",
                "client_id": client_id,
                "audit_id": audit_id,
                "lifecycle_state": LIFECYCLE_STATE_SCHEDULED,
                "schedules": created,
            }
        )

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


def _normalize_product_schedule_config(
    audit_config: dict[str, Any], client_id: str, audit_id: str
) -> dict[str, Any]:
    config = dict(audit_config)
    config["client_id"] = client_id
    config["audit_id"] = audit_id
    window = dict(config.get("audit_window") or {})
    if "start_at" in window or "end_at" in window:
        window["start_time"] = window.get("start_time") or window.get("start_at")
        window["end_time"] = window.get("end_time") or window.get("end_at")
    window["timezone"] = window.get("timezone") or config.get("timezone")
    config["audit_window"] = window
    if "baseline_schedule" in config:
        config["baseline"] = config["baseline_schedule"]
    else:
        config["baseline"] = {"enabled": False}
    if "repeated_schedule" in config:
        repeated = config["repeated_schedule"]
        config["repeated"] = repeated if isinstance(repeated, list) else [repeated]
    else:
        config["repeated"] = []
    if "finalization_schedule" not in config:
        config["finalization_schedule"] = {"enabled": False}
    return config
