"""Phase 6 report S3 artifact publisher.

Owns the S3 boundary for Phase 6 report artifacts exclusively.
The engine calls write_artifact() before updating DynamoDB to COMPLETE
to ensure the artifact is durable before the status is visible to Phase 7 consumers.

Key format: reports/{client_id}/{audit_id}/.../{report_job_id}/artifact.json
The key is always constructed by identity.build_s3_key() and is never built here.
The publisher has no knowledge of report business logic or DynamoDB.

Evidence Governance Workstream A1.3d.3 (Technical Design Section 20.7.6):
write_artifact() additionally owns a HoldRepository-backed, ConsistentRead:
true hold-state read immediately before put_object, and writes the
rcp-legal-hold/rcp-evidence-class object tags accordingly -- mirroring
IntelligencePublisher.write_artifact's already-merged pattern
(reliability_intelligence/publisher.py). This module's write path scope is
narrow and fixed: read current hold state, tag the object, write it. Any
other retention-subsystem responsibility (S3-side transition-boundary
coordination, periodic evidence re-tagging, or age-based object cleanup) is
out of this module's scope entirely and lives in separately governed
components this module has no dependency on and no knowledge of.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.constants import (
    EVIDENCE_CLASS_TAG_KEY,
    HOLD_STATUS_ACTIVE,
    LEGAL_HOLD_TAG_KEY,
    LEGAL_HOLD_TAG_VALUE_FALSE,
    LEGAL_HOLD_TAG_VALUE_TRUE,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository


def _parse_report_key_identity(key: str) -> tuple[str, str]:
    """Parse (client_id, audit_id) from a reports/ S3 artifact key
    (Technical Design Section 20.7.6). Expected shape:
    reports/{client_id}/{audit_id}/{audit_execution_id}/{aggregation_version}
    /{intelligence_version}/{report_version}/{report_job_id}/artifact.json
    (9 segments -- one longer than Phase 5's 8-segment intelligence/ key,
    since Phase 6 additionally embeds report_version).
    """
    parts = key.split("/")
    if len(parts) != 9 or parts[0] != "reports" or parts[8] != "artifact.json":
        raise StorageError(
            "Report artifact key does not match the expected "
            "reports/{client_id}/{audit_id}/... shape; cannot resolve "
            "audit identity for legal-hold state resolution.",
            "STORAGE_ERROR",
        )
    client_id, audit_id = parts[1], parts[2]
    if not client_id or not audit_id:
        raise StorageError(
            "Report artifact key does not match the expected "
            "reports/{client_id}/{audit_id}/... shape; cannot resolve "
            "audit identity for legal-hold state resolution.",
            "STORAGE_ERROR",
        )
    return client_id, audit_id


def _report_tagging(hold_state: dict[str, Any] | None) -> str:
    """Compute the rcp-legal-hold/rcp-evidence-class S3 object tagging string
    for one report artifact write, from a freshly read hold state
    (Technical Design Section 20.7.6, ADR Decision 2)."""
    is_actively_held = hold_state is not None and hold_state.get("status") == HOLD_STATUS_ACTIVE
    legal_hold_value = LEGAL_HOLD_TAG_VALUE_TRUE if is_actively_held else LEGAL_HOLD_TAG_VALUE_FALSE
    return urlencode(
        {
            LEGAL_HOLD_TAG_KEY: legal_hold_value,
            EVIDENCE_CLASS_TAG_KEY: "report",
        }
    )


class ReportPublisher:
    """S3 artifact write and read boundary for Phase 6 report artifacts."""

    def __init__(
        self, bucket_name: str, s3_client: Any, hold_repository: HoldRepository | None = None
    ) -> None:
        self.bucket_name = bucket_name
        self.s3_client = s3_client
        self._hold_repository = hold_repository

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        """Write the report artifact JSON to S3, tagged with the audit
        identity's current legal-hold state.

        Uses sort_keys=True and default=str for byte-identical determinism across
        re-serialization. Each generation writes to a unique key (unique report_job_id).

        Write-entry governance preflight (ADR Invariant 31): hold coordination
        must be configured before any hold-state read or AWS mutation.

        Args:
            key: S3 object key (must begin with reports/).
            artifact: Artifact dict to serialize and write.

        Raises:
            StorageError: ``HOLD_COORDINATION_NOT_CONFIGURED`` if this
                instance has no HoldRepository; ``STORAGE_ERROR`` if the
                hold-state read fails or on any S3 PutObject failure.
        """
        if self._hold_repository is None:
            raise StorageError(
                "Hold coordination is not configured", "HOLD_COORDINATION_NOT_CONFIGURED"
            )
        client_id, audit_id = _parse_report_key_identity(key)
        try:
            hold_state = self._hold_repository.get_legal_hold(
                client_id, audit_id, consistent_read=True
            )
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(
                "Legal-hold state could not be resolved prior to report artifact write.",
                "STORAGE_ERROR",
            ) from exc
        tagging = _report_tagging(hold_state)
        body = json.dumps(artifact, sort_keys=True, default=str).encode("utf-8")
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=body,
                ContentType="application/json",
                Tagging=tagging,
            )
        except Exception as exc:
            raise StorageError(
                f"Failed to write report S3 artifact: {exc}", "S3_WRITE_FAILED"
            ) from exc

    def read_artifact(self, key: str) -> dict[str, Any]:
        """Read and deserialize a report artifact JSON from S3.

        Args:
            key: S3 object key from ReportMetadata.s3_artifact_ref.

        Returns:
            Parsed artifact dict.

        Raises:
            StorageError: On any S3 GetObject failure or JSON parse failure.
        """
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except Exception as exc:
            raise StorageError(
                f"Failed to read report S3 artifact: {exc}", "S3_READ_FAILED"
            ) from exc
