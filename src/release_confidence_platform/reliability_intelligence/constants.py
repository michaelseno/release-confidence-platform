"""All bounded constants for intel_v1 reliability intelligence.

Section 13.7 of the Phase 5 technical design defines the authoritative constant reference.
No algorithm module may define threshold constants inline — all constants must be imported
from this module.
"""

from decimal import Decimal

# ---------------------------------------------------------------------------
# Intelligence version identifier
# ---------------------------------------------------------------------------

INTELLIGENCE_VERSION = "intel_v1"

# ---------------------------------------------------------------------------
# Algorithm name constants
# ---------------------------------------------------------------------------

SUCCESS_RATE_STABILITY_ALGORITHM = "success_rate_stability_v1"
LATENCY_STABILITY_ALGORITHM = "latency_stability_v1"
FAILURE_BURST_ALGORITHM = "failure_burst_v1"
LATENCY_SPIKE_ALGORITHM = "latency_spike_v1"
OUTCOME_CONSISTENCY_ALGORITHM = "outcome_consistency_v1"

# ---------------------------------------------------------------------------
# Stability label constants
# ---------------------------------------------------------------------------

LABEL_STABLE = "STABLE"
LABEL_DEGRADED = "DEGRADED"
LABEL_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# ---------------------------------------------------------------------------
# Consistency label constants
# ---------------------------------------------------------------------------

LABEL_CONSISTENT = "CONSISTENT"
LABEL_INCONSISTENT = "INCONSISTENT"

# ---------------------------------------------------------------------------
# Burst and spike label constants
# ---------------------------------------------------------------------------

LABEL_NO_BURST_DETECTED = "NO_BURST_DETECTED"
LABEL_BURST_SUSPECTED = "BURST_SUSPECTED"
LABEL_NO_SPIKE_DETECTED = "NO_SPIKE_DETECTED"
LABEL_SPIKE_SUSPECTED = "SPIKE_SUSPECTED"

# ---------------------------------------------------------------------------
# Score label constants (Section 13.6)
# ---------------------------------------------------------------------------

SCORE_LABEL_HIGH_CONFIDENCE = "HIGH_CONFIDENCE"
SCORE_LABEL_MODERATE_CONFIDENCE = "MODERATE_CONFIDENCE"
SCORE_LABEL_LOW_CONFIDENCE = "LOW_CONFIDENCE"

# ---------------------------------------------------------------------------
# Numeric thresholds (Section 13.7)
# ---------------------------------------------------------------------------

# Minimum execution count for characterization — below this, return INSUFFICIENT_DATA.
# Not a Decimal: used in integer comparison against integer execution_count fields.
MIN_EXECUTION_COUNT: int = 10

# Minimum latency count for latency stability and spike characterization.
# Not a Decimal: used in integer comparison against integer latency_count fields.
MIN_LATENCY_COUNT: int = 5

# success_rate_stability_v1: success rate at or above this → STABLE.
STABLE_THRESHOLD = Decimal("0.95")

# latency_stability_v1: p99/mean ratio above this → high distributional spread → DEGRADED.
P99_MEAN_RATIO_THRESHOLD = Decimal("3.0")

# latency_stability_v1: max/p95 ratio above this → outlier tail presence → DEGRADED.
MAX_P95_RATIO_THRESHOLD = Decimal("2.0")

# failure_burst_v1: timeout proportion above this → BURST_SUSPECTED.
TIMEOUT_BURST_THRESHOLD = Decimal("0.20")

# latency_spike_v1: max/p99 ratio above this → SPIKE_SUSPECTED.
MAX_P99_RATIO_THRESHOLD = Decimal("3.0")

# outcome_consistency_v1: Bernoulli variance p*(1-p) at or below this → CONSISTENT.
VARIANCE_CONSISTENT_THRESHOLD = Decimal("0.05")

# ---------------------------------------------------------------------------
# Label-to-score mapping (Section 13.2)
# ---------------------------------------------------------------------------

# Must be referenced by scoring.py AND by the S3 artifact methodology_disclosure
# label_to_score_mapping field. Defines the numeric value each analysis label
# contributes to the composite score. INSUFFICIENT_DATA always maps to 0.5
# (neutral — absence of evidence does not penalize or reward).
LABEL_TO_SCORE: dict[str, Decimal] = {
    LABEL_STABLE: Decimal("1.0"),
    LABEL_DEGRADED: Decimal("0.0"),
    LABEL_INSUFFICIENT_DATA: Decimal("0.5"),
    LABEL_CONSISTENT: Decimal("1.0"),
    LABEL_INCONSISTENT: Decimal("0.0"),
    LABEL_NO_BURST_DETECTED: Decimal("1.0"),
    LABEL_BURST_SUSPECTED: Decimal("0.0"),
    LABEL_NO_SPIKE_DETECTED: Decimal("1.0"),
    LABEL_SPIKE_SUSPECTED: Decimal("0.0"),
}

# Scoring: audit_score >= this → HIGH_CONFIDENCE label.
HIGH_CONFIDENCE_THRESHOLD = Decimal("0.80")

# Scoring: audit_score >= this → MODERATE_CONFIDENCE label.
MODERATE_CONFIDENCE_THRESHOLD = Decimal("0.50")

# ---------------------------------------------------------------------------
# Scoring weight constants (Section 13.3)
# ---------------------------------------------------------------------------

WEIGHT_RELIABILITY = Decimal("0.50")
WEIGHT_STABILITY = Decimal("0.20")
WEIGHT_BURST = Decimal("0.15")
WEIGHT_CONSISTENCY = Decimal("0.15")

# ---------------------------------------------------------------------------
# Neutral score for INSUFFICIENT_DATA (Section 13.2)
# ---------------------------------------------------------------------------

# Absence of evidence does not penalize or reward the endpoint.
INSUFFICIENT_DATA_SCORE = Decimal("0.5")
