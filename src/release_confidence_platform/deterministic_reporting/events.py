"""Structured log event name constants for the Phase 6 report generation pipeline.

All report generation events are logged with these constants as the event_type
field value in structured JSON logs. Consuming log aggregators and dashboards depend
on these values being stable within report_v1.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Phase 6 report generation pipeline event names
# ---------------------------------------------------------------------------

REPORT_GENERATION_INVOKED = "report_generation_invoked"
REPORT_ALREADY_EXISTS = "report_already_exists"
REPORT_PREREQUISITE_GATE_FAILED = "report_prerequisite_gate_failed"
REPORT_GENERATION_PENDING = "report_generation_pending"
REPORT_GENERATION_IN_PROGRESS = "report_generation_in_progress"
REPORT_S3_ARTIFACT_WRITTEN = "report_s3_artifact_written"
REPORT_GENERATION_COMPLETE = "report_generation_complete"
REPORT_GENERATION_FAILED = "report_generation_failed"
