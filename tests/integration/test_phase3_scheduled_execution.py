from apps.backend.handlers.scheduled_execution_handler import (
    ScheduledExecutionHandler,
    _emit_handler_started,
)


class Repo:
    def __init__(self):
        self.audit = {
            "lifecycle_state": "SCHEDULED",
            "audit_window": {
                "start_time": "2026-05-19T00:00:00Z",
                "end_time": "2026-05-21T00:00:00Z",
            },
            "execution_environment": {"target_environment": "staging"},
            "execution_counters": {"total_started": 0, "total_completed": 0},
        }
        self.claims = {}
        self.transitions = []

    def get_audit_metadata(self, client_id, audit_id):  # noqa: ARG002
        return self.audit

    def occurrence_keys(self, client_id, audit_id, occurrence_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#OCCURRENCE#{occurrence_id}"}

    def claim_occurrence(self, item):
        self.claims[(item["PK"], item["SK"])] = item

    def update_occurrence(self, key, updates):
        self.claims[(key["PK"], key["SK"])].update(updates)

    def update_execution_counters(self, client_id, audit_id, updates):  # noqa: ARG002
        self.audit["execution_counters"] = updates

    def append_lifecycle_transition(self, **kwargs):
        self.audit["lifecycle_state"] = kwargs["next_state"]
        self.transitions.append(kwargs)


class Orchestrator:
    def __init__(self):
        self.events = []

    def run(self, event):
        self.events.append(event)
        return {
            "run_id": "generated-run-id",
            "status": "COMPLETED",
            "raw_result_s3_key": "raw-results/client123/audit456/generated-run-id/results.json",
        }


class CaptureLogger:
    def __init__(self):
        self.records = []

    def log(self, message, **fields):
        self.records.append({"message": message, **fields})
        return self.records[-1]


def schedule_event(**overrides):
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
    }
    event.update(overrides)
    return event


def test_accepted_occurrence_claims_before_orchestrator_and_omits_run_id():
    repo = Repo()
    orch = Orchestrator()
    result = ScheduledExecutionHandler(repository=repo, orchestrator=orch).handle(schedule_event())
    assert result["status"] == "accepted"
    assert repo.transitions[0]["next_state"] == "RUNNING"
    assert orch.events and "run_id" not in orch.events[0]
    claim = next(iter(repo.claims.values()))
    assert claim["SK"].startswith("AUDIT#audit456#OCCURRENCE#")
    assert claim["run_id"] == "generated-run-id"


def test_scheduled_handler_emits_startup_claim_orchestration_logs():
    repo = Repo()
    orch = Orchestrator()
    logger = CaptureLogger()
    result = ScheduledExecutionHandler(
        repository=repo, orchestrator=orch, logger=logger
    ).handle(schedule_event())

    assert result["status"] == "accepted"
    messages = [record["message"] for record in logger.records]
    assert "event_contract_validated" in messages
    assert "occurrence_claim_attempted" in messages
    assert "occurrence_claim_created" in messages
    assert "orchestrator_execution_started" in messages
    assert "orchestrator_execution_completed" in messages
    assert "raw_results_written" in messages
    assert "run_metadata_written" in messages
    assert all("token" not in record for record in logger.records)


def test_scheduled_entrypoint_startup_log_is_lambda_visible(capsys):
    _emit_handler_started(schedule_event())

    captured = capsys.readouterr()
    assert "scheduled_execution_handler_started" in captured.out
    assert "schedule_occurrence_id" in captured.out


def test_scheduled_burst_metadata_is_preserved_for_orchestrator():
    repo = Repo()
    orch = Orchestrator()
    event = schedule_event(
        schedule_name="rcp-dev-client123-audit456-burst-burst_stability",
        schedule_type="burst",
        scenario_type="burst_stability",
        burst={
            "request_count": 7,
            "concurrency": 2,
            "window_start": "2026-05-19T09:00:00Z",
            "window_end": "2026-05-19T09:30:00Z",
        },
    )

    result = ScheduledExecutionHandler(repository=repo, orchestrator=orch).handle(event)

    assert result["status"] == "accepted"
    assert orch.events[0]["schedule_type"] == "burst"
    assert orch.events[0]["scheduled_at"] == "2026-05-19T00:15:00Z"
    assert orch.events[0]["burst"] == event["burst"]
    assert "run_id" not in orch.events[0]


def test_repeated_execution_is_sequential_and_omits_run_id():
    repo = Repo()
    orch = Orchestrator()
    event = schedule_event(
        schedule_type="repeated",
        scenario_type="repeated_stability",
        repeated={"iteration_count": 3, "execution_mode": "sequential"},
    )
    result = ScheduledExecutionHandler(repository=repo, orchestrator=orch).handle(event)
    assert result["status"] == "accepted"
    assert len(orch.events) == 3
    assert [event["iteration"] for event in orch.events] == [1, 2, 3]
    assert [event["repeated"]["iteration_count"] for event in orch.events] == [3, 3, 3]
    assert all("run_id" not in event for event in orch.events)


# ---------------------------------------------------------------------------
# B-01: completed orchestrator result increments total_completed
# ---------------------------------------------------------------------------

def test_scheduler_increments_total_completed_on_orchestrator_completed():
    """B-01: single execution with COMPLETED status → total_completed incremented, total_failed=0."""  # noqa: E501
    repo = Repo()

    class CompletedOrchestrator:
        def run(self, event):  # noqa: ARG002
            return {"run_id": "run-completed-01", "status": "COMPLETED"}

    ScheduledExecutionHandler(repository=repo, orchestrator=CompletedOrchestrator()).handle(
        schedule_event()
    )

    counters = repo.audit["execution_counters"]
    assert counters["total_started"] == 1
    assert counters["total_completed"] == 1
    assert counters.get("total_failed", 0) == 0


# ---------------------------------------------------------------------------
# B-02: failed orchestrator result does NOT increment total_completed
# ---------------------------------------------------------------------------

def test_scheduler_does_not_increment_total_completed_on_orchestrator_failed():
    """B-02: single execution with FAILED status → total_completed NOT incremented, total_failed=1."""  # noqa: E501
    repo = Repo()

    class FailedOrchestrator:
        def run(self, event):  # noqa: ARG002
            return {"run_id": "run-failed-01", "status": "FAILED"}

    ScheduledExecutionHandler(repository=repo, orchestrator=FailedOrchestrator()).handle(
        schedule_event()
    )

    counters = repo.audit["execution_counters"]
    assert counters["total_started"] == 1
    assert counters.get("total_completed", 0) == 0
    assert counters["total_failed"] == 1


# ---------------------------------------------------------------------------
# B-03: failed orchestrator result marks occurrence claim_status=failed
# ---------------------------------------------------------------------------

def test_scheduler_marks_occurrence_failed_when_orchestrator_returns_failed():
    """B-03: single execution with FAILED status → occurrence claim_status set to 'failed'."""
    repo = Repo()

    class FailedOrchestrator:
        def run(self, event):  # noqa: ARG002
            return {"run_id": "run-failed-02", "status": "FAILED"}

    ScheduledExecutionHandler(repository=repo, orchestrator=FailedOrchestrator()).handle(
        schedule_event()
    )

    claim = next(iter(repo.claims.values()))
    assert claim["claim_status"] == "failed"
    assert claim["run_id"] == "run-failed-02"


# ---------------------------------------------------------------------------
# B-04: mixed sequence of 4 COMPLETED + 1 FAILED across separate occurrences
# ---------------------------------------------------------------------------

def test_scheduler_counter_consistency_after_mixed_execution_sequence():
    """B-04: 4 COMPLETED + 1 FAILED → total_completed=4, total_failed=1, total_started=5."""
    call_count = 0

    class MixedOrchestrator:
        def run(self, event):  # noqa: ARG002
            nonlocal call_count
            call_count += 1
            status = "FAILED" if call_count == 3 else "COMPLETED"
            return {"run_id": f"run-mix-{call_count:02d}", "status": status}

    # Use a shared Repo that accumulates counters across five invocations.
    repo = Repo()
    # Override get_audit_metadata to always return the live audit dict so that
    # each subsequent call picks up counters written by the previous call.
    def get_live_audit(client_id, audit_id):  # noqa: ARG001
        return repo.audit

    repo.get_audit_metadata = get_live_audit

    orch = MixedOrchestrator()
    occurrence_ids = [
        "baseline#2026-05-19T00:15:00Z",
        "baseline#2026-05-19T00:30:00Z",
        "baseline#2026-05-19T00:45:00Z",
        "baseline#2026-05-19T01:00:00Z",
        "baseline#2026-05-19T01:15:00Z",
    ]
    handler = ScheduledExecutionHandler(repository=repo, orchestrator=orch)
    for occ_id in occurrence_ids:
        handler.handle(schedule_event(schedule_occurrence_id=occ_id))

    counters = repo.audit["execution_counters"]
    assert counters["total_started"] == 5
    assert counters["total_completed"] == 4
    assert counters["total_failed"] == 1
