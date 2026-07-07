"""Structured log event name constants for the Phase 7 certification pipeline.

All certification events are logged with these constants as the event_type field
value in structured JSON logs. Consuming log aggregators depend on these values
being stable within cert_v1.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Phase 7 certification pipeline event names
# ---------------------------------------------------------------------------

CERT_INVOKED = "certification_invoked"
CERT_PENDING = "certification_pending"
CERT_IN_PROGRESS = "certification_in_progress"
CERT_COMPLETE = "certification_complete"
CERT_FAILED = "certification_failed"
CERT_GATE_BLOCKED = "certification_gate_blocked"
CERT_ALREADY_CERTIFIED = "certification_already_certified"
