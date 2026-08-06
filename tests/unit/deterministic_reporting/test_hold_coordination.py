"""Evidence Governance Workstream A1.3d.3 — dedicated coverage for
ReportRepository.put_report_metadata_once / regenerate_report_metadata's
legal-hold coordination and custody-field computation (Technical Design
Section 20.7.1, 20.7.2, 20.7.5; ADR Non-Negotiable Invariants 11-12, 14, 31).

This file is Phase-6-local and self-contained: the low-level DynamoDB test
double, and the place_hold/release_hold helpers, are defined directly here
(not imported from tests/unit/reliability_intelligence/test_hold_coordination.py
or tests/unit/aggregation/_hold_coordination_double.py), per the locked
A1.3d.2 correction requiring independent, phase-local equivalents rather than
a shared double module. The double's wire-format shape and forced-failure-
injection mechanism intentionally mirror that precedent's already-proven
design, extended here to also simulate DynamoDB "Update" transact-items
(SET/REMOVE), since Phase 6's regeneration contract is a partial Update,
unlike Phase 5's full-item Put regeneration.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

import release_confidence_platform.deterministic_reporting.repository as repository_module
from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.deterministic_reporting.repository import (
    ConditionalWriteError,
    ReportRepository,
)
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldStateConcurrencyExceededError,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository

_DESER = TypeDeserializer()

CLIENT_ID = "client"
AUDIT_ID = "audit"


# ---------------------------------------------------------------------------
# Low-level DynamoDB test double
# ---------------------------------------------------------------------------


class ReportHoldAwareClient:
    """Low-level `boto3.client("dynamodb")`-shaped double.

    Backs both `HoldRepository` (get_item/put_item/update_item) and
    `HoldCoordinatedTransactionRunner` (transact_write_items) against one
    shared, real per-key typed-item store, so ConditionalCheckFailedException
    / TransactionCanceledException / CancellationReasons behavior faithfully
    simulates real DynamoDB wire format. Also simulates "Update" transact
    items (SET/REMOVE), which Phase 6's regenerate_report_metadata uses,
    unlike Phase 5's full-item-replacement regeneration.
    """

    def __init__(self) -> None:
        self.storage: dict[tuple[str, str], dict] = {}
        self.transact_calls: list[list[dict]] = []
        self.get_item_calls: list[dict] = []
        self.force_fail_indices_by_attempt: dict[int, set[int]] = {}
        self.force_client_error_by_attempt: dict[int, dict] = {}
        self._attempt = 0

    # -- HoldRepository / ReportRepository dependency surface -------------

    def get_item(self, **kwargs) -> dict:
        self.get_item_calls.append(kwargs)
        key = kwargs["Key"]
        item = self.storage.get((key["PK"]["S"], key["SK"]["S"]))
        return {"Item": item} if item else {}

    def put_item(self, Item: dict, ConditionExpression: str | None = None, **_) -> dict:
        pk, sk = Item["PK"]["S"], Item["SK"]["S"]
        if (
            ConditionExpression
            and "attribute_not_exists" in ConditionExpression
            and (pk, sk) in self.storage
        ):
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "exists"}},
                "PutItem",
            )
        self.storage[(pk, sk)] = Item
        return {}

    def update_item(
        self,
        Key: dict,
        UpdateExpression: str,
        ExpressionAttributeValues: dict,
        ExpressionAttributeNames: dict | None = None,
        **_,
    ) -> dict:
        pk, sk = Key["PK"]["S"], Key["SK"]["S"]
        existing = self.storage.get((pk, sk)) or {"PK": Key["PK"], "SK": Key["SK"]}
        names = ExpressionAttributeNames or {}
        for placeholder, attr_name in names.items():
            val_placeholder = UpdateExpression.split(f"{placeholder} = ")[1].split(",")[0].strip()
            existing[attr_name] = ExpressionAttributeValues[val_placeholder]
        self.storage[(pk, sk)] = existing
        return {}

    def _apply_update_transact_item(self, update: dict) -> None:
        """Apply a Phase-6-shaped Update transact-item -- SET clauses plus an
        optional trailing ' REMOVE <attr>' clause -- to the shared store."""
        key = update["Key"]
        pk, sk = key["PK"]["S"], key["SK"]["S"]
        existing = self.storage.get((pk, sk)) or {"PK": key["PK"], "SK": key["SK"]}
        names = update.get("ExpressionAttributeNames", {})
        values = update.get("ExpressionAttributeValues", {})
        expr = update["UpdateExpression"]

        remove_attr: str | None = None
        set_portion = expr
        if " REMOVE " in expr:
            set_portion, remove_clause = expr.split(" REMOVE ", 1)
            remove_placeholder = remove_clause.strip()
            remove_attr = names.get(remove_placeholder, remove_placeholder)

        set_portion = set_portion[len("SET ") :] if set_portion.startswith("SET ") else set_portion
        for assignment in set_portion.split(", "):
            assignment = assignment.strip()
            if not assignment:
                continue
            name_placeholder, value_placeholder = [p.strip() for p in assignment.split("=", 1)]
            attr_name = names.get(name_placeholder, name_placeholder)
            existing[attr_name] = values[value_placeholder]

        if remove_attr is not None:
            existing.pop(remove_attr, None)

        self.storage[(pk, sk)] = existing

    def transact_write_items(self, TransactItems: list[dict]) -> dict:
        self._attempt += 1
        self.transact_calls.append(TransactItems)

        forced_error = self.force_client_error_by_attempt.get(self._attempt)
        if forced_error is not None:
            raise ClientError({"Error": forced_error}, "TransactWriteItems")

        forced = self.force_fail_indices_by_attempt.get(self._attempt, set())
        reasons: list[dict[str, str]] = []
        any_failed = False
        for idx, transact_item in enumerate(TransactItems):
            if idx in forced:
                reasons.append({"Code": "ConditionalCheckFailed"})
                any_failed = True
                continue
            if "Put" in transact_item:
                put = transact_item["Put"]
                pk, sk = put["Item"]["PK"]["S"], put["Item"]["SK"]["S"]
                condition = put.get("ConditionExpression")
                if condition and "attribute_not_exists" in condition and (pk, sk) in self.storage:
                    reasons.append({"Code": "ConditionalCheckFailed"})
                    any_failed = True
                else:
                    reasons.append({"Code": "None"})
            elif "Update" in transact_item:
                # Phase 6's regeneration Update carries no ConditionExpression
                # of its own -- it always succeeds structurally (the hold
                # ConditionCheck is the only condition in the transaction).
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
            elif "Update" in transact_item:
                self._apply_update_transact_item(transact_item["Update"])
        return {}


def place_hold(
    hold_repository: HoldRepository,
    client_id: str,
    audit_id: str,
    *,
    hold_version: int = 1,
    hold_id: str = "hold_test",
) -> None:
    """Durably commit an ACTIVE LegalHold via the real HoldRepository CRUD
    surface (never a hand-rolled typed item)."""
    hold_repository.upsert_hold(
        client_id,
        audit_id,
        "ACTIVE",
        hold_id,
        hold_version,
        "COMPLETE",
        "2026-01-01T00:00:00Z",
        "tester",
        "test hold",
        1,
    )


def release_hold(
    hold_repository: HoldRepository,
    client_id: str,
    audit_id: str,
    *,
    hold_version: int,
    hold_id: str = "hold_test",
) -> None:
    """Durably commit a RELEASED LegalHold via the real HoldRepository CRUD
    surface."""
    hold_repository.upsert_hold(
        client_id,
        audit_id,
        "RELEASED",
        hold_id,
        hold_version,
        "COMPLETE",
        "2026-01-01T00:00:00Z",
        "tester",
        "test hold",
        1,
        released_at="2026-01-02T00:00:00Z",
        released_by="tester",
    )


def _make_repo(client: ReportHoldAwareClient | None = None, custody_period_days: int | None = 90):
    client = client or ReportHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = ReportRepository(
        "metadata-table", client, hold_repository, custody_period_days=custody_period_days
    )
    return repo, hold_repository, client


def _meta_key(client_id: str = CLIENT_ID, audit_id: str = AUDIT_ID) -> dict:
    return {
        "PK": f"CLIENT#{client_id}",
        "SK": (f"AUDIT#{audit_id}#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#RPT#rpt_v1#META"),
    }


def _meta_item(client_id: str = CLIENT_ID, audit_id: str = AUDIT_ID, **overrides) -> dict:
    item = {
        **_meta_key(client_id, audit_id),
        "record_type": "report_metadata",
        "status": "PENDING",
        "generation_count": 1,
    }
    item.update(overrides)
    return item


def _deser_item(client: ReportHoldAwareClient, key: dict) -> dict:
    stored = client.storage[(key["PK"], key["SK"])]
    return {k: _DESER.deserialize(v) for k, v in stored.items()}


# ---------------------------------------------------------------------------
# CREATE contract (put_report_metadata_once)
# ---------------------------------------------------------------------------


def test_create_unheld_includes_ttl_disposal_at_and_evidence_class():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_report_metadata_once(item)
    persisted = _deser_item(client, item)
    assert persisted["evidence_class"] == "report"
    assert "ttl_disposal_at" in persisted
    assert "custody_expires_at" in persisted


def test_create_active_hold_omits_ttl_disposal_at():
    repo, hold_repository, client = _make_repo()
    place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
    item = _meta_item()
    repo.put_report_metadata_once(item)
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" not in persisted
    assert persisted["evidence_class"] == "report"
    assert "custody_expires_at" in persisted


def test_create_released_hold_includes_ttl_disposal_at():
    repo, hold_repository, client = _make_repo()
    place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
    release_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=2)
    item = _meta_item()
    repo.put_report_metadata_once(item)
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" in persisted


def test_create_duplicate_key_governed_failure_wins_over_hold_check_failure():
    repo, hold_repository, client = _make_repo()
    repo.put_report_metadata_once(_meta_item())
    client._attempt = 0
    client.transact_calls = []
    # Force BOTH the governed Put index (0) and the hold ConditionCheck
    # index (1) to fail on attempt 1 -- the governed condition must still
    # win, with zero retries.
    client.force_fail_indices_by_attempt = {1: {0, 1}}
    with pytest.raises(ConditionalWriteError):
        repo.put_report_metadata_once(_meta_item())
    assert len(client.transact_calls) == 1, "governed condition failure must never be retried"


def test_create_collision_alone_raises_conditional_write_error():
    repo, hold_repository, client = _make_repo()
    repo.put_report_metadata_once(_meta_item())
    client._attempt = 0
    client.transact_calls = []
    with pytest.raises(ConditionalWriteError):
        repo.put_report_metadata_once(_meta_item())
    assert len(client.transact_calls) == 1


# ---------------------------------------------------------------------------
# Retry / race tests
# ---------------------------------------------------------------------------


def test_put_report_metadata_once_place_race_bounded_success():
    client = ReportHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = ReportRepository("metadata-table", client, hold_repository, custody_period_days=90)
    real_get_item = client.get_item
    calls = {"n": 0}

    def get_item_with_side_effect(*args, **kwargs):
        calls["n"] += 1
        result = real_get_item(*args, **kwargs)
        if calls["n"] == 1:
            place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
        return result

    client.get_item = get_item_with_side_effect
    item = _meta_item()
    repo.put_report_metadata_once(item)

    assert calls["n"] == 2
    assert len(client.transact_calls) == 2
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" not in persisted


def test_put_report_metadata_once_release_race_bounded_success():
    client = ReportHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = ReportRepository("metadata-table", client, hold_repository, custody_period_days=90)
    place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
    real_get_item = client.get_item
    calls = {"n": 0}

    def get_item_with_side_effect(*args, **kwargs):
        calls["n"] += 1
        result = real_get_item(*args, **kwargs)
        if calls["n"] == 1:
            release_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=2)
        return result

    client.get_item = get_item_with_side_effect
    item = _meta_item()
    repo.put_report_metadata_once(item)

    assert calls["n"] == 2
    assert len(client.transact_calls) == 2
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" in persisted


def test_put_report_metadata_once_hold_race_retry_exhaustion_fails_closed():
    client = ReportHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = ReportRepository("metadata-table", client, hold_repository, custody_period_days=90)
    client.force_fail_indices_by_attempt = {1: {1}, 2: {1}, 3: {1}}

    with pytest.raises(HoldStateConcurrencyExceededError) as exc_info:
        repo.put_report_metadata_once(_meta_item())

    assert exc_info.value.error_type == "HOLD_STATE_CONCURRENCY_EXCEEDED"
    assert len(client.transact_calls) == 3
    assert (f"CLIENT#{CLIENT_ID}", _meta_key()["SK"]) not in client.storage


def test_regenerate_report_metadata_hold_race_retry_exhaustion_fails_closed():
    client = ReportHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = ReportRepository("metadata-table", client, hold_repository, custody_period_days=90)
    item = _meta_item()
    repo.put_report_metadata_once(item)
    client._attempt = 0
    client.transact_calls = []
    client.force_fail_indices_by_attempt = {1: {1}, 2: {1}, 3: {1}}

    with pytest.raises(HoldStateConcurrencyExceededError):
        repo.regenerate_report_metadata(
            _meta_key(), {"status": "PENDING"}, client_id=CLIENT_ID, audit_id=AUDIT_ID
        )

    assert len(client.transact_calls) == 3
    persisted = _deser_item(client, item)
    assert persisted["status"] == "PENDING"


# ---------------------------------------------------------------------------
# CREATE collision + hold-race same-attempt precedence proof
# ---------------------------------------------------------------------------


def test_create_condition_and_hold_check_both_fail_same_attempt_precedence():
    """A single TransactionCanceledException carrying BOTH the governed Put's
    own ConditionalCheckFailed AND the hold ConditionCheck's
    ConditionalCheckFailed must still surface only ConditionalWriteError,
    never HoldStateConcurrencyExceededError -- proving governed-condition-wins
    precedence holds for Phase 6, not only Phase 5 (Technical Design Section
    20.7.5)."""
    repo, hold_repository, client = _make_repo()
    repo.put_report_metadata_once(_meta_item())
    client._attempt = 0
    client.transact_calls = []
    client.force_fail_indices_by_attempt = {1: {0, 1}}

    with pytest.raises(ConditionalWriteError):
        repo.put_report_metadata_once(_meta_item())
    assert len(client.transact_calls) == 1


# ---------------------------------------------------------------------------
# Fresh-fields-per-retry proof
# ---------------------------------------------------------------------------


def test_custody_expires_at_fresh_per_retry_attempt(monkeypatch):
    """The clock-derived custody_expires_at must be recomputed fresh on each
    retry attempt, not cached or reused from a prior attempt."""
    client = ReportHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = ReportRepository("metadata-table", client, hold_repository, custody_period_days=90)

    clocks = [
        datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC),
        datetime(2026, 1, 1, 0, 0, 5, tzinfo=UTC),
    ]
    call_count = {"n": 0}

    class _AdvancingDateTime:
        @classmethod
        def now(cls, tz=None):
            idx = min(call_count["n"], len(clocks) - 1)
            call_count["n"] += 1
            return clocks[idx]

    monkeypatch.setattr(repository_module, "datetime", _AdvancingDateTime)

    # Force the hold ConditionCheck (index 1) to fail on attempt 1 only, so
    # a second attempt occurs with a distinct build_transact_items() call.
    client.force_fail_indices_by_attempt = {1: {1}}
    item = _meta_item()
    repo.put_report_metadata_once(item)

    persisted = _deser_item(client, item)
    expected_second_attempt = int(clocks[1].timestamp()) + 90 * 86400
    assert int(persisted["custody_expires_at"]) == expected_second_attempt


def test_custody_expires_at_uses_deterministic_clock(monkeypatch):
    fixed_now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    class _FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(repository_module, "datetime", _FixedDateTime)

    repo, hold_repository, client = _make_repo(custody_period_days=10)
    item = _meta_item()
    repo.put_report_metadata_once(item)
    persisted = _deser_item(client, item)

    expected = int(fixed_now.timestamp()) + 10 * 86400
    assert int(persisted["custody_expires_at"]) == expected
    assert int(persisted["ttl_disposal_at"]) == expected


# ---------------------------------------------------------------------------
# Regeneration contract -- held/unheld SET/REMOVE ttl_disposal_at branching
# ---------------------------------------------------------------------------


def test_regenerate_unheld_sets_fresh_ttl_disposal_at():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_report_metadata_once(item)
    repo.regenerate_report_metadata(
        _meta_key(), {"status": "IN_PROGRESS"}, client_id=CLIENT_ID, audit_id=AUDIT_ID
    )
    persisted = _deser_item(client, item)
    assert persisted["status"] == "IN_PROGRESS"
    assert "ttl_disposal_at" in persisted
    assert persisted["evidence_class"] == "report"


def test_regenerate_active_hold_removes_ttl_disposal_at():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_report_metadata_once(item)
    # Confirm ttl_disposal_at exists before the hold is placed.
    assert "ttl_disposal_at" in _deser_item(client, item)
    place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
    repo.regenerate_report_metadata(
        _meta_key(), {"status": "IN_PROGRESS"}, client_id=CLIENT_ID, audit_id=AUDIT_ID
    )
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" not in persisted, (
        "an explicit REMOVE must clear a stale prior-generation ttl_disposal_at "
        "value, not merely omit it from the SET clause"
    )


def test_regenerate_released_hold_restores_ttl_disposal_at():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_report_metadata_once(item)
    place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
    repo.regenerate_report_metadata(
        _meta_key(), {"status": "IN_PROGRESS"}, client_id=CLIENT_ID, audit_id=AUDIT_ID
    )
    assert "ttl_disposal_at" not in _deser_item(client, item)
    release_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=2)
    repo.regenerate_report_metadata(
        _meta_key(), {"status": "PENDING"}, client_id=CLIENT_ID, audit_id=AUDIT_ID
    )
    assert "ttl_disposal_at" in _deser_item(client, item)


def test_regenerate_preserves_other_updates_fields():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_report_metadata_once(item)
    repo.regenerate_report_metadata(
        _meta_key(),
        {"report_job_id": "rptjob_new", "status": "PENDING", "generation_count": 2},
        client_id=CLIENT_ID,
        audit_id=AUDIT_ID,
    )
    persisted = _deser_item(client, item)
    assert persisted["report_job_id"] == "rptjob_new"
    assert persisted["status"] == "PENDING"
    assert int(persisted["generation_count"]) == 2


def test_regenerate_rejects_forbidden_governance_fields_before_any_aws_call():
    client = ReportHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = ReportRepository("metadata-table", client, hold_repository, custody_period_days=90)
    with pytest.raises(AssertionError):
        repo.regenerate_report_metadata(
            _meta_key(),
            {"status": "PENDING", "custody_expires_at": 123},
            client_id=CLIENT_ID,
            audit_id=AUDIT_ID,
        )
    assert client.get_item_calls == []
    assert client.transact_calls == []


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


def test_put_report_metadata_once_does_not_mutate_caller_item_on_success():
    repo, hold_repository, client = _make_repo()
    item = _meta_item(custody_expires_at=1, ttl_disposal_at=2, evidence_class="not_report")
    original = copy.deepcopy(item)

    repo.put_report_metadata_once(item)

    assert item == original
    persisted = _deser_item(client, item)
    assert int(persisted["custody_expires_at"]) != 1
    assert int(persisted["ttl_disposal_at"]) != 2
    assert persisted["evidence_class"] == "report"


def test_regenerate_report_metadata_does_not_mutate_caller_updates_dict():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_report_metadata_once(item)
    updates = {"status": "IN_PROGRESS"}
    original = copy.deepcopy(updates)

    repo.regenerate_report_metadata(_meta_key(), updates, client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert updates == original


# ---------------------------------------------------------------------------
# Sanitizer-safety regression test
# ---------------------------------------------------------------------------


def test_sanitize_never_reaches_persistence_path_for_phone_pattern_digit_sequences():
    """A PK/SK/identifier field embedding the literal digit sequence
    2475004829 (which sanitize()'s PHONE_PATTERN would redact, since PK/SK
    are not in STRUCTURAL_IDENTIFIER_KEYS) must survive byte-identical on
    put_report_metadata_once -- proving sanitize() never reaches the
    persistence path here."""
    repo, hold_repository, client = _make_repo()
    audit_id = "audit2475004829"
    item = {
        "PK": f"CLIENT#{CLIENT_ID}",
        "SK": (f"AUDIT#{audit_id}#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#RPT#rpt_v1#META"),
        "record_type": "report_metadata",
        "status": "PENDING",
        "some_identifier": "id-2475004829",
    }

    repo.put_report_metadata_once(dict(item))
    persisted = _deser_item(client, item)
    assert persisted["PK"] == item["PK"]
    assert persisted["SK"] == item["SK"]
    assert persisted["some_identifier"] == item["some_identifier"]


# ---------------------------------------------------------------------------
# Generic (non-condition) ClientError -- not retried, not misclassified
# ---------------------------------------------------------------------------


def test_generic_client_error_on_create_raises_storage_error_not_retried():
    repo, hold_repository, client = _make_repo()
    client.force_client_error_by_attempt = {
        1: {"Code": "ValidationException", "Message": "malformed request"}
    }

    with pytest.raises(StorageError) as exc_info:
        repo.put_report_metadata_once(_meta_item())

    assert not isinstance(exc_info.value, HoldStateConcurrencyExceededError)
    assert len(client.transact_calls) == 1
    assert client.storage == {}
