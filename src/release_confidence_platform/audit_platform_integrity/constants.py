"""All bounded constants for cert_v1 audit platform integrity.

These constants define the stable, version-locked values for the Platform Integrity
Certificate schema (cert_v1). Changes to any value here require a cert_version
increment per the versioning rules in the Phase 7 technical design Section 11.
"""

from __future__ import annotations

CERTIFICATE_VERSION = "cert_v1"
CERT_ID_PREFIX = "cert_"
CERTJOB_ID_PREFIX = "certjob_"

CERT_DOMAIN_IDENTIFIERS: tuple[str, ...] = (
    "RUNNER_HEALTH",
    "EVIDENCE_COMPLETENESS",
    "EVIDENCE_INTEGRITY",
    "EVIDENCE_LINEAGE",
    "OBSERVATION_COVERAGE",
    "SCHEDULER_INTEGRITY",
    "METHODOLOGY_COMPLIANCE",
    "REPORT_INTEGRITY",
)

CERTIFICATION_SUMMARY_MAP: dict[str, str] = {
    "CERTIFIED": "INTEGRITY_VERIFIED",
    "CERTIFICATION_FAILED": "INTEGRITY_FAILED",
    "CERTIFICATION_BLOCKED": "INTEGRITY_BLOCKED",
}

TERMINAL_STATES: frozenset[str] = frozenset({
    "CERTIFIED",
    "CERTIFICATION_FAILED",
    "CERTIFICATION_BLOCKED",
})

DOMAIN_STATUSES: frozenset[str] = frozenset({
    "PASSED",
    "FAILED",
    "BLOCKED",
})
