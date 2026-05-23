"""Sequential repeated execution coordinator."""

from __future__ import annotations

from typing import Any

from release_confidence_platform.audit_scheduling.safeguards import ensure_execution_allowed
from release_confidence_platform.core.exceptions import ValidationError


class RepeatedExecutionCoordinator:
    def __init__(self, orchestrator: Any):
        self.orchestrator = orchestrator

    def run(self, *, audit: dict[str, Any], event: dict[str, Any]) -> list[dict[str, Any]]:
        repeated = event.get("repeated") or {}
        iteration_count = repeated.get("iteration_count")
        if not isinstance(iteration_count, int) or iteration_count <= 0 or iteration_count > 100:
            raise ValidationError("Invalid repeated iteration count", "CAP_EXCEEDED")
        results = []
        for index in range(1, iteration_count + 1):
            ensure_execution_allowed(audit, event)
            results.append(
                self.orchestrator.run(
                    {
                        "client_id": event["client_id"],
                        "audit_id": event["audit_id"],
                        "scenario_type": event["scenario_type"],
                        "triggered_by": event["triggered_by"],
                        "iteration": index,
                    }
                )
            )
        return results
