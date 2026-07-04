"""Phase 6.7 Report Retrieval Service — read-only query logic.

This service is the single owner of report retrieval business logic.
It never writes, updates, or deletes records. All returned objects are either
plain dicts from DynamoDB/S3 or a fully validated ReleaseConfidenceReport DTO.

Accepts duck-typed repository and publisher interfaces — no concrete
DynamoDB or S3 code appears here.

Deviation from spec note:
    The spec describes get_report_dto() as calling ReportBuilder().build() on the
    S3 artifact. However, the Phase 6 S3 artifact is report.model_dump() (a
    serialised ReleaseConfidenceReport), not the Phase 5 intelligence artifact
    that ReportBuilder expects. ReleaseConfidenceReport.model_validate() is the
    correct round-trip for the stored artifact format.
"""

from __future__ import annotations

from release_confidence_platform.core.exceptions import ValidationError
from release_confidence_platform.deterministic_reporting.models import ReleaseConfidenceReport


class ReportRetrievalService:
    """Immutable-output query service for the Phase 6 Report Retrieval Layer."""

    def __init__(self, repository, publisher) -> None:
        self._repository = repository
        self._publisher = publisher

    # ------------------------------------------------------------------
    # DynamoDB-only read (report-status)
    # ------------------------------------------------------------------

    def get_report_status(
        self,
        client_id: str,
        audit_id: str,
        exec_id: str,
        config_v: str,
        agg_v: str,
        intel_v: str,
        report_v: str,
    ) -> dict | None:
        """Read the ReportMetadata record from DynamoDB only.

        No S3 access is performed.

        Args:
            client_id: Client identifier.
            audit_id: Audit identifier.
            exec_id: Audit execution identity.
            config_v: Configuration version.
            agg_v: Aggregation version.
            intel_v: Intelligence version.
            report_v: Report version.

        Returns:
            ReportMetadata dict if found, or None if absent.
        """
        return self._repository.get_report_metadata(
            client_id, audit_id, exec_id, config_v, agg_v, intel_v, report_v
        )

    # ------------------------------------------------------------------
    # DynamoDB -> S3 reads (all other report- commands)
    # ------------------------------------------------------------------

    def get_report_artifact(
        self,
        client_id: str,
        audit_id: str,
        exec_id: str,
        config_v: str,
        agg_v: str,
        intel_v: str,
        report_v: str,
    ) -> dict:
        """Load and return the Phase 6 S3 report artifact dict.

        The Phase 6 S3 artifact is the serialised ReleaseConfidenceReport
        (report.model_dump()) written by the ReportingEngine.

        Args:
            client_id: Client identifier.
            audit_id: Audit identifier.
            exec_id: Audit execution identity.
            config_v: Configuration version.
            agg_v: Aggregation version.
            intel_v: Intelligence version.
            report_v: Report version.

        Returns:
            The parsed S3 artifact dict.

        Raises:
            ValidationError: If metadata is missing or has no s3_artifact_ref.
        """
        metadata = self._repository.get_report_metadata(
            client_id, audit_id, exec_id, config_v, agg_v, intel_v, report_v
        )
        if metadata is None or not metadata.get("s3_artifact_ref"):
            raise ValidationError("REPORT_NOT_FOUND")
        return self._publisher.read_artifact(metadata["s3_artifact_ref"])

    def get_report_dto(
        self,
        client_id: str,
        audit_id: str,
        exec_id: str,
        config_v: str,
        agg_v: str,
        intel_v: str,
        report_v: str,
    ) -> ReleaseConfidenceReport:
        """Load the Phase 6 S3 artifact and return a ReleaseConfidenceReport DTO.

        The Phase 6 S3 artifact is the serialised report (report.model_dump()).
        ReleaseConfidenceReport.model_validate() reconstructs the DTO from this
        format, which is the correct round-trip for the stored artifact.

        Args:
            client_id: Client identifier.
            audit_id: Audit identifier.
            exec_id: Audit execution identity.
            config_v: Configuration version.
            agg_v: Aggregation version.
            intel_v: Intelligence version.
            report_v: Report version.

        Returns:
            Fully populated ReleaseConfidenceReport DTO.

        Raises:
            ValidationError: If metadata is missing or has no s3_artifact_ref.
        """
        metadata = self._repository.get_report_metadata(
            client_id, audit_id, exec_id, config_v, agg_v, intel_v, report_v
        )
        if metadata is None or not metadata.get("s3_artifact_ref"):
            raise ValidationError("REPORT_NOT_FOUND")
        artifact = self._publisher.read_artifact(metadata["s3_artifact_ref"])
        return ReleaseConfidenceReport.model_validate(artifact)
