"""Evidence Governance Workstream A1.3b/A1.3b.1 --
packages/storage/dynamodb_client.py custody-field and evidence_class tests.

Covers Technical Design Section 18.1 (Category 2 -- evidence-derived
artifact) and Section 11 rows 1-2 (RunMetadata CREATE / FINALIZATION):

  * put_started_once computes custody_expires_at/ttl_disposal_at from
    CUSTODY_PERIOD_DAYS_RAW_EVIDENCE at write time, never a hardcoded
    duration (ADR Non-Negotiable Invariant 3).
  * put_started_once fails closed (raises StorageError,
    CUSTODY_PERIOD_CONFIG_MISSING) rather than silently writing the record
    without the custody fields when that configuration is unresolvable.
  * update_terminal (FINALIZATION, not regeneration -- RunMetadata has no
    regeneration path) never touches either field.
  * (A1.3b.1) put_started_once also persists a fixed, non-caller-overridable
    evidence_class="raw_evidence" attribute, a member of the bounded
    EVIDENCE_CLASSES set, per TD Section 18.1's Category 2 table -- the gap
    the TD itself disclosed as left open by the original A1.3b round.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from botocore.exceptions import ClientError

from packages.core.constants.engine import RUN_STATUS_COMPLETED, RUN_STATUS_STARTED
from packages.core.exceptions import DuplicateRunIdError, StorageError
from packages.storage.dynamodb_client import (
    CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR,
    DynamoDBMetadataClient,
)
from release_confidence_platform.evidence_retention.constants import EVIDENCE_CLASSES

CLIENT_ID = "client1"
AUDIT_ID = "audit1"
RUN_ID = "run1"

_SECONDS_PER_DAY = 86400


class CapturingDynamoStub:
    """In-memory DynamoDB stub recording put_item/update_item calls."""

    def __init__(self) -> None:
        self.put_item_calls: list[dict[str, Any]] = []
        self.update_item_calls: list[dict[str, Any]] = []
        self.items: dict[tuple[str, str], dict[str, Any]] = {}

    def put_item(self, TableName, Item, ConditionExpression, **kwargs):  # noqa: N803, ARG002
        key = (Item["PK"], Item["SK"])
        if key in self.items:
            raise ClientError({"Error": {"Code": "ConditionalCheckFailedException"}}, "PutItem")
        self.put_item_calls.append({"Item": Item})
        self.items[key] = dict(Item)
        return {}

    def update_item(self, TableName, Key, **kwargs):  # noqa: N803, ARG002
        self.update_item_calls.append({"Key": Key, **kwargs})
        key = (Key["PK"], Key["SK"])
        names = kwargs.get("ExpressionAttributeNames", {})
        values = kwargs.get("ExpressionAttributeValues", {})
        stored = self.items.setdefault(key, dict(Key))
        for index, field_name in enumerate(names.values()):
            stored[field_name] = values[f":v{index}"]
        return {}


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


# ---------------------------------------------------------------------------
# put_started_once -- custody fields present and correctly computed
# ---------------------------------------------------------------------------


def test_put_started_once_sets_custody_fields_from_env_config(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    stub = CapturingDynamoStub()
    client = DynamoDBMetadataClient("test_table", stub)

    before = int(time.time())
    client.put_started_once(_make_item())
    after = int(time.time())

    persisted = stub.put_item_calls[0]["Item"]
    assert "custody_expires_at" in persisted
    assert "ttl_disposal_at" in persisted
    # Ordinary CREATE: no hold can exist yet for a record that doesn't exist
    # yet, so ttl_disposal_at == custody_expires_at unconditionally.
    assert persisted["custody_expires_at"] == persisted["ttl_disposal_at"]
    assert (before + 30 * _SECONDS_PER_DAY) <= persisted["custody_expires_at"]
    assert persisted["custody_expires_at"] <= (after + 30 * _SECONDS_PER_DAY)


def test_put_started_once_does_not_mutate_caller_supplied_item(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    stub = CapturingDynamoStub()
    client = DynamoDBMetadataClient("test_table", stub)
    item = _make_item()

    client.put_started_once(item)

    assert "custody_expires_at" not in item
    assert "ttl_disposal_at" not in item


def test_custody_expires_at_is_not_hardcoded_and_scales_with_configured_days(monkeypatch):
    """Mirrors A1.1/A1.2's own no-hardcoded-duration test pattern: two
    different configured custody-period-days values must produce
    proportionally different custody_expires_at outputs, proving the value
    is derived from configuration read at write time, never a fixed
    number."""
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "10")
    stub_a = CapturingDynamoStub()
    DynamoDBMetadataClient("test_table", stub_a).put_started_once(_make_item())
    first = stub_a.put_item_calls[0]["Item"]["custody_expires_at"]

    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "40")
    stub_b = CapturingDynamoStub()
    DynamoDBMetadataClient("test_table", stub_b).put_started_once(_make_item())
    second = stub_b.put_item_calls[0]["Item"]["custody_expires_at"]

    # Both writes happen within this test's own short execution window, so a
    # 30-day delta in configured custody period must show up as an
    # (approximately) matching delta in the computed expiry -- a hardcoded
    # duration would produce identical or unrelated outputs here.
    delta_days = (second - first) / _SECONDS_PER_DAY
    assert 29.9 <= delta_days <= 30.1


# ---------------------------------------------------------------------------
# put_started_once -- evidence_class (A1.3b.1 correction)
# ---------------------------------------------------------------------------


def test_put_started_once_sets_evidence_class_raw_evidence(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    stub = CapturingDynamoStub()
    client = DynamoDBMetadataClient("test_table", stub)

    client.put_started_once(_make_item())

    persisted = stub.put_item_calls[0]["Item"]
    assert persisted["evidence_class"] == "raw_evidence"


def test_run_metadata_evidence_class_is_member_of_bounded_evidence_classes(monkeypatch):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    stub = CapturingDynamoStub()
    client = DynamoDBMetadataClient("test_table", stub)

    client.put_started_once(_make_item())

    persisted = stub.put_item_calls[0]["Item"]
    assert persisted["evidence_class"] in EVIDENCE_CLASSES


def test_put_started_once_caller_cannot_override_evidence_class(monkeypatch):
    """A caller-supplied item that already contains a *different*
    evidence_class value must not be able to override the hardcoded
    "raw_evidence" value -- evidence_class is fixed and non-caller-
    controlled for this write path (TD Section 18.1 Category 2)."""
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    stub = CapturingDynamoStub()
    client = DynamoDBMetadataClient("test_table", stub)
    item = _make_item()
    item["evidence_class"] = "certificate"  # attempted override

    client.put_started_once(item)

    persisted = stub.put_item_calls[0]["Item"]
    assert persisted["evidence_class"] == "raw_evidence"
    # The caller's own dict must also remain unmutated (existing invariant),
    # so its attempted override value is untouched on its side too.
    assert item["evidence_class"] == "certificate"


# ---------------------------------------------------------------------------
# put_started_once -- fail closed when custody-period config is unresolvable
# ---------------------------------------------------------------------------


def test_put_started_once_fails_closed_when_custody_period_env_var_unset(monkeypatch):
    monkeypatch.delenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, raising=False)
    stub = CapturingDynamoStub()
    client = DynamoDBMetadataClient("test_table", stub)

    with pytest.raises(StorageError) as exc:
        client.put_started_once(_make_item())

    assert exc.value.error_type == "CUSTODY_PERIOD_CONFIG_MISSING"
    # The write must never have been attempted -- fail closed, not a
    # partial/silent write missing the custody fields.
    assert stub.put_item_calls == []
    # All-or-nothing: no partial record (e.g. evidence_class alone, or
    # custody fields without evidence_class) was ever written -- there is no
    # stored item under this key at all.
    keys = client.keys(CLIENT_ID, AUDIT_ID, RUN_ID)
    assert (keys["PK"], keys["SK"]) not in stub.items


@pytest.mark.parametrize("bad_value", ["", "0", "-5", "not-a-number", "3.5"])
def test_put_started_once_fails_closed_for_invalid_custody_period_values(monkeypatch, bad_value):
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, bad_value)
    stub = CapturingDynamoStub()
    client = DynamoDBMetadataClient("test_table", stub)

    with pytest.raises(StorageError) as exc:
        client.put_started_once(_make_item())

    assert exc.value.error_type == "CUSTODY_PERIOD_CONFIG_MISSING"
    assert stub.put_item_calls == []


# ---------------------------------------------------------------------------
# put_started_once -- repeated CREATE attempts (idempotency contract)
# ---------------------------------------------------------------------------


def test_put_started_once_repeated_call_raises_duplicate_run_id_error(monkeypatch):
    """Verifies, not assumes, the existing public idempotency contract:
    a second put_started_once call for the same (PK, SK) is rejected outright
    by the existing ConditionExpression, raising DuplicateRunIdError -- not
    converted into an idempotent no-op, and not silently accepted with a
    second (possibly different) evidence_class value. Since evidence_class is
    a fixed constant, not caller-supplied, there is no code path where two
    different values could ever be attempted for the same key; this test
    proves the rejection itself, not a hypothetical value conflict."""
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    stub = CapturingDynamoStub()
    client = DynamoDBMetadataClient("test_table", stub)

    client.put_started_once(_make_item())
    keys = client.keys(CLIENT_ID, AUDIT_ID, RUN_ID)
    first_persisted = dict(stub.items[(keys["PK"], keys["SK"])])

    with pytest.raises(DuplicateRunIdError):
        client.put_started_once(_make_item())

    # Exactly one successful put_item call was ever recorded.
    assert len(stub.put_item_calls) == 1
    # The first-written record (including its evidence_class) is unaffected
    # by the second, rejected attempt.
    stored_after_rejection = stub.items[(keys["PK"], keys["SK"])]
    assert stored_after_rejection == first_persisted
    assert stored_after_rejection["evidence_class"] == "raw_evidence"


# ---------------------------------------------------------------------------
# update_terminal -- negative test: never touches custody fields
# ---------------------------------------------------------------------------


def test_update_terminal_never_touches_custody_fields(monkeypatch):
    """update_terminal is a FINALIZATION transition on an existing
    RunMetadata record, not a regeneration -- RunMetadata has no
    regeneration path at all (Technical Design Section 18.1). This must
    never set, recompute, remove, or otherwise reference
    custody_expires_at/ttl_disposal_at/evidence_class, regardless of what
    custody configuration is present at call time."""
    monkeypatch.setenv(CUSTODY_PERIOD_DAYS_RAW_EVIDENCE_ENV_VAR, "30")
    stub = CapturingDynamoStub()
    client = DynamoDBMetadataClient("test_table", stub)
    client.put_started_once(_make_item())

    key = client.keys(CLIENT_ID, AUDIT_ID, RUN_ID)
    original = stub.items[(key["PK"], key["SK"])]
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

    # Positive check: the fields survive untouched.
    stored = stub.items[(key["PK"], key["SK"])]
    assert stored["custody_expires_at"] == original_custody_expires_at
    assert stored["ttl_disposal_at"] == original_ttl_disposal_at
    assert stored["evidence_class"] == original_evidence_class
    assert stored["status"] == RUN_STATUS_COMPLETED

    # Negative test proper: inspect the actual UpdateExpression update_terminal
    # issued and assert none of the three field names was ever named in it --
    # not just "the stored value happens to be unchanged," which could pass
    # even if update_terminal set the field to the same value it already had.
    update_call = stub.update_item_calls[-1]
    touched_attribute_names = set(update_call.get("ExpressionAttributeNames", {}).values())
    assert "custody_expires_at" not in touched_attribute_names
    assert "ttl_disposal_at" not in touched_attribute_names
    assert "evidence_class" not in touched_attribute_names
