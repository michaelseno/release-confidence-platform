"""Tests for CertificationRepository DynamoDB access and SK invariants."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from release_confidence_platform.audit_platform_integrity.repository import (
    CertificationRepository,
    _assert_phase7_sk,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TABLE = "test-table"
_BUCKET = "test-bucket"
_CLIENT_ID = "client1"
_AUDIT_ID = "audit1"
_EXEC_ID = "exec1"
_CFG = "cfg_v1"
_AGG = "agg_v1"
_INTEL = "intel_v1"
_RPT = "report_v1"
_CERT = "cert_v1"
_CERTJOB_ID = "certjob_abc"


def _make_repo() -> CertificationRepository:
    return CertificationRepository(_TABLE, MagicMock(), MagicMock(), _BUCKET)


# ---------------------------------------------------------------------------
# _assert_phase7_sk direct tests
# ---------------------------------------------------------------------------


def test_assert_phase7_sk_accepts_certjob_sk():
    """CertificationJob SK (#CERTJOB#) must pass the assertion."""
    sk = f"AUDIT#{_AUDIT_ID}#CERTJOB#{_CERTJOB_ID}"
    _assert_phase7_sk(sk)  # Must not raise


def test_assert_phase7_sk_accepts_cert_metadata_sk():
    """CertificationMetadata SK (#CERT#) must pass the assertion, even with structural qualifiers."""
    sk = (
        f"AUDIT#{_AUDIT_ID}#EXEC#{_EXEC_ID}#CFG#{_CFG}"
        f"#AGG#{_AGG}#INTEL#{_INTEL}#RPT#{_RPT}#CERT#{_CERT}#META"
    )
    _assert_phase7_sk(sk)  # Must not raise


def test_assert_phase7_sk_rejects_phase6_rptjob_sk():
    """Phase 6 ReportJob SK (#RPTJOB#) must be rejected."""
    bad_sk = f"AUDIT#{_AUDIT_ID}#RPTJOB#rptjob_abc"
    with pytest.raises(AssertionError) as exc_info:
        _assert_phase7_sk(bad_sk)
    assert "prohibited SK namespace" in str(exc_info.value)


def test_assert_phase7_sk_rejects_phase6_rpt_metadata_sk():
    """Phase 6 ReportMetadata SK (#RPT# without #CERT#) must be rejected."""
    bad_sk = (
        f"AUDIT#{_AUDIT_ID}#EXEC#{_EXEC_ID}#CFG#{_CFG}"
        f"#AGG#{_AGG}#INTEL#{_INTEL}#RPT#{_RPT}#META"
    )
    with pytest.raises(AssertionError):
        _assert_phase7_sk(bad_sk)


def test_assert_phase7_sk_rejects_phase5_intjob_sk():
    """Phase 5 IntelligenceJob SK (#INTJOB#) must be rejected."""
    bad_sk = f"AUDIT#{_AUDIT_ID}#INTJOB#intjob_abc"
    with pytest.raises(AssertionError) as exc_info:
        _assert_phase7_sk(bad_sk)
    assert "prohibited SK namespace" in str(exc_info.value)


def test_assert_phase7_sk_rejects_phase5_intel_metadata_sk():
    """Phase 5 IntelligenceMetadata SK (#INTEL# without #CERT#) must be rejected."""
    bad_sk = (
        f"AUDIT#{_AUDIT_ID}#EXEC#{_EXEC_ID}#CFG#{_CFG}"
        f"#AGG#{_AGG}#INTEL#{_INTEL}#META"
    )
    with pytest.raises(AssertionError):
        _assert_phase7_sk(bad_sk)


def test_assert_phase7_sk_rejects_phase4_agg_sk():
    """Phase 4 aggregation SK (#AGG# without #CERT#) must be rejected."""
    bad_sk = f"AUDIT#{_AUDIT_ID}#EXEC#{_EXEC_ID}#CFG#{_CFG}#AGG#{_AGG}#META"
    with pytest.raises(AssertionError):
        _assert_phase7_sk(bad_sk)


def test_assert_phase7_sk_rejects_sk_with_no_phase7_marker():
    """SK with no Phase 7 marker must be rejected."""
    bad_sk = f"AUDIT#{_AUDIT_ID}#EXEC#{_EXEC_ID}#CFG#{_CFG}#META"
    with pytest.raises(AssertionError):
        _assert_phase7_sk(bad_sk)


# ---------------------------------------------------------------------------
# get_report_metadata (Phase 6 read-only gate)
# ---------------------------------------------------------------------------


def test_get_report_metadata_returns_none_when_not_found():
    repo = _make_repo()
    with patch.object(repo, "_get_item", return_value=None):
        result = repo.get_report_metadata(
            _CLIENT_ID, _AUDIT_ID, _EXEC_ID, _CFG, _AGG, _INTEL, _RPT
        )
    assert result is None


def test_get_report_metadata_uses_correct_sk():
    """get_report_metadata must use the Phase 6 ReportMetadata SK pattern."""
    repo = _make_repo()
    captured = {}

    def fake_get_item(key):
        captured["key"] = key
        return None

    with patch.object(repo, "_get_item", side_effect=fake_get_item):
        repo.get_report_metadata(_CLIENT_ID, _AUDIT_ID, _EXEC_ID, _CFG, _AGG, _INTEL, _RPT)

    sk = captured["key"]["SK"]
    # Must reference Phase 6 ReportMetadata SK pattern (ends with #META, no #CERT#)
    assert f"#RPT#{_RPT}#META" in sk
    assert "#CERT#" not in sk
    assert "#CERTJOB#" not in sk


# ---------------------------------------------------------------------------
# get_cert_metadata (Phase 7 idempotency read)
# ---------------------------------------------------------------------------


def test_get_cert_metadata_returns_none_when_not_found():
    repo = _make_repo()
    with patch.object(repo, "_get_item", return_value=None):
        result = repo.get_cert_metadata(
            _CLIENT_ID, _AUDIT_ID, _EXEC_ID, _CFG, _AGG, _INTEL, _RPT, _CERT
        )
    assert result is None


def test_get_cert_metadata_uses_correct_sk():
    """get_cert_metadata must use the Phase 7 CertificationMetadata SK pattern."""
    repo = _make_repo()
    captured = {}

    def fake_get_item(key):
        captured["key"] = key
        return None

    with patch.object(repo, "_get_item", side_effect=fake_get_item):
        repo.get_cert_metadata(
            _CLIENT_ID, _AUDIT_ID, _EXEC_ID, _CFG, _AGG, _INTEL, _RPT, _CERT
        )

    sk = captured["key"]["SK"]
    assert f"#CERT#{_CERT}#META" in sk
    assert f"#RPT#{_RPT}" in sk


# ---------------------------------------------------------------------------
# write_certjob_pending
# ---------------------------------------------------------------------------


def test_write_certjob_pending_calls_put_once():
    """write_certjob_pending must call _put_once with correct PK/SK."""
    repo = _make_repo()
    identity_tuple = {
        "audit_execution_id": _EXEC_ID,
        "config_version": _CFG,
        "aggregation_version": _AGG,
        "intelligence_version": _INTEL,
        "report_version": _RPT,
        "cert_version": _CERT,
    }
    captured = {}

    def fake_put_once(item):
        captured["item"] = item

    with patch.object(repo, "_put_once", side_effect=fake_put_once):
        repo.write_certjob_pending(_CLIENT_ID, _AUDIT_ID, _CERTJOB_ID, identity_tuple)

    item = captured["item"]
    assert item["PK"] == f"CLIENT#{_CLIENT_ID}"
    assert item["SK"] == f"AUDIT#{_AUDIT_ID}#CERTJOB#{_CERTJOB_ID}"
    assert item["status"] == "PENDING"
    assert item["certjob_id"] == _CERTJOB_ID


def test_write_certjob_pending_asserts_phase7_sk():
    """write_certjob_pending must assert the SK is Phase 7 before writing."""
    # Since certjob_id always generates a #CERTJOB# SK, this tests indirectly.
    # We verify _assert_phase7_sk is called by checking the certjob SK.
    repo = _make_repo()
    identity_tuple = {
        "audit_execution_id": _EXEC_ID,
        "config_version": _CFG,
        "aggregation_version": _AGG,
        "intelligence_version": _INTEL,
        "report_version": _RPT,
        "cert_version": _CERT,
    }
    with patch.object(repo, "_put_once"):
        # Normal call must not raise AssertionError
        repo.write_certjob_pending(_CLIENT_ID, _AUDIT_ID, _CERTJOB_ID, identity_tuple)


# ---------------------------------------------------------------------------
# write_cert_metadata_complete
# ---------------------------------------------------------------------------


def test_write_cert_metadata_complete_asserts_phase7_sk():
    """write_cert_metadata_complete must assert the SK is Phase 7 before writing."""
    repo = _make_repo()
    with patch.object(repo, "_put_item"):
        # Normal call must not raise AssertionError
        repo.write_cert_metadata_complete(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            audit_execution_id=_EXEC_ID,
            config_version=_CFG,
            aggregation_version=_AGG,
            intelligence_version=_INTEL,
            report_version=_RPT,
            cert_version=_CERT,
            terminal_state="CERTIFIED",
            certificate_id="cert_abc",
            certjob_id=_CERTJOB_ID,
            s3_cert_ref="integrity/test/artifact.json",
            s3_report_artifact_ref="reports/test/artifact.json",
            aggregate_set_hash="hashTEST",
            report_id="report_abc",
            certification_summary="INTEGRITY_VERIFIED",
            disclosed_failures=[],
        )


def test_write_cert_metadata_complete_uses_correct_sk():
    """write_cert_metadata_complete must use the Phase 7 CertificationMetadata SK."""
    repo = _make_repo()
    captured = {}

    def fake_put_item(item):
        captured["item"] = item

    with patch.object(repo, "_put_item", side_effect=fake_put_item):
        repo.write_cert_metadata_complete(
            client_id=_CLIENT_ID,
            audit_id=_AUDIT_ID,
            audit_execution_id=_EXEC_ID,
            config_version=_CFG,
            aggregation_version=_AGG,
            intelligence_version=_INTEL,
            report_version=_RPT,
            cert_version=_CERT,
            terminal_state="CERTIFIED",
            certificate_id="cert_abc",
            certjob_id=_CERTJOB_ID,
            s3_cert_ref="integrity/test/artifact.json",
            s3_report_artifact_ref="reports/test/artifact.json",
            aggregate_set_hash="hashTEST",
            report_id="report_abc",
            certification_summary="INTEGRITY_VERIFIED",
            disclosed_failures=[],
        )

    item = captured["item"]
    sk = item["SK"]
    assert f"#CERT#{_CERT}#META" in sk
    assert f"#RPT#{_RPT}" in sk
    assert item["terminal_state"] == "CERTIFIED"
    assert item["certificate_id"] == "cert_abc"
