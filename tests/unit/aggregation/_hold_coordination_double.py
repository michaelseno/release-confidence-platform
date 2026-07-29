"""Shared low-level DynamoDB test double for Evidence Governance Workstream
A1.3c.1 hold-coordinated TransactWriteItems tests.

Reuses A1.LH3's established wire-format TransactWriteItems/CancellationReasons
test-double pattern (tests/unit/test_run_metadata_custody_fields.py,
tests/integration/test_phase4a7_aggregation_envelope_compatibility.py's
_LowLevelClient) rather than inventing a new fake shape: a real
per-(PK, SK) typed-AttributeValue store backs genuine attribute_not_exists /
hold_version condition evaluation, so ConditionalCheckFailedException /
TransactionCanceledException / CancellationReasons behavior is a faithful
simulation of real DynamoDB wire format, not a hand-rolled shortcut.

This double additionally supports index-targeted forced-failure injection
(``force_fail_indices_by_attempt``) so cancellation-index tests can
deterministically choose which submitted transact-item index fails on a
given attempt, independent of what the "real" per-key state would otherwise
produce -- required to exercise Technical Design Section 19.4 step 4's
governed-vs-hold-condition precedence rule at specific, chosen positions
(first/middle/last governed index, the hold-check index alone, and a
governed index + the hold-check index together) rather than only whatever
combination naturally falls out of real state.
"""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.evidence_retention.constants import (
    HOLD_STATUS_ACTIVE,
    HOLD_STATUS_RELEASED,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository


class RecordingHoldAwareClient:
    """Low-level `boto3.client("dynamodb")`-shaped double.

    Backs both `HoldRepository` (get_item/put_item/update_item) and
    `HoldCoordinatedTransactionRunner` (transact_write_items) against ONE
    shared, real per-key typed-item store -- exactly the single-client
    wiring `apps/backend/handlers/aggregation_handler.py` uses in
    production.
    """

    def __init__(self) -> None:
        self.storage: dict[tuple[str, str], dict[str, Any]] = {}
        self.transact_calls: list[list[dict[str, Any]]] = []
        self.get_item_calls: list[dict[str, Any]] = []
        # 1-based attempt number -> set of 0-based indices (within that
        # attempt's SUBMITTED TransactItems list) to force
        # ConditionalCheckFailed on, regardless of real evaluation outcome.
        self.force_fail_indices_by_attempt: dict[int, set[int]] = {}
        self._attempt = 0

    # -- HoldRepository / AggregationRepository dependency surface --------

    def get_item(self, Key: dict[str, Any], **_: Any) -> dict[str, Any]:
        self.get_item_calls.append(Key)
        item = self.storage.get((Key["PK"]["S"], Key["SK"]["S"]))
        return {"Item": item} if item else {}

    def query(
        self,
        KeyConditionExpression: str,
        ExpressionAttributeValues: dict[str, Any],
        **_: Any,
    ) -> dict[str, Any]:
        pk = ExpressionAttributeValues[":pk"]["S"]
        sk_prefix = ExpressionAttributeValues[":sk_prefix"]["S"]
        items = [
            item
            for (item_pk, item_sk), item in self.storage.items()
            if item_pk == pk and item_sk.startswith(sk_prefix)
        ]
        return {"Items": items}

    def put_item(
        self, Item: dict[str, Any], ConditionExpression: str | None = None, **_: Any
    ) -> dict[str, Any]:
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
        Key: dict[str, Any],
        UpdateExpression: str,
        ExpressionAttributeValues: dict[str, Any],
        ExpressionAttributeNames: dict[str, str] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        pk, sk = Key["PK"]["S"], Key["SK"]["S"]
        existing = self.storage.get((pk, sk)) or {"PK": Key["PK"], "SK": Key["SK"]}
        names = ExpressionAttributeNames or {}
        for placeholder, attr_name in names.items():
            val_placeholder = UpdateExpression.split(f"{placeholder} = ")[1].split(",")[0].strip()
            existing[attr_name] = ExpressionAttributeValues[val_placeholder]
        self.storage[(pk, sk)] = existing
        return {}

    def transact_write_items(self, TransactItems: list[dict[str, Any]]) -> dict[str, Any]:
        self._attempt += 1
        self.transact_calls.append(TransactItems)
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
                if (pk, sk) in self.storage:
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
    """Test helper: durably commit an ACTIVE LegalHold via the real
    HoldRepository CRUD surface (never hand-rolled typed items) so every
    read a test exercises goes through the same decode path production
    does."""
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
    """Test helper: durably commit a RELEASED LegalHold via the real
    HoldRepository CRUD surface."""
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
