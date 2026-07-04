"""Phase 6 report S3 artifact publisher.

Owns the S3 boundary for Phase 6 report artifacts exclusively.
The engine calls write_artifact() before updating DynamoDB to COMPLETE
to ensure the artifact is durable before the status is visible to Phase 7 consumers.

Key format: reports/{client_id}/{audit_id}/.../{report_job_id}/artifact.json
The key is always constructed by identity.build_s3_key() and is never built here.
The publisher has no knowledge of report business logic or DynamoDB.
"""

from __future__ import annotations

import json
from typing import Any

from release_confidence_platform.core.exceptions import StorageError


class ReportPublisher:
    """S3 artifact write and read boundary for Phase 6 report artifacts."""

    def __init__(self, bucket_name: str, s3_client: Any) -> None:
        self.bucket_name = bucket_name
        self.s3_client = s3_client

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        """Write the report artifact JSON to S3.

        Uses sort_keys=True and default=str for byte-identical determinism across
        re-serialization. Each generation writes to a unique key (unique report_job_id).

        Args:
            key: S3 object key (must begin with reports/).
            artifact: Artifact dict to serialize and write.

        Raises:
            StorageError: On any S3 PutObject failure.
        """
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
