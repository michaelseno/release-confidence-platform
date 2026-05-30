"""Manual orchestrator invocation service."""

from __future__ import annotations

from typing import Any

from release_confidence_platform.audit_scheduling.constants import EXECUTION_SCHEDULE_TYPES
from release_confidence_platform.audit_scheduling.taxonomy import validate_scenario_type
from release_confidence_platform.config.stage_config import StageConfig
from release_confidence_platform.core.validators import validate_identifier, validate_run_id
from release_confidence_platform.sanitization.sanitizer import sanitize


class ManualRunInvocationService:
    def __init__(self, *, stage_config: StageConfig, lambda_client: Any):
        self.stage_config = stage_config
        self.lambda_client = lambda_client

    def run(
        self,
        *,
        client_id: str,
        audit_id: str,
        scenario_type: str,
        run_id: str | None = None,
        schedule_type: str | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        payload = {
            "client_id": validate_identifier("client_id", client_id),
            "audit_id": validate_identifier("audit_id", audit_id),
            "scenario_type": validate_scenario_type(scenario_type),
            "triggered_by": "manual",
            "schedule_type": "manual",
            "stage": self.stage_config.stage,
        }
        if run_id is not None:
            payload["run_id"] = validate_run_id(run_id)
        if schedule_type is not None:
            if schedule_type not in ("manual", *EXECUTION_SCHEDULE_TYPES):
                from release_confidence_platform.core.exceptions import ValidationError

                raise ValidationError("Invalid schedule_type", "INVALID_SCHEDULE_TYPE")
            payload["schedule_type"] = schedule_type
        if dry_run:
            return sanitize(
                {
                    "status": "dry_run",
                    "payload": payload,
                    "function_name": self.stage_config.orchestrator_function_name,
                }
            )
        self.stage_config.validate_orchestrator_function_name()
        response = self.lambda_client.invoke(
            function_name=self.stage_config.orchestrator_function_name,
            payload=payload,
            invocation_type="RequestResponse",
        )
        handler_status = response.get("handler_status")
        normalized_status = handler_status.lower() if isinstance(handler_status, str) else None
        status = normalized_status if normalized_status in {"completed", "failed"} else "success"
        result = {"status": status, "payload": payload, "invocation": response}
        if status == "failed":
            result.update(_handler_failure_details(response=response, payload=payload))
        return sanitize(result)


def _handler_failure_details(
    *, response: dict[str, Any], payload: dict[str, Any]
) -> dict[str, Any]:
    """Extract bounded, safe fields from a synchronous handler failure response."""
    handler_response = response.get("handler_response")
    if not isinstance(handler_response, dict):
        handler_response = {}
    failure_summary = handler_response.get("failure_summary")
    if not isinstance(failure_summary, dict):
        failure_summary = {}

    error_type = failure_summary.get("error_type") or handler_response.get("error_type")
    message = failure_summary.get("message") or handler_response.get("message")
    run_id = handler_response.get("run_id") or payload.get("run_id")
    scenario_type = handler_response.get("scenario_type") or payload.get("scenario_type")
    handler_status = response.get("handler_status") or handler_response.get("status")
    next_step = failure_summary.get("next_step") or handler_response.get("next_step")

    details: dict[str, Any] = {
        "handler_status": handler_status,
        "run_id": run_id,
        "scenario_type": scenario_type,
        "error_code": error_type,
        "failure_type": error_type,
        "failure_message": message,
        "failure_summary": {
            key: value
            for key, value in {
                "error_type": error_type,
                "message": message,
                "next_step": next_step,
            }.items()
            if value is not None
        },
    }
    if next_step is not None:
        details["next_step"] = next_step
    details["failure_details"] = {
        key: details[key]
        for key in (
            "handler_status",
            "run_id",
            "scenario_type",
            "error_code",
            "failure_type",
            "failure_message",
            "next_step",
        )
        if details.get(key) is not None
    }
    return {key: value for key, value in details.items() if value not in (None, {})}
