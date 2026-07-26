"""Tests for the reusable DynamoDB TransactWriteItems hold-state
coordination mechanism (Legal-Hold Correction B1; Technical Design Section
19.4; ADR Non-Negotiable Invariants 11/12/14).

No Category 1/2 write path is wired to this mechanism anywhere in the
codebase yet (that is subphases C+D/E/F, not B1) -- every test below proves
the mechanism using a caller-supplied governed-item builder standing in for
a hypothetical governed record's own Put, exactly as B1's own scope note
requires ("no orchestration beyond what's needed to prove the DynamoDB
coordination foundation works end-to-end in a test").
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldCoordinatedTransactionRunner,
    HoldStateConcurrencyExceededError,
    build_hold_version_condition_check_item,
    compute_ttl_disposal_at,
)

_TABLE = "test-table"
_CLIENT_ID = "client1"
_AUDIT_ID = "audit1"
_HOLD_KEY = {"PK": f"CLIENT#{_CLIENT_ID}", "SK": f"AUDIT#{_AUDIT_ID}#LEGALHOLD"}

# A fixed, unrelated governed-record item this test suite uses in place of a
# real Category 1/2 write path (e.g. RunMetadata's put_started_once) -- the
# exact shape does not matter to the coordination mechanism, only that it is
# a well-formed transact-item with its own ConditionExpression.
_GOVERNED_PUT_ITEM = {
    "Put": {
        "TableName": _TABLE,
        "Item": {"PK": {"S": f"CLIENT#{_CLIENT_ID}"}, "SK": {"S": f"AUDIT#{_AUDIT_ID}#RUN#run1"}},
        "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
    }
}


class _FakeHoldRepository:
    """Returns a pre-scripted sequence of hold-state reads, one per call --
    lets a test simulate the hold state changing between transaction
    attempts without needing a real DynamoDB double."""

    def __init__(self, hold_states: list[dict[str, Any] | None]) -> None:
        self._hold_states = list(hold_states)
        self.calls = 0

    def get_legal_hold(self, client_id: str, audit_id: str) -> dict[str, Any] | None:
        index = min(self.calls, len(self._hold_states) - 1)
        self.calls += 1
        return self._hold_states[index]


def _cancellation_error(reasons: list[dict[str, Any]]) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
            "CancellationReasons": reasons,
        },
        "TransactWriteItems",
    )


def _condition_failed() -> dict[str, Any]:
    return {"Code": "ConditionalCheckFailedException", "Message": "condition failed"}


def _builder_with_governed_items(
    governed_items: list[dict[str, Any]],
) -> Any:
    def build(hold_state: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        condition_item = build_hold_version_condition_check_item(_TABLE, _HOLD_KEY, hold_state)
        return governed_items, condition_item

    return build


# ---------------------------------------------------------------------------
# build_hold_version_condition_check_item
# ---------------------------------------------------------------------------


def test_condition_check_uses_attribute_not_exists_when_no_hold_ever_placed():
    item = build_hold_version_condition_check_item(_TABLE, _HOLD_KEY, None)
    check = item["ConditionCheck"]
    assert check["ConditionExpression"] == "attribute_not_exists(PK)"
    assert "ExpressionAttributeValues" not in check


def test_condition_check_pins_exact_hold_version_when_hold_exists():
    hold_state = {"status": "ACTIVE", "hold_version": 7}
    item = build_hold_version_condition_check_item(_TABLE, _HOLD_KEY, hold_state)
    check = item["ConditionCheck"]
    assert check["ConditionExpression"] == "hold_version = :expected_hold_version"
    assert check["ExpressionAttributeValues"][":expected_hold_version"] == {"N": "7"}


# ---------------------------------------------------------------------------
# compute_ttl_disposal_at
# ---------------------------------------------------------------------------


def test_ttl_disposal_at_omitted_when_hold_active():
    assert compute_ttl_disposal_at({"status": "ACTIVE"}, custody_expires_at=1000) is None


@pytest.mark.parametrize(
    "hold_state", [None, {"status": "RELEASED"}], ids=["never-held", "released"]
)
def test_ttl_disposal_at_present_when_not_actively_held(hold_state):
    assert compute_ttl_disposal_at(hold_state, custody_expires_at=1000) == 1000


# ---------------------------------------------------------------------------
# HoldCoordinatedTransactionRunner — success paths
# ---------------------------------------------------------------------------


def test_run_commits_on_first_attempt_with_no_prior_hold():
    dynamodb_client = MagicMock()
    hold_repository = _FakeHoldRepository([None])
    runner = HoldCoordinatedTransactionRunner(dynamodb_client, hold_repository)

    result = runner.run(_CLIENT_ID, _AUDIT_ID, _builder_with_governed_items([_GOVERNED_PUT_ITEM]))

    assert result is None
    dynamodb_client.transact_write_items.assert_called_once()
    transact_items = dynamodb_client.transact_write_items.call_args.kwargs["TransactItems"]
    assert len(transact_items) == 2
    assert transact_items[0] == _GOVERNED_PUT_ITEM
    assert transact_items[1]["ConditionCheck"]["ConditionExpression"] == "attribute_not_exists(PK)"


def test_run_commits_with_existing_hold_state_returned():
    dynamodb_client = MagicMock()
    hold_state = {"status": "RELEASED", "hold_version": 3}
    hold_repository = _FakeHoldRepository([hold_state])
    runner = HoldCoordinatedTransactionRunner(dynamodb_client, hold_repository)

    result = runner.run(_CLIENT_ID, _AUDIT_ID, _builder_with_governed_items([_GOVERNED_PUT_ITEM]))

    assert result == hold_state


# ---------------------------------------------------------------------------
# Required behavior 9/10: stale hold_version causes transactional rejection
# and a bounded, deterministic retry.
# ---------------------------------------------------------------------------


def test_run_retries_when_only_hold_condition_fails_then_succeeds():
    dynamodb_client = MagicMock()
    # Attempt 1: governed item's own condition passes, hold ConditionCheck
    # fails (a concurrent PLACE/RELEASE raced this write).
    first_attempt_error = _cancellation_error([{"Code": "None"}, _condition_failed()])
    dynamodb_client.transact_write_items.side_effect = [first_attempt_error, None]

    hold_repository = _FakeHoldRepository(
        [{"status": "ACTIVE", "hold_version": 1}, {"status": "ACTIVE", "hold_version": 2}]
    )
    runner = HoldCoordinatedTransactionRunner(dynamodb_client, hold_repository)

    build_calls: list[dict[str, Any] | None] = []

    def build(hold_state: dict[str, Any] | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        build_calls.append(hold_state)
        condition_item = build_hold_version_condition_check_item(_TABLE, _HOLD_KEY, hold_state)
        return [_GOVERNED_PUT_ITEM], condition_item

    result = runner.run(_CLIENT_ID, _AUDIT_ID, build)

    assert dynamodb_client.transact_write_items.call_count == 2
    assert result == {"status": "ACTIVE", "hold_version": 2}
    # The retry re-read fresh hold state -- proves the mechanism re-derives
    # against the *current* hold_version, not the stale one.
    assert build_calls[0]["hold_version"] == 1
    assert build_calls[1]["hold_version"] == 2


def test_run_retries_on_transient_cancellation_unrelated_to_either_condition():
    dynamodb_client = MagicMock()
    transient_error = _cancellation_error([{"Code": "None"}, {"Code": "None"}])
    dynamodb_client.transact_write_items.side_effect = [transient_error, None]

    hold_repository = _FakeHoldRepository([None, None])
    runner = HoldCoordinatedTransactionRunner(dynamodb_client, hold_repository)

    runner.run(_CLIENT_ID, _AUDIT_ID, _builder_with_governed_items([_GOVERNED_PUT_ITEM]))

    assert dynamodb_client.transact_write_items.call_count == 2


# ---------------------------------------------------------------------------
# Required behavior 11: retry exhaustion fails closed, never an unconditioned
# fallback write.
# ---------------------------------------------------------------------------


def test_run_raises_hold_state_concurrency_exceeded_after_max_attempts():
    dynamodb_client = MagicMock()
    always_fails_hold_condition = _cancellation_error([{"Code": "None"}, _condition_failed()])
    dynamodb_client.transact_write_items.side_effect = always_fails_hold_condition

    hold_repository = _FakeHoldRepository(
        [{"status": "ACTIVE", "hold_version": n} for n in range(1, 10)]
    )
    runner = HoldCoordinatedTransactionRunner(dynamodb_client, hold_repository, max_attempts=3)

    with pytest.raises(HoldStateConcurrencyExceededError) as exc_info:
        runner.run(_CLIENT_ID, _AUDIT_ID, _builder_with_governed_items([_GOVERNED_PUT_ITEM]))

    assert exc_info.value.error_type == "HOLD_STATE_CONCURRENCY_EXCEEDED"
    assert isinstance(exc_info.value, StorageError)
    assert dynamodb_client.transact_write_items.call_count == 3

    # Every attempt, including the final exhausted one, included the hold
    # ConditionCheck -- never an unconditioned fallback write.
    for call in dynamodb_client.transact_write_items.call_args_list:
        transact_items = call.kwargs["TransactItems"]
        assert any("ConditionCheck" in item for item in transact_items)


def test_run_respects_custom_max_attempts():
    dynamodb_client = MagicMock()
    always_fails_hold_condition = _cancellation_error([{"Code": "None"}, _condition_failed()])
    dynamodb_client.transact_write_items.side_effect = always_fails_hold_condition

    hold_repository = _FakeHoldRepository([{"status": "ACTIVE", "hold_version": 1}] * 10)
    runner = HoldCoordinatedTransactionRunner(dynamodb_client, hold_repository, max_attempts=1)

    with pytest.raises(HoldStateConcurrencyExceededError):
        runner.run(_CLIENT_ID, _AUDIT_ID, _builder_with_governed_items([_GOVERNED_PUT_ITEM]))

    assert dynamodb_client.transact_write_items.call_count == 1


# ---------------------------------------------------------------------------
# Required behavior 12: dual failure precedence -- the governed record's own
# condition failure takes precedence over the hold ConditionCheck failure,
# and is never masked behind a hold-version retry loop.
# ---------------------------------------------------------------------------


class _DummyDuplicateError(Exception):
    pass


def test_governed_condition_failure_takes_precedence_over_hold_condition_failure():
    dynamodb_client = MagicMock()
    # Both the governed item's own condition AND the hold ConditionCheck
    # fail in the very same attempt.
    dual_failure = _cancellation_error([_condition_failed(), _condition_failed()])
    dynamodb_client.transact_write_items.side_effect = dual_failure

    hold_repository = _FakeHoldRepository([{"status": "ACTIVE", "hold_version": 1}] * 10)
    runner = HoldCoordinatedTransactionRunner(dynamodb_client, hold_repository)

    def on_governed_condition_failed(reasons: list[dict[str, Any]]) -> None:
        raise _DummyDuplicateError("simulated write path's own duplicate-write error")

    with pytest.raises(_DummyDuplicateError):
        runner.run(
            _CLIENT_ID,
            _AUDIT_ID,
            _builder_with_governed_items([_GOVERNED_PUT_ITEM]),
            on_governed_condition_failed=on_governed_condition_failed,
        )

    # No retry occurred -- a genuine duplicate-write condition must never be
    # retried behind a hold-version retry loop (Technical Design Section
    # 19.4 step 4).
    dynamodb_client.transact_write_items.assert_called_once()


def test_governed_condition_failure_without_callback_reraises_raw_client_error():
    dynamodb_client = MagicMock()
    dual_failure = _cancellation_error([_condition_failed(), _condition_failed()])
    dynamodb_client.transact_write_items.side_effect = dual_failure

    hold_repository = _FakeHoldRepository([{"status": "ACTIVE", "hold_version": 1}])
    runner = HoldCoordinatedTransactionRunner(dynamodb_client, hold_repository)

    with pytest.raises(ClientError):
        runner.run(_CLIENT_ID, _AUDIT_ID, _builder_with_governed_items([_GOVERNED_PUT_ITEM]))

    dynamodb_client.transact_write_items.assert_called_once()


def test_governed_condition_failure_with_multi_item_governed_write_still_takes_precedence():
    """Phase 4's put_records_once extends a 5-item set, not a single Put --
    the precedence check must inspect all governed items' reasons, not just
    the first."""
    dynamodb_client = MagicMock()
    governed_items = [_GOVERNED_PUT_ITEM, _GOVERNED_PUT_ITEM, _GOVERNED_PUT_ITEM]
    # Third governed item's own condition fails; hold ConditionCheck (index 3) also fails.
    reasons = [{"Code": "None"}, {"Code": "None"}, _condition_failed(), _condition_failed()]
    dynamodb_client.transact_write_items.side_effect = _cancellation_error(reasons)

    hold_repository = _FakeHoldRepository([{"status": "ACTIVE", "hold_version": 1}] * 5)
    runner = HoldCoordinatedTransactionRunner(dynamodb_client, hold_repository)

    callback_invocations = []

    with pytest.raises(ClientError):
        runner.run(
            _CLIENT_ID,
            _AUDIT_ID,
            _builder_with_governed_items(governed_items),
            on_governed_condition_failed=callback_invocations.append,
        )

    assert len(callback_invocations) == 1
    dynamodb_client.transact_write_items.assert_called_once()


# ---------------------------------------------------------------------------
# Non-condition DynamoDB failures are surfaced normally, not retried as a
# hold-state race.
# ---------------------------------------------------------------------------


def test_run_surfaces_unrelated_client_error_without_retry():
    dynamodb_client = MagicMock()
    resource_not_found = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "no such table"}},
        "TransactWriteItems",
    )
    dynamodb_client.transact_write_items.side_effect = resource_not_found

    hold_repository = _FakeHoldRepository([None])
    runner = HoldCoordinatedTransactionRunner(dynamodb_client, hold_repository)

    with pytest.raises(StorageError):
        runner.run(_CLIENT_ID, _AUDIT_ID, _builder_with_governed_items([_GOVERNED_PUT_ITEM]))

    dynamodb_client.transact_write_items.assert_called_once()
