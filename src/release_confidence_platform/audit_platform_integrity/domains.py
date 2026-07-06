"""Certification domain executor functions for Phase 7 Audit Platform Integrity.

Each function is a pure, stateless verification unit. Functions accept deserialized
Phase 6 artifact data and return a CertificationDomainResult. No I/O, no side
effects, no external service calls.

Domain identifiers and check counts per technical design Section 6 and QA validation
spec Sections 4.1–4.8:

  RUNNER_HEALTH           — 4 checks (RH-1 through RH-4)
  EVIDENCE_COMPLETENESS   — 4 checks (EC-1 through EC-4)
  EVIDENCE_INTEGRITY      — 5 checks (EI-1 through EI-5)
  EVIDENCE_LINEAGE        — 5 checks (EL-1 through EL-5)
  OBSERVATION_COVERAGE    — 5 checks (OC-1 through OC-5)
  SCHEDULER_INTEGRITY     — 3 checks (SI-1 through SI-3)
  METHODOLOGY_COMPLIANCE  — 5 checks (MC-1 through MC-5)
  REPORT_INTEGRITY        — 9 checks (RI-1 through RI-9)

BLOCKED status is returned only when a required top-level section is absent or None,
preventing the domain from executing its checks. Individual field-level failures
produce FAILED status, not BLOCKED.

All field name references use the actual ReleaseConfidenceReport Pydantic model
attribute names (e.g., execution_count, pass_count, fail_count, success_rate) as
defined in deterministic_reporting.models.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from release_confidence_platform.audit_platform_integrity.models import (
    CertificationDomainResult,
)
from release_confidence_platform.deterministic_reporting.constants import (
    REPORT_VERSION,
    SCORE_LABEL_BOUNDED_SET,
    SCORE_LABEL_DESCRIPTIONS,
)
from release_confidence_platform.deterministic_reporting.models import (
    ReleaseConfidenceReport,
)

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Intelligence version constant — checked in RI-2 and EI-4
_INTEL_V1 = "intel_v1"

# Required input_lineage fields per InputLineageSection model in
# deterministic_reporting.models (EL-4 check)
_REQUIRED_INPUT_LINEAGE_FIELDS: tuple[str, ...] = (
    "aggregate_set_hash",
    "aggregation_job_id",
    "aggregation_version",
    "aggregate_set_completion_created_at",
    "endpoint_aggregate_count",
    "source_raw_result_count",
    "audit_lineage_manifest_ref",
)

# Required methodology_disclosure fields per MethodologyDisclosure model (MC-2 check)
_REQUIRED_METHODOLOGY_DISCLOSURE_FIELDS: tuple[str, ...] = (
    "intelligence_version",
    "scoring",
    "stability_label_definitions",
    "burst_label_definitions",
    "consistency_label_definitions",
    "label_to_score_mapping",
    "limitations",
)

# Required report_metadata keys used by integrity and lineage domains
_REQUIRED_METADATA_KEYS_INTEGRITY: tuple[str, ...] = (
    "report_id",
    "report_version",
    "intelligence_version",
    "aggregate_set_hash",
    "endpoint_count",
)

_REQUIRED_METADATA_KEYS_LINEAGE: tuple[str, ...] = (
    "aggregate_set_hash",
)

_REQUIRED_METADATA_KEYS_COVERAGE: tuple[str, ...] = (
    "endpoint_count",
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _has_at_most_3_decimal_places(value: float) -> bool:
    """Return True if value can be expressed with at most 3 decimal places.

    Uses an epsilon of 1e-9 to accommodate float representation rounding.
    """
    return abs(value - round(value, 3)) < 1e-9


def _blocked(domain: str, reason: str, evidence_refs: list[str]) -> CertificationDomainResult:
    """Return a BLOCKED CertificationDomainResult with zero checks performed."""
    return CertificationDomainResult(
        domain=domain,
        status="BLOCKED",
        checks_performed=0,
        checks_passed=0,
        failure_details=[reason],
        evidence_refs=evidence_refs,
    )


def _result(
    domain: str,
    checks_performed: int,
    checks_passed: int,
    failure_details: list[str],
    evidence_refs: list[str],
) -> CertificationDomainResult:
    """Return a PASSED or FAILED CertificationDomainResult based on failure_details."""
    status = "PASSED" if not failure_details else "FAILED"
    return CertificationDomainResult(
        domain=domain,
        status=status,
        checks_performed=checks_performed,
        checks_passed=checks_passed,
        failure_details=failure_details,
        evidence_refs=evidence_refs,
    )


# ---------------------------------------------------------------------------
# Domain: RUNNER_HEALTH
# ---------------------------------------------------------------------------


def check_runner_health(report: ReleaseConfidenceReport) -> CertificationDomainResult:
    """RUNNER_HEALTH domain — verify runner operated within expected health parameters.

    Checks performed: 4 (RH-1 through RH-4)

    RH-1: executive_summary.total_executions > 0
    RH-2: No endpoint has reliability_metrics.execution_count == 0
    RH-3: No endpoint has fail_count / execution_count outside [0.0, 1.0]
    RH-4: methodology_trace present and non-null in stability, burst, and
          consistency analysis sub-sections for all endpoints
    """
    domain = "RUNNER_HEALTH"
    evidence_refs = [
        "executive_summary.total_executions",
        "endpoints[*].reliability_metrics",
        "methodology_disclosure",
    ]

    endpoints = getattr(report, "endpoints", None)
    methodology_disclosure = getattr(report, "methodology_disclosure", None)
    executive_summary = getattr(report, "executive_summary", None)

    if endpoints is None or methodology_disclosure is None or executive_summary is None:
        return _blocked(
            domain,
            "Required section absent or None: one or more of endpoints, "
            "methodology_disclosure, executive_summary is None",
            evidence_refs,
        )

    failure_details: list[str] = []
    checks_performed = 0
    checks_passed = 0

    # RH-1: total_executions > 0
    checks_performed += 1
    if executive_summary.total_executions > 0:
        checks_passed += 1
    else:
        failure_details.append(
            f"RH-1: executive_summary.total_executions must be > 0, "
            f"got {executive_summary.total_executions}"
        )

    # RH-2: No endpoint has execution_count == 0
    checks_performed += 1
    zero_exec = [
        ep.endpoint_id
        for ep in endpoints
        if ep.reliability_metrics.execution_count == 0
    ]
    if not zero_exec:
        checks_passed += 1
    else:
        failure_details.append(
            f"RH-2: endpoints with zero execution_count (no observations): {zero_exec}"
        )

    # RH-3: Failure rate (fail_count / execution_count) must be in [0.0, 1.0]
    checks_performed += 1
    invalid_rate = []
    for ep in endpoints:
        rm = ep.reliability_metrics
        if rm.execution_count > 0:
            rate = rm.fail_count / rm.execution_count
            if rate < 0.0 or rate > 1.0:
                invalid_rate.append(
                    f"{ep.endpoint_id} (fail_count={rm.fail_count}, "
                    f"execution_count={rm.execution_count}, rate={rate:.6f})"
                )
    if not invalid_rate:
        checks_passed += 1
    else:
        failure_details.append(
            f"RH-3: endpoints with invalid failure rate outside [0.0, 1.0]: {invalid_rate}"
        )

    # RH-4: methodology_trace present and non-null in all three per-endpoint analysis sections
    checks_performed += 1
    missing_trace = []
    for ep in endpoints:
        sa_trace = getattr(ep.stability_analysis, "methodology_trace", None)
        ba_trace = getattr(ep.burst_analysis, "methodology_trace", None)
        ca_trace = getattr(ep.consistency_analysis, "methodology_trace", None)
        if sa_trace is None or ba_trace is None or ca_trace is None:
            missing_trace.append(ep.endpoint_id)
    if not missing_trace:
        checks_passed += 1
    else:
        failure_details.append(
            f"RH-4: endpoints with absent or null methodology_trace in analysis "
            f"sub-sections: {missing_trace}"
        )

    return _result(domain, checks_performed, checks_passed, failure_details, evidence_refs)


# ---------------------------------------------------------------------------
# Domain: EVIDENCE_COMPLETENESS
# ---------------------------------------------------------------------------


def check_evidence_completeness(report: ReleaseConfidenceReport) -> CertificationDomainResult:
    """EVIDENCE_COMPLETENESS domain — verify evidence base is complete.

    Checks performed: 4 (EC-1 through EC-4)

    EC-1: executive_summary.total_executions > 0
    EC-2: No endpoint has reliability_metrics.execution_count == 0
    EC-3: All required reliability_metrics fields (execution_count, pass_count,
          fail_count, success_rate) are present and non-null for every endpoint
    EC-4: executive_summary.endpoint_count > 0
    """
    domain = "EVIDENCE_COMPLETENESS"
    evidence_refs = [
        "executive_summary.total_executions",
        "executive_summary.endpoint_count",
        "endpoints[*].reliability_metrics",
        "methodology_disclosure",
    ]

    executive_summary = getattr(report, "executive_summary", None)
    endpoints = getattr(report, "endpoints", None)
    methodology_disclosure = getattr(report, "methodology_disclosure", None)

    if executive_summary is None or endpoints is None or methodology_disclosure is None:
        return _blocked(
            domain,
            "Required section absent or None: one or more of executive_summary, "
            "endpoints, methodology_disclosure is None",
            evidence_refs,
        )

    failure_details: list[str] = []
    checks_performed = 0
    checks_passed = 0

    # EC-1: total_executions > 0
    checks_performed += 1
    if executive_summary.total_executions > 0:
        checks_passed += 1
    else:
        failure_details.append(
            f"EC-1: executive_summary.total_executions must be > 0, "
            f"got {executive_summary.total_executions}"
        )

    # EC-2: No endpoint has execution_count == 0
    checks_performed += 1
    zero_exec = [
        ep.endpoint_id
        for ep in endpoints
        if ep.reliability_metrics.execution_count == 0
    ]
    if not zero_exec:
        checks_passed += 1
    else:
        failure_details.append(
            f"EC-2: endpoints with execution_count == 0 (below minimum): {zero_exec}"
        )

    # EC-3: Required reliability_metrics fields present and non-null for every endpoint.
    # execution_count, pass_count, fail_count are non-Optional in the model.
    # success_rate is Optional[float]; it must be non-null.
    checks_performed += 1
    missing_fields = []
    for ep in endpoints:
        rm = ep.reliability_metrics
        null_fields = []
        if getattr(rm, "execution_count", None) is None:
            null_fields.append("execution_count")
        if getattr(rm, "pass_count", None) is None:
            null_fields.append("pass_count")
        if getattr(rm, "fail_count", None) is None:
            null_fields.append("fail_count")
        if getattr(rm, "success_rate", None) is None:
            null_fields.append("success_rate")
        if null_fields:
            missing_fields.append(f"{ep.endpoint_id}: {null_fields}")
    if not missing_fields:
        checks_passed += 1
    else:
        failure_details.append(
            f"EC-3: endpoints with null required reliability_metrics fields: {missing_fields}"
        )

    # EC-4: endpoint_count > 0
    checks_performed += 1
    if executive_summary.endpoint_count > 0:
        checks_passed += 1
    else:
        failure_details.append(
            f"EC-4: executive_summary.endpoint_count must be > 0, "
            f"got {executive_summary.endpoint_count}"
        )

    return _result(domain, checks_performed, checks_passed, failure_details, evidence_refs)


# ---------------------------------------------------------------------------
# Domain: EVIDENCE_INTEGRITY
# ---------------------------------------------------------------------------


def check_evidence_integrity(
    report: ReleaseConfidenceReport,
    report_metadata: dict,
) -> CertificationDomainResult:
    """EVIDENCE_INTEGRITY domain — verify report artifact is intact vs ReportMetadata.

    Checks performed: 5 (EI-1 through EI-5)

    EI-1: intelligence_provenance.aggregate_set_hash matches ReportMetadata.aggregate_set_hash
    EI-2: identity.report_id matches ReportMetadata.report_id
    EI-3: identity.report_version matches ReportMetadata.report_version
    EI-4: intelligence_provenance.intelligence_version matches ReportMetadata.intelligence_version
    EI-5: ReportMetadata.endpoint_count matches executive_summary.endpoint_count
    """
    domain = "EVIDENCE_INTEGRITY"
    evidence_refs = [
        "identity.report_id",
        "identity.report_version",
        "intelligence_provenance.intelligence_version",
        "intelligence_provenance.aggregate_set_hash",
        "executive_summary.endpoint_count",
        "ReportMetadata.report_id",
        "ReportMetadata.report_version",
        "ReportMetadata.intelligence_version",
        "ReportMetadata.aggregate_set_hash",
        "ReportMetadata.endpoint_count",
    ]

    # Check report_metadata for required keys
    missing_meta_keys = [
        k for k in _REQUIRED_METADATA_KEYS_INTEGRITY if k not in report_metadata
    ]
    if missing_meta_keys:
        return _blocked(
            domain,
            f"Required ReportMetadata keys absent: {missing_meta_keys}",
            evidence_refs,
        )

    identity = getattr(report, "identity", None)
    intel_prov = getattr(report, "intelligence_provenance", None)
    executive_summary = getattr(report, "executive_summary", None)

    if identity is None or intel_prov is None or executive_summary is None:
        return _blocked(
            domain,
            "Required report section absent or None: one or more of identity, "
            "intelligence_provenance, executive_summary is None",
            evidence_refs,
        )

    failure_details: list[str] = []
    checks_performed = 0
    checks_passed = 0

    # EI-1: aggregate_set_hash cross-reference
    checks_performed += 1
    artifact_hash = getattr(intel_prov, "aggregate_set_hash", None)
    meta_hash = report_metadata["aggregate_set_hash"]
    if artifact_hash and meta_hash and artifact_hash == meta_hash:
        checks_passed += 1
    else:
        failure_details.append(
            f"EI-1: intelligence_provenance.aggregate_set_hash mismatch: "
            f"artifact={artifact_hash!r}, ReportMetadata={meta_hash!r}"
        )

    # EI-2: report_id cross-reference
    checks_performed += 1
    artifact_report_id = getattr(identity, "report_id", None)
    meta_report_id = report_metadata["report_id"]
    if artifact_report_id == meta_report_id:
        checks_passed += 1
    else:
        failure_details.append(
            f"EI-2: identity.report_id mismatch: "
            f"artifact={artifact_report_id!r}, ReportMetadata={meta_report_id!r}"
        )

    # EI-3: report_version cross-reference
    checks_performed += 1
    artifact_report_version = getattr(identity, "report_version", None)
    meta_report_version = report_metadata["report_version"]
    if artifact_report_version == meta_report_version:
        checks_passed += 1
    else:
        failure_details.append(
            f"EI-3: identity.report_version mismatch: "
            f"artifact={artifact_report_version!r}, ReportMetadata={meta_report_version!r}"
        )

    # EI-4: intelligence_version cross-reference
    checks_performed += 1
    artifact_intel_version = getattr(intel_prov, "intelligence_version", None)
    meta_intel_version = report_metadata["intelligence_version"]
    if artifact_intel_version == meta_intel_version:
        checks_passed += 1
    else:
        failure_details.append(
            f"EI-4: intelligence_provenance.intelligence_version mismatch: "
            f"artifact={artifact_intel_version!r}, ReportMetadata={meta_intel_version!r}"
        )

    # EI-5: endpoint_count cross-reference
    checks_performed += 1
    artifact_ep_count = getattr(executive_summary, "endpoint_count", None)
    meta_ep_count = report_metadata["endpoint_count"]
    if artifact_ep_count == meta_ep_count:
        checks_passed += 1
    else:
        failure_details.append(
            f"EI-5: executive_summary.endpoint_count mismatch: "
            f"artifact={artifact_ep_count!r}, ReportMetadata={meta_ep_count!r}"
        )

    return _result(domain, checks_performed, checks_passed, failure_details, evidence_refs)


# ---------------------------------------------------------------------------
# Domain: EVIDENCE_LINEAGE
# ---------------------------------------------------------------------------


def check_evidence_lineage(
    report: ReleaseConfidenceReport,
    report_metadata: dict,
) -> CertificationDomainResult:
    """EVIDENCE_LINEAGE domain — verify complete lineage chain from Phase 4 through Phase 6.

    Checks performed: 5 (EL-1 through EL-5)

    EL-1: intelligence_provenance.aggregate_set_hash present, non-null, non-empty;
          ReportMetadata.aggregate_set_hash present and non-empty
    EL-2: intelligence_provenance.aggregate_set_hash matches ReportMetadata.aggregate_set_hash
    EL-3: intelligence_provenance.intelligence_job_id present and non-null/non-empty
    EL-4: All required input_lineage fields present and non-null
    EL-5: intelligence_provenance.intelligence_completed_at is a valid UTC ISO-8601 timestamp
    """
    domain = "EVIDENCE_LINEAGE"
    evidence_refs = [
        "intelligence_provenance.aggregate_set_hash",
        "intelligence_provenance.intelligence_job_id",
        "intelligence_provenance.intelligence_completed_at",
        "input_lineage",
        "ReportMetadata.aggregate_set_hash",
    ]

    missing_meta_keys = [
        k for k in _REQUIRED_METADATA_KEYS_LINEAGE if k not in report_metadata
    ]
    if missing_meta_keys:
        return _blocked(
            domain,
            f"Required ReportMetadata keys absent: {missing_meta_keys}",
            evidence_refs,
        )

    intel_prov = getattr(report, "intelligence_provenance", None)
    input_lineage = getattr(report, "input_lineage", None)

    if intel_prov is None or input_lineage is None:
        return _blocked(
            domain,
            "Required report section absent or None: one or more of "
            "intelligence_provenance, input_lineage is None",
            evidence_refs,
        )

    failure_details: list[str] = []
    checks_performed = 0
    checks_passed = 0

    # EL-1: aggregate_set_hash present and non-empty in both artifact and ReportMetadata
    checks_performed += 1
    artifact_hash = getattr(intel_prov, "aggregate_set_hash", None)
    meta_hash = report_metadata.get("aggregate_set_hash", "")
    artifact_hash_ok = bool(artifact_hash)
    meta_hash_ok = bool(meta_hash)
    if artifact_hash_ok and meta_hash_ok:
        checks_passed += 1
    else:
        parts = []
        if not artifact_hash_ok:
            parts.append(f"intelligence_provenance.aggregate_set_hash is absent or empty ({artifact_hash!r})")
        if not meta_hash_ok:
            parts.append(f"ReportMetadata.aggregate_set_hash is absent or empty ({meta_hash!r})")
        failure_details.append(f"EL-1: {'; '.join(parts)}")

    # EL-2: hash consistency — artifact matches ReportMetadata
    checks_performed += 1
    if artifact_hash and meta_hash and artifact_hash == meta_hash:
        checks_passed += 1
    else:
        failure_details.append(
            f"EL-2: lineage hash mismatch: "
            f"intelligence_provenance.aggregate_set_hash={artifact_hash!r}, "
            f"ReportMetadata.aggregate_set_hash={meta_hash!r}"
        )

    # EL-3: intelligence_job_id present and non-empty
    checks_performed += 1
    intelligence_job_id = getattr(intel_prov, "intelligence_job_id", None)
    if intelligence_job_id:
        checks_passed += 1
    else:
        failure_details.append(
            f"EL-3: intelligence_provenance.intelligence_job_id is absent or empty "
            f"({intelligence_job_id!r})"
        )

    # EL-4: All required input_lineage fields present and non-null
    checks_performed += 1
    null_lineage_fields = [
        field
        for field in _REQUIRED_INPUT_LINEAGE_FIELDS
        if getattr(input_lineage, field, None) is None
    ]
    if not null_lineage_fields:
        checks_passed += 1
    else:
        failure_details.append(
            f"EL-4: required input_lineage fields absent or null: {null_lineage_fields}"
        )

    # EL-5: intelligence_completed_at is a valid UTC ISO-8601 timestamp
    checks_performed += 1
    completed_at = getattr(intel_prov, "intelligence_completed_at", None)
    el5_pass = False
    if completed_at:
        try:
            parsed = datetime.fromisoformat(completed_at)
            if parsed.tzinfo is not None:
                el5_pass = True
        except (ValueError, TypeError):
            pass
    if el5_pass:
        checks_passed += 1
    else:
        failure_details.append(
            f"EL-5: intelligence_provenance.intelligence_completed_at is not a valid "
            f"UTC ISO-8601 timestamp: {completed_at!r}"
        )

    return _result(domain, checks_performed, checks_passed, failure_details, evidence_refs)


# ---------------------------------------------------------------------------
# Domain: OBSERVATION_COVERAGE
# ---------------------------------------------------------------------------


def check_observation_coverage(
    report: ReleaseConfidenceReport,
    report_metadata: dict,
) -> CertificationDomainResult:
    """OBSERVATION_COVERAGE domain — verify all endpoints observed with sufficient coverage.

    Checks performed: 5 (OC-1 through OC-5)

    OC-1: Every endpoint has all five sub-sections present and non-null
    OC-2: executive_summary.endpoint_count matches len(endpoints)
    OC-3: ReportMetadata.endpoint_count matches len(endpoints)
    OC-4: executive_summary.audit_success_rate in [0.0, 1.0] with 3 decimal places
    OC-5: executive_summary.total_executions equals sum of per-endpoint execution_counts
    """
    domain = "OBSERVATION_COVERAGE"
    evidence_refs = [
        "executive_summary.endpoint_count",
        "executive_summary.audit_success_rate",
        "executive_summary.total_executions",
        "endpoints[*].endpoint_score",
        "endpoints[*].reliability_metrics",
        "endpoints[*].stability_analysis",
        "endpoints[*].burst_analysis",
        "endpoints[*].consistency_analysis",
        "ReportMetadata.endpoint_count",
    ]

    missing_meta_keys = [
        k for k in _REQUIRED_METADATA_KEYS_COVERAGE if k not in report_metadata
    ]
    if missing_meta_keys:
        return _blocked(
            domain,
            f"Required ReportMetadata keys absent: {missing_meta_keys}",
            evidence_refs,
        )

    endpoints = getattr(report, "endpoints", None)
    executive_summary = getattr(report, "executive_summary", None)

    if endpoints is None or executive_summary is None:
        return _blocked(
            domain,
            "Required report section absent or None: one or more of endpoints, "
            "executive_summary is None",
            evidence_refs,
        )

    failure_details: list[str] = []
    checks_performed = 0
    checks_passed = 0

    # OC-1: Every endpoint has all five analysis sub-sections present and non-null
    checks_performed += 1
    missing_sections = []
    for ep in endpoints:
        absent = []
        if getattr(ep, "endpoint_score", None) is None:
            absent.append("endpoint_score")
        if getattr(ep, "reliability_metrics", None) is None:
            absent.append("reliability_metrics")
        if getattr(ep, "stability_analysis", None) is None:
            absent.append("stability_analysis")
        if getattr(ep, "burst_analysis", None) is None:
            absent.append("burst_analysis")
        if getattr(ep, "consistency_analysis", None) is None:
            absent.append("consistency_analysis")
        if absent:
            missing_sections.append(f"{ep.endpoint_id}: {absent}")
    if not missing_sections:
        checks_passed += 1
    else:
        failure_details.append(
            f"OC-1: endpoints with absent or null sub-sections: {missing_sections}"
        )

    # OC-2: executive_summary.endpoint_count matches len(endpoints)
    checks_performed += 1
    actual_count = len(endpoints)
    summary_count = executive_summary.endpoint_count
    if summary_count == actual_count:
        checks_passed += 1
    else:
        failure_details.append(
            f"OC-2: executive_summary.endpoint_count ({summary_count}) != "
            f"len(endpoints) ({actual_count})"
        )

    # OC-3: ReportMetadata.endpoint_count matches len(endpoints)
    checks_performed += 1
    meta_count = report_metadata["endpoint_count"]
    if meta_count == actual_count:
        checks_passed += 1
    else:
        failure_details.append(
            f"OC-3: ReportMetadata.endpoint_count ({meta_count}) != "
            f"len(endpoints) ({actual_count})"
        )

    # OC-4: audit_success_rate in [0.0, 1.0] with 3 decimal places
    checks_performed += 1
    asr = executive_summary.audit_success_rate
    if 0.0 <= asr <= 1.0 and _has_at_most_3_decimal_places(asr):
        checks_passed += 1
    else:
        failure_details.append(
            f"OC-4: executive_summary.audit_success_rate must be in [0.0, 1.0] with "
            f"at most 3 decimal places, got {asr}"
        )

    # OC-5: total_executions matches sum of per-endpoint execution_counts
    checks_performed += 1
    sum_ep_exec = sum(ep.reliability_metrics.execution_count for ep in endpoints)
    total = executive_summary.total_executions
    if total == sum_ep_exec:
        checks_passed += 1
    else:
        failure_details.append(
            f"OC-5: executive_summary.total_executions ({total}) != "
            f"sum of per-endpoint execution_counts ({sum_ep_exec})"
        )

    return _result(domain, checks_performed, checks_passed, failure_details, evidence_refs)


# ---------------------------------------------------------------------------
# Domain: SCHEDULER_INTEGRITY
# ---------------------------------------------------------------------------


def check_scheduler_integrity(report: ReleaseConfidenceReport) -> CertificationDomainResult:
    """SCHEDULER_INTEGRITY domain — verify scheduler produced consistent observations.

    Checks performed: 3 (SI-1 through SI-3)

    SI-1: executive_summary.total_executions > 0
    SI-2: Execution density (total_executions / endpoint_count) is consistent —
          each endpoint's execution_count is within [floor(mean), ceil(mean)]
    SI-3: methodology_disclosure.limitations is present and not None
          (scheduler anomaly disclosure check)
    """
    domain = "SCHEDULER_INTEGRITY"
    evidence_refs = [
        "executive_summary.total_executions",
        "executive_summary.endpoint_count",
        "methodology_disclosure",
        "endpoints[*].reliability_metrics.total_executions",
    ]

    methodology_disclosure = getattr(report, "methodology_disclosure", None)
    executive_summary = getattr(report, "executive_summary", None)
    endpoints = getattr(report, "endpoints", None)

    if methodology_disclosure is None or executive_summary is None or endpoints is None:
        return _blocked(
            domain,
            "Required section absent or None: one or more of methodology_disclosure, "
            "executive_summary, endpoints is None",
            evidence_refs,
        )

    failure_details: list[str] = []
    checks_performed = 0
    checks_passed = 0

    # SI-1: total_executions > 0
    checks_performed += 1
    total = executive_summary.total_executions
    if total > 0:
        checks_passed += 1
    else:
        failure_details.append(
            f"SI-1: executive_summary.total_executions must be > 0, got {total}"
        )

    # SI-2: Execution density consistency —
    # each endpoint's execution_count must be in [floor(mean), ceil(mean)]
    # where mean = total_executions / endpoint_count
    checks_performed += 1
    ep_count = executive_summary.endpoint_count
    if ep_count > 0 and total > 0:
        mean = total / ep_count
        floor_mean = math.floor(mean)
        ceil_mean = math.ceil(mean)
        uneven = []
        for ep in endpoints:
            ec = ep.reliability_metrics.execution_count
            if ec < floor_mean or ec > ceil_mean:
                uneven.append(
                    f"{ep.endpoint_id} (execution_count={ec}, "
                    f"expected [{floor_mean}, {ceil_mean}])"
                )
        if not uneven:
            checks_passed += 1
        else:
            failure_details.append(
                f"SI-2: execution density inconsistent for endpoints: {uneven}"
            )
    else:
        # Cannot compute density — fail the check
        failure_details.append(
            f"SI-2: cannot compute execution density — "
            f"total_executions={total}, endpoint_count={ep_count}"
        )

    # SI-3: methodology_disclosure.limitations present and not None
    # (scheduler anomaly disclosure availability check)
    checks_performed += 1
    limitations = getattr(methodology_disclosure, "limitations", None)
    if limitations is not None:
        checks_passed += 1
    else:
        failure_details.append(
            "SI-3: methodology_disclosure.limitations is absent or None — "
            "scheduler anomaly disclosure mechanism is unavailable"
        )

    return _result(domain, checks_performed, checks_passed, failure_details, evidence_refs)


# ---------------------------------------------------------------------------
# Domain: METHODOLOGY_COMPLIANCE
# ---------------------------------------------------------------------------


def check_methodology_compliance(report: ReleaseConfidenceReport) -> CertificationDomainResult:
    """METHODOLOGY_COMPLIANCE domain — verify methodology disclosure is complete.

    Checks performed: 5 (MC-1 through MC-5)

    MC-1: methodology_disclosure present, non-null, and non-empty
          (intelligence_version field is non-null as representative field)
    MC-2: All required methodology_disclosure fields present and non-null
    MC-3: methodology_disclosure.limitations is present (may be empty list)
    MC-4: methodology_trace present and non-null in stability, burst, and
          consistency analysis sub-sections for all endpoints
    MC-5: endpoint_score.score_derivation present and non-null for all endpoints
    """
    domain = "METHODOLOGY_COMPLIANCE"
    evidence_refs = [
        "methodology_disclosure",
        "endpoints[*].stability_analysis.methodology_trace",
        "endpoints[*].burst_analysis.methodology_trace",
        "endpoints[*].consistency_analysis.methodology_trace",
        "endpoints[*].endpoint_score.score_derivation",
    ]

    methodology_disclosure = getattr(report, "methodology_disclosure", None)
    endpoints = getattr(report, "endpoints", None)

    if methodology_disclosure is None or endpoints is None:
        return _blocked(
            domain,
            "Required section absent or None: one or more of methodology_disclosure, "
            "endpoints is None",
            evidence_refs,
        )

    failure_details: list[str] = []
    checks_performed = 0
    checks_passed = 0

    # MC-1: methodology_disclosure present and non-empty — intelligence_version non-null
    checks_performed += 1
    intel_version_present = getattr(methodology_disclosure, "intelligence_version", None)
    if intel_version_present is not None and intel_version_present != "":
        checks_passed += 1
    else:
        failure_details.append(
            "MC-1: methodology_disclosure is empty or non-substantive — "
            f"intelligence_version is absent or empty ({intel_version_present!r})"
        )

    # MC-2: All required disclosure fields present and non-null
    checks_performed += 1
    absent_fields = [
        field
        for field in _REQUIRED_METHODOLOGY_DISCLOSURE_FIELDS
        if getattr(methodology_disclosure, field, None) is None
    ]
    if not absent_fields:
        checks_passed += 1
    else:
        failure_details.append(
            f"MC-2: required methodology_disclosure fields absent or null: {absent_fields}"
        )

    # MC-3: limitations array present (may be empty but not absent)
    checks_performed += 1
    limitations = getattr(methodology_disclosure, "limitations", None)
    if limitations is not None:
        checks_passed += 1
    else:
        failure_details.append(
            "MC-3: methodology_disclosure.limitations is absent or None — "
            "limitations array must be present (may be empty)"
        )

    # MC-4: methodology_trace present and non-null in all three per-endpoint analysis sections
    checks_performed += 1
    missing_trace = []
    for ep in endpoints:
        sa_trace = getattr(ep.stability_analysis, "methodology_trace", None)
        ba_trace = getattr(ep.burst_analysis, "methodology_trace", None)
        ca_trace = getattr(ep.consistency_analysis, "methodology_trace", None)
        if sa_trace is None or ba_trace is None or ca_trace is None:
            absent_in_ep = []
            if sa_trace is None:
                absent_in_ep.append("stability_analysis.methodology_trace")
            if ba_trace is None:
                absent_in_ep.append("burst_analysis.methodology_trace")
            if ca_trace is None:
                absent_in_ep.append("consistency_analysis.methodology_trace")
            missing_trace.append(f"{ep.endpoint_id}: {absent_in_ep}")
    if not missing_trace:
        checks_passed += 1
    else:
        failure_details.append(
            f"MC-4: endpoints with absent or null methodology_trace: {missing_trace}"
        )

    # MC-5: endpoint_score.score_derivation present and non-null for all endpoints
    checks_performed += 1
    missing_derivation = [
        ep.endpoint_id
        for ep in endpoints
        if getattr(ep.endpoint_score, "score_derivation", None) is None
    ]
    if not missing_derivation:
        checks_passed += 1
    else:
        failure_details.append(
            f"MC-5: endpoints with absent or null endpoint_score.score_derivation: "
            f"{missing_derivation}"
        )

    return _result(domain, checks_performed, checks_passed, failure_details, evidence_refs)


# ---------------------------------------------------------------------------
# Domain: REPORT_INTEGRITY
# ---------------------------------------------------------------------------


def check_report_integrity(report: ReleaseConfidenceReport) -> CertificationDomainResult:
    """REPORT_INTEGRITY domain — verify report artifact is internally consistent.

    Checks performed: 9 (RI-1 through RI-9)

    RI-1: identity.report_version == 'report_v1'
    RI-2: intelligence_provenance.intelligence_version == 'intel_v1'
    RI-3: executive_summary.score_label in bounded set
    RI-4: executive_summary.composite_score_value in [0.0, 1.0] with 3 decimal places
    RI-5: endpoints[] lexicographically sorted by endpoint_id (ascending)
    RI-6: No duplicate endpoint_id values
    RI-7: No null or empty endpoint_id values
    RI-8: All numeric endpoint_score fields in [0.0, 1.0] with 3 decimal places
    RI-9: executive_summary.score_label_description in bounded value set
    """
    domain = "REPORT_INTEGRITY"
    evidence_refs = [
        "identity.report_version",
        "intelligence_provenance.intelligence_version",
        "executive_summary.score_label",
        "executive_summary.composite_score_value",
        "executive_summary.score_label_description",
        "endpoints[*].endpoint_id",
        "endpoints[*].endpoint_score.*",
    ]

    identity = getattr(report, "identity", None)
    executive_summary = getattr(report, "executive_summary", None)
    endpoints = getattr(report, "endpoints", None)

    if identity is None or executive_summary is None or endpoints is None:
        return _blocked(
            domain,
            "Required section absent or None: one or more of identity, "
            "executive_summary, endpoints is None",
            evidence_refs,
        )

    failure_details: list[str] = []
    checks_performed = 0
    checks_passed = 0

    # RI-1: report_version == 'report_v1'
    checks_performed += 1
    report_version = getattr(identity, "report_version", None)
    if report_version == REPORT_VERSION:
        checks_passed += 1
    else:
        failure_details.append(
            f"RI-1: identity.report_version: expected {REPORT_VERSION!r}, "
            f"got {report_version!r}"
        )

    # RI-2: intelligence_version == 'intel_v1'
    checks_performed += 1
    intel_prov = getattr(report, "intelligence_provenance", None)
    intel_version = getattr(intel_prov, "intelligence_version", None) if intel_prov else None
    if intel_version == _INTEL_V1:
        checks_passed += 1
    else:
        failure_details.append(
            f"RI-2: intelligence_provenance.intelligence_version: "
            f"expected {_INTEL_V1!r}, got {intel_version!r}"
        )

    # RI-3: score_label in bounded set
    checks_performed += 1
    score_label = getattr(executive_summary, "score_label", None)
    if score_label in SCORE_LABEL_BOUNDED_SET:
        checks_passed += 1
    else:
        failure_details.append(
            f"RI-3: executive_summary.score_label not in bounded set "
            f"{sorted(SCORE_LABEL_BOUNDED_SET)}: got {score_label!r}"
        )

    # RI-4: composite_score_value in [0.0, 1.0] with 3 decimal places
    checks_performed += 1
    csv = getattr(executive_summary, "composite_score_value", None)
    if csv is not None and 0.0 <= csv <= 1.0 and _has_at_most_3_decimal_places(csv):
        checks_passed += 1
    else:
        failure_details.append(
            f"RI-4: executive_summary.composite_score_value must be in [0.0, 1.0] "
            f"with at most 3 decimal places, got {csv!r}"
        )

    # RI-5: endpoints[] sorted by endpoint_id (ascending, lexicographic)
    checks_performed += 1
    endpoint_ids = [getattr(ep, "endpoint_id", None) or "" for ep in endpoints]
    is_sorted = all(
        endpoint_ids[i] <= endpoint_ids[i + 1]
        for i in range(len(endpoint_ids) - 1)
    )
    if is_sorted:
        checks_passed += 1
    else:
        failure_details.append(
            f"RI-5: endpoints[] is not lexicographically sorted by endpoint_id: "
            f"{endpoint_ids}"
        )

    # RI-6: No duplicate endpoint_id values
    checks_performed += 1
    seen: set[str] = set()
    duplicates: list[str] = []
    for eid in endpoint_ids:
        if eid in seen:
            duplicates.append(eid)
        seen.add(eid)
    if not duplicates:
        checks_passed += 1
    else:
        failure_details.append(
            f"RI-6: duplicate endpoint_id values in endpoints[]: {duplicates}"
        )

    # RI-7: No null or empty endpoint_id values
    checks_performed += 1
    null_ids = [
        i
        for i, eid in enumerate(endpoint_ids)
        if not eid
    ]
    if not null_ids:
        checks_passed += 1
    else:
        failure_details.append(
            f"RI-7: endpoints[] has null or empty endpoint_id at indices: {null_ids}"
        )

    # RI-8: All numeric endpoint_score fields in [0.0, 1.0] with 3 decimal places
    checks_performed += 1
    score_field_names = (
        "composite_score",
        "reliability_score",
        "stability_score",
        "burst_score",
        "consistency_score",
    )
    out_of_range: list[str] = []
    for ep in endpoints:
        es = getattr(ep, "endpoint_score", None)
        if es is None:
            out_of_range.append(f"{ep.endpoint_id}: endpoint_score is None")
            continue
        for field_name in score_field_names:
            val = getattr(es, field_name, None)
            if val is None or not (0.0 <= val <= 1.0) or not _has_at_most_3_decimal_places(val):
                out_of_range.append(
                    f"{ep.endpoint_id}.endpoint_score.{field_name}={val!r}"
                )
    if not out_of_range:
        checks_passed += 1
    else:
        failure_details.append(
            f"RI-8: endpoint_score fields outside [0.0, 1.0] or with more than 3 "
            f"decimal places: {out_of_range}"
        )

    # RI-9: score_label_description in bounded value set
    checks_performed += 1
    sld = getattr(executive_summary, "score_label_description", None)
    valid_descriptions = set(SCORE_LABEL_DESCRIPTIONS.values())
    if sld in valid_descriptions:
        checks_passed += 1
    else:
        failure_details.append(
            f"RI-9: executive_summary.score_label_description not in bounded "
            f"value set from SCORE_LABEL_DESCRIPTIONS: got {sld!r}"
        )

    return _result(domain, checks_performed, checks_passed, failure_details, evidence_refs)
