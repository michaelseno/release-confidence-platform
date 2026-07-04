"""Tests for ReportRepository DynamoDB access and SK invariants."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from release_confidence_platform.deterministic_reporting.repository import (
    ReportRepository,
    _assert_phase6_sk,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TABLE = "test-table"
_CLIENT_ID = "client1"
_AUDIT_ID = "audit1"
_EXEC_ID = "exec1"
_CFG = "cfg_v1"
_AGG = "agg_v1"
_INTEL = "intel_v1"
_RPT = "rpt_v1"
_RPTJOB_ID = "rptjob_abc"


def _make_repo() -> ReportRepository:
    return ReportRepository(_TABLE, MagicMock())


# ---------------------------------------------------------------------------
# Key format tests (no DynamoDB needed)
# ---------------------------------------------------------------------------


def test_report_job_keys_format():
    repo = _make_repo()
    keys = repo.report_job_keys(_CLIENT_ID, _AUDIT_ID, _RPTJOB_ID)
    assert keys["PK"] == "CLIENT#client1"
    assert keys["SK"] == "AUDIT#audit1#RPTJOB#rptjob_abc"
    assert "#RPTJOB#" in keys["SK"]


def test_report_metadata_keys_format():
    repo = _make_repo()
    keys = repo.report_metadata_keys(
        _CLIENT_ID, _AUDIT_ID, _EXEC_ID, _CFG, _AGG, _INTEL, _RPT
    )
    assert keys["PK"] == "CLIENT#client1"
    sk = keys["SK"]
    assert "AUDIT#audit1" in sk
    assert "#EXEC#exec1" in sk
    assert "#CFG#cfg_v1" in sk
    assert "#AGG#agg_v1" in sk
    assert "#INTEL#intel_v1" in sk
    assert "#RPT#rpt_v1" in sk
    assert sk.endswith("#META")


# ---------------------------------------------------------------------------
# get_intelligence_metadata (Phase 5 read-only gate)
# ---------------------------------------------------------------------------


def test_get_intelligence_metadata_returns_none_when_not_found():
    repo = _make_repo()
    with patch.object(repo, "_get_item", return_value=None):
        result = repo.get_intelligence_metadata(
            _CLIENT_ID, _AUDIT_ID, _EXEC_ID, _CFG, _AGG, _INTEL
        )
    assert result is None


def test_get_intelligence_metadata_uses_correct_sk():
    repo = _make_repo()
    captured = {}

    def fake_get_item(key):
        captured["key"] = key
        return None

    with patch.object(repo, "_get_item", side_effect=fake_get_item):
        repo.get_intelligence_metadata(_CLIENT_ID, _AUDIT_ID, _EXEC_ID, _CFG, _AGG, _INTEL)

    sk = captured["key"]["SK"]
    # Must reference Phase 5 IntelligenceMetadata SK pattern (no #RPT# or #RPTJOB#)
    assert f"#INTEL#{_INTEL}#META" in sk
    assert "#RPT#" not in sk
    assert "#RPTJOB#" not in sk


# ---------------------------------------------------------------------------
# get_report_metadata (Phase 6 idempotency read)
# ---------------------------------------------------------------------------


def test_get_report_metadata_returns_none_when_not_found():
    repo = _make_repo()
    with patch.object(repo, "_get_item", return_value=None):
        result = repo.get_report_metadata(
            _CLIENT_ID, _AUDIT_ID, _EXEC_ID, _CFG, _AGG, _INTEL, _RPT
        )
    assert result is None


def test_get_report_metadata_uses_correct_sk():
    repo = _make_repo()
    captured = {}

    def fake_get_item(key):
        captured["key"] = key
        return None

    with patch.object(repo, "_get_item", side_effect=fake_get_item):
        repo.get_report_metadata(
            _CLIENT_ID, _AUDIT_ID, _EXEC_ID, _CFG, _AGG, _INTEL, _RPT
        )

    sk = captured["key"]["SK"]
    assert f"#RPT#{_RPT}#META" in sk
    assert "#INTEL#" in sk


# ---------------------------------------------------------------------------
# put_report_job_once
# ---------------------------------------------------------------------------


def test_put_report_job_once_calls_put_once():
    repo = _make_repo()
    valid_item = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#RPTJOB#rptjob_abc",
        "record_type": "report_job",
        "status": "PENDING",
    }
    with patch.object(repo, "_put_once") as mock_put:
        repo.put_report_job_once(valid_item)
        mock_put.assert_called_once_with(valid_item)


def test_put_report_job_once_asserts_phase6_sk():
    repo = _make_repo()
    bad_item = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#INTJOB#intjob_bad",
    }
    with pytest.raises(AssertionError):
        repo.put_report_job_once(bad_item)


# ---------------------------------------------------------------------------
# put_report_metadata_once
# ---------------------------------------------------------------------------


def test_put_report_metadata_once_calls_put_once():
    repo = _make_repo()
    valid_item = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#RPT#rpt_v1#META",
        "record_type": "report_metadata",
        "status": "PENDING",
    }
    with patch.object(repo, "_put_once") as mock_put:
        repo.put_report_metadata_once(valid_item)
        mock_put.assert_called_once_with(valid_item)


def test_put_report_metadata_once_asserts_phase6_sk():
    repo = _make_repo()
    bad_item = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#INTJOB#bad",
    }
    with pytest.raises(AssertionError):
        repo.put_report_metadata_once(bad_item)


# ---------------------------------------------------------------------------
# update_report_job
# ---------------------------------------------------------------------------


def test_update_report_job_calls_update_item():
    repo = _make_repo()
    key = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#RPTJOB#rptjob_abc",
    }
    updates = {"status": "COMPLETE", "completed_at": "2026-07-04T12:00:00Z"}
    with patch.object(repo, "_update_item") as mock_update:
        repo.update_report_job(key, updates)
        mock_update.assert_called_once_with(key, updates)


def test_update_report_job_asserts_phase6_sk():
    repo = _make_repo()
    bad_key = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#LINEAGE#something",
    }
    with pytest.raises(AssertionError):
        repo.update_report_job(bad_key, {"status": "COMPLETE"})


# ---------------------------------------------------------------------------
# update_report_metadata_fields
# ---------------------------------------------------------------------------


def test_update_report_metadata_fields_calls_update_item():
    repo = _make_repo()
    key = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#RPT#rpt_v1#META",
    }
    updates = {"status": "COMPLETE", "s3_artifact_ref": "reports/..."}
    with patch.object(repo, "_update_item") as mock_update:
        repo.update_report_metadata_fields(key, updates)
        mock_update.assert_called_once_with(key, updates)


# ---------------------------------------------------------------------------
# _assert_phase6_sk direct tests
# ---------------------------------------------------------------------------


def test_assert_phase6_sk_rejects_intjob_sk():
    bad_sk = "AUDIT#audit1#INTJOB#intjob_bad"
    with pytest.raises(AssertionError) as exc_info:
        _assert_phase6_sk(bad_sk)
    assert "prohibited SK namespace" in str(exc_info.value)


def test_assert_phase6_sk_rejects_lineage_sk():
    bad_sk = "AUDIT#audit1#LINEAGE#lineage_bad"
    with pytest.raises(AssertionError):
        _assert_phase6_sk(bad_sk)


def test_assert_phase6_sk_rejects_sk_with_no_phase6_marker():
    bad_sk = "AUDIT#audit1#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#META"
    with pytest.raises(AssertionError):
        _assert_phase6_sk(bad_sk)


def test_assert_phase6_sk_accepts_rptjob_sk():
    sk = "AUDIT#audit1#RPTJOB#rptjob_abc"
    # Must not raise
    _assert_phase6_sk(sk)


def test_assert_phase6_sk_accepts_rpt_sk():
    sk = "AUDIT#audit1#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#RPT#rpt_v1#META"
    # Must not raise
    _assert_phase6_sk(sk)
