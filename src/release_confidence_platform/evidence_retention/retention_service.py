"""RetentionService -- the minimal internal orchestrator wiring A1.LH1's
DynamoDB-authoritative hold-state transitions (HoldTransitions) together
with A1.LH2's S3-side canary-marker mechanism (MarkerStore) and the
already-built existing-object sweep (CustodySweepClient), end to end
(Legal-Hold Correction B2; Technical Design Section 19.2 "Hold-Placement
Sequence" steps 5-9, Section 19.3 "Hold-Release Sequence" steps 4-7, Section
19.5.3 "Creation and Finalization Ordering", Section 19.6 "Sweep and
Failure-Recovery Semantics").

This is a REAL internal orchestration implementation, not a test double --
Product Strategy explicitly required this (see this subphase's task
briefing): the test double pattern is for TESTING RetentionService (fake
HoldRepository/MarkerStore/CustodySweepClient collaborators, exactly as
test_hold_transitions.py already does for HoldTransitions), not for
replacing RetentionService's own orchestration logic.

Two public methods only, mirroring Technical Design Section 8/10.4's
existing `rcp retention hold place|release` command shape (no CLI wiring
here -- that remains a later, explicitly out-of-scope subphase):

  place_legal_hold(client_id, audit_id, actor, reason, now)
  release_legal_hold(client_id, audit_id, actor, reason, now)

Orchestration, per transition:
  1. HoldTransitions.place()/release() -- decides new episode vs. resume vs.
     no-op vs. rejection (A1.LH1, unchanged, called here not reimplemented).
  2. If outcome.is_noop: return immediately (ADR Invariant 23) -- no marker
     touch, no CustodySweepClient call, no LegalHoldEvent/LegalHold write of
     any kind beyond what HoldTransitions itself already did (nothing, for
     a no-op). This is the direct regression test for the
     sweep_status=COMPLETE terminal no-op case surviving the FULL
     orchestration, not just HoldTransitions alone.
  3. Marker establishment (Technical Design Section 19.5.3 step 2, ADR
     Invariant 24): read the CURRENT transition's own LegalHoldEvent.
     marker_status first. If already CONFIRMED, reuse the durably-recorded
     marker_confirmed_last_modified directly -- never re-attempt an S3
     write for a transition already confirmed, regardless of whether the
     marker object still exists in S3. Otherwise (PENDING or FAILED), call
     MarkerStore.establish_marker(); on failure, persist
     marker_status=FAILED (HoldRepository.update_hold_event_marker_fields),
     set sweep_status=FAILED, and propagate the error -- never proceed to
     the sweep on an unconfirmed marker (Technical Design Section 19.5.6).
     On success, persist marker_status=CONFIRMED with the verified
     marker_confirmed_last_modified, denormalized onto LegalHold too
     (Technical Design Section 19.5.1).
  4. sweep_status -> IN_PROGRESS, only once the marker is confirmed.
  5. Run the existing, unchanged CustodySweepClient sweep methods
     (remove_ttl_disposal_at/retag_s3_versions(legal_hold=True) for PLACE;
     restore_ttl_disposal_at/retag_s3_versions(legal_hold=False) for
     RELEASE).
  6. Run the marker-anchored reconciliation pass
     (CustodySweepClient.reconcile_versions), scoped to the confirmed
     marker's own LastModified.
  7. On success of steps 4-6: sweep_status -> COMPLETE.
  8. On failure of steps 5-6 (post marker confirmation): sweep_status
     remains IN_PROGRESS (Technical Design Section 19.6 -- every
     CustodySweepClient operation and the reconciliation pass are already
     naturally idempotent, so a safe re-invocation resumes cleanly, reusing
     the already-CONFIRMED marker rather than re-establishing it). This
     module does not attempt to positively distinguish a transient AWS
     failure from a genuinely non-retriable one (that classification
     machinery is out of this subphase's authorized scope) -- leaving
     sweep_status=IN_PROGRESS is always the safe, always-resumable branch
     Section 19.6 itself permits ("or transitions to FAILED for a detected
     non-retriable error" is the narrower, positive-detection branch this
     module does not implement).

Never represents status=ACTIVE alone as complete protection anywhere in
this service -- HoldTransitions.is_hold_fully_enforced() (imported, reused,
not reimplemented) is the single source of truth for that conjunction if a
caller needs it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from release_confidence_platform.evidence_retention.constants import (
    HOLD_ACTION_PLACE,
    HOLD_ACTION_RELEASE,
    MARKER_STATUS_CONFIRMED,
    MARKER_STATUS_FAILED,
    SWEEP_STATUS_COMPLETE,
    SWEEP_STATUS_FAILED,
    SWEEP_STATUS_IN_PROGRESS,
)
from release_confidence_platform.evidence_retention.custody_sweep_client import (
    CustodySweepClient,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.evidence_retention.hold_transitions import (
    HoldTransitionOutcome,
    HoldTransitions,
)
from release_confidence_platform.evidence_retention.marker_store import (
    MarkerEstablishmentFailedError,
    MarkerEstablishmentResult,
    MarkerIntegrityError,
    MarkerStore,
    build_marker_key,
)


def _epoch_seconds(now: str) -> int:
    """Parse this codebase's standard "Z"-suffixed UTC ISO-8601 timestamp
    string (core.time.utc_now_iso()'s own format) into epoch seconds, for
    CustodySweepClient.restore_ttl_disposal_at()'s now_epoch_seconds
    parameter -- mirrors the identical fromisoformat(...replace("Z",
    "+00:00")) pattern already used throughout this codebase (e.g.
    evidence_retention/models.py::_parse_iso8601,
    aggregation/engine.py)."""
    return int(datetime.fromisoformat(now.replace("Z", "+00:00")).timestamp())


class RetentionService:
    """Orchestrates HoldTransitions (A1.LH1) + MarkerStore + CustodySweepClient
    end to end for a single hold-placement/hold-release invocation (Legal-Hold
    Correction B2; Technical Design Section 19.2/19.3/19.5.3/19.6)."""

    def __init__(
        self,
        hold_transitions: HoldTransitions,
        hold_repository: HoldRepository,
        marker_store: MarkerStore,
        custody_sweep_client: CustodySweepClient,
    ) -> None:
        self._transitions = hold_transitions
        self._holds = hold_repository
        self._marker_store = marker_store
        self._sweep = custody_sweep_client

    # ------------------------------------------------------------------
    # Public orchestration entry points
    # ------------------------------------------------------------------

    def place_legal_hold(
        self, client_id: str, audit_id: str, actor: str, reason: str, now: str
    ) -> HoldTransitionOutcome:
        """Technical Design Section 19.2 steps 1-9, end to end.

        Raises:
            MarkerEstablishmentFailedError: Marker establishment exhausted
                its retry/wall-clock budget (Section 19.5.6).
            MarkerIntegrityError: A genuine marker identity collision was
                found (Section 19.5.7).
            HoldStateConcurrencyExceededError / StorageError: Propagated
                unchanged from HoldTransitions/HoldRepository/
                CustodySweepClient on their own respective failure modes.
        """
        outcome = self._transitions.place(client_id, audit_id, actor, reason, now)
        if outcome.is_noop:
            # ADR Invariant 23: a stale re-invocation with sweep_status
            # already COMPLETE is a pure no-op all the way through this
            # orchestration -- return immediately without touching the
            # marker, CustodySweepClient, or LegalHoldEvent/LegalHold in any
            # way beyond what HoldTransitions itself already did (nothing).
            return outcome
        self._run_sweep_sequence(
            outcome, transition=HOLD_ACTION_PLACE, legal_hold=True, now=now
        )
        return outcome

    def release_legal_hold(
        self, client_id: str, audit_id: str, actor: str, reason: str, now: str
    ) -> HoldTransitionOutcome:
        """Technical Design Section 19.3 steps 1-7, end to end.

        Raises:
            HoldNotActiveError: Nothing eligible to release (Section 19.3
                step 2's third case) -- propagated unchanged from
                HoldTransitions.release().
            MarkerEstablishmentFailedError / MarkerIntegrityError /
            HoldStateConcurrencyExceededError / StorageError: As above.
        """
        outcome = self._transitions.release(client_id, audit_id, actor, reason, now)
        if outcome.is_noop:
            # HoldTransitions.release() does not currently produce an
            # is_noop=True outcome (its only no-further-action path raises
            # HoldNotActiveError instead) -- this check is a defensive,
            # symmetric guard against place_legal_hold()'s identical gate,
            # so RetentionService never depends on which of the two
            # branches HoldTransitions happens to implement a given no-op
            # case through.
            return outcome
        self._run_sweep_sequence(
            outcome, transition=HOLD_ACTION_RELEASE, legal_hold=False, now=now
        )
        return outcome

    # ------------------------------------------------------------------
    # Shared sequence (Technical Design Section 19.2 steps 5-9 / Section
    # 19.3 steps 4-7 -- structurally identical for both directions, only
    # the CustodySweepClient method pair and the reconciliation tag
    # direction differ, both captured by the `legal_hold` flag).
    # ------------------------------------------------------------------

    def _run_sweep_sequence(
        self, outcome: HoldTransitionOutcome, *, transition: str, legal_hold: bool, now: str
    ) -> None:
        client_id = outcome.client_id
        audit_id = outcome.audit_id
        hold_id = outcome.hold_id
        hold_version = outcome.hold_version

        try:
            marker_result = self._ensure_marker_confirmed(
                client_id, audit_id, hold_id, hold_version, transition
            )
        except (MarkerEstablishmentFailedError, MarkerIntegrityError):
            self._mark_event_marker_failed(client_id, audit_id, hold_id, hold_version, transition)
            self._set_sweep_status(client_id, audit_id, SWEEP_STATUS_FAILED)
            raise

        self._set_sweep_status(client_id, audit_id, SWEEP_STATUS_IN_PROGRESS)

        try:
            if legal_hold:
                self._sweep.remove_ttl_disposal_at(client_id, audit_id)
                self._sweep.retag_s3_versions(client_id, audit_id, legal_hold=True)
            else:
                self._sweep.restore_ttl_disposal_at(
                    client_id, audit_id, _epoch_seconds(now)
                )
                self._sweep.retag_s3_versions(client_id, audit_id, legal_hold=False)

            self._sweep.reconcile_versions(
                client_id,
                audit_id,
                marker_confirmed_last_modified=marker_result.marker_confirmed_last_modified,
                legal_hold=legal_hold,
            )
        except Exception:
            # Technical Design Section 19.6: sweep_status remains
            # IN_PROGRESS on a sweep/reconciliation-phase failure that
            # occurs AFTER the marker is already confirmed -- every
            # CustodySweepClient operation and reconcile_versions() are
            # already naturally idempotent, so a safe re-invocation of
            # place()/release() resumes cleanly (marker_status already
            # CONFIRMED is reused, not re-established). This module does
            # not positively distinguish transient-vs-non-retriable AWS
            # failures (out of this subphase's authorized scope); leaving
            # sweep_status=IN_PROGRESS is always the safe branch this
            # section permits.
            raise

        self._set_sweep_status(client_id, audit_id, SWEEP_STATUS_COMPLETE)

    # ------------------------------------------------------------------
    # Marker establishment/confirmation (Technical Design Section 19.5.3
    # step 2, ADR Invariant 24)
    # ------------------------------------------------------------------

    def _ensure_marker_confirmed(
        self,
        client_id: str,
        audit_id: str,
        hold_id: str,
        hold_version: int,
        transition: str,
    ) -> MarkerEstablishmentResult:
        event = self._holds.get_legal_hold_event(client_id, audit_id, hold_id, hold_version)
        if event is not None and event.get("marker_status") == MARKER_STATUS_CONFIRMED:
            # ADR Invariant 24: once CONFIRMED, this value is authoritative
            # and immutable for the life of this transition -- reuse it
            # directly, never attempt a new S3 write, regardless of whether
            # the marker object still physically exists in S3 (it may have
            # been disposed per its purpose-limited retention, Technical
            # Design Section 19.5.8, or this may simply be a resumed
            # invocation of a transition whose marker step already finished
            # before an earlier attempt was interrupted mid-sweep).
            return MarkerEstablishmentResult(
                marker_s3_key=event["marker_s3_key"],
                marker_status=MARKER_STATUS_CONFIRMED,
                marker_confirmed_last_modified=event["marker_confirmed_last_modified"],
            )

        # marker_status is PENDING (first attempt, or resumed before
        # confirmation) or FAILED (a prior attempt exhausted its own
        # retry/wall-clock budget) -- attempt establishment. MarkerStore
        # itself handles the atomic-conditional-write/orphan-recovery
        # mechanics (Technical Design Section 19.5.7); on precondition
        # conflict it validates the existing marker's identity rather than
        # blindly reusing or rejecting it.
        result = self._marker_store.establish_marker(
            client_id, audit_id, hold_id, hold_version, transition
        )
        self._holds.update_hold_event_marker_fields(
            client_id,
            audit_id,
            hold_id,
            hold_version,
            marker_s3_key=result.marker_s3_key,
            marker_status=MARKER_STATUS_CONFIRMED,
            marker_confirmed_last_modified=result.marker_confirmed_last_modified,
        )
        self._denormalize_marker_onto_legal_hold(client_id, audit_id, result)
        return result

    def _mark_event_marker_failed(
        self,
        client_id: str,
        audit_id: str,
        hold_id: str,
        hold_version: int,
        transition: str,
    ) -> None:
        # The key is deterministically computable regardless of whether
        # establishment actually succeeded -- recorded here for operator
        # traceability even on failure. marker_confirmed_last_modified stays
        # None: nothing was ever confirmed for this attempt.
        key = build_marker_key(client_id, audit_id, hold_id, hold_version, transition)
        self._holds.update_hold_event_marker_fields(
            client_id,
            audit_id,
            hold_id,
            hold_version,
            marker_s3_key=key,
            marker_status=MARKER_STATUS_FAILED,
            marker_confirmed_last_modified=None,
        )

    def _denormalize_marker_onto_legal_hold(
        self, client_id: str, audit_id: str, result: MarkerEstablishmentResult
    ) -> None:
        current = self._holds.get_legal_hold(client_id, audit_id)
        if current is None:
            return  # Defensive only -- unreachable in practice: a marker is
            # only ever established mid-transition, after upsert_hold has
            # already durably committed the current-state record.
        self._upsert_current_state(
            current, marker_s3_key=result.marker_s3_key,
            marker_confirmed_last_modified=result.marker_confirmed_last_modified,
        )

    # ------------------------------------------------------------------
    # sweep_status bookkeeping. HoldRepository.upsert_hold() is a plain,
    # full-overwrite PutItem (unchanged from A1.LH1) -- re-examined per
    # this subphase's own task briefing and confirmed sufficient for
    # updating sweep_status/marker fields on LegalHold: no new
    # LegalHold-specific update method is required (unlike LegalHoldEvent,
    # which IS write-once and does need update_hold_event_marker_fields,
    # added to hold_repository.py by this subphase).
    # ------------------------------------------------------------------

    def _set_sweep_status(self, client_id: str, audit_id: str, sweep_status: str) -> None:
        current = self._holds.get_legal_hold(client_id, audit_id)
        if current is None:
            return  # Defensive only -- unreachable: upsert_hold already
            # committed before any sweep_status transition is attempted.
        self._upsert_current_state(current, sweep_status=sweep_status)

    def _upsert_current_state(
        self,
        current: dict[str, Any],
        *,
        sweep_status: str | None = None,
        marker_s3_key: str | None = None,
        marker_confirmed_last_modified: str | None = None,
    ) -> None:
        """Re-persist LegalHold's current-state record via upsert_hold()'s
        existing full-overwrite semantics, changing only the field(s) this
        call specifies and preserving every other field exactly as read.
        """
        self._holds.upsert_hold(
            client_id=current["client_id"],
            audit_id=current["audit_id"],
            status=current["status"],
            hold_id=current["hold_id"],
            hold_version=current["hold_version"],
            sweep_status=sweep_status if sweep_status is not None else current["sweep_status"],
            placed_at=current["placed_at"],
            placed_by=current["placed_by"],
            reason=current["reason"],
            hold_count=current["hold_count"],
            released_at=current.get("released_at"),
            released_by=current.get("released_by"),
            marker_s3_key=(
                marker_s3_key if marker_s3_key is not None else current.get("marker_s3_key")
            ),
            marker_confirmed_last_modified=(
                marker_confirmed_last_modified
                if marker_confirmed_last_modified is not None
                else current.get("marker_confirmed_last_modified")
            ),
        )


__all__ = ["RetentionService"]
