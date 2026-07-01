"""IntelligenceRetrievalService — read-only query logic for Phase 5.7.

This service is the single owner of intelligence retrieval business logic.
It never writes, updates, or deletes records. All returned objects are either
frozen DTOs or plain dicts from the S3 artifact.

Accepts duck-typed repository and publisher interfaces — no concrete
DynamoDB or S3 code appears here.
"""
from __future__ import annotations

from release_confidence_platform.reliability_intelligence.dtypes import (
    IntelligenceNotFoundDTO,
    IntelligenceStatusDTO,
    IntelligenceSummaryDTO,
)


class IntelligenceRetrievalService:
    """Immutable-output query service for the Intelligence Retrieval Layer."""

    def __init__(self, repository, publisher=None) -> None:
        self._repo = repository
        self._publisher = publisher

    # ------------------------------------------------------------------
    # IRET-U04 — intelligence-status
    # ------------------------------------------------------------------

    def retrieve_status(
        self, filters
    ) -> IntelligenceStatusDTO | IntelligenceNotFoundDTO:
        metadata = self._repo.get_intelligence_metadata(filters)
        if metadata is None:
            return IntelligenceNotFoundDTO(
                reason="INTELLIGENCE_NOT_FOUND",
                client_id=filters.client_id,
                audit_id=filters.audit_id,
            )
        return IntelligenceStatusDTO(
            status=metadata.get("status", "UNKNOWN"),
            intelligence_job_id=metadata.get("intelligence_job_id"),
            composite_score=metadata.get("composite_score"),
            score_label=metadata.get("score_label"),
            endpoint_count=metadata.get("endpoint_count"),
            s3_artifact_ref=metadata.get("s3_artifact_ref"),
            completed_at=metadata.get("completed_at"),
            failure_reason=metadata.get("failure_reason_code"),
        )

    # ------------------------------------------------------------------
    # IRET-U01 — intelligence-summary
    # ------------------------------------------------------------------

    def retrieve_summary(
        self, filters
    ) -> IntelligenceSummaryDTO | IntelligenceNotFoundDTO:
        metadata = self._repo.get_intelligence_metadata(filters)
        if metadata is None:
            return IntelligenceNotFoundDTO(
                reason="INTELLIGENCE_NOT_FOUND",
                client_id=filters.client_id,
                audit_id=filters.audit_id,
            )
        return IntelligenceSummaryDTO(
            intelligence_version=metadata.get(
                "intelligence_version", filters.intelligence_version
            ),
            intelligence_job_id=metadata.get("intelligence_job_id"),
            client_id=metadata.get("client_id", filters.client_id),
            audit_id=metadata.get("audit_id", filters.audit_id),
            audit_execution_id=metadata.get(
                "audit_execution_id", filters.audit_execution_id
            ),
            config_version=metadata.get("config_version", filters.config_version),
            aggregation_version=metadata.get(
                "aggregation_version", filters.aggregation_version
            ),
            status=metadata.get("status", "UNKNOWN"),
            composite_score=metadata.get("composite_score"),
            score_label=metadata.get("score_label"),
            endpoint_count=metadata.get("endpoint_count"),
            s3_artifact_ref=metadata.get("s3_artifact_ref"),
            aggregate_set_hash=metadata.get("aggregate_set_hash"),
            created_at=metadata.get("created_at"),
            completed_at=metadata.get("completed_at"),
        )

    # ------------------------------------------------------------------
    # IRET-U02 — intelligence-detail
    # ------------------------------------------------------------------

    def retrieve_detail(self, filters) -> dict | IntelligenceNotFoundDTO:
        metadata = self._repo.get_intelligence_metadata(filters)
        if metadata is None:
            return IntelligenceNotFoundDTO(
                reason="INTELLIGENCE_NOT_FOUND",
                client_id=filters.client_id,
                audit_id=filters.audit_id,
            )
        s3_ref = metadata.get("s3_artifact_ref")
        if not s3_ref or self._publisher is None:
            return IntelligenceNotFoundDTO(
                reason="ARTIFACT_NOT_READABLE",
                client_id=filters.client_id,
                audit_id=filters.audit_id,
            )
        artifact = self._publisher.read_artifact(s3_ref)
        if artifact is None:
            return IntelligenceNotFoundDTO(
                reason="ARTIFACT_NOT_FOUND",
                client_id=filters.client_id,
                audit_id=filters.audit_id,
            )
        return artifact

    # ------------------------------------------------------------------
    # IRET-U03 — intelligence-methodology
    # ------------------------------------------------------------------

    def retrieve_methodology(self, filters) -> dict | IntelligenceNotFoundDTO:
        result = self.retrieve_detail(filters)
        if isinstance(result, IntelligenceNotFoundDTO):
            return result
        return result.get("methodology_disclosure", {})
