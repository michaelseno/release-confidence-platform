"""Phase 6 Report Generation Engine.

Orchestrates the full report generation pipeline:
  idempotency check → prerequisite gate → write PENDING → IN_PROGRESS →
  load Phase 5 artifact → build DTO → write S3 artifact → COMPLETE

Owns all status lifecycle transitions for ReportJob and ReportMetadata records.
Catches pipeline failures and updates records to FAILED before re-raising.

Phase 5 non-mutation is unconditional: the engine reads Phase 5 IntelligenceMetadata
via the repository's read-only gate method and never writes to Phase 5 SK namespaces.
All engine writes target only #RPTJOB# and #RPT# SK patterns.

Pipeline steps:
  1. Log invocation
  2. Idempotency check (ReportMetadata)
  3. Prerequisite gate (IntelligenceMetadata must be COMPLETE)
  4. Generate report_job_id
  5. Compute DynamoDB keys
  6. Write ReportJob (PENDING)
  7. Write or update ReportMetadata (PENDING)
  8. Log PENDING. Update both records to IN_PROGRESS.
  9. Log IN_PROGRESS.
  10. Load Phase 5 S3 artifact
  11. Build ReleaseConfidenceReport DTO
  12. Compute S3 key and serialise artifact
  13. Write S3 artifact (BEFORE step 14)
  14. Update both records to COMPLETE. Log COMPLETE.
"""

from __future__ import annotations

from typing import Any

from release_confidence_platform.core.constants.engine import LOG_CATEGORY_INTERNAL
from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.core.logging import StructuredLogger
from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.deterministic_reporting import events as evt
from release_confidence_platform.deterministic_reporting.builder import ReportBuilder
from release_confidence_platform.deterministic_reporting.constants import REPORT_VERSION
from release_confidence_platform.deterministic_reporting.identity import (
    build_s3_key,
    generate_report_job_id,
)


class ReportGateError(ValidationError):
    """Raised when the IntelligenceMetadata prerequisite gate is not satisfied.

    Phase 6 cannot generate a report until Phase 5 intelligence generation is complete.
    No Phase 6 DynamoDB records are written when this error is raised.
    """

    def __init__(
        self,
        message: str = "IntelligenceMetadata prerequisite not satisfied",
        error_type: str = "REPORT_GATE_ERROR",
    ) -> None:
        super().__init__(message, error_type)


class ReportGenerationInProgressError(ValidationError):
    """Raised when a report generation is already in progress for this combination.

    A concurrent generation is running; the caller must wait for it to complete or fail
    before retrying. No Phase 6 DynamoDB records are written when this error is raised.
    """

    def __init__(
        self,
        message: str = "Report generation is already in progress",
        error_type: str = "REPORT_GENERATION_IN_PROGRESS",
    ) -> None:
        super().__init__(message, error_type)


class ReportingEngine:
    """Orchestrates the Phase 6 report generation pipeline."""

    def __init__(
        self,
        repository: Any,
        publisher: Any,
        builder: Any | None = None,
        logger: Any = None,
    ) -> None:
        self.repository = repository
        self.publisher = publisher
        self.builder = builder if builder is not None else ReportBuilder()
        self.logger = logger or StructuredLogger()

    def generate(
        self,
        *,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str,
        report_version: str = REPORT_VERSION,
        force: bool = False,
    ) -> dict[str, Any]:
        """Run the full report generation pipeline.

        Args:
            client_id: Validated client identifier.
            audit_id: Validated audit identifier.
            audit_execution_id: Durable execution identity (from Phase 4).
            config_version: Configuration version.
            aggregation_version: Phase 4 aggregation version consumed by Phase 5.
            intelligence_version: Phase 5 intelligence version.
            report_version: Report version identifier (report_v1).
            force: Re-generate even if COMPLETE already exists.

        Returns:
            Dict with status, report_job_id, report_id, composite_score, score_label,
            endpoint_count, and s3_artifact_ref.

        Raises:
            ReportGateError: When IntelligenceMetadata prerequisite is not met.
            ReportGenerationInProgressError: When generation is already in progress.
            StorageError: On DynamoDB or S3 write failure.
        """
        invoked_at = utc_now_iso()

        # ------------------------------------------------------------------
        # Step 1: Log invocation
        # ------------------------------------------------------------------
        self.logger.log(
            evt.REPORT_GENERATION_INVOKED,
            event_type=evt.REPORT_GENERATION_INVOKED,
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="ReportingEngine",
            client_id=client_id,
            audit_id=audit_id,
            audit_execution_id=audit_execution_id,
            aggregation_version=aggregation_version,
            intelligence_version=intelligence_version,
            report_version=report_version,
            force=force,
        )

        # ------------------------------------------------------------------
        # Step 2: Idempotency check
        # ------------------------------------------------------------------
        existing = self.repository.get_report_metadata(
            client_id,
            audit_id,
            audit_execution_id,
            config_version,
            aggregation_version,
            intelligence_version,
            report_version,
        )

        if existing:
            status = existing.get("status", "UNKNOWN")
            if status == "IN_PROGRESS":
                raise ReportGenerationInProgressError(
                    "Report generation is already in progress for this combination. "
                    "Wait for the current generation to complete before retrying."
                )
            if status == "COMPLETE" and not force:
                self.logger.log(
                    evt.REPORT_ALREADY_EXISTS,
                    event_type=evt.REPORT_ALREADY_EXISTS,
                    log_category=LOG_CATEGORY_INTERNAL,
                    level="INFO",
                    service="ReportingEngine",
                    client_id=client_id,
                    audit_id=audit_id,
                    report_job_id=existing.get("report_job_id"),
                )
                return {
                    "client_id": client_id,
                    "audit_id": audit_id,
                    "audit_execution_id": audit_execution_id,
                    "report_job_id": existing.get("report_job_id"),
                    "report_id": existing.get("report_id"),
                    "report_version": report_version,
                    "status": "ALREADY_COMPLETE",
                    "composite_score": existing.get("composite_score"),
                    "score_label": existing.get("score_label"),
                    "endpoint_count": existing.get("endpoint_count"),
                    "s3_artifact_ref": existing.get("s3_artifact_ref"),
                }

        # ------------------------------------------------------------------
        # Step 3: Prerequisite gate — IntelligenceMetadata must be COMPLETE
        # No Phase 6 DynamoDB records are written before this gate passes.
        # ------------------------------------------------------------------
        intel_metadata = self.repository.get_intelligence_metadata(
            client_id,
            audit_id,
            audit_execution_id,
            config_version,
            aggregation_version,
            intelligence_version,
        )

        if intel_metadata is None or intel_metadata.get("status") != "COMPLETE":
            gate_reason = (
                "IntelligenceMetadata not found"
                if intel_metadata is None
                else f"status={intel_metadata.get('status')!r} != COMPLETE"
            )
            self.logger.log(
                evt.REPORT_PREREQUISITE_GATE_FAILED,
                event_type=evt.REPORT_PREREQUISITE_GATE_FAILED,
                log_category=LOG_CATEGORY_INTERNAL,
                level="WARNING",
                service="ReportingEngine",
                client_id=client_id,
                audit_id=audit_id,
                gate_reason=gate_reason,
            )
            raise ReportGateError(
                f"Report generation prerequisite not satisfied: {gate_reason}"
            )

        # ------------------------------------------------------------------
        # Step 4: Generate report_job_id
        # ------------------------------------------------------------------
        report_job_id = generate_report_job_id()

        # ------------------------------------------------------------------
        # Step 5: Compute DynamoDB keys
        # ------------------------------------------------------------------
        job_key = self.repository.report_job_keys(client_id, audit_id, report_job_id)
        meta_key = self.repository.report_metadata_keys(
            client_id,
            audit_id,
            audit_execution_id,
            config_version,
            aggregation_version,
            intelligence_version,
            report_version,
        )

        # ------------------------------------------------------------------
        # Step 6: Write ReportJob (PENDING)
        # ------------------------------------------------------------------
        job_item: dict[str, Any] = {
            **job_key,
            "record_type": "report_job",
            "report_job_id": report_job_id,
            "client_id": client_id,
            "audit_id": audit_id,
            "audit_execution_id": audit_execution_id,
            "config_version": config_version,
            "aggregation_version": aggregation_version,
            "intelligence_version": intelligence_version,
            "report_version": report_version,
            "status": "PENDING",
            "s3_artifact_ref_intel": intel_metadata.get("s3_artifact_ref"),
            "created_at": invoked_at,
            "updated_at": invoked_at,
        }
        if force:
            job_item["is_force_regeneration"] = True
        self.repository.put_report_job_once(job_item)

        # ------------------------------------------------------------------
        # Step 7: Write or update ReportMetadata (PENDING)
        # ------------------------------------------------------------------
        if existing is None:
            meta_item: dict[str, Any] = {
                **meta_key,
                "record_type": "report_metadata",
                "report_job_id": report_job_id,
                "client_id": client_id,
                "audit_id": audit_id,
                "audit_execution_id": audit_execution_id,
                "config_version": config_version,
                "aggregation_version": aggregation_version,
                "intelligence_version": intelligence_version,
                "report_version": report_version,
                "status": "PENDING",
                "generation_count": 1,
                "created_at": invoked_at,
                "updated_at": invoked_at,
            }
            self.repository.put_report_metadata_once(meta_item)
        else:
            generation_count = (existing.get("generation_count") or 1) + 1
            self.repository.update_report_metadata_fields(
                meta_key,
                {
                    "report_job_id": report_job_id,
                    "status": "PENDING",
                    "generation_count": generation_count,
                    "updated_at": invoked_at,
                },
            )

        # ------------------------------------------------------------------
        # Step 8: Log PENDING. Update both records to IN_PROGRESS.
        # ------------------------------------------------------------------
        self.logger.log(
            evt.REPORT_GENERATION_PENDING,
            event_type=evt.REPORT_GENERATION_PENDING,
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="ReportingEngine",
            client_id=client_id,
            audit_id=audit_id,
            report_job_id=report_job_id,
        )

        progress_now = utc_now_iso()
        in_progress_updates: dict[str, Any] = {
            "status": "IN_PROGRESS",
            "updated_at": progress_now,
        }
        self.repository.update_report_job(job_key, in_progress_updates)
        self.repository.update_report_metadata_fields(meta_key, in_progress_updates)

        # ------------------------------------------------------------------
        # Step 9: Log IN_PROGRESS
        # ------------------------------------------------------------------
        self.logger.log(
            evt.REPORT_GENERATION_IN_PROGRESS,
            event_type=evt.REPORT_GENERATION_IN_PROGRESS,
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="ReportingEngine",
            client_id=client_id,
            audit_id=audit_id,
            report_job_id=report_job_id,
        )

        # ------------------------------------------------------------------
        # Steps 10-14: Pipeline computation (failure-safe)
        # ------------------------------------------------------------------
        failure_stage: str = "unknown"
        try:
            # Step 10: Load Phase 5 S3 artifact
            failure_stage = "loading_phase5_artifact"
            artifact = self.publisher.read_artifact(intel_metadata["s3_artifact_ref"])

            # Step 11: Build ReleaseConfidenceReport DTO
            failure_stage = "building_report_dto"
            generated_at = utc_now_iso()
            report = self.builder.build(artifact, report_job_id, generated_at)

            # Step 12: Compute S3 key
            failure_stage = "computing_s3_key"
            s3_key = build_s3_key(
                client_id=client_id,
                audit_id=audit_id,
                audit_execution_id=audit_execution_id,
                aggregation_version=aggregation_version,
                intelligence_version=intelligence_version,
                report_version=report_version,
                report_job_id=report_job_id,
            )

            # Step 13: Write S3 artifact BEFORE updating to COMPLETE
            failure_stage = "writing_s3_artifact"
            self.publisher.write_artifact(s3_key, report.model_dump())

            self.logger.log(
                evt.REPORT_S3_ARTIFACT_WRITTEN,
                event_type=evt.REPORT_S3_ARTIFACT_WRITTEN,
                log_category=LOG_CATEGORY_INTERNAL,
                level="INFO",
                service="ReportingEngine",
                client_id=client_id,
                audit_id=audit_id,
                report_job_id=report_job_id,
                s3_key=s3_key,
            )

        except Exception as exc:
            # Failure path: update both records to FAILED before re-raising.
            failure_reason = getattr(exc, "error_type", "REPORT_GENERATION_FAILED")
            fail_now = utc_now_iso()
            fail_updates: dict[str, Any] = {
                "status": "FAILED",
                "failure_stage": failure_stage,
                "failure_reason_code": failure_reason,
                "completed_at": fail_now,
                "updated_at": fail_now,
            }
            try:
                self.repository.update_report_job(job_key, fail_updates)
                self.repository.update_report_metadata_fields(meta_key, fail_updates)
            except Exception:
                pass  # Do not mask the original exception.

            self.logger.log(
                evt.REPORT_GENERATION_FAILED,
                event_type=evt.REPORT_GENERATION_FAILED,
                log_category=LOG_CATEGORY_INTERNAL,
                level="ERROR",
                service="ReportingEngine",
                client_id=client_id,
                audit_id=audit_id,
                report_job_id=report_job_id,
                failure_stage=failure_stage,
                failure_reason=failure_reason,
            )
            raise

        # ------------------------------------------------------------------
        # Step 14: Update both records to COMPLETE
        # ------------------------------------------------------------------
        complete_at = utc_now_iso()
        composite_score_str = str(report.executive_summary.composite_score_value)
        job_complete_updates: dict[str, Any] = {
            "status": "COMPLETE",
            "report_id": report.identity.report_id,
            "composite_score": composite_score_str,
            "score_label": report.executive_summary.score_label,
            "endpoint_count": report.executive_summary.endpoint_count,
            "s3_artifact_ref": s3_key,
            "completed_at": complete_at,
            "updated_at": complete_at,
        }
        meta_complete_updates: dict[str, Any] = {
            "status": "COMPLETE",
            "report_id": report.identity.report_id,
            "composite_score": composite_score_str,
            "score_label": report.executive_summary.score_label,
            "endpoint_count": report.executive_summary.endpoint_count,
            "s3_artifact_ref": s3_key,
            "completed_at": complete_at,
            "updated_at": complete_at,
        }
        self.repository.update_report_job(job_key, job_complete_updates)
        self.repository.update_report_metadata_fields(meta_key, meta_complete_updates)

        self.logger.log(
            evt.REPORT_GENERATION_COMPLETE,
            event_type=evt.REPORT_GENERATION_COMPLETE,
            log_category=LOG_CATEGORY_INTERNAL,
            level="INFO",
            service="ReportingEngine",
            client_id=client_id,
            audit_id=audit_id,
            report_job_id=report_job_id,
            report_id=report.identity.report_id,
            composite_score=composite_score_str,
            score_label=report.executive_summary.score_label,
            endpoint_count=report.executive_summary.endpoint_count,
        )

        return {
            "client_id": client_id,
            "audit_id": audit_id,
            "audit_execution_id": audit_execution_id,
            "report_job_id": report_job_id,
            "report_id": report.identity.report_id,
            "report_version": report_version,
            "status": "COMPLETE",
            "composite_score": composite_score_str,
            "score_label": report.executive_summary.score_label,
            "endpoint_count": report.executive_summary.endpoint_count,
            "s3_artifact_ref": s3_key,
        }
