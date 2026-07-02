"""Test: anomaly flagging when FailureClassificationAggregate is absent for an endpoint.

Validates ARCH-3: when an endpoint has non-zero execution_count but no corresponding
FailureClassificationAggregate record, the assembled artifact must:
  - set source_field_refs.failure_classification_breakdown to the ANOMALY string
  - include data_quality_notes with note_type=MISSING_FAILURE_CLASSIFICATION_AGGREGATE
  - still include failure_classification_breakdown (sourced from EndpointAggregate fallback)

For endpoints that DO have a FailureClassificationAggregate:
  - source_field_refs.failure_classification_breakdown is the normal string
  - data_quality_notes is absent
  - failure_classification_breakdown is always present
"""
from __future__ import annotations

from release_confidence_platform.reliability_intelligence.engine import IntelligenceEngine

# ---------------------------------------------------------------------------
# Fixture Phase 4 data: two endpoints, only one has an FC aggregate
# ---------------------------------------------------------------------------

_AGGREGATE_SET = {
    "completion_status": "COMPLETE",
    "aggregate_set_hash": "hash_anomaly_test",
    "aggregation_job_id": "aggjob_anomaly",
    "source_raw_result_count": 20,
    "endpoint_aggregate_count": 2,
    "created_at": "2026-01-01T00:00:00Z",
    "audit_lineage_manifest_ref": None,
}

_AUDIT_AGGREGATE = {
    "aggregate_type": "audit",
    "record_kind": "aggregate",
    "request_counts": {
        "total": 20, "successful": 18, "failed": 2, "timeout": 0, "network_failure": 2,
    },
    "latency_summary_ms": {
        "count": 20, "min": 50.0, "max": 500.0, "mean": 120.0,
        "median": 100.0, "p95": 400.0, "p99": 480.0,
    },
    "endpoint_execution_counts": {"ep_with_fc": 10, "ep_without_fc": 10},
    "lineage": {"audit_execution_id": "exec1", "config_version": "cfg_v1"},
}

# ep_with_fc: has execution_count > 0 AND a corresponding FailureClassificationAggregate
_ENDPOINT_WITH_FC = {
    "aggregate_type": "endpoint",
    "record_kind": "aggregate",
    "endpoint_id": "ep_with_fc",
    "execution_count": 10,
    "success_inputs": {"numerator": 10, "denominator": 10},
    "timeout_count": 0,
    "failure_classification_counts": {"PASS": 10},
    "http_response_distribution": {"200": 10},
    "latency_distribution_ms": {
        "summary": {
            "count": 10, "min": 50.0, "max": 200.0, "mean": 100.0,
            "median": 95.0, "p95": 180.0, "p99": 195.0,
        }
    },
    "lineage": {"audit_execution_id": "exec1", "config_version": "cfg_v1"},
}

# ep_without_fc: has execution_count > 0 but NO FailureClassificationAggregate record
_ENDPOINT_WITHOUT_FC = {
    "aggregate_type": "endpoint",
    "record_kind": "aggregate",
    "endpoint_id": "ep_without_fc",
    "execution_count": 10,
    "success_inputs": {"numerator": 8, "denominator": 10},
    "timeout_count": 0,
    "failure_classification_counts": {"PASS": 8, "CONNECTION_ERROR": 2},
    "http_response_distribution": {"200": 8, "503": 2},
    "latency_distribution_ms": {
        "summary": {
            "count": 10, "min": 60.0, "max": 500.0, "mean": 150.0,
            "median": 120.0, "p95": 420.0, "p99": 490.0,
        }
    },
    "lineage": {"audit_execution_id": "exec1", "config_version": "cfg_v1"},
}

# Only ep_with_fc has a FailureClassificationAggregate; ep_without_fc has none
_FC_WITH_FC = {
    "aggregate_type": "failure_classification",
    "record_kind": "aggregate",
    "scope": "endpoint",
    "endpoint_id": "ep_with_fc",
    "classification_counts": {"PASS": 10},
    "lineage": {"audit_execution_id": "exec1", "config_version": "cfg_v1"},
}


# ---------------------------------------------------------------------------
# Minimal in-memory repository and publisher for this test
# ---------------------------------------------------------------------------


class _AnomalyTestRepository:
    """Repository that returns only an FC aggregate for ep_with_fc (not ep_without_fc)."""

    def get_intelligence_metadata(self, filters):
        return None

    def get_aggregate_set_completion(self, client_id, audit_id, exec_id, cfg, agg_ver):
        return _AGGREGATE_SET

    def list_phase4_aggregate_records(self, client_id, audit_id, exec_id, cfg, agg_ver):
        return [_AUDIT_AGGREGATE, _ENDPOINT_WITH_FC, _ENDPOINT_WITHOUT_FC, _FC_WITH_FC]

    def intelligence_job_keys(self, client_id, audit_id, job_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#INTJOB#{job_id}"}

    def intelligence_metadata_keys(
        self, client_id, audit_id, exec_id, cfg, agg_ver, intel_ver
    ):
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": (
                f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}"
                f"#AGG#{agg_ver}#INTEL#{intel_ver}#META"
            ),
        }

    def put_intelligence_job_once(self, item): pass
    def put_intelligence_metadata_once(self, item): pass
    def update_intelligence_metadata(self, item): pass
    def update_intelligence_job(self, key, updates): pass
    def update_intelligence_metadata_fields(self, key, updates): pass


class _CapturingPublisher:
    def __init__(self):
        self.artifact: dict | None = None

    def write_artifact(self, key, artifact):
        self.artifact = artifact


def _run_anomaly_pipeline() -> dict:
    """Run the full engine pipeline and return the assembled S3 artifact."""
    repo = _AnomalyTestRepository()
    publisher = _CapturingPublisher()
    engine = IntelligenceEngine(repo, publisher)
    engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
    )
    assert publisher.artifact is not None, "Publisher must have received an artifact"
    return publisher.artifact


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_missing_fc_aggregate_flags_anomaly_in_data_quality_notes():
    """Endpoint WITHOUT a FailureClassificationAggregate must have data_quality_notes set."""
    artifact = _run_anomaly_pipeline()
    endpoints = {ep["endpoint_id"]: ep for ep in artifact["endpoints"]}

    rm_no_fc = endpoints["ep_without_fc"]["reliability_metrics"]

    assert "data_quality_notes" in rm_no_fc, (
        "reliability_metrics must contain data_quality_notes when FC aggregate is absent"
    )
    notes = rm_no_fc["data_quality_notes"]
    assert len(notes) == 1, f"Expected exactly one data_quality_note, got {len(notes)}"
    assert notes[0]["note_type"] == "MISSING_FAILURE_CLASSIFICATION_AGGREGATE", (
        f"Expected note_type MISSING_FAILURE_CLASSIFICATION_AGGREGATE, got {notes[0]['note_type']!r}"
    )
    assert "ANOMALY" in rm_no_fc["source_field_refs"]["failure_classification_breakdown"], (
        "source_field_refs.failure_classification_breakdown must contain 'ANOMALY' "
        "when FC aggregate is absent"
    )


def test_present_fc_aggregate_no_anomaly_note():
    """Endpoint WITH a FailureClassificationAggregate must NOT have data_quality_notes."""
    artifact = _run_anomaly_pipeline()
    endpoints = {ep["endpoint_id"]: ep for ep in artifact["endpoints"]}

    rm_with_fc = endpoints["ep_with_fc"]["reliability_metrics"]

    assert "data_quality_notes" not in rm_with_fc, (
        "reliability_metrics must NOT contain data_quality_notes when FC aggregate is present"
    )
    fc_ref = rm_with_fc["source_field_refs"]["failure_classification_breakdown"]
    assert "ANOMALY" not in fc_ref, (
        f"source_field_refs.failure_classification_breakdown must be normal string, got {fc_ref!r}"
    )
    assert fc_ref == "FailureClassificationAggregate.classification_counts (scope=endpoint)", (
        f"Expected normal FC ref string, got {fc_ref!r}"
    )


def test_failure_classification_breakdown_always_present():
    """failure_classification_breakdown must always be present in reliability_metrics."""
    artifact = _run_anomaly_pipeline()
    for ep_entry in artifact["endpoints"]:
        ep_id = ep_entry["endpoint_id"]
        rm = ep_entry["reliability_metrics"]
        assert "failure_classification_breakdown" in rm, (
            f"failure_classification_breakdown missing for endpoint {ep_id!r}"
        )
        assert isinstance(rm["failure_classification_breakdown"], dict), (
            f"failure_classification_breakdown must be a dict for endpoint {ep_id!r}"
        )
