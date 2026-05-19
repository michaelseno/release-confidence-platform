import pytest

from packages.audit_scheduling.events import (
    validate_finalization_event,
    validate_scheduled_execution_event,
)
from packages.core.exceptions import ValidationError


def test_scheduled_execution_event_contract_rejects_run_id():
    event = {
        "event_type": "audit_schedule_execution",
        "schema_version": "phase3.schedule_event.v1",
        "client_id": "client123",
        "audit_id": "audit456",
        "schedule_name": "rcp-dev-client123-audit456-baseline-baseline_health",
        "schedule_type": "baseline",
        "scenario_type": "baseline_health",
        "triggered_by": "eventbridge_scheduler",
        "schedule_occurrence_id": "baseline#2026-05-19T00:15:00Z",
        "scheduled_at": "2026-05-19T00:15:00Z",
        "run_id": "caller-run-id",
    }
    with pytest.raises(ValidationError):
        validate_scheduled_execution_event(event)
    del event["run_id"]
    assert validate_scheduled_execution_event(event)["schedule_occurrence_id"].startswith(
        "baseline#"
    )


def test_finalization_event_contract():
    event = {
        "event_type": "audit_finalization",
        "schema_version": "phase3.finalization_event.v1",
        "client_id": "client123",
        "audit_id": "audit456",
        "schedule_name": "rcp-dev-client123-audit456-finalization",
        "triggered_by": "eventbridge_scheduler",
        "audit_window_end": "2026-05-21T00:00:00Z",
        "schedule_occurrence_id": "finalization#2026-05-21T00:00:00Z",
    }
    assert validate_finalization_event(event)["audit_id"] == "audit456"
