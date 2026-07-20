"""Tests for DisposalRepository DynamoDB access and #DISPOSAL# SK-write guard.

Mirrors the test style of tests/unit/audit_platform_integrity/test_repository.py
for _assert_phase7_sk, and is the symmetric counterpart to
test_hold_repository.py's coverage of _assert_retention_sk.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from release_confidence_platform.evidence_retention.disposal_repository import (
    DisposalRepository,
    _assert_disposal_sk,
)

_TABLE = "test-table"
_CLIENT_ID = "client1"
_AUDIT_ID = "audit1"
_HOLD_ID = "hold_abc"
_DISPOSAL_ID = "disp_abc"


def _make_repo() -> DisposalRepository:
    return DisposalRepository(_TABLE, MagicMock())


# ---------------------------------------------------------------------------
# _assert_disposal_sk direct tests
# ---------------------------------------------------------------------------


def test_assert_disposal_sk_accepts_disposal_record_sk():
    sk = f"AUDIT#{_AUDIT_ID}#DISPOSAL#{_DISPOSAL_ID}"
    _assert_disposal_sk(sk)  # Must not raise


def test_assert_disposal_sk_rejects_legal_hold_current_state_sk():
    """A #LEGALHOLD#-shaped (current-state) SK must be rejected."""
    bad_sk = f"AUDIT#{_AUDIT_ID}#LEGALHOLD"
    with pytest.raises(AssertionError) as exc_info:
        _assert_disposal_sk(bad_sk)
    assert "prohibited SK namespace" in str(exc_info.value)


def test_assert_disposal_sk_rejects_legal_hold_event_sk():
    """A #LEGALHOLD#{hold_id}-shaped (event log) SK must be rejected."""
    bad_sk = f"AUDIT#{_AUDIT_ID}#LEGALHOLD#{_HOLD_ID}"
    with pytest.raises(AssertionError) as exc_info:
        _assert_disposal_sk(bad_sk)
    assert "prohibited SK namespace" in str(exc_info.value)


def test_assert_disposal_sk_rejects_sk_with_no_disposal_marker():
    bad_sk = f"AUDIT#{_AUDIT_ID}#RUN#run1"
    with pytest.raises(AssertionError):
        _assert_disposal_sk(bad_sk)


def test_assert_disposal_sk_rejects_sk_with_both_markers():
    bad_sk = f"AUDIT#{_AUDIT_ID}#LEGALHOLD#DISPOSAL#{_DISPOSAL_ID}"
    with pytest.raises(AssertionError):
        _assert_disposal_sk(bad_sk)


# ---------------------------------------------------------------------------
# Key construction helpers
# ---------------------------------------------------------------------------


def test_disposal_record_key_shape():
    repo = _make_repo()
    key = repo.disposal_record_key(_CLIENT_ID, _AUDIT_ID, _DISPOSAL_ID)
    assert key == {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#DISPOSAL#{_DISPOSAL_ID}",
    }


# ---------------------------------------------------------------------------
# get_disposal_record
# ---------------------------------------------------------------------------


def test_get_disposal_record_returns_none_when_not_found():
    repo = _make_repo()
    with patch.object(repo, "_get_item", return_value=None):
        result = repo.get_disposal_record(_CLIENT_ID, _AUDIT_ID, _DISPOSAL_ID)
    assert result is None


def test_get_disposal_record_returns_item_when_found():
    repo = _make_repo()
    item = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#DISPOSAL#{_DISPOSAL_ID}",
        "disposal_mechanism": "DYNAMODB_TTL",
    }
    with patch.object(repo, "_get_item", return_value=item):
        result = repo.get_disposal_record(_CLIENT_ID, _AUDIT_ID, _DISPOSAL_ID)
    assert result == item


def test_get_disposal_record_uses_correct_key():
    repo = _make_repo()
    captured = {}

    def fake_get_item(key):
        captured["key"] = key
        return None

    with patch.object(repo, "_get_item", side_effect=fake_get_item):
        repo.get_disposal_record(_CLIENT_ID, _AUDIT_ID, _DISPOSAL_ID)

    assert captured["key"]["SK"] == f"AUDIT#{_AUDIT_ID}#DISPOSAL#{_DISPOSAL_ID}"
    assert "#LEGALHOLD" not in captured["key"]["SK"]


# ---------------------------------------------------------------------------
# put_disposal_record
# ---------------------------------------------------------------------------


def test_put_disposal_record_calls_put_once():
    repo = _make_repo()
    captured = {}

    def fake_put_once(item):
        captured["item"] = item

    with patch.object(repo, "_put_once", side_effect=fake_put_once):
        repo.put_disposal_record(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            disposal_id=_DISPOSAL_ID,
            evidence_class="raw_evidence",
            disposal_mechanism="DYNAMODB_TTL",
            disposed_identity_ref=f"CLIENT#{_CLIENT_ID}#AUDIT#{_AUDIT_ID}#RUN#run1",
            disposed_at="2026-07-18T00:00:00.000Z",
            recorded_at="2026-07-18T00:05:00.000Z",
        )

    item = captured["item"]
    assert item["PK"] == f"CLIENT#{_CLIENT_ID}"
    assert item["SK"] == f"AUDIT#{_AUDIT_ID}#DISPOSAL#{_DISPOSAL_ID}"
    assert item["record_type"] == "disposal_record"
    assert item["disposal_mechanism"] == "DYNAMODB_TTL"
    assert item["evidence_class"] == "raw_evidence"
    assert item["source_created_at"] is None
    assert item["custody_period_days_applied"] is None
    # Non-Negotiable Invariant 1: a DisposalRecord must never carry ttl_disposal_at.
    assert "ttl_disposal_at" not in item


def test_put_disposal_record_with_optional_fields():
    repo = _make_repo()
    captured = {}

    def fake_put_once(item):
        captured["item"] = item

    with patch.object(repo, "_put_once", side_effect=fake_put_once):
        repo.put_disposal_record(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            disposal_id=_DISPOSAL_ID,
            evidence_class="report",
            disposal_mechanism="S3_LIFECYCLE_EXPIRATION",
            disposed_identity_ref="reports/client1/audit1/artifact.json",
            disposed_at="2026-07-18T00:00:00.000Z",
            recorded_at="2026-07-18T00:05:00.000Z",
            source_created_at="2026-01-01T00:00:00.000Z",
            custody_period_days_applied=90,
        )

    item = captured["item"]
    assert item["source_created_at"] == "2026-01-01T00:00:00.000Z"
    assert item["custody_period_days_applied"] == 90


def test_put_disposal_record_asserts_disposal_sk():
    """put_disposal_record must not raise AssertionError for a valid call."""
    repo = _make_repo()
    with patch.object(repo, "_put_once"):
        repo.put_disposal_record(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            disposal_id=_DISPOSAL_ID,
            evidence_class="raw_evidence",
            disposal_mechanism="DYNAMODB_TTL",
            disposed_identity_ref=f"CLIENT#{_CLIENT_ID}#AUDIT#{_AUDIT_ID}#RUN#run1",
            disposed_at="2026-07-18T00:00:00.000Z",
            recorded_at="2026-07-18T00:05:00.000Z",
        )


def test_put_disposal_record_conditional_write_error_on_duplicate():
    """Duplicate disposal_id (redelivery) must surface as ConditionalWriteError."""
    from botocore.exceptions import ClientError

    from release_confidence_platform.evidence_retention.disposal_repository import (
        ConditionalWriteError,
    )

    repo = _make_repo()

    def fake_call(method_name, **kwargs):
        raise ClientError(
            {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
            "PutItem",
        )

    with patch.object(repo, "_call", side_effect=fake_call):
        with pytest.raises(ConditionalWriteError):
            repo.put_disposal_record(
                client_id=_CLIENT_ID,
                audit_id=_AUDIT_ID,
                disposal_id=_DISPOSAL_ID,
                evidence_class="raw_evidence",
                disposal_mechanism="DYNAMODB_TTL",
                disposed_identity_ref=f"CLIENT#{_CLIENT_ID}#AUDIT#{_AUDIT_ID}#RUN#run1",
                disposed_at="2026-07-18T00:00:00.000Z",
                recorded_at="2026-07-18T00:05:00.000Z",
            )
