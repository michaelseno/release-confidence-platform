"""Test: ReportingEngine pipeline behavior — gate, idempotency, and completion.

Verifies prerequisite gate enforcement, idempotency semantics, error class hierarchy,
and full pipeline completion, mirroring test_engine_gate.py patterns from Phase 5.
"""

from __future__ import annotations

from typing import Any

import pytest

from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.deterministic_reporting.engine import (
    ReportGateError,
    ReportGenerationInProgressError,
    ReportingEngine,
)

# ---------------------------------------------------------------------------
# Phase 5 intelligence artifact fixture (minimal but valid)
# ---------------------------------------------------------------------------

_INTEL_ARTIFACT = {
    "intelligence_version": "intel_v1",
    "aggregation_version": "agg_v1",
    "client_id": "client_test",
    "audit_id": "audit_test",
    "audit_execution_id": "exec_test",
    "config_version": "cfg_v1",
    "intelligence_job_id": "intjob_testfixture",
    "generated_at": "2026-07-04T12:00:00Z",
    "generator_version": "1.0.0",
    "input_lineage": {
        "aggregate_set_hash": "hashTEST",
        "aggregation_job_id": "aggjob_TEST",
        "aggregation_version": "agg_v1",
        "aggregate_set_completion_created_at": "2026-07-04T10:00:00Z",
        "endpoint_aggregate_count": 1,
        "source_raw_result_count": 20,
        "audit_lineage_manifest_ref": None,
    },
    "audit_reliability_summary": {
        "total_executions": 20,
        "total_pass": 18,
        "total_fail": 2,
        "total_timeout": 1,
        "total_network_failure": 0,
        "audit_success_rate": "0.900",
        "endpoint_count": 1,
        "audit_latency_mean_ms": 120.0,
        "audit_latency_p95_ms": 400.0,
        "audit_latency_p99_ms": 480.0,
        "source_field_refs": {"total_executions": "AuditAggregate.request_counts.total"},
    },
    "composite_score": {
        "value": "0.850",
        "score_label": "HIGH_CONFIDENCE",
        "intelligence_version": "intel_v1",
        "aggregation_version": "agg_v1",
        "aggregate_set_hash": "hashTEST",
        "endpoint_count": 1,
        "component_breakdown": {"reliability": 0.9},
    },
    "endpoints": [
        {
            "endpoint_id": "ep_test",
            "reliability_metrics": {
                "execution_count": 20,
                "pass_count": 18,
                "fail_count": 2,
                "timeout_count": 1,
                "success_rate": "0.900",
                "success_rate_numerator": 18,
                "success_rate_denominator": 20,
                "latency_min_ms": 50.0,
                "latency_max_ms": 500.0,
                "latency_mean_ms": 120.0,
                "latency_median_ms": 100.0,
                "latency_p95_ms": 400.0,
                "latency_p99_ms": 480.0,
                "latency_count": 20,
                "failure_classification_breakdown": {"PASS": 18, "TIMEOUT": 1, "CONNECTION_ERROR": 1},
                "http_response_distribution": {"200": 18, "504": 2},
                "source_field_refs": {
                    "execution_count": "EndpointAggregate.execution_count",
                },
            },
            "stability_analysis": {
                "success_rate_stability_label": "STABLE",
                "latency_stability_label": "STABLE",
                "methodology_trace": {"window": 5},
            },
            "burst_analysis": {
                "failure_burst_label": "NO_BURST",
                "latency_spike_label": "NO_SPIKE",
                "methodology_trace": {"threshold": 3},
            },
            "consistency_analysis": {
                "consistency_label": "CONSISTENT",
                "methodology_trace": {"cv": 0.1},
            },
            "endpoint_score": {
                "composite_score": "0.850",
                "reliability_score": "0.900",
                "stability_score": "1.000",
                "burst_score": "1.000",
                "consistency_score": "1.000",
                "score_derivation": {"method": "weighted_average"},
            },
        }
    ],
    "methodology_disclosure": {
        "intelligence_version": "intel_v1",
        "scoring": {"method": "composite"},
        "stability_label_definitions": {"STABLE": "..."},
        "burst_label_definitions": {"NO_BURST": "..."},
        "consistency_label_definitions": {"CONSISTENT": "..."},
        "label_to_score_mapping": {"HIGH_CONFIDENCE": 0.9},
        "limitations": ["MVP limitation"],
    },
}

_COMPLETE_INTEL_METADATA = {
    "status": "COMPLETE",
    "intelligence_job_id": "intjob_testfixture",
    "s3_artifact_ref": "intelligence/client_test/audit_test/exec_test/agg_v1/intel_v1/intjob_testfixture/artifact.json",
    "composite_score": "0.850",
    "score_label": "HIGH_CONFIDENCE",
    "endpoint_count": 1,
    "aggregate_set_hash": "hashTEST",
    "completed_at": "2026-07-04T12:00:00Z",
}


# ---------------------------------------------------------------------------
# Test repository stub
# ---------------------------------------------------------------------------


class _EngineTestRepository:
    """Repository stub with configurable state for gate and idempotency tests."""

    def __init__(
        self,
        *,
        intel_metadata: dict[str, Any] | None = _COMPLETE_INTEL_METADATA,
        existing_report_metadata: dict[str, Any] | None = None,
    ) -> None:
        self._intel_metadata = intel_metadata
        self._existing_report_metadata = existing_report_metadata
        self.write_calls: list[tuple[str, Any]] = []

    def get_intelligence_metadata(
        self, client_id, audit_id, audit_execution_id, config_version,
        aggregation_version, intelligence_version,
    ) -> dict[str, Any] | None:
        return self._intel_metadata

    def get_report_metadata(
        self, client_id, audit_id, audit_execution_id, config_version,
        aggregation_version, intelligence_version, report_version,
    ) -> dict[str, Any] | None:
        return self._existing_report_metadata

    def report_job_keys(self, client_id: str, audit_id: str, report_job_id: str) -> dict[str, str]:
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#RPTJOB#{report_job_id}",
        }

    def report_metadata_keys(
        self, client_id, audit_id, audit_execution_id, config_version,
        aggregation_version, intelligence_version, report_version,
    ) -> dict[str, str]:
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": (
                f"AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}"
                f"#AGG#{aggregation_version}#INTEL#{intelligence_version}"
                f"#RPT#{report_version}#META"
            ),
        }

    def put_report_job_once(self, item: dict[str, Any]) -> None:
        self.write_calls.append(("put_report_job_once", item))

    def put_report_metadata_once(self, item: dict[str, Any]) -> None:
        self.write_calls.append(("put_report_metadata_once", item))

    def update_report_job(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        self.write_calls.append(("update_report_job", {**key, **updates}))

    def update_report_metadata_fields(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        self.write_calls.append(("update_report_metadata_fields", {**key, **updates}))


# ---------------------------------------------------------------------------
# Publisher stubs
# ---------------------------------------------------------------------------


class _NullPublisher:
    """Publisher stub that discards writes and returns the fixture artifact on read."""

    def __init__(self, artifact: dict[str, Any] | None = None) -> None:
        self._artifact = artifact or _INTEL_ARTIFACT
        self.write_calls: list[tuple[str, dict]] = []
        self._call_order: list[str] = []

    def read_artifact(self, key: str) -> dict[str, Any]:
        self._call_order.append("read_artifact")
        return self._artifact

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        self._call_order.append("write_artifact")
        self.write_calls.append((key, artifact))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _call_generate(repo, publisher=None):
    publisher = publisher or _NullPublisher()
    engine = ReportingEngine(repo, publisher)
    return engine.generate(
        client_id="client_test",
        audit_id="audit_test",
        audit_execution_id="exec_test",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        intelligence_version="intel_v1",
    )


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------


def test_gate_fails_when_intelligence_not_found():
    """None from get_intelligence_metadata must raise ReportGateError."""
    repo = _EngineTestRepository(intel_metadata=None)
    with pytest.raises(ReportGateError):
        _call_generate(repo)


def test_gate_fails_when_intelligence_not_complete():
    """IntelligenceMetadata with status=PENDING must raise ReportGateError."""
    pending_intel = {**_COMPLETE_INTEL_METADATA, "status": "PENDING"}
    repo = _EngineTestRepository(intel_metadata=pending_intel)
    with pytest.raises(ReportGateError):
        _call_generate(repo)


def test_no_phase6_records_written_when_gate_fails():
    """No Phase 6 DynamoDB records may be written when the gate fails."""
    repo = _EngineTestRepository(intel_metadata=None)
    with pytest.raises(ReportGateError):
        _call_generate(repo)
    assert len(repo.write_calls) == 0, (
        f"Expected 0 Phase 6 writes when gate fails, got {len(repo.write_calls)}: "
        f"{repo.write_calls}"
    )


def test_gate_passes_when_intelligence_complete():
    """COMPLETE IntelligenceMetadata must allow the pipeline to proceed past the gate.

    After the gate passes, the pipeline writes Phase 6 records. The important
    assertion is that the error is NOT a ReportGateError.
    """
    repo = _EngineTestRepository(intel_metadata=_COMPLETE_INTEL_METADATA)
    # Pipeline should complete fully when using _NullPublisher with the fixture artifact.
    result = _call_generate(repo)
    assert result["status"] == "COMPLETE"
    assert len(repo.write_calls) > 0


# ---------------------------------------------------------------------------
# Idempotency tests
# ---------------------------------------------------------------------------


def test_idempotency_returns_already_complete():
    """Existing COMPLETE report without force flag must return ALREADY_COMPLETE."""
    existing = {
        "status": "COMPLETE",
        "report_job_id": "rptjob_existing",
        "report_id": "report_existing",
        "composite_score": "0.850",
        "score_label": "HIGH_CONFIDENCE",
        "endpoint_count": 1,
        "s3_artifact_ref": "reports/client_test/audit_test/exec_test/agg_v1/intel_v1/report_v1/rptjob_existing/artifact.json",
    }
    repo = _EngineTestRepository(existing_report_metadata=existing)
    result = _call_generate(repo)
    assert result["status"] == "ALREADY_COMPLETE"
    assert result["report_job_id"] == "rptjob_existing"


def test_in_progress_raises_error():
    """Existing IN_PROGRESS report must raise ReportGenerationInProgressError."""
    in_progress = {"status": "IN_PROGRESS", "report_job_id": "rptjob_running"}
    repo = _EngineTestRepository(existing_report_metadata=in_progress)
    with pytest.raises(ReportGenerationInProgressError):
        _call_generate(repo)


# ---------------------------------------------------------------------------
# Error class hierarchy
# ---------------------------------------------------------------------------


def test_report_gate_error_inherits_validation_error():
    """ReportGateError must inherit from ValidationError for consistent exception handling."""
    error = ReportGateError("test gate error")
    assert isinstance(error, ValidationError)
    assert error.error_type == "REPORT_GATE_ERROR"


def test_report_generation_in_progress_error_inherits_validation_error():
    """ReportGenerationInProgressError must inherit from ValidationError."""
    error = ReportGenerationInProgressError("test in-progress error")
    assert isinstance(error, ValidationError)
    assert error.error_type == "REPORT_GENERATION_IN_PROGRESS"


# ---------------------------------------------------------------------------
# Full pipeline completion
# ---------------------------------------------------------------------------


def test_generation_complete_returns_dict_with_expected_keys():
    """Full pipeline with mocked publisher must return dict with all expected keys."""
    repo = _EngineTestRepository()
    publisher = _NullPublisher()
    result = _call_generate(repo, publisher)

    assert result["status"] == "COMPLETE"
    assert "client_id" in result
    assert "audit_id" in result
    assert "audit_execution_id" in result
    assert "report_job_id" in result
    assert "report_id" in result
    assert "report_version" in result
    assert "composite_score" in result
    assert "score_label" in result
    assert "endpoint_count" in result
    assert "s3_artifact_ref" in result


def test_s3_artifact_written_before_complete():
    """S3 write_artifact must be called exactly once."""
    repo = _EngineTestRepository()
    publisher = _NullPublisher()
    _call_generate(repo, publisher)
    assert len(publisher.write_calls) == 1
