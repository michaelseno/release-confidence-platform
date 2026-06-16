"""RET-U01 through RET-U15 — retrieval command correctness unit tests."""

from __future__ import annotations

from release_confidence_platform.retrieval.dtypes import (
    AggregationGenerationStatusDTO,
    AggregationLineageDTO,
    AggregationMetadataDTO,
    AggregationResultsDTO,
    AggregationStatusDTO,
    AggregationVersionDTO,
    AuditEventTimelineDTO,
    EngineeringLogsDTO,
    EvidenceReferencesDTO,
    ExecutionSummaryDTO,
    FailureSummariesDTO,
    LifecycleTransitionsDTO,
    OrchestrationTimelineDTO,
    ProcessingTimelineDTO,
    RetrievalFilter,
    RetryHistoryDTO,
)
from release_confidence_platform.retrieval.service import RetrievalService

# ---------------------------------------------------------------------------
# Mock repository
# ---------------------------------------------------------------------------


class MockRepo:
    def __init__(self, *, audit_metadata=None, jobs=None, aggregate_records=None,
                 lifecycle_history=None, runs=None):
        self._audit_metadata = audit_metadata or {}
        self._jobs = jobs or []
        self._aggregate_records = aggregate_records or []
        self._lifecycle_history = lifecycle_history or []
        self._runs = runs or []

    def get_audit_metadata(self, client_id, audit_id):
        return self._audit_metadata

    def list_aggregation_jobs(self, client_id, audit_id):
        return self._jobs

    def get_latest_aggregation_job(self, client_id, audit_id):
        if not self._jobs:
            return None
        return max(self._jobs, key=lambda j: j.get("started_at") or j.get("SK") or "")

    def list_aggregate_records(self, client_id, audit_id):
        return self._aggregate_records

    def get_aggregate_set_completion(self, client_id, audit_id):
        for r in self._aggregate_records:
            if r.get("aggregate_type") == "aggregate_set_completion":
                return r
        return None

    def list_lifecycle_history(self, client_id, audit_id):
        return self._lifecycle_history

    def list_all_audit_items(self, client_id, audit_id):
        return self._aggregate_records + self._jobs + self._lifecycle_history

    def list_lineage_manifests(self, client_id, audit_id):
        return [r for r in self._aggregate_records if r.get("record_kind") == "lineage_manifest"]

    def list_completed_runs(self, client_id, audit_id):
        return self._runs


_FILTERS = RetrievalFilter(client_id="client1", audit_id="audit1")

_COMPLETION = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#SET",
    "record_kind": "aggregate_set_completion",
    "aggregate_type": "aggregate_set_completion",
    "client_id": "client1",
    "audit_id": "audit1",
    "audit_execution_id": "exec1",
    "config_version": "cfg1",
    "aggregation_version": "v1",
    "aggregation_job_id": "job1",
    "completion_status": "COMPLETE",
    "created_at": "2024-01-01T10:00:00Z",
    "expected_execution_count": 5,
    "source_run_count": 5,
    "source_raw_result_count": 15,
    "aggregate_record_count": 4,
    "endpoint_aggregate_count": 2,
    "manifest_count": 3,
    "audit_lineage_manifest_ref": {"PK": "CLIENT#client1"},
    "aggregate_set_hash": "abc123",
}

_AUDIT_AGGREGATE = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#AUDIT",
    "record_kind": "aggregate",
    "aggregate_type": "audit",
    "client_id": "client1",
    "audit_id": "audit1",
    "aggregation_version": "v1",
    "created_at": "2024-01-01T10:00:00Z",
    "request_counts": {"total": 15, "successful": 12, "failed": 2, "skipped": 1},
}

_ENDPOINT_AGGREGATE = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#ENDPOINT#ep1",
    "record_kind": "aggregate",
    "aggregate_type": "endpoint",
    "client_id": "client1",
    "audit_id": "audit1",
    "endpoint_id": "ep1",
    "aggregation_version": "v1",
    "execution_count": 5,
    "created_at": "2024-01-01T10:00:00Z",
}

_FAILURE_AGG = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#FAILURE_CLASSIFICATION",
    "record_kind": "aggregate",
    "aggregate_type": "failure_classification",
    "scope": "audit",
    "classification_counts": {"network_failure": 1, "timeout": 1},
}

_LINEAGE_MANIFEST = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#LINEAGE#audit",
    "record_kind": "lineage_manifest",
    "aggregate_type": "lineage_manifest",
    "client_id": "client1",
    "audit_id": "audit1",
    "audit_execution_id": "exec1",
    "aggregation_version": "v1",
    "aggregation_job_id": "job1",
    "aggregation_timestamp": "2024-01-01T10:00:00Z",
    "source_ref_count": 15,
    "manifest_hash": "manifest_hash_abc",
    "lineage_manifest_ref": {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#LINEAGE#audit",
    },
    "source_refs": [
        {
            "run_id": "run1",
            "result_index": 0,
            "endpoint_id": "ep1",
            "result_timestamp": "2024-01-01T09:00:00Z",
            "raw_result_s3_key": "raw-results/client1/audit1/run1.json",
        },
    ],
}

_JOB = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#AGGJOB#job1",
    "client_id": "client1",
    "audit_id": "audit1",
    "aggregation_job_id": "job1",
    "aggregation_version": "v1",
    "audit_execution_id": "exec1",
    "config_version": "cfg1",
    "status": "COMPLETED",
    "reason_code": None,
    "failure_category": None,
    "started_at": "2024-01-01T09:55:00Z",
    "completed_at": "2024-01-01T10:00:00Z",
    "source_run_count": 5,
    "source_raw_result_count": 15,
}

_LIFECYCLE_ITEM = {
    "from_state": "SCHEDULED",
    "to_state": "RUNNING",
    "actor": "scheduler",
    "reason": "window_opened",
    "timestamp": "2024-01-01T08:00:00Z",
}


def _make_svc(**kwargs):
    return RetrievalService(MockRepo(**kwargs))


# ---------------------------------------------------------------------------
# RET-U01: aggregation-results
# ---------------------------------------------------------------------------


def test_ret_u01_aggregation_results():
    svc = _make_svc(
        aggregate_records=[_COMPLETION, _AUDIT_AGGREGATE, _ENDPOINT_AGGREGATE, _FAILURE_AGG],
    )
    dto = svc.get_aggregation_results(_FILTERS)
    assert isinstance(dto, AggregationResultsDTO)
    assert dto.total_count >= 1
    assert dto.completion_status == "COMPLETE"
    assert dto.endpoint_count >= 1
    # No raw bodies in any record data
    for record in dto.records:
        field_keys = {k for k, _v in record.data}
        assert "request_body" not in field_keys
        assert "response_body" not in field_keys


# ---------------------------------------------------------------------------
# RET-U02: aggregation-metadata
# ---------------------------------------------------------------------------


def test_ret_u02_aggregation_metadata():
    svc = _make_svc(jobs=[_JOB])
    dto = svc.get_aggregation_metadata(_FILTERS)
    assert isinstance(dto, AggregationMetadataDTO)
    assert dto.job_id == "job1"
    assert dto.status == "COMPLETED"
    assert dto.source_run_count == 5
    assert dto.source_raw_result_count == 15
    assert dto.aggregation_version == "v1"


def test_ret_u02_aggregation_metadata_empty():
    svc = _make_svc()
    dto = svc.get_aggregation_metadata(_FILTERS)
    assert dto.job_id is None
    assert dto.status is None


# ---------------------------------------------------------------------------
# RET-U03: aggregation-lineage
# ---------------------------------------------------------------------------


def test_ret_u03_aggregation_lineage():
    svc = _make_svc(aggregate_records=[_LINEAGE_MANIFEST])
    dto = svc.get_aggregation_lineage(_FILTERS)
    assert isinstance(dto, AggregationLineageDTO)
    assert dto.source_ref_count == 15
    assert dto.manifest_hash == "manifest_hash_abc"
    assert dto.aggregation_version == "v1"


# ---------------------------------------------------------------------------
# RET-U04: aggregation-status
# ---------------------------------------------------------------------------


def test_ret_u04_aggregation_status():
    svc = _make_svc(jobs=[_JOB])
    dto = svc.get_aggregation_status(_FILTERS)
    assert isinstance(dto, AggregationStatusDTO)
    assert dto.status == "COMPLETED"
    assert dto.job_id == "job1"
    assert dto.aggregation_version == "v1"


# ---------------------------------------------------------------------------
# RET-U05: orchestration-timeline
# ---------------------------------------------------------------------------


def test_ret_u05_orchestration_timeline():
    svc = _make_svc(jobs=[_JOB])
    dto = svc.get_orchestration_timeline(_FILTERS)
    assert isinstance(dto, OrchestrationTimelineDTO)
    assert dto.job_count == 1
    assert len(dto.events) >= 2  # started + completed
    timestamps = [e.timestamp for e in dto.events]
    assert sorted(timestamps) == timestamps  # ascending order


# ---------------------------------------------------------------------------
# RET-U06: lifecycle-transitions
# ---------------------------------------------------------------------------


def test_ret_u06_lifecycle_transitions():
    svc = _make_svc(lifecycle_history=[_LIFECYCLE_ITEM])
    dto = svc.get_lifecycle_transitions(_FILTERS)
    assert isinstance(dto, LifecycleTransitionsDTO)
    assert dto.total_count == 1
    t = dto.transitions[0]
    assert t.from_state == "SCHEDULED"
    assert t.to_state == "RUNNING"
    assert t.actor == "scheduler"
    assert t.reason == "window_opened"


# ---------------------------------------------------------------------------
# RET-U07: execution-summary
# ---------------------------------------------------------------------------


def test_ret_u07_execution_summary():
    runs = [
        {"status": "COMPLETED", "raw_result_s3_key": "raw-results/c/a/r1.json", "duration_ms": 100},
        {"status": "COMPLETED", "raw_result_s3_key": "raw-results/c/a/r2.json", "duration_ms": 200},
    ]
    svc = _make_svc(runs=runs)
    dto = svc.get_execution_summary(_FILTERS)
    assert isinstance(dto, ExecutionSummaryDTO)
    assert dto.run_count == 2
    assert dto.total_duration_ms == 300.0
    assert ("COMPLETED", 2) in dto.outcome_distribution


# ---------------------------------------------------------------------------
# RET-U08: audit-event-timeline
# ---------------------------------------------------------------------------


def test_ret_u08_audit_event_timeline():
    svc = _make_svc(aggregate_records=[_COMPLETION, _AUDIT_AGGREGATE], jobs=[_JOB])
    dto = svc.get_audit_event_timeline(_FILTERS)
    assert isinstance(dto, AuditEventTimelineDTO)
    assert dto.total_count > 0


# ---------------------------------------------------------------------------
# RET-U09: engineering-logs
# ---------------------------------------------------------------------------


def test_ret_u09_engineering_logs():
    svc = _make_svc(jobs=[_JOB], lifecycle_history=[_LIFECYCLE_ITEM])
    dto = svc.get_engineering_logs(_FILTERS)
    assert isinstance(dto, EngineeringLogsDTO)
    assert dto.total_count > 0
    event_types = [e.event_type for e in dto.events]
    assert "aggregation_job_claimed" in event_types
    assert "lifecycle_transition" in event_types
    # No raw evidence content
    for event in dto.events:
        for k, _v in event.data:
            assert "request_body" not in k
            assert "response_body" not in k


# ---------------------------------------------------------------------------
# RET-U10: retry-history
# ---------------------------------------------------------------------------


def test_ret_u10_retry_history():
    failed_job = {**_JOB, "status": "FAILED", "reason_code": "INTEGRITY_GATE_FAILED",
                  "failure_category": "EVIDENCE_PRODUCING"}
    svc = _make_svc(jobs=[failed_job, _JOB])
    dto = svc.get_retry_history(_FILTERS)
    assert isinstance(dto, RetryHistoryDTO)
    assert dto.total_attempts == 2
    statuses = [a.status for a in dto.attempts]
    assert "COMPLETED" in statuses


# ---------------------------------------------------------------------------
# RET-U11: aggregation-generation-status
# ---------------------------------------------------------------------------


def test_ret_u11_aggregation_generation_status_complete():
    svc = _make_svc(aggregate_records=[_COMPLETION])
    dto = svc.get_aggregation_generation_status(_FILTERS)
    assert isinstance(dto, AggregationGenerationStatusDTO)
    assert dto.completion_marker_present is True
    assert dto.completeness_status == "COMPLETE"
    assert dto.aggregate_record_count == 4


def test_ret_u11_aggregation_generation_status_pending():
    svc = _make_svc()
    dto = svc.get_aggregation_generation_status(_FILTERS)
    assert dto.completeness_status == "PENDING"
    assert dto.completion_marker_present is False


# ---------------------------------------------------------------------------
# RET-U12: aggregation-version
# ---------------------------------------------------------------------------


def test_ret_u12_aggregation_version_from_completion():
    svc = _make_svc(aggregate_records=[_COMPLETION])
    dto = svc.get_aggregation_version(_FILTERS)
    assert isinstance(dto, AggregationVersionDTO)
    assert dto.aggregation_version == "v1"
    assert dto.source == "aggregate_set_completion"


def test_ret_u12_aggregation_version_from_job():
    svc = _make_svc(jobs=[_JOB])
    dto = svc.get_aggregation_version(_FILTERS)
    assert dto.aggregation_version == "v1"
    assert dto.source == "aggregation_job"


# ---------------------------------------------------------------------------
# RET-U13: evidence-references
# ---------------------------------------------------------------------------


def test_ret_u13_evidence_references():
    svc = _make_svc(aggregate_records=[_LINEAGE_MANIFEST])
    dto = svc.get_evidence_references(_FILTERS)
    assert isinstance(dto, EvidenceReferencesDTO)
    assert dto.source_ref_count == 15
    assert dto.manifest_hash == "manifest_hash_abc"
    # Raw S3 key must NOT appear in output
    for ref in dto.source_refs:
        assert ref.s3_key_ref is None or not ref.s3_key_ref.startswith("raw-results/")


# ---------------------------------------------------------------------------
# RET-U14: failure-summaries
# ---------------------------------------------------------------------------


def test_ret_u14_failure_summaries():
    svc = _make_svc(aggregate_records=[_FAILURE_AGG])
    dto = svc.get_failure_summaries(_FILTERS)
    assert isinstance(dto, FailureSummariesDTO)
    counts = dict(dto.classification_counts)
    assert "network_failure" in counts
    assert "timeout" in counts
    assert dto.total_failures == 2


# ---------------------------------------------------------------------------
# RET-U15: processing-timeline
# ---------------------------------------------------------------------------


def test_ret_u15_processing_timeline():
    svc = _make_svc(jobs=[_JOB])
    dto = svc.get_processing_timeline(_FILTERS)
    assert isinstance(dto, ProcessingTimelineDTO)
    assert dto.started_at == "2024-01-01T09:55:00Z"
    assert dto.completed_at == "2024-01-01T10:00:00Z"
    assert dto.duration_ms is not None
    assert dto.duration_ms > 0
