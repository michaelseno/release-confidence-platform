import pytest

from apps.backend.handlers.scheduled_execution_handler import ScheduledExecutionHandler
from packages.core.exceptions import ValidationError
from packages.storage.audit_metadata_client import DuplicateOccurrenceClaimError
from tests.integration.test_phase3_scheduled_execution import (
    CaptureLogger,
    Orchestrator,
    Repo,
    schedule_event,
)


class DuplicateRepo(Repo):
    def claim_occurrence(self, item):
        raise DuplicateOccurrenceClaimError()


def test_duplicate_delivery_skips_execution():
    orch = Orchestrator()
    logger = CaptureLogger()
    handler = ScheduledExecutionHandler(
        repository=DuplicateRepo(), orchestrator=orch, logger=logger
    )
    result = handler.handle(schedule_event())
    assert result["status"] == "duplicate_skipped"
    assert orch.events == []
    assert "duplicate_occurrence_skipped" in [record["message"] for record in logger.records]


def test_malformed_event_with_run_id_rejected_before_claim():
    repo = Repo()
    with pytest.raises(ValidationError):
        ScheduledExecutionHandler(repository=repo, orchestrator=Orchestrator()).handle(
            schedule_event(run_id="bad-run-id")
        )
    assert repo.claims == {}


def test_expired_window_blocks_after_claim_before_orchestrator():
    repo = Repo()
    repo.audit["audit_window"]["end_time"] = "2026-05-19T00:10:00Z"
    orch = Orchestrator()
    result = ScheduledExecutionHandler(repository=repo, orchestrator=orch).handle(schedule_event())
    assert result["status"] == "blocked"
    assert orch.events == []
    assert next(iter(repo.claims.values()))["claim_status"] == "skipped"
