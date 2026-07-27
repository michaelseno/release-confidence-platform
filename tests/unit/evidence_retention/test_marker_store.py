"""Tests for the S3 canary-marker store (Legal-Hold Correction B2; Technical
Design Section 19.5.1-19.5.7; ADR Non-Negotiable Invariants 15-24).

Mirrors the test style of test_custody_sweep_client.py (patch.object on an
internal dispatch helper / MagicMock S3 client rather than simulating full
low-level boto3 response shapes for most cases), plus direct tests of the
_assert_marker_key() structural guard, matching the existing negative-test
pattern for _assert_retention_sk/_assert_disposal_sk/
_assert_custody_field_only_update.
"""

from __future__ import annotations

import json

import pytest
from botocore.exceptions import ClientError

from release_confidence_platform.evidence_retention.marker_store import (
    MarkerEstablishmentFailedError,
    MarkerIntegrityError,
    MarkerStore,
    _assert_marker_key,
    build_marker_content,
    build_marker_key,
    format_s3_timestamp,
    parse_s3_timestamp,
)

_CLIENT_ID = "client_abc"
_AUDIT_ID = "audit_xyz"
_HOLD_ID = "hold_4f5a"
_BUCKET = "test-bucket"


def _precondition_failed() -> ClientError:
    return ClientError(
        {"Error": {"Code": "PreconditionFailed", "Message": "At least one condition failed"}},
        "PutObject",
    )


def _make_body(content: dict) -> dict:
    class _FakeBody:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self) -> bytes:
            return self._data

    return {"Body": _FakeBody(json.dumps(content).encode("utf-8"))}


class _FakeClock:
    """Deterministic, injectable monotonic clock for wall-clock-budget tests."""

    def __init__(self, start: float = 0.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _make_store(s3_client, **kwargs) -> MarkerStore:
    return MarkerStore(_BUCKET, s3_client, **kwargs)


# ---------------------------------------------------------------------------
# build_marker_key / build_marker_content — worked-example proofs
# ---------------------------------------------------------------------------


def test_build_marker_key_matches_technical_design_worked_example():
    """Technical Design Section 19.5.1's own worked PLACE -> RELEASE example."""
    place_key = build_marker_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    release_key = build_marker_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 2, "RELEASE")
    assert place_key == "retention-markers/client_abc/audit_xyz/hold_4f5a/1-PLACE.marker"
    assert release_key == "retention-markers/client_abc/audit_xyz/hold_4f5a/2-RELEASE.marker"
    assert place_key != release_key


def test_build_marker_content_is_deterministic():
    a = build_marker_content(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    b = build_marker_content(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    assert a == b
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_build_marker_content_has_required_fields():
    content = build_marker_content(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 2, "RELEASE")
    assert content["schema_version"] == 1
    assert content["client_id"] == _CLIENT_ID
    assert content["audit_id"] == _AUDIT_ID
    assert content["hold_id"] == _HOLD_ID
    assert content["hold_version"] == 2
    assert content["transition"] == "RELEASE"
    assert content["transition_id"] == f"{_HOLD_ID}#2#RELEASE"


def test_build_marker_content_place_and_release_differ_only_in_transition_fields():
    place = build_marker_content(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    release = build_marker_content(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 2, "RELEASE")
    assert place["client_id"] == release["client_id"]
    assert place["audit_id"] == release["audit_id"]
    assert place["hold_id"] == release["hold_id"]
    assert place["hold_version"] != release["hold_version"]
    assert place["transition"] != release["transition"]
    assert place["transition_id"] != release["transition_id"]


# ---------------------------------------------------------------------------
# _assert_marker_key structural guard — positive cases
# ---------------------------------------------------------------------------


def test_assert_marker_key_accepts_valid_place_key():
    key = build_marker_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    _assert_marker_key(key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")  # must not raise


def test_assert_marker_key_accepts_valid_release_key():
    key = build_marker_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 2, "RELEASE")
    _assert_marker_key(key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 2, "RELEASE")  # must not raise


# ---------------------------------------------------------------------------
# _assert_marker_key structural guard — negative cases (required coverage:
# wrong prefix, missing path components, mismatched client_id/audit_id/
# hold_id/hold_version/transition, extra/traversal-like components)
# ---------------------------------------------------------------------------


def test_assert_marker_key_rejects_wrong_prefix():
    bad_key = f"raw-results/{_CLIENT_ID}/{_AUDIT_ID}/{_HOLD_ID}/1-PLACE.marker"
    with pytest.raises(AssertionError):
        _assert_marker_key(bad_key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")


def test_assert_marker_key_rejects_missing_path_components():
    bad_key = f"retention-markers/{_CLIENT_ID}/{_HOLD_ID}/1-PLACE.marker"
    with pytest.raises(AssertionError):
        _assert_marker_key(bad_key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")


def test_assert_marker_key_rejects_mismatched_client_id():
    key = build_marker_key("other_client", _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    with pytest.raises(AssertionError):
        _assert_marker_key(key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")


def test_assert_marker_key_rejects_mismatched_audit_id():
    key = build_marker_key(_CLIENT_ID, "other_audit", _HOLD_ID, 1, "PLACE")
    with pytest.raises(AssertionError):
        _assert_marker_key(key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")


def test_assert_marker_key_rejects_mismatched_hold_id():
    key = build_marker_key(_CLIENT_ID, _AUDIT_ID, "hold_other", 1, "PLACE")
    with pytest.raises(AssertionError):
        _assert_marker_key(key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")


def test_assert_marker_key_rejects_mismatched_hold_version():
    key = build_marker_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 2, "PLACE")
    with pytest.raises(AssertionError):
        _assert_marker_key(key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")


def test_assert_marker_key_rejects_place_key_when_release_expected():
    key = build_marker_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    with pytest.raises(AssertionError):
        _assert_marker_key(key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "RELEASE")


def test_assert_marker_key_rejects_release_key_when_place_expected():
    key = build_marker_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "RELEASE")
    with pytest.raises(AssertionError):
        _assert_marker_key(key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")


def test_assert_marker_key_rejects_extra_path_segment():
    bad_key = f"retention-markers/{_CLIENT_ID}/{_AUDIT_ID}/{_HOLD_ID}/extra/1-PLACE.marker"
    with pytest.raises(AssertionError):
        _assert_marker_key(bad_key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")


def test_assert_marker_key_rejects_traversal_like_component():
    bad_key = f"retention-markers/../{_AUDIT_ID}/{_HOLD_ID}/1-PLACE.marker"
    with pytest.raises(AssertionError):
        _assert_marker_key(bad_key, _CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")


# ---------------------------------------------------------------------------
# format_s3_timestamp / parse_s3_timestamp
# ---------------------------------------------------------------------------


def test_format_s3_timestamp_from_datetime():
    from datetime import UTC, datetime

    value = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
    assert format_s3_timestamp(value) == "2026-07-18T12:00:00Z"


def test_format_s3_timestamp_passthrough_for_string():
    assert format_s3_timestamp("2026-07-18T12:00:00Z") == "2026-07-18T12:00:00Z"


def test_parse_s3_timestamp_roundtrip():
    from datetime import UTC, datetime

    value = datetime(2026, 7, 18, 12, 0, 0, tzinfo=UTC)
    formatted = format_s3_timestamp(value)
    assert parse_s3_timestamp(formatted) == value


# ---------------------------------------------------------------------------
# MarkerStore.establish_marker — atomic first-write-wins creation (required:
# "Atomic first marker creation")
# ---------------------------------------------------------------------------


def test_establish_marker_atomic_first_write_uses_if_none_match_star():
    s3 = _FakeS3()
    store = _make_store(s3)
    result = store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")

    assert result.marker_status == "CONFIRMED"
    assert result.marker_s3_key == build_marker_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    put_calls = [c for c in s3.calls if c[0] == "put_object"]
    assert len(put_calls) == 1
    assert put_calls[0][1]["IfNoneMatch"] == "*"
    assert put_calls[0][1]["Key"] == result.marker_s3_key


def test_establish_marker_never_calls_head_object_then_put_object_check_then_write():
    """Required negative proof: no HeadObject precedes the conditional
    PutObject (the anti-pattern this mechanism must never replicate,
    ADR Invariant 19)."""
    s3 = _FakeS3()
    store = _make_store(s3)
    store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")

    first_call = s3.calls[0]
    assert first_call[0] == "put_object"


def test_establish_marker_reads_back_last_modified_via_head_object_never_trusting_put_response():
    """Required: "Authoritative LastModified capture (via read-back, never
    trusting PutObject's own response)"."""
    s3 = _FakeS3(head_object_last_modified="2026-07-18T00:00:05Z")
    store = _make_store(s3)
    result = store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")

    assert result.marker_confirmed_last_modified == "2026-07-18T00:00:05Z"
    head_calls = [c for c in s3.calls if c[0] == "head_object"]
    assert len(head_calls) == 1


# ---------------------------------------------------------------------------
# Idempotent replay / orphan-marker recovery (required: "Idempotent replay
# with identical content")
# ---------------------------------------------------------------------------


def test_establish_marker_reuses_existing_matching_marker_on_precondition_failure():
    existing_content = build_marker_content(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    s3 = _FakeS3(
        put_object_raises=_precondition_failed(),
        get_object_body=existing_content,
        head_object_last_modified="2026-07-18T00:00:00Z",
    )
    store = _make_store(s3)
    result = store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")

    assert result.marker_status == "CONFIRMED"
    assert result.marker_confirmed_last_modified == "2026-07-18T00:00:00Z"
    get_calls = [c for c in s3.calls if c[0] == "get_object"]
    assert len(get_calls) == 1


def test_establish_marker_two_overlapping_attempts_neither_overwrites_the_other():
    """Required Technical Design Section 19.5.10 test 6: two genuinely
    overlapping marker-establishment attempts for the same transition --
    exactly one PutObject succeeds, the other receives a precondition
    failure and falls back to reading the winner's marker, neither
    overwrites the other's confirmed marker_confirmed_last_modified."""
    winner_content = build_marker_content(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    s3_loser = _FakeS3(
        put_object_raises=_precondition_failed(),
        get_object_body=winner_content,
        head_object_last_modified="2026-07-18T00:00:00Z",
    )
    loser_store = _make_store(s3_loser)
    loser_result = loser_store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")

    s3_winner = _FakeS3(head_object_last_modified="2026-07-18T00:00:00Z")
    winner_store = _make_store(s3_winner)
    winner_result = winner_store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")

    assert (
        loser_result.marker_confirmed_last_modified
        == winner_result.marker_confirmed_last_modified
    )
    assert loser_result.marker_s3_key == winner_result.marker_s3_key


# ---------------------------------------------------------------------------
# Rejection of conflicting existing content (required: "Rejection of
# conflicting existing content — integrity/collision failure")
# ---------------------------------------------------------------------------


def test_establish_marker_raises_integrity_error_on_mismatched_existing_content():
    conflicting_content = build_marker_content(_CLIENT_ID, _AUDIT_ID, "hold_DIFFERENT", 1, "PLACE")
    s3 = _FakeS3(
        put_object_raises=_precondition_failed(),
        get_object_body=conflicting_content,
    )
    store = _make_store(s3)
    with pytest.raises(MarkerIntegrityError):
        store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")


def test_establish_marker_integrity_error_is_not_retried():
    """A genuine identity mismatch must propagate immediately, never be
    silently retried into a false success."""
    conflicting_content = build_marker_content(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 2, "RELEASE")
    s3 = _FakeS3(put_object_raises=_precondition_failed(), get_object_body=conflicting_content)
    store = _make_store(s3)
    with pytest.raises(MarkerIntegrityError):
        store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    # Only one put_object attempt -- no retry loop consumed on a genuine
    # collision.
    put_calls = [c for c in s3.calls if c[0] == "put_object"]
    assert len(put_calls) == 1


def test_establish_marker_never_attempts_unconditioned_overwrite():
    """Structural proof that an unconditioned overwrite is impossible: even
    when the store deliberately simulates "the object already exists"
    (PreconditionFailed) with mismatched content, MarkerStore never issues a
    second put_object call without IfNoneMatch -- it only ever reads via
    get_object/head_object from that point on, per the design (no code path
    exists that could "fix" a conflict via an unconditional PutObject)."""
    conflicting_content = build_marker_content(_CLIENT_ID, _AUDIT_ID, "hold_other", 1, "PLACE")
    s3 = _FakeS3(put_object_raises=_precondition_failed(), get_object_body=conflicting_content)
    store = _make_store(s3)
    with pytest.raises(MarkerIntegrityError):
        store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    for name, kwargs in s3.calls:
        if name == "put_object":
            assert kwargs.get("IfNoneMatch") == "*"


# ---------------------------------------------------------------------------
# PLACE and RELEASE marker non-collision / PLACE -> RELEASE -> PLACE episodes
# (required coverage, at the key-construction level -- full episode-level
# proof lives in test_retention_service.py)
# ---------------------------------------------------------------------------


def test_place_and_release_markers_of_same_episode_do_not_collide():
    s3 = _FakeS3()
    store = _make_store(s3)
    place_result = store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    release_result = store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 2, "RELEASE")
    assert place_result.marker_s3_key != release_result.marker_s3_key


def test_place_release_place_three_generations_no_aliasing():
    s3 = _FakeS3()
    store = _make_store(s3)
    first_place = store.establish_marker(_CLIENT_ID, _AUDIT_ID, "hold_gen1", 1, "PLACE")
    release = store.establish_marker(_CLIENT_ID, _AUDIT_ID, "hold_gen1", 2, "RELEASE")
    second_place = store.establish_marker(_CLIENT_ID, _AUDIT_ID, "hold_gen2", 3, "PLACE")

    keys = {first_place.marker_s3_key, release.marker_s3_key, second_place.marker_s3_key}
    assert len(keys) == 3


# ---------------------------------------------------------------------------
# Marker establishment timeout/failure (required: deterministic error,
# marker_status=FAILED persistence is retention_service.py's job -- this
# module proves the raised error type/retry-exhaustion behavior itself)
# ---------------------------------------------------------------------------


def test_establish_marker_raises_on_put_object_retry_exhaustion():
    s3 = _FakeS3(put_object_raises=RuntimeError("transient S3 failure"), always_fail_put=True)
    store = _make_store(s3, max_attempts=3)
    with pytest.raises(MarkerEstablishmentFailedError):
        store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    put_calls = [c for c in s3.calls if c[0] == "put_object"]
    assert len(put_calls) == 3


def test_establish_marker_raises_on_head_object_retry_exhaustion():
    s3 = _FakeS3(head_object_raises=RuntimeError("transient S3 failure"), always_fail_head=True)
    store = _make_store(s3, max_attempts=3)
    with pytest.raises(MarkerEstablishmentFailedError):
        store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    head_calls = [c for c in s3.calls if c[0] == "head_object"]
    assert len(head_calls) == 3


def test_establish_marker_retries_transient_put_failure_then_succeeds():
    s3 = _FakeS3(put_object_raises=RuntimeError("transient"), fail_put_times=2)
    store = _make_store(s3, max_attempts=3)
    result = store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    assert result.marker_status == "CONFIRMED"
    put_calls = [c for c in s3.calls if c[0] == "put_object"]
    assert len(put_calls) == 3


# ---------------------------------------------------------------------------
# Wall-clock cap (required: "Clock-boundary and defense-in-depth buffer
# behavior"; Technical Design Section 19.5.10 test 7)
# ---------------------------------------------------------------------------


def test_establish_marker_fails_closed_on_wall_clock_budget_even_with_attempts_remaining():
    """Simulated slow-but-eventually-successful retries whose cumulative
    latency exceeds the wall-clock budget -- must fail closed even though
    the attempt-count cap has not been reached."""
    clock = _FakeClock()

    class _SlowFailingS3:
        calls: list = []

        def put_object(self, **kwargs):
            self.calls.append(("put_object", kwargs))
            clock.advance(3.0)  # each attempt is individually slow
            raise RuntimeError("slow transient failure")

    s3 = _SlowFailingS3()
    store = MarkerStore(
        _BUCKET, s3, clock=clock, max_attempts=10, wall_clock_budget_seconds=5.0
    )
    with pytest.raises(MarkerEstablishmentFailedError):
        store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    # Budget is 5s, each attempt costs 3s -- only 2 attempts should fit
    # (0->3s: attempt 1 ends; 3s->6s: attempt 2 starts within budget check
    # at t=3 <5, ends at t=6; next check at t=6 exceeds budget) -- assert
    # retries were abandoned well before the max_attempts=10 cap.
    assert len(s3.calls) < 10


def test_establish_marker_wall_clock_budget_shared_across_put_and_head_phases():
    """The wall-clock deadline must span BOTH phases of establish_marker(),
    not reset between the PutObject phase and the HeadObject read-back
    phase (Technical Design Section 19.5.6's architecture + security review
    correction)."""
    clock = _FakeClock()

    class _SlowHeadS3:
        def __init__(self):
            self.calls = []

        def put_object(self, **kwargs):
            self.calls.append(("put_object", kwargs))
            clock.advance(4.5)  # consumes most of the budget

        def head_object(self, **kwargs):
            self.calls.append(("head_object", kwargs))
            clock.advance(4.5)  # would exceed the shared 5s budget
            raise RuntimeError("slow head_object")

    s3 = _SlowHeadS3()
    store = MarkerStore(_BUCKET, s3, clock=clock, max_attempts=10, wall_clock_budget_seconds=5.0)
    with pytest.raises(MarkerEstablishmentFailedError):
        store.establish_marker(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1, "PLACE")
    head_calls = [c for c in s3.calls if c[0] == "head_object"]
    # Only one head_object attempt should have been made before the shared
    # deadline (already at 4.5s after the put phase) is exceeded.
    assert len(head_calls) == 1


# ---------------------------------------------------------------------------
# Structural allowlist -- MarkerStore may only call put_object/head_object/
# get_object (mirrors CustodySweepClient's own allowlist discipline)
# ---------------------------------------------------------------------------


def test_call_s3_rejects_disallowed_method_name():
    store = _make_store(_FakeS3())
    with pytest.raises(AssertionError):
        store._call_s3("delete_object", Key="retention-markers/x")


def test_call_s3_rejects_list_object_versions():
    """MarkerStore must never gain evidence-sweep capability -- it operates
    exclusively on the retention-markers/ prefix, never the evidence-class
    prefixes CustodySweepClient enumerates."""
    store = _make_store(_FakeS3())
    with pytest.raises(AssertionError):
        store._call_s3("list_object_versions", Bucket=_BUCKET, Prefix="raw-results/")


# ---------------------------------------------------------------------------
# Test double: a minimal, explicit fake S3 client (not a MagicMock) so every
# call and its exact kwargs are directly inspectable, mirroring
# test_custody_sweep_client.py's own patch.object-on-dispatch-helper style
# but implemented as a full fake client here since MarkerStore's _call_s3
# dispatches directly to attribute lookup on the client, same pattern as
# CustodySweepClient._call_s3.
# ---------------------------------------------------------------------------


class _FakeS3:
    def __init__(
        self,
        *,
        put_object_raises: Exception | None = None,
        always_fail_put: bool = False,
        fail_put_times: int = 0,
        head_object_raises: Exception | None = None,
        always_fail_head: bool = False,
        head_object_last_modified: str = "2026-07-18T00:00:00Z",
        get_object_body: dict | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._put_object_raises = put_object_raises
        self._always_fail_put = always_fail_put
        self._fail_put_times = fail_put_times
        self._put_attempts = 0
        self._head_object_raises = head_object_raises
        self._always_fail_head = always_fail_head
        self._head_attempts = 0
        self._head_object_last_modified = head_object_last_modified
        self._get_object_body = get_object_body

    def put_object(self, **kwargs):
        self.calls.append(("put_object", kwargs))
        self._put_attempts += 1
        if self._put_object_raises is not None:
            if self._always_fail_put:
                raise self._put_object_raises
            if self._put_attempts <= self._fail_put_times:
                raise self._put_object_raises
            if isinstance(self._put_object_raises, ClientError):
                # A precondition-failure double is meant to fail exactly
                # once, permanently (simulating a persistently-existing
                # marker), not transiently.
                raise self._put_object_raises
        return {}

    def head_object(self, **kwargs):
        self.calls.append(("head_object", kwargs))
        self._head_attempts += 1
        if self._head_object_raises is not None and (
            self._always_fail_head or self._head_attempts == 1
        ):
            if self._always_fail_head:
                raise self._head_object_raises
        return {"LastModified": self._head_object_last_modified}

    def get_object(self, **kwargs):
        self.calls.append(("get_object", kwargs))
        body = self._get_object_body if self._get_object_body is not None else {}
        return _make_body(body)
