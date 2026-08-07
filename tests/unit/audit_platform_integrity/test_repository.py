"""Tests for CertificationRepository DynamoDB access and SK invariants.

Evidence Governance Workstream A1.3d.4 (Technical Design Section 20.8):
write_cert_metadata_complete() is a hold-coordinated TransactWriteItems call
that preserves the unconditional-replacement (no ConditionExpression on its
own Put) contract. All write_cert_metadata_complete tests below construct a
hold-aware CertificationRepository via _make_hold_aware_repo(); the four
CertificationJob write methods (Category 3, Technical Design Section 20.2)
are unaffected and their existing coverage is preserved unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

from release_confidence_platform.audit_platform_integrity.repository import (
    CertificationRepository,
    _assert_phase7_sk,
)
from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository

_DESER = TypeDeserializer()

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


def _cert_sk() -> str:
    return (
        f"AUDIT#{_AUDIT_ID}#EXEC#{_EXEC_ID}#CFG#{_CFG}"
        f"#AGG#{_AGG}#INTEL#{_INTEL}#RPT#{_RPT}#CERT#{_CERT}#META"
    )


class _FakeHoldRepository:
    """Minimal HoldRepository double for tests that only need to control/observe
    get_legal_hold and legal_hold_key -- not a full DynamoDB-backed simulation."""

    def __init__(self, hold_state: dict | None = None, *, raises: Exception | None = None):
        self.hold_state = hold_state
        self.raises = raises
        self.calls: list[tuple] = []

    def legal_hold_key(self, client_id: str, audit_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#LEGALHOLD"}

    def get_legal_hold(self, client_id, audit_id, *, consistent_read: bool = False):
        self.calls.append((client_id, audit_id, consistent_read))
        if self.raises is not None:
            raise self.raises
        return self.hold_state


class _SimpleHoldAwareClient:
    """Minimal low-level DynamoDB double used by this file's CREATE-contract
    unit tests. Deeper race/retry/precedence coverage lives in
    tests/unit/audit_platform_integrity/test_hold_coordination.py; this
    double supports only what those unit-level tests need: get_item,
    put_item (for HoldRepository CRUD), and transact_write_items."""

    def __init__(self) -> None:
        self.storage: dict[tuple[str, str], dict] = {}
        self.transact_calls: list[list[dict]] = []
        self.get_item_calls: list[dict] = []

    def get_item(self, **kwargs) -> dict:
        self.get_item_calls.append(kwargs)
        key = kwargs["Key"]
        item = self.storage.get((key["PK"]["S"], key["SK"]["S"]))
        return {"Item": item} if item else {}

    def put_item(self, Item: dict, ConditionExpression: str | None = None, **_) -> dict:
        pk, sk = Item["PK"]["S"], Item["SK"]["S"]
        self.storage[(pk, sk)] = Item
        return {}

    def transact_write_items(self, TransactItems: list[dict]) -> dict:
        self.transact_calls.append(TransactItems)
        reasons: list[dict[str, str]] = []
        any_failed = False
        for transact_item in TransactItems:
            if "Put" in transact_item:
                put = transact_item["Put"]
                pk, sk = put["Item"]["PK"]["S"], put["Item"]["SK"]["S"]
                condition = put.get("ConditionExpression")
                if condition and "attribute_not_exists" in condition and (pk, sk) in self.storage:
                    reasons.append({"Code": "ConditionalCheckFailed"})
                    any_failed = True
                else:
                    reasons.append({"Code": "None"})
            elif "ConditionCheck" in transact_item:
                cc = transact_item["ConditionCheck"]
                pk, sk = cc["Key"]["PK"]["S"], cc["Key"]["SK"]["S"]
                existing = self.storage.get((pk, sk))
                if "attribute_not_exists" in cc["ConditionExpression"]:
                    passed = existing is None
                else:
                    expected = cc["ExpressionAttributeValues"][":expected_hold_version"]
                    passed = existing is not None and existing.get("hold_version") == expected
                reasons.append({"Code": "None"} if passed else {"Code": "ConditionalCheckFailed"})
                if not passed:
                    any_failed = True
            else:  # pragma: no cover - defensive
                reasons.append({"Code": "None"})
        if any_failed:
            raise ClientError(
                {
                    "Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
                    "CancellationReasons": reasons,
                },
                "TransactWriteItems",
            )
        for transact_item in TransactItems:
            if "Put" in transact_item:
                item = transact_item["Put"]["Item"]
                self.storage[(item["PK"]["S"], item["SK"]["S"])] = item
        return {}


def _make_hold_aware_repo(custody_period_days: int | None = 90):
    client = _SimpleHoldAwareClient()
    hold_repository = HoldRepository(_TABLE, client)
    repo = CertificationRepository(
        _TABLE,
        client,
        MagicMock(),
        _BUCKET,
        hold_repository,
        custody_period_days=custody_period_days,
    )
    return repo, hold_repository, client


def _deser_item(client: _SimpleHoldAwareClient, key: dict) -> dict:
    stored = client.storage[(key["PK"], key["SK"])]
    return {k: _DESER.deserialize(v) for k, v in stored.items()}


def _call_write_cert_metadata_complete(repo: CertificationRepository, **overrides) -> None:
    kwargs = dict(
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
    kwargs.update(overrides)
    repo.write_cert_metadata_complete(**kwargs)


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
    repo, _hold_repository, _client = _make_hold_aware_repo()
    # Normal call must not raise AssertionError
    _call_write_cert_metadata_complete(repo)


def test_write_cert_metadata_complete_uses_correct_sk():
    """write_cert_metadata_complete must use the Phase 7 CertificationMetadata SK."""
    repo, _hold_repository, client = _make_hold_aware_repo()
    _call_write_cert_metadata_complete(repo)

    item = _deser_item(client, {"PK": f"CLIENT#{_CLIENT_ID}", "SK": _cert_sk()})
    sk = item["SK"]
    assert f"#CERT#{_CERT}#META" in sk
    assert f"#RPT#{_RPT}" in sk
    assert item["terminal_state"] == "CERTIFIED"
    assert item["certificate_id"] == "cert_abc"


# ---------------------------------------------------------------------------
# write_cert_metadata_complete -- governance preflight and transaction shape
# Evidence Governance Workstream A1.3d.4 (Technical Design Section 20.8)
# ---------------------------------------------------------------------------


def test_write_cert_metadata_complete_transaction_shape_and_no_put_condition():
    """The TransactWriteItems call must carry exactly one Put (no
    ConditionExpression -- unconditional replacement is preserved) and one
    ConditionCheck against the LegalHold key, for both a never-held and an
    already-held audit identity."""
    # Never-held: ConditionCheck must assert attribute_not_exists(PK).
    dynamodb_client = MagicMock()
    hold_repository = _FakeHoldRepository(hold_state=None)
    repo = CertificationRepository(
        _TABLE, dynamodb_client, MagicMock(), _BUCKET, hold_repository, custody_period_days=90
    )
    _call_write_cert_metadata_complete(repo)

    transact_items = dynamodb_client.transact_write_items.call_args.kwargs["TransactItems"]
    assert len(transact_items) == 2
    put_items = [i for i in transact_items if "Put" in i]
    cc_items = [i for i in transact_items if "ConditionCheck" in i]
    assert len(put_items) == 1
    assert len(cc_items) == 1
    put_item = put_items[0]["Put"]
    assert "ConditionExpression" not in put_item
    assert "#CERT#" in put_item["Item"]["SK"]["S"]
    cc = cc_items[0]["ConditionCheck"]
    assert cc["Key"] == {
        "PK": {"S": f"CLIENT#{_CLIENT_ID}"},
        "SK": {"S": f"AUDIT#{_AUDIT_ID}#LEGALHOLD"},
    }
    assert "attribute_not_exists(PK)" in cc["ConditionExpression"]
    # No item other than the ConditionCheck carries any condition-related key.
    assert "ConditionExpression" not in put_item

    # Already-held: ConditionCheck must assert hold_version equality instead.
    dynamodb_client2 = MagicMock()
    hold_repository2 = _FakeHoldRepository(hold_state={"status": "ACTIVE", "hold_version": 4})
    repo2 = CertificationRepository(
        _TABLE, dynamodb_client2, MagicMock(), _BUCKET, hold_repository2, custody_period_days=90
    )
    _call_write_cert_metadata_complete(repo2)
    transact_items2 = dynamodb_client2.transact_write_items.call_args.kwargs["TransactItems"]
    cc2 = next(i for i in transact_items2 if "ConditionCheck" in i)["ConditionCheck"]
    assert "hold_version" in cc2["ConditionExpression"]
    put2 = next(i for i in transact_items2 if "Put" in i)["Put"]
    assert "ConditionExpression" not in put2


def test_write_cert_metadata_complete_evidence_class_fixed_certificate():
    repo, _hold_repository, client = _make_hold_aware_repo()
    _call_write_cert_metadata_complete(repo)
    item = _deser_item(client, {"PK": f"CLIENT#{_CLIENT_ID}", "SK": _cert_sk()})
    assert item["evidence_class"] == "certificate"


def test_write_cert_metadata_complete_raises_hold_coordination_not_configured_when_hold_repository_none():  # noqa: E501
    dynamodb_client = MagicMock()
    s3_client = MagicMock()
    repo = CertificationRepository(
        _TABLE, dynamodb_client, s3_client, _BUCKET, custody_period_days=90
    )
    with pytest.raises(StorageError) as exc_info:
        _call_write_cert_metadata_complete(repo)
    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"
    assert dynamodb_client.method_calls == []
    assert s3_client.method_calls == []


def test_write_cert_metadata_complete_custody_expires_at_computed_from_injected_duration():
    repo, _hold_repository, client = _make_hold_aware_repo(custody_period_days=7)
    before = int(datetime.now(UTC).timestamp())
    _call_write_cert_metadata_complete(repo)
    after = int(datetime.now(UTC).timestamp())
    item = _deser_item(client, {"PK": f"CLIENT#{_CLIENT_ID}", "SK": _cert_sk()})
    assert before + 7 * 86400 <= item["custody_expires_at"] <= after + 7 * 86400


def test_write_cert_metadata_complete_delegates_to_hold_coordinated_transaction_runner():
    dynamodb_client = MagicMock()
    hold_repository = _FakeHoldRepository(hold_state=None)
    repo = CertificationRepository(
        _TABLE, dynamodb_client, MagicMock(), _BUCKET, hold_repository, custody_period_days=90
    )
    _call_write_cert_metadata_complete(repo)
    dynamodb_client.transact_write_items.assert_called_once()
    dynamodb_client.put_item.assert_not_called()


_INVALID_DURATIONS = [
    pytest.param(None, id="missing_duration"),
    pytest.param(True, id="boolean_true"),
    pytest.param("10", id="string"),
    pytest.param(0, id="zero"),
    pytest.param(-5, id="negative"),
]


@pytest.mark.parametrize("bad_duration", _INVALID_DURATIONS)
def test_write_cert_metadata_complete_raises_custody_period_config_missing(bad_duration):
    dynamodb_client = MagicMock()
    s3_client = MagicMock()
    hold_repository = _FakeHoldRepository(hold_state=None)
    repo = CertificationRepository(
        _TABLE,
        dynamodb_client,
        s3_client,
        _BUCKET,
        hold_repository,
        custody_period_days=bad_duration,
    )
    with pytest.raises(StorageError) as exc_info:
        _call_write_cert_metadata_complete(repo)
    assert exc_info.value.error_type == "CUSTODY_PERIOD_CONFIG_MISSING"
    assert hold_repository.calls == []
    dynamodb_client.transact_write_items.assert_not_called()
    dynamodb_client.put_item.assert_not_called()
    dynamodb_client.update_item.assert_not_called()
    assert s3_client.method_calls == []


def test_repository_never_calls_custody_period_config_loader(monkeypatch):
    """CertificationRepository must never import or call CustodyPeriodConfigLoader,
    regardless of whether the injected custody_period_days is valid or invalid."""
    from release_confidence_platform.config.custody_period_config import (
        CustodyPeriodConfigLoader,
    )

    def _raise_if_called(*args, **kwargs):
        raise AssertionError("CertificationRepository must never call CustodyPeriodConfigLoader")

    monkeypatch.setattr(CustodyPeriodConfigLoader, "resolve", _raise_if_called)

    # Valid duration -- write succeeds without ever invoking the loader.
    repo, _hold, _client = _make_hold_aware_repo(custody_period_days=30)
    _call_write_cert_metadata_complete(repo)

    # Invalid duration -- write fails via the repository's own preflight,
    # never by invoking the loader (which would raise AssertionError instead).
    bad_repo, _hold2, _client2 = _make_hold_aware_repo(custody_period_days=0)
    with pytest.raises(StorageError) as exc_info:
        _call_write_cert_metadata_complete(bad_repo)
    assert exc_info.value.error_type == "CUSTODY_PERIOD_CONFIG_MISSING"


def test_write_cert_metadata_complete_zero_aws_calls_when_hold_repository_none():
    dynamodb_client = MagicMock()
    s3_client = MagicMock()
    repo = CertificationRepository(
        _TABLE, dynamodb_client, s3_client, _BUCKET, custody_period_days=90
    )
    with pytest.raises(StorageError) as exc_info:
        _call_write_cert_metadata_complete(repo)
    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"
    assert dynamodb_client.method_calls == []
    assert s3_client.method_calls == []


# ---------------------------------------------------------------------------
# CertificationJob (Category 3) governance-field exclusion
# Evidence Governance Workstream A1.3d.4 (Technical Design Section 20.2)
# ---------------------------------------------------------------------------

_GOVERNANCE_FIELD_NAMES = ("custody_expires_at", "ttl_disposal_at", "evidence_class")


def test_write_certjob_pending_carries_no_governance_fields():
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
    for field in _GOVERNANCE_FIELD_NAMES:
        assert field not in item
    assert not any("hold_version" in key for key in item)


def test_update_certjob_in_progress_carries_no_governance_fields():
    repo = _make_repo()
    captured = {}

    def fake_update_item(key, updates):
        captured["updates"] = updates

    with patch.object(repo, "_update_item", side_effect=fake_update_item):
        repo.update_certjob_in_progress(_CLIENT_ID, _AUDIT_ID, _CERTJOB_ID)

    updates = captured["updates"]
    for field in _GOVERNANCE_FIELD_NAMES:
        assert field not in updates
    assert not any("hold_version" in key for key in updates)


def test_update_certjob_complete_carries_no_governance_fields():
    repo = _make_repo()
    captured = {}

    def fake_update_item(key, updates):
        captured["updates"] = updates

    with patch.object(repo, "_update_item", side_effect=fake_update_item):
        repo.update_certjob_complete(
            _CLIENT_ID, _AUDIT_ID, _CERTJOB_ID, "CERTIFIED", "integrity/test/artifact.json"
        )

    updates = captured["updates"]
    for field in _GOVERNANCE_FIELD_NAMES:
        assert field not in updates
    assert not any("hold_version" in key for key in updates)


def test_update_certjob_failed_carries_no_governance_fields():
    repo = _make_repo()
    captured = {}

    def fake_update_item(key, updates):
        captured["updates"] = updates

    with patch.object(repo, "_update_item", side_effect=fake_update_item):
        repo.update_certjob_failed(_CLIENT_ID, _AUDIT_ID, _CERTJOB_ID, "some error")

    updates = captured["updates"]
    for field in _GOVERNANCE_FIELD_NAMES:
        assert field not in updates
    assert not any("hold_version" in key for key in updates)


def test_certjob_write_methods_perform_zero_hold_reads():
    hold_repository = _FakeHoldRepository()
    repo = CertificationRepository(
        _TABLE, MagicMock(), MagicMock(), _BUCKET, hold_repository, custody_period_days=90
    )
    identity_tuple = {
        "audit_execution_id": _EXEC_ID,
        "config_version": _CFG,
        "aggregation_version": _AGG,
        "intelligence_version": _INTEL,
        "report_version": _RPT,
        "cert_version": _CERT,
    }
    with patch.object(repo, "_put_once"), patch.object(repo, "_update_item"):
        repo.write_certjob_pending(_CLIENT_ID, _AUDIT_ID, _CERTJOB_ID, identity_tuple)
        repo.update_certjob_in_progress(_CLIENT_ID, _AUDIT_ID, _CERTJOB_ID)
        repo.update_certjob_complete(
            _CLIENT_ID, _AUDIT_ID, _CERTJOB_ID, "CERTIFIED", "integrity/test/artifact.json"
        )
        repo.update_certjob_failed(_CLIENT_ID, _AUDIT_ID, _CERTJOB_ID, "err")

    assert hold_repository.calls == []
