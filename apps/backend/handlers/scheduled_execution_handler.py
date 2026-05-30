"""Phase 3 scheduled execution handler."""

from __future__ import annotations

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
from packages.core.constants.engine import LOG_CATEGORY_CLIENT_SAFE
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
        audit = self.repository.get_audit_metadata(validated["client_id"], validated["audit_id"])
        claim_key = self.repository.occurrence_keys(
            validated["client_id"], validated["audit_id"], validated["schedule_occurrence_id"]
        )
        try:
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
        except DuplicateOccurrenceClaimError:
            self.logger.log(
                "audit_schedule_duplicate_delivery",
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
                results = RepeatedExecutionCoordinator(self.orchestrator).run(
                    audit=audit, event=validated
                )
                run_id = results[-1].get("run_id") if results else None
            else:
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
            self.repository.update_occurrence(
                claim_key,
                {"claim_status": "completed", "run_id": run_id, "completed_at": utc_now_iso()},
            )
            counters = dict(audit.get("execution_counters") or {})
            counters["total_started"] = counters.get("total_started", 0) + 1
            counters["total_completed"] = counters.get("total_completed", 0) + 1
            counters["last_execution_at"] = utc_now_iso()
            self.repository.update_execution_counters(
                validated["client_id"], validated["audit_id"], counters
            )
            return sanitize(
                {**self._base_response(validated), "status": "accepted", "run_id": run_id}
            )
        except EngineError as exc:
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

    def _base_response(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "client_id": event["client_id"],
            "audit_id": event["audit_id"],
            "schedule_type": event["schedule_type"],
        }


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    table = boto3.resource("dynamodb").Table(os.environ["METADATA_TABLE"])
    repository = AuditMetadataRepository(os.environ["METADATA_TABLE"], table)
    metadata = DynamoDBMetadataClient(os.environ["METADATA_TABLE"], table)
    orchestrator = CoreEngineOrchestrator(
        s3_storage=S3StorageClient(os.environ["RAW_RESULTS_BUCKET"], boto3.client("s3")),
        metadata_storage=metadata,
        secrets_client=SecretsManagerClient(boto3.client("secretsmanager")),
    )
    return ScheduledExecutionHandler(repository=repository, orchestrator=orchestrator).handle(event)
