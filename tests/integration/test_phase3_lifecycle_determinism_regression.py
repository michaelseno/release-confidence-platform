"""Regression tests for Phase 3 lifecycle determinism defects.

Covers three confirmed root causes from the HITL investigation on branch
bugfix/phase3-running-after-window-rca-v2:

RCA-1  _normalize_product_schedule_config injected {"enabled": False} for absent
       finalization_schedule keys, silently suppressing the finalization schedule.

RCA-2  AuditFinalizationHandler.handle() did not catch LifecycleConflictError from
       the RUNNING → FINALIZING transition.  An unhandled exception caused the Lambda
       to fail after EventBridge already deleted the one-time at() schedule, leaving the
       audit permanently stuck in RUNNING.

RCA-3  (Inherited from prior bug chain) The finalization integrity gate's
       NO_ORPHANED_STARTED_RECORDS check would leave audits stuck in FINALIZING when
       STARTED runs existed at window close.  Fixed by _fail_gate_failure_finalization()
       driving FINALIZING → FAILED.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from apps.backend.handlers.audit_finalization_handler import AuditFinalizationHandler
from packages.audit_lifecycle.exceptions import LifecycleConflictError
from packages.audit_scheduling.service import AuditSchedulingService
from src.release_confidence_platform.operator_cli.discovery_service import DiscoveryListService

# ---------------------------------------------------------------------------
# Shared test fixtures / stubs
# ---------------------------------------------------------------------------


def _finalization_event() -> dict:
    return {
        "event_type": "audit_finalization",
        "schema_version": "phase3.finalization_event.v1",
        "client_id": "client123",
        "audit_id": "audit456",
        "schedule_name": "rcp-dev-client123-audit456-finalization",
        "triggered_by": "eventbridge_scheduler",
        "audit_window_end": "2026-06-13T01:57:41Z",
        "schedule_occurrence_id": "finalization#2026-06-13T01:57:41Z",
    }


class _SimpleRepo:
    """In-memory repository stub for finalization handler tests."""

    def __init__(self, state="RUNNING", executions=1, run_records=None):
        self.audit = {
            "lifecycle_state": state,
            "lifecycle_history": [],
            "audit_window": {
                "start_time": "2026-06-12T17:57:41Z",
                "end_time": "2026-06-13T01:57:41Z",
            },
            "execution_counters": {"total_completed": executions},
            "schedules": [
                {"schedule_name": "rcp-dev-client123-audit456-baseline-baseline-health-001",
                 "schedule_type": "baseline"},
                {"schedule_name": "rcp-dev-client123-audit456-finalization",
                 "schedule_type": "finalization"},
            ],
            "finalization": None,
        }
        self.items: dict = {}
        if run_records is not None:
            self._run_records = run_records
        else:
            n = max(int(executions), 0) if executions is not None else 0
            self._run_records = [{"run_id": f"run{i}", "status": "COMPLETED"} for i in range(n)]
        self._transition_call_count = 0
        self._conflict_on_call: int | None = None  # raise on Nth append_lifecycle_transition

    def raise_conflict_on_first_transition(self) -> None:
        self._conflict_on_call = 0

    def get_audit_metadata(self, client_id, audit_id):  # noqa: ARG002
        return self.audit

    def list_run_records(self, client_id, audit_id):  # noqa: ARG002
        return self._run_records

    def append_lifecycle_transition(self, **kwargs):
        call_n = self._transition_call_count
        self._transition_call_count += 1
        if self._conflict_on_call is not None and call_n == self._conflict_on_call:
            raise LifecycleConflictError()
        self.audit["lifecycle_state"] = kwargs["next_state"]
        self.audit["lifecycle_history"].append(kwargs["history_entry"])

    def record_finalization(self, client_id, audit_id, metadata):  # noqa: ARG002
        self.audit["finalization"] = metadata

    def aggregation_job_keys(self, client_id, audit_id, job_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#AGGJOB#{job_id}"}

    def put_aggregation_job_intent_once(self, item):
        self.items[(item["PK"], item["SK"])] = item

    def update_aggregation_job_intent(self, key, updates):
        self.items[(key["PK"], key["SK"])].update(updates)


class _MatchingS3:
    """S3 stub: returns evidence keys for all non-STARTED run records."""

    def __init__(self, repo: _SimpleRepo, client_id="client123", audit_id="audit456"):
        self._repo = repo
        self._client_id = client_id
        self._audit_id = audit_id

    def list_raw_evidence_keys(self, client_id, audit_id):  # noqa: ARG002
        return [
            f"raw-results/{self._client_id}/{self._audit_id}/{r['run_id']}/results.json"
            for r in self._repo._run_records
            if r.get("status") != "STARTED"
        ]


def _handler(repo: _SimpleRepo, **kwargs) -> AuditFinalizationHandler:
    return AuditFinalizationHandler(
        repository=repo,
        s3_storage=_MatchingS3(repo),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Shared scheduling stubs
# ---------------------------------------------------------------------------


def _future_window() -> dict:
    """Return an audit_window that starts now and lasts 8 hours (well-formed)."""
    start = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"start_time": start, "duration_hours": 8}


class _SchedulingRepo:
    """In-memory repo for AuditSchedulingService tests."""

    def __init__(self):
        self.items: dict = {}

    def audit_keys(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

    def get_audit_metadata(self, client_id, audit_id):
        key = (f"CLIENT#{client_id}", f"AUDIT#{audit_id}")
        if key not in self.items:
            raise KeyError(f"audit not found: {client_id}/{audit_id}")
        return self.items[key]

    def put_audit_metadata_once(self, item):
        key = (item["PK"], item["SK"])
        if key in self.items:
            raise RuntimeError("already exists")
        self.items[key] = item

    def set_schedules(self, client_id, audit_id, schedules):
        self.get_audit_metadata(client_id, audit_id)["schedules"] = schedules

    def record_cleanup_errors(self, client_id, audit_id, errors):
        self.get_audit_metadata(client_id, audit_id)["cleanup_errors"] = errors

    def append_lifecycle_transition(self, **kwargs):
        item = self.get_audit_metadata(kwargs["client_id"], kwargs["audit_id"])
        item["lifecycle_state"] = kwargs["next_state"]
        item.setdefault("lifecycle_history", []).append(kwargs["history_entry"])


class _FakeScheduler:
    def __init__(self):
        self.created: list[dict] = []

    def create_schedule(self, definition):
        meta = {**definition.metadata, "status": "created"}
        self.created.append(meta)
        return meta

    def delete_schedule(self, name, group_name=None):  # noqa: ARG002
        pass

    def disable_schedule(self, name, group_name=None):  # noqa: ARG002
        pass


class _FakeS3:
    def __init__(self, data: dict):
        self._data = data

    def read_json(self, key: str) -> dict:
        return self._data[key]


class _FakePersistRepo(_SchedulingRepo):
    """Extends _SchedulingRepo to support schedule_from_persisted_audit."""

    def __init__(self, initial_audit: dict):
        super().__init__()
        key = (f"CLIENT#{initial_audit['client_id']}", f"AUDIT#{initial_audit['audit_id']}")
        self.items[key] = initial_audit


# ---------------------------------------------------------------------------
# RCA-1: _normalize_product_schedule_config finalization_schedule fix
# ---------------------------------------------------------------------------


class TestNormalizeConfigFinalizationSchedule:
    """RCA-1: Absent finalization_schedule key must not suppress the finalization schedule."""

    def test_config_without_finalization_key_still_creates_finalization_schedule(self):
        """Primary regression guard for RCA-1.

        When the audit config S3 file does not contain a finalization_schedule key, the
        previous code injected {"enabled": False}, causing build_all() to skip
        build_finalization().  The correct behaviour is for build_all()'s `or {"enabled": True}`
        fallback to take effect — an absent key is treated as enabled.
        """
        config = {
            "client_id": "client1",
            "audit_id": "audit1",
            "audit_window": _future_window(),
            "execution_environment": {
                "target_environment": "staging",
                "allow_production_execution": False,
            },
            "baseline_schedule": {"enabled": True, "interval_minutes": 15},
            # finalization_schedule deliberately absent
        }
        repo = _FakePersistRepo({
            "PK": "CLIENT#client1",
            "SK": "AUDIT#audit1",
            "client_id": "client1",
            "audit_id": "audit1",
            "lifecycle_state": "DRAFT",
            "config_s3_keys": {"audit_config": "audit.json"},
        })
        scheduler = _FakeScheduler()

        result = AuditSchedulingService(
            repository=repo,
            scheduler_client=scheduler,
            stage="staging",
            schedule_name_prefix="rcp-staging",
        ).schedule_from_persisted_audit(
            client_id="client1",
            audit_id="audit1",
            s3_storage=_FakeS3({"audit.json": config}),
            dry_run=True,
        )

        types = [s["schedule_type"] for s in result["planned_schedules"]]
        assert "finalization" in types, (
            "finalization schedule must be planned even when config omits finalization_schedule key"
        )

    def test_config_with_finalization_enabled_true_creates_finalization_schedule(self):
        """Explicit finalization_schedule: {enabled: true} must also produce a finalization schedule."""  # noqa: E501
        config = {
            "client_id": "client1",
            "audit_id": "audit1",
            "audit_window": _future_window(),
            "execution_environment": {
                "target_environment": "staging",
                "allow_production_execution": False,
            },
            "baseline_schedule": {"enabled": True, "interval_minutes": 15},
            "finalization_schedule": {"enabled": True},
        }
        repo = _FakePersistRepo({
            "PK": "CLIENT#client1",
            "SK": "AUDIT#audit1",
            "client_id": "client1",
            "audit_id": "audit1",
            "lifecycle_state": "DRAFT",
            "config_s3_keys": {"audit_config": "audit.json"},
        })
        scheduler = _FakeScheduler()

        result = AuditSchedulingService(
            repository=repo,
            scheduler_client=scheduler,
            stage="staging",
            schedule_name_prefix="rcp-staging",
        ).schedule_from_persisted_audit(
            client_id="client1",
            audit_id="audit1",
            s3_storage=_FakeS3({"audit.json": config}),
            dry_run=True,
        )

        types = [s["schedule_type"] for s in result["planned_schedules"]]
        assert "finalization" in types

    def test_config_with_finalization_enabled_false_omits_finalization_schedule(self):
        """Explicit finalization_schedule: {enabled: false} must suppress the finalization schedule.

        This is the only legitimate way to disable finalization — by explicitly setting
        enabled=false in the config.  An absent key must NOT be treated as disabled.
        """
        config = {
            "client_id": "client1",
            "audit_id": "audit1",
            "audit_window": _future_window(),
            "execution_environment": {
                "target_environment": "staging",
                "allow_production_execution": False,
            },
            "baseline_schedule": {"enabled": True, "interval_minutes": 15},
            "finalization_schedule": {"enabled": False},
        }
        repo = _FakePersistRepo({
            "PK": "CLIENT#client1",
            "SK": "AUDIT#audit1",
            "client_id": "client1",
            "audit_id": "audit1",
            "lifecycle_state": "DRAFT",
            "config_s3_keys": {"audit_config": "audit.json"},
        })
        scheduler = _FakeScheduler()

        result = AuditSchedulingService(
            repository=repo,
            scheduler_client=scheduler,
            stage="staging",
            schedule_name_prefix="rcp-staging",
        ).schedule_from_persisted_audit(
            client_id="client1",
            audit_id="audit1",
            s3_storage=_FakeS3({"audit.json": config}),
            dry_run=True,
        )

        types = [s["schedule_type"] for s in result["planned_schedules"]]
        assert "finalization" not in types, (
            "explicit finalization_schedule: {enabled: false} must suppress finalization schedule"
        )


# ---------------------------------------------------------------------------
# RCA-2: LifecycleConflictError on RUNNING → FINALIZING must not leave RUNNING permanently
# ---------------------------------------------------------------------------


class TestLifecycleConflictOnFinalizingTransition:
    """RCA-2: LifecycleConflictError on RUNNING→FINALIZING must be handled idempotently."""

    def test_conflict_on_transition_when_already_terminal_returns_skipped(self):
        """If a conflict occurs and re-read shows a terminal state, return skipped (idempotent)."""
        repo = _SimpleRepo(state="RUNNING", executions=1)
        # Simulate: conflict fires on first transition attempt; re-read shows COMPLETED
        repo.raise_conflict_on_first_transition()
        repo.audit["lifecycle_state"] = "RUNNING"  # initial read sees RUNNING

        # After the conflict, the repo will return the same dict — but we need to simulate
        # the re-read showing a terminal state.  We do this by overriding get_audit_metadata
        # to return a terminal state on the second call.
        call_count = {"n": 0}

        def patched_get(client_id, audit_id):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"lifecycle_state": "RUNNING", "lifecycle_history": [],
                        "audit_window": repo.audit["audit_window"],
                        "execution_counters": {"total_completed": 1},
                        "finalization": None}
            # Second call (after conflict): audit is already COMPLETED
            return {"lifecycle_state": "COMPLETED", "lifecycle_history": [],
                    "audit_window": repo.audit["audit_window"],
                    "execution_counters": {"total_completed": 1},
                    "finalization": {"execution_count": 1}}

        repo.get_audit_metadata = patched_get

        handler = _handler(repo)
        result = handler.handle(_finalization_event())

        assert result["status"] == "skipped", (
            "must return skipped when conflict reveals audit already reached a terminal state"
        )

    def test_conflict_on_transition_when_already_finalizing_executes_retry_path(self):
        """If a conflict occurs and re-read shows FINALIZING, the retry path must execute."""
        repo = _SimpleRepo(state="RUNNING", executions=1)
        repo.raise_conflict_on_first_transition()

        call_count = {"n": 0}

        def patched_get(client_id, audit_id):  # noqa: ARG001
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Initial read: RUNNING
                return {
                    "lifecycle_state": "RUNNING",
                    "lifecycle_history": [],
                    "audit_window": repo.audit["audit_window"],
                    "execution_counters": {"total_completed": 1},
                    "finalization": {"execution_count": 1},  # finalization metadata already set
                }
            # After conflict: already FINALIZING with finalization metadata
            return {
                "lifecycle_state": "FINALIZING",
                "lifecycle_history": [{"to_state": "FINALIZING"}],
                "audit_window": repo.audit["audit_window"],
                "execution_counters": {"total_completed": 1},
                "finalization": {"execution_count": 1},
            }

        repo.get_audit_metadata = patched_get
        # Allow subsequent transitions (no more conflicts)
        repo._conflict_on_call = None

        handler = _handler(repo)
        result = handler.handle(_finalization_event())

        # The retry path should complete finalization → COMPLETED (run records match gate)
        assert result["lifecycle_state"] in ("COMPLETED", "FAILED", "gate_failure"), (
            f"retry path must execute and produce a terminal state, got {result}"
        )
        assert result["status"] != "running", (
            "audit must not remain in RUNNING after LifecycleConflictError"
        )

    def test_conflict_on_transition_does_not_leave_audit_in_running(self):
        """Core regression guard for RCA-2.

        Before the fix, an unhandled LifecycleConflictError caused the Lambda to fail.
        The one-time EventBridge at() schedule is deleted on first invocation regardless
        of Lambda outcome.  The audit would permanently remain in RUNNING with no automatic
        escape.

        With the fix, LifecycleConflictError is caught, re-read is performed, and the
        handler returns a non-RUNNING response.
        """
        repo = _SimpleRepo(state="RUNNING", executions=2)
        repo.raise_conflict_on_first_transition()

        call_count = {"n": 0}

        def patched_get(client_id, audit_id):  # noqa: ARG001
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {
                    "lifecycle_state": "RUNNING",
                    "lifecycle_history": [],
                    "audit_window": repo.audit["audit_window"],
                    "execution_counters": {"total_completed": 2},
                    "finalization": None,
                }
            # After conflict: some unexpected intermediate state
            return {
                "lifecycle_state": "RUNNING",
                "lifecycle_history": [],
                "audit_window": repo.audit["audit_window"],
                "execution_counters": {"total_completed": 2},
                "finalization": None,
            }

        repo.get_audit_metadata = patched_get

        handler = _handler(repo)
        # Must NOT raise an unhandled LifecycleConflictError
        result = handler.handle(_finalization_event())

        assert result["lifecycle_state"] != "RUNNING", (
            f"audit must NOT remain in RUNNING after LifecycleConflictError, got {result}"
        )


# ---------------------------------------------------------------------------
# RCA-3 (regression guard): STARTED runs at window close → FINALIZING → FAILED
# ---------------------------------------------------------------------------


class TestStartedRunsAtWindowClose:
    """STARTED runs at window close must not cause permanent FINALIZING dead-end."""

    def test_started_run_at_window_close_terminates_to_failed_not_finalizing(self):
        """Primary regression guard: STARTED run at finalization → gate failure → FAILED.

        The gate's NO_ORPHANED_STARTED_RECORDS check fails when any run record is in
        STARTED state.  The handler must drive FINALIZING → FAILED, never leave the
        audit permanently stuck in FINALIZING.
        """
        run_records = [
            {"run_id": "run-completed-1", "status": "COMPLETED"},
            {"run_id": "run-started-1", "status": "STARTED"},  # in-flight at window close
        ]
        repo = _SimpleRepo(executions=1, run_records=run_records)

        class _PartialS3:
            def list_raw_evidence_keys(self, client_id, audit_id):  # noqa: ARG002
                return [f"raw-results/{client_id}/{audit_id}/run-completed-1/results.json"]

        handler = AuditFinalizationHandler(
            repository=repo,
            s3_storage=_PartialS3(),
        )
        result = handler.handle(_finalization_event())

        assert result["status"] == "gate_failure"
        assert result["lifecycle_state"] == "FAILED"
        assert repo.audit["lifecycle_state"] == "FAILED"
        states = [entry["to_state"] for entry in repo.audit["lifecycle_history"]]
        assert "FINALIZING" in states, "must have passed through FINALIZING"
        assert states[-1] == "FAILED", f"final state must be FAILED, got {states}"

    def test_all_started_runs_at_window_close_terminates_to_failed(self):
        """All runs STARTED at window close → no terminal runs → gate fails both checks → FAILED."""
        run_records = [
            {"run_id": "run-started-1", "status": "STARTED"},
            {"run_id": "run-started-2", "status": "STARTED"},
        ]
        repo = _SimpleRepo(executions=2, run_records=run_records)

        class _EmptyS3:
            def list_raw_evidence_keys(self, client_id, audit_id):  # noqa: ARG002
                return []

        handler = AuditFinalizationHandler(
            repository=repo,
            s3_storage=_EmptyS3(),
        )
        result = handler.handle(_finalization_event())

        assert result["lifecycle_state"] == "FAILED"
        assert result["status"] in ("gate_failure", "failed")
        assert repo.audit["lifecycle_state"] == "FAILED"


# ---------------------------------------------------------------------------
# Audit list read-through: no stale cache in DiscoveryListService.list_audits
# ---------------------------------------------------------------------------


class TestAuditListReadThrough:
    """rcp audit list must reflect DynamoDB state directly (no cache layer)."""

    def test_list_audits_reflects_current_dynamodb_state(self):
        """list_audits() must query the repository on every call without caching.

        If the same DiscoveryListService instance is called twice and the underlying
        repository state changes between calls, the second call must return the updated
        state.
        """

        class _StateChangingRepo:
            def __init__(self):
                self._call_count = 0
                self._state_sequence = ["RUNNING", "COMPLETED"]

            def list_audits_for_client(self, client_id, *, limit=20):
                state = self._state_sequence[min(self._call_count, len(self._state_sequence) - 1)]
                self._call_count += 1
                return {
                    "items": [
                        {
                            "PK": f"CLIENT#{client_id}",
                            "SK": "AUDIT#audit001",
                            "client_id": client_id,
                            "audit_id": "audit001",
                            "lifecycle_state": state,
                            "created_at": "2026-06-13T00:00:00Z",
                            "updated_at": "2026-06-13T01:57:41Z",
                            "audit_window": {
                                "start_time": "2026-06-12T17:57:41Z",
                                "end_time": "2026-06-13T01:57:41Z",
                            },
                        }
                    ],
                    "last_evaluated_key": None,
                }

        repo = _StateChangingRepo()
        service = DiscoveryListService(repository=repo)

        first_result = service.list_audits(client_id="client123")
        second_result = service.list_audits(client_id="client123")

        first_states = [item["lifecycle_state"] for item in first_result["items"]]
        second_states = [item["lifecycle_state"] for item in second_result["items"]]

        assert first_states == ["RUNNING"], (
            "first call should return RUNNING from repo"
        )
        assert second_states == ["COMPLETED"], (
            "second call must reflect updated repo state — no cache layer"
        )
        assert repo._call_count == 2, (
            "repository must be queried on every list_audits call, not served from cache"
        )

    def test_list_audits_post_finalization_shows_completed_not_running(self):
        """After finalization, audit must appear COMPLETED (or FAILED) in list_audits.

        This is a guard against any cache or read-inconsistency that could cause
        rcp audit list to show RUNNING after the lifecycle has advanced.
        """

        class _FinalizationAwareRepo:
            def list_audits_for_client(self, client_id, *, limit=20):
                return {
                    "items": [
                        {
                            "PK": f"CLIENT#{client_id}",
                            "SK": "AUDIT#audit_finalized",
                            "client_id": client_id,
                            "audit_id": "audit_finalized",
                            "lifecycle_state": "COMPLETED",  # finalization has run
                            "created_at": "2026-06-13T00:00:00Z",
                            "updated_at": "2026-06-13T01:58:00Z",
                            "audit_window": {
                                "start_time": "2026-06-12T17:57:41Z",
                                "end_time": "2026-06-13T01:57:41Z",
                            },
                        }
                    ],
                    "last_evaluated_key": None,
                }

        service = DiscoveryListService(repository=_FinalizationAwareRepo())
        result = service.list_audits(client_id="client123")

        states = [item["lifecycle_state"] for item in result["items"]]
        assert "RUNNING" not in states, (
            "completed audit must not appear as RUNNING in list_audits output"
        )
        assert "COMPLETED" in states
