"""Bounded constants for the evidence_retention package (Workstream A1.1).

Defines record-type literals, bounded value sets, ID prefixes, S3 legal-hold
tag key/value constants, and the DynamoDB SK-namespace markers shared by
hold_repository.py and disposal_repository.py.

No custody-period duration value is defined here. Per the companion ADR
(`docs/architecture/adr_evidence_retention_disposal_enforcement.md`, Decision 5
and Non-Negotiable Invariant 3) and Technical Design Section 14, the
custody-period duration is sourced exclusively from external stage/
evidence-class configuration and must never be hardcoded in application code.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Record type literals (Technical Design Section 7.1 / 7.2 / 7.3)
# ---------------------------------------------------------------------------

LEGAL_HOLD_RECORD_TYPE = "legal_hold"
LEGAL_HOLD_EVENT_RECORD_TYPE = "legal_hold_event"
DISPOSAL_RECORD_RECORD_TYPE = "disposal_record"

# ---------------------------------------------------------------------------
# ID prefixes (Technical Design Section 11)
# ---------------------------------------------------------------------------

HOLD_ID_PREFIX = "hold_"
DISPOSAL_ID_PREFIX = "disp_"

# ---------------------------------------------------------------------------
# LegalHold.status / LegalHoldEvent.action bounded sets (Section 7.1 / 7.2)
# ---------------------------------------------------------------------------

HOLD_STATUS_ACTIVE = "ACTIVE"
HOLD_STATUS_RELEASED = "RELEASED"
HOLD_STATUSES: frozenset[str] = frozenset({HOLD_STATUS_ACTIVE, HOLD_STATUS_RELEASED})

HOLD_ACTION_PLACE = "PLACE"
HOLD_ACTION_RELEASE = "RELEASE"
HOLD_ACTIONS: frozenset[str] = frozenset({HOLD_ACTION_PLACE, HOLD_ACTION_RELEASE})

# ---------------------------------------------------------------------------
# DisposalRecord.evidence_class bounded set (Section 7.3)
# ---------------------------------------------------------------------------

EVIDENCE_CLASSES: frozenset[str] = frozenset({
    "raw_evidence",
    "aggregate_metadata",
    "intelligence",
    "report",
    "certificate",
    "metadata_generic",
})

# ---------------------------------------------------------------------------
# DisposalRecord.disposal_mechanism bounded set (Section 7.3)
# ---------------------------------------------------------------------------

DISPOSAL_MECHANISM_S3_LIFECYCLE_EXPIRATION = "S3_LIFECYCLE_EXPIRATION"
DISPOSAL_MECHANISM_S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION = (
    "S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION"
)
DISPOSAL_MECHANISM_DYNAMODB_TTL = "DYNAMODB_TTL"
DISPOSAL_MECHANISMS: frozenset[str] = frozenset({
    DISPOSAL_MECHANISM_S3_LIFECYCLE_EXPIRATION,
    DISPOSAL_MECHANISM_S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION,
    DISPOSAL_MECHANISM_DYNAMODB_TTL,
})

# ---------------------------------------------------------------------------
# S3 legal-hold tag key/value constants (ADR Decision 2) — reserved for the
# later subphase (A1.2/A1.3) that performs S3 object tagging. Defined here
# now so the tag vocabulary has a single source of truth from the start.
# ---------------------------------------------------------------------------

LEGAL_HOLD_TAG_KEY = "rcp-legal-hold"
EVIDENCE_CLASS_TAG_KEY = "rcp-evidence-class"
LEGAL_HOLD_TAG_VALUE_TRUE = "true"
LEGAL_HOLD_TAG_VALUE_FALSE = "false"

# ---------------------------------------------------------------------------
# DynamoDB SK-namespace markers (ADR Non-Negotiable Invariant 6; Technical
# Design Section 5.2 / 6).
#
# Deliberately defined WITHOUT a trailing "#": the LegalHold current-state
# record's SK terminates exactly at "...#LEGALHOLD" (no further segment),
# while LegalHoldEvent's SK continues as "...#LEGALHOLD#{hold_id}". A
# trailing-"#" marker would fail to match the current-state record's SK.
# Both SK shapes contain the marker as defined here as a substring — this
# mirrors the rationale documented for Phase 7's _PHASE7_SK_MARKERS in
# audit_platform_integrity/repository.py.
# ---------------------------------------------------------------------------

LEGALHOLD_SK_MARKER = "#LEGALHOLD"
DISPOSAL_SK_MARKER = "#DISPOSAL"

# ---------------------------------------------------------------------------
# CustodySweepClient (A1.2/A1.3) — cross-phase DynamoDB attribute names and
# S3 evidence-class prefixes requiring custody-sweep coverage. Defined here
# now for the same single-source-of-truth reason as the S3 legal-hold tag
# constants above (Technical Design Section 6/11 amendment).
# ---------------------------------------------------------------------------

TTL_DISPOSAL_AT_ATTRIBUTE = "ttl_disposal_at"
CUSTODY_EXPIRES_AT_ATTRIBUTE = "custody_expires_at"

# S3 key prefixes requiring CustodySweepClient's per-version legal-hold
# tagging sweep coverage (Technical Design Section 5.2/8): raw execution
# evidence (Phase 1/2/3), intelligence (Phase 5), reports (Phase 6),
# certificates (Phase 7). Confirmed by direct inspection of each phase's
# write path (packages/storage/s3_client.py, reliability_intelligence/
# identity.py, deterministic_reporting/identity.py,
# audit_platform_integrity/identity.py::build_cert_s3_key) — each writes
# under f"{prefix}/{client_id}/{audit_id}/...". Phase 4 aggregation is
# DynamoDB-only in the current schema (confirmed: aggregation/repository.py
# and aggregation/lineage.py never call any S3 client) and therefore has no
# corresponding entry here.
S3_EVIDENCE_CLASS_PREFIXES: tuple[str, ...] = (
    "raw-results",
    "intelligence",
    "reports",
    "integrity",
)
