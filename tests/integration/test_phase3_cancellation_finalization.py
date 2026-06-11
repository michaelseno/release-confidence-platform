from decimal import Decimal

import pytest

from apps.backend.handlers.audit_finalization_handler import AuditFinalizationHandler
from packages.audit_lifecycle.cancellation import AuditCancellationService


def _make_completed_run(run_id: str) -> dict:
    return {"run_id": run_id, "status": "COMPLETED"}


class Repo:
    def __init__(self, state="RUNNING", executions=1, run_records=None):
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
        self.items = {}
        # Default: one COMPLETED run per reported execution, used by the integrity gate.
        if run_records is not None:
            self._run_records = run_records
        else:
            try:
                n = int(executions)
            except (TypeError, ValueError):
                n = 0
            self._run_records = [_make_completed_run(f"run{i}") for i in range(n)] if n > 0 else []

    def get_audit_metadata(self, client_id, audit_id):  # noqa: ARG002
        return self.audit

    def list_run_records(self, client_id, audit_id):  # noqa: ARG002
        return self._run_records

    def append_lifecycle_transition(self, **kwargs):
        self.audit["lifecycle_state"] = kwargs["next_state"]
        self.audit["lifecycle_history"].append(kwargs["history_entry"])

    def record_finalization(self, client_id, audit_id, metadata):  # noqa: ARG002
        self.audit["finalization"] = metadata

    def record_cleanup_errors(self, client_id, audit_id, errors):  # noqa: ARG002
        self.audit["cleanup_errors"] = errors

    def aggregation_job_keys(self, client_id, audit_id, job_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#AGGJOB#{job_id}"}

    def put_aggregation_job_intent_once(self, item):
        self.items[(item["PK"], item["SK"])] = item

    def update_aggregation_job_intent(self, key, updates):
        self.items[(key["PK"], key["SK"])].update(updates)


class FakeS3:
    """S3 stub that returns evidence keys matching the repo's run records."""

    def __init__(self, repo: Repo, client_id: str = "client123", audit_id: str = "audit456"):
        self._repo = repo
        self._client_id = client_id
        self._audit_id = audit_id

    def list_raw_evidence_keys(self, client_id, audit_id):  # noqa: ARG002
        return [
            f"raw-results/{self._client_id}/{self._audit_id}/{r['run_id']}/results.json"
            for r in self._repo._run_records
            if r.get("status") != "STARTED"
        ]


def _handler(repo, *, aggregation_invoker=None, aggregation_function_name=None):
    """Create a handler with a matching S3 stub for normal finalization tests."""
    return AuditFinalizationHandler(
        repository=repo,
        s3_storage=FakeS3(repo),
        aggregation_invoker=aggregation_invoker,
        aggregation_function_name=aggregation_function_name,
    )


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


class AggregationInvoker:
    def __init__(self, fail=False):
        self.fail = fail
        self.invocations = []

    def invoke(self, *, function_name, payload, invocation_type="Event"):
        if self.fail:
            raise RuntimeError("invoke failed")
        self.invocations.append(
            {
                "function_name": function_name,
                "payload": payload,
                "invocation_type": invocation_type,
            }
        )
        return {"accepted_async_invocation": True}


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
    result = _handler(repo).handle(finalization_event())
    assert result["lifecycle_state"] == "COMPLETED"
    assert result["status"] == "completed"
    assert repo.audit["finalization"]["execution_count"] == 1
    assert [entry["to_state"] for entry in repo.audit["lifecycle_history"]] == [
        "FINALIZING",
        "COMPLETED",
    ]


def test_successful_finalization_triggers_internal_aggregation_event():
    repo = Repo(executions=1)
    invoker = AggregationInvoker()

    result = _handler(
        repo,
        aggregation_invoker=invoker,
        aggregation_function_name="auditAggregationFunction",
    ).handle(finalization_event())

    assert result["status"] == "completed"
    assert len(invoker.invocations) == 1
    assert invoker.invocations[0]["function_name"] == "auditAggregationFunction"
    assert invoker.invocations[0]["invocation_type"] == "Event"
    assert invoker.invocations[0]["payload"] | {"aggregation_job_id": "ignored"} == {
        "event_type": "aggregate_audit",
        "schema_version": "phase4.aggregation_event.v1",
        "client_id": "client123",
        "audit_id": "audit456",
        "aggregation_version": "agg_v1",
        "aggregation_job_id": "ignored",
    }
    assert next(iter(repo.items.values()))["trigger_invocation_status"] == "ACCEPTED"


def test_aggregation_trigger_failure_persists_durable_job_intent():
    repo = Repo(executions=1)
    invoker = AggregationInvoker(fail=True)

    result = _handler(
        repo,
        aggregation_invoker=invoker,
        aggregation_function_name="auditAggregationFunction",
    ).handle(finalization_event())

    assert result["status"] == "completed"
    intent = next(iter(repo.items.values()))
    assert intent["status"] == "INVOCATION_FAILED"
    assert intent["failure_category"] == "EVIDENCE_TRANSFORMING"
    assert intent["reason_code"] == "AGGREGATION_TRIGGER_INVOCATION_FAILED"


def test_zero_execution_finalization_does_not_trigger_aggregation():
    repo = Repo(executions=0)
    invoker = AggregationInvoker()

    result = _handler(
        repo,
        aggregation_invoker=invoker,
        aggregation_function_name="auditAggregationFunction",
    ).handle(finalization_event())

    assert result["status"] == "failed"
    assert invoker.invocations == []


def test_finalization_with_decimal_execution_counter_completes_after_logging():
    repo = Repo(executions=Decimal("13"))

    result = _handler(repo).handle(finalization_event())

    assert result["lifecycle_state"] == "COMPLETED"
    assert result["status"] == "completed"
    assert repo.audit["finalization"]["execution_count"] == 13
    assert [entry["to_state"] for entry in repo.audit["lifecycle_history"]] == [
        "FINALIZING",
        "COMPLETED",
    ]
    assert repo.audit["lifecycle_history"][0]["metadata"]["execution_count"] == 13


def test_finalization_with_zero_executions_fails_after_finalizing():
    repo = Repo(executions=0)
    result = _handler(repo).handle(finalization_event())
    assert result["lifecycle_state"] == "FAILED"
    assert [entry["to_state"] for entry in repo.audit["lifecycle_history"]] == [
        "FINALIZING",
        "FAILED",
    ]


def test_finalization_with_decimal_zero_execution_counter_still_fails():
    repo = Repo(executions=Decimal("0"))

    result = _handler(repo).handle(finalization_event())

    assert result["lifecycle_state"] == "FAILED"
    assert result["status"] == "failed"
    assert repo.audit["finalization"]["execution_count"] == 0
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

    result = _handler(repo).handle(finalization_event())

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

    result = _handler(repo).handle(finalization_event())

    assert result == {
        "client_id": "client123",
        "audit_id": "audit456",
        "status": "completed",
        "lifecycle_state": "COMPLETED",
    }
    assert repo.audit["lifecycle_state"] == "COMPLETED"
    assert [entry["to_state"] for entry in repo.audit["lifecycle_history"]] == ["COMPLETED"]


def test_finalization_retry_from_finalizing_with_decimal_metadata_completes():
    repo = Repo(state="FINALIZING", executions=Decimal("13"))
    repo.audit["finalization"] = {
        "execution_count": Decimal("13"),
        "schedule_occurrence_id": "finalization#2026-05-21T00:00:00Z",
    }

    result = _handler(repo).handle(finalization_event())

    assert result["lifecycle_state"] == "COMPLETED"
    assert repo.audit["lifecycle_state"] == "COMPLETED"
    assert repo.audit["lifecycle_history"][0]["metadata"]["execution_count"] == 13


def test_finalization_retry_from_finalizing_with_zero_metadata_fails():
    repo = Repo(state="FINALIZING", executions=0)
    repo.audit["finalization"] = {
        "execution_count": 0,
        "schedule_occurrence_id": "finalization#2026-05-21T00:00:00Z",
    }

    result = _handler(repo).handle(finalization_event())

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
