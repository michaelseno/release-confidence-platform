"""Phase 6 report repository stub (Phase 6.4 will implement DynamoDB I/O).

Key helper methods (report_job_keys, report_metadata_keys) are fully implemented
because the engine uses them immediately. All read/write methods that require
DynamoDB raise NotImplementedError until Phase 6.4.
"""

from __future__ import annotations

from typing import Any


class ReportRepository:
    """Provides DynamoDB access for Phase 6 report job and metadata records."""

    def __init__(self, table_name: str, dynamodb_client: Any) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client

    # ------------------------------------------------------------------
    # Phase 5 read-only gate (must NOT be a stub — needed by engine)
    # ------------------------------------------------------------------

    def get_intelligence_metadata(
        self,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str,
    ) -> dict[str, Any] | None:
        """Read the Phase 5 IntelligenceMetadata record (prerequisite gate check).

        Returns the record dict if found, or None if absent.
        Phase 6 reads this record but never writes to it.
        """
        raise NotImplementedError(
            "ReportRepository.get_intelligence_metadata: Phase 6.4 pending"
        )

    # ------------------------------------------------------------------
    # Phase 6 idempotency check
    # ------------------------------------------------------------------

    def get_report_metadata(
        self,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str,
        report_version: str,
    ) -> dict[str, Any] | None:
        """Read the Phase 6 ReportMetadata record for idempotency check.

        Returns the record dict if found, or None if this is a first-time generation.
        """
        raise NotImplementedError(
            "ReportRepository.get_report_metadata: Phase 6.4 pending"
        )

    # ------------------------------------------------------------------
    # Key helpers (fully implemented — used by engine without DynamoDB)
    # ------------------------------------------------------------------

    def report_job_keys(
        self,
        client_id: str,
        audit_id: str,
        report_job_id: str,
    ) -> dict[str, str]:
        """Build the PK/SK key dict for a ReportJob record."""
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#RPTJOB#{report_job_id}",
        }

    def report_metadata_keys(
        self,
        client_id: str,
        audit_id: str,
        audit_execution_id: str,
        config_version: str,
        aggregation_version: str,
        intelligence_version: str,
        report_version: str,
    ) -> dict[str, str]:
        """Build the PK/SK key dict for a ReportMetadata record."""
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": (
                f"AUDIT#{audit_id}#EXEC#{audit_execution_id}#CFG#{config_version}"
                f"#AGG#{aggregation_version}#INTEL#{intelligence_version}"
                f"#RPT#{report_version}#META"
            ),
        }

    # ------------------------------------------------------------------
    # Phase 6 writes (stubs)
    # ------------------------------------------------------------------

    def put_report_job_once(self, item: dict[str, Any]) -> None:
        """Write a new ReportJob record (conditional, first-write-wins)."""
        raise NotImplementedError(
            "ReportRepository.put_report_job_once: Phase 6.4 pending"
        )

    def put_report_metadata_once(self, item: dict[str, Any]) -> None:
        """Write a new ReportMetadata record (conditional, first-write-wins)."""
        raise NotImplementedError(
            "ReportRepository.put_report_metadata_once: Phase 6.4 pending"
        )

    def update_report_job(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        """Apply field updates to an existing ReportJob record."""
        raise NotImplementedError(
            "ReportRepository.update_report_job: Phase 6.4 pending"
        )

    def update_report_metadata_fields(
        self, key: dict[str, str], updates: dict[str, Any]
    ) -> None:
        """Apply field updates to an existing ReportMetadata record."""
        raise NotImplementedError(
            "ReportRepository.update_report_metadata_fields: Phase 6.4 pending"
        )
