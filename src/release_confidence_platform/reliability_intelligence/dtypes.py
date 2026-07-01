"""Immutable DTO definitions for Phase 5.7 Intelligence Retrieval Layer."""
from __future__ import annotations

from dataclasses import dataclass

_INTELLIGENCE_NOTICE = (
    "This output is for engineering diagnostics only. "
    "Authoritative intelligence resides in the immutable Phase 5 S3 artifact."
)
INTELLIGENCE_RETRIEVAL_VERSION = "1.0.0"


@dataclass(frozen=True)
class IntelligenceFilter:
    client_id: str
    audit_id: str
    audit_execution_id: str
    config_version: str
    aggregation_version: str
    intelligence_version: str = "intel_v1"
    endpoint_id: str | None = None


@dataclass(frozen=True)
class IntelligenceProvenanceEnvelope:
    # _notice must be present in every JSON output (IRET-PROV02)
    _notice: str
    retrieved_at: str
    retrieval_version: str
    intelligence_version: str | None
    aggregation_version: str | None
    aggregate_set_hash: str | None
    audit_id: str | None
    client_id: str | None
    intelligence_job_id: str | None


@dataclass(frozen=True)
class IntelligenceStatusDTO:
    # IRET-U04: status + intelligence_job_id; failure_reason if FAILED
    # IRET-U05: for FAILED jobs, composite_score and score_label are None
    status: str
    intelligence_job_id: str | None
    composite_score: str | None
    score_label: str | None
    endpoint_count: int | None
    s3_artifact_ref: str | None
    completed_at: str | None
    failure_reason: str | None


@dataclass(frozen=True)
class IntelligenceSummaryDTO:
    # IRET-U01: all IntelligenceMetadata stable fields
    intelligence_version: str
    intelligence_job_id: str | None
    client_id: str
    audit_id: str
    audit_execution_id: str
    config_version: str
    aggregation_version: str
    status: str
    composite_score: str | None
    score_label: str | None
    endpoint_count: int | None
    s3_artifact_ref: str | None
    aggregate_set_hash: str | None
    created_at: str | None
    completed_at: str | None


@dataclass(frozen=True)
class IntelligenceNotFoundDTO:
    # IRET-U06: controlled not-found — NOT an unhandled exception
    reason: str
    client_id: str
    audit_id: str
