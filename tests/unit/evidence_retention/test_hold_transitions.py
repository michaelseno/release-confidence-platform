"""Tests for the authoritative PLACE/RELEASE hold-state transition sequences
(Legal-Hold Correction B1; Technical Design Section 19.2/19.3).

Uses a fake, in-memory HoldRepository double to isolate the transition
*decision logic* (new episode vs. resume vs. no-op vs. rejection; hold_id/
hold_version bookkeeping) from HoldRepository's own DynamoDB wire format,
which test_hold_repository.py already covers directly. A final integration
section proves HoldTransitions actually calls the *real* HoldRepository with
the correct keyword-argument names.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.evidence_retention.hold_transitions import (
    HoldNotActiveError,
    HoldTransitions,
    is_hold_fully_enforced,
)

_CLIENT_ID = "client1"
_AUDIT_ID = "audit1"
_ACTOR = "operator_a"
_REASON = "litigation hold"


class _FakeHoldRepository:
    """In-memory stand-in for HoldRepository's LegalHold/LegalHoldEvent CRUD.

    Mirrors real persistence semantics closely enough for pure
    decision-logic testing: get_legal_hold reflects only what the most
    recent upsert_hold call wrote, and every write_hold_event call is
    recorded distinctly (a real duplicate-key write would raise
    ConditionalWriteError -- ../test_hold_repository.py proves the SK shape
    that makes that guarantee hold; this fake does not re-simulate that).
    """

    def __init__(self) -> None:
        self.hold_state: dict[str, Any] | None = None
        self.write_event_calls: list[dict[str, Any]] = []
        self.upsert_calls: list[dict[str, Any]] = []

    def get_legal_hold(self, client_id: str, audit_id: str) -> dict[str, Any] | None:
        return dict(self.hold_state) if self.hold_state is not None else None

    def write_hold_event(self, **kwargs: Any) -> None:
        self.write_event_calls.append(kwargs)

    def upsert_hold(self, **kwargs: Any) -> None:
        self.upsert_calls.append(kwargs)
        self.hold_state = dict(kwargs)


def _make_transitions() -> tuple[HoldTransitions, _FakeHoldRepository]:
    fake = _FakeHoldRepository()
    return HoldTransitions(fake), fake  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Required behavior 1/2: hold_version increments by exactly 1 on every
# PLACE/RELEASE; the same hold_id identifies one PLACE/RELEASE episode.
# ---------------------------------------------------------------------------


def test_place_new_episode_starts_hold_version_at_one():
    transitions, _ = _make_transitions()
    outcome = transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, now="t0")
    assert outcome.hold_version == 1
    assert outcome.is_noop is False
    assert outcome.should_run_sweep is True
    assert outcome.status == "ACTIVE"
    assert outcome.sweep_status == "PENDING"


def test_place_then_release_share_hold_id_and_increment_version_by_exactly_one():
    transitions, fake = _make_transitions()
    place_outcome = transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, now="t0")
    # Mark this episode's sweep complete before releasing, so release() takes
    # the "genuine new release" branch, not a resume of an interrupted PLACE.
    fake.hold_state["sweep_status"] = "COMPLETE"
    release_outcome = transitions.release(_CLIENT_ID, _AUDIT_ID, _ACTOR, "release reason", now="t1")

    assert release_outcome.hold_id == place_outcome.hold_id
    assert release_outcome.hold_version == place_outcome.hold_version + 1
    assert release_outcome.status == "RELEASED"


def test_full_cycle_place_release_place_yields_three_strictly_increasing_versions():
    """QA item 18's scenario: three transitions in sequence, hold_version =
    N, N+1, N+2, with no aliasing between any pair."""
    transitions, fake = _make_transitions()

    first_place = transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, now="t0")
    fake.hold_state["sweep_status"] = "COMPLETE"

    release = transitions.release(_CLIENT_ID, _AUDIT_ID, _ACTOR, "released", now="t1")
    fake.hold_state["sweep_status"] = "COMPLETE"

    second_place = transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, "re-held", now="t2")

    versions = [first_place.hold_version, release.hold_version, second_place.hold_version]
    assert versions == [1, 2, 3]
    assert len(set(versions)) == 3


# ---------------------------------------------------------------------------
# Required behavior 3: a later, independent episode receives a new hold_id
# (not over-constraining the exact mechanism, per Technical Design Section
# 19.11 item 18's own note).
# ---------------------------------------------------------------------------


def test_new_episode_after_release_receives_a_different_hold_id():
    transitions, fake = _make_transitions()
    first_place = transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, now="t0")
    fake.hold_state["sweep_status"] = "COMPLETE"
    transitions.release(_CLIENT_ID, _AUDIT_ID, _ACTOR, "released", now="t1")
    fake.hold_state["sweep_status"] = "COMPLETE"

    second_place = transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, "re-held", now="t2")

    assert second_place.hold_id != first_place.hold_id


# ---------------------------------------------------------------------------
# Required behavior 5 (critical regression): a stale PLACE re-invocation
# after sweep_status=COMPLETE is a pure no-op.
# ---------------------------------------------------------------------------


def test_place_reinvocation_after_sweep_complete_is_pure_noop():
    transitions, fake = _make_transitions()
    transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, now="t0")
    fake.hold_state["sweep_status"] = "COMPLETE"

    write_calls_before = len(fake.write_event_calls)
    upsert_calls_before = len(fake.upsert_calls)

    outcome = transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, "stale reinvocation", now="t9")

    assert outcome.is_noop is True
    assert outcome.should_run_sweep is False
    # The direct proof of the defect this correction closes: no new
    # LegalHoldEvent write, no upsert_hold call, at all.
    assert len(fake.write_event_calls) == write_calls_before
    assert len(fake.upsert_calls) == upsert_calls_before
    assert outcome.hold_version == fake.hold_state["hold_version"]


def test_release_reinvocation_after_sweep_complete_raises_hold_not_active_not_a_noop():
    """§19.3 step 2's third case was already safe before this correction --
    this test proves the new resume branch did not inadvertently loosen it
    (Technical Design Section 19.11 item 21(b))."""
    transitions, fake = _make_transitions()
    transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, now="t0")
    fake.hold_state["sweep_status"] = "COMPLETE"
    transitions.release(_CLIENT_ID, _AUDIT_ID, _ACTOR, "released", now="t1")
    fake.hold_state["sweep_status"] = "COMPLETE"

    with pytest.raises(HoldNotActiveError):
        transitions.release(_CLIENT_ID, _AUDIT_ID, _ACTOR, "stale reinvocation", now="t9")


# ---------------------------------------------------------------------------
# Required behavior 6: interrupted transitions (sweep_status != COMPLETE)
# resume safely, reusing hold_id/hold_version, no duplicate event write.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("interrupted_sweep_status", ["PENDING", "IN_PROGRESS", "FAILED"])
def test_place_resumes_interrupted_episode_without_new_write(interrupted_sweep_status):
    transitions, fake = _make_transitions()
    first = transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, now="t0")
    fake.hold_state["sweep_status"] = interrupted_sweep_status

    write_calls_before = len(fake.write_event_calls)
    upsert_calls_before = len(fake.upsert_calls)

    resumed = transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, "resume", now="t1")

    assert resumed.is_noop is False
    assert resumed.should_run_sweep is True
    assert resumed.hold_id == first.hold_id
    assert resumed.hold_version == first.hold_version
    assert len(fake.write_event_calls) == write_calls_before
    assert len(fake.upsert_calls) == upsert_calls_before


@pytest.mark.parametrize("interrupted_sweep_status", ["PENDING", "IN_PROGRESS", "FAILED"])
def test_release_resumes_interrupted_episode_without_new_write(interrupted_sweep_status):
    transitions, fake = _make_transitions()
    transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, now="t0")
    fake.hold_state["sweep_status"] = "COMPLETE"
    first_release = transitions.release(_CLIENT_ID, _AUDIT_ID, _ACTOR, "released", now="t1")
    fake.hold_state["sweep_status"] = interrupted_sweep_status

    write_calls_before = len(fake.write_event_calls)
    upsert_calls_before = len(fake.upsert_calls)

    resumed = transitions.release(_CLIENT_ID, _AUDIT_ID, _ACTOR, "resume release", now="t2")

    assert resumed.is_noop is False
    assert resumed.should_run_sweep is True
    assert resumed.hold_id == first_release.hold_id
    assert resumed.hold_version == first_release.hold_version
    assert len(fake.write_event_calls) == write_calls_before
    assert len(fake.upsert_calls) == upsert_calls_before


# ---------------------------------------------------------------------------
# release() rejection cases (Technical Design Section 19.3 step 2, third case)
# ---------------------------------------------------------------------------


def test_release_raises_hold_not_active_when_never_held():
    transitions, _ = _make_transitions()
    with pytest.raises(HoldNotActiveError):
        transitions.release(_CLIENT_ID, _AUDIT_ID, _ACTOR, "release", now="t0")


def test_release_raises_hold_not_active_when_already_released_and_complete():
    transitions, fake = _make_transitions()
    transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, now="t0")
    fake.hold_state["sweep_status"] = "COMPLETE"
    transitions.release(_CLIENT_ID, _AUDIT_ID, _ACTOR, "released", now="t1")
    fake.hold_state["sweep_status"] = "COMPLETE"

    with pytest.raises(HoldNotActiveError):
        transitions.release(_CLIENT_ID, _AUDIT_ID, _ACTOR, "release again", now="t2")


# ---------------------------------------------------------------------------
# Required behavior 7/8: status and sweep_status independence;
# status=ACTIVE alone is never proof of full enforcement.
# ---------------------------------------------------------------------------


def test_outcome_reports_status_and_sweep_status_independently():
    transitions, fake = _make_transitions()
    transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, now="t0")
    fake.hold_state["sweep_status"] = "IN_PROGRESS"

    outcome = transitions.place(_CLIENT_ID, _AUDIT_ID, _ACTOR, "resume", now="t1")

    assert outcome.status == "ACTIVE"
    assert outcome.sweep_status == "IN_PROGRESS"


def test_is_hold_fully_enforced_requires_both_active_and_complete():
    assert is_hold_fully_enforced(None) is False
    assert is_hold_fully_enforced({"status": "ACTIVE", "sweep_status": "PENDING"}) is False
    assert is_hold_fully_enforced({"status": "ACTIVE", "sweep_status": "IN_PROGRESS"}) is False
    assert is_hold_fully_enforced({"status": "RELEASED", "sweep_status": "COMPLETE"}) is False
    assert is_hold_fully_enforced({"status": "ACTIVE", "sweep_status": "COMPLETE"}) is True


# ---------------------------------------------------------------------------
# Integration: HoldTransitions must call the *real* HoldRepository with the
# correct keyword-argument names (catches a signature-mismatch regression
# the fake double above cannot, since it accepts **kwargs unconditionally).
# ---------------------------------------------------------------------------


def test_place_calls_real_hold_repository_with_matching_signature():
    repo = HoldRepository("test-table", MagicMock())
    transitions = HoldTransitions(repo)

    written_events: list[dict[str, Any]] = []
    written_holds: list[dict[str, Any]] = []

    with (
        patch.object(repo, "get_legal_hold", return_value=None),
        patch.object(repo, "_put_once", side_effect=lambda item: written_events.append(item)),
        patch.object(repo, "_put_item", side_effect=lambda item: written_holds.append(item)),
    ):
        outcome = transitions.place(
            _CLIENT_ID, _AUDIT_ID, _ACTOR, _REASON, now="2026-07-18T00:00:00.000Z"
        )

    assert outcome.hold_version == 1
    assert len(written_events) == 1
    assert written_events[0]["hold_version"] == 1
    assert written_events[0]["SK"] == f"AUDIT#{_AUDIT_ID}#LEGALHOLD#{outcome.hold_id}#1"
    assert len(written_holds) == 1
    assert written_holds[0]["hold_version"] == 1
    assert written_holds[0]["sweep_status"] == "PENDING"


def test_release_calls_real_hold_repository_with_matching_signature():
    repo = HoldRepository("test-table", MagicMock())
    transitions = HoldTransitions(repo)

    current_hold = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#LEGALHOLD",
        "record_type": "legal_hold",
        "client_id": _CLIENT_ID,
        "audit_id": _AUDIT_ID,
        "status": "ACTIVE",
        "hold_id": "hold_fixed",
        "hold_version": 1,
        "sweep_status": "COMPLETE",
        "placed_at": "2026-07-18T00:00:00.000Z",
        "placed_by": _ACTOR,
        "reason": _REASON,
        "hold_count": 1,
        "released_at": None,
        "released_by": None,
    }

    written_events: list[dict[str, Any]] = []
    written_holds: list[dict[str, Any]] = []

    with (
        patch.object(repo, "get_legal_hold", return_value=current_hold),
        patch.object(repo, "_put_once", side_effect=lambda item: written_events.append(item)),
        patch.object(repo, "_put_item", side_effect=lambda item: written_holds.append(item)),
    ):
        outcome = transitions.release(
            _CLIENT_ID, _AUDIT_ID, _ACTOR, "release reason", now="2026-07-19T00:00:00.000Z"
        )

    assert outcome.hold_id == "hold_fixed"
    assert outcome.hold_version == 2
    assert written_events[0]["SK"] == f"AUDIT#{_AUDIT_ID}#LEGALHOLD#hold_fixed#2"
    assert written_holds[0]["status"] == "RELEASED"
    assert written_holds[0]["hold_version"] == 2
    assert written_holds[0]["sweep_status"] == "PENDING"
