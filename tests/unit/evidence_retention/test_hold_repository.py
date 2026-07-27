"""Tests for HoldRepository DynamoDB access and #LEGALHOLD# SK-write guard.

Mirrors the test style of tests/unit/audit_platform_integrity/test_repository.py
for _assert_phase7_sk.

Legal-Hold Correction B1: write_hold_event/legal_hold_event_key/
get_legal_hold_event now require an explicit hold_version parameter (ADR
Non-Negotiable Invariant 25), and upsert_hold now requires explicit
hold_version/sweep_status parameters (ADR Invariant 12; Technical Design
Section 19.1). The tests below are updated for those signature changes and
extended with new coverage for the corrected SK shape, the new fields, and
required behavior 13 (existing A1.1 namespace guards remain intact).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from release_confidence_platform.evidence_retention.hold_repository import (
    HoldRepository,
    _assert_retention_sk,
)

_TABLE = "test-table"
_CLIENT_ID = "client1"
_AUDIT_ID = "audit1"
_HOLD_ID = "hold_abc"
_DISPOSAL_ID = "disp_abc"


def _make_repo() -> HoldRepository:
    return HoldRepository(_TABLE, MagicMock())


# ---------------------------------------------------------------------------
# _assert_retention_sk direct tests (required behavior 13: existing A1.1
# namespace guards remain intact under the corrected SK shape)
# ---------------------------------------------------------------------------


def test_assert_retention_sk_accepts_legal_hold_current_state_sk():
    """LegalHold current-state SK (#LEGALHOLD, no trailing #) must pass."""
    sk = f"AUDIT#{_AUDIT_ID}#LEGALHOLD"
    _assert_retention_sk(sk)  # Must not raise


def test_assert_retention_sk_accepts_legal_hold_event_sk():
    """LegalHoldEvent SK (#LEGALHOLD#{hold_id}#{hold_version}) must pass
    under the corrected, hold_version-discriminated shape (ADR Invariant 25).
    """
    sk = f"AUDIT#{_AUDIT_ID}#LEGALHOLD#{_HOLD_ID}#1"
    _assert_retention_sk(sk)  # Must not raise


def test_assert_retention_sk_rejects_disposal_sk():
    """A #DISPOSAL#-shaped SK must be rejected by the retention guard."""
    bad_sk = f"AUDIT#{_AUDIT_ID}#DISPOSAL#{_DISPOSAL_ID}"
    with pytest.raises(AssertionError) as exc_info:
        _assert_retention_sk(bad_sk)
    assert "prohibited SK namespace" in str(exc_info.value)


def test_assert_retention_sk_rejects_sk_with_no_retention_marker():
    """An SK with neither marker must be rejected."""
    bad_sk = f"AUDIT#{_AUDIT_ID}#RUN#run1"
    with pytest.raises(AssertionError):
        _assert_retention_sk(bad_sk)


def test_assert_retention_sk_rejects_phase7_cert_sk():
    """A Phase 7 CertificationMetadata-shaped SK must be rejected (no retention marker)."""
    bad_sk = f"AUDIT#{_AUDIT_ID}#EXEC#exec1#CFG#cfg_v1#CERT#cert_v1#META"
    with pytest.raises(AssertionError):
        _assert_retention_sk(bad_sk)


def test_assert_retention_sk_rejects_sk_with_both_markers():
    """An SK containing both markers must still be rejected (prohibited wins)."""
    bad_sk = f"AUDIT#{_AUDIT_ID}#LEGALHOLD#DISPOSAL#{_DISPOSAL_ID}"
    with pytest.raises(AssertionError):
        _assert_retention_sk(bad_sk)


def test_assert_retention_sk_rejects_disposal_sk_even_with_hold_version_shape():
    """A #DISPOSAL#-shaped SK must still be rejected even if it happens to
    carry a trailing numeric segment resembling a hold_version — the guard
    must key off the namespace markers only, not the corrected SK's shape."""
    bad_sk = f"AUDIT#{_AUDIT_ID}#DISPOSAL#{_DISPOSAL_ID}#1"
    with pytest.raises(AssertionError):
        _assert_retention_sk(bad_sk)


# ---------------------------------------------------------------------------
# Key construction helpers
# ---------------------------------------------------------------------------


def test_legal_hold_key_shape():
    repo = _make_repo()
    key = repo.legal_hold_key(_CLIENT_ID, _AUDIT_ID)
    assert key == {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#LEGALHOLD",
    }


def test_legal_hold_event_key_shape_includes_hold_version():
    repo = _make_repo()
    key = repo.legal_hold_event_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1)
    assert key == {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#LEGALHOLD#{_HOLD_ID}#1",
    }


def test_legal_hold_event_key_distinct_for_place_and_release_of_same_episode():
    """The direct regression test for the defect ADR Invariant 25 fixes:
    a PLACE (hold_version=1) and its paired RELEASE (hold_version=2), which
    share the same hold_id, must never produce the same SK."""
    repo = _make_repo()
    place_key = repo.legal_hold_event_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1)
    release_key = repo.legal_hold_event_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 2)
    assert place_key != release_key
    assert place_key["SK"] != release_key["SK"]


# ---------------------------------------------------------------------------
# get_legal_hold / get_legal_hold_event
# ---------------------------------------------------------------------------


def test_get_legal_hold_returns_none_when_not_found():
    repo = _make_repo()
    with patch.object(repo, "_get_item", return_value=None):
        result = repo.get_legal_hold(_CLIENT_ID, _AUDIT_ID)
    assert result is None


def test_get_legal_hold_returns_item_when_found():
    repo = _make_repo()
    item = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#LEGALHOLD",
        "status": "ACTIVE",
        "hold_version": 1,
        "sweep_status": "PENDING",
    }
    with patch.object(repo, "_get_item", return_value=item):
        result = repo.get_legal_hold(_CLIENT_ID, _AUDIT_ID)
    assert result == item


def test_get_legal_hold_uses_correct_key():
    repo = _make_repo()
    captured = {}

    def fake_get_item(key):
        captured["key"] = key
        return None

    with patch.object(repo, "_get_item", side_effect=fake_get_item):
        repo.get_legal_hold(_CLIENT_ID, _AUDIT_ID)

    assert captured["key"]["SK"] == f"AUDIT#{_AUDIT_ID}#LEGALHOLD"
    assert "#DISPOSAL#" not in captured["key"]["SK"]


def test_get_legal_hold_event_returns_none_when_not_found():
    repo = _make_repo()
    with patch.object(repo, "_get_item", return_value=None):
        result = repo.get_legal_hold_event(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 1)
    assert result is None


def test_get_legal_hold_event_uses_hold_version_discriminated_key():
    repo = _make_repo()
    captured = {}

    def fake_get_item(key):
        captured["key"] = key
        return None

    with patch.object(repo, "_get_item", side_effect=fake_get_item):
        repo.get_legal_hold_event(_CLIENT_ID, _AUDIT_ID, _HOLD_ID, 2)

    assert captured["key"]["SK"] == f"AUDIT#{_AUDIT_ID}#LEGALHOLD#{_HOLD_ID}#2"


# ---------------------------------------------------------------------------
# write_hold_event
# ---------------------------------------------------------------------------


def test_write_hold_event_calls_put_once():
    repo = _make_repo()
    captured = {}

    def fake_put_once(item):
        captured["item"] = item

    with patch.object(repo, "_put_once", side_effect=fake_put_once):
        repo.write_hold_event(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            hold_id=_HOLD_ID,
            hold_version=1,
            action="PLACE",
            actor="operator_a",
            reason="litigation hold",
            timestamp="2026-07-18T00:00:00.000Z",
            s3_versions_retagged_count=3,
            dynamodb_items_updated_count=2,
        )

    item = captured["item"]
    assert item["PK"] == f"CLIENT#{_CLIENT_ID}"
    assert item["SK"] == f"AUDIT#{_AUDIT_ID}#LEGALHOLD#{_HOLD_ID}#1"
    assert item["record_type"] == "legal_hold_event"
    assert item["hold_version"] == 1
    assert item["action"] == "PLACE"
    assert item["s3_versions_retagged_count"] == 3


def test_write_hold_event_defaults_marker_fields_to_pending_plumbing_state():
    """Legal-Hold Correction B1 never sets marker_status to anything other
    than its initial default -- proving the plumbing default here, not any
    marker-establishment behavior (B2 scope)."""
    repo = _make_repo()
    captured = {}

    with patch.object(repo, "_put_once", side_effect=lambda item: captured.update(item=item)):
        repo.write_hold_event(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            hold_id=_HOLD_ID,
            hold_version=1,
            action="PLACE",
            actor="operator_a",
            reason="litigation hold",
            timestamp="2026-07-18T00:00:00.000Z",
            s3_versions_retagged_count=0,
            dynamodb_items_updated_count=0,
        )

    item = captured["item"]
    assert item["marker_status"] == "PENDING"
    assert item["marker_s3_key"] is None
    assert item["marker_confirmed_last_modified"] is None


def test_write_hold_event_asserts_retention_sk():
    """write_hold_event must not raise AssertionError for a valid call."""
    repo = _make_repo()
    with patch.object(repo, "_put_once"):
        repo.write_hold_event(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            hold_id=_HOLD_ID,
            hold_version=2,
            action="RELEASE",
            actor="operator_a",
            reason="litigation hold released",
            timestamp="2026-07-19T00:00:00.000Z",
            s3_versions_retagged_count=0,
            dynamodb_items_updated_count=0,
        )


def test_write_hold_event_place_and_release_of_same_episode_use_distinct_keys():
    """End-to-end regression proof (required behavior 4): a PLACE and its
    paired RELEASE, sharing hold_id, never write to the same SK."""
    repo = _make_repo()
    captured_items = []

    with patch.object(
        repo, "_put_once", side_effect=lambda item: captured_items.append(item)
    ):
        repo.write_hold_event(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            hold_id=_HOLD_ID,
            hold_version=1,
            action="PLACE",
            actor="operator_a",
            reason="litigation hold",
            timestamp="2026-07-18T00:00:00.000Z",
            s3_versions_retagged_count=0,
            dynamodb_items_updated_count=0,
        )
        repo.write_hold_event(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            hold_id=_HOLD_ID,
            hold_version=2,
            action="RELEASE",
            actor="operator_a",
            reason="litigation hold released",
            timestamp="2026-07-19T00:00:00.000Z",
            s3_versions_retagged_count=0,
            dynamodb_items_updated_count=0,
        )

    assert len(captured_items) == 2
    assert captured_items[0]["SK"] != captured_items[1]["SK"]


# ---------------------------------------------------------------------------
# upsert_hold
# ---------------------------------------------------------------------------


def test_upsert_hold_calls_put_item():
    repo = _make_repo()
    captured = {}

    def fake_put_item(item):
        captured["item"] = item

    with patch.object(repo, "_put_item", side_effect=fake_put_item):
        repo.upsert_hold(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            status="ACTIVE",
            hold_id=_HOLD_ID,
            hold_version=1,
            sweep_status="PENDING",
            placed_at="2026-07-18T00:00:00.000Z",
            placed_by="operator_a",
            reason="litigation hold",
            hold_count=1,
        )

    item = captured["item"]
    assert item["PK"] == f"CLIENT#{_CLIENT_ID}"
    assert item["SK"] == f"AUDIT#{_AUDIT_ID}#LEGALHOLD"
    assert item["record_type"] == "legal_hold"
    assert item["status"] == "ACTIVE"
    assert item["hold_version"] == 1
    assert item["sweep_status"] == "PENDING"
    assert item["hold_count"] == 1
    assert item["released_at"] is None
    assert item["released_by"] is None
    assert item["marker_s3_key"] is None
    assert item["marker_confirmed_last_modified"] is None


def test_upsert_hold_released_state():
    repo = _make_repo()
    captured = {}

    def fake_put_item(item):
        captured["item"] = item

    with patch.object(repo, "_put_item", side_effect=fake_put_item):
        repo.upsert_hold(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            status="RELEASED",
            hold_id=_HOLD_ID,
            hold_version=2,
            sweep_status="PENDING",
            placed_at="2026-07-18T00:00:00.000Z",
            placed_by="operator_a",
            reason="litigation hold",
            hold_count=1,
            released_at="2026-07-19T00:00:00.000Z",
            released_by="operator_b",
        )

    item = captured["item"]
    assert item["status"] == "RELEASED"
    assert item["hold_version"] == 2
    assert item["released_at"] == "2026-07-19T00:00:00.000Z"
    assert item["released_by"] == "operator_b"


def test_upsert_hold_asserts_retention_sk():
    """upsert_hold must not raise AssertionError for a valid call."""
    repo = _make_repo()
    with patch.object(repo, "_put_item"):
        repo.upsert_hold(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            status="ACTIVE",
            hold_id=_HOLD_ID,
            hold_version=1,
            sweep_status="PENDING",
            placed_at="2026-07-18T00:00:00.000Z",
            placed_by="operator_a",
            reason="litigation hold",
            hold_count=1,
        )


def test_upsert_hold_persists_sweep_status_independent_of_status():
    """Required behavior 7: status and sweep_status are never conflated."""
    repo = _make_repo()
    captured = {}

    with patch.object(repo, "_put_item", side_effect=lambda item: captured.update(item=item)):
        repo.upsert_hold(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            status="ACTIVE",
            hold_id=_HOLD_ID,
            hold_version=3,
            sweep_status="FAILED",
            placed_at="2026-07-18T00:00:00.000Z",
            placed_by="operator_a",
            reason="litigation hold",
            hold_count=2,
        )

    # status=ACTIVE and sweep_status=FAILED coexist -- neither is derived
    # from, or overrides, the other.
    assert captured["item"]["status"] == "ACTIVE"
    assert captured["item"]["sweep_status"] == "FAILED"


# ---------------------------------------------------------------------------
# update_hold_event_marker_fields (Legal-Hold Correction B2; Technical
# Design Section 19.5.3 steps 2-3; ADR Non-Negotiable Invariant 24)
# ---------------------------------------------------------------------------


def test_update_hold_event_marker_fields_calls_update_item():
    repo = _make_repo()
    captured = {}

    def fake_call(method_name, **kwargs):
        captured["method_name"] = method_name
        captured["kwargs"] = kwargs
        return {}

    with patch.object(repo, "_call", side_effect=fake_call):
        repo.update_hold_event_marker_fields(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            hold_id=_HOLD_ID,
            hold_version=1,
            marker_s3_key=f"retention-markers/{_CLIENT_ID}/{_AUDIT_ID}/{_HOLD_ID}/1-PLACE.marker",
            marker_status="CONFIRMED",
            marker_confirmed_last_modified="2026-07-18T00:00:00Z",
        )

    assert captured["method_name"] == "update_item"
    assert captured["kwargs"]["Key"] == {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#LEGALHOLD#{_HOLD_ID}#1",
    }
    names = captured["kwargs"]["ExpressionAttributeNames"]
    assert set(names.values()) == {
        "marker_s3_key",
        "marker_status",
        "marker_confirmed_last_modified",
    }
    values = captured["kwargs"]["ExpressionAttributeValues"]
    assert values[":ms"] == "CONFIRMED"
    assert values[":mlm"] == "2026-07-18T00:00:00Z"


def test_update_hold_event_marker_fields_asserts_retention_sk():
    """Must not raise AssertionError for a valid call, and must raise for a
    disposal-shaped SK if one were ever (incorrectly) constructed -- proven
    indirectly via the key construction being retention-namespaced by
    definition (legal_hold_event_key always produces a #LEGALHOLD# SK)."""
    repo = _make_repo()
    with patch.object(repo, "_call"):
        repo.update_hold_event_marker_fields(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            hold_id=_HOLD_ID,
            hold_version=2,
            marker_s3_key=None,
            marker_status="FAILED",
            marker_confirmed_last_modified=None,
        )


def test_update_hold_event_marker_fields_supports_failed_state_with_none_values():
    repo = _make_repo()
    captured = {}

    with patch.object(
        repo, "_call", side_effect=lambda method_name, **kwargs: captured.update(kwargs=kwargs)
    ):
        repo.update_hold_event_marker_fields(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            hold_id=_HOLD_ID,
            hold_version=1,
            marker_s3_key=f"retention-markers/{_CLIENT_ID}/{_AUDIT_ID}/{_HOLD_ID}/1-PLACE.marker",
            marker_status="FAILED",
            marker_confirmed_last_modified=None,
        )

    values = captured["kwargs"]["ExpressionAttributeValues"]
    assert values[":ms"] == "FAILED"
    assert values[":mlm"] is None


def test_update_hold_event_marker_fields_does_not_touch_write_once_fields():
    """The UpdateExpression must only ever SET the three marker fields --
    never action/actor/reason/timestamp/counts, mirroring
    CustodySweepClient's _assert_custody_field_only_update discipline for
    its own single-attribute updates."""
    repo = _make_repo()
    captured = {}

    with patch.object(
        repo, "_call", side_effect=lambda method_name, **kwargs: captured.update(kwargs=kwargs)
    ):
        repo.update_hold_event_marker_fields(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            hold_id=_HOLD_ID,
            hold_version=1,
            marker_s3_key="retention-markers/x/y/z/1-PLACE.marker",
            marker_status="CONFIRMED",
            marker_confirmed_last_modified="2026-07-18T00:00:00Z",
        )

    touched = set(captured["kwargs"]["ExpressionAttributeNames"].values())
    assert touched == {"marker_s3_key", "marker_status", "marker_confirmed_last_modified"}
    for forbidden in ("action", "actor", "reason", "timestamp", "s3_versions_retagged_count"):
        assert forbidden not in touched
