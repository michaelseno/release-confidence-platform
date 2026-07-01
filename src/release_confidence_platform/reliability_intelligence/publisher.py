"""S3 artifact writer/reader for Phase 5 intelligence artifacts.

Owns the S3 boundary exclusively. The engine calls write_artifact() before updating
DynamoDB to COMPLETE to ensure the artifact is durable before the status is visible
to Phase 6 consumers. read_artifact() is used by the retrieval layer.

The publisher is intentionally simple: it has no knowledge of intelligence business
logic, artifact structure, or DynamoDB. It only serializes/deserializes JSON to/from
a bounded S3 key.
"""

from __future__ import annotations

import json
from typing import Any

from release_confidence_platform.core.exceptions import StorageError


class IntelligencePublisher:
    """S3 artifact write and read boundary for Phase 5 intelligence artifacts."""

    def __init__(self, bucket_name: str, s3_client: Any) -> None:
        self.bucket_name = bucket_name
        self.s3_client = s3_client

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        """Write the intelligence artifact JSON to S3.

        Uses sort_keys=True and default=str for byte-identical determinism across
        re-serialization. The key must follow the intelligence/ key prefix pattern
        constructed by identity.build_s3_key(). The artifact is immutable once
        written — each generation writes to a unique key (unique intelligence_job_id).

        Args:
            key: S3 object key (must begin with intelligence/).
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
                f"Failed to write intelligence S3 artifact: {exc}", "S3_WRITE_FAILED"
            ) from exc

    def read_artifact(self, key: str) -> dict[str, Any]:
        """Read and deserialize an intelligence artifact JSON from S3.

        Args:
            key: S3 object key from IntelligenceMetadata.s3_artifact_ref.

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
                f"Failed to read intelligence S3 artifact: {exc}", "S3_READ_FAILED"
            ) from exc
