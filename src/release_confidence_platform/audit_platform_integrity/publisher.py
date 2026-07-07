"""Phase 7 Platform Integrity Certificate S3 artifact publisher.

Owns the S3 write boundary for Phase 7 certificate artifacts exclusively.
All writes target the integrity/ prefix only. The publisher has no write path
to reports/ (Phase 6), intelligence/ (Phase 5), or raw-results/ (Phase 1/2).

Key format: integrity/{client_id}/{audit_id}/.../{certjob_id}/artifact.json
The key is always constructed by identity.build_cert_s3_key() and is never
built here. The publisher has no knowledge of certification business logic
or DynamoDB.
"""

from __future__ import annotations

import json
from typing import Any

from release_confidence_platform.core.exceptions import StorageError


class CertificationPublisher:
    """S3 artifact write boundary for Phase 7 certificate artifacts."""

    def __init__(self, bucket_name: str, s3_client: Any) -> None:
        self.bucket_name = bucket_name
        self.s3_client = s3_client

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        """Write the certificate artifact JSON to S3 under the integrity/ prefix.

        Uses sort_keys=True for byte-identical determinism across re-serialization.
        Each invocation writes to a unique key (unique certjob_id segment).

        Args:
            key: S3 object key. Must begin with integrity/.
            artifact: Certificate dict to serialize and write.

        Raises:
            AssertionError: If key does not start with 'integrity/'. Programming-error guard.
            StorageError: On any S3 PutObject failure.
        """
        assert key.startswith("integrity/"), (
            f"Phase 7 publisher write attempted to non-integrity/ key prefix: {key!r}. "
            "Phase 7 certificate writes must target only the integrity/ S3 prefix."
        )
        body = json.dumps(artifact, sort_keys=True, default=str).encode("utf-8")
        try:
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=body,
                ContentType="application/json",
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
            StorageError: On any S3 GetObject failure or JSON parse failure.
        """
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            return json.loads(response["Body"].read().decode("utf-8"))
        except Exception as exc:
            raise StorageError(
                f"Failed to read certificate S3 artifact: {exc}",
                "S3_CERTIFICATE_READ_FAILURE",
            ) from exc
