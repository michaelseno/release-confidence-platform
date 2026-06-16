"""RET-FL01 through RET-FL05 — filtering tests."""

from __future__ import annotations

from release_confidence_platform.retrieval.dtypes import RetrievalFilter
from release_confidence_platform.retrieval.service import RetrievalService
from tests.unit.retrieval.test_retrieval_commands import _JOB, MockRepo

_CLIENT1_JOB = {**_JOB, "client_id": "client1", "audit_id": "audit1"}
_CLIENT2_JOB = {**_JOB, "client_id": "client2", "audit_id": "audit2",
                "PK": "CLIENT#client2", "SK": "AUDIT#audit2#AGGJOB#job2",
                "aggregation_job_id": "job2"}

_EP1_AGGREGATE = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#ENDPOINT#ep1",
    "record_kind": "aggregate",
    "aggregate_type": "endpoint",
    "client_id": "client1",
    "audit_id": "audit1",
    "endpoint_id": "ep1",
    "aggregation_version": "v1",
}

_EP2_AGGREGATE = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg1#AGG#v1#ENDPOINT#ep2",
    "record_kind": "aggregate",
    "aggregate_type": "endpoint",
    "client_id": "client1",
    "audit_id": "audit1",
    "endpoint_id": "ep2",
    "aggregation_version": "v1",
}


# ---------------------------------------------------------------------------
# RET-FL01: --client filter restricts to specified client
# ---------------------------------------------------------------------------


def test_ret_fl01_client_filter():
    # Repo only returns client1 data (filter applied at repo level in real usage;
    # here we test the filter logic applied in-service)
    svc = RetrievalService(MockRepo(jobs=[_CLIENT1_JOB]))
    filters = RetrievalFilter(client_id="client1", audit_id="audit1")
    dto = svc.get_aggregation_metadata(filters)
    assert dto.job_id == "job1"

    # If we set a different client filter, the repo returns same job but filter removes it
    # (In full integration this is the DynamoDB PK; here we test apply_filter directly)
    from release_confidence_platform.retrieval.filters import apply_filter  # noqa: PLC0415

    filtered = apply_filter([_CLIENT1_JOB, _CLIENT2_JOB], RetrievalFilter(client_id="client2"))
    assert all(item["client_id"] == "client2" for item in filtered)
    assert len(filtered) == 1


# ---------------------------------------------------------------------------
# RET-FL02: --audit filter restricts to specified audit
# ---------------------------------------------------------------------------


def test_ret_fl02_audit_filter():
    from release_confidence_platform.retrieval.filters import apply_filter  # noqa: PLC0415

    filtered = apply_filter([_CLIENT1_JOB, _CLIENT2_JOB], RetrievalFilter(audit_id="audit1"))
    assert all(item["audit_id"] == "audit1" for item in filtered)
    assert len(filtered) == 1


# ---------------------------------------------------------------------------
# RET-FL03: --endpoint filter restricts endpoint aggregate results
# ---------------------------------------------------------------------------


def test_ret_fl03_endpoint_filter():
    from release_confidence_platform.retrieval.filters import apply_filter  # noqa: PLC0415

    filtered = apply_filter(
        [_EP1_AGGREGATE, _EP2_AGGREGATE],
        RetrievalFilter(client_id="client1", audit_id="audit1", endpoint_id="ep1"),
    )
    assert len(filtered) == 1
    assert filtered[0]["endpoint_id"] == "ep1"


# ---------------------------------------------------------------------------
# RET-FL04: Unknown client ID returns empty/not-found, no error
# ---------------------------------------------------------------------------


def test_ret_fl04_unknown_client_returns_empty():
    svc = RetrievalService(MockRepo())  # repo returns nothing for unknown client
    filters = RetrievalFilter(client_id="unknown_client", audit_id="unknown_audit")
    dto = svc.get_aggregation_metadata(filters)
    assert dto.job_id is None
    assert dto.status is None


# ---------------------------------------------------------------------------
# RET-FL05: Unknown audit ID returns empty/not-found, no error
# ---------------------------------------------------------------------------


def test_ret_fl05_unknown_audit_returns_empty():
    svc = RetrievalService(MockRepo())
    filters = RetrievalFilter(client_id="client1", audit_id="nonexistent_audit")
    dto = svc.get_aggregation_results(filters)
    assert dto.total_count == 0
    dto2 = svc.get_lifecycle_transitions(filters)
    assert dto2.total_count == 0
