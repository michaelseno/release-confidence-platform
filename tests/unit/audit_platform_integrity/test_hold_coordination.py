"""Evidence Governance Workstream A1.3d.4 -- Phase 7 (Certificate) hold
coordination tests (Technical Design Section 20.8/20.8.1).

Covers: unconditional-replacement preservation (forced recertification still
succeeds against an existing record), fresh clock/hold-state recomputation
per retry attempt, TTL omit/include correctness, bounded retry exhaustion,
the governed-condition-vs-hold-condition precedence rule as it applies to a
Put with no condition of its own, and end-to-end tag construction identity
between the CERTIFIED and TN-12 BLOCKED write_artifact paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

from release_confidence_platform.audit_platform_integrity.identity import build_cert_s3_key
from release_confidence_platform.audit_platform_integrity.publisher import CertificationPublisher
from release_confidence_platform.audit_platform_integrity.repository import CertificationRepository
from release_confidence_platform.evidence_retention.constants import (
    MAX_HOLD_COORDINATION_RETRY_ATTEMPTS,
)
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldStateConcurrencyExceededError,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from tests.unit.audit_platform_integrity.test_engine import (
    build_tn12_blocked_write_artifact_call,
)

_DESER = TypeDeserializer()

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


def _cert_key() -> dict[str, str]:
    return {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": (
            f"AUDIT#{_AUDIT_ID}#EXEC#{_EXEC_ID}#CFG#{_CFG}"
            f"#AGG#{_AGG}#INTEL#{_INTEL}#RPT#{_RPT}#CERT#{_CERT}#META"
        ),
    }


def _write(repo: CertificationRepository, **overrides) -> None:
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


def _deser_item(client, key: dict) -> dict:
    stored = client.storage[(key["PK"], key["SK"])]
    return {k: _DESER.deserialize(v) for k, v in stored.items()}


class _SimpleHoldAwareClient:
    """DynamoDB double proven for CREATE-contract unit tests
    (tests/unit/audit_platform_integrity/test_repository.py); reused here for
    the same reason."""

    def __init__(self) -> None:
        self.storage: dict[tuple[str, str], dict] = {}
        self.transact_calls: list[list[dict]] = []

    def get_item(self, **kwargs) -> dict:
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


def _make_hold_aware_repo(custody_period_days: int = 90):
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


class _FakeHoldRepository:
    def __init__(self, hold_state: dict | None = None):
        self.hold_state = hold_state
        self.calls: list[tuple] = []

    def get_legal_hold(self, client_id, audit_id, *, consistent_read=False):
        self.calls.append((client_id, audit_id, consistent_read))
        return self.hold_state


class _SequencedHoldRepository:
    """HoldRepository double whose get_legal_hold returns a fresh state per
    call from a fixed sequence (clamped at the last entry), proving each
    HoldCoordinatedTransactionRunner attempt performs its own fresh read."""

    def __init__(self, states: list[dict | None]):
        self.states = states
        self.calls = 0

    def legal_hold_key(self, client_id: str, audit_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#LEGALHOLD"}

    def get_legal_hold(self, client_id, audit_id, *, consistent_read: bool = False):
        state = self.states[min(self.calls, len(self.states) - 1)]
        self.calls += 1
        return state


class _FlakyDynamoClient:
    """transact_write_items fails with a hold-ConditionCheck-only cancellation
    for `fail_times` calls, then (if fail_times is finite and exceeded) succeeds."""

    def __init__(self, fail_times: int) -> None:
        self.fail_times = fail_times
        self.calls = 0
        self.transact_calls: list[list[dict]] = []

    def transact_write_items(self, TransactItems: list[dict]) -> dict:
        self.transact_calls.append(TransactItems)
        self.calls += 1
        if self.calls <= self.fail_times:
            raise ClientError(
                {
                    "Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
                    "CancellationReasons": [
                        {"Code": "None"},
                        {"Code": "ConditionalCheckFailed"},
                    ],
                },
                "TransactWriteItems",
            )
        return {}


# ---------------------------------------------------------------------------
# Unconditional-replacement preservation
# ---------------------------------------------------------------------------


def test_forced_recertification_replaces_existing_record():
    """A second write_cert_metadata_complete call against an already-written
    record must succeed (no ConditionalCheckFailed on the Put) and replace
    the stored item's terminal_state/certificate_id."""
    repo, _hold, client = _make_hold_aware_repo()
    _write(repo, terminal_state="CERTIFIED", certificate_id="cert_first")
    _write(repo, terminal_state="CERTIFICATION_FAILED", certificate_id="cert_second")

    item = _deser_item(client, _cert_key())
    assert item["terminal_state"] == "CERTIFICATION_FAILED"
    assert item["certificate_id"] == "cert_second"


# ---------------------------------------------------------------------------
# Fresh clock / hold-state recomputation per attempt
# ---------------------------------------------------------------------------


def test_fresh_clock_and_hold_state_recomputed_per_retry_attempt():
    """A retried write must re-read hold state on every attempt -- proven by
    the final committed item reflecting the SECOND attempt's hold state
    (ACTIVE), not the first attempt's (unheld)."""
    client = _FlakyDynamoClient(fail_times=1)
    hold_repository = _SequencedHoldRepository([None, {"status": "ACTIVE", "hold_version": 5}])
    repo = CertificationRepository(
        _TABLE, client, MagicMock(), _BUCKET, hold_repository, custody_period_days=90
    )
    _write(repo)

    assert hold_repository.calls == 2
    assert client.calls == 2
    second_attempt_items = client.transact_calls[1]
    put_item = next(i for i in second_attempt_items if "Put" in i)["Put"]
    assert "ttl_disposal_at" not in put_item["Item"]


def test_no_stale_governance_value_survives_between_attempts():
    """The final, successfully-committed attempt's item must reflect only
    that attempt's own fresh governance computation -- never a value carried
    over from an earlier, failed attempt."""
    client = _FlakyDynamoClient(fail_times=2)
    hold_repository = _SequencedHoldRepository(
        [{"status": "ACTIVE", "hold_version": 1}, None, None]
    )
    repo = CertificationRepository(
        _TABLE, client, MagicMock(), _BUCKET, hold_repository, custody_period_days=90
    )
    _write(repo)

    assert client.calls == 3
    final_attempt_items = client.transact_calls[2]
    put_item = next(i for i in final_attempt_items if "Put" in i)["Put"]
    # Final attempt observed an unheld state -- ttl_disposal_at must be
    # present, not omitted per the FIRST (held) attempt's would-be value.
    assert "ttl_disposal_at" in put_item["Item"]


# ---------------------------------------------------------------------------
# TTL omit/include correctness
# ---------------------------------------------------------------------------


def test_ttl_omitted_when_held():
    repo, _hold, client = _make_hold_aware_repo()
    # Seed an ACTIVE LegalHold record directly in the shared table.
    client.storage[(f"CLIENT#{_CLIENT_ID}", f"AUDIT#{_AUDIT_ID}#LEGALHOLD")] = {
        "PK": {"S": f"CLIENT#{_CLIENT_ID}"},
        "SK": {"S": f"AUDIT#{_AUDIT_ID}#LEGALHOLD"},
        "status": {"S": "ACTIVE"},
        "hold_version": {"N": "1"},
    }
    _write(repo)
    item = _deser_item(client, _cert_key())
    assert "ttl_disposal_at" not in item


def test_ttl_present_when_unheld():
    repo, _hold, client = _make_hold_aware_repo()
    _write(repo)
    item = _deser_item(client, _cert_key())
    assert item["ttl_disposal_at"] == item["custody_expires_at"]


# ---------------------------------------------------------------------------
# Bounded retry exhaustion
# ---------------------------------------------------------------------------


def test_bounded_retry_exhaustion_raises_hold_state_concurrency_exceeded():
    client = _FlakyDynamoClient(fail_times=MAX_HOLD_COORDINATION_RETRY_ATTEMPTS + 5)
    hold_repository = _SequencedHoldRepository([None])
    repo = CertificationRepository(
        _TABLE, client, MagicMock(), _BUCKET, hold_repository, custody_period_days=90
    )
    with pytest.raises(HoldStateConcurrencyExceededError):
        _write(repo)
    assert client.calls == MAX_HOLD_COORDINATION_RETRY_ATTEMPTS


# ---------------------------------------------------------------------------
# Governed-condition-vs-hold-condition precedence
# ---------------------------------------------------------------------------


def test_governed_condition_precedence_not_applicable_no_put_condition():
    """The Put carries no condition of its own, so a cancellation whose only
    real failure reason belongs to the ConditionCheck item must always route
    to a hold-version retry -- never a governed-condition failure path (there
    is none), and never on_governed_condition_failed (never supplied)."""
    client = _FlakyDynamoClient(fail_times=1)
    hold_repository = _SequencedHoldRepository([None, None])
    repo = CertificationRepository(
        _TABLE, client, MagicMock(), _BUCKET, hold_repository, custody_period_days=90
    )
    _write(repo)  # must not raise -- retried once, then succeeded

    assert client.calls == 2
    first_attempt_items = client.transact_calls[0]
    put_item = next(i for i in first_attempt_items if "Put" in i)["Put"]
    assert "ConditionExpression" not in put_item


# ---------------------------------------------------------------------------
# End-to-end tag construction identity: CERTIFIED vs TN-12 BLOCKED
# ---------------------------------------------------------------------------


def test_certified_path_tag_construction():
    s3 = MagicMock()
    hold_repository = _FakeHoldRepository({"status": "ACTIVE"})
    publisher = CertificationPublisher(_BUCKET, s3, hold_repository)
    key = build_cert_s3_key(
        client_id="client1",
        audit_id="audit1",
        audit_execution_id="exec1",
        config_version="cfg_v1",
        aggregation_version="agg_v1",
        intelligence_version="intel_v1",
        report_version="report_v1",
        cert_version="cert_v1",
        certjob_id="certjob_certified",
    )
    artifact = {"terminal_state": "CERTIFIED"}
    publisher.write_artifact(key, artifact)
    tagging = s3.put_object.call_args.kwargs["Tagging"]
    assert tagging == "rcp-legal-hold=true&rcp-evidence-class=certificate"


def test_tn12_blocked_path_tag_construction_matches_certified_path():
    """Consumes a (key, artifact) pair produced by test_engine.py's TN-12
    BLOCKED-path pipeline run and feeds it through the real write_artifact
    under the identical hold state used by test_certified_path_tag_construction,
    proving the publisher applies no BLOCKED-specific branch -- it receives
    no terminal-state argument and cannot distinguish paths."""
    key, artifact = build_tn12_blocked_write_artifact_call()
    assert key.startswith("integrity/")

    s3 = MagicMock()
    hold_repository = _FakeHoldRepository({"status": "ACTIVE"})
    publisher = CertificationPublisher(_BUCKET, s3, hold_repository)
    publisher.write_artifact(key, artifact)
    tagging = s3.put_object.call_args.kwargs["Tagging"]
    assert tagging == "rcp-legal-hold=true&rcp-evidence-class=certificate"
