"""Phase 3 scheduled execution handler."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import boto3

from apps.backend.orchestrator.service import CoreEngineOrchestrator
from packages.audit_lifecycle.constants import LIFECYCLE_STATE_RUNNING, LIFECYCLE_STATE_SCHEDULED
from packages.audit_lifecycle.service import AuditLifecycleService, LifecycleTransition
from packages.audit_scheduling.constants import SCHEDULE_TYPE_REPEATED
from packages.audit_scheduling.events import validate_scheduled_execution_event
from packages.audit_scheduling.repeated import RepeatedExecutionCoordinator
from packages.audit_scheduling.safeguards import ensure_execution_allowed
from packages.core.constants.engine import (
    LOG_CATEGORY_CLIENT_SAFE,
    RUN_STATUS_COMPLETED,
    RUN_STATUS_FAILED,
)
from packages.core.exceptions import EngineError, ValidationError
from packages.core.logging import StructuredLogger
from packages.core.time import utc_now_iso
from packages.sanitization.sanitizer import sanitize
from packages.storage.audit_metadata_client import (
    AuditMetadataRepository,
    DuplicateOccurrenceClaimError,
)
from packages.storage.dynamodb_client import DynamoDBMetadataClient
from packages.storage.s3_client import S3StorageClient
from packages.storage.secrets_client import SecretsManagerClient

# ---------------------------------------------------------------------------
# Startup import validation — fail fast on missing critical modules
# ---------------------------------------------------------------------------
try:
    from packages.core import logging as _core_logging  # noqa: F401
    from packages.storage import audit_metadata_client as _amc  # noqa: F401
except ImportError as _exc:  # pragma: no cover
    import logging as _logging
    _logging.critical("STARTUP_IMPORT_FAILURE: %s", _exc)
    raise


def configure_logging() -> None:
    """Configure Lambda-visible structured logging for the scheduled entrypoint."""

    level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()
    app_logger = logging.getLogger("release-confidence-platform")
    if not root_logger.handlers:
        logging.basicConfig(level=level)
    root_logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setLevel(level)
    app_logger.setLevel(level)
    app_logger.propagate = True


configure_logging()


def _emit_handler_started(event: Any) -> None:
    record = sanitize(
        {
            "timestamp": utc_now_iso(),
            "level": "INFO",
            "message": "scheduled_execution_handler_started",
            "service": "release-confidence-platform",
            "event_type": "scheduled_execution_handler_started",
            "event_keys": list(event.keys()) if isinstance(event, dict) else [],
            "input_type": type(event).__name__,
        }
    )
    print(json.dumps(record, sort_keys=True))


class ScheduledExecutionHandler:
    def __init__(
        self, *, repository: Any, orchestrator: Any, logger: StructuredLogger | None = None
    ):
        self.repository = repository
        self.orchestrator = orchestrator
        self.logger = logger or StructuredLogger()
        self.lifecycle = AuditLifecycleService(repository)

    def handle(self, event: dict[str, Any]) -> dict[str, Any]:
        validated = validate_scheduled_execution_event(event)
        self._log("event_contract_validated", validated)
        audit = self.repository.get_audit_metadata(validated["client_id"], validated["audit_id"])
        claim_key = self.repository.occurrence_keys(
            validated["client_id"], validated["audit_id"], validated["schedule_occurrence_id"]
        )
        try:
            self._log("occurrence_claim_attempted", validated)
            self.repository.claim_occurrence(
                {
                    **claim_key,
                    "client_id": validated["client_id"],
                    "audit_id": validated["audit_id"],
                    "schedule_occurrence_id": validated["schedule_occurrence_id"],
                    "schedule_name": validated["schedule_name"],
                    "schedule_type": validated["schedule_type"],
                    "scenario_type": validated["scenario_type"],
                    "scheduled_at": validated["scheduled_at"],
                    "claim_status": "claimed",
                    "claimed_at": utc_now_iso(),
                    "run_id": None,
                    "duplicate_delivery_count": 0,
                    "last_duplicate_at": None,
                }
            )
            self._log("occurrence_claim_created", validated)
        except DuplicateOccurrenceClaimError:
            self.logger.log(
                "duplicate_occurrence_skipped",
                log_category=LOG_CATEGORY_CLIENT_SAFE,
                client_id=validated["client_id"],
                audit_id=validated["audit_id"],
                schedule_name=validated["schedule_name"],
                schedule_type=validated["schedule_type"],
                scenario_type=validated["scenario_type"],
                schedule_occurrence_id=validated["schedule_occurrence_id"],
            )
            return sanitize(
                {**self._base_response(validated), "status": "duplicate_skipped", "run_id": None}
            )
        try:
            ensure_execution_allowed(audit, validated)
            if audit.get("lifecycle_state") == LIFECYCLE_STATE_SCHEDULED:
                self.lifecycle.transition(
                    LifecycleTransition(
                        client_id=validated["client_id"],
                        audit_id=validated["audit_id"],
                        expected_current_state=LIFECYCLE_STATE_SCHEDULED,
                        next_state=LIFECYCLE_STATE_RUNNING,
                        reason="scheduled_occurrence_started",
                        actor="orchestrator",
                        metadata={"schedule_occurrence_id": validated["schedule_occurrence_id"]},
                    )
                )
            if validated["schedule_type"] == SCHEDULE_TYPE_REPEATED:
                self._log("orchestrator_execution_started", validated)
                # RepeatedExecutionCoordinator.run() returns a list of individual result dicts.
                results = RepeatedExecutionCoordinator(self.orchestrator).run(
                    audit=audit, event=validated
                )
                run_id = results[-1].get("run_id") if results else None
                self._log("orchestrator_execution_completed", validated, run_id=run_id)
                # Count completed and failed outcomes across all individual results.
                num_completed = sum(
                    1 for r in results if r.get("status") == RUN_STATUS_COMPLETED
                )
                num_failed = sum(
                    1 for r in results if r.get("status") == RUN_STATUS_FAILED
                )
                # Derive aggregate claim status: all-completed, all-failed, or mixed→failed.
                if num_failed == 0:
                    occurrence_claim_status = "completed"
                else:
                    occurrence_claim_status = "failed"
            else:
                self._log("orchestrator_execution_started", validated)
                result = self.orchestrator.run(
                    {
                        "client_id": validated["client_id"],
                        "audit_id": validated["audit_id"],
                        "scenario_type": validated["scenario_type"],
                        "triggered_by": validated["triggered_by"],
                        "schedule_type": validated["schedule_type"],
                        "scheduled_at": validated["scheduled_at"],
                        "burst": validated.get("burst"),
                    }
                )
                run_id = result.get("run_id")
                self._log("orchestrator_execution_completed", validated, run_id=run_id)
                if result.get("raw_result_s3_key"):
                    self._log("raw_results_written", validated, run_id=run_id)
                if result.get("status"):
                    self._log("run_metadata_written", validated, run_id=run_id)
                # Counters track occurrence handler path outcomes, not terminal RUN record states.
                # The finalization integrity gate is the canonical authority for lifecycle completion.
                result_status = result.get("status")
                if result_status == RUN_STATUS_COMPLETED:
                    num_completed = 1
                    num_failed = 0
                    occurrence_claim_status = "completed"
                elif result_status == RUN_STATUS_FAILED:
                    num_completed = 0
                    num_failed = 1
                    occurrence_claim_status = "failed"
                else:
                    num_completed = 0
                    num_failed = 0
                    occurrence_claim_status = "failed"
            self.repository.update_occurrence(
                claim_key,
                {
                    "claim_status": occurrence_claim_status,
                    "run_id": run_id,
                    "completed_at": utc_now_iso(),
                },
            )
            counters = dict(audit.get("execution_counters") or {})
            counters["total_started"] = counters.get("total_started", 0) + 1
            counters["total_completed"] = counters.get("total_completed", 0) + num_completed
            counters["total_failed"] = counters.get("total_failed", 0) + num_failed
            counters["last_execution_at"] = utc_now_iso()
            self.repository.update_execution_counters(
                validated["client_id"], validated["audit_id"], counters
            )
            return sanitize(
                {**self._base_response(validated), "status": "accepted", "run_id": run_id}
            )
        except EngineError as exc:
            self._log(
                "scheduled_execution_failed",
                validated,
                level="ERROR",
                error_type=exc.error_type,
            )
            self.repository.update_occurrence(
                claim_key,
                {
                    "claim_status": "skipped" if isinstance(exc, ValidationError) else "failed",
                    "error_code": exc.error_type,
                    "completed_at": utc_now_iso(),
                },
            )
            return sanitize(
                {
                    **self._base_response(validated),
                    "status": "blocked",
                    "run_id": None,
                    "error_type": exc.error_type,
                }
            )

        except Exception:
            self._log("scheduled_execution_failed", validated, level="ERROR")
            raise

    def _base_response(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "client_id": event["client_id"],
            "audit_id": event["audit_id"],
            "schedule_type": event["schedule_type"],
        }

    def _log(
        self, message: str, event: dict[str, Any], *, level: str = "INFO", **fields: Any
    ) -> None:
        self.logger.log(
            message,
            log_category=LOG_CATEGORY_CLIENT_SAFE,
            level=level,
            client_id=event.get("client_id"),
            audit_id=event.get("audit_id"),
            schedule_name=event.get("schedule_name"),
            schedule_type=event.get("schedule_type"),
            scenario_type=event.get("scenario_type"),
            schedule_occurrence_id=event.get("schedule_occurrence_id"),
            scheduled_at=event.get("scheduled_at"),
            **fields,
        )


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    configure_logging()
    _emit_handler_started(event)
    table = boto3.resource("dynamodb").Table(os.environ["METADATA_TABLE"])
    repository = AuditMetadataRepository(os.environ["METADATA_TABLE"], table)
    metadata = DynamoDBMetadataClient(os.environ["METADATA_TABLE"], table)
    orchestrator = CoreEngineOrchestrator(
        s3_storage=S3StorageClient(os.environ["RAW_RESULTS_BUCKET"], boto3.client("s3")),
        metadata_storage=metadata,
        secrets_client=SecretsManagerClient(boto3.client("secretsmanager")),
    )
    return ScheduledExecutionHandler(repository=repository, orchestrator=orchestrator).handle(event)
