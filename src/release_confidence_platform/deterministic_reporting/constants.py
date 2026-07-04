"""All bounded constants for report_v1 deterministic reporting."""

from __future__ import annotations

REPORT_VERSION = "report_v1"
REPORT_JOB_ID_PREFIX = "rptjob_"
REPORT_ID_PREFIX = "report_"

SCORE_LABEL_DESCRIPTIONS: dict[str, str] = {
    "HIGH_CONFIDENCE": (
        "Reliability indicators across all assessed endpoints are strong. "
        "The observed evidence does not indicate material reliability concerns "
        "for the audited release scope."
    ),
    "MODERATE_CONFIDENCE": (
        "Reliability indicators are mixed or partially insufficient. "
        "Review the per-endpoint analysis for areas requiring attention before release."
    ),
    "LOW_CONFIDENCE": (
        "Reliability indicators indicate meaningful reliability risk. "
        "Review the per-endpoint analysis and methodology disclosure for full evidence detail."
    ),
}

SCORE_LABEL_BOUNDED_SET: frozenset[str] = frozenset(SCORE_LABEL_DESCRIPTIONS.keys())
