"""Integration tests for Workstream C — finalization integrity gate.

Tests are named by their scenario IDs from the WS-C specification:
  C-01 through C-05: gate-blocking and gate-passing scenarios
  ER-02: reproduction of the confirmed incident scenario

Each test exercises the gate via AuditFinalizationHandler so that the full
integration path (handler → gate → lifecycle transition) is validated.
"""

from __future__ import annotations

from apps.backend.handlers.audit_finalization_handler import AuditFinalizationHandler

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

CLIENT_ID = "client_test"
AUDIT_ID = "audit_test_001"


def _raw_key(run_id: str) -> str:
    return f"raw-results/{CLIENT_ID}/{AUDIT_ID}/{run_id}/results.json"


def _make_run(run_id: str, status: str) -> dict:
    return {"run_id": run_id, "status": status}


class Repo:
    """Minimal fake repository for finalization handler tests."""

    def __init__(
        self,
        *,
        state: str = "RUNNING",
        total_completed: int = 5,
        run_records: list[dict] | None = None,
        finalization: dict | None = None,
    ):
        self.audit: dict = {
            "lifecycle_state": state,
            "lifecycle_history": [],
            "audit_window": {
                "start_time": "2026-06-01T00:00:00Z",
                "end_time": "2026-06-08T00:00:00Z",
            },
            "execution_counters": {"total_completed": total_completed},
            "schedules": [
                {"schedule_name": "sched-baseline", "schedule_type": "baseline"},
                {"schedule_name": "sched-final", "schedule_type": "finalization"},
            ],
        }
        if finalization is not None:
            self.audit["finalization"] = finalization
        self.items: dict = {}
        self._run_records: list[dict] = run_records if run_records is not None else []

    # --- Repository interface ---

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
    """Fake S3 client that returns a fixed list of evidence keys."""

    def __init__(self, keys: list[str]):
        self._keys = list(keys)

    def list_raw_evidence_keys(self, client_id, audit_id):  # noqa: ARG002
        return list(self._keys)


def _finalization_event() -> dict:
    return {
        "event_type": "audit_finalization",
        "schema_version": "phase3.finalization_event.v1",
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "schedule_name": f"rcp-dev-{CLIENT_ID}-{AUDIT_ID}-finalization",
        "triggered_by": "eventbridge_scheduler",
        "audit_window_end": "2026-06-08T00:00:00Z",
        "schedule_occurrence_id": "finalization#2026-06-08T00:00:00Z",
    }


def _make_handler(repo: Repo, s3: FakeS3) -> AuditFinalizationHandler:
    return AuditFinalizationHandler(repository=repo, s3_storage=s3)


# ---------------------------------------------------------------------------
# C-01: Finalization blocked when one RUN is STARTED (4 COMPLETED + 1 STARTED)
# ---------------------------------------------------------------------------

def test_c01_finalization_blocked_when_started_run_exists():
    """Gate must block COMPLETED when any RUN record is still STARTED."""
    run_records = [
        _make_run("run-c01-1", "COMPLETED"),
        _make_run("run-c01-2", "COMPLETED"),
        _make_run("run-c01-3", "COMPLETED"),
        _make_run("run-c01-4", "COMPLETED"),
        _make_run("run-c01-5", "STARTED"),   # orphaned STARTED
    ]
    terminal_keys = [_raw_key(r["run_id"]) for r in run_records if r["status"] != "STARTED"]
    # S3 has only the 4 terminal keys — the STARTED run has no evidence
    repo = Repo(total_completed=4, run_records=run_records)
    s3 = FakeS3(terminal_keys)

    result = _make_handler(repo, s3).handle(_finalization_event())

    # Handler catches FinalizationGateError, transitions to FAILED, returns gate_failure response
    assert result["status"] == "gate_failure"
    assert result["lifecycle_state"] == "FAILED"

    # Lifecycle must NOT have reached COMPLETED
    states = [e["to_state"] for e in repo.audit["lifecycle_history"]]
    assert "COMPLETED" not in states, f"COMPLETED must not appear in history: {states}"
    assert repo.audit["lifecycle_state"] == "FAILED"


# ---------------------------------------------------------------------------
# C-02: Finalization blocked when COMPLETED RUN has raw_result_s3_key=None
#        (S3 evidence missing for a terminal RUN)
# ---------------------------------------------------------------------------

def test_c02_finalization_blocked_when_terminal_run_has_no_s3_evidence():
    """Gate must block COMPLETED when a terminal RUN has no matching S3 object."""
    run_records = [
        _make_run("run-c02-1", "COMPLETED"),
        _make_run("run-c02-2", "COMPLETED"),  # this run has no S3 key
        _make_run("run-c02-3", "COMPLETED"),
    ]
    # Only 2 of the 3 terminal runs have S3 evidence
    s3_keys = [_raw_key("run-c02-1"), _raw_key("run-c02-3")]
    repo = Repo(total_completed=3, run_records=run_records)
    s3 = FakeS3(s3_keys)

    result = _make_handler(repo, s3).handle(_finalization_event())

    # Handler catches FinalizationGateError, transitions to FAILED, returns gate_failure response
    assert result["status"] == "gate_failure"
    assert result["lifecycle_state"] == "FAILED"

    states = [e["to_state"] for e in repo.audit["lifecycle_history"]]
    assert "COMPLETED" not in states


# ---------------------------------------------------------------------------
# C-03: Finalization blocked when total_completed > count(terminal RUNs)
#        (counter inflation — counter higher than actual terminal evidence)
# ---------------------------------------------------------------------------

def test_c03_finalization_blocked_when_counter_exceeds_terminal_run_count():
    """Check 6 must fire when total_completed > terminal RUN records."""
    run_records = [
        _make_run("run-c03-1", "COMPLETED"),
        _make_run("run-c03-2", "COMPLETED"),
        _make_run("run-c03-3", "COMPLETED"),
    ]
    # Counter says 5, but only 3 terminal runs exist
    s3_keys = [_raw_key(r["run_id"]) for r in run_records]
    repo = Repo(total_completed=5, run_records=run_records)
    s3 = FakeS3(s3_keys)

    result = _make_handler(repo, s3).handle(_finalization_event())

    # Handler catches FinalizationGateError, transitions to FAILED, returns gate_failure response
    assert result["status"] == "gate_failure"
    assert result["lifecycle_state"] == "FAILED"

    states = [e["to_state"] for e in repo.audit["lifecycle_history"]]
    assert "COMPLETED" not in states


# ---------------------------------------------------------------------------
# C-04: Finalization blocked when total_completed < count(terminal RUNs)
# ---------------------------------------------------------------------------

def test_c04_finalization_blocked_when_counter_below_terminal_run_count():
    """Check 6 must fire when total_completed < terminal RUN records."""
    run_records = [
        _make_run("run-c04-1", "COMPLETED"),
        _make_run("run-c04-2", "COMPLETED"),
        _make_run("run-c04-3", "COMPLETED"),
        _make_run("run-c04-4", "COMPLETED"),
        _make_run("run-c04-5", "COMPLETED"),
    ]
    # Counter says 3 but 5 terminal runs exist
    s3_keys = [_raw_key(r["run_id"]) for r in run_records]
    repo = Repo(total_completed=3, run_records=run_records)
    s3 = FakeS3(s3_keys)

    result = _make_handler(repo, s3).handle(_finalization_event())

    # Handler catches FinalizationGateError, transitions to FAILED, returns gate_failure response
    assert result["status"] == "gate_failure"
    assert result["lifecycle_state"] == "FAILED"

    states = [e["to_state"] for e in repo.audit["lifecycle_history"]]
    assert "COMPLETED" not in states


# ---------------------------------------------------------------------------
# C-05: Finalization SUCCEEDS when all evidence reconciles (positive path)
# ---------------------------------------------------------------------------

def test_c05_finalization_succeeds_when_all_evidence_reconciles():
    """Gate must pass and COMPLETED must be reached when all evidence is consistent."""
    run_records = [
        _make_run("run-c05-1", "COMPLETED"),
        _make_run("run-c05-2", "COMPLETED"),
        _make_run("run-c05-3", "COMPLETED"),
        _make_run("run-c05-4", "COMPLETED"),
        _make_run("run-c05-5", "COMPLETED"),
    ]
    s3_keys = [_raw_key(r["run_id"]) for r in run_records]
    repo = Repo(total_completed=5, run_records=run_records)
    s3 = FakeS3(s3_keys)

    result = _make_handler(repo, s3).handle(_finalization_event())

    assert result["lifecycle_state"] == "COMPLETED"
    assert result["status"] == "completed"
    states = [e["to_state"] for e in repo.audit["lifecycle_history"]]
    assert "COMPLETED" in states


# ---------------------------------------------------------------------------
# ER-02: Orphaned STARTED run reproduces the confirmed incident scenario.
#        total_completed=5, 4 COMPLETED + 1 STARTED, 5 S3 objects.
#        The S3 key for the STARTED run uses an UNSANITIZED run_id that does
#        NOT match the DynamoDB record's run_id (sanitized equivalent).
# ---------------------------------------------------------------------------

def test_er02_incident_scenario_orphaned_started_run_blocks_completed():
    """Reproduce the audit_20260609_b18fee6a incident scenario.

    State:
    - execution_counters.total_completed = 5
    - 4 COMPLETED RUN records (run_ids: sanitized UUIDs)
    - 1 STARTED RUN record (run_id: sanitized variant — e.g. ends in [REDACTED]ec)
    - 5 S3 objects: 4 for the completed runs + 1 for the orphaned run but using
      the UNSANITIZED run_id (2475004829ec suffix) that does NOT match the
      DynamoDB record's sanitized run_id ([REDACTED]ec)

    Expected: gate returns passed=False, COMPLETED transition blocked.
    Handler catches FinalizationGateError and returns gate_failure response.
    """
    # Sanitized run_id as stored in DynamoDB (phone-pattern digits redacted)
    sanitized_run_id = "48a87626-e2f9-4f81-82ff-[REDACTED]ec"
    # Unsanitized run_id as embedded in the S3 key path
    unsanitized_run_id = "48a87626-e2f9-4f81-82ff-2475004829ec"

    run_records = [
        _make_run("run-er02-1", "COMPLETED"),
        _make_run("run-er02-2", "COMPLETED"),
        _make_run("run-er02-3", "COMPLETED"),
        _make_run("run-er02-4", "COMPLETED"),
        # Orphaned STARTED record — stored under SANITIZED run_id
        _make_run(sanitized_run_id, "STARTED"),
    ]

    # S3 has 4 correct keys + 1 key using the UNSANITIZED run_id
    s3_keys = [
        _raw_key("run-er02-1"),
        _raw_key("run-er02-2"),
        _raw_key("run-er02-3"),
        _raw_key("run-er02-4"),
        _raw_key(unsanitized_run_id),  # uses unsanitized id — no matching DDB record
    ]

    repo = Repo(total_completed=5, run_records=run_records)
    s3 = FakeS3(s3_keys)

    result = _make_handler(repo, s3).handle(_finalization_event())

    # Handler catches FinalizationGateError, transitions to FAILED, returns gate_failure response
    assert result["status"] == "gate_failure"
    assert result["lifecycle_state"] == "FAILED"

    # Lifecycle must NOT have reached COMPLETED
    states = [e["to_state"] for e in repo.audit["lifecycle_history"]]
    assert "COMPLETED" not in states, f"COMPLETED must not appear in history: {states}"
    assert repo.audit["lifecycle_state"] == "FAILED"


# ---------------------------------------------------------------------------
# Retry path: gate also runs on FINALIZING retry — blocks on failure
# ---------------------------------------------------------------------------

def test_retry_path_gate_also_blocks_when_started_run_exists():
    """Gate must block COMPLETED on the FINALIZING retry path too."""
    run_records = [
        _make_run("run-retry-1", "COMPLETED"),
        _make_run("run-retry-2", "STARTED"),  # orphaned
    ]
    s3_keys = [_raw_key("run-retry-1")]

    # Simulate audit already in FINALIZING state (retry scenario)
    repo = Repo(
        state="FINALIZING",
        total_completed=1,
        run_records=run_records,
        finalization={
            "execution_count": 1,
            "schedule_occurrence_id": "finalization#2026-06-08T00:00:00Z",
        },
    )
    s3 = FakeS3(s3_keys)

    result = _make_handler(repo, s3).handle(_finalization_event())

    # Handler catches FinalizationGateError, transitions to FAILED, returns gate_failure response
    assert result["status"] == "gate_failure"
    assert result["lifecycle_state"] == "FAILED"

    states = [e["to_state"] for e in repo.audit["lifecycle_history"]]
    assert "COMPLETED" not in states


# ---------------------------------------------------------------------------
# Retry path (positive): gate passes after evidence is reconciled
# ---------------------------------------------------------------------------

def test_retry_path_gate_passes_when_evidence_consistent():
    """Gate passes on the retry path when all evidence is consistent."""
    run_records = [
        _make_run("run-retry-ok-1", "COMPLETED"),
        _make_run("run-retry-ok-2", "COMPLETED"),
    ]
    s3_keys = [_raw_key(r["run_id"]) for r in run_records]

    repo = Repo(
        state="FINALIZING",
        total_completed=2,
        run_records=run_records,
        finalization={
            "execution_count": 2,
            "schedule_occurrence_id": "finalization#2026-06-08T00:00:00Z",
        },
    )
    s3 = FakeS3(s3_keys)

    result = _make_handler(repo, s3).handle(_finalization_event())

    assert result["lifecycle_state"] == "COMPLETED"
    assert result["status"] == "completed"
