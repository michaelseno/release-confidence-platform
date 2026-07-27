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

# ---------------------------------------------------------------------------
# LegalHold.sweep_status bounded set (Legal-Hold Correction B1; Technical
# Design Section 19.1; ADR Non-Negotiable Invariant 23).
#
# Tracks completion of the *current* hold episode's pre-existing-record
# sweep, independent of `status` (ADR Decision 9): `status=ACTIVE` answers
# "is this audit currently held"; `sweep_status` answers "has the sweep for
# the current episode finished". Reset to PENDING at the start of every
# PLACE and every RELEASE (each transition has its own sweep). B1 defines
# and stores this field and gates resumability on it (Technical Design
# Section 19.2 step 4 / 19.3 step 2); B1 does not itself perform any sweep
# (that remains CustodySweepClient's, already-merged, unchanged scope) or
# the S3 marker/reconciliation steps that also drive this field toward
# COMPLETE/FAILED (Legal-Hold Correction B2, not part of B1).
# ---------------------------------------------------------------------------

SWEEP_STATUS_PENDING = "PENDING"
SWEEP_STATUS_IN_PROGRESS = "IN_PROGRESS"
SWEEP_STATUS_COMPLETE = "COMPLETE"
SWEEP_STATUS_FAILED = "FAILED"
SWEEP_STATUSES: frozenset[str] = frozenset({
    SWEEP_STATUS_PENDING,
    SWEEP_STATUS_IN_PROGRESS,
    SWEEP_STATUS_COMPLETE,
    SWEEP_STATUS_FAILED,
})

# ---------------------------------------------------------------------------
# Canary-marker status bounded set (Technical Design Section 19.5.1).
#
# B1 scope note: these fields (marker_status on LegalHoldEvent;
# marker_s3_key/marker_confirmed_last_modified on both LegalHold and
# LegalHoldEvent) are additive plumbing only -- B1 adds them to the models
# and repository method signatures so Legal-Hold Correction B2 (the S3
# canary-marker mechanism itself) has somewhere durable to persist to. B1
# has no S3 client dependency anywhere and never sets marker_status to
# anything other than its initial PENDING default.
# ---------------------------------------------------------------------------

MARKER_STATUS_PENDING = "PENDING"
MARKER_STATUS_CONFIRMED = "CONFIRMED"
MARKER_STATUS_FAILED = "FAILED"
MARKER_STATUSES: frozenset[str] = frozenset({
    MARKER_STATUS_PENDING,
    MARKER_STATUS_CONFIRMED,
    MARKER_STATUS_FAILED,
})

# ---------------------------------------------------------------------------
# DynamoDB TransactWriteItems hold-state coordination (Technical Design
# Section 19.4 step 4/5, Section 19.5.6). An engineering reliability choice
# (Technical Design Section 19.4 step 4), not a product tradeoff -- shared
# by both the DynamoDB governed-record coordination mechanism (B1 scope) and
# canary-marker establishment retry (B2 scope, reuses the same reasoned
# value per Technical Design Section 19.5.6 rather than re-justifying it).
# ---------------------------------------------------------------------------

MAX_HOLD_COORDINATION_RETRY_ATTEMPTS = 3

# ---------------------------------------------------------------------------
# Governed error classification for retry exhaustion (Technical Design
# Section 19.15). Both codes are defined here now so the classification
# table is complete and consistent; B1's own code paths only ever raise
# HOLD_STATE_CONCURRENCY_EXCEEDED_CODE -- HOLD_MARKER_ESTABLISHMENT_FAILED_CODE
# is reserved for the S3 canary-marker mechanism (Legal-Hold Correction B2,
# not part of B1), which never runs in B1 since B1 has no S3 client
# dependency at all.
# ---------------------------------------------------------------------------

HOLD_STATE_CONCURRENCY_EXCEEDED_CODE = "HOLD_STATE_CONCURRENCY_EXCEEDED"
HOLD_MARKER_ESTABLISHMENT_FAILED_CODE = "HOLD_MARKER_ESTABLISHMENT_FAILED"

# A third, distinguishable code for the marker integrity/collision failure
# mode (Legal-Hold Correction B2; Technical Design Section 19.5.1/19.5.2 --
# an existing marker found at a conditional-write conflict whose content
# does NOT match the current transition's expected identity tuple). Not
# itself enumerated in Technical Design Section 19.15's table (which covers
# only retry-exhaustion classification) -- this is a distinct failure mode
# (a deterministic identity mismatch, never retried) added here following
# the same established StorageError-subcode pattern
# (DuplicateRunIdError/ConditionalWriteError/HOLD_STATE_CONCURRENCY_EXCEEDED_CODE)
# rather than inventing a new error-handling mechanism.
HOLD_MARKER_INTEGRITY_VIOLATION_CODE = "HOLD_MARKER_INTEGRITY_VIOLATION"

# ---------------------------------------------------------------------------
# S3 canary-marker mechanism (Legal-Hold Correction B2; Technical Design
# Section 19.5.1-19.5.10; ADR Non-Negotiable Invariants 15-24).
# ---------------------------------------------------------------------------

# Required key shape (Technical Design Section 19.5.1):
#   retention-markers/{client_id}/{audit_id}/{hold_id}/{hold_version}-{transition}.marker
# Explicitly NOT one of the four evidence-class prefixes
# (S3_EVIDENCE_CLASS_PREFIXES) -- a marker is governance metadata (Category
# 4), never evidence content, and is never subject to any evidence-class
# Lifecycle rule or enumerated by CustodySweepClient's evidence-retagging
# sweep.
RETENTION_MARKER_KEY_PREFIX = "retention-markers"

# Marker JSON payload schema version (Technical Design Section 19.5.1's
# "self-describing" requirement, extended per this subphase's own scope: a
# schema_version field makes a future format change to the marker payload
# detectable by any reader, including an orphaned marker read back long
# after the code that wrote it may have changed).
MARKER_SCHEMA_VERSION = 1

# The 5-second buffer (Technical Design Section 19.5.5) and the marker
# establishment wall-clock cap (Technical Design Section 19.5.6) are the
# SAME reasoned value, deliberately expressed as one constant reused in two
# places rather than two independently-justified numbers -- Section 19.5.6:
# "the same reasoned value already established for the reconciliation
# buffer, reused rather than independently justified a second time... if
# establishing the marker itself consumes as much time as the buffer's own
# margin, the buffer's sizing assumption... no longer holds."
RECONCILIATION_BUFFER_SECONDS = 5
MARKER_ESTABLISHMENT_WALL_CLOCK_BUDGET_SECONDS = RECONCILIATION_BUFFER_SECONDS
