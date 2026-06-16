"""RetrievalService — query logic, filtering, and immutable DTO construction.

This service is the single owner of retrieval business logic. It never writes,
updates, or deletes records. All returned objects are frozen DTOs.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

from release_confidence_platform.retrieval.dtypes import (
    AggregationGenerationStatusDTO,
    AggregationLineageDTO,
    AggregationMetadataDTO,
    AggregationResultRecord,
    AggregationResultsDTO,
    AggregationStatusDTO,
    AggregationVersionDTO,
    AuditEventTimelineDTO,
    EngineeringLogsDTO,
    EvidenceReferenceEntry,
    EvidenceReferencesDTO,
    ExecutionSummaryDTO,
    FailureSummariesDTO,
    LifecycleTransition,
    LifecycleTransitionsDTO,
    LogEvent,
    OrchestrationTimelineDTO,
    ProcessingTimelineDTO,
    RetrievalFilter,
    RetryAttempt,
    RetryHistoryDTO,
    TimelineEvent,
)
from release_confidence_platform.retrieval.filters import (
    apply_filter,
    sanitize_s3_key_ref,
    scrub_sensitive_fields,
)
from release_confidence_platform.retrieval.repository import RetrievalRepository

# Fields allowed in aggregate records that reach the output layer
_AGGREGATE_ALLOWED_FIELDS = frozenset(
    {
        "PK",
        "SK",
        "aggregate_type",
        "record_kind",
        "client_id",
        "audit_id",
        "audit_execution_id",
        "config_version",
        "aggregation_version",
        "aggregation_job_id",
        "created_at",
        "completion_status",
        "expected_execution_count",
        "source_run_count",
        "source_raw_result_count",
        "aggregate_record_count",
        "endpoint_aggregate_count",
        "manifest_count",
        "audit_lineage_manifest_ref",
        "aggregate_set_hash",
        "lineage",
        "lineage_manifest_ref",
        "lineage_manifest_hash",
        "source_ref_count",
        "endpoint_id",
        "scope",
        "classification_counts",
        "request_counts",
        "status_code_distribution",
        "execution_duration_ms",
        "latency_summary_ms",
        "endpoint_execution_counts",
        "success_inputs",
        "latency_distribution_ms",
        "timeout_count",
        "failure_classification_counts",
        "http_response_distribution",
        "manifest_scope",
        "manifest_hash",
        "source_refs",  # bounded count only
    }
)


def _canonical_sort_key(item: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(item.get("audit_id") or ""),
        str(item.get("audit_execution_id") or ""),
        str(item.get("endpoint_id") or ""),
        str(item.get("scenario_id") or ""),
        str(item.get("timestamp") or item.get("created_at") or item.get("started_at") or ""),
    )


def _safe_record_data(record: dict[str, Any]) -> tuple[tuple[str, Any], ...]:
    scrubbed = scrub_sensitive_fields(record)
    allowed = {k: v for k, v in scrubbed.items() if k in _AGGREGATE_ALLOWED_FIELDS}
    # Sanitize lineage refs to strip raw S3 keys if they leaked in
    if "lineage" in allowed and isinstance(allowed["lineage"], dict):
        lineage = dict(allowed["lineage"])
        lineage.pop("source_refs", None)
        allowed["lineage"] = lineage
    return tuple(sorted(allowed.items()))


class RetrievalService:
    """Immutable-output query service for the Engineering Retrieval Layer."""

    def __init__(self, repository: RetrievalRepository) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # RET-U01 — aggregation-results
    # ------------------------------------------------------------------

    def get_aggregation_results(self, filters: RetrievalFilter) -> AggregationResultsDTO:
        records = apply_filter(
            self._repo.list_aggregate_records(
                filters.client_id or "", filters.audit_id or ""
            ),
            filters,
        )
        aggregate_records = [r for r in records if r.get("record_kind") == "aggregate"]
        sorted_records = sorted(aggregate_records, key=_canonical_sort_key)
        completion = next(
            (r for r in records if r.get("aggregate_type") == "aggregate_set_completion"),
            None,
        )
        endpoint_ids = {
            r.get("endpoint_id")
            for r in aggregate_records
            if r.get("aggregate_type") == "endpoint" and r.get("endpoint_id")
        }
        result_records = tuple(
            AggregationResultRecord(
                aggregate_type=str(r.get("aggregate_type") or ""),
                sk=str(r.get("SK") or ""),
                data=_safe_record_data(r),
            )
            for r in sorted_records
        )
        return AggregationResultsDTO(
            records=result_records,
            total_count=len(result_records),
            endpoint_count=len(endpoint_ids),
            completion_status=completion.get("completion_status") if completion else None,
        )

    # ------------------------------------------------------------------
    # RET-U02 — aggregation-metadata
    # ------------------------------------------------------------------

    def get_aggregation_metadata(self, filters: RetrievalFilter) -> AggregationMetadataDTO:
        job = self._repo.get_latest_aggregation_job(
            filters.client_id or "", filters.audit_id or ""
        )
        if not job:
            return AggregationMetadataDTO(
                job_id=None,
                status=None,
                failure_category=None,
                reason_code=None,
                source_run_count=None,
                source_raw_result_count=None,
                created_at=None,
                updated_at=None,
                aggregation_version=None,
                audit_execution_id=None,
                config_version=None,
            )
        return AggregationMetadataDTO(
            job_id=job.get("aggregation_job_id"),
            status=job.get("status"),
            failure_category=job.get("failure_category"),
            reason_code=job.get("reason_code"),
            source_run_count=job.get("source_run_count"),
            source_raw_result_count=job.get("source_raw_result_count"),
            created_at=job.get("started_at"),
            updated_at=job.get("completed_at"),
            aggregation_version=job.get("aggregation_version"),
            audit_execution_id=job.get("audit_execution_id"),
            config_version=job.get("config_version"),
        )

    # ------------------------------------------------------------------
    # RET-U03 — aggregation-lineage
    # ------------------------------------------------------------------

    def get_aggregation_lineage(self, filters: RetrievalFilter) -> AggregationLineageDTO:
        manifests = self._repo.list_lineage_manifests(
            filters.client_id or "", filters.audit_id or ""
        )
        audit_manifests = [
            m for m in manifests if str(m.get("SK") or "").endswith("LINEAGE#audit")
        ]
        manifest = audit_manifests[0] if audit_manifests else (manifests[0] if manifests else {})
        return AggregationLineageDTO(
            lineage_manifest_ref=manifest.get("lineage_manifest_ref"),
            source_ref_count=manifest.get("source_ref_count"),
            manifest_hash=manifest.get("manifest_hash") or manifest.get("lineage_manifest_hash"),
            audit_execution_id=manifest.get("audit_execution_id"),
            config_version=manifest.get("config_version"),
            aggregation_version=manifest.get("aggregation_version"),
            aggregation_job_id=manifest.get("aggregation_job_id"),
            aggregation_timestamp=(
                manifest.get("aggregation_timestamp") or manifest.get("created_at")
            ),
        )

    # ------------------------------------------------------------------
    # RET-U04 — aggregation-status
    # ------------------------------------------------------------------

    def get_aggregation_status(self, filters: RetrievalFilter) -> AggregationStatusDTO:
        job = self._repo.get_latest_aggregation_job(
            filters.client_id or "", filters.audit_id or ""
        )
        if not job:
            return AggregationStatusDTO(
                status=None,
                reason_code=None,
                failure_category=None,
                job_id=None,
                aggregation_version=None,
                started_at=None,
                completed_at=None,
            )
        return AggregationStatusDTO(
            status=job.get("status"),
            reason_code=job.get("reason_code"),
            failure_category=job.get("failure_category"),
            job_id=job.get("aggregation_job_id"),
            aggregation_version=job.get("aggregation_version"),
            started_at=job.get("started_at"),
            completed_at=job.get("completed_at"),
        )

    # ------------------------------------------------------------------
    # RET-U05 — orchestration-timeline
    # ------------------------------------------------------------------

    def get_orchestration_timeline(self, filters: RetrievalFilter) -> OrchestrationTimelineDTO:
        jobs = self._repo.list_aggregation_jobs(
            filters.client_id or "", filters.audit_id or ""
        )
        events = []
        for job in jobs:
            for ts_key, label in (
                ("started_at", "job_started"),
                ("completed_at", "job_completed"),
            ):
                if job.get(ts_key):
                    events.append(
                        TimelineEvent(
                            timestamp=job[ts_key],
                            event_type=label,
                            data=tuple(
                                sorted(
                                    {
                                        "job_id": job.get("aggregation_job_id"),
                                        "status": job.get("status"),
                                        "reason_code": job.get("reason_code"),
                                    }.items()
                                )
                            ),
                        )
                    )
        events.sort(key=lambda e: e.timestamp or "")
        return OrchestrationTimelineDTO(events=tuple(events), job_count=len(jobs))

    # ------------------------------------------------------------------
    # RET-U06 — lifecycle-transitions
    # ------------------------------------------------------------------

    def get_lifecycle_transitions(self, filters: RetrievalFilter) -> LifecycleTransitionsDTO:
        history = self._repo.list_lifecycle_history(
            filters.client_id or "", filters.audit_id or ""
        )
        transitions = []
        for item in sorted(history, key=lambda h: h.get("timestamp") or ""):
            transitions.append(
                LifecycleTransition(
                    from_state=item.get("from_state"),
                    to_state=item.get("to_state"),
                    actor=item.get("actor"),
                    reason=item.get("reason"),
                    timestamp=item.get("timestamp"),
                )
            )
        return LifecycleTransitionsDTO(
            transitions=tuple(transitions), total_count=len(transitions)
        )

    # ------------------------------------------------------------------
    # RET-U07 — execution-summary
    # ------------------------------------------------------------------

    def get_execution_summary(self, filters: RetrievalFilter) -> ExecutionSummaryDTO:
        runs = self._repo.list_completed_runs(
            filters.client_id or "", filters.audit_id or ""
        )
        total_duration: float = 0.0
        outcome_counts: dict[str, int] = {}
        for run in runs:
            dur = run.get("duration_ms")
            if isinstance(dur, (int, float)):
                total_duration += dur
            outcome = run.get("status") or run.get("outcome") or "COMPLETED"
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        return ExecutionSummaryDTO(
            run_count=len(runs),
            total_duration_ms=total_duration if runs else None,
            outcome_distribution=tuple(sorted(outcome_counts.items())),
        )

    # ------------------------------------------------------------------
    # RET-U08 — audit-event-timeline
    # ------------------------------------------------------------------

    def get_audit_event_timeline(self, filters: RetrievalFilter) -> AuditEventTimelineDTO:
        items = self._repo.list_all_audit_items(
            filters.client_id or "", filters.audit_id or ""
        )
        events = []
        for item in items:
            ts = (
                item.get("timestamp")
                or item.get("created_at")
                or item.get("started_at")
                or item.get("completed_at")
            )
            event_type = (
                item.get("aggregate_type")
                or item.get("record_kind")
                or item.get("status")
                or "event"
            )
            scrubbed = scrub_sensitive_fields(item)
            safe_data = {
                k: v
                for k, v in scrubbed.items()
                if k in ("SK", "aggregate_type", "record_kind", "status", "created_at",
                          "started_at", "completed_at", "audit_execution_id", "aggregation_version")
            }
            events.append(
                TimelineEvent(
                    timestamp=ts,
                    event_type=str(event_type),
                    data=tuple(sorted(safe_data.items())),
                )
            )
        events.sort(key=_canonical_sort_key_event)
        return AuditEventTimelineDTO(events=tuple(events), total_count=len(events))

    # ------------------------------------------------------------------
    # RET-U09 — engineering-logs
    # ------------------------------------------------------------------

    def get_engineering_logs(self, filters: RetrievalFilter) -> EngineeringLogsDTO:
        """Return sanitized structured log events from aggregation job metadata.

        Engineering logs are derived from aggregation job records and lifecycle history.
        They are operational diagnostics only — not authoritative evidence.
        """
        jobs = self._repo.list_aggregation_jobs(
            filters.client_id or "", filters.audit_id or ""
        )
        lifecycle = self._repo.list_lifecycle_history(
            filters.client_id or "", filters.audit_id or ""
        )
        log_events: list[LogEvent] = []
        for job in jobs:
            for ts_key, level, event_type, stage in (
                ("started_at", "INFO", "aggregation_job_claimed", "aggregation"),
                ("completed_at", "INFO", "aggregation_outcome", "aggregation"),
            ):
                if job.get(ts_key):
                    log_events.append(
                        LogEvent(
                            timestamp=job[ts_key],
                            level=level,
                            event_type=event_type,
                            stage=stage,
                            service="aggregation",
                            data=tuple(
                                sorted(
                                    {
                                        "job_id": job.get("aggregation_job_id"),
                                        "status": job.get("status"),
                                        "reason_code": job.get("reason_code"),
                                        "failure_category": job.get("failure_category"),
                                        "aggregation_version": job.get("aggregation_version"),
                                        "audit_execution_id": job.get("audit_execution_id"),
                                    }.items()
                                )
                            ),
                        )
                    )
        for item in lifecycle:
            log_events.append(
                LogEvent(
                    timestamp=item.get("timestamp"),
                    level="INFO",
                    event_type="lifecycle_transition",
                    stage="lifecycle",
                    service="audit_lifecycle",
                    data=tuple(
                        sorted(
                            {
                                "from_state": item.get("from_state"),
                                "to_state": item.get("to_state"),
                                "actor": item.get("actor"),
                                "reason": item.get("reason"),
                            }.items()
                        )
                    ),
                )
            )
        log_events.sort(key=lambda e: e.timestamp or "")
        return EngineeringLogsDTO(events=tuple(log_events), total_count=len(log_events))

    # ------------------------------------------------------------------
    # RET-U10 — retry-history
    # ------------------------------------------------------------------

    def get_retry_history(self, filters: RetrievalFilter) -> RetryHistoryDTO:
        jobs = self._repo.list_aggregation_jobs(
            filters.client_id or "", filters.audit_id or ""
        )
        attempts = [
            RetryAttempt(
                job_id=job.get("aggregation_job_id"),
                status=job.get("status"),
                started_at=job.get("started_at"),
                completed_at=job.get("completed_at"),
                reason_code=job.get("reason_code"),
                failure_category=job.get("failure_category"),
            )
            for job in sorted(jobs, key=lambda j: j.get("started_at") or "")
        ]
        return RetryHistoryDTO(attempts=tuple(attempts), total_attempts=len(attempts))

    # ------------------------------------------------------------------
    # RET-U11 — aggregation-generation-status
    # ------------------------------------------------------------------

    def get_aggregation_generation_status(
        self, filters: RetrievalFilter
    ) -> AggregationGenerationStatusDTO:
        completion = self._repo.get_aggregate_set_completion(
            filters.client_id or "", filters.audit_id or ""
        )
        if not completion:
            return AggregationGenerationStatusDTO(
                completeness_status="PENDING",
                completion_marker_present=False,
                aggregate_record_count=None,
                endpoint_aggregate_count=None,
                manifest_count=None,
                expected_execution_count=None,
                source_run_count=None,
                source_raw_result_count=None,
                aggregation_version=None,
                created_at=None,
            )
        return AggregationGenerationStatusDTO(
            completeness_status=str(completion.get("completion_status") or "COMPLETE"),
            completion_marker_present=True,
            aggregate_record_count=completion.get("aggregate_record_count"),
            endpoint_aggregate_count=completion.get("endpoint_aggregate_count"),
            manifest_count=completion.get("manifest_count"),
            expected_execution_count=completion.get("expected_execution_count"),
            source_run_count=completion.get("source_run_count"),
            source_raw_result_count=completion.get("source_raw_result_count"),
            aggregation_version=completion.get("aggregation_version"),
            created_at=completion.get("created_at"),
        )

    # ------------------------------------------------------------------
    # RET-U12 — aggregation-version
    # ------------------------------------------------------------------

    def get_aggregation_version(self, filters: RetrievalFilter) -> AggregationVersionDTO:
        completion = self._repo.get_aggregate_set_completion(
            filters.client_id or "", filters.audit_id or ""
        )
        if completion:
            return AggregationVersionDTO(
                aggregation_version=completion.get("aggregation_version"),
                config_version=completion.get("config_version"),
                created_at=completion.get("created_at"),
                source="aggregate_set_completion",
            )
        job = self._repo.get_latest_aggregation_job(
            filters.client_id or "", filters.audit_id or ""
        )
        if job:
            return AggregationVersionDTO(
                aggregation_version=job.get("aggregation_version"),
                config_version=job.get("config_version"),
                created_at=job.get("started_at"),
                source="aggregation_job",
            )
        return AggregationVersionDTO(
            aggregation_version=None,
            config_version=None,
            created_at=None,
            source="not_found",
        )

    # ------------------------------------------------------------------
    # RET-U13 — evidence-references
    # ------------------------------------------------------------------

    def get_evidence_references(self, filters: RetrievalFilter) -> EvidenceReferencesDTO:
        manifests = self._repo.list_lineage_manifests(
            filters.client_id or "", filters.audit_id or ""
        )
        audit_manifests = [
            m for m in manifests if str(m.get("SK") or "").endswith("LINEAGE#audit")
        ]
        manifest = audit_manifests[0] if audit_manifests else {}
        raw_refs = manifest.get("source_refs") or []
        if not isinstance(raw_refs, list):
            raw_refs = []
        entries = tuple(
            EvidenceReferenceEntry(
                run_id=ref.get("run_id") if isinstance(ref, dict) else None,
                result_index=ref.get("result_index") if isinstance(ref, dict) else None,
                endpoint_id=ref.get("endpoint_id") if isinstance(ref, dict) else None,
                result_timestamp=ref.get("result_timestamp") if isinstance(ref, dict) else None,
                s3_key_ref=sanitize_s3_key_ref(
                    ref.get("raw_result_s3_key") if isinstance(ref, dict) else None
                ),
            )
            for ref in raw_refs
        )
        return EvidenceReferencesDTO(
            source_refs=entries,
            source_ref_count=manifest.get("source_ref_count") or len(raw_refs),
            manifest_hash=manifest.get("manifest_hash") or manifest.get("lineage_manifest_hash"),
        )

    # ------------------------------------------------------------------
    # RET-U14 — failure-summaries
    # ------------------------------------------------------------------

    def get_failure_summaries(self, filters: RetrievalFilter) -> FailureSummariesDTO:
        records = self._repo.list_aggregate_records(
            filters.client_id or "", filters.audit_id or ""
        )
        failure_records = [
            r
            for r in records
            if r.get("aggregate_type") == "failure_classification"
            and r.get("scope") == "audit"
        ]
        if not failure_records:
            job = self._repo.get_latest_aggregation_job(
                filters.client_id or "", filters.audit_id or ""
            )
            return FailureSummariesDTO(
                classification_counts=(),
                reason_code=job.get("reason_code") if job else None,
                failure_category=job.get("failure_category") if job else None,
                scope="audit",
                total_failures=0,
            )
        record = failure_records[0]
        counts = record.get("classification_counts") or {}
        if not isinstance(counts, dict):
            counts = {}
        classification_counts = tuple(sorted(counts.items()))
        total = sum(v for v in counts.values() if isinstance(v, int))
        job = self._repo.get_latest_aggregation_job(
            filters.client_id or "", filters.audit_id or ""
        )
        return FailureSummariesDTO(
            classification_counts=classification_counts,
            reason_code=job.get("reason_code") if job else None,
            failure_category=job.get("failure_category") if job else None,
            scope="audit",
            total_failures=total,
        )

    # ------------------------------------------------------------------
    # RET-U15 — processing-timeline
    # ------------------------------------------------------------------

    def get_processing_timeline(self, filters: RetrievalFilter) -> ProcessingTimelineDTO:
        job = self._repo.get_latest_aggregation_job(
            filters.client_id or "", filters.audit_id or ""
        )
        if not job:
            return ProcessingTimelineDTO(
                started_at=None,
                completed_at=None,
                duration_ms=None,
                per_stage=(),
            )
        started_at = job.get("started_at")
        completed_at = job.get("completed_at")
        per_stage: list[tuple[str, str | None]] = [
            ("job_started_at", started_at),
            ("job_completed_at", completed_at),
            ("audit_execution_id_assigned_at", None),
        ]
        duration_ms: int | float | None = None
        if started_at and completed_at:
            from datetime import datetime  # noqa: PLC0415

            try:
                t0 = datetime.fromisoformat(started_at.replace("Z", "+00:00")).replace(
                    tzinfo=UTC
                )
                t1 = datetime.fromisoformat(completed_at.replace("Z", "+00:00")).replace(
                    tzinfo=UTC
                )
                duration_ms = (t1 - t0).total_seconds() * 1000
            except (ValueError, AttributeError):
                duration_ms = None
        return ProcessingTimelineDTO(
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            per_stage=tuple(per_stage),
        )


def _canonical_sort_key_event(event: TimelineEvent) -> tuple[str, str]:
    return (str(event.timestamp or ""), str(event.event_type or ""))
