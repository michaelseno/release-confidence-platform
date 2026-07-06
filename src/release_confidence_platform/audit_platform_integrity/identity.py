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


__all__ = ["generate_certificate_id", "generate_certjob_id"]
