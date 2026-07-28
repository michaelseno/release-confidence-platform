"""Regression tests: phone-like UUID keys must persist unsanitized through DynamoDB client."""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from packages.core.constants.engine import RUN_STATUS_COMPLETED, RUN_STATUS_STARTED
from packages.storage.dynamodb_client import DynamoDBMetadataClient
from release_confidence_platform.storage.dynamodb_codec import decode_item

# This specific UUID is the canonical regression fixture: PHONE_PATTERN matches
# the digit sequence "2475004829" within the UUID hex, which previously caused
# sanitize() to mutate the key to "...#RUN#48a87626-e2f9-4f81-82ff-[REDACTED]ec".
PHONE_LIKE_UUID = "48a87626-e2f9-4f81-82ff-2475004829ec"
AUDIT_ID = "audit_test"
CLIENT_ID = "client_test"


class CapturingDynamoStub:
    """In-memory DynamoDB stub that captures put_item call arguments."""

    def __init__(self):
        self.put_item_calls: list[dict[str, Any]] = []
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def put_item(self, TableName, Item, ConditionExpression, **kwargs):  # noqa: N803, ARG002
        key = (Item["PK"], Item["SK"])
        if key in self.items:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem"
            )
        self.put_item_calls.append({"Item": Item})
        self.items[key] = Item
        return {}

    def update_item(self, TableName, Key, **kwargs):  # noqa: N803, ARG002
        key = (Key["PK"], Key["SK"])
        if key not in self.items:
            raise ClientError(
                {"Error": {"Code": "ConditionalCheckFailedException"}}, "UpdateItem"
            )
        names = kwargs.get("ExpressionAttributeNames", {})
        values = kwargs.get("ExpressionAttributeValues", {})
        for index, field_name in enumerate(names.values()):
            self.items[key][field_name] = values[f":v{index}"]
        return {}

    def transact_write_items(self, TransactItems):  # noqa: N803
        # Evidence Governance Workstream A1.LH3: put_started_once now writes
        # via TransactWriteItems (wire-format Item). No LegalHold record is
        # ever stored by this stub (paired with _NoLegalHoldRepository
        # below), so the ConditionCheck item always trivially passes; only
        # the governed Put item's own condition can fail, preserving this
        # stub's pre-existing duplicate-write behavior unchanged. The
        # decoded (plain-Python) item is recorded into put_item_calls too,
        # so this file's existing byte-identity assertions against
        # stub.put_item_calls[0]["Item"] are unaffected by the encode/decode
        # round trip.
        reasons = []
        any_failed = False
        for transact_item in TransactItems:
            if "Put" in transact_item:
                item = decode_item(transact_item["Put"]["Item"])
                key = (item["PK"], item["SK"])
                if key in self.items:
                    reasons.append({"Code": "ConditionalCheckFailed"})
                    any_failed = True
                else:
                    reasons.append({"Code": "None"})
            else:
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
                item = decode_item(transact_item["Put"]["Item"])
                self.put_item_calls.append({"Item": item})
                self.items[(item["PK"], item["SK"])] = item
        return {}


class _NoLegalHoldRepository:
    def get_legal_hold(self, client_id, audit_id, *, consistent_read=False):  # noqa: ARG002
        return None

    def legal_hold_key(self, client_id, audit_id):
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#LEGALHOLD"}


_NO_HOLD = _NoLegalHoldRepository()


def _make_item(run_id: str) -> dict[str, Any]:
    client = DynamoDBMetadataClient("test_table", None)
    keys = client.keys(CLIENT_ID, AUDIT_ID, run_id)
    return {
        **keys,
        "client_id": CLIENT_ID,
        "audit_id": AUDIT_ID,
        "run_id": run_id,
        "status": RUN_STATUS_STARTED,
        "raw_result_s3_key": None,
        "raw_result_version": "v1",
        "started_at": "2026-06-12T00:00:00Z",
        "completed_at": None,
        "failure_summary": None,
    }


def test_put_started_once_phone_like_uuid_persists_unsanitized_keys():
    """A-01: put_started_once must persist PK, SK, and run_id byte-identical to the input UUID."""
    stub = CapturingDynamoStub()
    client = DynamoDBMetadataClient("test_table", stub, _NO_HOLD)

    item = _make_item(PHONE_LIKE_UUID)
    client.put_started_once(item)

    assert len(stub.put_item_calls) == 1
    persisted = stub.put_item_calls[0]["Item"]

    expected_sk = f"AUDIT#{AUDIT_ID}#RUN#{PHONE_LIKE_UUID}"
    assert persisted["SK"] == expected_sk, (
        f"SK was mutated before persistence: got {persisted['SK']!r}, expected {expected_sk!r}"
    )
    assert persisted["run_id"] == PHONE_LIKE_UUID, (
        f"run_id was mutated before persistence: got {persisted['run_id']!r}"
    )
    assert "[REDACTED]" not in persisted["SK"]
    assert "[REDACTED]" not in persisted["run_id"]


def test_update_terminal_key_matches_put_started_once_key_for_phone_like_uuid():
    """A-03: update_terminal must succeed when the item key matches what put_started_once wrote."""
    stub = CapturingDynamoStub()
    client = DynamoDBMetadataClient("test_table", stub, _NO_HOLD)

    item = _make_item(PHONE_LIKE_UUID)
    client.put_started_once(item)

    terminal_key = client.keys(CLIENT_ID, AUDIT_ID, PHONE_LIKE_UUID)
    # This must not raise ConditionalCheckFailedException — the key written by
    # put_started_once must match the key passed to update_terminal.
    client.update_terminal(
        terminal_key,
        {
            "status": RUN_STATUS_COMPLETED,
            "completed_at": "2026-06-12T00:01:00Z",
            "raw_result_s3_key": f"raw-results/{CLIENT_ID}/{AUDIT_ID}/{PHONE_LIKE_UUID}/results.json",  # noqa: E501
        },
    )

    # Verify the item was updated under the correct key
    stored_key = (f"CLIENT#{CLIENT_ID}", f"AUDIT#{AUDIT_ID}#RUN#{PHONE_LIKE_UUID}")
    assert stub.items[stored_key]["status"] == RUN_STATUS_COMPLETED
