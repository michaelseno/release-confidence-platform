"""Tests for RetentionService, the minimal internal orchestrator wiring
HoldTransitions (A1.LH1) + MarkerStore + CustodySweepClient end to end
(Legal-Hold Correction B2; Technical Design Section 19.2 steps 5-9, Section
19.3 steps 4-7, Section 19.5.3, Section 19.6).

Uses fake, in-memory collaborator doubles for HoldRepository/MarkerStore/
CustodySweepClient (mirroring test_hold_transitions.py's own
_FakeHoldRepository pattern) so RetentionService's OWN orchestration logic
-- not its collaborators' internals, already covered by
test_hold_repository.py/test_marker_store.py/test_custody_sweep_client.py --
is what's under test here. A real HoldTransitions is used throughout (it is
itself already fully covered by test_hold_transitions.py; reusing it here,
wired to the fake HoldRepository, exercises the full, real orchestration
path end to end, per this subphase's requirement for a real internal
orchestration implementation, not a test double standing in for it).
"""

from __future__ import annotations

from typing import Any

import pytest

from release_confidence_platform.evidence_retention.hold_transitions import (
    HoldNotActiveError,
    HoldTransitions,
)
from release_confidence_platform.evidence_retention.marker_store import (
    MarkerEstablishmentFailedError,
    MarkerEstablishmentResult,
    MarkerIntegrityError,
    build_marker_key,
)
from release_confidence_platform.evidence_retention.retention_service import RetentionService

_CLIENT_ID = "client1"
_AUDIT_ID = "audit1"
_ACTOR = "operator_a"
_REASON = "litigation hold"


class _FakeHoldRepository:
    """In-memory stand-in mirroring test_hold_transitions.py's
    _FakeHoldRepository, extended with the LegalHoldEvent store and the new
    update_hold_event_marker_fields method this subphase adds."""

    def __init__(self) -> None:
        self.hold_state: dict[str, Any] | None = None
        self.events: dict[tuple[str, int], dict[str, Any]] = {}
        self.upsert_calls: list[dict[str, Any]] = []
        self.marker_update_calls: list[dict[str, Any]] = []

    def get_legal_hold(self, client_id: str, audit_id: str) -> dict[str, Any] | None:
        return dict(self.hold_state) if self.hold_state is not None else None

    def get_legal_hold_event(
        self, client_id: str, audit_id: str, hold_id: str, hold_version: int
    ) -> dict[str, Any] | None:
        event = self.events.get((hold_id, hold_version))
        return dict(event) if event is not None else None

    def write_hold_event(self, **kwargs: Any) -> None:
        key = (kwargs["hold_id"], kwargs["hold_version"])
        self.events[key] = dict(kwargs)

    def upsert_hold(self, **kwargs: Any) -> None:
        self.upsert_calls.append(kwargs)
        self.hold_state = dict(kwargs)

    def update_hold_event_marker_fields(
        self,
        client_id: str,
        audit_id: str,
        hold_id: str,
        hold_version: int,
        marker_s3_key: str | None,
        marker_status: str,
        marker_confirmed_last_modified: str | None,
    ) -> None:
        self.marker_update_calls.append(
            {
                "hold_id": hold_id,
                "hold_version": hold_version,
                "marker_s3_key": marker_s3_key,
                "marker_status": marker_status,
                "marker_confirmed_last_modified": marker_confirmed_last_modified,
            }
        )
        key = (hold_id, hold_version)
        event = self.events.setdefault(key, {"hold_id": hold_id, "hold_version": hold_version})
        event["marker_s3_key"] = marker_s3_key
        event["marker_status"] = marker_status
        event["marker_confirmed_last_modified"] = marker_confirmed_last_modified


class _FakeMarkerStore:
    """Records establish_marker() calls; behavior is configured per-test via
    `outcomes` (a list of callables/exceptions/results consumed in order) or
    a single fixed `result`/`error`."""

    def __init__(
        self,
        *,
        result: MarkerEstablishmentResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, str, int, str]] = []
        self._result = result
        self._error = error

    def establish_marker(self, client_id, audit_id, hold_id, hold_version, transition):
        self.calls.append((client_id, audit_id, hold_id, hold_version, transition))
        if self._error is not None:
            raise self._error
        if self._result is not None:
            return self._result
        key = build_marker_key(client_id, audit_id, hold_id, hold_version, transition)
        return MarkerEstablishmentResult(
            marker_s3_key=key,
            marker_status="CONFIRMED",
            marker_confirmed_last_modified="2026-07-18T00:00:10Z",
        )


class _FakeCustodySweepClient:
    def __init__(self, *, raise_on: str | None = None) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []
        self._raise_on = raise_on

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if self._raise_on == name:
            raise RuntimeError(f"simulated {name} failure")

    def remove_ttl_disposal_at(self, client_id, audit_id):
        self._record("remove_ttl_disposal_at", client_id, audit_id)
        return 0

    def retag_s3_versions(self, client_id, audit_id, legal_hold):
        self._record("retag_s3_versions", client_id, audit_id, legal_hold=legal_hold)
        return 0

    def restore_ttl_disposal_at(self, client_id, audit_id, now_epoch_seconds):
        self._record("restore_ttl_disposal_at", client_id, audit_id, now_epoch_seconds)
        return 0

    def reconcile_versions(
        self, client_id, audit_id, *, marker_confirmed_last_modified, legal_hold
    ):
        self._record(
            "reconcile_versions",
            client_id,
            audit_id,
            marker_confirmed_last_modified=marker_confirmed_last_modified,
            legal_hold=legal_hold,
        )
        return 0


def _make_service(
    *, marker_store=None, sweep=None
) -> tuple[RetentionService, _FakeHoldRepository, _FakeMarkerStore, _FakeCustodySweepClient]:
    fake_repo = _FakeHoldRepository()
    transitions = HoldTransitions(fake_repo)  # type: ignore[arg-type]
    fake_marker_store = marker_store if marker_store is not None else _FakeMarkerStore()
    fake_sweep = sweep if sweep is not None else _FakeCustodySweepClient()
    service = RetentionService(transitions, fake_repo, fake_marker_store, fake_sweep)  # type: ignore[arg-type]
    return service, fake_repo, fake_marker_store, fake_sweep


_NOW = "2026-07-18T00:00:00.000Z"


# ---------------------------------------------------------------------------
# Terminal no-op behavior at the FULL orchestration layer (required: new
# coverage beyond HoldTransitions' own, per the task's explicit regression
# requirement)
# ---------------------------------------------------------------------------


def test_place_legal_hold_stale_reinvocation_after_complete_is_pure_noop_e2e():
    service, fake_repo, fake_marker_store, fake_sweep = _make_service()
    service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)
    fake_repo.hold_state["sweep_status"] = "COMPLETE"
    marker_calls_before = len(fake_marker_store.calls)
    sweep_calls_before = len(fake_sweep.calls)

    outcome = service.place_legal_hold(
        _CLIENT_ID, _AUDIT_ID, _ACTOR, "stale", "2026-07-19T00:00:00Z"
    )

    assert outcome.is_noop is True
    # The direct proof required by this subphase: the marker store and
    # CustodySweepClient are never reached AGAIN for a stale re-invocation --
    # no new calls beyond the original (genuine) place()'s own.
    assert len(fake_marker_store.calls) == marker_calls_before
    assert len(fake_sweep.calls) == sweep_calls_before


def test_release_legal_hold_reinvocation_after_complete_raises_and_never_touches_marker_or_sweep():
    service, fake_repo, fake_marker_store, fake_sweep = _make_service()
    service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)
    fake_repo.hold_state["sweep_status"] = "COMPLETE"
    service.release_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, "release", "2026-07-19T00:00:00Z")
    fake_repo.hold_state["sweep_status"] = "COMPLETE"
    marker_calls_before = len(fake_marker_store.calls)
    sweep_calls_before = len(fake_sweep.calls)

    with pytest.raises(HoldNotActiveError):
        service.release_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, "stale", "2026-07-20T00:00:00Z")

    # No new marker/sweep calls beyond the original PLACE+RELEASE's own.
    assert len(fake_marker_store.calls) == marker_calls_before
    assert len(fake_sweep.calls) == sweep_calls_before


# ---------------------------------------------------------------------------
# End-to-end PLACE / RELEASE happy path
# ---------------------------------------------------------------------------


def test_place_legal_hold_establishes_marker_runs_sweep_and_reconciliation_then_completes():
    service, fake_repo, fake_marker_store, fake_sweep = _make_service()

    outcome = service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)

    assert outcome.is_noop is False
    assert fake_marker_store.calls == [
        (_CLIENT_ID, _AUDIT_ID, outcome.hold_id, outcome.hold_version, "PLACE")
    ]
    sweep_call_names = [name for name, _, _ in fake_sweep.calls]
    assert sweep_call_names == [
        "remove_ttl_disposal_at",
        "retag_s3_versions",
        "reconcile_versions",
    ]
    assert fake_repo.hold_state["sweep_status"] == "COMPLETE"
    # Marker confirmation persisted on LegalHoldEvent.
    event = fake_repo.get_legal_hold_event(
        _CLIENT_ID, _AUDIT_ID, outcome.hold_id, outcome.hold_version
    )
    assert event["marker_status"] == "CONFIRMED"
    assert event["marker_confirmed_last_modified"] == "2026-07-18T00:00:10Z"
    # Marker denormalized onto LegalHold.
    assert fake_repo.hold_state["marker_confirmed_last_modified"] == "2026-07-18T00:00:10Z"


def test_release_legal_hold_uses_inverse_sweep_methods_and_legal_hold_false():
    service, fake_repo, fake_marker_store, fake_sweep = _make_service()
    service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)
    fake_repo.hold_state["sweep_status"] = "COMPLETE"

    outcome = service.release_legal_hold(
        _CLIENT_ID, _AUDIT_ID, _ACTOR, "released", "2026-07-19T00:00:00.000Z"
    )

    assert outcome.status == "RELEASED"
    call_names_after_place = [name for name, _, _ in fake_sweep.calls][3:]
    assert call_names_after_place == [
        "restore_ttl_disposal_at",
        "retag_s3_versions",
        "reconcile_versions",
    ]
    # retag_s3_versions called with legal_hold=False on release.
    retag_call = [c for c in fake_sweep.calls if c[0] == "retag_s3_versions"][-1]
    assert retag_call[2]["legal_hold"] is False
    reconcile_call = [c for c in fake_sweep.calls if c[0] == "reconcile_versions"][-1]
    assert reconcile_call[2]["legal_hold"] is False
    assert fake_repo.hold_state["sweep_status"] == "COMPLETE"


# ---------------------------------------------------------------------------
# PLACE and RELEASE marker non-collision / PLACE -> RELEASE -> PLACE
# episodes, at the full-orchestration level
# ---------------------------------------------------------------------------


def test_full_episode_place_release_place_three_distinct_markers_no_aliasing():
    service, fake_repo, fake_marker_store, fake_sweep = _make_service()

    first_place = service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)
    fake_repo.hold_state["sweep_status"] = "COMPLETE"

    release = service.release_legal_hold(
        _CLIENT_ID, _AUDIT_ID, _ACTOR, "released", "2026-07-19T00:00:00.000Z"
    )
    fake_repo.hold_state["sweep_status"] = "COMPLETE"

    second_place = service.place_legal_hold(
        _CLIENT_ID, _AUDIT_ID, _ACTOR, "re-held", "2026-07-20T00:00:00.000Z"
    )

    assert first_place.hold_id == release.hold_id  # same episode
    assert second_place.hold_id != first_place.hold_id  # new episode
    marker_transitions_called = [
        (hold_id, hold_version, transition)
        for (_, _, hold_id, hold_version, transition) in fake_marker_store.calls
    ]
    assert len(marker_transitions_called) == 3
    assert len(set(marker_transitions_called)) == 3  # no aliasing


# ---------------------------------------------------------------------------
# Marker establishment failure -> marker_status=FAILED, sweep_status=FAILED,
# error propagates, sweep never runs
# ---------------------------------------------------------------------------


def test_place_legal_hold_marker_establishment_failure_sets_failed_states_and_propagates():
    failing_marker_store = _FakeMarkerStore(error=MarkerEstablishmentFailedError())
    service, fake_repo, fake_marker_store, fake_sweep = _make_service(
        marker_store=failing_marker_store
    )

    with pytest.raises(MarkerEstablishmentFailedError):
        service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)

    assert fake_repo.hold_state["sweep_status"] == "FAILED"
    assert fake_sweep.calls == []  # sweep never reached on an unconfirmed marker
    hold_id = fake_repo.hold_state["hold_id"]
    hold_version = fake_repo.hold_state["hold_version"]
    event = fake_repo.get_legal_hold_event(_CLIENT_ID, _AUDIT_ID, hold_id, hold_version)
    assert event["marker_status"] == "FAILED"
    assert event["marker_confirmed_last_modified"] is None


def test_place_legal_hold_marker_integrity_error_sets_failed_states_and_propagates():
    failing_marker_store = _FakeMarkerStore(error=MarkerIntegrityError())
    service, fake_repo, _, fake_sweep = _make_service(marker_store=failing_marker_store)

    with pytest.raises(MarkerIntegrityError):
        service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)

    assert fake_repo.hold_state["sweep_status"] == "FAILED"
    assert fake_sweep.calls == []


def test_release_legal_hold_marker_establishment_failure_sets_failed_states():
    service, fake_repo, fake_marker_store, fake_sweep = _make_service()
    service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)
    fake_repo.hold_state["sweep_status"] = "COMPLETE"

    failing_marker_store = _FakeMarkerStore(error=MarkerEstablishmentFailedError())
    # Swap in a failing marker store for the release attempt specifically.
    service._marker_store = failing_marker_store  # type: ignore[attr-defined]

    with pytest.raises(MarkerEstablishmentFailedError):
        service.release_legal_hold(
            _CLIENT_ID, _AUDIT_ID, _ACTOR, "released", "2026-07-19T00:00:00.000Z"
        )

    assert fake_repo.hold_state["sweep_status"] == "FAILED"
    assert fake_repo.hold_state["status"] == "RELEASED"


# ---------------------------------------------------------------------------
# Marker status confirmation and failure paths persisted correctly via
# HoldRepository (required, separate from the propagation tests above)
# ---------------------------------------------------------------------------


def test_marker_confirmed_persists_key_status_and_last_modified_on_event_and_hold():
    service, fake_repo, fake_marker_store, fake_sweep = _make_service()
    outcome = service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)

    event = fake_repo.get_legal_hold_event(
        _CLIENT_ID, _AUDIT_ID, outcome.hold_id, outcome.hold_version
    )
    expected_key = build_marker_key(
        _CLIENT_ID, _AUDIT_ID, outcome.hold_id, outcome.hold_version, "PLACE"
    )
    assert event["marker_s3_key"] == expected_key
    assert event["marker_status"] == "CONFIRMED"
    assert fake_repo.hold_state["marker_s3_key"] == expected_key


# ---------------------------------------------------------------------------
# Resume support: an already-CONFIRMED marker is reused, never re-established
# (ADR Invariant 24) -- this is the "Stale re-invocation after marker
# disposal" regression at the orchestration layer, and the ordinary resume
# case (sweep_status != COMPLETE, marker already CONFIRMED).
# ---------------------------------------------------------------------------


def test_resumed_place_with_confirmed_marker_never_calls_marker_store_again():
    service, fake_repo, fake_marker_store, fake_sweep = _make_service()
    outcome = service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)
    # Simulate interruption: marker confirmed, but sweep_status never reached
    # COMPLETE (e.g. crash mid-sweep).
    fake_repo.hold_state["sweep_status"] = "IN_PROGRESS"
    calls_before = len(fake_marker_store.calls)

    resumed_outcome = service.place_legal_hold(
        _CLIENT_ID, _AUDIT_ID, _ACTOR, "resume", "2026-07-19T00:00:00.000Z"
    )

    assert resumed_outcome.hold_id == outcome.hold_id
    assert resumed_outcome.hold_version == outcome.hold_version
    # No new marker establishment attempt -- the already-CONFIRMED marker
    # (per ADR Invariant 24) is reused directly, never re-derived.
    assert len(fake_marker_store.calls) == calls_before
    assert fake_repo.hold_state["sweep_status"] == "COMPLETE"


def test_resumed_place_after_marker_failed_reestablishes_marker():
    """A prior attempt's marker_status=FAILED must be retried (not treated
    as terminal) -- distinguishing FAILED (retriable) from CONFIRMED
    (immutable, never retried)."""
    failing_then_ok = _FailThenSucceedMarkerStore()
    service, fake_repo, fake_marker_store, fake_sweep = _make_service(
        marker_store=failing_then_ok
    )

    with pytest.raises(MarkerEstablishmentFailedError):
        service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)
    assert fake_repo.hold_state["sweep_status"] == "FAILED"

    # Re-invoke: HoldTransitions resumes (sweep_status=FAILED != COMPLETE),
    # marker_status=FAILED on the event triggers a fresh establishment
    # attempt, which now succeeds.
    outcome = service.place_legal_hold(
        _CLIENT_ID, _AUDIT_ID, _ACTOR, "retry", "2026-07-19T00:00:00.000Z"
    )
    assert outcome.is_noop is False
    assert fake_repo.hold_state["sweep_status"] == "COMPLETE"
    assert failing_then_ok.attempts == 2


class _FailThenSucceedMarkerStore:
    def __init__(self) -> None:
        self.attempts = 0

    def establish_marker(self, client_id, audit_id, hold_id, hold_version, transition):
        self.attempts += 1
        if self.attempts == 1:
            raise MarkerEstablishmentFailedError()
        key = build_marker_key(client_id, audit_id, hold_id, hold_version, transition)
        return MarkerEstablishmentResult(
            marker_s3_key=key,
            marker_status="CONFIRMED",
            marker_confirmed_last_modified="2026-07-19T00:00:00Z",
        )


# ---------------------------------------------------------------------------
# Sweep interruption and retry (partial failure mid-sequence, then safe
# resumption) -- sweep_status remains IN_PROGRESS, not FAILED, on a
# post-marker-confirmation sweep/reconciliation failure.
# ---------------------------------------------------------------------------


def test_sweep_failure_after_marker_confirmed_leaves_sweep_status_in_progress():
    failing_sweep = _FakeCustodySweepClient(raise_on="retag_s3_versions")
    service, fake_repo, fake_marker_store, fake_sweep = _make_service(sweep=failing_sweep)

    with pytest.raises(RuntimeError):
        service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)

    assert fake_repo.hold_state["sweep_status"] == "IN_PROGRESS"
    # Marker was confirmed before the sweep failure.
    hold_id = fake_repo.hold_state["hold_id"]
    hold_version = fake_repo.hold_state["hold_version"]
    event = fake_repo.get_legal_hold_event(_CLIENT_ID, _AUDIT_ID, hold_id, hold_version)
    assert event["marker_status"] == "CONFIRMED"


def test_resume_after_sweep_interruption_reuses_marker_and_reaches_complete():
    failing_sweep = _FakeCustodySweepClient(raise_on="retag_s3_versions")
    service, fake_repo, fake_marker_store, fake_sweep = _make_service(sweep=failing_sweep)

    with pytest.raises(RuntimeError):
        service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)
    assert fake_repo.hold_state["sweep_status"] == "IN_PROGRESS"
    marker_calls_before = len(fake_marker_store.calls)

    # Swap in a healthy sweep client for the resumed attempt.
    healthy_sweep = _FakeCustodySweepClient()
    service._sweep = healthy_sweep  # type: ignore[attr-defined]

    resumed = service.place_legal_hold(
        _CLIENT_ID, _AUDIT_ID, _ACTOR, "resume", "2026-07-19T00:00:00.000Z"
    )

    assert resumed.is_noop is False
    assert fake_repo.hold_state["sweep_status"] == "COMPLETE"
    # Marker was already CONFIRMED -- not re-established on resume.
    assert len(fake_marker_store.calls) == marker_calls_before


# ---------------------------------------------------------------------------
# Never represents status=ACTIVE alone as complete protection
# ---------------------------------------------------------------------------


def test_outcome_never_conflates_active_status_with_full_enforcement():
    from release_confidence_platform.evidence_retention.hold_transitions import (
        is_hold_fully_enforced,
    )

    failing_sweep = _FakeCustodySweepClient(raise_on="retag_s3_versions")
    service, fake_repo, _, _ = _make_service(sweep=failing_sweep)

    with pytest.raises(RuntimeError):
        service.place_legal_hold(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, _NOW)

    assert fake_repo.hold_state["status"] == "ACTIVE"
    assert fake_repo.hold_state["sweep_status"] == "IN_PROGRESS"
    assert is_hold_fully_enforced(fake_repo.hold_state) is False
