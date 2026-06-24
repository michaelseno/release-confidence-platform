"""LOG-U01 through LOG-U07 — structured logging validation tests for Phase 4A.5.

These tests verify that the aggregation orchestrator and lifecycle service emit
the required structured log events with correct fields.
"""

from __future__ import annotations

import json
import logging

from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator
from release_confidence_platform.audit_lifecycle.service import (
    AuditLifecycleService,
    LifecycleTransition,
)
from release_confidence_platform.core.logging import StructuredLogger

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records: list[dict] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(json.loads(record.getMessage()))
        except (json.JSONDecodeError, TypeError):
            self.records.append({"raw": record.getMessage()})


def _make_capturing_logger(name: str = "test-logger") -> tuple[StructuredLogger, CapturingHandler]:
    handler = CapturingHandler()
    raw_logger = logging.getLogger(name)
    raw_logger.handlers.clear()
    raw_logger.addHandler(handler)
    raw_logger.setLevel(logging.DEBUG)
    return StructuredLogger(name=name, logger=raw_logger), handler


def _find_event(records: list[dict], event_type: str) -> dict | None:
    for record in records:
        if record.get("event_type") == event_type or record.get("message") == event_type:
            return record
    return None


# ---------------------------------------------------------------------------
# Minimal in-memory repository for orchestrator tests
# ---------------------------------------------------------------------------


class MemoryJobRepo:
    """Minimal repo that fails eligibility to produce a short, predictable log trace."""

    def __init__(self):
        self.items: dict = {}

    def audit_keys(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

    def execution_identity_keys(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#EXECUTION_ID"}

    def job_keys(self, client_id, audit_id, job_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#AGGJOB#{job_id}"}

    def aggregate_prefix(self, client_id, audit_id, exec_id, cfg, ver):
        return f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{ver}"

    def get_audit_metadata(self, client_id, audit_id):
        return {
            "client_id": client_id,
            "audit_id": audit_id,
            "lifecycle_state": "COMPLETED",
            "finalization": {
                "execution_count": 2,
                "zero_execution": False,
                "aggregation_job_id": "job_x",
                "aggregation_version": "v1",
            },
            "config_version": "cfg1",
            "lifecycle_history": [
                {
                    "from_state": "FINALIZING",
                    "to_state": "COMPLETED",
                    "actor": "finalization_handler",
                    "reason": "finalization_completed",
                    "timestamp": "2024-01-01T08:00:00Z",
                }
            ],
        }

    def get_audit_execution_identity(self, client_id, audit_id):
        key = (f"CLIENT#{client_id}", f"AUDIT#{audit_id}#EXECUTION_ID")
        return self.items.get(key)

    def put_audit_execution_identity_once(self, item):
        self._put(item)

    def put_job_once(self, item):
        self._put(item)

    def update_job(self, key, updates):
        k = (key["PK"], key["SK"])
        if k in self.items:
            self.items[k].update(updates)

    def get_job(self, key):
        return self.items.get((key["PK"], key["SK"]))

    def aggregate_set_exists(self, client_id, audit_id, exec_id, cfg, ver):
        return False

    def list_completed_runs(self, client_id, audit_id):
        return [
            {
                "run_id": "run1",
                "status": "COMPLETED",
                "raw_result_version": "v1",
                "raw_result_s3_key": f"raw-results/{client_id}/{audit_id}/run1.json",
                "s3_version_id": None,
            }
        ]

    def put_records_once(self, records):
        for item in records:
            self._put(item)

    def put_lineage_page_once(self, item):
        self._put(item)

    def get_lineage_page(self, key):
        return self.items.get((key["PK"], key["SK"]))

    def _put(self, item):
        key = (item["PK"], item["SK"])
        self.items[key] = item


class MemoryS3WithEvidence:
    """S3 stub that returns minimal raw evidence."""

    def read_json(self, key: str) -> dict:
        run_id = key.split("/")[-1].replace(".json", "")
        return {
            "raw_result_version": "v1",
            "client_id": key.split("/")[1],
            "audit_id": key.split("/")[2],
            "run_id": run_id,
            "results": [
                {
                    "endpoint_id": "ep1",
                    "status_code": 200,
                    "duration_ms": 100,
                    "failure_type": "none",
                    "timestamp": "2024-01-01T09:00:00Z",
                }
            ],
        }


def _run_orchestrator_and_capture(finalization_count: int = 1) -> list[dict]:
    logger, handler = _make_capturing_logger("orch-log-test")

    class AdjustedRepo(MemoryJobRepo):
        def get_audit_metadata(self, client_id, audit_id):
            return {
                "client_id": client_id,
                "audit_id": audit_id,
                "lifecycle_state": "COMPLETED",
                "finalization": {
                    "execution_count": finalization_count,
                    "zero_execution": False,
                    "aggregation_job_id": "job_x",
                    "aggregation_version": "v1",
                },
                "config_version": "cfg1",
                "lifecycle_history": [
                    {
                        "from_state": "FINALIZING",
                        "to_state": "COMPLETED",
                        "actor": "finalization_handler",
                        "reason": "finalization_completed",
                        "timestamp": "2024-01-01T08:00:00Z",
                    }
                ],
            }

    orchestrator = AggregationOrchestrator(
        repository=AdjustedRepo(),
        s3_storage=MemoryS3WithEvidence(),
        logger=logger,
    )
    orchestrator.run(
        {
            "client_id": "client1",
            "audit_id": "audit1",
            "aggregation_version": "v1",
            "aggregation_job_id": "job1",
        }
    )
    return handler.records


# ---------------------------------------------------------------------------
# LOG-U01: aggregation_job_claimed event
# ---------------------------------------------------------------------------


def test_log_u01_aggregation_job_claimed():
    records = _run_orchestrator_and_capture()
    event = _find_event(records, "aggregation_job_claimed")
    assert event is not None, "aggregation_job_claimed event not found"
    assert "audit_id" in event
    assert "client_id" in event
    assert event.get("audit_id") == "client1" or event.get("client_id") == "client1"
    # Either client_id or audit_id must be present
    assert event.get("aggregation_job_id") is not None or event.get("audit_id") is not None


# ---------------------------------------------------------------------------
# LOG-U02: aggregation_eligibility_evaluated event
# ---------------------------------------------------------------------------


def test_log_u02_aggregation_eligibility_evaluated():
    records = _run_orchestrator_and_capture()
    event = _find_event(records, "aggregation_eligibility_evaluated")
    assert event is not None, "aggregation_eligibility_evaluated event not found"
    assert "result" in event
    assert event["result"] in ("eligible", "ineligible")


# ---------------------------------------------------------------------------
# LOG-U03: aggregation_integrity_gate_evaluated event
# ---------------------------------------------------------------------------


def test_log_u03_integrity_gate_evaluated():
    records = _run_orchestrator_and_capture(finalization_count=1)
    event = _find_event(records, "aggregation_integrity_gate_evaluated")
    assert event is not None, "aggregation_integrity_gate_evaluated event not found"
    assert "result" in event
    assert "expected_count" in event
    assert "observed_count" in event


# ---------------------------------------------------------------------------
# LOG-U04: aggregation_set_completed event
# ---------------------------------------------------------------------------


def test_log_u04_aggregation_set_completed():
    records = _run_orchestrator_and_capture(finalization_count=1)
    event = _find_event(records, "aggregation_set_completed")
    assert event is not None, "aggregation_set_completed event not found"
    assert "aggregate_record_count" in event


# ---------------------------------------------------------------------------
# LOG-U05: aggregation_job_failed event on failure
# ---------------------------------------------------------------------------


def test_log_u05_aggregation_job_failed():
    logger, handler = _make_capturing_logger("orch-fail-test")

    class FailingRepo(MemoryJobRepo):
        def get_audit_metadata(self, client_id, audit_id):
            return {
                "client_id": client_id,
                "audit_id": audit_id,
                "lifecycle_state": "FINALIZING",
                # Missing execution_count to force eligibility failure
                "finalization": {},
                "config_version": None,
            }


    orchestrator = AggregationOrchestrator(
        repository=FailingRepo(),
        s3_storage=MemoryS3WithEvidence(),
        logger=logger,
    )
    orchestrator.run(
        {
            "client_id": "client1",
            "audit_id": "audit1",
            "aggregation_version": "v1",
            "aggregation_job_id": "job_fail",
        }
    )
    records = handler.records
    # Either job_failed or ineligible event must be present
    failed_event = _find_event(records, "aggregation_job_failed")
    ineligible_event = _find_event(records, "aggregation_eligibility_evaluated")
    assert failed_event is not None or (
        ineligible_event is not None and ineligible_event.get("result") == "ineligible"
    ), "No failure or ineligible event found"
    if failed_event:
        assert "failure_category" in failed_event or "reason_code" in failed_event


# ---------------------------------------------------------------------------
# LOG-U06: lifecycle_transition event
# ---------------------------------------------------------------------------


def test_log_u06_lifecycle_transition():
    logger, handler = _make_capturing_logger("lifecycle-log-test")

    class MockLifecycleRepo:
        def append_lifecycle_transition(self, *, client_id, audit_id,
                                        expected_current_state, next_state, history_entry):
            pass  # No-op for testing

    svc = AuditLifecycleService(repository=MockLifecycleRepo(), logger=logger)
    svc.transition(
        LifecycleTransition(
            client_id="client1",
            audit_id="audit1",
            expected_current_state="SCHEDULED",
            next_state="RUNNING",
            reason="window_opened",
            actor="scheduler",
        )
    )
    records = handler.records
    event = _find_event(records, "lifecycle_transition")
    assert event is not None, "lifecycle_transition event not found"
    assert event.get("from_state") == "SCHEDULED"
    assert event.get("to_state") == "RUNNING"
    assert event.get("actor") == "scheduler"
    assert event.get("reason") == "window_opened"


# ---------------------------------------------------------------------------
# LOG-U07: No canary value in any log event output
# ---------------------------------------------------------------------------


def test_log_u07_no_sensitive_content_in_logs():
    _CANARY = "CANARY_LOG_SENSITIVE_DO_NOT_EXPOSE_99999"
    logger, handler = _make_capturing_logger("canary-log-test")

    class SensitiveDataRepo(MemoryJobRepo):
        def get_audit_metadata(self, client_id, audit_id):
            return {
                "client_id": client_id,
                "audit_id": audit_id,
                "lifecycle_state": "COMPLETED",
                "finalization": {
                    "execution_count": 1,
                    "zero_execution": False,
                    "aggregation_version": "v1",
                },
                "config_version": "cfg1",
                "lifecycle_history": [
                    {
                        "from_state": "FINALIZING",
                        "to_state": "COMPLETED",
                        "actor": "finalization_handler",
                        "reason": "finalization_completed",
                        "timestamp": "2024-01-01T08:00:00Z",
                    }
                ],
                # Sensitive data that must not leak into logs
                "raw_endpoint_url": f"https://api.example.com/{_CANARY}",
                "api_key": _CANARY,
            }

    orchestrator = AggregationOrchestrator(
        repository=SensitiveDataRepo(),
        s3_storage=MemoryS3WithEvidence(),
        logger=logger,
    )
    orchestrator.run(
        {
            "client_id": "client1",
            "audit_id": "audit1",
            "aggregation_version": "v1",
            "aggregation_job_id": "job_canary",
        }
    )
    for record in handler.records:
        record_str = json.dumps(record)
        assert _CANARY not in record_str, f"Canary found in log record: {record_str[:200]}"
