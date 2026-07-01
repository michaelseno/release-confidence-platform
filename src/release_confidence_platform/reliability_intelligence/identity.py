"""Phase 5 intelligence job identity and S3 key construction."""

from __future__ import annotations

import uuid

from release_confidence_platform.reliability_intelligence.constants import INTELLIGENCE_VERSION


def generate_intelligence_job_id() -> str:
    """Generate a unique intelligence job identifier with intjob_ prefix."""
    return f"intjob_{uuid.uuid4().hex}"


def build_s3_key(
    client_id: str,
    audit_id: str,
    audit_execution_id: str,
    aggregation_version: str,
    intelligence_version: str,
    intelligence_job_id: str,
) -> str:
    """Build the canonical S3 key for an intelligence artifact.

    Pattern: intelligence/{client_id}/{audit_id}/{audit_execution_id}
             /{aggregation_version}/{intelligence_version}/{intelligence_job_id}/artifact.json

    The intelligence/ prefix is mutually exclusive with raw-results/ (Phase 4). Each
    intelligence_job_id produces a unique, addressable key. Force re-generation writes
    a new key; the previous artifact is preserved at its original key.
    """
    return (
        f"intelligence/{client_id}/{audit_id}/{audit_execution_id}"
        f"/{aggregation_version}/{intelligence_version}/{intelligence_job_id}/artifact.json"
    )


__all__ = ["generate_intelligence_job_id", "build_s3_key", "INTELLIGENCE_VERSION"]
