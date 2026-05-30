from apps.backend.handlers.scheduled_execution_handler import ScheduledExecutionHandler


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
        return {"run_id": "generated-run-id", "status": "COMPLETED"}


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
