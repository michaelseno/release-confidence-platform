"""Structured log event name constants for the Phase 5 intelligence generation pipeline.

All intelligence generation events are logged with these constants as the event_type
field value in structured JSON logs. Consuming log aggregators and dashboards depend
on these values being stable within intel_v1.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Phase 5 intelligence generation pipeline event names
# ---------------------------------------------------------------------------

INTELLIGENCE_GENERATION_INVOKED = "intelligence_generation_invoked"
INTELLIGENCE_ALREADY_EXISTS = "intelligence_already_exists"
INTELLIGENCE_PREREQUISITE_GATE_FAILED = "intelligence_prerequisite_gate_failed"
INTELLIGENCE_GENERATION_PENDING = "intelligence_generation_pending"
INTELLIGENCE_GENERATION_IN_PROGRESS = "intelligence_generation_in_progress"
INTELLIGENCE_METRICS_COMPLETE = "intelligence_metrics_complete"
INTELLIGENCE_ANALYSIS_COMPLETE = "intelligence_analysis_complete"
INTELLIGENCE_SCORING_COMPLETE = "intelligence_scoring_complete"
INTELLIGENCE_S3_ARTIFACT_WRITTEN = "intelligence_s3_artifact_written"
INTELLIGENCE_GENERATION_COMPLETE = "intelligence_generation_complete"
INTELLIGENCE_GENERATION_FAILED = "intelligence_generation_failed"
