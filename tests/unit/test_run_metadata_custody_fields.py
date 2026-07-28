"""Evidence Governance Workstream A1.LH3 --
packages/storage/dynamodb_client.py hold-aware custody-field, evidence_class,
and DynamoDB TransactWriteItems hold-coordination tests.

Supersedes A1.3b/A1.3b.1's own test file of the same name: the merged
put_started_once was a plain conditional put_item with no hold-state
awareness at all (Technical Design Section 19.8's impact analysis). This
file proves the correction: put_started_once now resolves current
legal-hold state via HoldRepository/HoldCoordinatedTransactionRunner
(Technical Design Section 19.4) inside a single TransactWriteItems call,
omits ttl_disposal_at if and only if the audit identity is under an ACTIVE
hold, retries a detected hold-version race up to the bounded attempt count,
and fails closed (HOLD_STATE_CONCURRENCY_EXCEEDED) on retry exhaustion --
never falling back to an unconditioned write.

Covers:
  * custody_expires_at is always freshly computed, never hardcoded (ADR
    Non-Negotiable Invariant 3) -- unchanged from A1.3b.
  * ttl_disposal_at is omitted under an ACTIVE hold, included otherwise (no
    hold record at all, or a RELEASED hold) -- Technical Design Section 19.4
    step 2.
  * evidence_class remains a fixed, non-caller-overridable "raw_evidence"
    value -- unchanged from A1.3b.1.
  * A concurrent PLACE/RELEASE racing the CREATE forces a retry that
    correctly re-observes the new hold state (Technical Design Section 19.4
    step 4's second bullet; QA strategy categories 1/2, Section 19.11).
  * Retry exhaustion fails closed (HoldStateConcurrencyExceededError,
    re-surfaced as this module's own StorageError with the same
    HOLD_STATE_CONCURRENCY_EXCEEDED code -- Section 19.15) with no partial
    write ever observable.
  * The governed record's own duplicate-write condition always wins over a
    concurrent hold-version race in the same attempt (Section 19.4 step 4's
    explicit precedence rule).
  * update_terminal (FINALIZATION, not regeneration) never touches custody
    fields -- unchanged, Section 19.7 row 2.
  * A DynamoDBMetadataClient constructed without a HoldRepository fails
    closed rather than silently skipping legal-hold verification (Section
    19.14's uniform fail-closed rule).
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from packages.core.constants.engine import RUN_STATUS_COMPLETED, RUN_STATUS_STARTED
from packages.core.exceptions import DuplicateRunIdError, StorageError
from packages.storage.dynamodb_client import (
    CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR,
    DynamoDBMetadataClient,
)
from release_confidence_platform.evidence_retention.constants import (
    EVIDENCE_CLASSES,
    HOLD_STATE_CONCURRENCY_EXCEEDED_CODE,
    HOLD_STATUS_ACTIVE,
    HOLD_STATUS_RELEASED,
    MAX_HOLD_COORDINATION_RETRY_ATTEMPTS,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository

CLIENT_ID = "client1"
AUDIT_ID = "audit1"
RUN_ID = "run1"

_SECONDS_PER_DAY = 86400

_SER = TypeSerializer()
_DESER = TypeDeserializer()


def _to_typed(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _SER.serialize(v) for k, v in item.items()}


def _from_typed(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _DESER.deserialize(v) for k, v in item.items()}


class _SharedStore:
    """Backing store shared by the resource-style and low-level fakes below,
    always holding true DynamoDB typed-AttributeValue items -- a faithful
    simulation of one real DynamoDB table, not a hand-rolled shortcut."""

    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def get(self, pk: str, sk: str) -> dict[str, Any] | None:
        return self.items.get((pk, sk))

    def put(self, typed_item: dict[str, Any]) -> None:
        self.items[(typed_item["PK"]["S"], typed_item["SK"]["S"])] = typed_item


class _TableResource:
    """Mirrors boto3.resource('dynamodb').Table(...): plain-Python in/out,
    no TableName kwarg -- backs DynamoDBMetadataClient's pre-existing
    get_item/put_item/update_item operations, unchanged by A1.LH3."""

    def __init__(self, store: _SharedStore) -> None:
        self.store = store
        self.update_item_calls: list[dict[str, Any]] = []

    def get_item(self, Key: dict[str, Any]) -> dict[str, Any]:
        typed_key = _to_typed(Key)
        item = self.store.get(typed_key["PK"]["S"], typed_key["SK"]["S"])
        return {"Item": _from_typed(item)} if item else {}

    def update_item(
        self,
        Key: dict[str, Any],
        UpdateExpression: str,
        ExpressionAttributeValues: dict[str, Any],
        ExpressionAttributeNames: dict[str, str] | None = None,
        ConditionExpression: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        self.update_item_calls.append(
            {"Key": Key, "ExpressionAttributeNames": ExpressionAttributeNames or {}}
        )
        typed_key = _to_typed(Key)
        pk, sk = typed_key["PK"]["S"], typed_key["SK"]["S"]
        existing = self.store.get(pk, sk)
        if ConditionExpression and "attribute_exists" in ConditionExpression and existing is None:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}},
                "UpdateItem",
            )
        existing = existing or {"PK": typed_key["PK"], "SK": typed_key["SK"]}
        names = ExpressionAttributeNames or {}
        typed_values = _to_typed(ExpressionAttributeValues)
        for placeholder, attr_name in names.items():
            val_placeholder = UpdateExpression.split(f"{placeholder} = ")[1].split(",")[0].strip()
            existing[attr_name] = typed_values[val_placeholder]
        self.store.put(existing)
        return {}


class _LowLevelClient:
    """Mirrors boto3.client('dynamodb') / table.meta.client: typed
    AttributeValue in/out, accepts TableName=. Backs HoldRepository and
    HoldCoordinatedTransactionRunner (via DynamoDBMetadataClient's
    transact_dynamodb_client constructor argument), exactly as
    apps/backend/handlers/orchestrator_handler.py wires production."""

    def __init__(self, store: _SharedStore) -> None:
        self.store = store
        self.transact_write_items_calls: list[list[dict[str, Any]]] = []
        # Injected by individual tests to simulate a concurrent PLACE/RELEASE
        # committing in the gap between this attempt's own hold-state read
        # and its transact_write_items call -- invoked once per attempt,
        # immediately before this attempt's conditions are evaluated.
        self.before_transact: Any = None

    def get_item(self, TableName: str, Key: dict[str, Any], **_: Any) -> dict[str, Any]:
        pk, sk = Key["PK"]["S"], Key["SK"]["S"]
        item = self.store.get(pk, sk)
        return {"Item": item} if item else {}

    def transact_write_items(self, TransactItems: list[dict[str, Any]]) -> dict[str, Any]:
        self.transact_write_items_calls.append(TransactItems)
        if self.before_transact is not None:
            self.before_transact(len(self.transact_write_items_calls))
        reasons: list[dict[str, str]] = []
        any_failed = False
        for transact_item in TransactItems:
            if "Put" in transact_item:
                put = transact_item["Put"]
                pk, sk = put["Item"]["PK"]["S"], put["Item"]["SK"]["S"]
                if self.store.get(pk, sk) is not None:
                    reasons.append({"Code": "ConditionalCheckFailed"})
                    any_failed = True
                else:
                    reasons.append({"Code": "None"})
            elif "ConditionCheck" in transact_item:
                cc = transact_item["ConditionCheck"]
                pk, sk = cc["Key"]["PK"]["S"], cc["Key"]["SK"]["S"]
                existing = self.store.get(pk, sk)
                if "attribute_not_exists" in cc["ConditionExpression"]:
                    passed = existing is None
                else:
                    expected = cc["ExpressionAttributeValues"][":expected_hold_version"]
                    passed = existing is not None and existing.get("hold_version") == expected
                reasons.append({"Code": "None"} if passed else {"Code": "ConditionalCheckFailed"})
                if not passed:
                    any_failed = True
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
                self.store.put(transact_item["Put"]["Item"])
        return {}


def _make_client(store: _SharedStore) -> tuple[DynamoDBMetadataClient, _LowLevelClient]:
    table = _TableResource(store)
    low_level = _LowLevelClient(store)
    hold_repository = HoldRepository("test_table", low_level)
    client = DynamoDBMetadataClient("test_table", table, hold_repository, low_level)
    return client, low_level


def _place_hold(
    store: _SharedStore, *, hold_version: int, status: str = HOLD_STATUS_ACTIVE
) -> None:
    """Directly write a LegalHold current-state record into the shared
    store, standing in for HoldRepository.upsert_hold's committed effect --
    equivalent for these tests' purposes (upsert_hold is a plain,
    unconditional PutItem, already covered by A1.LH1's own test suite)."""
    store.put(
        _to_typed(
            {
                "PK": f"CLIENT#{CLIENT_ID}",
                "SK": f"AUDIT#{AUDIT_ID}#LEGALHOLD",
                "record_type": "legal_hold",
                "status": status,
                "hold_version": hold_version,
                "sweep_status": "COMPLETE",
            }
        )
    )


def _make_item() -> dict[str, Any]:
    client = DynamoDBMetadataClient("test_table", None)
    keys = client.keys(CLIENT_ID, AUDIT_ID, RUN_ID)
    return {
        **keys,
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "run_id": RUN_ID,
        "status": RUN_STATUS_STARTED,
        "raw_result_s3_key": None,
        "started_at": "2026-07-21T00:00:00Z",
        "completed_at": None,
        "failure_summary": None,
    }


def _stored_run_metadata(store: _SharedStore) -> dict[str, Any] | None:
    item = store.get(f"CLIENT#{CLIENT_ID}", f"AUDIT#{AUDIT_ID}#RUN#{RUN_ID}")
    return _from_typed(item) if item else None


# ---------------------------------------------------------------------------
# put_started_once -- custody fields present and correctly computed (no hold)
# ---------------------------------------------------------------------------


def test_put_started_once_sets_custody_fields_from_env_config(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    client, _low_level = _make_client(store)

    before = int(time.time())
    client.put_started_once(_make_item())
    after = int(time.time())

    persisted = _stored_run_metadata(store)
    assert "custody_expires_at" in persisted
    assert "ttl_disposal_at" in persisted
    # No hold record at all: ttl_disposal_at == custody_expires_at.
    assert persisted["custody_expires_at"] == persisted["ttl_disposal_at"]
    assert (before + 30 * _SECONDS_PER_DAY) <= persisted["custody_expires_at"]
    assert persisted["custody_expires_at"] <= (after + 30 * _SECONDS_PER_DAY)


def test_put_started_once_does_not_mutate_caller_supplied_item(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    client, _low_level = _make_client(store)
    item = _make_item()

    client.put_started_once(item)

    assert "custody_expires_at" not in item
    assert "ttl_disposal_at" not in item


def test_custody_expires_at_is_not_hardcoded_and_scales_with_configured_days(monkeypatch):
    """Two different configured custody-period-days values must produce
    proportionally different custody_expires_at outputs, proving the value
    is derived from configuration read at write time, never a fixed
    number."""
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "10")
    store_a = _SharedStore()
    client_a, _ = _make_client(store_a)
    client_a.put_started_once(_make_item())
    first = _stored_run_metadata(store_a)["custody_expires_at"]

    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "40")
    store_b = _SharedStore()
    client_b, _ = _make_client(store_b)
    client_b.put_started_once(_make_item())
    second = _stored_run_metadata(store_b)["custody_expires_at"]

    delta_days = (second - first) / _SECONDS_PER_DAY
    assert 29.9 <= delta_days <= 30.1


# ---------------------------------------------------------------------------
# put_started_once -- evidence_class (A1.3b.1, unaffected by A1.LH3)
# ---------------------------------------------------------------------------


def test_put_started_once_sets_evidence_class_raw_evidence(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    client, _low_level = _make_client(store)

    client.put_started_once(_make_item())

    assert _stored_run_metadata(store)["evidence_class"] == "raw_evidence"


def test_run_metadata_evidence_class_is_member_of_bounded_evidence_classes(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    client, _low_level = _make_client(store)

    client.put_started_once(_make_item())

    assert _stored_run_metadata(store)["evidence_class"] in EVIDENCE_CLASSES


def test_put_started_once_caller_cannot_override_evidence_class(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    client, _low_level = _make_client(store)
    item = _make_item()
    item["evidence_class"] = "certificate"  # attempted override

    client.put_started_once(item)

    persisted = _stored_run_metadata(store)
    assert persisted["evidence_class"] == "raw_evidence"
    assert item["evidence_class"] == "certificate"  # caller's own dict untouched


# ---------------------------------------------------------------------------
# put_started_once -- hold-state awareness (Technical Design Section 19.4)
# ---------------------------------------------------------------------------


def test_put_started_once_omits_ttl_disposal_at_under_active_hold(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    _place_hold(store, hold_version=1, status=HOLD_STATUS_ACTIVE)
    client, _low_level = _make_client(store)

    client.put_started_once(_make_item())

    persisted = _stored_run_metadata(store)
    assert "custody_expires_at" in persisted
    assert "ttl_disposal_at" not in persisted
    assert persisted["evidence_class"] == "raw_evidence"


def test_put_started_once_includes_ttl_disposal_at_under_released_hold(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    _place_hold(store, hold_version=2, status=HOLD_STATUS_RELEASED)
    client, _low_level = _make_client(store)

    client.put_started_once(_make_item())

    persisted = _stored_run_metadata(store)
    assert persisted["ttl_disposal_at"] == persisted["custody_expires_at"]


def test_put_started_once_includes_ttl_disposal_at_when_no_hold_record_exists(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    client, _low_level = _make_client(store)

    client.put_started_once(_make_item())

    persisted = _stored_run_metadata(store)
    assert persisted["ttl_disposal_at"] == persisted["custody_expires_at"]


# ---------------------------------------------------------------------------
# put_started_once -- concurrency races (Technical Design Section 19.4 step
# 4, Section 19.11 categories 1/2)
# ---------------------------------------------------------------------------


def test_put_started_once_retries_and_resolves_when_place_races_creation(monkeypatch):
    """A PLACE commits in the gap between this write's own hold-state read
    and its transact_write_items call: attempt 1's ConditionCheck (built
    from a None read) must fail against the now-existing LegalHold record,
    forcing a retry that re-reads and correctly observes ACTIVE, omitting
    ttl_disposal_at -- never committing it on a now-held audit."""
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    client, low_level = _make_client(store)

    def race_in_place(attempt_number: int) -> None:
        if attempt_number == 1:
            _place_hold(store, hold_version=1, status=HOLD_STATUS_ACTIVE)

    low_level.before_transact = race_in_place

    client.put_started_once(_make_item())

    persisted = _stored_run_metadata(store)
    assert "ttl_disposal_at" not in persisted
    assert len(low_level.transact_write_items_calls) == 2


def test_put_started_once_retries_and_resolves_when_release_races_creation(monkeypatch):
    """Symmetric case: a RELEASE (hold_version bump, status -> RELEASED)
    commits between this write's read (observing ACTIVE) and its commit --
    the retry must observe RELEASED and include ttl_disposal_at."""
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    _place_hold(store, hold_version=1, status=HOLD_STATUS_ACTIVE)
    client, low_level = _make_client(store)

    def race_release(attempt_number: int) -> None:
        if attempt_number == 1:
            _place_hold(store, hold_version=2, status=HOLD_STATUS_RELEASED)

    low_level.before_transact = race_release

    client.put_started_once(_make_item())

    persisted = _stored_run_metadata(store)
    assert persisted["ttl_disposal_at"] == persisted["custody_expires_at"]
    assert len(low_level.transact_write_items_calls) == 2


def test_put_started_once_stale_hold_version_forces_retry_even_when_status_unchanged(monkeypatch):
    """A hold_version bump alone (e.g. a completed RELEASE-then-PLACE cycle
    landing between read and commit, status ending ACTIVE both before and
    after) must still be detected and retried -- hold_version, not status,
    is what the ConditionCheck asserts (ADR Non-Negotiable Invariant 12: a
    reused status value must not alias as "unchanged")."""
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    _place_hold(store, hold_version=1, status=HOLD_STATUS_ACTIVE)
    client, low_level = _make_client(store)

    def bump_version_same_status(attempt_number: int) -> None:
        if attempt_number == 1:
            _place_hold(store, hold_version=3, status=HOLD_STATUS_ACTIVE)

    low_level.before_transact = bump_version_same_status

    client.put_started_once(_make_item())

    persisted = _stored_run_metadata(store)
    assert "ttl_disposal_at" not in persisted
    assert len(low_level.transact_write_items_calls) == 2


def test_put_started_once_fails_closed_on_bounded_retry_exhaustion(monkeypatch):
    """A hold-version race that never resolves within the bounded retry
    count must fail closed (HOLD_STATE_CONCURRENCY_EXCEEDED) -- never fall
    back to an unconditioned write (Technical Design Section 19.4 step 5,
    Section 19.14)."""
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    _place_hold(store, hold_version=1, status=HOLD_STATUS_ACTIVE)
    client, low_level = _make_client(store)

    def perpetual_race(attempt_number: int) -> None:
        _place_hold(store, hold_version=attempt_number + 100, status=HOLD_STATUS_ACTIVE)

    low_level.before_transact = perpetual_race

    with pytest.raises(StorageError) as exc:
        client.put_started_once(_make_item())

    assert exc.value.error_type == HOLD_STATE_CONCURRENCY_EXCEEDED_CODE
    assert len(low_level.transact_write_items_calls) == MAX_HOLD_COORDINATION_RETRY_ATTEMPTS
    # No partial RunMetadata write under any circumstance.
    assert _stored_run_metadata(store) is None


def test_put_started_once_governed_condition_failure_wins_over_concurrent_hold_race(monkeypatch):
    """Technical Design Section 19.4 step 4's explicit precedence: if the
    governed record's own condition AND the hold ConditionCheck both fail in
    the same attempt, DuplicateRunIdError must win outright -- never masked
    behind, or converted into, a hold-version retry loop."""
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    client, low_level = _make_client(store)
    # Establish the record first (no hold involved).
    client.put_started_once(_make_item())
    assert len(low_level.transact_write_items_calls) == 1

    def race_and_duplicate(attempt_number: int) -> None:
        if attempt_number == 2:
            _place_hold(store, hold_version=1, status=HOLD_STATUS_ACTIVE)

    low_level.before_transact = race_and_duplicate

    with pytest.raises(DuplicateRunIdError):
        client.put_started_once(_make_item())

    # Precedence proven directly: exactly one further attempt was made (no
    # hold-version retry loop was entered even though the hold ConditionCheck
    # also failed in that same attempt).
    assert len(low_level.transact_write_items_calls) == 2


# ---------------------------------------------------------------------------
# put_started_once -- fail closed when custody-period config is unresolvable
# ---------------------------------------------------------------------------


def test_put_started_once_fails_closed_when_custody_period_env_var_unset(monkeypatch):
    monkeypatch.delenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, raising=False)
    store = _SharedStore()
    client, low_level = _make_client(store)

    with pytest.raises(StorageError) as exc:
        client.put_started_once(_make_item())

    assert exc.value.error_type == "CUSTODY_PERIOD_CONFIG_MISSING"
    # The write must never have been attempted -- fail closed, no partial
    # write, no stored item under this key at all.
    assert low_level.transact_write_items_calls == []
    assert _stored_run_metadata(store) is None


@pytest.mark.parametrize("bad_value", ["", "0", "-5", "not-a-number", "3.5"])
def test_put_started_once_fails_closed_for_invalid_custody_period_values(monkeypatch, bad_value):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, bad_value)
    store = _SharedStore()
    client, low_level = _make_client(store)

    with pytest.raises(StorageError) as exc:
        client.put_started_once(_make_item())

    assert exc.value.error_type == "CUSTODY_PERIOD_CONFIG_MISSING"
    assert low_level.transact_write_items_calls == []


# ---------------------------------------------------------------------------
# put_started_once -- repeated CREATE attempts (idempotency contract)
# ---------------------------------------------------------------------------


def test_put_started_once_repeated_call_raises_duplicate_run_id_error(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    client, low_level = _make_client(store)

    client.put_started_once(_make_item())
    first_persisted = dict(_stored_run_metadata(store))

    with pytest.raises(DuplicateRunIdError):
        client.put_started_once(_make_item())

    assert len(low_level.transact_write_items_calls) == 2
    stored_after_rejection = _stored_run_metadata(store)
    assert stored_after_rejection == first_persisted
    assert stored_after_rejection["evidence_class"] == "raw_evidence"


# ---------------------------------------------------------------------------
# put_started_once -- fail closed when hold coordination is not configured
# ---------------------------------------------------------------------------


def test_put_started_once_fails_closed_when_hold_repository_not_configured(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    client = DynamoDBMetadataClient("test_table", _TableResource(_SharedStore()))

    with pytest.raises(StorageError) as exc:
        client.put_started_once(_make_item())

    assert exc.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# update_terminal -- negative test: never touches custody fields
# ---------------------------------------------------------------------------


def test_update_terminal_never_touches_custody_fields(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    store = _SharedStore()
    client, _low_level = _make_client(store)
    client.put_started_once(_make_item())

    key = client.keys(CLIENT_ID, AUDIT_ID, RUN_ID)
    original = _stored_run_metadata(store)
    original_custody_expires_at = original["custody_expires_at"]
    original_ttl_disposal_at = original["ttl_disposal_at"]
    original_evidence_class = original["evidence_class"]

    client.update_terminal(
        key,
        {
            "status": RUN_STATUS_COMPLETED,
            "completed_at": "2026-07-21T00:05:00Z",
            "raw_result_s3_key": f"raw-results/{CLIENT_ID}/{AUDIT_ID}/{RUN_ID}/results.json",
            "failure_summary": None,
        },
    )

    stored = _stored_run_metadata(store)
    assert stored["custody_expires_at"] == original_custody_expires_at
    assert stored["ttl_disposal_at"] == original_ttl_disposal_at
    assert stored["evidence_class"] == original_evidence_class
    assert stored["status"] == RUN_STATUS_COMPLETED

    # Negative test proper: inspect the actual update_item call and assert
    # none of the three field names was ever named in it -- not just "the
    # stored value happens to be unchanged," which could pass even if
    # update_terminal set the field to the same value it already had.
    update_call = client.dynamodb_client.update_item_calls[-1]
    touched_attribute_names = set(update_call["ExpressionAttributeNames"].values())
    assert "custody_expires_at" not in touched_attribute_names
    assert "ttl_disposal_at" not in touched_attribute_names
    assert "evidence_class" not in touched_attribute_names
