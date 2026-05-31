import pytest

from apps.backend.handlers.audit_finalization_handler import AuditFinalizationHandler
from packages.audit_lifecycle.cancellation import AuditCancellationService


class Repo:
    def __init__(self, state="RUNNING", executions=1):
        self.audit = {
            "lifecycle_state": state,
            "lifecycle_history": [],
            "audit_window": {
                "start_time": "2026-05-19T00:00:00Z",
                "end_time": "2026-05-21T00:00:00Z",
            },
            "execution_counters": {"total_completed": executions},
            "schedules": [
                {"schedule_name": "schedule-one", "schedule_type": "baseline"},
                {"schedule_name": "schedule-two", "schedule_type": "finalization"},
            ],
        }

    def get_audit_metadata(self, client_id, audit_id):  # noqa: ARG002
        return self.audit

    def append_lifecycle_transition(self, **kwargs):
        self.audit["lifecycle_state"] = kwargs["next_state"]
        self.audit["lifecycle_history"].append(kwargs["history_entry"])

    def record_finalization(self, client_id, audit_id, metadata):  # noqa: ARG002
        self.audit["finalization"] = metadata

    def record_cleanup_errors(self, client_id, audit_id, errors):  # noqa: ARG002
        self.audit["cleanup_errors"] = errors


class Scheduler:
    def __init__(self, fail=False):
        self.deleted = []
        self.fail = fail

    def delete_schedule(self, name, group=None):  # noqa: ARG002
        if self.fail and name == "schedule-two":
            raise RuntimeError("delete failed")
        self.deleted.append(name)

    def disable_schedule(self, name, group=None):  # noqa: ARG002
        if self.fail and name == "schedule-two":
            raise RuntimeError("disable failed")


def finalization_event():
    return {
        "event_type": "audit_finalization",
        "schema_version": "phase3.finalization_event.v1",
        "client_id": "client123",
        "audit_id": "audit456",
        "schedule_name": "rcp-dev-client123-audit456-finalization",
        "triggered_by": "eventbridge_scheduler",
        "audit_window_end": "2026-05-21T00:00:00Z",
        "schedule_occurrence_id": "finalization#2026-05-21T00:00:00Z",
    }


def test_finalization_with_executions_completes_after_finalizing():
    repo = Repo(executions=1)
    result = AuditFinalizationHandler(repository=repo).handle(finalization_event())
    assert result["lifecycle_state"] == "COMPLETED"
    assert result["status"] == "completed"
    assert repo.audit["finalization"]["execution_count"] == 1
    assert [entry["to_state"] for entry in repo.audit["lifecycle_history"]] == [
        "FINALIZING",
        "COMPLETED",
    ]


def test_finalization_with_zero_executions_fails_after_finalizing():
    repo = Repo(executions=0)
    result = AuditFinalizationHandler(repository=repo).handle(finalization_event())
    assert result["lifecycle_state"] == "FAILED"
    assert [entry["to_state"] for entry in repo.audit["lifecycle_history"]] == [
        "FINALIZING",
        "FAILED",
    ]


@pytest.mark.parametrize("state", ["COMPLETED", "FAILED", "CANCELLED"])
def test_duplicate_finalization_delivery_skips_terminal_state(state):
    repo = Repo(state=state, executions=1)
    existing_finalization = {
        "execution_count": 1,
        "schedule_occurrence_id": "finalization#2026-05-21T00:00:00Z",
    }
    repo.audit["finalization"] = existing_finalization.copy()

    result = AuditFinalizationHandler(repository=repo).handle(finalization_event())

    assert result == {
        "client_id": "client123",
        "audit_id": "audit456",
        "status": "skipped",
        "lifecycle_state": state,
    }
    assert repo.audit["lifecycle_state"] == state
    assert repo.audit["lifecycle_history"] == []
    assert repo.audit["finalization"] == existing_finalization


def test_finalization_retry_from_finalizing_with_nonzero_metadata_completes():
    repo = Repo(state="FINALIZING", executions=1)
    repo.audit["finalization"] = {
        "execution_count": 1,
        "schedule_occurrence_id": "finalization#2026-05-21T00:00:00Z",
    }

    result = AuditFinalizationHandler(repository=repo).handle(finalization_event())

    assert result == {
        "client_id": "client123",
        "audit_id": "audit456",
        "status": "completed",
        "lifecycle_state": "COMPLETED",
    }
    assert repo.audit["lifecycle_state"] == "COMPLETED"
    assert [entry["to_state"] for entry in repo.audit["lifecycle_history"]] == ["COMPLETED"]


def test_finalization_retry_from_finalizing_with_zero_metadata_fails():
    repo = Repo(state="FINALIZING", executions=0)
    repo.audit["finalization"] = {
        "execution_count": 0,
        "schedule_occurrence_id": "finalization#2026-05-21T00:00:00Z",
    }

    result = AuditFinalizationHandler(repository=repo).handle(finalization_event())

    assert result["lifecycle_state"] == "FAILED"
    assert repo.audit["lifecycle_state"] == "FAILED"
    assert [entry["to_state"] for entry in repo.audit["lifecycle_history"]] == ["FAILED"]


def test_cancellation_cleanup_errors_recorded_but_cancelled():
    repo = Repo(state="SCHEDULED")
    result = AuditCancellationService(
        repository=repo, scheduler_client=Scheduler(fail=True)
    ).cancel(client_id="client123", audit_id="audit456")
    assert result["lifecycle_state"] == "CANCELLED"
    assert repo.audit["cleanup_errors"][0]["error_code"] == "SCHEDULE_CLEANUP_FAILED"


def test_cancellation_cleanup_iterates_multiple_discrete_baseline_schedules():
    repo = Repo(state="SCHEDULED")
    repo.audit["schedules"] = [
        {"schedule_name": "baseline-001", "schedule_type": "baseline"},
        {"schedule_name": "baseline-002", "schedule_type": "baseline"},
        {"schedule_name": "finalization", "schedule_type": "finalization"},
    ]
    scheduler = Scheduler()

    result = AuditCancellationService(repository=repo, scheduler_client=scheduler).cancel(
        client_id="client123", audit_id="audit456"
    )

    assert result["lifecycle_state"] == "CANCELLED"
    assert scheduler.deleted == ["baseline-001", "baseline-002", "finalization"]
