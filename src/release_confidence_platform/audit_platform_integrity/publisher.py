"""Phase 7 Platform Integrity Certificate S3 artifact publisher.

Owns the S3 write boundary for Phase 7 certificate artifacts exclusively.
All writes target the integrity/ prefix only. The publisher has no write path
to reports/ (Phase 6), intelligence/ (Phase 5), or raw-results/ (Phase 1/2).

Key format: integrity/{client_id}/{audit_id}/.../{certjob_id}/artifact.json
The key is always constructed by identity.build_cert_s3_key() and is never
built here. The publisher has no knowledge of certification business logic
or DynamoDB.

Evidence Governance Workstream A1.3d.4 (Technical Design Section 20.8.1):
write_artifact() additionally owns a HoldRepository-backed, ConsistentRead:
true hold-state read immediately before put_object, and writes the
rcp-legal-hold/rcp-evidence-class object tags accordingly -- mirroring
ReportPublisher.write_artifact's already-merged pattern
(deterministic_reporting/publisher.py). The canonical 11-segment key parser
(_parse_cert_key_identity) replaces the prior prefix-only assertion as the
authoritative structural validation for write_artifact; read_artifact's
existing prefix-only guard is unaffected. This module's write path scope is
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


def _parse_cert_key_identity(key: str) -> tuple[str, str]:
    """Parse (client_id, audit_id) from an integrity/ S3 artifact key
    (Technical Design Section 20.8.1). Expected shape:
    integrity/{client_id}/{audit_id}/{audit_execution_id}/{config_version}
    /{aggregation_version}/{intelligence_version}/{report_version}
    /{cert_version}/{certjob_id}/artifact.json (11 segments).

    Replaces the prior `assert key.startswith("integrity/")` guard as the
    authoritative structural validation for write_artifact -- a key that
    merely starts with integrity/ is not guaranteed to have the full
    11-segment shape client_id/audit_id derivation depends on.
    """
    parts = key.split("/")
    if len(parts) != 11 or parts[0] != "integrity" or parts[10] != "artifact.json":
        raise StorageError(
            "Certificate artifact key does not match the expected "
            "integrity/{client_id}/{audit_id}/... shape; cannot resolve "
            "audit identity for legal-hold state resolution.",
            "STORAGE_ERROR",
        )
    client_id, audit_id = parts[1], parts[2]
    if not client_id or not audit_id:
        raise StorageError(
            "Certificate artifact key does not match the expected "
            "integrity/{client_id}/{audit_id}/... shape; cannot resolve "
            "audit identity for legal-hold state resolution.",
            "STORAGE_ERROR",
        )
    return client_id, audit_id


def _cert_tagging(hold_state: dict[str, Any] | None) -> str:
    """Compute the rcp-legal-hold/rcp-evidence-class S3 object tagging string
    for one certificate artifact write, from a freshly read hold state
    (Technical Design Section 20.8.1, ADR Decision 2)."""
    is_actively_held = hold_state is not None and hold_state.get("status") == HOLD_STATUS_ACTIVE
    legal_hold_value = LEGAL_HOLD_TAG_VALUE_TRUE if is_actively_held else LEGAL_HOLD_TAG_VALUE_FALSE
    return urlencode(
        {
            LEGAL_HOLD_TAG_KEY: legal_hold_value,
            EVIDENCE_CLASS_TAG_KEY: "certificate",
        }
    )


class CertificationPublisher:
    """S3 artifact write boundary for Phase 7 certificate artifacts."""

    def __init__(
        self, bucket_name: str, s3_client: Any, hold_repository: HoldRepository | None = None
    ) -> None:
        self.bucket_name = bucket_name
        self.s3_client = s3_client
        self._hold_repository = hold_repository

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        """Write the certificate artifact JSON to S3 under the integrity/ prefix,
        tagged with the audit identity's current legal-hold state.

        Uses sort_keys=True for byte-identical determinism across re-serialization.
        Each invocation writes to a unique key (unique certjob_id segment).

        Write-entry governance preflight (ADR Invariant 31): hold coordination
        must be configured before any key parsing, hold-state read, or AWS
        mutation -- this check runs before key parsing, so a missing
        HoldRepository is reported even for an otherwise-malformed key.

        Args:
            key: S3 object key. Must begin with integrity/ and have the
                canonical 11-segment shape (Technical Design Section 20.8.1).
            artifact: Certificate dict to serialize and write.

        Raises:
            StorageError: ``HOLD_COORDINATION_NOT_CONFIGURED`` if this
                instance has no HoldRepository; ``STORAGE_ERROR`` if the key
                does not match the canonical 11-segment shape, if the
                hold-state read fails, or on any S3 PutObject failure
                (``S3_CERTIFICATE_WRITE_FAILURE``).
        """
        if self._hold_repository is None:
            raise StorageError(
                "Hold coordination is not configured", "HOLD_COORDINATION_NOT_CONFIGURED"
            )
        client_id, audit_id = _parse_cert_key_identity(key)
        try:
            hold_state = self._hold_repository.get_legal_hold(
                client_id, audit_id, consistent_read=True
            )
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(
                "Legal-hold state could not be resolved prior to certificate artifact write.",
                "STORAGE_ERROR",
            ) from exc
        tagging = _cert_tagging(hold_state)
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
                f"Failed to write certificate S3 artifact: {exc}", "S3_CERTIFICATE_WRITE_FAILURE"
            ) from exc

    def read_artifact(self, key: str) -> dict[str, Any]:
        """Read and deserialize a certificate artifact JSON from S3.

        Args:
            key: S3 object key from CertificationMetadata.s3_certificate_ref.

        Returns:
            Parsed certificate artifact dict.

        Raises:
            AssertionError: If key does not start with 'integrity/'. Programming-error guard.
            StorageError: On any S3 GetObject failure or JSON parse failure.
        """
        assert key.startswith("integrity/"), (
            f"read_artifact key must start with 'integrity/', got: {key!r}"
        )
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except Exception as exc:
            raise StorageError(
                f"Failed to read certificate S3 artifact: {exc}",
                "S3_CERTIFICATE_READ_FAILURE",
            ) from exc
