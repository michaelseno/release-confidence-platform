"""Evidence Governance Workstream A1.3d.2 — dedicated coverage for
IntelligenceRepository.put_intelligence_metadata_once / update_intelligence_metadata's
legal-hold coordination and custody-field computation, and for
IntelligencePublisher.write_artifact's write-time S3 tagging (Technical
Design Section 20.6, 20.9; ADR Non-Negotiable Invariants 11-12, 14, 17-18,
27, 31).

This file is Phase-5-local and self-contained: the low-level DynamoDB test
double, and the place_hold/release_hold helpers, are defined directly here
(not imported from tests/unit/aggregation/_hold_coordination_double.py),
per the task's explicit "independent, Phase-5-local equivalents"
requirement. The double's wire-format shape and forced-failure-injection
mechanism intentionally mirror that A1.3c.1 precedent's already-proven
design.
"""

from __future__ import annotations

import copy
import inspect
from datetime import UTC, datetime

import pytest
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

import release_confidence_platform.reliability_intelligence.publisher as publisher_module
import release_confidence_platform.reliability_intelligence.repository as repository_module
from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.constants import (
    HOLD_STATUS_ACTIVE,
    HOLD_STATUS_RELEASED,
)
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldStateConcurrencyExceededError,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.reliability_intelligence.publisher import (
    IntelligencePublisher,
    _intelligence_tagging,
    _parse_intelligence_key_identity,
)
from release_confidence_platform.reliability_intelligence.repository import (
    ConditionalWriteError,
    IntelligenceRepository,
)

_DESER = TypeDeserializer()

CLIENT_ID = "client"
AUDIT_ID = "audit"


# ---------------------------------------------------------------------------
# Low-level DynamoDB test double
# ---------------------------------------------------------------------------


class IntelligenceHoldAwareClient:
    """Low-level `boto3.client("dynamodb")`-shaped double.

    Backs both `HoldRepository` (get_item/put_item/update_item) and
    `HoldCoordinatedTransactionRunner` (transact_write_items) against one
    shared, real per-key typed-item store, so ConditionalCheckFailedException
    / TransactionCanceledException / CancellationReasons behavior faithfully
    simulates real DynamoDB wire format.
    """

    def __init__(self) -> None:
        self.storage: dict[tuple[str, str], dict] = {}
        self.transact_calls: list[list[dict]] = []
        self.get_item_calls: list[dict] = []
        # 1-based attempt number (global across this client instance's
        # lifetime, matching AWS's own per-call semantics) -> set of 0-based
        # indices within that attempt's submitted TransactItems list to
        # force ConditionalCheckFailed on.
        self.force_fail_indices_by_attempt: dict[int, set[int]] = {}
        # 1-based attempt number -> a full ClientError.response["Error"]
        # dict to raise as a non-TransactionCanceledException ClientError on
        # that attempt (for byte-boundary / non-condition-failure testing).
        self.force_client_error_by_attempt: dict[int, dict] = {}
        self._attempt = 0

    # -- HoldRepository / IntelligenceRepository dependency surface -------

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
                # A Put with NO ConditionExpression against an existing key
                # must succeed (the regeneration/update_intelligence_metadata
                # contract), not be treated as a condition failure.
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
        HOLD_STATUS_ACTIVE,
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
        HOLD_STATUS_RELEASED,
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


def _make_repo(
    client: IntelligenceHoldAwareClient | None = None, custody_period_days: int | None = 90
):
    client = client or IntelligenceHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = IntelligenceRepository(
        "metadata-table", client, hold_repository, custody_period_days=custody_period_days
    )
    return repo, hold_repository, client


def _meta_item(client_id: str = CLIENT_ID, audit_id: str = AUDIT_ID, **overrides) -> dict:
    item = {
        "PK": f"CLIENT#{client_id}",
        "SK": f"AUDIT#{audit_id}#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#META",
        "record_type": "intelligence_metadata",
        "status": "PENDING",
    }
    item.update(overrides)
    return item


def _deser_item(client: IntelligenceHoldAwareClient, item: dict) -> dict:
    stored = client.storage[(item["PK"], item["SK"])]
    return {k: _DESER.deserialize(v) for k, v in stored.items()}


# ---------------------------------------------------------------------------
# Repository preflight matrix (both write methods, 8 conditions each)
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


@pytest.mark.parametrize("bad_duration", _INVALID_DURATIONS)
def test_put_intelligence_metadata_once_preflight_invalid_duration(bad_duration):
    client = IntelligenceHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = IntelligenceRepository(
        "metadata-table", client, hold_repository, custody_period_days=bad_duration
    )
    with pytest.raises(StorageError) as exc_info:
        repo.put_intelligence_metadata_once(_meta_item())
    assert exc_info.value.error_type == "CUSTODY_PERIOD_CONFIG_MISSING"
    assert client.get_item_calls == []
    assert client.transact_calls == []


@pytest.mark.parametrize("bad_duration", _INVALID_DURATIONS)
def test_update_intelligence_metadata_preflight_invalid_duration(bad_duration):
    client = IntelligenceHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = IntelligenceRepository(
        "metadata-table", client, hold_repository, custody_period_days=bad_duration
    )
    with pytest.raises(StorageError) as exc_info:
        repo.update_intelligence_metadata(_meta_item())
    assert exc_info.value.error_type == "CUSTODY_PERIOD_CONFIG_MISSING"
    assert client.get_item_calls == []
    assert client.transact_calls == []


def test_put_intelligence_metadata_once_preflight_missing_hold_repository():
    client = IntelligenceHoldAwareClient()
    repo = IntelligenceRepository("metadata-table", client, custody_period_days=90)
    with pytest.raises(StorageError) as exc_info:
        repo.put_intelligence_metadata_once(_meta_item())
    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"
    assert client.get_item_calls == []
    assert client.transact_calls == []


def test_update_intelligence_metadata_preflight_missing_hold_repository():
    client = IntelligenceHoldAwareClient()
    repo = IntelligenceRepository("metadata-table", client, custody_period_days=90)
    with pytest.raises(StorageError) as exc_info:
        repo.update_intelligence_metadata(_meta_item())
    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"
    assert client.get_item_calls == []
    assert client.transact_calls == []


def test_put_intelligence_metadata_once_hold_before_duration_precedence():
    """Both dependencies invalid simultaneously: HOLD_COORDINATION_NOT_CONFIGURED
    must win, proving hold-repository presence is checked first."""
    client = IntelligenceHoldAwareClient()
    repo = IntelligenceRepository("metadata-table", client, custody_period_days=None)
    with pytest.raises(StorageError) as exc_info:
        repo.put_intelligence_metadata_once(_meta_item())
    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"


def test_update_intelligence_metadata_hold_before_duration_precedence():
    client = IntelligenceHoldAwareClient()
    repo = IntelligenceRepository("metadata-table", client, custody_period_days=None)
    with pytest.raises(StorageError) as exc_info:
        repo.update_intelligence_metadata(_meta_item())
    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_repository_source_never_references_custody_period_config_loader():
    source = inspect.getsource(repository_module)
    assert "CustodyPeriodConfigLoader" not in source


def test_repository_source_never_references_environment_variables():
    source = inspect.getsource(repository_module)
    assert "os.environ" not in source
    assert "os.getenv" not in source


# ---------------------------------------------------------------------------
# CREATE contract (put_intelligence_metadata_once)
# ---------------------------------------------------------------------------


def test_create_unheld_includes_ttl_disposal_at_and_evidence_class():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_intelligence_metadata_once(item)
    persisted = _deser_item(client, item)
    assert persisted["evidence_class"] == "intelligence"
    assert "ttl_disposal_at" in persisted
    assert "custody_expires_at" in persisted


def test_create_active_hold_omits_ttl_disposal_at():
    repo, hold_repository, client = _make_repo()
    place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
    item = _meta_item()
    repo.put_intelligence_metadata_once(item)
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" not in persisted
    assert persisted["evidence_class"] == "intelligence"
    assert "custody_expires_at" in persisted


def test_create_released_hold_includes_ttl_disposal_at():
    repo, hold_repository, client = _make_repo()
    place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
    release_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=2)
    item = _meta_item()
    repo.put_intelligence_metadata_once(item)
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" in persisted


def test_create_preserves_existing_condition_expression():
    repo, hold_repository, client = _make_repo()
    repo.put_intelligence_metadata_once(_meta_item())
    put_entry = client.transact_calls[-1][0]
    assert put_entry["Put"]["ConditionExpression"] == (
        "attribute_not_exists(PK) AND attribute_not_exists(SK)"
    )


def test_create_duplicate_key_governed_failure_wins_over_hold_check_failure():
    repo, hold_repository, client = _make_repo()
    repo.put_intelligence_metadata_once(_meta_item())
    client._attempt = 0
    client.transact_calls = []
    # Force BOTH the governed Put index (0) and the hold ConditionCheck
    # index (1) to fail on attempt 1 -- the governed condition must still
    # win, with zero retries.
    client.force_fail_indices_by_attempt = {1: {0, 1}}
    with pytest.raises(ConditionalWriteError):
        repo.put_intelligence_metadata_once(_meta_item())
    assert len(client.transact_calls) == 1, "governed condition failure must never be retried"


# ---------------------------------------------------------------------------
# Regeneration contract (update_intelligence_metadata)
# ---------------------------------------------------------------------------


def test_regenerate_unheld_includes_ttl_disposal_at():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_intelligence_metadata_once(item)
    repo.update_intelligence_metadata(_meta_item(status="COMPLETE"))
    persisted = _deser_item(client, item)
    assert persisted["status"] == "COMPLETE"
    assert "ttl_disposal_at" in persisted
    assert persisted["evidence_class"] == "intelligence"


def test_regenerate_active_hold_omits_ttl_disposal_at():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_intelligence_metadata_once(item)
    place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
    repo.update_intelligence_metadata(_meta_item(status="COMPLETE"))
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" not in persisted


def test_regenerate_released_hold_includes_ttl_disposal_at():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_intelligence_metadata_once(item)
    place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
    release_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=2)
    repo.update_intelligence_metadata(_meta_item(status="COMPLETE"))
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" in persisted


def test_regenerate_put_has_no_condition_expression_and_succeeds_on_existing_key():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_intelligence_metadata_once(item)
    # Must not raise -- overwriting an existing key is the intended contract.
    repo.update_intelligence_metadata(_meta_item(status="COMPLETE"))
    last_put = client.transact_calls[-1][0]
    assert "Put" in last_put
    assert "ConditionExpression" not in last_put["Put"]


# ---------------------------------------------------------------------------
# Retry / race tests
# ---------------------------------------------------------------------------


def test_put_intelligence_metadata_once_no_hold_to_active_race_bounded_success():
    client = IntelligenceHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = IntelligenceRepository("metadata-table", client, hold_repository, custody_period_days=90)
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
    repo.put_intelligence_metadata_once(item)

    assert calls["n"] == 2
    assert len(client.transact_calls) == 2
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" not in persisted


def test_put_intelligence_metadata_once_active_to_released_race_bounded_success():
    client = IntelligenceHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = IntelligenceRepository("metadata-table", client, hold_repository, custody_period_days=90)
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
    repo.put_intelligence_metadata_once(item)

    assert calls["n"] == 2
    assert len(client.transact_calls) == 2
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" in persisted


def test_update_intelligence_metadata_release_race_bounded_success():
    """RELEASE race, symmetric to the PLACE race above, for the
    regeneration write method."""
    client = IntelligenceHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = IntelligenceRepository("metadata-table", client, hold_repository, custody_period_days=90)
    item = _meta_item()
    repo.put_intelligence_metadata_once(item)
    place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
    client.transact_calls = []

    real_get_item = client.get_item
    calls = {"n": 0}

    def get_item_with_side_effect(*args, **kwargs):
        calls["n"] += 1
        result = real_get_item(*args, **kwargs)
        if calls["n"] == 1:
            release_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=2)
        return result

    client.get_item = get_item_with_side_effect
    repo.update_intelligence_metadata(_meta_item(status="COMPLETE"))

    assert calls["n"] == 2
    assert len(client.transact_calls) == 2
    persisted = _deser_item(client, item)
    assert "ttl_disposal_at" in persisted


def test_put_intelligence_metadata_once_hold_race_retry_exhaustion_fails_closed():
    client = IntelligenceHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = IntelligenceRepository("metadata-table", client, hold_repository, custody_period_days=90)
    client.force_fail_indices_by_attempt = {1: {1}, 2: {1}, 3: {1}}

    with pytest.raises(HoldStateConcurrencyExceededError) as exc_info:
        repo.put_intelligence_metadata_once(_meta_item())

    assert exc_info.value.error_type == "HOLD_STATE_CONCURRENCY_EXCEEDED"
    assert len(client.transact_calls) == 3
    assert (f"CLIENT#{CLIENT_ID}", _meta_item()["SK"]) not in client.storage


def test_update_intelligence_metadata_hold_race_retry_exhaustion_fails_closed():
    client = IntelligenceHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = IntelligenceRepository("metadata-table", client, hold_repository, custody_period_days=90)
    item = _meta_item()
    repo.put_intelligence_metadata_once(item)
    client._attempt = 0
    client.transact_calls = []
    client.force_fail_indices_by_attempt = {1: {1}, 2: {1}, 3: {1}}

    with pytest.raises(HoldStateConcurrencyExceededError):
        repo.update_intelligence_metadata(_meta_item(status="COMPLETE"))

    assert len(client.transact_calls) == 3
    # No partial/unconditioned write ever committed on exhaustion -- the
    # record's status must remain whatever it was before this attempt.
    persisted = _deser_item(client, item)
    assert persisted["status"] == "PENDING"


# ---------------------------------------------------------------------------
# Deterministic clock test
# ---------------------------------------------------------------------------


def test_custody_expires_at_uses_deterministic_clock(monkeypatch):
    fixed_now = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)

    class _FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    monkeypatch.setattr(repository_module, "datetime", _FixedDateTime)

    repo, hold_repository, client = _make_repo(custody_period_days=10)
    item = _meta_item()
    repo.put_intelligence_metadata_once(item)
    persisted = _deser_item(client, item)

    expected = int(fixed_now.timestamp()) + 10 * 86400
    assert int(persisted["custody_expires_at"]) == expected
    assert int(persisted["ttl_disposal_at"]) == expected


# ---------------------------------------------------------------------------
# Byte-boundary test — non-condition ClientError injection
# ---------------------------------------------------------------------------


def test_generic_client_error_on_create_raises_storage_error_not_retried():
    repo, hold_repository, client = _make_repo()
    client.force_client_error_by_attempt = {
        1: {"Code": "ValidationException", "Message": "malformed request"}
    }

    with pytest.raises(StorageError) as exc_info:
        repo.put_intelligence_metadata_once(_meta_item())

    assert not isinstance(exc_info.value, HoldStateConcurrencyExceededError)
    assert len(client.transact_calls) == 1
    assert client.storage == {}


def test_generic_client_error_on_regeneration_raises_storage_error_not_retried():
    repo, hold_repository, client = _make_repo()
    item = _meta_item()
    repo.put_intelligence_metadata_once(item)
    client._attempt = 0
    client.transact_calls = []
    client.force_client_error_by_attempt = {
        1: {"Code": "ValidationException", "Message": "malformed request"}
    }

    with pytest.raises(StorageError) as exc_info:
        repo.update_intelligence_metadata(_meta_item(status="COMPLETE"))

    assert not isinstance(exc_info.value, HoldStateConcurrencyExceededError)
    assert len(client.transact_calls) == 1
    persisted = _deser_item(client, item)
    assert persisted["status"] == "PENDING", "no partial success from the failed regeneration"


# ---------------------------------------------------------------------------
# Immutability tests
# ---------------------------------------------------------------------------


def test_put_intelligence_metadata_once_does_not_mutate_caller_item_on_success():
    repo, hold_repository, client = _make_repo()
    item = _meta_item(custody_expires_at=1, ttl_disposal_at=2, evidence_class="not_intelligence")
    original = copy.deepcopy(item)

    repo.put_intelligence_metadata_once(item)

    assert item == original
    persisted = _deser_item(client, item)
    assert int(persisted["custody_expires_at"]) != 1
    assert int(persisted["ttl_disposal_at"]) != 2
    assert persisted["evidence_class"] == "intelligence"


def test_update_intelligence_metadata_does_not_mutate_caller_item_on_success():
    repo, hold_repository, client = _make_repo()
    repo.put_intelligence_metadata_once(_meta_item())
    item = _meta_item(
        status="COMPLETE",
        custody_expires_at=1,
        ttl_disposal_at=2,
        evidence_class="not_intelligence",
    )
    original = copy.deepcopy(item)

    repo.update_intelligence_metadata(item)

    assert item == original
    persisted = _deser_item(client, item)
    assert int(persisted["custody_expires_at"]) != 1
    assert int(persisted["ttl_disposal_at"]) != 2
    assert persisted["evidence_class"] == "intelligence"


def test_put_intelligence_metadata_once_does_not_mutate_caller_item_on_retry_exhaustion():
    repo, hold_repository, client = _make_repo()
    client.force_fail_indices_by_attempt = {1: {1}, 2: {1}, 3: {1}}
    item = _meta_item()
    original = copy.deepcopy(item)

    with pytest.raises(HoldStateConcurrencyExceededError):
        repo.put_intelligence_metadata_once(item)

    assert item == original


def test_update_intelligence_metadata_does_not_mutate_caller_item_on_retry_exhaustion():
    repo, hold_repository, client = _make_repo()
    repo.put_intelligence_metadata_once(_meta_item())
    client._attempt = 0
    client.transact_calls = []
    client.force_fail_indices_by_attempt = {1: {1}, 2: {1}, 3: {1}}
    item = _meta_item(status="COMPLETE")
    original = copy.deepcopy(item)

    with pytest.raises(HoldStateConcurrencyExceededError):
        repo.update_intelligence_metadata(item)

    assert item == original


# ---------------------------------------------------------------------------
# Sanitizer-safety regression test
# ---------------------------------------------------------------------------


def test_sanitize_never_reaches_persistence_path_for_phone_pattern_digit_sequences():
    """A PK/SK/identifier field embedding the literal digit sequence
    2475004829 (which sanitize()'s PHONE_PATTERN would redact, since PK/SK
    are not in STRUCTURAL_IDENTIFIER_KEYS) must survive byte-identical on
    both write methods -- proving sanitize() never reaches the persistence
    path here."""
    repo, hold_repository, client = _make_repo()
    audit_id = "audit2475004829"
    item = {
        "PK": f"CLIENT#{CLIENT_ID}",
        "SK": f"AUDIT#{audit_id}#EXEC#exec1#CFG#cfg_v1#AGG#agg_v1#INTEL#intel_v1#META",
        "record_type": "intelligence_metadata",
        "status": "PENDING",
        "some_identifier": "id-2475004829",
    }

    repo.put_intelligence_metadata_once(dict(item))
    persisted = _deser_item(client, item)
    assert persisted["PK"] == item["PK"]
    assert persisted["SK"] == item["SK"]
    assert persisted["some_identifier"] == item["some_identifier"]

    repo.update_intelligence_metadata(dict(item, status="COMPLETE"))
    persisted2 = _deser_item(client, item)
    assert persisted2["PK"] == item["PK"]
    assert persisted2["SK"] == item["SK"]
    assert persisted2["some_identifier"] == item["some_identifier"]


# ---------------------------------------------------------------------------
# IntelligenceJob structural-exclusion test (Category 3, ADR Invariant 27)
# ---------------------------------------------------------------------------


def test_intelligence_job_writes_never_receive_hold_coordination():
    repo, hold_repository, client = _make_repo()
    job_key = repo.intelligence_job_keys(CLIENT_ID, AUDIT_ID, "intjob_abc")
    job_item = {
        **job_key,
        "record_type": "intelligence_job",
        "status": "PENDING",
    }

    repo.put_intelligence_job_once(job_item)
    repo.update_intelligence_job(job_key, {"status": "IN_PROGRESS"})

    assert client.transact_calls == [], "IntelligenceJob writes must never be transactional"
    hold_related_reads = [
        call
        for call in client.get_item_calls
        if call.get("Key", {}).get("SK", {}).get("S", "").endswith("#LEGALHOLD")
    ]
    assert hold_related_reads == [], "IntelligenceJob writes must never read legal-hold state"
    persisted = _deser_item(client, job_item)
    for element in (
        "custody_expires_at",
        "ttl_disposal_at",
        "evidence_class",
        "rcp-legal-hold",
        "rcp-evidence-class",
        "hold_version",
    ):
        assert element not in persisted


# ---------------------------------------------------------------------------
# Publisher tests
# ---------------------------------------------------------------------------

_VALID_KEY = "intelligence/client1/audit1/exec1/agg_v1/intel_v1/intjob_abc/artifact.json"


def test_parse_intelligence_key_identity_valid():
    assert _parse_intelligence_key_identity(_VALID_KEY) == ("client1", "audit1")


@pytest.mark.parametrize(
    "key",
    [
        "wrong-prefix/client1/audit1/exec1/agg_v1/intel_v1/intjob_abc/artifact.json",
        "intelligence/client1/audit1/exec1/agg_v1/intel_v1/intjob_abc",
        "intelligence/client1/audit1/exec1/agg_v1/intel_v1/intjob_abc/wrong.json",
        "intelligence//audit1/exec1/agg_v1/intel_v1/intjob_abc/artifact.json",
        "intelligence/client1//exec1/agg_v1/intel_v1/intjob_abc/artifact.json",
    ],
)
def test_parse_intelligence_key_identity_malformed(key):
    with pytest.raises(StorageError) as exc_info:
        _parse_intelligence_key_identity(key)
    assert exc_info.value.error_type == "STORAGE_ERROR"


@pytest.mark.parametrize(
    "hold_state,expected_tag",
    [
        (None, "rcp-legal-hold=false&rcp-evidence-class=intelligence"),
        ({"status": "ACTIVE"}, "rcp-legal-hold=true&rcp-evidence-class=intelligence"),
        ({"status": "RELEASED"}, "rcp-legal-hold=false&rcp-evidence-class=intelligence"),
    ],
)
def test_intelligence_tagging_exact_string_per_state(hold_state, expected_tag):
    assert _intelligence_tagging(hold_state) == expected_tag


@pytest.mark.parametrize(
    "hold_state,expected_tag",
    [
        (None, "rcp-legal-hold=false&rcp-evidence-class=intelligence"),
        ({"status": "ACTIVE"}, "rcp-legal-hold=true&rcp-evidence-class=intelligence"),
        ({"status": "RELEASED"}, "rcp-legal-hold=false&rcp-evidence-class=intelligence"),
    ],
)
def test_write_artifact_call_order_and_tagging_per_state(hold_state, expected_tag):
    order: list = []

    class _Hold:
        def get_legal_hold(self, client_id, audit_id, *, consistent_read=False):
            order.append(("get_legal_hold", client_id, audit_id, consistent_read))
            return hold_state

    class _S3:
        def put_object(self, **kwargs):
            order.append(("put_object", kwargs.get("Tagging")))
            return {}

    publisher = IntelligencePublisher("bucket", _S3(), _Hold())
    publisher.write_artifact(_VALID_KEY, {"a": 1})

    assert order[0] == ("get_legal_hold", "client1", "audit1", True)
    assert order[1] == ("put_object", expected_tag)


def test_write_artifact_storage_error_from_hold_read_propagates_unchanged():
    class _Hold:
        def get_legal_hold(self, client_id, audit_id, *, consistent_read=False):
            raise StorageError("hold read failed", "SOME_OTHER_CODE")

    class _S3:
        def __init__(self):
            self.calls: list = []

        def put_object(self, **kwargs):
            self.calls.append(kwargs)
            return {}

    s3 = _S3()
    publisher = IntelligencePublisher("bucket", s3, _Hold())

    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_VALID_KEY, {})

    assert exc_info.value.error_type == "SOME_OTHER_CODE"
    assert s3.calls == []


def test_write_artifact_unexpected_exception_maps_to_storage_error():
    class _Hold:
        def get_legal_hold(self, client_id, audit_id, *, consistent_read=False):
            raise RuntimeError("unexpected failure")

    class _S3:
        def __init__(self):
            self.calls: list = []

        def put_object(self, **kwargs):
            self.calls.append(kwargs)
            return {}

    s3 = _S3()
    publisher = IntelligencePublisher("bucket", s3, _Hold())

    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_VALID_KEY, {})

    assert exc_info.value.error_type == "STORAGE_ERROR"
    assert s3.calls == []


def test_write_artifact_fails_closed_when_hold_repository_not_configured():
    class _S3:
        def __init__(self):
            self.calls: list = []

        def put_object(self, **kwargs):
            self.calls.append(kwargs)
            return {}

    s3 = _S3()
    publisher = IntelligencePublisher("bucket", s3)  # hold_repository=None

    with pytest.raises(StorageError) as exc_info:
        publisher.write_artifact(_VALID_KEY, {})

    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"
    assert s3.calls == []


def test_write_artifact_does_not_mutate_caller_artifact():
    class _Hold:
        def get_legal_hold(self, client_id, audit_id, *, consistent_read=False):
            return None

    class _S3:
        def put_object(self, **kwargs):
            return {}

    publisher = IntelligencePublisher("bucket", _S3(), _Hold())
    artifact = {"a": 1, "nested": {"b": 2}}
    original = copy.deepcopy(artifact)

    publisher.write_artifact(_VALID_KEY, artifact)

    assert artifact == original


def test_publisher_source_has_no_marker_reconciliation_sweep_disposal_references():
    source_lower = inspect.getsource(publisher_module).lower()
    for forbidden in (
        "markerstore",
        "retentionservice",
        "custodysweepclient",
        "marker",
        "reconcil",
        "sweep",
        "disposal",
    ):
        assert forbidden not in source_lower, f"publisher.py unexpectedly references {forbidden!r}"
