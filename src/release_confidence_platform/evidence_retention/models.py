"""Pydantic models for evidence_retention Workstream A1.1: LegalHold,
LegalHoldEvent, DisposalRecord.

Model stratification (Technical Design Section 7):
  LegalHold        — authoritative current-state hold record, one per audit
                      identity, updated in place. Analogous in pattern to
                      Phase 6's ReportMetadata.
  LegalHoldEvent    — immutable, append-only log of every place/release
                      action, mirroring the platform's existing Job-log
                      convention (ReportJob, CertificationJob, IntelligenceJob).
  DisposalRecord    — durable, queryable evidence that a specific disposal
                      action occurred (FR-A1-5 / AC-A1-6). Never carries a
                      ttl_disposal_at attribute (ADR Non-Negotiable Invariant 1).

These models represent the DynamoDB item shape directly (including PK/SK),
unlike Phase 6/7's stratified presentation-artifact DTOs — LegalHold/
LegalHoldEvent/DisposalRecord are themselves the persisted record, not an
intermediate business object assembled into a separately-shaped item dict.

Serialization: model.to_dict() returns model.model_dump(), mirroring the
convention in audit_platform_integrity/models.py and
deterministic_reporting/models.py.

No custody-period duration value is defined or assumed by any model here.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, field_validator, model_validator

from release_confidence_platform.evidence_retention.constants import (
    DISPOSAL_MECHANISMS,
    DISPOSAL_RECORD_RECORD_TYPE,
    EVIDENCE_CLASSES,
    HOLD_ACTIONS,
    HOLD_STATUS_RELEASED,
    HOLD_STATUSES,
    LEGAL_HOLD_EVENT_RECORD_TYPE,
    LEGAL_HOLD_RECORD_TYPE,
    MARKER_STATUS_PENDING,
    MARKER_STATUSES,
    SWEEP_STATUSES,
)


def _parse_iso8601(value: str) -> datetime:
    """Parse a UTC ISO-8601 timestamp produced by core.time.utc_now_iso().

    Accepts the "Z"-suffixed form this platform's timestamps use.
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# LegalHold (current-state record) — Technical Design Section 7.1
# ---------------------------------------------------------------------------


class LegalHold(BaseModel):
    """Authoritative current hold status for a given audit identity.

    Primary key: PK=CLIENT#{client_id}, SK=AUDIT#{audit_id}#LEGALHOLD.
    One record per (client_id, audit_id). Never deleted; never subject to
    ttl_disposal_at (a hold record is a governance artifact, not evidence).

    hold_version / sweep_status (Legal-Hold Correction B1; Technical Design
    Section 19.1; ADR Decision 9, Non-Negotiable Invariants 12/23): status
    answers "is this audit currently held"; sweep_status answers
    "has the current episode's sweep finished" -- deliberately independent,
    never derived from one another. hold_version is the optimistic-
    concurrency token every Category 1/2 governed-record write conditions
    against (Technical Design Section 19.4); it is incremented by exactly 1
    on every write to this record -- every PLACE and every RELEASE, with no
    exception -- and is never reused, reset, or derived from status.

    marker_s3_key / marker_confirmed_last_modified (Technical Design Section
    19.5.1): additive plumbing for the current transition's S3 canary
    marker, denormalized here the same way sweep_status already is, so a
    future `rcp retention hold status` can report marker state without a
    separate query. Set only by the S3 canary-marker mechanism (Legal-Hold
    Correction B2, not part of B1) -- B1 never writes a non-None value.
    """

    PK: str
    SK: str
    record_type: str
    client_id: str
    audit_id: str
    status: str
    hold_id: str
    hold_version: int
    sweep_status: str
    placed_at: str
    placed_by: str
    reason: str
    hold_count: int
    released_at: str | None = None
    released_by: str | None = None
    marker_s3_key: str | None = None
    marker_confirmed_last_modified: str | None = None

    @field_validator("record_type")
    @classmethod
    def _record_type_must_be_legal_hold(cls, v: str) -> str:
        if v != LEGAL_HOLD_RECORD_TYPE:
            raise ValueError(
                f"record_type must be '{LEGAL_HOLD_RECORD_TYPE}', got {v!r}"
            )
        return v

    @field_validator("status")
    @classmethod
    def _status_in_bounded_set(cls, v: str) -> str:
        if v not in HOLD_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(HOLD_STATUSES)}, got {v!r}"
            )
        return v

    @field_validator("sweep_status")
    @classmethod
    def _sweep_status_in_bounded_set(cls, v: str) -> str:
        if v not in SWEEP_STATUSES:
            raise ValueError(
                f"sweep_status must be one of {sorted(SWEEP_STATUSES)}, got {v!r}"
            )
        return v

    @field_validator("hold_version")
    @classmethod
    def _hold_version_at_least_one(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"hold_version must be >= 1, got {v}")
        return v

    @field_validator("hold_count")
    @classmethod
    def _hold_count_at_least_one(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"hold_count must be >= 1, got {v}")
        return v

    @model_validator(mode="after")
    def _released_fields_required_when_released(self) -> LegalHold:
        if self.status == HOLD_STATUS_RELEASED:
            if self.released_at is None or self.released_by is None:
                raise ValueError(
                    "released_at and released_by are required when "
                    f"status={HOLD_STATUS_RELEASED!r}"
                )
        return self

    def to_dict(self) -> dict:
        """Return a plain dict representation suitable for DynamoDB PutItem."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# LegalHoldEvent (immutable log) — Technical Design Section 7.2
# ---------------------------------------------------------------------------


class LegalHoldEvent(BaseModel):
    """Immutable audit log entry for a single place/release action.

    Primary key: PK=CLIENT#{client_id},
    SK=AUDIT#{audit_id}#LEGALHOLD#{hold_id}#{hold_version}. Write-once,
    append-only. Never mutated after write; never deleted; never subject to
    ttl_disposal_at.

    hold_version (Legal-Hold Correction B1; ADR Non-Negotiable Invariant 25;
    Technical Design Section 19.5.1's "Required consequence", Section
    19.5.2): required per-transition SK discriminator. hold_id identifies
    one legal-hold episode from its PLACE through its eventual RELEASE and
    is held constant across that pair (ADR Invariant 21) -- hold_id alone is
    therefore no longer sufficient to key this record, since it would make
    RELEASE's event write collide with its paired PLACE's at the identical
    key. Non-collision is proved by hold_version's monotonicity alone
    (ADR Invariant 12): no two transitions of the same audit identity ever
    share a hold_version value.

    marker_s3_key / marker_status / marker_confirmed_last_modified
    (Technical Design Section 19.5.1): additive plumbing for the S3 canary
    marker established for this specific transition. B1 never sets
    marker_status to anything other than its initial PENDING default and
    never sets marker_s3_key/marker_confirmed_last_modified to a non-None
    value -- both are set only by the S3 canary-marker mechanism (Legal-Hold
    Correction B2, not part of B1).
    """

    PK: str
    SK: str
    record_type: str
    hold_id: str
    hold_version: int
    client_id: str
    audit_id: str
    action: str
    actor: str
    reason: str
    timestamp: str
    s3_versions_retagged_count: int
    dynamodb_items_updated_count: int
    marker_s3_key: str | None = None
    marker_status: str = MARKER_STATUS_PENDING
    marker_confirmed_last_modified: str | None = None

    @field_validator("record_type")
    @classmethod
    def _record_type_must_be_legal_hold_event(cls, v: str) -> str:
        if v != LEGAL_HOLD_EVENT_RECORD_TYPE:
            raise ValueError(
                f"record_type must be '{LEGAL_HOLD_EVENT_RECORD_TYPE}', got {v!r}"
            )
        return v

    @field_validator("action")
    @classmethod
    def _action_in_bounded_set(cls, v: str) -> str:
        if v not in HOLD_ACTIONS:
            raise ValueError(
                f"action must be one of {sorted(HOLD_ACTIONS)}, got {v!r}"
            )
        return v

    @field_validator("hold_version")
    @classmethod
    def _hold_version_at_least_one(cls, v: int) -> int:
        if v < 1:
            raise ValueError(f"hold_version must be >= 1, got {v}")
        return v

    @field_validator("marker_status")
    @classmethod
    def _marker_status_in_bounded_set(cls, v: str) -> str:
        if v not in MARKER_STATUSES:
            raise ValueError(
                f"marker_status must be one of {sorted(MARKER_STATUSES)}, got {v!r}"
            )
        return v

    @field_validator("s3_versions_retagged_count", "dynamodb_items_updated_count")
    @classmethod
    def _counts_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"count fields must be >= 0, got {v}")
        return v

    def to_dict(self) -> dict:
        """Return a plain dict representation suitable for DynamoDB PutItem."""
        return self.model_dump()


# ---------------------------------------------------------------------------
# DisposalRecord — Technical Design Section 7.3
# ---------------------------------------------------------------------------


class DisposalRecord(BaseModel):
    """Durable, queryable evidence that a specific disposal action occurred.

    Primary key: PK=CLIENT#{client_id}, SK=AUDIT#{audit_id}#DISPOSAL#{disposal_id}.
    One record per disposed S3 object-version or DynamoDB item. Write-once,
    append-only, never mutated after write. Never carries a ttl_disposal_at
    attribute (ADR Non-Negotiable Invariant 1) — this is a compliance/audit-
    trail artifact, not evidence subject to its own custody clock.
    """

    PK: str
    SK: str
    record_type: str
    disposal_id: str
    client_id: str
    audit_id: str
    evidence_class: str
    disposal_mechanism: str
    disposed_identity_ref: str
    disposed_at: str
    recorded_at: str
    source_created_at: str | None = None
    custody_period_days_applied: int | None = None

    @field_validator("record_type")
    @classmethod
    def _record_type_must_be_disposal_record(cls, v: str) -> str:
        if v != DISPOSAL_RECORD_RECORD_TYPE:
            raise ValueError(
                f"record_type must be '{DISPOSAL_RECORD_RECORD_TYPE}', got {v!r}"
            )
        return v

    @field_validator("evidence_class")
    @classmethod
    def _evidence_class_in_bounded_set(cls, v: str) -> str:
        if v not in EVIDENCE_CLASSES:
            raise ValueError(
                f"evidence_class must be one of {sorted(EVIDENCE_CLASSES)}, got {v!r}"
            )
        return v

    @field_validator("disposal_mechanism")
    @classmethod
    def _disposal_mechanism_in_bounded_set(cls, v: str) -> str:
        if v not in DISPOSAL_MECHANISMS:
            raise ValueError(
                f"disposal_mechanism must be one of {sorted(DISPOSAL_MECHANISMS)}, "
                f"got {v!r}"
            )
        return v

    @field_validator("custody_period_days_applied")
    @classmethod
    def _custody_period_days_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError(
                f"custody_period_days_applied must be >= 0, got {v}"
            )
        return v

    @model_validator(mode="after")
    def _recorded_at_not_before_disposed_at(self) -> DisposalRecord:
        # recorded_at (when RCP became aware) is modeled as distinct from, and
        # always >= disposed_at (AWS's own best-available deletion timestamp)
        # per Technical Design Section 7.3 / ADR Decision 4.
        try:
            recorded = _parse_iso8601(self.recorded_at)
            disposed = _parse_iso8601(self.disposed_at)
        except ValueError as exc:
            raise ValueError(
                f"disposed_at/recorded_at must be valid ISO-8601 timestamps: {exc}"
            ) from exc
        if recorded < disposed:
            raise ValueError(
                f"recorded_at ({self.recorded_at!r}) must not be before "
                f"disposed_at ({self.disposed_at!r})"
            )
        return self

    def to_dict(self) -> dict:
        """Return a plain dict representation suitable for DynamoDB PutItem."""
        return self.model_dump()
