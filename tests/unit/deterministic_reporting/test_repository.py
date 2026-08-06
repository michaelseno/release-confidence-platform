"""Tests for ReportRepository DynamoDB access and SK invariants."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.deterministic_reporting.repository import (
    ConditionalWriteError,
    ReportRepository,
    _assert_phase6_sk,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository

_DESER = TypeDeserializer()

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


class _SimpleHoldAwareClient:
    """Minimal low-level DynamoDB double used by this file's CREATE-contract
    unit tests. Deeper race/retry/precedence coverage lives in
    tests/unit/deterministic_reporting/test_hold_coordination.py; this
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
    repo = ReportRepository(
        _TABLE, client, hold_repository, custody_period_days=custody_period_days
    )
    return repo, hold_repository, client


def _valid_report_metadata_item(**overrides) -> dict:
    item = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": (
            f"AUDIT#{_AUDIT_ID}#EXEC#{_EXEC_ID}#CFG#{_CFG}#AGG#{_AGG}"
            f"#INTEL#{_INTEL}#RPT#{_RPT}#META"
        ),
        "record_type": "report_metadata",
        "status": "PENDING",
    }
    item.update(overrides)
    return item


def _deser_item(client: _SimpleHoldAwareClient, key: dict) -> dict:
    stored = client.storage[(key["PK"], key["SK"])]
    return {k: _DESER.deserialize(v) for k, v in stored.items()}


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
# ReportRepository construction -- optional-default behavior
# ---------------------------------------------------------------------------


def test_constructor_defaults_hold_repository_and_custody_period_to_none():
    repo = ReportRepository(_TABLE, MagicMock())
    assert repo._hold_repository is None
    assert repo._custody_period_days is None


def test_constructor_accepts_positional_hold_repository_and_keyword_custody_period():
    client = MagicMock()
    hold_repository = HoldRepository(_TABLE, client)
    repo = ReportRepository(_TABLE, client, hold_repository, custody_period_days=90)
    assert repo._hold_repository is hold_repository
    assert repo._custody_period_days == 90


# ---------------------------------------------------------------------------
# put_report_metadata_once -- governance preflight
# ---------------------------------------------------------------------------

_INVALID_DURATIONS = [
    pytest.param(None, id="missing_duration"),
    pytest.param(True, id="boolean_true"),
    pytest.param(False, id="boolean_false"),
    pytest.param("30", id="string"),
    pytest.param(30.0, id="float"),
    pytest.param(0, id="zero"),
    pytest.param(-1, id="negative"),
]


def test_put_report_metadata_once_fails_closed_when_hold_repository_missing():
    client = _SimpleHoldAwareClient()
    repo = ReportRepository(_TABLE, client, custody_period_days=90)
    with pytest.raises(StorageError) as exc_info:
        repo.put_report_metadata_once(_valid_report_metadata_item())
    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"
    assert client.get_item_calls == []
    assert client.transact_calls == []


@pytest.mark.parametrize("bad_duration", _INVALID_DURATIONS)
def test_put_report_metadata_once_fails_closed_on_invalid_duration(bad_duration):
    client = _SimpleHoldAwareClient()
    hold_repository = HoldRepository(_TABLE, client)
    repo = ReportRepository(_TABLE, client, hold_repository, custody_period_days=bad_duration)
    with pytest.raises(StorageError) as exc_info:
        repo.put_report_metadata_once(_valid_report_metadata_item())
    assert exc_info.value.error_type == "CUSTODY_PERIOD_CONFIG_MISSING"
    assert client.get_item_calls == []
    assert client.transact_calls == []


# ---------------------------------------------------------------------------
# put_report_metadata_once -- CREATE contract
# ---------------------------------------------------------------------------


def test_put_report_metadata_once_asserts_phase6_sk():
    repo, hold_repository, client = _make_hold_aware_repo()
    bad_item = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#INTJOB#bad",
    }
    with pytest.raises(AssertionError):
        repo.put_report_metadata_once(bad_item)


def test_put_report_metadata_once_unheld_includes_ttl_disposal_at():
    repo, hold_repository, client = _make_hold_aware_repo()
    item = _valid_report_metadata_item()
    repo.put_report_metadata_once(item)
    persisted = _deser_item(client, item)
    assert persisted["evidence_class"] == "report"
    assert "ttl_disposal_at" in persisted
    assert "custody_expires_at" in persisted


def test_put_report_metadata_once_active_hold_omits_ttl_disposal_at():
    repo, hold_repository, client = _make_hold_aware_repo()
    hold_repository.upsert_hold(
        _CLIENT_ID, _AUDIT_ID, "ACTIVE", "hold1", 1, "COMPLETE",
        "2026-01-01T00:00:00Z", "tester", "reason", 1,
    )
    item = _valid_report_metadata_item()
    repo.put_report_metadata_once(item)
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" not in persisted


def test_put_report_metadata_once_released_hold_includes_ttl_disposal_at():
    repo, hold_repository, client = _make_hold_aware_repo()
    hold_repository.upsert_hold(
        _CLIENT_ID, _AUDIT_ID, "ACTIVE", "hold1", 1, "COMPLETE",
        "2026-01-01T00:00:00Z", "tester", "reason", 1,
    )
    hold_repository.upsert_hold(
        _CLIENT_ID, _AUDIT_ID, "RELEASED", "hold1", 2, "COMPLETE",
        "2026-01-01T00:00:00Z", "tester", "reason", 1,
        released_at="2026-01-02T00:00:00Z", released_by="tester",
    )
    item = _valid_report_metadata_item()
    repo.put_report_metadata_once(item)
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" in persisted


def test_put_report_metadata_once_malformed_identity_zero_hold_reads():
    repo, hold_repository, client = _make_hold_aware_repo()
    bad_item = {
        "PK": "NOT-A-CLIENT-KEY",
        "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#RPT#rpt_v1#META",
        "status": "PENDING",
    }
    with pytest.raises(StorageError) as exc_info:
        repo.put_report_metadata_once(bad_item)
    assert exc_info.value.error_type == "STORAGE_ERROR"
    assert client.get_item_calls == []
    assert client.transact_calls == []


def test_put_report_metadata_once_caller_item_immutability():
    repo, hold_repository, client = _make_hold_aware_repo()
    item = _valid_report_metadata_item(
        custody_expires_at=1, ttl_disposal_at=2, evidence_class="not_report"
    )
    original = dict(item)
    repo.put_report_metadata_once(item)
    assert item == original
    persisted = _deser_item(client, item)
    assert int(persisted["custody_expires_at"]) != 1
    assert persisted["evidence_class"] == "report"


def test_put_report_metadata_once_sanitizer_sensitive_identifier_preserved():
    repo, hold_repository, client = _make_hold_aware_repo()
    audit_id = "audit2475004829"
    item = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": (
            f"AUDIT#{audit_id}#EXEC#{_EXEC_ID}#CFG#{_CFG}#AGG#{_AGG}"
            f"#INTEL#{_INTEL}#RPT#{_RPT}#META"
        ),
        "status": "PENDING",
        "some_identifier": "id-2475004829",
    }
    repo.put_report_metadata_once(dict(item))
    persisted = _deser_item(client, item)
    assert persisted["PK"] == item["PK"]
    assert persisted["SK"] == item["SK"]
    assert persisted["some_identifier"] == item["some_identifier"]


def test_put_report_metadata_once_collision_raises_conditional_write_error():
    repo, hold_repository, client = _make_hold_aware_repo()
    repo.put_report_metadata_once(_valid_report_metadata_item())
    with pytest.raises(ConditionalWriteError):
        repo.put_report_metadata_once(_valid_report_metadata_item())


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
# update_report_metadata_fields -- forbidden governance-field guard
# (Technical Design Section 20.7.3; 9 required negative tests)
# ---------------------------------------------------------------------------

_UPDATE_KEY = {
    "PK": "CLIENT#client1",
    "SK": "AUDIT#audit1#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#RPT#rpt_v1#META",
}


def test_update_report_metadata_fields_rejects_custody_expires_at():
    repo = _make_repo()
    with pytest.raises(AssertionError):
        repo.update_report_metadata_fields(_UPDATE_KEY, {"custody_expires_at": 123})


def test_update_report_metadata_fields_rejects_ttl_disposal_at():
    repo = _make_repo()
    with pytest.raises(AssertionError):
        repo.update_report_metadata_fields(_UPDATE_KEY, {"ttl_disposal_at": 123})


def test_update_report_metadata_fields_rejects_evidence_class():
    repo = _make_repo()
    with pytest.raises(AssertionError):
        repo.update_report_metadata_fields(_UPDATE_KEY, {"evidence_class": "report"})


def test_update_report_metadata_fields_rejects_all_forbidden_fields_together():
    repo = _make_repo()
    with pytest.raises(AssertionError):
        repo.update_report_metadata_fields(
            _UPDATE_KEY,
            {"custody_expires_at": 1, "ttl_disposal_at": 2, "evidence_class": "report"},
        )


def test_update_report_metadata_fields_rejects_forbidden_field_mixed_with_ordinary_fields():
    repo = _make_repo()
    with patch.object(repo, "_update_item") as mock_update:
        with pytest.raises(AssertionError):
            repo.update_report_metadata_fields(
                _UPDATE_KEY, {"status": "COMPLETE", "ttl_disposal_at": 123}
            )
        mock_update.assert_not_called()


def test_update_report_metadata_fields_forbidden_field_exception_type_and_message():
    repo = _make_repo()
    with pytest.raises(AssertionError) as exc_info:
        repo.update_report_metadata_fields(_UPDATE_KEY, {"evidence_class": "report"})
    assert str(exc_info.value) == "ReportMetadata governance fields are repository-owned"
    assert "evidence_class" not in str(exc_info.value)
    assert "report" not in str(exc_info.value)


def test_update_report_metadata_fields_forbidden_field_rejection_performs_zero_dynamodb_activity():
    client = MagicMock()
    repo = ReportRepository(_TABLE, client)
    with pytest.raises(AssertionError):
        repo.update_report_metadata_fields(_UPDATE_KEY, {"custody_expires_at": 1})
    client.update_item.assert_not_called()
    client.put_item.assert_not_called()
    client.transact_write_items.assert_not_called()


def test_update_report_metadata_fields_forbidden_field_rejection_preserves_caller_dict():
    repo = _make_repo()
    updates = {"status": "COMPLETE", "ttl_disposal_at": 123}
    original = dict(updates)
    with pytest.raises(AssertionError):
        repo.update_report_metadata_fields(_UPDATE_KEY, updates)
    assert updates == original


def test_update_report_metadata_fields_permitted_fields_unaffected():
    repo = _make_repo()
    updates = {
        "status": "COMPLETE",
        "report_job_id": "rptjob_abc",
        "generation_count": 2,
        "updated_at": "2026-07-04T12:00:00Z",
        "failure_stage": "writing_s3_artifact",
        "failure_reason_code": "S3_WRITE_FAILED",
        "completed_at": "2026-07-04T12:00:00Z",
        "report_id": "report_abc",
        "composite_score": "0.850",
        "score_label": "HIGH_CONFIDENCE",
        "endpoint_count": 1,
        "s3_artifact_ref": "reports/client1/audit1/.../artifact.json",
        "aggregate_set_hash": "hashABC",
    }
    with patch.object(repo, "_update_item") as mock_update:
        repo.update_report_metadata_fields(_UPDATE_KEY, updates)
        mock_update.assert_called_once_with(_UPDATE_KEY, updates)


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


# ---------------------------------------------------------------------------
# Category 3 exclusion — ReportJob never receives governance elements
# (ADR Invariant 27 / Decision 8; Technical Design Section 20.2). Unit-level
# direct calls, gated only by _assert_phase6_sk -- ReportJob writes never
# read hold state and never construct a TransactWriteItems call.
# ---------------------------------------------------------------------------

_GOVERNANCE_ELEMENTS = (
    "custody_expires_at",
    "ttl_disposal_at",
    "evidence_class",
    "rcp-legal-hold",
    "rcp-evidence-class",
    "hold_version",
)


def test_put_report_job_once_never_carries_governance_elements():
    repo = _make_repo()
    job_item = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#RPTJOB#rptjob_abc",
        "record_type": "report_job",
        "status": "PENDING",
    }
    with patch.object(repo, "_put_once") as mock_put:
        repo.put_report_job_once(job_item)
        mock_put.assert_called_once_with(job_item)
    for element in _GOVERNANCE_ELEMENTS:
        assert element not in job_item


def test_update_report_job_never_carries_governance_elements():
    repo = _make_repo()
    key = {"PK": "CLIENT#client1", "SK": "AUDIT#audit1#RPTJOB#rptjob_abc"}
    updates = {"status": "COMPLETE", "completed_at": "2026-07-04T12:00:00Z"}
    with patch.object(repo, "_update_item") as mock_update:
        repo.update_report_job(key, updates)
        mock_update.assert_called_once_with(key, updates)
    for element in _GOVERNANCE_ELEMENTS:
        assert element not in updates


def test_put_report_job_once_gated_only_by_assert_phase6_sk():
    """ReportJob CREATE has no governance preflight -- an unconfigured
    ReportRepository (no hold_repository, no custody_period_days) must
    still accept a valid ReportJob write, proving the only gate is the SK
    guard, not hold coordination."""
    repo = ReportRepository(_TABLE, MagicMock())
    valid_job_item = {
        "PK": "CLIENT#client1",
        "SK": "AUDIT#audit1#RPTJOB#rptjob_abc",
        "record_type": "report_job",
        "status": "PENDING",
    }
    with patch.object(repo, "_put_once") as mock_put:
        repo.put_report_job_once(valid_job_item)
        mock_put.assert_called_once()
