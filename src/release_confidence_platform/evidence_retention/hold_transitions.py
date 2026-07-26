"""Authoritative PLACE/RELEASE hold-state transition sequences.

Legal-Hold Correction B1 (companion ADR Decision 9, Non-Negotiable
Invariants 12/21/23/24; Technical Design Section 19.2 "Hold-Placement
Sequence", Section 19.3 "Hold-Release Sequence").

Scope: this module implements exactly the DynamoDB-authoritative decision
logic those two sequences specify -- deciding whether an invocation is a
genuine new episode, a resumption of an interrupted transition, or a stale
no-op/rejection; generating hold_id once per episode and reusing it for the
paired transition; incrementing hold_version by exactly 1 on every write
(ADR Invariant 12); and persisting the LegalHoldEvent + LegalHold writes for
that decision via HoldRepository's existing, unchanged guarded CRUD.

Deliberately excluded (see docs/backend/legal_hold_correction_b1_*_implementation_report.md
for the full scope boundary): the canary marker (Technical Design Section
19.5), the CustodySweepClient sweep (Section 19.6), and the S3/DynamoDB
reconciliation passes -- none of Section 19.2's steps 5-9 or Section 19.3's
steps 4-7 are implemented here. Callers (a future RetentionService, not yet
built anywhere in this codebase) use should_run_sweep on the returned
HoldTransitionOutcome to decide whether to proceed with that later work.

No S3 client dependency of any kind exists anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.constants import (
    HOLD_ACTION_PLACE,
    HOLD_ACTION_RELEASE,
    HOLD_STATUS_ACTIVE,
    HOLD_STATUS_RELEASED,
    SWEEP_STATUS_COMPLETE,
    SWEEP_STATUS_PENDING,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.evidence_retention.identity import generate_hold_id


class HoldNotActiveError(StorageError):
    """Raised when `release` is invoked and there is nothing eligible to
    release: the audit was never held, or its most recent episode already
    reached RELEASED with sweep_status=COMPLETE (Technical Design Section
    19.3 step 2, third case; Section 8's existing idempotency contract --
    "a second release attempt likely indicates operator confusion... worth
    surfacing, not silently ignored")."""

    def __init__(self, message: str = "No active legal hold to release"):
        super().__init__(message, "HOLD_NOT_ACTIVE")


@dataclass(frozen=True)
class HoldTransitionOutcome:
    """Result of a single place()/release() invocation.

    is_noop=True means this invocation performed no LegalHold/LegalHoldEvent
    write at all -- Technical Design Section 19.2 step 4's sweep_status=
    COMPLETE gate (ADR Invariant 23). A caller must return immediately
    without proceeding to any marker/sweep/reconciliation step, and without
    modifying LegalHoldEvent in any way.

    should_run_sweep=True means sweep_status != COMPLETE for the returned
    episode (either a fresh write just set it to PENDING, or an interrupted
    episode is being resumed) and a future RetentionService should proceed
    with the marker/sweep/reconciliation sequence this module does not
    implement. is_noop and should_run_sweep are never both True.
    """

    client_id: str
    audit_id: str
    hold_id: str
    hold_version: int
    status: str
    sweep_status: str
    is_noop: bool
    should_run_sweep: bool


def is_hold_fully_enforced(hold_state: dict[str, Any] | None) -> bool:
    """Technical Design Section 19.6: "A caller must never treat
    status=ACTIVE alone as proof that every pre-existing record/object is
    protected -- only status=ACTIVE AND sweep_status=COMPLETE is that
    proof." This is the direct, queryable answer -- a future `rcp retention
    hold status` command should report both fields (Section 19.6) and could
    use this helper rather than re-deriving the conjunction inline.
    """
    if hold_state is None:
        return False
    return (
        hold_state.get("status") == HOLD_STATUS_ACTIVE
        and hold_state.get("sweep_status") == SWEEP_STATUS_COMPLETE
    )


class HoldTransitions:
    """Authoritative PLACE/RELEASE sequencing over HoldRepository's guarded
    LegalHold/LegalHoldEvent CRUD (Technical Design Section 19.2/19.3)."""

    def __init__(self, hold_repository: HoldRepository) -> None:
        self._holds = hold_repository

    # ------------------------------------------------------------------
    # PLACE — Technical Design Section 19.2, steps 1-4
    # ------------------------------------------------------------------

    def place(
        self,
        client_id: str,
        audit_id: str,
        actor: str,
        reason: str,
        now: str,
    ) -> HoldTransitionOutcome:
        """Technical Design Section 19.2 steps 1-4 only. Steps 5-9 (canary
        marker, sweep, reconciliation, sweep_status -> COMPLETE) are Legal-Hold
        Correction B2/C+D/E/F scope, invoked by a future caller using this
        outcome's should_run_sweep flag -- not performed here.
        """
        current = self._holds.get_legal_hold(client_id, audit_id)

        if current is None or current.get("status") == HOLD_STATUS_RELEASED:
            # Step 3: no record exists, or the existing record's status is
            # RELEASED -- this is a genuine new hold episode. A fresh
            # hold_id is generated once, here, and is reused unchanged by
            # this episode's eventual paired RELEASE (Technical Design
            # Section 19.5.2's corrected identity model; ADR Invariant 21).
            hold_id = generate_hold_id()
            hold_version = int(current["hold_version"]) + 1 if current else 1
            hold_count = int(current["hold_count"]) + 1 if current else 1
            self._holds.write_hold_event(
                client_id=client_id,
                audit_id=audit_id,
                hold_id=hold_id,
                hold_version=hold_version,
                action=HOLD_ACTION_PLACE,
                actor=actor,
                reason=reason,
                timestamp=now,
                s3_versions_retagged_count=0,
                dynamodb_items_updated_count=0,
            )
            # This write must be confirmed durably committed before any
            # sweep begins (Technical Design Section 19.1's "effective
            # ordering", made load-bearing by ADR Invariant 13) -- that
            # ordering property is preserved here simply by this being a
            # synchronous call that returns (or raises) before this method
            # returns to its caller; no sweep is invoked by this module.
            self._holds.upsert_hold(
                client_id=client_id,
                audit_id=audit_id,
                status=HOLD_STATUS_ACTIVE,
                hold_id=hold_id,
                hold_version=hold_version,
                sweep_status=SWEEP_STATUS_PENDING,
                placed_at=now,
                placed_by=actor,
                reason=reason,
                hold_count=hold_count,
            )
            return HoldTransitionOutcome(
                client_id=client_id,
                audit_id=audit_id,
                hold_id=hold_id,
                hold_version=hold_version,
                status=HOLD_STATUS_ACTIVE,
                sweep_status=SWEEP_STATUS_PENDING,
                is_noop=False,
                should_run_sweep=True,
            )

        # current["status"] == ACTIVE: a re-run of an already-placed hold.
        # RetentionService must NOT call upsert_hold again here (no new
        # hold_version, no new LegalHoldEvent) -- what happens next depends
        # on sweep_status, not on status alone (the specific defect
        # Technical Design Section 19.2 step 4 / ADR Invariant 23 fixes).
        if current.get("sweep_status") == SWEEP_STATUS_COMPLETE:
            # Stale re-invocation with nothing left to resume: pure no-op,
            # return immediately without touching LegalHoldEvent or
            # attempting any further step (ADR Invariant 23). This is the
            # specific regression this correction closes -- see the
            # implementation report's traceability for required behavior 5.
            return HoldTransitionOutcome(
                client_id=client_id,
                audit_id=audit_id,
                hold_id=current["hold_id"],
                hold_version=current["hold_version"],
                status=HOLD_STATUS_ACTIVE,
                sweep_status=SWEEP_STATUS_COMPLETE,
                is_noop=True,
                should_run_sweep=False,
            )

        # sweep_status in {PENDING, IN_PROGRESS, FAILED}: genuine resumption
        # of an interrupted sweep -- reuse the existing hold_id/hold_version
        # unchanged, no new write.
        return HoldTransitionOutcome(
            client_id=client_id,
            audit_id=audit_id,
            hold_id=current["hold_id"],
            hold_version=current["hold_version"],
            status=HOLD_STATUS_ACTIVE,
            sweep_status=current.get("sweep_status", SWEEP_STATUS_PENDING),
            is_noop=False,
            should_run_sweep=True,
        )

    # ------------------------------------------------------------------
    # RELEASE — Technical Design Section 19.3, steps 1-3
    # ------------------------------------------------------------------

    def release(
        self,
        client_id: str,
        audit_id: str,
        actor: str,
        reason: str,
        now: str,
    ) -> HoldTransitionOutcome:
        """Technical Design Section 19.3 steps 1-3 only (the three-case
        correction). Steps 4-7 (canary marker, sweep, reconciliation,
        sweep_status -> COMPLETE) are Legal-Hold Correction B2/C+D/E/F scope.

        Raises:
            HoldNotActiveError: The third case -- status=RELEASED with
                sweep_status=COMPLETE, or no record exists at all.
        """
        current = self._holds.get_legal_hold(client_id, audit_id)

        if current is not None and current.get("status") == HOLD_STATUS_ACTIVE:
            # Step 2, first case: a genuine new release. Reuses this
            # episode's own hold_id (no new hold_id is generated for a
            # release -- Technical Design Section 19.5.2's identity model).
            hold_id = current["hold_id"]
            hold_version = int(current["hold_version"]) + 1
            self._holds.write_hold_event(
                client_id=client_id,
                audit_id=audit_id,
                hold_id=hold_id,
                hold_version=hold_version,
                action=HOLD_ACTION_RELEASE,
                actor=actor,
                reason=reason,
                timestamp=now,
                s3_versions_retagged_count=0,
                dynamodb_items_updated_count=0,
            )
            self._holds.upsert_hold(
                client_id=client_id,
                audit_id=audit_id,
                status=HOLD_STATUS_RELEASED,
                hold_id=hold_id,
                hold_version=hold_version,
                sweep_status=SWEEP_STATUS_PENDING,
                placed_at=current["placed_at"],
                placed_by=current["placed_by"],
                reason=current["reason"],
                hold_count=current["hold_count"],
                released_at=now,
                released_by=actor,
            )
            return HoldTransitionOutcome(
                client_id=client_id,
                audit_id=audit_id,
                hold_id=hold_id,
                hold_version=hold_version,
                status=HOLD_STATUS_RELEASED,
                sweep_status=SWEEP_STATUS_PENDING,
                is_noop=False,
                should_run_sweep=True,
            )

        if (
            current is not None
            and current.get("status") == HOLD_STATUS_RELEASED
            and current.get("sweep_status") != SWEEP_STATUS_COMPLETE
        ):
            # Step 2, second case (the new required correction): resumption
            # of *this same episode's own* interrupted release-sweep,
            # symmetric with place()'s resume branch. Does not call
            # upsert_hold or write a new LegalHoldEvent -- proceeds using
            # the existing hold_id/hold_version.
            return HoldTransitionOutcome(
                client_id=client_id,
                audit_id=audit_id,
                hold_id=current["hold_id"],
                hold_version=current["hold_version"],
                status=HOLD_STATUS_RELEASED,
                sweep_status=current.get("sweep_status", SWEEP_STATUS_PENDING),
                is_noop=False,
                should_run_sweep=True,
            )

        # Step 2, third case: status=RELEASED with sweep_status=COMPLETE, or
        # no record ever existed -- unchanged from the existing design's
        # idempotency contract (Section 8). Never reaches any marker/sweep
        # step, so it is inherently immune to the marker-disposal defect
        # place()'s COMPLETE branch required a fix for.
        raise HoldNotActiveError()


__all__ = [
    "HoldNotActiveError",
    "HoldTransitionOutcome",
    "HoldTransitions",
    "is_hold_fully_enforced",
]
