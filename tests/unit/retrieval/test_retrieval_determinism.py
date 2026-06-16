"""Determinism tests — multiple invocations with identical state produce identical output."""

from __future__ import annotations

import pytest

from release_confidence_platform.retrieval.dtypes import (
    ProvenanceEnvelope,
    RetrievalFilter,
)
from release_confidence_platform.retrieval.formatter import RetrievalFormatter
from release_confidence_platform.retrieval.service import RetrievalService
from tests.unit.retrieval.test_retrieval_commands import (
    _AUDIT_AGGREGATE,
    _COMPLETION,
    _ENDPOINT_AGGREGATE,
    _FAILURE_AGG,
    _JOB,
    _LIFECYCLE_ITEM,
    _LINEAGE_MANIFEST,
    MockRepo,
)

_FILTERS = RetrievalFilter(client_id="client1", audit_id="audit1")
_ENVELOPE = ProvenanceEnvelope(
    retrieved_at="2024-01-01T10:00:00.000Z",
    retrieval_version="1.0.0",
    aggregation_version="v1",
    manifest_hash="abc123",
    audit_id="audit1",
    client_id="client1",
)


def _make_svc():
    return RetrievalService(
        MockRepo(
            aggregate_records=[
                _COMPLETION,
                _AUDIT_AGGREGATE,
                _ENDPOINT_AGGREGATE,
                _FAILURE_AGG,
                _LINEAGE_MANIFEST,
            ],
            jobs=[_JOB],
            lifecycle_history=[_LIFECYCLE_ITEM],
        )
    )


def _render_json(svc, method_name):
    dto = getattr(svc, method_name)(_FILTERS)
    return RetrievalFormatter.format_json(dto, _ENVELOPE)


# ---------------------------------------------------------------------------
# Determinism: multiple invocations produce identical output for each command
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method_name",
    [
        "get_aggregation_results",
        "get_aggregation_metadata",
        "get_aggregation_lineage",
        "get_aggregation_status",
        "get_orchestration_timeline",
        "get_lifecycle_transitions",
        "get_execution_summary",
        "get_audit_event_timeline",
        "get_engineering_logs",
        "get_retry_history",
        "get_aggregation_generation_status",
        "get_aggregation_version",
        "get_evidence_references",
        "get_failure_summaries",
        "get_processing_timeline",
    ],
)
def test_determinism_all_commands(method_name):
    svc = _make_svc()
    out1 = _render_json(svc, method_name)
    out2 = _render_json(svc, method_name)
    assert out1 == out2, f"{method_name}: outputs differ across invocations"


# ---------------------------------------------------------------------------
# Canonical collection ordering is stable across re-runs
# ---------------------------------------------------------------------------


def test_collection_ordering_stability():
    # Records in non-canonical order — after service sorting + formatter, order must be stable
    ep_c = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#ENDPOINT#ep_c",
        "record_kind": "aggregate",
        "aggregate_type": "endpoint",
        "client_id": "client1",
        "audit_id": "audit1",
        "endpoint_id": "ep_c",
        "aggregation_version": "v1",
    }
    ep_a = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#ENDPOINT#ep_a",
        "record_kind": "aggregate",
        "aggregate_type": "endpoint",
        "client_id": "client1",
        "audit_id": "audit1",
        "endpoint_id": "ep_a",
        "aggregation_version": "v1",
    }
    svc = RetrievalService(MockRepo(aggregate_records=[ep_c, ep_a]))
    dto = svc.get_aggregation_results(_FILTERS)
    env = _ENVELOPE
    out1 = RetrievalFormatter.format_json(dto, env)
    out2 = RetrievalFormatter.format_json(dto, env)
    assert out1 == out2


# ---------------------------------------------------------------------------
# Stable under timestamp ties
# ---------------------------------------------------------------------------


def test_ordering_stable_under_timestamp_ties():
    job_a = {**_JOB, "aggregation_job_id": "job_a", "started_at": "2024-01-01T09:55:00Z"}
    job_b = {**_JOB, "aggregation_job_id": "job_b", "started_at": "2024-01-01T09:55:00Z",
             "PK": "CLIENT#client1", "SK": "AUDIT#audit1#AGGJOB#job_b"}
    svc = RetrievalService(MockRepo(jobs=[job_a, job_b]))
    out1 = _render_json(svc, "get_retry_history")
    out2 = _render_json(svc, "get_retry_history")
    assert out1 == out2
