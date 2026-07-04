"""Phase 6 report artifact publisher stub (Phase 6.4 will implement S3 I/O).

This stub satisfies the engine's import contract. All methods raise NotImplementedError
until Phase 6.4 wires the real S3 implementation.
"""

from __future__ import annotations

from typing import Any

from release_confidence_platform.core.exceptions import StorageError  # noqa: F401


class ReportPublisher:
    """Publishes and retrieves Phase 6 report artifacts from S3."""

    def __init__(self, bucket_name: str, s3_client: Any) -> None:
        self.bucket_name = bucket_name
        self.s3_client = s3_client

    def write_artifact(self, key: str, artifact: dict[str, Any]) -> None:
        """Write a serialised report artifact to S3 at the given key."""
        raise NotImplementedError("ReportPublisher.write_artifact: Phase 6.4 implementation pending")

    def read_artifact(self, key: str) -> dict[str, Any]:
        """Read and deserialise an artifact from S3 at the given key."""
        raise NotImplementedError("ReportPublisher.read_artifact: Phase 6.4 implementation pending")
