"""Phase 3 audit finalization handler."""

from __future__ import annotations

import json
import logging
import os
import uuid
from decimal import Decimal
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
from packages.core.constants.engine import LOG_CATEGORY_CLIENT_SAFE, RUN_STATUS_STARTED
from packages.core.logging import StructuredLogger
from packages.core.time import utc_now_iso
from packages.sanitization.sanitizer import sanitize
from packages.storage.audit_metadata_client import AuditMetadataRepository
from packages.storage.lambda_client import LambdaInvocationClient
from packages.storage.s3_client import S3StorageClient
from release_confidence_platform.aggregation.constants import (
    AGGREGATION_EVENT_SCHEMA_VERSION,
    AGGREGATION_EVENT_TYPE,
    AGGREGATION_VERSION,
    FAILURE_CATEGORY_EVIDENCE_TRANSFORMING,
    JOB_STATUS_INTENT_RECORDED,
    JOB_STATUS_INVOCATION_FAILED,
    JOB_STATUS_INVOCATION_REQUESTED,
)
from release_confidence_platform.audit_lifecycle.finalization_gate import (
    FinalizationGateError,
    finalization_integrity_gate,
)


class AuditFinalizationHandler:
    def __init__(
        self,
        *,
        repository: Any,
        s3_storage: Any | None = None,
        logger: StructuredLogger | None = None,
        aggregation_invoker: Any | None = None,
        aggregation_function_name: str | None = None,
    ):
        self.repository = repository
        self.s3_storage = s3_storage
        self.logger = logger or StructuredLogger()
        self.lifecycle = AuditLifecycleService(repository)
        self.aggregation_invoker = aggregation_invoker
        self.aggregation_function_name = aggregation_function_name

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

        execution_count = _normalize_execution_count(
            (audit.get("execution_counters") or {}).get("total_completed", 0)
        )
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
            return self._response(
                validated, status="failed", lifecycle_state=LIFECYCLE_STATE_FAILED
            )

        try:
            self._complete_finalization(
                validated,
                audit=audit,
                expected_current_state=LIFECYCLE_STATE_FINALIZING,
                execution_count=execution_count,
                reason="finalization_completed",
            )
        except FinalizationGateError:
            return self._response(
                validated, status="gate_failure", lifecycle_state=LIFECYCLE_STATE_FINALIZING
            )
        self._trigger_aggregation_after_finalization(validated)
        return self._response(
            validated, status="completed", lifecycle_state=LIFECYCLE_STATE_COMPLETED
        )

    def _handle_finalizing_retry(
        self, event: dict[str, Any], audit: dict[str, Any]
    ) -> dict[str, Any]:
        existing_execution_count = _finalization_execution_count(audit)
        if existing_execution_count and existing_execution_count > 0:
            try:
                self._complete_finalization(
                    event,
                    audit=audit,
                    expected_current_state=LIFECYCLE_STATE_FINALIZING,
                    execution_count=existing_execution_count,
                    reason="finalization_retry_completed",
                )
            except FinalizationGateError:
                return self._response(
                    event, status="gate_failure", lifecycle_state=LIFECYCLE_STATE_FINALIZING
                )
            self._trigger_aggregation_after_finalization(event)
            return self._response(
                event, status="completed", lifecycle_state=LIFECYCLE_STATE_COMPLETED
            )
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
        audit: dict[str, Any],
        expected_current_state: str,
        execution_count: int,
        reason: str,
    ) -> None:
        client_id = event["client_id"]
        audit_id = event["audit_id"]

        # --- Finalization integrity gate ---
        # Load RUN records and S3 evidence keys to feed the gate.
        run_records = self.repository.list_run_records(client_id, audit_id)
        s3_keys: list[str] = (
            self.s3_storage.list_raw_evidence_keys(client_id, audit_id)
            if self.s3_storage is not None
            else []
        )

        # Set finalization.execution_count from the actual terminal RUN count
        # (not from execution_counters.total_completed).
        # If terminal_count is 0, use execution_count so the gate still runs
        # and Check 1 / Check 2 surface the inconsistency.
        terminal_count = len([r for r in run_records if r.get("status") != RUN_STATUS_STARTED])
        gate_execution_count = terminal_count if terminal_count > 0 else execution_count
        finalization = dict(audit.get("finalization") or {})
        finalization["execution_count"] = gate_execution_count
        audit_for_gate = dict(audit)
        audit_for_gate["finalization"] = finalization

        gate_result = finalization_integrity_gate(
            audit=audit_for_gate,
            run_records=run_records,
            s3_evidence_keys=s3_keys,
            client_id=client_id,
            audit_id=audit_id,
        )

        if not gate_result.passed:
            failure_payload = {
                "type": "FINALIZATION_INTEGRITY_GATE_FAILURE",
                "auditId": audit_id,
                "timestamp": gate_result.timestamp,
                "failedChecks": [
                    {
                        "check": f.check,
                        "expected": f.expected,
                        "actual": f.actual,
                        "detail": f.detail,
                    }
                    for f in gate_result.failures
                ],
            }
            # Gate failure payload logged via direct JSON — do not route through
            # StructuredLogger without sanitize=False support (see design section 13).
            logging.getLogger(__name__).error(json.dumps(failure_payload))
            raise FinalizationGateError(failure_payload)
        # --- Gate passed — proceed with COMPLETED transition ---

        self.lifecycle.transition(
            LifecycleTransition(
                client_id=client_id,
                audit_id=audit_id,
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

    def _trigger_aggregation_after_finalization(self, event: dict[str, Any]) -> None:
        job_id = f"aggjob_{uuid.uuid4().hex}"
        intent_key = self.repository.aggregation_job_keys(
            event["client_id"], event["audit_id"], job_id
        )
        now = utc_now_iso()
        self.repository.put_aggregation_job_intent_once(
            {
                **intent_key,
                "client_id": event["client_id"],
                "audit_id": event["audit_id"],
                "aggregation_job_id": job_id,
                "aggregation_version": AGGREGATION_VERSION,
                "status": JOB_STATUS_INTENT_RECORDED,
                "trigger_invocation_status": "NOT_REQUESTED",
                "intent_recorded_at": now,
                "started_at": None,
                "completed_at": None,
                "reason_code": None,
                "failure_category": None,
                "finalization_correlation": {
                    "schedule_name": event.get("schedule_name"),
                    "schedule_occurrence_id": event.get("schedule_occurrence_id"),
                },
            }
        )
        if self.aggregation_invoker is None or not self.aggregation_function_name:
            self._log_finalization(
                "auditFinalization_aggregation_trigger_not_configured",
                event,
                execution_count=None,
                previous_state=LIFECYCLE_STATE_COMPLETED,
                next_state=LIFECYCLE_STATE_COMPLETED,
                reason="aggregation_trigger_not_configured",
                status="skipped",
            )
            return
        self.repository.update_aggregation_job_intent(
            intent_key,
            {
                "status": JOB_STATUS_INVOCATION_REQUESTED,
                "trigger_invocation_status": "REQUESTED",
                "trigger_invocation_attempted_at": utc_now_iso(),
            },
        )
        payload = {
            "event_type": AGGREGATION_EVENT_TYPE,
            "schema_version": AGGREGATION_EVENT_SCHEMA_VERSION,
            "client_id": event["client_id"],
            "audit_id": event["audit_id"],
            "aggregation_version": AGGREGATION_VERSION,
            "aggregation_job_id": job_id,
        }
        try:
            self.aggregation_invoker.invoke(
                function_name=self.aggregation_function_name,
                payload=payload,
                invocation_type="Event",
            )
        except Exception:
            self.repository.update_aggregation_job_intent(
                intent_key,
                {
                    "status": JOB_STATUS_INVOCATION_FAILED,
                    "trigger_invocation_status": "FAILED",
                    "failure_category": FAILURE_CATEGORY_EVIDENCE_TRANSFORMING,
                    "reason_code": "AGGREGATION_TRIGGER_INVOCATION_FAILED",
                    "completed_at": utc_now_iso(),
                    "error_summary": {
                        "reason_code": "AGGREGATION_TRIGGER_INVOCATION_FAILED",
                        "component": "AuditFinalizationHandler",
                    },
                },
            )
            self._log_finalization(
                "auditFinalization_aggregation_trigger_failed",
                event,
                execution_count=None,
                previous_state=LIFECYCLE_STATE_COMPLETED,
                next_state=LIFECYCLE_STATE_COMPLETED,
                reason="aggregation_trigger_failed",
                status="failed",
            )
            return
        self.repository.update_aggregation_job_intent(
            intent_key,
            {
                "trigger_invocation_status": "ACCEPTED",
                "trigger_invocation_accepted_at": utc_now_iso(),
            },
        )
        self._log_finalization(
            "auditFinalization_aggregation_triggered",
            event,
            execution_count=None,
            previous_state=LIFECYCLE_STATE_COMPLETED,
            next_state=LIFECYCLE_STATE_COMPLETED,
            reason="aggregation_triggered",
            status="triggered",
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
    if not _is_integer_count(execution_count):
        return None
    return _normalize_execution_count(execution_count)


def _is_integer_count(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, Decimal):
        return value == value.to_integral_value()
    return False


def _normalize_execution_count(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ValueError("execution_count must be a whole number")
        return int(value)
    return value


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    table = boto3.resource("dynamodb").Table(os.environ["METADATA_TABLE"])
    repository = AuditMetadataRepository(os.environ["METADATA_TABLE"], table)
    aggregation_function_name = os.environ.get("AGGREGATION_FUNCTION_NAME")
    aggregation_invoker = (
        LambdaInvocationClient(boto3.client("lambda")) if aggregation_function_name else None
    )
    evidence_bucket = os.environ.get("EVIDENCE_BUCKET")
    s3_storage = (
        S3StorageClient(evidence_bucket, boto3.client("s3")) if evidence_bucket else None
    )
    return AuditFinalizationHandler(
        repository=repository,
        s3_storage=s3_storage,
        aggregation_invoker=aggregation_invoker,
        aggregation_function_name=aggregation_function_name,
    ).handle(event)
