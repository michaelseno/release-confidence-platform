"""Test: IntelligenceEngine prerequisite gate behavior.

Verifies that IntelligenceGateError is raised correctly and no Phase 5 records
are written when the AggregateSetCompletion prerequisite is not satisfied.
"""
from __future__ import annotations

import pytest

from release_confidence_platform.reliability_intelligence.engine import (
    IntelligenceEngine,
    IntelligenceGateError,
)

# ---------------------------------------------------------------------------
# Minimal repository stubs
# ---------------------------------------------------------------------------


class _GateTestRepository:
    """Repository stub for gate tests with configurable aggregate_set state."""

    def __init__(self, aggregate_set=None):
        self._aggregate_set = aggregate_set
        self.write_calls: list = []

    def get_intelligence_metadata(self, filters):
        return None  # No existing record

    def get_aggregate_set_completion(self, client_id, audit_id, exec_id, cfg, agg_ver):
        return self._aggregate_set

    def list_phase4_aggregate_records(self, *args, **kwargs):
        return []

    def intelligence_job_keys(self, client_id, audit_id, job_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#INTJOB#{job_id}"}

    def intelligence_metadata_keys(self, client_id, audit_id, exec_id, cfg, agg_ver, intel_ver):
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{agg_ver}#INTEL#{intel_ver}#META",
        }

    def put_intelligence_job_once(self, item):
        self.write_calls.append(("put_intelligence_job_once", item))

    def put_intelligence_metadata_once(self, item):
        self.write_calls.append(("put_intelligence_metadata_once", item))

    def update_intelligence_metadata(self, item):
        self.write_calls.append(("update_intelligence_metadata", item))

    def update_intelligence_job(self, key, updates):
        self.write_calls.append(("update_intelligence_job", {**key, **updates}))

    def update_intelligence_metadata_fields(self, key, updates):
        self.write_calls.append(("update_intelligence_metadata_fields", {**key, **updates}))


class _NullPublisher:
    def write_artifact(self, key, artifact):
        pass


def _call_generate(repo):
    engine = IntelligenceEngine(repo, _NullPublisher())
    engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
    )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_gate_fails_when_aggregate_set_missing():
    """Missing AggregateSetCompletion must raise IntelligenceGateError."""
    repo = _GateTestRepository(aggregate_set=None)
    with pytest.raises(IntelligenceGateError):
        _call_generate(repo)


def test_gate_fails_when_aggregate_set_not_complete():
    """AggregateSetCompletion with status != COMPLETE must raise IntelligenceGateError."""
    incomplete_set = {
        "completion_status": "PENDING",
        "aggregate_set_hash": "abc",
    }
    repo = _GateTestRepository(aggregate_set=incomplete_set)
    with pytest.raises(IntelligenceGateError):
        _call_generate(repo)


def test_gate_fails_when_aggregate_set_failed():
    """AggregateSetCompletion with status = FAILED must raise IntelligenceGateError."""
    failed_set = {
        "completion_status": "FAILED",
        "aggregate_set_hash": "abc",
    }
    repo = _GateTestRepository(aggregate_set=failed_set)
    with pytest.raises(IntelligenceGateError):
        _call_generate(repo)


def test_no_phase5_records_written_when_gate_fails_missing():
    """When AggregateSetCompletion is absent, no Phase 5 DynamoDB records may be written."""
    repo = _GateTestRepository(aggregate_set=None)
    publisher = _NullPublisher()
    engine = IntelligenceEngine(repo, publisher)
    with pytest.raises(IntelligenceGateError):
        engine.generate(
            client_id="client1",
            audit_id="audit1",
            audit_execution_id="exec1",
            config_version="cfg_v1",
            aggregation_version="agg_v1",
        )
    assert len(repo.write_calls) == 0, (
        f"Expected 0 Phase 5 writes when gate fails (missing), got {len(repo.write_calls)}: "
        f"{repo.write_calls}"
    )
    # Evidence Governance Workstream A1.3d.2 (Technical Design Section 20.10):
    # gate denial must produce zero IntelligenceMetadata writes and zero
    # artifact writes -- the engine's gate-denial code path is unmodified
    # and contains no hold-coordination-related behavior.
    meta_writes = [
        c
        for c in repo.write_calls
        if c[0] in ("put_intelligence_metadata_once", "update_intelligence_metadata")
    ]
    assert meta_writes == [], "Expected 0 IntelligenceMetadata writes when gate fails (missing)"


def test_no_phase5_records_written_when_gate_fails_incomplete():
    """When AggregateSetCompletion has status != COMPLETE, no Phase 5 records may be written."""
    repo = _GateTestRepository(aggregate_set={"completion_status": "PENDING"})
    with pytest.raises(IntelligenceGateError):
        _call_generate(repo)
    assert len(repo.write_calls) == 0, (
        f"Expected 0 Phase 5 writes when gate fails (incomplete), got {len(repo.write_calls)}: "
        f"{repo.write_calls}"
    )
    meta_writes = [
        c
        for c in repo.write_calls
        if c[0] in ("put_intelligence_metadata_once", "update_intelligence_metadata")
    ]
    assert meta_writes == [], "Expected 0 IntelligenceMetadata writes when gate fails (incomplete)"


def test_zero_artifact_writes_when_gate_fails():
    """Gate denial must never reach the publisher -- zero artifact writes,
    whether AggregateSetCompletion is missing or present-but-incomplete."""

    class _TrackingPublisher:
        def __init__(self):
            self.write_calls: list = []

        def write_artifact(self, key, artifact):
            self.write_calls.append((key, artifact))

    for aggregate_set in (None, {"completion_status": "PENDING"}, {"completion_status": "FAILED"}):
        repo = _GateTestRepository(aggregate_set=aggregate_set)
        publisher = _TrackingPublisher()
        engine = IntelligenceEngine(repo, publisher)
        with pytest.raises(IntelligenceGateError):
            engine.generate(
                client_id="client1",
                audit_id="audit1",
                audit_execution_id="exec1",
                config_version="cfg_v1",
                aggregation_version="agg_v1",
            )
        assert publisher.write_calls == [], (
            f"Expected 0 artifact writes when gate fails (aggregate_set={aggregate_set!r}), "
            f"got: {publisher.write_calls}"
        )


def test_gate_denial_code_path_has_no_hold_coordination_reference():
    """Structural proof: the engine's gate-denial code path (the block
    raising IntelligenceGateError) contains no hold-coordination-related
    identifier. This should already be true since engine.py is unmodified
    by Evidence Governance Workstream A1.3d.2 -- this test proves it rather
    than assuming it."""
    import inspect

    from release_confidence_platform.reliability_intelligence import engine as engine_module

    source = inspect.getsource(engine_module)
    gate_block_start = source.index("Step 2: Prerequisite gate")
    gate_block_end = source.index("Step 3: Generate new intelligence_job_id")
    gate_block = source[gate_block_start:gate_block_end]
    for forbidden in (
        "HoldRepository",
        "hold_repository",
        "hold_version",
        "CustodyPeriodConfigLoader",
        "custody_period_days",
        "HoldCoordinatedTransactionRunner",
    ):
        assert forbidden not in gate_block, (
            f"Gate-denial code path unexpectedly references {forbidden!r} -- "
            "engine.py must remain hold-coordination-unaware."
        )


def test_gate_passes_when_aggregate_set_complete():
    """COMPLETE AggregateSetCompletion must allow the pipeline to proceed past the gate."""
    complete_set = {
        "completion_status": "COMPLETE",
        "aggregate_set_hash": "abc123",
        "aggregation_job_id": "aggjob_xyz",
        "source_raw_result_count": 10,
        "endpoint_aggregate_count": 1,
        "created_at": "2026-01-01T00:00:00Z",
    }
    repo = _GateTestRepository(aggregate_set=complete_set)
    # Pipeline will fail past the gate (no audit_aggregate), but the gate itself must pass.
    # We expect a ValidationError or StorageError, not IntelligenceGateError.
    with pytest.raises(Exception) as exc_info:
        _call_generate(repo)
    # The exception must NOT be an IntelligenceGateError — the gate passed.
    assert not isinstance(exc_info.value, IntelligenceGateError), (
        f"Gate should have passed for COMPLETE AggregateSetCompletion, "
        f"but got IntelligenceGateError: {exc_info.value}"
    )
    # At least the IntelligenceJob should have been written before the pipeline failed.
    job_writes = [c for c in repo.write_calls if c[0] == "put_intelligence_job_once"]
    assert len(job_writes) == 1, (
        f"Expected 1 IntelligenceJob write after gate passes, got {len(job_writes)}"
    )


def test_intelligence_gate_error_inherits_validation_error():
    """IntelligenceGateError must inherit from ValidationError for consistent handling."""
    from release_confidence_platform.core.exceptions import ValidationError

    error = IntelligenceGateError("test gate error")
    assert isinstance(error, ValidationError), (
        "IntelligenceGateError must inherit from ValidationError"
    )
    assert error.error_type == "INTELLIGENCE_GATE_ERROR"


def test_unsupported_aggregation_version_raises_validation_error():
    """Unsupported aggregation_version must raise ValidationError before gate check."""
    from release_confidence_platform.core.exceptions import ValidationError

    repo = _GateTestRepository(aggregate_set={"completion_status": "COMPLETE"})
    engine = IntelligenceEngine(repo, _NullPublisher())
    with pytest.raises(ValidationError) as exc_info:
        engine.generate(
            client_id="client1",
            audit_id="audit1",
            audit_execution_id="exec1",
            config_version="cfg_v1",
            aggregation_version="agg_v99",  # Unknown version
        )
    assert exc_info.value.error_type == "UNSUPPORTED_AGGREGATION_VERSION"
    # No Phase 5 records must be written for an unsupported aggregation version.
    assert len(repo.write_calls) == 0
