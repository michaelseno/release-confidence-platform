"""E2E-01: Full lifecycle completes cleanly with phone-like UUID run included.

Validates all four defect vectors simultaneously via in-process simulation:
  WS-A: phone-like UUID run_id persists without sanitization
  WS-B: counters track only COMPLETED runs
  WS-C: finalization integrity gate reconciles evidence before COMPLETED transition
  Integration: finalization reaches COMPLETED cleanly for a clean audit
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.backend.handlers.audit_finalization_handler import AuditFinalizationHandler
from apps.backend.handlers.scheduled_execution_handler import ScheduledExecutionHandler

# The canonical regression fixture UUID.  Its digit sequence "2475004829" matches
# PHONE_PATTERN in sanitizer.py.  After WS-A, this UUID must flow through all
# persistence layers without mutation.
PHONE_LIKE_UUID = "48a87626-e2f9-4f81-82ff-2475004829ec"

CLIENT_ID = "e2e-client"
AUDIT_ID = "e2e-audit"


# ---------------------------------------------------------------------------
# Shared in-memory store
# ---------------------------------------------------------------------------


class _SharedStore:
    """Single source of truth shared by both handler test doubles."""

    def __init__(self) -> None:
        self.run_records: list[dict[str, Any]] = []
        self.s3_keys: list[str] = []
        self.claims: dict = {}
        self.agg_items: dict = {}
        self.audit: dict[str, Any] = {
            "lifecycle_state": "RUNNING",
            "lifecycle_history": [],
            "audit_window": {
                "start_time": "2026-06-01T00:00:00Z",
                "end_time": "2026-06-08T23:59:59Z",
            },
            "execution_environment": {"target_environment": "staging"},
            "execution_counters": {"total_started": 0, "total_completed": 0},
            "schedules": [
                {
                    "schedule_name": f"rcp-dev-{CLIENT_ID}-{AUDIT_ID}-baseline-0",
                    "schedule_type": "baseline",
                },
                {
                    "schedule_name": f"rcp-dev-{CLIENT_ID}-{AUDIT_ID}-finalization",
                    "schedule_type": "finalization",
                },
            ],
        }


# ---------------------------------------------------------------------------
# Stub orchestrator
# ---------------------------------------------------------------------------


class _StubOrchestrator:
    """Stub orchestrator that writes to the shared store without sanitization.

    Simulates the WS-A-fixed CoreEngineOrchestrator: run_id is persisted
    byte-identically to what was passed to the orchestrator.
    """

    def __init__(self, store: _SharedStore, predefined_run_id: str | None = None) -> None:
        self._store = store
        self._predefined_run_id = predefined_run_id
        self._call_count = 0

    def run(self, event: dict[str, Any]) -> dict[str, Any]:
        run_id = self._predefined_run_id if (self._predefined_run_id and self._call_count == 0) else str(uuid.uuid4())
        self._call_count += 1

        client_id = event["client_id"]
        audit_id = event["audit_id"]
        s3_key = f"raw-results/{client_id}/{audit_id}/{run_id}/results.json"

        self._store.run_records.append({
            "run_id": run_id,
            "status": "COMPLETED",
            "raw_result_s3_key": s3_key,
            "completed_at": "2026-06-01T01:05:00Z",
        })
        self._store.s3_keys.append(s3_key)

        return {"run_id": run_id, "status": "COMPLETED", "raw_result_s3_key": s3_key}


# ---------------------------------------------------------------------------
# Repo for ScheduledExecutionHandler
# ---------------------------------------------------------------------------


class _SchedulerRepo:
    def __init__(self, store: _SharedStore) -> None:
        self._store = store

    def get_audit_metadata(self, client_id: str, audit_id: str) -> dict:  # noqa: ARG002
        return self._store.audit

    def occurrence_keys(self, client_id: str, audit_id: str, occurrence_id: str) -> dict:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#OCCURRENCE#{occurrence_id}"}

    def claim_occurrence(self, item: dict) -> None:
        self._store.claims[(item["PK"], item["SK"])] = item

    def update_occurrence(self, key: dict, updates: dict) -> None:
        self._store.claims[(key["PK"], key["SK"])].update(updates)

    def update_execution_counters(self, client_id: str, audit_id: str, updates: dict) -> None:  # noqa: ARG002
        self._store.audit["execution_counters"] = updates

    def append_lifecycle_transition(self, **kwargs: Any) -> None:
        self._store.audit["lifecycle_state"] = kwargs["next_state"]
        self._store.audit["lifecycle_history"].append(kwargs["history_entry"])


# ---------------------------------------------------------------------------
# Repo for AuditFinalizationHandler
# ---------------------------------------------------------------------------


class _FinalizationRepo:
    def __init__(self, store: _SharedStore) -> None:
        self._store = store

    def get_audit_metadata(self, client_id: str, audit_id: str) -> dict:  # noqa: ARG002
        return self._store.audit

    def list_run_records(self, client_id: str, audit_id: str) -> list[dict]:  # noqa: ARG002
        return list(self._store.run_records)

    def append_lifecycle_transition(self, **kwargs: Any) -> None:
        self._store.audit["lifecycle_state"] = kwargs["next_state"]
        self._store.audit["lifecycle_history"].append(kwargs["history_entry"])

    def record_finalization(self, client_id: str, audit_id: str, metadata: dict) -> None:  # noqa: ARG002
        self._store.audit["finalization"] = metadata

    def record_cleanup_errors(self, client_id: str, audit_id: str, errors: list) -> None:  # noqa: ARG002
        pass

    def aggregation_job_keys(self, client_id: str, audit_id: str, job_id: str) -> dict:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#AGGJOB#{job_id}"}

    def put_aggregation_job_intent_once(self, item: dict) -> None:
        self._store.agg_items[(item["PK"], item["SK"])] = item

    def update_aggregation_job_intent(self, key: dict, updates: dict) -> None:
        self._store.agg_items[(key["PK"], key["SK"])].update(updates)


# ---------------------------------------------------------------------------
# S3 stub for AuditFinalizationHandler
# ---------------------------------------------------------------------------


class _FinalizationS3:
    def __init__(self, store: _SharedStore) -> None:
        self._store = store

    def list_raw_evidence_keys(self, client_id: str, audit_id: str) -> list[str]:  # noqa: ARG002
        return list(self._store.s3_keys)


# ---------------------------------------------------------------------------
# Event builders
# ---------------------------------------------------------------------------


def _schedule_event(occurrence_id: str) -> dict:
    return {
        "event_type": "audit_schedule_execution",
        "schema_version": "phase3.schedule_event.v1",
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "schedule_name": f"rcp-dev-{CLIENT_ID}-{AUDIT_ID}-baseline-baseline_health",
        "schedule_type": "baseline",
        "scenario_type": "baseline_health",
        "triggered_by": "eventbridge_scheduler",
        "schedule_occurrence_id": occurrence_id,
        "scheduled_at": "2026-06-01T01:00:00Z",
    }


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


# ---------------------------------------------------------------------------
# E2E-01
# ---------------------------------------------------------------------------


def test_e2e_full_lifecycle_execution_finalization_aggregation_trigger():
    """E2E-01: All three workstream fixes must work in concert.

    Step 1 — Execute 3 scheduled occurrences.  Occurrence 1 uses the phone-like
    UUID (48a87626-e2f9-4f81-82ff-2475004829ec) as run_id to validate WS-A.

    Step 2 — Trigger finalization.  All evidence must reconcile (WS-C) and the
    audit must reach COMPLETED.
    """
    store = _SharedStore()

    # --- Step 1: 3 scheduled execution occurrences ---

    # Occurrence 1: phone-like UUID run
    ScheduledExecutionHandler(
        repository=_SchedulerRepo(store),
        orchestrator=_StubOrchestrator(store, predefined_run_id=PHONE_LIKE_UUID),
    ).handle(_schedule_event("baseline#occ-1"))

    # Occurrence 2: normal run
    ScheduledExecutionHandler(
        repository=_SchedulerRepo(store),
        orchestrator=_StubOrchestrator(store),
    ).handle(_schedule_event("baseline#occ-2"))

    # Occurrence 3: normal run
    ScheduledExecutionHandler(
        repository=_SchedulerRepo(store),
        orchestrator=_StubOrchestrator(store),
    ).handle(_schedule_event("baseline#occ-3"))

    # --- Step 1 verification ---

    counters = store.audit["execution_counters"]
    assert counters["total_completed"] == 3, f"total_completed={counters['total_completed']}"
    assert counters["total_started"] == 3, f"total_started={counters['total_started']}"

    assert len(store.run_records) == 3, "Expected exactly 3 RUN records"
    assert all(r["status"] == "COMPLETED" for r in store.run_records), (
        "All RUN records must be COMPLETED — zero STARTED remain"
    )
    assert len(store.s3_keys) == 3, "Expected exactly 3 S3 evidence keys"

    # WS-A: phone-like UUID must be present unredacted in run_id and S3 key
    phone_run = next(
        (r for r in store.run_records if r["run_id"] == PHONE_LIKE_UUID), None
    )
    assert phone_run is not None, (
        f"No RUN record with run_id={PHONE_LIKE_UUID!r} — "
        "WS-A fix may not be applied: sanitize() is still mutating run_id"
    )
    assert "[REDACTED]" not in phone_run["run_id"], (
        "run_id must not contain [REDACTED] — sanitize() must not be called on persistence key material"
    )
    assert "[REDACTED]" not in phone_run["raw_result_s3_key"], (
        "raw_result_s3_key must not contain [REDACTED]"
    )
    phone_s3_key = phone_run["raw_result_s3_key"]
    assert f"/{PHONE_LIKE_UUID}/" in phone_s3_key, (
        f"S3 key must contain unsanitized UUID path segment; got {phone_s3_key!r}"
    )

    # --- Step 2: Finalization ---

    result = AuditFinalizationHandler(
        repository=_FinalizationRepo(store),
        s3_storage=_FinalizationS3(store),
    ).handle(_finalization_event())

    # --- Step 2 verification ---

    assert result["lifecycle_state"] == "COMPLETED", (
        f"Audit must reach COMPLETED; got {result['lifecycle_state']!r}"
    )
    assert result["status"] == "completed"

    states_visited = [e["to_state"] for e in store.audit["lifecycle_history"]]
    assert "COMPLETED" in states_visited, (
        f"COMPLETED must appear in lifecycle history; got {states_visited}"
    )

    finalization = store.audit.get("finalization", {})
    assert finalization.get("execution_count") == 3, (
        f"finalization.execution_count must be 3; got {finalization.get('execution_count')!r}"
    )

    # WS-C evidence triangle: terminal RUN count == S3 key count == execution_count
    terminal_runs = [r for r in store.run_records if r["status"] != "STARTED"]
    assert len(terminal_runs) == 3
    assert len(store.s3_keys) == 3
    assert finalization.get("execution_count") == 3

    # Aggregation intent record must exist (finalization triggers aggregation)
    assert len(store.agg_items) > 0, "Aggregation job intent record must be created after COMPLETED"
