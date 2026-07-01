"""Test: IntelligenceEngine never writes to Phase 4 DynamoDB SK namespaces.

NFR-5 — Phase 4 non-mutation invariant.

All write calls on the repository are intercepted and checked to ensure the SK
contains only Phase 5 markers (#INTJOB# or #INTEL#) and never any Phase 4-exclusive
markers (#AGGJOB#, #EXECUTION_ID, #ENDPOINT#, #LINEAGE#, #RUN#, #SET, #AUDIT, etc.).
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from release_confidence_platform.reliability_intelligence.engine import (
    IntelligenceEngine,
    IntelligenceGateError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_AGGREGATE_SET = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#SET",
    "aggregate_type": "aggregate_set_completion",
    "record_kind": "aggregate_set_completion",
    "completion_status": "COMPLETE",
    "aggregate_set_hash": "abc123",
    "aggregation_job_id": "aggjob_xyz",
    "source_raw_result_count": 20,
    "endpoint_aggregate_count": 1,
    "created_at": "2026-01-01T00:00:00Z",
    "audit_lineage_manifest_ref": None,
}

_AUDIT_AGGREGATE = {
    "aggregate_type": "audit",
    "record_kind": "aggregate",
    "request_counts": {
        "total": 20,
        "successful": 18,
        "failed": 2,
        "timeout": 1,
        "network_failure": 1,
    },
    "latency_summary_ms": {
        "count": 20,
        "min": 50.0,
        "max": 500.0,
        "mean": 120.0,
        "median": 100.0,
        "p95": 400.0,
        "p99": 480.0,
    },
    "endpoint_execution_counts": {"ep_1": 20},
    "lineage": {"audit_execution_id": "exec1", "config_version": "cfg_v1"},
}

_ENDPOINT_AGGREGATE = {
    "aggregate_type": "endpoint",
    "record_kind": "aggregate",
    "endpoint_id": "ep_1",
    "execution_count": 20,
    "success_inputs": {"numerator": 18, "denominator": 20},
    "timeout_count": 1,
    "failure_classification_counts": {"PASS": 18, "TIMEOUT": 1, "CONNECTION_ERROR": 1},
    "http_response_distribution": {"200": 18, "504": 2},
    "latency_distribution_ms": {
        "summary": {
            "count": 20,
            "min": 50.0,
            "max": 500.0,
            "mean": 120.0,
            "median": 100.0,
            "p95": 400.0,
            "p99": 480.0,
        }
    },
    "lineage": {"audit_execution_id": "exec1", "config_version": "cfg_v1"},
}

_FAILURE_CLASSIFICATION = {
    "aggregate_type": "failure_classification",
    "record_kind": "aggregate",
    "scope": "endpoint",
    "endpoint_id": "ep_1",
    "classification_counts": {"PASS": 18, "TIMEOUT": 1, "CONNECTION_ERROR": 1},
    "lineage": {"audit_execution_id": "exec1", "config_version": "cfg_v1"},
}

# Phase 4-exclusive SK markers that must never appear in Phase 5 writes.
_PHASE4_PROHIBITED = (
    "#AGGJOB#",
    "#EXECUTION_ID",
    "#ENDPOINT#",
    "#LINEAGE#",
    "#RUN#",
    "#SET",
    "#AUDIT",
    "#FAILURE_CLASSIFICATION",
)


class _TrackingRepository:
    """Repository that tracks all write calls and validates Phase 5 SK invariants."""

    def __init__(self, *, has_existing_metadata: bool = False):
        self.write_calls: list[tuple[str, dict]] = []
        self._has_existing_metadata = has_existing_metadata

    # ------ Phase 4 reads (read-only) ------

    def get_intelligence_metadata(self, filters):
        if self._has_existing_metadata:
            return {
                "status": "FAILED",
                "intelligence_job_id": "intjob_old",
                "generation_count": 1,
                "created_at": "2026-01-01T00:00:00Z",
            }
        return None

    def get_aggregate_set_completion(self, client_id, audit_id, exec_id, cfg, agg_ver):
        return _AGGREGATE_SET

    def list_phase4_aggregate_records(self, client_id, audit_id, exec_id, cfg, agg_ver):
        return [_AUDIT_AGGREGATE, _ENDPOINT_AGGREGATE, _FAILURE_CLASSIFICATION]

    # ------ Phase 5 writes (tracked) ------

    def intelligence_job_keys(self, client_id, audit_id, job_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#INTJOB#{job_id}"}

    def intelligence_metadata_keys(self, client_id, audit_id, exec_id, cfg, agg_ver, intel_ver):
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{agg_ver}#INTEL#{intel_ver}#META",
        }

    def put_intelligence_job_once(self, item):
        sk = item.get("SK", "")
        self._assert_phase5_sk("put_intelligence_job_once", sk)
        self.write_calls.append(("put_intelligence_job_once", item))

    def put_intelligence_metadata_once(self, item):
        sk = item.get("SK", "")
        self._assert_phase5_sk("put_intelligence_metadata_once", sk)
        self.write_calls.append(("put_intelligence_metadata_once", item))

    def update_intelligence_metadata(self, item):
        sk = item.get("SK", "")
        self._assert_phase5_sk("update_intelligence_metadata", sk)
        self.write_calls.append(("update_intelligence_metadata", item))

    def update_intelligence_job(self, key, updates):
        sk = key.get("SK", "")
        self._assert_phase5_sk("update_intelligence_job", sk)
        self.write_calls.append(("update_intelligence_job", {**key, **updates}))

    def update_intelligence_metadata_fields(self, key, updates):
        sk = key.get("SK", "")
        self._assert_phase5_sk("update_intelligence_metadata_fields", sk)
        self.write_calls.append(("update_intelligence_metadata_fields", {**key, **updates}))

    def _assert_phase5_sk(self, method_name: str, sk: str) -> None:
        for prohibited in _PHASE4_PROHIBITED:
            assert prohibited not in sk, (
                f"Phase 4 mutation detected! Method={method_name!r} attempted to write "
                f"to Phase 4 SK namespace. SK={sk!r} contains prohibited marker {prohibited!r}. "
                "Phase 5 writes must only target #INTJOB# or #INTEL# SK patterns."
            )
        assert "#INTJOB#" in sk or "#INTEL#" in sk, (
            f"Phase 5 write target must contain #INTJOB# or #INTEL#. "
            f"Method={method_name!r}, SK={sk!r}"
        )


class _TrackingPublisher:
    def __init__(self):
        self.write_calls: list[tuple[str, dict]] = []

    def write_artifact(self, key, artifact):
        self.write_calls.append((key, artifact))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def _run_engine(*, has_existing: bool = False) -> tuple[_TrackingRepository, _TrackingPublisher]:
    repo = _TrackingRepository(has_existing_metadata=has_existing)
    publisher = _TrackingPublisher()
    engine = IntelligenceEngine(repo, publisher)
    engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
    )
    return repo, publisher


def test_no_phase4_writes_on_first_generation():
    """First-time generation must only write to Phase 5 SK namespaces."""
    repo, publisher = _run_engine(has_existing=False)
    assert len(repo.write_calls) > 0, "Expected at least one write call"
    # If _assert_phase5_sk didn't raise, all writes are Phase 5-only.
    for method, item in repo.write_calls:
        sk = item.get("SK", "")
        assert "#INTJOB#" in sk or "#INTEL#" in sk, (
            f"Write {method!r} targeted non-Phase-5 SK: {sk!r}"
        )


def test_no_phase4_writes_on_force_regeneration():
    """Force re-generation must only write to Phase 5 SK namespaces."""
    repo = _TrackingRepository(has_existing_metadata=True)
    publisher = _TrackingPublisher()
    engine = IntelligenceEngine(repo, publisher)
    engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        force=True,
    )
    assert len(repo.write_calls) > 0, "Expected at least one write call on force re-generation"
    for method, item in repo.write_calls:
        sk = item.get("SK", "")
        assert "#INTJOB#" in sk or "#INTEL#" in sk, (
            f"Force re-gen write {method!r} targeted non-Phase-5 SK: {sk!r}"
        )


def test_no_phase4_writes_on_failed_retry():
    """Retrying a FAILED intelligence generation must only write to Phase 5 SK namespaces."""
    repo, publisher = _run_engine(has_existing=True)
    assert len(repo.write_calls) > 0
    for method, item in repo.write_calls:
        sk = item.get("SK", "")
        assert "#INTJOB#" in sk or "#INTEL#" in sk


def test_write_call_count_first_generation():
    """First generation must write IntelligenceJob and IntelligenceMetadata at minimum."""
    repo, publisher = _run_engine(has_existing=False)
    methods = [call[0] for call in repo.write_calls]
    assert "put_intelligence_job_once" in methods
    assert "put_intelligence_metadata_once" in methods
    assert "update_intelligence_job" in methods
    assert "update_intelligence_metadata_fields" in methods


def test_s3_write_contains_correct_key_prefix():
    """S3 artifact key must use the intelligence/ prefix, never raw-results/."""
    _, publisher = _run_engine(has_existing=False)
    assert len(publisher.write_calls) == 1
    key, _artifact = publisher.write_calls[0]
    assert key.startswith("intelligence/"), (
        f"S3 artifact key must start with intelligence/, got: {key!r}"
    )
    assert "raw-results" not in key, (
        f"S3 artifact key must not use raw-results/ prefix: {key!r}"
    )
