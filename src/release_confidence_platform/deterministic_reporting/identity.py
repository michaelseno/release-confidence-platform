"""Report artifact identity and S3 key construction for Phase 6 deterministic reporting."""

from __future__ import annotations

import uuid

from release_confidence_platform.deterministic_reporting.constants import (
    REPORT_ID_PREFIX,
    REPORT_JOB_ID_PREFIX,
)


def generate_report_job_id() -> str:
    """Generate a unique report job identifier with rptjob_ prefix."""
    return f"{REPORT_JOB_ID_PREFIX}{uuid.uuid4().hex}"


def generate_report_id() -> str:
    """Generate a unique report identifier with report_ prefix."""
    return f"{REPORT_ID_PREFIX}{uuid.uuid4().hex}"


def build_s3_key(
    client_id: str,
    audit_id: str,
    audit_execution_id: str,
    aggregation_version: str,
    intelligence_version: str,
    report_version: str,
    report_job_id: str,
) -> str:
    """Build the canonical S3 key for a Phase 6 report artifact.

    Pattern: reports/{client_id}/{audit_id}/{audit_execution_id}
             /{aggregation_version}/{intelligence_version}/{report_version}
             /{report_job_id}/artifact.json

    The reports/ prefix is mutually exclusive with intelligence/ (Phase 5)
    and raw-results/ (Phase 1/2). Each report_job_id produces a unique,
    addressable key. Force re-generation writes a new key; the previous
    artifact is preserved at its original key.
    """
    return (
        f"reports/{client_id}/{audit_id}/{audit_execution_id}"
        f"/{aggregation_version}/{intelligence_version}/{report_version}"
        f"/{report_job_id}/artifact.json"
    )


__all__ = ["generate_report_id", "generate_report_job_id", "build_s3_key"]
