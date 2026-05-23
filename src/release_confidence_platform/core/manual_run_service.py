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
        response = self.lambda_client.invoke(
            function_name=self.stage_config.orchestrator_function_name, payload=payload
        )
        return sanitize({"status": "success", "payload": payload, "invocation": response})
