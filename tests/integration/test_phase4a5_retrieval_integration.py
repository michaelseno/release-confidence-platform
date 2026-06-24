"""Phase 4A.5 integration tests.

RET-I01, RET-I02, RET-I03 — retrieval against fixture aggregation state.
LOG-I01 — end-to-end aggregation emits complete structured log timeline.
"""

from __future__ import annotations

import json
import logging

from release_confidence_platform.aggregation.orchestrator import AggregationOrchestrator
from release_confidence_platform.core.logging import StructuredLogger
from release_confidence_platform.retrieval.dtypes import RetrievalFilter
from release_confidence_platform.retrieval.service import RetrievalService

# ---------------------------------------------------------------------------
# Shared in-memory repository for integration tests
# ---------------------------------------------------------------------------


class MemoryRepo:
    """Full-fidelity in-memory repository compatible with both orchestrator and retrieval."""

    def __init__(self, audit, runs, s3_objects):
        self.audit = audit
        self.runs = runs
        self.s3_objects = s3_objects
        self.items: dict = {}
        self._mutations: list[str] = []  # Track all write operations for RET-I03

    # AggregationRepository interface
    def audit_keys(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

    def execution_identity_keys(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#EXECUTION_ID"}

    def job_keys(self, client_id, audit_id, job_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#AGGJOB#{job_id}"}

    def aggregate_prefix(self, client_id, audit_id, exec_id, cfg, ver):
        return f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{ver}"

    def get_audit_metadata(self, client_id, audit_id):
        return self.audit

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
        pk = f"CLIENT#{client_id}"
        prefix = self.aggregate_prefix(client_id, audit_id, exec_id, cfg, ver)
        return (pk, f"{prefix}#SET") in self.items

    def list_completed_runs(self, client_id, audit_id):
        return self.runs

    def put_records_once(self, records):
        from release_confidence_platform.aggregation.repository import (
            ConditionalWriteError,  # noqa: PLC0415
        )

        keys = [(item["PK"], item["SK"]) for item in records]
        if any(key in self.items for key in keys):
            raise ConditionalWriteError()
        for item in records:
            self._put(item)

    def put_lineage_page_once(self, item):
        self._put(item)

    def get_lineage_page(self, key):
        return self.items.get((key["PK"], key["SK"]))

    def _put(self, item):
        from release_confidence_platform.aggregation.repository import (
            ConditionalWriteError,  # noqa: PLC0415
        )

        key = (item["PK"], item["SK"])
        if key in self.items:
            raise ConditionalWriteError()
        self.items[key] = item

    # RetrievalRepository interface
    def get_audit_metadata_for_retrieval(self, client_id, audit_id):
        return self.audit

    def list_aggregation_jobs(self, client_id, audit_id):
        return [
            v for k, v in self.items.items()
            if f"AUDIT#{audit_id}#AGGJOB#" in k[1]
        ]

    def get_latest_aggregation_job(self, client_id, audit_id):
        jobs = self.list_aggregation_jobs(client_id, audit_id)
        if not jobs:
            return None
        return max(jobs, key=lambda j: j.get("started_at") or j.get("SK") or "")

    def list_aggregate_records(self, client_id, audit_id):
        prefix = f"AUDIT#{audit_id}#EXEC#"
        return [v for k, v in self.items.items() if k[1].startswith(prefix)]

    def get_aggregate_set_completion(self, client_id, audit_id):
        for item in self.list_aggregate_records(client_id, audit_id):
            if item.get("aggregate_type") == "aggregate_set_completion":
                return item
        return None

    def list_lifecycle_history(self, client_id, audit_id):
        prefix = f"AUDIT#{audit_id}#LIFECYCLE#"
        return [v for k, v in self.items.items() if k[1].startswith(prefix)]

    def list_all_audit_items(self, client_id, audit_id):
        prefix = f"AUDIT#{audit_id}#"
        return [v for k, v in self.items.items() if k[1].startswith(prefix)]

    def list_lineage_manifests(self, client_id, audit_id):
        return [r for r in self.list_aggregate_records(client_id, audit_id)
                if r.get("record_kind") == "lineage_manifest"]

    def list_lineage_manifest_pages(self, client_id, audit_id):
        return [r for r in self.list_aggregate_records(client_id, audit_id)
                if r.get("record_kind") == "lineage_manifest_page"]

    def list_completed_runs_for_retrieval(self, client_id, audit_id):
        return self.runs


class MemoryS3:
    def __init__(self, client_id, audit_id):
        self.client_id = client_id
        self.audit_id = audit_id

    def read_json(self, key):
        run_id = key.split("/")[-1].replace(".json", "")
        return {
            "raw_result_version": "v1",
            "client_id": self.client_id,
            "audit_id": self.audit_id,
            "run_id": run_id,
            "results": [
                {
                    "endpoint_id": "ep1",
                    "status_code": 200,
                    "duration_ms": 150,
                    "failure_type": "none",
                    "timestamp": "2024-01-01T09:00:00Z",
                },
            ],
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


CLIENT_ID = "integration_client"
AUDIT_ID = "integration_audit"
AGG_VERSION = "v1"


def _build_audit():
    return {
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "lifecycle_state": "COMPLETED",
        "finalization": {
            "execution_count": 2,
            "zero_execution": False,
            "aggregation_version": AGG_VERSION,
        },
        "config_version": "cfg_integration",
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


def _build_runs():
    return [
        {
            "run_id": "run_a",
            "status": "COMPLETED",
            "raw_result_version": "v1",
            "raw_result_s3_key": f"raw-results/{CLIENT_ID}/{AUDIT_ID}/run_a.json",
            "s3_version_id": None,
        },
        {
            "run_id": "run_b",
            "status": "COMPLETED",
            "raw_result_version": "v1",
            "raw_result_s3_key": f"raw-results/{CLIENT_ID}/{AUDIT_ID}/run_b.json",
            "s3_version_id": None,
        },
    ]


def _build_repo():
    return MemoryRepo(
        audit=_build_audit(),
        runs=_build_runs(),
        s3_objects={},
    )


def _run_aggregation(repo):
    orchestrator = AggregationOrchestrator(
        repository=repo,
        s3_storage=MemoryS3(CLIENT_ID, AUDIT_ID),
    )
    return orchestrator.run(
        {
            "client_id": CLIENT_ID,
            "audit_id": AUDIT_ID,
            "aggregation_version": AGG_VERSION,
            "aggregation_job_id": "job_integration",
        }
    )


# ---------------------------------------------------------------------------
# RET-I01: Retrieval against known fixture aggregation state
# ---------------------------------------------------------------------------


def test_ret_i01_retrieval_against_fixture():
    repo = _build_repo()
    result = _run_aggregation(repo)
    assert result["status"] == "COMPLETED"

    # Build retrieval service on the same in-memory state
    svc = RetrievalService(repo)
    filters = RetrievalFilter(client_id=CLIENT_ID, audit_id=AUDIT_ID)

    # aggregation-results
    dto = svc.get_aggregation_results(filters)
    assert dto.total_count > 0
    assert dto.completion_status == "COMPLETE"

    # aggregation-metadata
    meta = svc.get_aggregation_metadata(filters)
    assert meta.status == "COMPLETED"
    assert meta.job_id == "job_integration"
    assert meta.source_run_count == 2

    # aggregation-version
    ver = svc.get_aggregation_version(filters)
    assert ver.aggregation_version == AGG_VERSION

    # aggregation-generation-status
    gen = svc.get_aggregation_generation_status(filters)
    assert gen.completion_marker_present is True
    assert gen.completeness_status == "COMPLETE"

    # evidence-references
    evref = svc.get_evidence_references(filters)
    assert evref.source_ref_count > 0
    # No raw S3 keys
    for ref in evref.source_refs:
        if ref.s3_key_ref is not None:
            assert not ref.s3_key_ref.startswith("raw-results/")

    # failure-summaries
    fails = svc.get_failure_summaries(filters)
    assert isinstance(fails.classification_counts, tuple)

    # processing-timeline
    proc = svc.get_processing_timeline(filters)
    assert proc.started_at is not None


# ---------------------------------------------------------------------------
# RET-I02: Retrieval for failed aggregation job returns correct failure metadata
# ---------------------------------------------------------------------------


def test_ret_i02_retrieval_for_failed_job():
    """Force a failure by having mismatched execution_count (3 expected, 2 runs)."""
    audit = {
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "lifecycle_state": "COMPLETED",
        "finalization": {
            "execution_count": 3,  # Mismatch: 3 expected but only 2 runs
            "zero_execution": False,
            "aggregation_version": AGG_VERSION,
        },
        "config_version": "cfg_integration",
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
    repo = MemoryRepo(audit=audit, runs=_build_runs(), s3_objects={})
    result = _run_aggregation(repo)
    # Should be ineligible or failed
    assert result["status"] in ("INELIGIBLE", "FAILED", "ineligible", "failed") or \
           result.get("reason_code") is not None

    svc = RetrievalService(repo)
    filters = RetrievalFilter(client_id=CLIENT_ID, audit_id=AUDIT_ID)
    meta = svc.get_aggregation_metadata(filters)
    # No aggregate_set_completion should exist
    gen = svc.get_aggregation_generation_status(filters)
    assert gen.completion_marker_present is False or gen.completeness_status != "COMPLETE" or \
           meta.status in (None, "INELIGIBLE", "FAILED", "ineligible", "failed")


# ---------------------------------------------------------------------------
# RET-I03: Retrieval commands produce no mutations (state before == state after)
# ---------------------------------------------------------------------------


def test_ret_i03_retrieval_does_not_mutate():
    repo = _build_repo()
    _run_aggregation(repo)

    # Snapshot state before retrieval
    state_before = dict(repo.items)

    svc = RetrievalService(repo)
    filters = RetrievalFilter(client_id=CLIENT_ID, audit_id=AUDIT_ID)

    # Run all 15 retrieval commands
    svc.get_aggregation_results(filters)
    svc.get_aggregation_metadata(filters)
    svc.get_aggregation_lineage(filters)
    svc.get_aggregation_status(filters)
    svc.get_orchestration_timeline(filters)
    svc.get_lifecycle_transitions(filters)
    svc.get_execution_summary(filters)
    svc.get_audit_event_timeline(filters)
    svc.get_engineering_logs(filters)
    svc.get_retry_history(filters)
    svc.get_aggregation_generation_status(filters)
    svc.get_aggregation_version(filters)
    svc.get_evidence_references(filters)
    svc.get_failure_summaries(filters)
    svc.get_processing_timeline(filters)

    # State after must be identical — no mutations
    state_after = dict(repo.items)
    assert set(state_before.keys()) == set(state_after.keys()), \
        "Retrieval commands added or removed items from storage"
    for key in state_before:
        assert state_before[key] == state_after[key], \
            f"Retrieval mutated item at key {key}"


# ---------------------------------------------------------------------------
# LOG-I01: End-to-end aggregation emits complete structured log timeline
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


def test_log_i01_end_to_end_log_timeline():
    handler = CapturingHandler()
    raw_logger = logging.getLogger("log-i01-test")
    raw_logger.handlers.clear()
    raw_logger.addHandler(handler)
    raw_logger.setLevel(logging.DEBUG)
    logger = StructuredLogger(name="log-i01-test", logger=raw_logger)

    repo = _build_repo()
    orchestrator = AggregationOrchestrator(
        repository=repo,
        s3_storage=MemoryS3(CLIENT_ID, AUDIT_ID),
        logger=logger,
    )
    result = orchestrator.run(
        {
            "client_id": CLIENT_ID,
            "audit_id": AUDIT_ID,
            "aggregation_version": AGG_VERSION,
            "aggregation_job_id": "job_log_i01",
        }
    )
    assert result["status"] == "COMPLETED"

    event_types = {r.get("event_type") for r in handler.records}

    required_events = {
        "aggregation_job_claimed",
        "aggregation_eligibility_evaluated",
        "aggregation_integrity_gate_evaluated",
        "aggregation_manifest_write_started",
        "aggregation_set_completed",
    }
    missing = required_events - event_types
    assert not missing, f"Missing required log events: {missing}"

    # Verify chronological ordering of key events
    claimed = next(
        (r for r in handler.records if r.get("event_type") == "aggregation_job_claimed"), None
    )
    completed = next(
        (r for r in handler.records if r.get("event_type") == "aggregation_set_completed"), None
    )
    assert claimed is not None
    assert completed is not None
    if claimed.get("timestamp") and completed.get("timestamp"):
        assert claimed["timestamp"] <= completed["timestamp"]
