"""Test: IntelligenceEngine idempotency behavior.

Covers:
  1. Second invocation without --force when COMPLETE exists returns existing result, no new writes.
  2. --force when COMPLETE exists proceeds with a new intelligence_job_id.
  3. Re-invocation when status=FAILED proceeds without --force.
"""
from __future__ import annotations

from release_confidence_platform.reliability_intelligence.engine import (
    IntelligenceEngine,
)

# ---------------------------------------------------------------------------
# Shared test infrastructure
# ---------------------------------------------------------------------------

_AGGREGATE_SET = {
    "completion_status": "COMPLETE",
    "aggregate_set_hash": "hash_abc",
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
        "total": 20, "successful": 18, "failed": 2, "timeout": 1, "network_failure": 1
    },
    "latency_summary_ms": {
        "count": 20, "min": 50.0, "max": 500.0, "mean": 120.0,
        "median": 100.0, "p95": 400.0, "p99": 480.0,
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
            "count": 20, "min": 50.0, "max": 500.0, "mean": 120.0,
            "median": 100.0, "p95": 400.0, "p99": 480.0,
        }
    },
    "lineage": {"audit_execution_id": "exec1", "config_version": "cfg_v1"},
}


class _IdempotencyRepository:
    """Repository with configurable existing metadata state for idempotency testing."""

    def __init__(self, existing_metadata: dict | None = None):
        self._existing_metadata = existing_metadata
        self.write_calls: list = []

    def get_intelligence_metadata(self, filters):
        return self._existing_metadata

    def get_aggregate_set_completion(self, client_id, audit_id, exec_id, cfg, agg_ver):
        return _AGGREGATE_SET

    def list_phase4_aggregate_records(self, client_id, audit_id, exec_id, cfg, agg_ver):
        return [_AUDIT_AGGREGATE, _ENDPOINT_AGGREGATE]

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


class _TrackingPublisher:
    def __init__(self):
        self.write_calls: list = []

    def write_artifact(self, key, artifact):
        self.write_calls.append((key, artifact))


def _make_engine(existing_metadata=None):
    repo = _IdempotencyRepository(existing_metadata=existing_metadata)
    publisher = _TrackingPublisher()
    engine = IntelligenceEngine(repo, publisher)
    return engine, repo, publisher


# ---------------------------------------------------------------------------
# Test 1: COMPLETE + no force → return existing, no new writes
# ---------------------------------------------------------------------------


def test_complete_without_force_returns_existing_no_writes():
    """Second call without --force when COMPLETE exists must return existing and skip all writes."""
    existing = {
        "status": "COMPLETE",
        "intelligence_job_id": "intjob_existing",
        "composite_score": "0.900",
        "score_label": "HIGH_CONFIDENCE",
        "endpoint_count": 1,
        "s3_artifact_ref": (
            "intelligence/client1/audit1/exec1/agg_v1/intel_v1/intjob_existing/artifact.json"
        ),
        "generation_count": 1,
        "created_at": "2026-01-01T00:00:00Z",
    }
    engine, repo, publisher = _make_engine(existing_metadata=existing)
    result = engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        force=False,
    )

    assert result["status"] == "ALREADY_COMPLETE"
    assert result["intelligence_job_id"] == "intjob_existing"
    assert result["composite_score"] == "0.900"
    assert result["score_label"] == "HIGH_CONFIDENCE"
    assert len(repo.write_calls) == 0, (
        f"No writes expected when COMPLETE without force, got: {repo.write_calls}"
    )
    assert len(publisher.write_calls) == 0, (
        "No S3 writes expected when COMPLETE without force"
    )


def test_complete_without_force_returns_existing_artifact_ref():
    """The returned s3_artifact_ref must match the existing record's ref."""
    existing = {
        "status": "COMPLETE",
        "intelligence_job_id": "intjob_existing",
        "composite_score": "0.750",
        "score_label": "MODERATE_CONFIDENCE",
        "endpoint_count": 2,
        "s3_artifact_ref": (
            "intelligence/client1/audit1/exec1/agg_v1/intel_v1/intjob_existing/artifact.json"
        ),
        "generation_count": 1,
        "created_at": "2026-01-01T00:00:00Z",
    }
    engine, repo, publisher = _make_engine(existing_metadata=existing)
    result = engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        force=False,
    )

    assert result["s3_artifact_ref"] == existing["s3_artifact_ref"]


# ---------------------------------------------------------------------------
# Test 2: COMPLETE + force → proceeds, new job_id generated
# ---------------------------------------------------------------------------


def test_force_when_complete_generates_new_job_id():
    """--force when COMPLETE exists must create a new intelligence_job_id, not reuse the old one."""
    existing = {
        "status": "COMPLETE",
        "intelligence_job_id": "intjob_existing",
        "composite_score": "0.900",
        "score_label": "HIGH_CONFIDENCE",
        "endpoint_count": 1,
        "s3_artifact_ref": (
            "intelligence/client1/audit1/exec1/agg_v1/intel_v1/intjob_existing/artifact.json"
        ),
        "generation_count": 1,
        "created_at": "2026-01-01T00:00:00Z",
    }
    engine, repo, publisher = _make_engine(existing_metadata=existing)
    result = engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        force=True,
    )

    assert result["status"] == "COMPLETE"
    assert result["intelligence_job_id"] != "intjob_existing", (
        "Force re-generation must use a new intelligence_job_id"
    )
    assert result["intelligence_job_id"].startswith("intjob_")
    assert len(repo.write_calls) > 0, "Expected writes on force re-generation"
    assert len(publisher.write_calls) == 1, "Expected one S3 artifact write on force re-generation"


def test_force_uses_update_metadata_not_put_once_when_existing():
    """--force when COMPLETE exists must use update_intelligence_metadata, not put_once."""
    existing = {
        "status": "COMPLETE",
        "intelligence_job_id": "intjob_existing",
        "composite_score": "0.900",
        "score_label": "HIGH_CONFIDENCE",
        "endpoint_count": 1,
        "s3_artifact_ref": "...",
        "generation_count": 1,
        "created_at": "2026-01-01T00:00:00Z",
    }
    engine, repo, publisher = _make_engine(existing_metadata=existing)
    engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        force=True,
    )

    methods = [c[0] for c in repo.write_calls]
    assert "update_intelligence_metadata" in methods, (
        "Force re-generation must use update_intelligence_metadata for the existing metadata record"
    )
    assert "put_intelligence_metadata_once" not in methods, (
        "Force re-generation must NOT use put_intelligence_metadata_once for existing records"
    )


def test_force_generation_count_increments():
    """Force re-generation must increment the generation_count from the existing record."""
    existing = {
        "status": "COMPLETE",
        "intelligence_job_id": "intjob_existing",
        "composite_score": "0.900",
        "score_label": "HIGH_CONFIDENCE",
        "endpoint_count": 1,
        "s3_artifact_ref": "...",
        "generation_count": 2,  # Previous generation count
        "created_at": "2026-01-01T00:00:00Z",
    }
    engine, repo, publisher = _make_engine(existing_metadata=existing)
    engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        force=True,
    )

    # Find the update_intelligence_metadata call and check generation_count
    update_calls = [c for c in repo.write_calls if c[0] == "update_intelligence_metadata"]
    assert len(update_calls) == 1
    meta_item = update_calls[0][1]
    assert meta_item.get("generation_count") == 3, (
        f"generation_count must increment from 2 to 3, got {meta_item.get('generation_count')}"
    )


# ---------------------------------------------------------------------------
# Test 3: FAILED status → proceeds without --force
# ---------------------------------------------------------------------------


def test_failed_status_retries_without_force():
    """FAILED intelligence must be retryable without --force."""
    existing = {
        "status": "FAILED",
        "intelligence_job_id": "intjob_failed",
        "failure_stage": "computing_metrics",
        "failure_reason_code": "MISSING_AUDIT_AGGREGATE",
        "generation_count": 1,
        "created_at": "2026-01-01T00:00:00Z",
    }
    engine, repo, publisher = _make_engine(existing_metadata=existing)
    result = engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        force=False,  # No --force needed for FAILED retry
    )

    assert result["status"] == "COMPLETE", (
        f"Retry of FAILED intelligence must produce COMPLETE, got {result['status']}"
    )
    assert result["intelligence_job_id"] != "intjob_failed", (
        "Retry must generate a new intelligence_job_id"
    )


def test_failed_retry_increments_generation_count():
    """Retrying a FAILED generation must increment generation_count."""
    existing = {
        "status": "FAILED",
        "intelligence_job_id": "intjob_failed",
        "generation_count": 1,
        "created_at": "2026-01-01T00:00:00Z",
    }
    engine, repo, publisher = _make_engine(existing_metadata=existing)
    engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
    )

    update_meta_calls = [c for c in repo.write_calls if c[0] == "update_intelligence_metadata"]
    assert len(update_meta_calls) == 1
    assert update_meta_calls[0][1].get("generation_count") == 2


# ---------------------------------------------------------------------------
# Test: pending/in-progress existing — proceed
# ---------------------------------------------------------------------------


def test_pending_status_proceeds():
    """PENDING IntelligenceMetadata must not block a new generation attempt."""
    existing = {
        "status": "PENDING",
        "intelligence_job_id": "intjob_stalled",
        "generation_count": 1,
        "created_at": "2026-01-01T00:00:00Z",
    }
    engine, repo, publisher = _make_engine(existing_metadata=existing)
    result = engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
    )
    assert result["status"] == "COMPLETE"
