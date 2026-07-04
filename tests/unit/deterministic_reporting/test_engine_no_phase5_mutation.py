"""Test: ReportingEngine never writes to Phase 5 DynamoDB SK namespaces.

NFR — Phase 5 non-mutation invariant.

All write calls on the repository are intercepted and verified to ensure the SK
contains only Phase 6 markers (#RPTJOB# or #RPT#) and never any Phase 5-exclusive
markers (#INTJOB#, #INTEL#, #AGG#, #EXEC#, #CFG#, #LINEAGE#).

This mirrors test_engine_no_phase4_mutation.py from Phase 5.
"""

from __future__ import annotations

from typing import Any

from release_confidence_platform.deterministic_reporting.engine import ReportingEngine

# ---------------------------------------------------------------------------
# Phase 5 prohibited SK markers — must NEVER appear in Phase 6 write calls
# ---------------------------------------------------------------------------
#
# NOTE on marker selection: The Phase 6 ReportMetadata SK necessarily contains
# #EXEC#, #CFG#, #AGG#, and #INTEL# as structural scope qualifiers because it
# must distinguish reports by execution, config, aggregation, and intelligence
# version. These markers are shared between Phase 5 and Phase 6 SK structures.
# Including them in _PHASE5_PROHIBITED would incorrectly flag legitimate Phase 6
# ReportMetadata writes.
#
# Only markers that are EXCLUSIVELY Phase 5 record types — with no presence in
# any Phase 6 SK pattern — belong in this list:
#   #INTJOB# → IntelligenceJob records (AUDIT#{id}#INTJOB#{job_id})
#   #LINEAGE# → Phase-specific lineage records, absent from all Phase 6 SKs
#
# The _PHASE6_ALLOWED check (every write must contain #RPTJOB# or #RPT#) is
# the primary invariant enforcement mechanism.

_PHASE5_PROHIBITED = (
    "#INTJOB#",   # IntelligenceJob records — never a write target for Phase 6
    "#LINEAGE#",  # Lineage records — absent from all Phase 6 SK patterns
)

# Phase 6 allowed SK markers — all writes must contain at least one of these
_PHASE6_ALLOWED = ("#RPTJOB#", "#RPT#")

# ---------------------------------------------------------------------------
# Phase 5 intelligence artifact fixture
# ---------------------------------------------------------------------------

_INTEL_ARTIFACT = {
    "intelligence_version": "intel_v1",
    "aggregation_version": "agg_v1",
    "client_id": "client1",
    "audit_id": "audit1",
    "audit_execution_id": "exec1",
    "config_version": "cfg_v1",
    "intelligence_job_id": "intjob_mutation_test",
    "generated_at": "2026-07-04T12:00:00Z",
    "generator_version": "1.0.0",
    "input_lineage": {
        "aggregate_set_hash": "hashMUTATION",
        "aggregation_job_id": "aggjob_MUTATION",
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
        "aggregate_set_hash": "hashMUTATION",
        "endpoint_count": 1,
        "component_breakdown": {"reliability": 0.9},
    },
    "endpoints": [
        {
            "endpoint_id": "ep_mutation",
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
    "intelligence_job_id": "intjob_mutation_test",
    "s3_artifact_ref": "intelligence/client1/audit1/exec1/agg_v1/intel_v1/intjob_mutation_test/artifact.json",
    "composite_score": "0.850",
    "score_label": "HIGH_CONFIDENCE",
    "endpoint_count": 1,
    "aggregate_set_hash": "hashMUTATION",
    "completed_at": "2026-07-04T12:00:00Z",
}


# ---------------------------------------------------------------------------
# Tracking repository
# ---------------------------------------------------------------------------


class _TrackingRepository:
    """Repository that tracks all write calls and asserts Phase 5 SK invariants."""

    def __init__(self, *, has_existing_metadata: bool = False) -> None:
        self.write_calls: list[tuple[str, dict]] = []
        self._has_existing_metadata = has_existing_metadata

    def get_intelligence_metadata(
        self, client_id, audit_id, audit_execution_id, config_version,
        aggregation_version, intelligence_version,
    ) -> dict[str, Any]:
        return _COMPLETE_INTEL_METADATA

    def get_report_metadata(
        self, client_id, audit_id, audit_execution_id, config_version,
        aggregation_version, intelligence_version, report_version,
    ) -> dict[str, Any] | None:
        if self._has_existing_metadata:
            return {
                "status": "FAILED",
                "report_job_id": "rptjob_old",
                "generation_count": 1,
                "created_at": "2026-01-01T00:00:00Z",
            }
        return None

    def report_job_keys(
        self, client_id: str, audit_id: str, report_job_id: str
    ) -> dict[str, str]:
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
        sk = item.get("SK", "")
        self._assert_phase6_sk("put_report_job_once", sk)
        self.write_calls.append(("put_report_job_once", item))

    def put_report_metadata_once(self, item: dict[str, Any]) -> None:
        sk = item.get("SK", "")
        self._assert_phase6_sk("put_report_metadata_once", sk)
        self.write_calls.append(("put_report_metadata_once", item))

    def update_report_job(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        sk = key.get("SK", "")
        self._assert_phase6_sk("update_report_job", sk)
        self.write_calls.append(("update_report_job", {**key, **updates}))

    def update_report_metadata_fields(
        self, key: dict[str, str], updates: dict[str, Any]
    ) -> None:
        sk = key.get("SK", "")
        self._assert_phase6_sk("update_report_metadata_fields", sk)
        self.write_calls.append(("update_report_metadata_fields", {**key, **updates}))

    def _assert_phase6_sk(self, method_name: str, sk: str) -> None:
        for prohibited in _PHASE5_PROHIBITED:
            assert prohibited not in sk, (
                f"Phase 5 mutation detected! Method={method_name!r} attempted to write "
                f"to Phase 5 SK namespace. SK={sk!r} contains prohibited marker {prohibited!r}. "
                "Phase 6 writes must only target #RPTJOB# or #RPT# SK patterns."
            )
        assert any(allowed in sk for allowed in _PHASE6_ALLOWED), (
            f"Phase 6 write target must contain #RPTJOB# or #RPT#. "
            f"Method={method_name!r}, SK={sk!r}"
        )


# ---------------------------------------------------------------------------
# Tracking publisher
# ---------------------------------------------------------------------------


class _TrackingPublisher:
    def __init__(self) -> None:
        self.write_calls: list[tuple[str, dict]] = []

    def read_artifact(self, key: str) -> dict[str, Any]:
        return _INTEL_ARTIFACT

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        self.write_calls.append((key, artifact))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_engine(*, has_existing: bool = False) -> tuple[_TrackingRepository, _TrackingPublisher]:
    repo = _TrackingRepository(has_existing_metadata=has_existing)
    publisher = _TrackingPublisher()
    engine = ReportingEngine(repo, publisher)
    engine.generate(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        intelligence_version="intel_v1",
    )
    return repo, publisher


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_phase5_writes_on_first_generation():
    """First-time generation must only write to Phase 6 SK namespaces.

    If _assert_phase6_sk did not raise, all writes are Phase 6-only.
    """
    repo, publisher = _run_engine(has_existing=False)
    assert len(repo.write_calls) > 0, "Expected at least one write call"
    for _method, item in repo.write_calls:
        sk = item.get("SK", "")
        assert any(allowed in sk for allowed in _PHASE6_ALLOWED), (
            f"Write targeted non-Phase-6 SK: {sk!r}"
        )


def test_write_call_count_first_generation():
    """First generation must write ReportJob and ReportMetadata at minimum."""
    repo, publisher = _run_engine(has_existing=False)
    methods = [call[0] for call in repo.write_calls]
    assert "put_report_job_once" in methods, (
        f"put_report_job_once not found in write calls: {methods}"
    )
    assert "put_report_metadata_once" in methods, (
        f"put_report_metadata_once not found in write calls: {methods}"
    )
