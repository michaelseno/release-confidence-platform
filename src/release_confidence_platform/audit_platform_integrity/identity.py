"""Certificate and certification job identity generation for Phase 7.

Follows the same uuid4 hex pattern established in Phase 5 (intjob_) and Phase 6
(rptjob_, report_). No hyphens; 32-character hex suffix.
"""

from __future__ import annotations

import uuid

from release_confidence_platform.audit_platform_integrity.constants import (
    CERT_ID_PREFIX,
    CERTJOB_ID_PREFIX,
)


def generate_certificate_id() -> str:
    """Generate a unique certificate identifier with cert_ prefix."""
    return f"{CERT_ID_PREFIX}{uuid.uuid4().hex}"


def generate_certjob_id() -> str:
    """Generate a unique certification job identifier with certjob_ prefix."""
    return f"{CERTJOB_ID_PREFIX}{uuid.uuid4().hex}"


def build_cert_s3_key(
    client_id: str,
    audit_id: str,
    audit_execution_id: str,
    config_version: str,
    aggregation_version: str,
    intelligence_version: str,
    report_version: str,
    cert_version: str,
    certjob_id: str,
) -> str:
    """Build the canonical S3 key for a Phase 7 certificate artifact.

    Pattern: integrity/{client_id}/{audit_id}/{audit_execution_id}
             /{config_version}/{aggregation_version}/{intelligence_version}
             /{report_version}/{cert_version}/{certjob_id}/artifact.json

    The integrity/ prefix is mutually exclusive with reports/ (Phase 6),
    intelligence/ (Phase 5), and raw-results/ (Phase 1/2). Each certjob_id
    segment produces a unique, addressable key. Force re-certification writes
    a new key; the previous certificate artifact is preserved at its original key.
    """
    return (
        f"integrity/{client_id}/{audit_id}/{audit_execution_id}"
        f"/{config_version}/{aggregation_version}/{intelligence_version}"
        f"/{report_version}/{cert_version}/{certjob_id}/artifact.json"
    )


__all__ = ["generate_certificate_id", "generate_certjob_id", "build_cert_s3_key"]
