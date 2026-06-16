"""Immutable DTO definitions for the Engineering Retrieval Layer.

All DTOs are frozen dataclasses. Formatters and callers must not mutate them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_NOTICE = (
    "This output is for engineering diagnostics only. "
    "Authoritative evidence resides in immutable aggregation artifacts."
)

RETRIEVAL_VERSION = "1.0.0"


@dataclass(frozen=True)
class RetrievalFilter:
    client_id: str | None = None
    audit_id: str | None = None
    run_id: str | None = None
    endpoint_id: str | None = None
    scenario_id: str | None = None
    window_start: str | None = None
    window_end: str | None = None


@dataclass(frozen=True)
class ProvenanceEnvelope:
    retrieved_at: str
    retrieval_version: str
    aggregation_version: str | None
    manifest_hash: str | None
    audit_id: str | None
    client_id: str | None
    _notice: str = field(default=_NOTICE)


@dataclass(frozen=True)
class AggregationResultRecord:
    aggregate_type: str
    sk: str
    data: tuple[tuple[str, Any], ...]  # sorted key-value pairs


@dataclass(frozen=True)
class AggregationResultsDTO:
    records: tuple[AggregationResultRecord, ...]
    total_count: int
    endpoint_count: int
    completion_status: str | None


@dataclass(frozen=True)
class AggregationMetadataDTO:
    job_id: str | None
    status: str | None
    failure_category: str | None
    reason_code: str | None
    source_run_count: int | None
    source_raw_result_count: int | None
    created_at: str | None
    updated_at: str | None
    aggregation_version: str | None
    audit_execution_id: str | None
    config_version: str | None


@dataclass(frozen=True)
class AggregationLineageDTO:
    lineage_manifest_ref: Any
    source_ref_count: int | None
    manifest_hash: str | None
    audit_execution_id: str | None
    config_version: str | None
    aggregation_version: str | None
    aggregation_job_id: str | None
    aggregation_timestamp: str | None


@dataclass(frozen=True)
class AggregationStatusDTO:
    status: str | None
    reason_code: str | None
    failure_category: str | None
    job_id: str | None
    aggregation_version: str | None
    started_at: str | None
    completed_at: str | None


@dataclass(frozen=True)
class TimelineEvent:
    timestamp: str | None
    event_type: str
    data: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class OrchestrationTimelineDTO:
    events: tuple[TimelineEvent, ...]
    job_count: int


@dataclass(frozen=True)
class LifecycleTransition:
    from_state: str | None
    to_state: str | None
    actor: str | None
    reason: str | None
    timestamp: str | None


@dataclass(frozen=True)
class LifecycleTransitionsDTO:
    transitions: tuple[LifecycleTransition, ...]
    total_count: int


@dataclass(frozen=True)
class ExecutionSummaryDTO:
    run_count: int
    total_duration_ms: int | float | None
    outcome_distribution: tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class AuditEventTimelineDTO:
    events: tuple[TimelineEvent, ...]
    total_count: int


@dataclass(frozen=True)
class LogEvent:
    timestamp: str | None
    level: str | None
    event_type: str | None
    stage: str | None
    service: str | None
    data: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class EngineeringLogsDTO:
    events: tuple[LogEvent, ...]
    total_count: int


@dataclass(frozen=True)
class RetryAttempt:
    job_id: str | None
    status: str | None
    started_at: str | None
    completed_at: str | None
    reason_code: str | None
    failure_category: str | None


@dataclass(frozen=True)
class RetryHistoryDTO:
    attempts: tuple[RetryAttempt, ...]
    total_attempts: int


@dataclass(frozen=True)
class AggregationGenerationStatusDTO:
    completeness_status: str
    completion_marker_present: bool
    aggregate_record_count: int | None
    endpoint_aggregate_count: int | None
    manifest_count: int | None
    expected_execution_count: int | None
    source_run_count: int | None
    source_raw_result_count: int | None
    aggregation_version: str | None
    created_at: str | None


@dataclass(frozen=True)
class AggregationVersionDTO:
    aggregation_version: str | None
    config_version: str | None
    created_at: str | None
    source: str


@dataclass(frozen=True)
class EvidenceReferenceEntry:
    run_id: str | None
    result_index: int | None
    endpoint_id: str | None
    result_timestamp: str | None
    s3_key_ref: str | None


@dataclass(frozen=True)
class EvidenceReferencesDTO:
    source_refs: tuple[EvidenceReferenceEntry, ...]
    source_ref_count: int
    manifest_hash: str | None


@dataclass(frozen=True)
class FailureSummariesDTO:
    classification_counts: tuple[tuple[str, int], ...]
    reason_code: str | None
    failure_category: str | None
    scope: str | None
    total_failures: int


@dataclass(frozen=True)
class ProcessingTimelineDTO:
    started_at: str | None
    completed_at: str | None
    duration_ms: int | float | None
    per_stage: tuple[tuple[str, str | None], ...]
