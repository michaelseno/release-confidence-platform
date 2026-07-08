"""Test: CertificationEngine never writes to Phase 6 DynamoDB SK namespaces.

NFR — Phase 6 non-mutation invariant.

All write calls on the repository are intercepted and verified to ensure the SK
contains only Phase 7 markers (#CERTJOB# or #CERT#) and never any exclusively
Phase 6 markers (#RPTJOB#).

This mirrors test_engine_no_phase5_mutation.py from Phase 6.

SK selection note:
  The Phase 7 CertificationMetadata SK necessarily contains #AGG#, #INTEL#, and #RPT#
  as structural scope qualifiers (e.g., ...#AGG#{agg_v}#INTEL#{intel_v}#RPT#{rpt_v}
  #CERT#{cert_v}#META). These markers are shared between Phase 6 and Phase 7 SK
  structures. Including them in _PHASE6_PROHIBITED would incorrectly flag legitimate
  Phase 7 CertificationMetadata writes.

  Only markers that are EXCLUSIVELY Phase 6 record types — with no presence in
  any Phase 7 SK pattern — belong in the prohibited list:
    #RPTJOB# → ReportJob records (AUDIT#{id}#RPTJOB#{job_id})

  The _PHASE7_ALLOWED check (every write must contain #CERTJOB# or #CERT#) is
  the primary invariant enforcement mechanism.
"""

from __future__ import annotations

from typing import Any

from release_confidence_platform.audit_platform_integrity.engine import CertificationEngine

# ---------------------------------------------------------------------------
# Phase 6 prohibited SK markers — must NEVER appear in Phase 7 write calls
# ---------------------------------------------------------------------------

_PHASE6_PROHIBITED = (
    "#RPTJOB#",  # ReportJob records — never a write target for Phase 7
    "#INTJOB#",  # IntelligenceJob records — never a write target for Phase 7
)

# Phase 7 allowed SK markers — all writes must contain at least one of these
_PHASE7_ALLOWED = ("#CERTJOB#", "#CERT#")

# ---------------------------------------------------------------------------
# Phase 6 report artifact fixture (full valid report)
# ---------------------------------------------------------------------------

_REPORT_ARTIFACT = {
    "identity": {
        "report_id": "report_mutationtest",
        "report_version": "report_v1",
        "generated_at": "2026-07-05T12:00:00Z",
        "generator_version": "1.0.0",
    },
    "intelligence_provenance": {
        "intelligence_version": "intel_v1",
        "intelligence_job_id": "intjob_mutationtest",
        "client_id": "client1",
        "audit_id": "audit1",
        "audit_execution_id": "exec1",
        "config_version": "cfg_v1",
        "aggregation_version": "agg_v1",
        "aggregate_set_hash": "hashMUTATION",
        "intelligence_completed_at": "2026-07-05T11:00:00Z",
    },
    "executive_summary": {
        "score_label": "HIGH_CONFIDENCE",
        "composite_score_value": 0.850,
        "endpoint_count": 1,
        "audit_success_rate": 0.900,
        "total_executions": 20,
        "score_label_description": (
            "Reliability indicators across all assessed endpoints are strong. "
            "The observed evidence does not indicate material reliability concerns "
            "for the audited release scope."
        ),
    },
    "audit_reliability_overview": {
        "total_executions": 20,
        "total_pass": 18,
        "total_fail": 2,
        "total_timeout": 1,
        "total_network_failure": 0,
        "audit_success_rate": 0.9,
        "endpoint_count": 1,
        "audit_latency_mean_ms": 120.0,
        "audit_latency_p95_ms": 400.0,
        "audit_latency_p99_ms": 480.0,
        "source_field_refs": {"total_executions": "AuditAggregate.request_counts.total"},
    },
    "composite_score": {
        "value": 0.850,
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
                "success_rate": 0.9,
                "success_rate_numerator": 18,
                "success_rate_denominator": 20,
                "latency_min_ms": 50.0,
                "latency_max_ms": 500.0,
                "latency_mean_ms": 120.0,
                "latency_median_ms": 100.0,
                "latency_p95_ms": 400.0,
                "latency_p99_ms": 480.0,
                "latency_count": 20,
                "failure_classification_breakdown": {"PASS": 18, "TIMEOUT": 1},
                "http_response_distribution": {"200": 18, "504": 2},
                "source_field_refs": {"execution_count": "EndpointAggregate.execution_count"},
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
                "composite_score": 0.850,
                "reliability_score": 0.900,
                "stability_score": 1.000,
                "burst_score": 1.000,
                "consistency_score": 1.000,
                "score_derivation": {"method": "weighted_average"},
            },
        }
    ],
    "input_lineage": {
        "aggregate_set_hash": "hashMUTATION",
        "aggregation_job_id": "aggjob_MUTATION",
        "aggregation_version": "agg_v1",
        "aggregate_set_completion_created_at": "2026-07-05T10:00:00Z",
        "endpoint_aggregate_count": 1,
        "source_raw_result_count": 20,
        "audit_lineage_manifest_ref": {},
    },
    "methodology_disclosure": {
        "intelligence_version": "intel_v1",
        "scoring": {"method": "composite"},
        "stability_label_definitions": {"STABLE": "stable definition"},
        "burst_label_definitions": {"NO_BURST": "no burst definition"},
        "consistency_label_definitions": {"CONSISTENT": "consistent definition"},
        "label_to_score_mapping": {"HIGH_CONFIDENCE": 0.9},
        "limitations": [],
    },
}

_COMPLETE_REPORT_METADATA = {
    "status": "COMPLETE",
    "report_id": "report_mutationtest",
    "report_version": "report_v1",
    "intelligence_version": "intel_v1",
    "aggregate_set_hash": "hashMUTATION",
    "endpoint_count": 1,
    "s3_artifact_ref": "reports/client1/audit1/exec1/agg_v1/intel_v1/report_v1/rptjob_mut/artifact.json",
    "completed_at": "2026-07-05T12:00:00Z",
}


# ---------------------------------------------------------------------------
# Tracking repository
# ---------------------------------------------------------------------------


class _TrackingRepository:
    """Repository that tracks all write calls and asserts Phase 6 SK invariants."""

    def __init__(self) -> None:
        self.write_calls: list[tuple[str, dict]] = []

    def get_report_metadata(self, *args, **kwargs) -> dict[str, Any]:
        return _COMPLETE_REPORT_METADATA

    def get_cert_metadata(self, *args, **kwargs) -> dict[str, Any] | None:
        return None

    def read_report_artifact(self, s3_artifact_ref: str) -> dict[str, Any]:
        return _REPORT_ARTIFACT

    def write_certjob_pending(
        self, client_id: str, audit_id: str, certjob_id: str, identity_tuple: dict
    ) -> None:
        sk = f"AUDIT#{audit_id}#CERTJOB#{certjob_id}"
        self._assert_phase7_sk("write_certjob_pending", sk)
        self.write_calls.append(("write_certjob_pending", {"SK": sk}))

    def update_certjob_in_progress(
        self, client_id: str, audit_id: str, certjob_id: str
    ) -> None:
        sk = f"AUDIT#{audit_id}#CERTJOB#{certjob_id}"
        self._assert_phase7_sk("update_certjob_in_progress", sk)
        self.write_calls.append(("update_certjob_in_progress", {"SK": sk}))

    def update_certjob_complete(
        self, client_id: str, audit_id: str, certjob_id: str,
        terminal_state: str, s3_ref: str
    ) -> None:
        sk = f"AUDIT#{audit_id}#CERTJOB#{certjob_id}"
        self._assert_phase7_sk("update_certjob_complete", sk)
        self.write_calls.append(("update_certjob_complete", {"SK": sk}))

    def update_certjob_failed(
        self, client_id: str, audit_id: str, certjob_id: str, error: str
    ) -> None:
        sk = f"AUDIT#{audit_id}#CERTJOB#{certjob_id}"
        self._assert_phase7_sk("update_certjob_failed", sk)
        self.write_calls.append(("update_certjob_failed", {"SK": sk}))

    def write_cert_metadata_complete(self, **kwargs) -> None:
        audit_id = kwargs["audit_id"]
        audit_execution_id = kwargs["audit_execution_id"]
        config_version = kwargs["config_version"]
        aggregation_version = kwargs["aggregation_version"]
        intelligence_version = kwargs["intelligence_version"]
        report_version = kwargs["report_version"]
        cert_version = kwargs["cert_version"]
        client_id = kwargs["client_id"]
        sk = (
            f"AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}"
            f"#AGG#{aggregation_version}#INTEL#{intelligence_version}"
            f"#RPT#{report_version}#CERT#{cert_version}#META"
        )
        self._assert_phase7_sk("write_cert_metadata_complete", sk)
        self.write_calls.append(("write_cert_metadata_complete", {"SK": sk}))

    def _assert_phase7_sk(self, method_name: str, sk: str) -> None:
        for prohibited in _PHASE6_PROHIBITED:
            assert prohibited not in sk, (
                f"Phase 6 mutation detected! Method={method_name!r} attempted to write "
                f"to Phase 6 SK namespace. SK={sk!r} contains prohibited marker {prohibited!r}. "
                "Phase 7 writes must only target #CERTJOB# or #CERT# SK patterns."
            )
        assert any(allowed in sk for allowed in _PHASE7_ALLOWED), (
            f"Phase 7 write target must contain #CERTJOB# or #CERT#. "
            f"Method={method_name!r}, SK={sk!r}"
        )


# ---------------------------------------------------------------------------
# Tracking publisher
# ---------------------------------------------------------------------------


class _TrackingPublisher:
    def __init__(self) -> None:
        self.write_calls: list[tuple[str, dict]] = []

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        self.write_calls.append((key, artifact))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_engine() -> tuple[_TrackingRepository, _TrackingPublisher]:
    repo = _TrackingRepository()
    publisher = _TrackingPublisher()
    engine = CertificationEngine(
        repository=repo,
        publisher=publisher,
        platform_version="mutation_test_1.0.0",
    )
    engine.certify(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        intelligence_version="intel_v1",
        report_version="report_v1",
        cert_version="cert_v1",
    )
    return repo, publisher


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_no_phase6_writes_during_certification():
    """All Phase 7 writes must target only #CERTJOB# or #CERT# SK namespaces.

    If _assert_phase7_sk did not raise, all writes are Phase 7-only.
    """
    repo, publisher = _run_engine()
    assert len(repo.write_calls) > 0, "Expected at least one write call"
    for method_name, item in repo.write_calls:
        sk = item.get("SK", "")
        assert any(allowed in sk for allowed in _PHASE7_ALLOWED), (
            f"Write targeted non-Phase-7 SK: method={method_name!r}, SK={sk!r}"
        )


def test_write_call_count_includes_certjob_and_cert_metadata():
    """Certification must write CertificationJob records and CertificationMetadata."""
    repo, publisher = _run_engine()
    methods = [call[0] for call in repo.write_calls]
    assert "write_certjob_pending" in methods, (
        f"write_certjob_pending not found in write calls: {methods}"
    )
    assert "write_cert_metadata_complete" in methods, (
        f"write_cert_metadata_complete not found in write calls: {methods}"
    )


def test_s3_write_uses_integrity_prefix():
    """S3 certificate artifact write must use the integrity/ prefix."""
    _, publisher = _run_engine()
    assert len(publisher.write_calls) == 1
    key, _ = publisher.write_calls[0]
    assert key.startswith("integrity/"), (
        f"S3 write used non-integrity/ prefix: {key!r}"
    )


def test_no_phase6_rptjob_sk_in_any_write():
    """No write call must contain #RPTJOB# in its SK — that is an exclusively Phase 6 marker."""
    repo, _ = _run_engine()
    for method_name, item in repo.write_calls:
        sk = item.get("SK", "")
        assert "#RPTJOB#" not in sk, (
            f"Phase 6 #RPTJOB# found in write call: method={method_name!r}, SK={sk!r}"
        )
