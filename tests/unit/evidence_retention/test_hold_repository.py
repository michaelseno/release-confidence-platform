"""Tests for HoldRepository DynamoDB access and #LEGALHOLD# SK-write guard.

Mirrors the test style of tests/unit/audit_platform_integrity/test_repository.py
for _assert_phase7_sk.
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
# _assert_retention_sk direct tests
# ---------------------------------------------------------------------------


def test_assert_retention_sk_accepts_legal_hold_current_state_sk():
    """LegalHold current-state SK (#LEGALHOLD, no trailing #) must pass."""
    sk = f"AUDIT#{_AUDIT_ID}#LEGALHOLD"
    _assert_retention_sk(sk)  # Must not raise


def test_assert_retention_sk_accepts_legal_hold_event_sk():
    """LegalHoldEvent SK (#LEGALHOLD#{hold_id}) must pass."""
    sk = f"AUDIT#{_AUDIT_ID}#LEGALHOLD#{_HOLD_ID}"
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


def test_legal_hold_event_key_shape():
    repo = _make_repo()
    key = repo.legal_hold_event_key(_CLIENT_ID, _AUDIT_ID, _HOLD_ID)
    assert key == {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#LEGALHOLD#{_HOLD_ID}",
    }


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
    item = {"PK": f"CLIENT#{_CLIENT_ID}", "SK": f"AUDIT#{_AUDIT_ID}#LEGALHOLD", "status": "ACTIVE"}
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
        result = repo.get_legal_hold_event(_CLIENT_ID, _AUDIT_ID, _HOLD_ID)
    assert result is None


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
            action="PLACE",
            actor="operator_a",
            reason="litigation hold",
            timestamp="2026-07-18T00:00:00.000Z",
            s3_versions_retagged_count=3,
            dynamodb_items_updated_count=2,
        )

    item = captured["item"]
    assert item["PK"] == f"CLIENT#{_CLIENT_ID}"
    assert item["SK"] == f"AUDIT#{_AUDIT_ID}#LEGALHOLD#{_HOLD_ID}"
    assert item["record_type"] == "legal_hold_event"
    assert item["action"] == "PLACE"
    assert item["s3_versions_retagged_count"] == 3


def test_write_hold_event_asserts_retention_sk():
    """write_hold_event must not raise AssertionError for a valid call."""
    repo = _make_repo()
    with patch.object(repo, "_put_once"):
        repo.write_hold_event(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            hold_id=_HOLD_ID,
            action="RELEASE",
            actor="operator_a",
            reason="litigation hold released",
            timestamp="2026-07-19T00:00:00.000Z",
            s3_versions_retagged_count=0,
            dynamodb_items_updated_count=0,
        )


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
    assert item["hold_count"] == 1
    assert item["released_at"] is None
    assert item["released_by"] is None


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
            placed_at="2026-07-18T00:00:00.000Z",
            placed_by="operator_a",
            reason="litigation hold",
            hold_count=1,
            released_at="2026-07-19T00:00:00.000Z",
            released_by="operator_b",
        )

    item = captured["item"]
    assert item["status"] == "RELEASED"
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
            placed_at="2026-07-18T00:00:00.000Z",
            placed_by="operator_a",
            reason="litigation hold",
            hold_count=1,
        )
