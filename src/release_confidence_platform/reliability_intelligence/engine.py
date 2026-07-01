"""Phase 5 Intelligence Generation Engine.

Orchestrates the full intelligence generation pipeline:
  prerequisite gate → metrics → stability → burst → consistency → scoring → publish

Owns all status lifecycle transitions for IntelligenceJob and IntelligenceMetadata.
Catches pipeline failures and updates records to FAILED before re-raising.

Phase 4 non-mutation is unconditional: the engine reads Phase 4 records via the
repository's read-only methods and never passes Phase 4 DynamoDB keys to write methods.

Pipeline steps:
  1. Log invocation
  2. Idempotency check (IntelligenceMetadata)
  3. Prerequisite gate (AggregateSetCompletion)
  4. Write IntelligenceJob (PENDING)
  5. Write or update IntelligenceMetadata (PENDING)
  6. Update both records to IN_PROGRESS
  7. Load Phase 4 aggregates
  8. Separate by aggregate_type
  9. Compute metrics
  10. Compute stability, burst, consistency
  11. Compute scores
  12. Assemble S3 artifact
  13. Write S3 artifact (BEFORE step 14)
  14. Update both records to COMPLETE
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from release_confidence_platform.core.constants.engine import LOG_CATEGORY_INTERNAL
from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.core.logging import StructuredLogger
from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.reliability_intelligence import events as evt
from release_confidence_platform.reliability_intelligence.burst import compute_burst_analysis
from release_confidence_platform.reliability_intelligence.consistency import (
    compute_consistency_analysis,
)
from release_confidence_platform.reliability_intelligence.constants import INTELLIGENCE_VERSION
from release_confidence_platform.reliability_intelligence.dtypes import IntelligenceFilter
from release_confidence_platform.reliability_intelligence.identity import (
    build_s3_key,
    generate_intelligence_job_id,
)
from release_confidence_platform.reliability_intelligence.metrics import (
    compute_audit_metrics_summary,
    compute_endpoint_metrics,
)
from release_confidence_platform.reliability_intelligence.models import EndpointMetricsDTO
from release_confidence_platform.reliability_intelligence.scoring import (
    build_methodology_disclosure,
    compute_audit_score,
    compute_endpoint_score,
)
from release_confidence_platform.reliability_intelligence.stability import (
    compute_stability_analysis,
)

# Platform generator version for the S3 artifact header.
_GENERATOR_VERSION = "1.0.0"

# Bounded set of known aggregation versions.
_KNOWN_AGGREGATION_VERSIONS = frozenset({"agg_v1"})

_PRECISION = Decimal("0.001")


class IntelligenceGateError(ValidationError):
    """Raised when the AggregateSetCompletion prerequisite gate is not satisfied.

    Phase 5 cannot generate intelligence until Phase 4 aggregation is complete.
    No Phase 5 DynamoDB records are written when this error is raised.
    """

    def __init__(
        self,
        message: str = "AggregateSetCompletion prerequisite not satisfied",
        error_type: str = "INTELLIGENCE_GATE_ERROR",
    ) -> None:
        super().__init__(message, error_type)


class IntelligenceEngine:
    """Orchestrates the Phase 5 intelligence generation pipeline."""

    def __init__(self, repository: Any, publisher: Any, logger: Any = None) -> None:
        self.repository = repository
        self.publisher = publisher
        self.logger = logger or StructuredLogger()

    def generate(
        self,
        *,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str = INTELLIGENCE_VERSION,
        force: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Run the full intelligence generation pipeline.

        Args:
            client_id: Validated client identifier.
            audit_id: Validated audit identifier.
            audit_execution_id: Durable execution identity (from Phase 4).
            config_version: Configuration version.
            aggregation_version: Phase 4 aggregation version to consume.
            intelligence_version: Intelligence version identifier (intel_v1).
            force: Re-generate even if COMPLETE already exists.
            dry_run: Run the full pipeline but skip all DynamoDB and S3 writes.

        Returns:
            Dict with status, job_id, composite_score, score_label, endpoint_count,
            and s3_artifact_ref (None when dry_run).

        Raises:
            ValidationError: On invalid aggregation_version.
            IntelligenceGateError: When AggregateSetCompletion prerequisite is not met.
            StorageError: On DynamoDB or S3 write failure.
        """
        if aggregation_version not in _KNOWN_AGGREGATION_VERSIONS:
            raise ValidationError(
                f"Unsupported aggregation_version: {aggregation_version!r}. "
                f"Known versions: {sorted(_KNOWN_AGGREGATION_VERSIONS)}",
                "UNSUPPORTED_AGGREGATION_VERSION",
            )

        invoked_at = utc_now_iso()

        self.logger.log(
            evt.INTELLIGENCE_GENERATION_INVOKED,
            event_type=evt.INTELLIGENCE_GENERATION_INVOKED,
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="IntelligenceEngine",
            client_id=client_id,
            audit_id=audit_id,
            audit_execution_id=audit_execution_id,
            aggregation_version=aggregation_version,
            intelligence_version=intelligence_version,
            force=force,
            dry_run=dry_run,
        )

        # ------------------------------------------------------------------
        # Step 1: Idempotency check
        # ------------------------------------------------------------------
        existing_filter = IntelligenceFilter(
            client_id=client_id,
            audit_id=audit_id,
            audit_execution_id=audit_execution_id,
            config_version=config_version,
            aggregation_version=aggregation_version,
            intelligence_version=intelligence_version,
        )
        existing = self.repository.get_intelligence_metadata(existing_filter)

        if existing:
            status = existing.get("status", "UNKNOWN")
            if status == "COMPLETE" and not force:
                self.logger.log(
                    evt.INTELLIGENCE_ALREADY_EXISTS,
                    event_type=evt.INTELLIGENCE_ALREADY_EXISTS,
                    log_category=LOG_CATEGORY_INTERNAL,
                    level="INFO",
                    service="IntelligenceEngine",
                    client_id=client_id,
                    audit_id=audit_id,
                    intelligence_job_id=existing.get("intelligence_job_id"),
                )
                return {
                    "client_id": client_id,
                    "audit_id": audit_id,
                    "audit_execution_id": audit_execution_id,
                    "config_version": config_version,
                    "aggregation_version": aggregation_version,
                    "intelligence_version": intelligence_version,
                    "intelligence_job_id": existing.get("intelligence_job_id"),
                    "status": "ALREADY_COMPLETE",
                    "composite_score": existing.get("composite_score"),
                    "score_label": existing.get("score_label"),
                    "endpoint_count": existing.get("endpoint_count"),
                    "s3_artifact_ref": existing.get("s3_artifact_ref"),
                }

        # ------------------------------------------------------------------
        # Step 2: Prerequisite gate — AggregateSetCompletion must be COMPLETE
        # ------------------------------------------------------------------
        aggregate_set = self.repository.get_aggregate_set_completion(
            client_id, audit_id, audit_execution_id, config_version, aggregation_version
        )
        if aggregate_set is None or aggregate_set.get("completion_status") != "COMPLETE":
            gate_reason = (
                "AggregateSetCompletion not found"
                if aggregate_set is None
                else f"completion_status={aggregate_set.get('completion_status')!r} != COMPLETE"
            )
            self.logger.log(
                evt.INTELLIGENCE_PREREQUISITE_GATE_FAILED,
                event_type=evt.INTELLIGENCE_PREREQUISITE_GATE_FAILED,
                log_category=LOG_CATEGORY_INTERNAL,
                level="WARNING",
                service="IntelligenceEngine",
                client_id=client_id,
                audit_id=audit_id,
                gate_reason=gate_reason,
            )
            raise IntelligenceGateError(
                f"Intelligence generation prerequisite not satisfied: {gate_reason}"
            )

        # ------------------------------------------------------------------
        # Step 3: Generate new intelligence_job_id
        # ------------------------------------------------------------------
        intelligence_job_id = generate_intelligence_job_id()
        aggregate_set_hash = aggregate_set.get("aggregate_set_hash")
        aggregation_job_id = aggregate_set.get("aggregation_job_id")

        job_key = self.repository.intelligence_job_keys(client_id, audit_id, intelligence_job_id)
        meta_key = self.repository.intelligence_metadata_keys(
            client_id, audit_id, audit_execution_id, config_version, aggregation_version,
            intelligence_version
        )

        if dry_run:
            return self._dry_run_pipeline(
                client_id=client_id,
                audit_id=audit_id,
                audit_execution_id=audit_execution_id,
                config_version=config_version,
                aggregation_version=aggregation_version,
                intelligence_version=intelligence_version,
                intelligence_job_id=intelligence_job_id,
                aggregate_set=aggregate_set,
            )

        # ------------------------------------------------------------------
        # Step 4: Write IntelligenceJob (PENDING)
        # ------------------------------------------------------------------
        job_item = _build_job_item(
            job_key=job_key,
            client_id=client_id,
            audit_id=audit_id,
            audit_execution_id=audit_execution_id,
            config_version=config_version,
            aggregation_version=aggregation_version,
            intelligence_version=intelligence_version,
            intelligence_job_id=intelligence_job_id,
            aggregate_set_hash=aggregate_set_hash,
            aggregation_job_id=aggregation_job_id,
            force=force,
            now=invoked_at,
        )
        self.repository.put_intelligence_job_once(job_item)

        self.logger.log(
            evt.INTELLIGENCE_GENERATION_PENDING,
            event_type=evt.INTELLIGENCE_GENERATION_PENDING,
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="IntelligenceEngine",
            client_id=client_id,
            audit_id=audit_id,
            intelligence_job_id=intelligence_job_id,
        )

        # ------------------------------------------------------------------
        # Step 5: Write or update IntelligenceMetadata (PENDING)
        # ------------------------------------------------------------------
        if existing is None:
            meta_item = _build_metadata_item(
                meta_key=meta_key,
                client_id=client_id,
                audit_id=audit_id,
                audit_execution_id=audit_execution_id,
                config_version=config_version,
                aggregation_version=aggregation_version,
                intelligence_version=intelligence_version,
                intelligence_job_id=intelligence_job_id,
                aggregate_set_hash=aggregate_set_hash,
                generation_count=1,
                now=invoked_at,
                original_created_at=None,
            )
            self.repository.put_intelligence_metadata_once(meta_item)
        else:
            generation_count = (existing.get("generation_count") or 1) + 1
            meta_item = _build_metadata_item(
                meta_key=meta_key,
                client_id=client_id,
                audit_id=audit_id,
                audit_execution_id=audit_execution_id,
                config_version=config_version,
                aggregation_version=aggregation_version,
                intelligence_version=intelligence_version,
                intelligence_job_id=intelligence_job_id,
                aggregate_set_hash=aggregate_set_hash,
                generation_count=generation_count,
                now=invoked_at,
                original_created_at=existing.get("created_at"),
            )
            self.repository.update_intelligence_metadata(meta_item)

        # ------------------------------------------------------------------
        # Step 6: Update both records to IN_PROGRESS
        # ------------------------------------------------------------------
        progress_now = utc_now_iso()
        in_progress_updates: dict[str, Any] = {
            "status": "IN_PROGRESS",
            "updated_at": progress_now,
        }
        self.repository.update_intelligence_job(job_key, in_progress_updates)
        self.repository.update_intelligence_metadata_fields(meta_key, in_progress_updates)

        self.logger.log(
            evt.INTELLIGENCE_GENERATION_IN_PROGRESS,
            event_type=evt.INTELLIGENCE_GENERATION_IN_PROGRESS,
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="IntelligenceEngine",
            client_id=client_id,
            audit_id=audit_id,
            intelligence_job_id=intelligence_job_id,
        )

        # ------------------------------------------------------------------
        # Steps 7-13: Pipeline computation and S3 publish
        # ------------------------------------------------------------------
        failure_stage: str = "unknown"
        try:
            # Step 7: Load Phase 4 aggregates
            failure_stage = "loading_phase4_aggregates"
            all_phase4_records = self.repository.list_phase4_aggregate_records(
                client_id, audit_id, audit_execution_id, config_version, aggregation_version
            )

            # Step 8: Separate by aggregate_type
            failure_stage = "separating_aggregate_records"
            audit_aggregate, endpoint_aggregates, failure_classification_by_endpoint = (
                _separate_aggregate_records(all_phase4_records)
            )
            if audit_aggregate is None:
                raise ValidationError(
                    "AuditAggregate record not found in Phase 4 aggregate set",
                    "MISSING_AUDIT_AGGREGATE",
                )

            # Step 9: Compute metrics (with latency normalization)
            failure_stage = "computing_metrics"
            all_endpoint_metrics: list[EndpointMetricsDTO] = []
            for ep_id in sorted(endpoint_aggregates.keys()):
                ep_record = _normalize_endpoint_for_metrics(endpoint_aggregates[ep_id])
                all_endpoint_metrics.append(compute_endpoint_metrics(ep_record))

            audit_metrics_summary = compute_audit_metrics_summary(
                audit_aggregate, all_endpoint_metrics
            )

            self.logger.log(
                evt.INTELLIGENCE_METRICS_COMPLETE,
                event_type=evt.INTELLIGENCE_METRICS_COMPLETE,
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="IntelligenceEngine",
                client_id=client_id,
                audit_id=audit_id,
                intelligence_job_id=intelligence_job_id,
                endpoint_count=len(all_endpoint_metrics),
            )

            # Steps 10a-10c: Compute analysis for each endpoint
            failure_stage = "computing_stability_burst_consistency"
            stability_results = {}
            burst_results = {}
            consistency_results = {}
            for ep_metrics in all_endpoint_metrics:
                ep_id = ep_metrics.endpoint_id
                stability_results[ep_id] = compute_stability_analysis(ep_metrics)
                burst_results[ep_id] = compute_burst_analysis(ep_metrics)
                consistency_results[ep_id] = compute_consistency_analysis(ep_metrics)

            self.logger.log(
                evt.INTELLIGENCE_ANALYSIS_COMPLETE,
                event_type=evt.INTELLIGENCE_ANALYSIS_COMPLETE,
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="IntelligenceEngine",
                client_id=client_id,
                audit_id=audit_id,
                intelligence_job_id=intelligence_job_id,
                endpoint_count=len(all_endpoint_metrics),
            )

            # Step 11: Compute scores
            failure_stage = "computing_scores"
            endpoint_score_results = []
            for ep_metrics in all_endpoint_metrics:
                ep_id = ep_metrics.endpoint_id
                ep_score = compute_endpoint_score(
                    ep_metrics,
                    stability_results[ep_id],
                    burst_results[ep_id],
                    consistency_results[ep_id],
                )
                endpoint_score_results.append(ep_score)

            audit_score_result = compute_audit_score(
                endpoint_score_results,
                aggregate_set_hash=aggregate_set_hash,
            )
            methodology_disclosure = build_methodology_disclosure()

            self.logger.log(
                evt.INTELLIGENCE_SCORING_COMPLETE,
                event_type=evt.INTELLIGENCE_SCORING_COMPLETE,
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="IntelligenceEngine",
                client_id=client_id,
                audit_id=audit_id,
                intelligence_job_id=intelligence_job_id,
                composite_score=str(audit_score_result.composite_score),
                score_label=audit_score_result.score_label,
            )

            # Step 12: Assemble S3 artifact
            failure_stage = "assembling_artifact"
            generated_at = utc_now_iso()
            s3_key = build_s3_key(
                client_id=client_id,
                audit_id=audit_id,
                audit_execution_id=audit_execution_id,
                aggregation_version=aggregation_version,
                intelligence_version=intelligence_version,
                intelligence_job_id=intelligence_job_id,
            )
            artifact = _assemble_artifact(
                client_id=client_id,
                audit_id=audit_id,
                audit_execution_id=audit_execution_id,
                config_version=config_version,
                aggregation_version=aggregation_version,
                intelligence_version=intelligence_version,
                intelligence_job_id=intelligence_job_id,
                generated_at=generated_at,
                aggregate_set=aggregate_set,
                audit_aggregate=audit_aggregate,
                audit_metrics_summary=audit_metrics_summary,
                audit_score_result=audit_score_result,
                all_endpoint_metrics=all_endpoint_metrics,
                endpoint_aggregates=endpoint_aggregates,
                failure_classification_by_endpoint=failure_classification_by_endpoint,
                stability_results=stability_results,
                burst_results=burst_results,
                consistency_results=consistency_results,
                endpoint_score_results=endpoint_score_results,
                methodology_disclosure=methodology_disclosure,
            )

            # Step 13: Write S3 artifact BEFORE updating COMPLETE
            failure_stage = "writing_s3_artifact"
            self.publisher.write_artifact(s3_key, artifact)

            self.logger.log(
                evt.INTELLIGENCE_S3_ARTIFACT_WRITTEN,
                event_type=evt.INTELLIGENCE_S3_ARTIFACT_WRITTEN,
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="IntelligenceEngine",
                client_id=client_id,
                audit_id=audit_id,
                intelligence_job_id=intelligence_job_id,
                s3_key=s3_key,
            )

        except Exception as exc:
            # Failure path: update both records to FAILED before re-raising.
            failure_reason = getattr(exc, "error_type", "INTELLIGENCE_GENERATION_FAILED")
            fail_now = utc_now_iso()
            fail_updates: dict[str, Any] = {
                "status": "FAILED",
                "failure_stage": failure_stage,
                "failure_reason_code": failure_reason,
                "completed_at": fail_now,
                "updated_at": fail_now,
            }
            try:
                self.repository.update_intelligence_job(job_key, fail_updates)
                self.repository.update_intelligence_metadata_fields(meta_key, fail_updates)
            except Exception:
                pass  # Do not mask the original exception.

            self.logger.log(
                evt.INTELLIGENCE_GENERATION_FAILED,
                event_type=evt.INTELLIGENCE_GENERATION_FAILED,
                log_category=LOG_CATEGORY_INTERNAL,
                level="ERROR",
                service="IntelligenceEngine",
                client_id=client_id,
                audit_id=audit_id,
                intelligence_job_id=intelligence_job_id,
                failure_stage=failure_stage,
                failure_reason=failure_reason,
            )
            raise

        # ------------------------------------------------------------------
        # Step 14: Update both records to COMPLETE
        # ------------------------------------------------------------------
        complete_at = utc_now_iso()
        complete_score_str = str(audit_score_result.composite_score)
        job_complete_updates: dict[str, Any] = {
            "status": "COMPLETE",
            "composite_score": complete_score_str,
            "endpoint_count": audit_score_result.endpoint_count,
            "s3_artifact_ref": s3_key,
            "aggregate_set_hash": aggregate_set_hash,
            "completed_at": complete_at,
            "updated_at": complete_at,
        }
        meta_complete_updates: dict[str, Any] = {
            "status": "COMPLETE",
            "composite_score": complete_score_str,
            "score_label": audit_score_result.score_label,
            "endpoint_count": audit_score_result.endpoint_count,
            "s3_artifact_ref": s3_key,
            "aggregate_set_hash": aggregate_set_hash,
            "completed_at": complete_at,
            "updated_at": complete_at,
        }
        self.repository.update_intelligence_job(job_key, job_complete_updates)
        self.repository.update_intelligence_metadata_fields(meta_key, meta_complete_updates)

        self.logger.log(
            evt.INTELLIGENCE_GENERATION_COMPLETE,
            event_type=evt.INTELLIGENCE_GENERATION_COMPLETE,
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="IntelligenceEngine",
            client_id=client_id,
            audit_id=audit_id,
            intelligence_job_id=intelligence_job_id,
            composite_score=complete_score_str,
            score_label=audit_score_result.score_label,
            endpoint_count=audit_score_result.endpoint_count,
        )

        return {
            "client_id": client_id,
            "audit_id": audit_id,
            "audit_execution_id": audit_execution_id,
            "config_version": config_version,
            "aggregation_version": aggregation_version,
            "intelligence_version": intelligence_version,
            "intelligence_job_id": intelligence_job_id,
            "status": "COMPLETE",
            "composite_score": complete_score_str,
            "score_label": audit_score_result.score_label,
            "endpoint_count": audit_score_result.endpoint_count,
            "s3_artifact_ref": s3_key,
        }

    def _dry_run_pipeline(
        self,
        *,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str,
        intelligence_job_id: str,
        aggregate_set: dict[str, Any],
    ) -> dict[str, Any]:
        """Run the computation pipeline without writing to DynamoDB or S3."""
        all_phase4_records = self.repository.list_phase4_aggregate_records(
            client_id, audit_id, audit_execution_id, config_version, aggregation_version
        )
        audit_aggregate, endpoint_aggregates, _ = _separate_aggregate_records(all_phase4_records)
        if audit_aggregate is None:
            raise ValidationError(
                "AuditAggregate record not found in Phase 4 aggregate set",
                "MISSING_AUDIT_AGGREGATE",
            )

        all_endpoint_metrics: list[EndpointMetricsDTO] = []
        for ep_id in sorted(endpoint_aggregates.keys()):
            ep_record = _normalize_endpoint_for_metrics(endpoint_aggregates[ep_id])
            all_endpoint_metrics.append(compute_endpoint_metrics(ep_record))

        endpoint_score_results = []
        for ep_metrics in all_endpoint_metrics:
            ep_id = ep_metrics.endpoint_id
            endpoint_score_results.append(
                compute_endpoint_score(
                    ep_metrics,
                    compute_stability_analysis(ep_metrics),
                    compute_burst_analysis(ep_metrics),
                    compute_consistency_analysis(ep_metrics),
                )
            )

        audit_score_result = compute_audit_score(
            endpoint_score_results,
            aggregate_set_hash=aggregate_set.get("aggregate_set_hash"),
        )

        return {
            "client_id": client_id,
            "audit_id": audit_id,
            "audit_execution_id": audit_execution_id,
            "config_version": config_version,
            "aggregation_version": aggregation_version,
            "intelligence_version": intelligence_version,
            "intelligence_job_id": intelligence_job_id,
            "status": "DRY_RUN",
            "composite_score": str(audit_score_result.composite_score),
            "score_label": audit_score_result.score_label,
            "endpoint_count": audit_score_result.endpoint_count,
            "s3_artifact_ref": None,
        }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _separate_aggregate_records(
    records: list[dict[str, Any]],
) -> tuple[
    dict[str, Any] | None,
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
]:
    """Separate a list of Phase 4 aggregate records by aggregate_type.

    Returns:
        (audit_aggregate, endpoint_aggregates, failure_classification_by_endpoint)
        where endpoint_aggregates is {endpoint_id: record}
        and failure_classification_by_endpoint is {endpoint_id: record} for scope=endpoint.
    """
    audit_aggregate: dict[str, Any] | None = None
    endpoint_aggregates: dict[str, dict[str, Any]] = {}
    failure_classification_by_endpoint: dict[str, dict[str, Any]] = {}

    for record in records:
        agg_type = record.get("aggregate_type")
        if agg_type == "audit":
            audit_aggregate = record
        elif agg_type == "endpoint":
            ep_id = record.get("endpoint_id")
            if ep_id:
                endpoint_aggregates[ep_id] = record
        elif agg_type == "failure_classification":
            scope = record.get("scope", "")
            if scope == "endpoint":
                ep_id = record.get("endpoint_id")
                if ep_id:
                    failure_classification_by_endpoint[ep_id] = record

    return audit_aggregate, endpoint_aggregates, failure_classification_by_endpoint


def _normalize_endpoint_for_metrics(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize Phase 4 EndpointAggregate latency_distribution_ms for Phase 5 consumption.

    Phase 4 aggregation engine stores latency_distribution_ms as:
      {"summary": {"count": N, "min": ..., "max": ..., "mean": ..., ...}}

    Phase 5 consumer contract (metrics.py) expects fields at the top level:
      {"count": N, "min": ..., "max": ..., "mean": ..., ...}

    This normalization is applied per Phase 5 technical design Section 9 note.
    """
    result = dict(record)
    lat_dist = result.get("latency_distribution_ms") or {}
    if isinstance(lat_dist, dict) and "summary" in lat_dist:
        result["latency_distribution_ms"] = lat_dist["summary"]
    return result


def _build_job_item(
    *,
    job_key: dict[str, str],
    client_id: str,
    audit_id: str,
    audit_execution_id: str,
    config_version: str,
    aggregation_version: str,
    intelligence_version: str,
    intelligence_job_id: str,
    aggregate_set_hash: str | None,
    aggregation_job_id: str | None,
    force: bool,
    now: str,
) -> dict[str, Any]:
    """Build the IntelligenceJob item for the initial PENDING write."""
    item: dict[str, Any] = {
        **job_key,
        "record_type": "intelligence_job",
        "intelligence_version": intelligence_version,
        "intelligence_job_id": intelligence_job_id,
        "client_id": client_id,
        "audit_id": audit_id,
        "audit_execution_id": audit_execution_id,
        "config_version": config_version,
        "aggregation_version": aggregation_version,
        "status": "PENDING",
        "aggregate_set_hash": aggregate_set_hash,
        "created_at": now,
        "updated_at": now,
    }
    if aggregation_job_id:
        item["aggregation_job_id"] = aggregation_job_id
    if force:
        item["is_force_regeneration"] = True
    return item


def _build_metadata_item(
    *,
    meta_key: dict[str, str],
    client_id: str,
    audit_id: str,
    audit_execution_id: str,
    config_version: str,
    aggregation_version: str,
    intelligence_version: str,
    intelligence_job_id: str,
    aggregate_set_hash: str | None,
    generation_count: int,
    now: str,
    original_created_at: str | None,
) -> dict[str, Any]:
    """Build the IntelligenceMetadata item for a PENDING write or update."""
    return {
        **meta_key,
        "record_type": "intelligence_metadata",
        "intelligence_version": intelligence_version,
        "intelligence_job_id": intelligence_job_id,
        "client_id": client_id,
        "audit_id": audit_id,
        "audit_execution_id": audit_execution_id,
        "config_version": config_version,
        "aggregation_version": aggregation_version,
        "status": "PENDING",
        "aggregate_set_hash": aggregate_set_hash,
        "generation_count": generation_count,
        "created_at": original_created_at or now,
        "updated_at": now,
    }


def _assemble_artifact(
    *,
    client_id: str,
    audit_id: str,
    audit_execution_id: str,
    config_version: str,
    aggregation_version: str,
    intelligence_version: str,
    intelligence_job_id: str,
    generated_at: str,
    aggregate_set: dict[str, Any],
    audit_aggregate: dict[str, Any],
    audit_metrics_summary: Any,
    audit_score_result: Any,
    all_endpoint_metrics: list[Any],
    endpoint_aggregates: dict[str, dict[str, Any]],
    failure_classification_by_endpoint: dict[str, dict[str, Any]],
    stability_results: dict[str, Any],
    burst_results: dict[str, Any],
    consistency_results: dict[str, Any],
    endpoint_score_results: list[Any],
    methodology_disclosure: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the full S3 intelligence artifact matching technical design Section 8.2."""
    request_counts = audit_aggregate.get("request_counts") or {}
    latency_summary_ms = audit_aggregate.get("latency_summary_ms") or {}
    endpoint_execution_counts = audit_aggregate.get("endpoint_execution_counts") or {}

    total_executions = request_counts.get("total", 0)
    total_pass = request_counts.get("successful", 0)
    total_fail = request_counts.get("failed", 0)
    total_timeout = request_counts.get("timeout", 0)
    total_network_failure = request_counts.get("network_failure", 0)

    audit_success_rate_str = "0.000"
    if total_executions > 0:
        sr = (
            Decimal(str(total_pass)) / Decimal(str(total_executions))
        ).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
        audit_success_rate_str = str(sr)

    audit_lineage_manifest_ref = aggregate_set.get("audit_lineage_manifest_ref")

    input_lineage: dict[str, Any] = {
        "aggregate_set_hash": aggregate_set.get("aggregate_set_hash"),
        "aggregation_job_id": aggregate_set.get("aggregation_job_id"),
        "aggregation_version": aggregation_version,
        "aggregate_set_completion_created_at": aggregate_set.get("created_at"),
        "endpoint_aggregate_count": aggregate_set.get("endpoint_aggregate_count"),
        "source_raw_result_count": aggregate_set.get("source_raw_result_count"),
    }
    if audit_lineage_manifest_ref:
        input_lineage["audit_lineage_manifest_ref"] = audit_lineage_manifest_ref

    audit_reliability_summary: dict[str, Any] = {
        "total_executions": total_executions,
        "total_pass": total_pass,
        "total_fail": total_fail,
        "total_timeout": total_timeout,
        "total_network_failure": total_network_failure,
        "audit_success_rate": audit_success_rate_str,
        "endpoint_count": len(endpoint_execution_counts),
        "audit_latency_mean_ms": latency_summary_ms.get("mean"),
        "audit_latency_p95_ms": latency_summary_ms.get("p95"),
        "audit_latency_p99_ms": latency_summary_ms.get("p99"),
        "source_field_refs": {
            "total_executions": "AuditAggregate.request_counts.total",
            "total_pass": "AuditAggregate.request_counts.successful",
            "total_fail": "AuditAggregate.request_counts.failed",
            "total_timeout": "AuditAggregate.request_counts.timeout",
            "total_network_failure": "AuditAggregate.request_counts.network_failure",
            "audit_latency_mean_ms": "AuditAggregate.latency_summary_ms.mean",
            "audit_latency_p95_ms": "AuditAggregate.latency_summary_ms.p95",
            "audit_latency_p99_ms": "AuditAggregate.latency_summary_ms.p99",
            "endpoint_count": "AuditAggregate.endpoint_execution_counts (distinct key count)",
        },
    }

    composite_score_section: dict[str, Any] = {
        "value": str(audit_score_result.composite_score),
        "score_label": audit_score_result.score_label,
        "intelligence_version": intelligence_version,
        "aggregation_version": aggregation_version,
        "aggregate_set_hash": aggregate_set.get("aggregate_set_hash"),
        "endpoint_count": audit_score_result.endpoint_count,
        "component_breakdown": audit_score_result.component_breakdown,
    }

    # Build per-endpoint list sorted by endpoint_id ascending (NFR-1 determinism).
    score_by_ep = {ep.endpoint_id: ep for ep in endpoint_score_results}
    endpoints_list = []
    for ep_metrics in all_endpoint_metrics:  # already sorted by endpoint_id
        ep_id = ep_metrics.endpoint_id
        ep_record = endpoint_aggregates.get(ep_id, {})
        ep_fc = failure_classification_by_endpoint.get(ep_id, {})
        ep_stability = stability_results[ep_id]
        ep_burst = burst_results[ep_id]
        ep_consistency = consistency_results[ep_id]
        ep_score = score_by_ep[ep_id]

        pass_count = ep_metrics.success_inputs.get("numerator", 0)
        latency_profile = ep_metrics.latency_profile or {}

        reliability_metrics: dict[str, Any] = {
            "execution_count": ep_metrics.execution_count,
            "pass_count": pass_count,
            "fail_count": ep_metrics.execution_count - pass_count,
            "timeout_count": ep_metrics.timeout_count,
            "success_rate": (
                str(ep_metrics.success_rate) if ep_metrics.success_rate is not None else None
            ),
            "success_rate_numerator": ep_metrics.success_inputs.get("numerator", 0),
            "success_rate_denominator": ep_metrics.success_inputs.get("denominator", 0),
            "latency_min_ms": latency_profile.get("min"),
            "latency_max_ms": latency_profile.get("max"),
            "latency_mean_ms": latency_profile.get("mean"),
            "latency_median_ms": latency_profile.get("median"),
            "latency_p95_ms": latency_profile.get("p95"),
            "latency_p99_ms": latency_profile.get("p99"),
            "latency_count": latency_profile.get("count", 0),
            "failure_classification_breakdown": ep_fc.get(
                "classification_counts",
                dict(ep_metrics.failure_classification_counts),
            ),
            "http_response_distribution": ep_record.get("http_response_distribution", {}),
            "source_field_refs": {
                "success_rate_numerator": "EndpointAggregate.success_inputs.numerator",
                "success_rate_denominator": "EndpointAggregate.success_inputs.denominator",
                "execution_count": "EndpointAggregate.execution_count",
                "timeout_count": "EndpointAggregate.timeout_count",
                "latency_*": "EndpointAggregate.latency_distribution_ms.*",
                "failure_classification_breakdown": (
                    "FailureClassificationAggregate.classification_counts (scope=endpoint)"
                ),
            },
        }

        endpoint_score_section: dict[str, Any] = {
            "composite_score": str(ep_score.composite_score),
            "reliability_score": str(ep_score.reliability_score),
            "stability_score": str(ep_score.stability_score),
            "burst_score": str(ep_score.burst_score),
            "consistency_score": str(ep_score.consistency_score),
            "score_derivation": ep_score.score_derivation,
        }

        endpoint_entry: dict[str, Any] = {
            "endpoint_id": ep_id,
            "reliability_metrics": reliability_metrics,
            "stability_analysis": {
                "success_rate_stability_label": ep_stability.success_rate_stability_label,
                "latency_stability_label": ep_stability.latency_stability_label,
                "methodology_trace": ep_stability.methodology_trace,
            },
            "burst_analysis": {
                "failure_burst_label": ep_burst.failure_burst_label,
                "latency_spike_label": ep_burst.latency_spike_label,
                "methodology_trace": ep_burst.methodology_trace,
            },
            "consistency_analysis": {
                "consistency_label": ep_consistency.consistency_label,
                "methodology_trace": ep_consistency.methodology_trace,
            },
            "endpoint_score": endpoint_score_section,
        }
        endpoints_list.append(endpoint_entry)

    return {
        "intelligence_version": intelligence_version,
        "aggregation_version": aggregation_version,
        "client_id": client_id,
        "audit_id": audit_id,
        "audit_execution_id": audit_execution_id,
        "config_version": config_version,
        "intelligence_job_id": intelligence_job_id,
        "generated_at": generated_at,
        "generator_version": _GENERATOR_VERSION,
        "input_lineage": input_lineage,
        "audit_reliability_summary": audit_reliability_summary,
        "composite_score": composite_score_section,
        "endpoints": endpoints_list,
        "methodology_disclosure": methodology_disclosure,
    }
