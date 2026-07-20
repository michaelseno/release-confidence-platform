"""Legal hold and disposal record identity generation for evidence_retention.

Follows the same uuid4 hex pattern established in Phase 5 (intjob_), Phase 6
(rptjob_, report_), and Phase 7 (cert_, certjob_): no hyphens, 32-character
hex suffix.
"""

from __future__ import annotations

import uuid

from release_confidence_platform.evidence_retention.constants import (
    DISPOSAL_ID_PREFIX,
    HOLD_ID_PREFIX,
)


def generate_hold_id() -> str:
    """Generate a unique legal hold identifier with the hold_ prefix."""
    return f"{HOLD_ID_PREFIX}{uuid.uuid4().hex}"


def generate_disposal_id() -> str:
    """Generate a unique disposal record identifier with the disp_ prefix."""
    return f"{DISPOSAL_ID_PREFIX}{uuid.uuid4().hex}"


__all__ = ["generate_hold_id", "generate_disposal_id"]
