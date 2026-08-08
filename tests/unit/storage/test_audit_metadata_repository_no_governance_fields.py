"""Evidence Governance Workstream A1.3e -- negative regression coverage for
`AuditMetadataRepository` (Technical Design Section 18.1, 18.3).

`AuditMetadataRepository` governs two distinct categories from the six-way
classification in Technical Design Section 18.1, and both are covered here
because they share one production class, genuinely duplicated across two
independently-maintained trees (`packages/storage/audit_metadata_client.py`
for Lambda, `src/release_confidence_platform/storage/audit_metadata_client.py`
for the CLI -- confirmed structurally identical method sets, Section 18.5):

- Category 6 (`AuditMetadata` -- items 4a-4g): the canonical audit-anchor
  record. Explicitly excluded from custody-field treatment (Section 18.1);
  whether it should ever be disposed under a cascading rule is a distinct,
  unresolved question this task does not touch.
- Category 3 (operational coordination metadata -- items 4h-4k): the
  `AggregationJobIntent`/`ScheduleOccurrenceClaim` write paths this class
  also governs. Purely operational, no standalone evidentiary value, and
  permanently excluded from custody-field treatment (Section 18.1).

Section 18.3 explains why this is test-level enforcement, not a runtime
guard: these are existing, locked write methods this workstream has no
other reason to touch, and their semantics already prevent the invariant by
simple omission -- they have never set, and must continue to never set,
`custody_expires_at`/`ttl_disposal_at`/`evidence_class`/`hold_version`. A
regression that started setting one of these fields on any of the methods
below would fail the corresponding test immediately.

Each test constructs the REAL `AuditMetadataRepository` (from each tree)
against a recording double standing in for the low-level DynamoDB client,
calls the real method with a realistic, minimal argument set, and inspects
the actual `put_item`/`update_item` kwargs the repository constructed --
not the caller's input.

For PutItem-shaped calls, the assertion checks that none of the four
governance field names are keys in the captured `Item`. This is a
repository-boundary check: `src/`'s `_call` additionally encodes `Item`
into low-level DynamoDB AttributeValue format
(`dynamodb_codec.encode_dynamodb_call_kwargs`) before handing it to the
client, while `packages/`'s `_call` does not encode at all -- but
`encode_item` preserves top-level keys unchanged (it only transforms each
key's *value* into an AttributeValue wrapper), so a plain "is this key
present" check is valid and equivalent across both trees without decoding.

For UpdateItem-shaped calls, the assertion checks that none of the four
governance field names appear as *values* in the captured
`ExpressionAttributeNames` dict (i.e. as the real attribute name a
placeholder like `#f0` maps to). `ExpressionAttributeNames` is never
touched by `encode_dynamodb_call_kwargs`, so this dict is identical,
unencoded, in both trees.
"""

from __future__ import annotations

from typing import Any

import pytest

from packages.storage.audit_metadata_client import AuditMetadataRepository as PkgRepo
from release_confidence_platform.storage.audit_metadata_client import (
    AuditMetadataRepository as SrcRepo,
)

GOVERNANCE_FIELD_NAMES = (
    "custody_expires_at",
    "ttl_disposal_at",
    "evidence_class",
    "hold_version",
)

_REPO_CLASSES = [PkgRepo, SrcRepo]
_REPO_IDS = ["packages", "src"]


class _RecordingDynamoClient:
    """Minimal low-level-shaped stub recording put_item/update_item calls,
    mirroring test_update_job_custody_guard.py's `_RecordingDynamoClient`
    pattern. Accepts arbitrary kwargs (including a `TableName` kwarg) so
    both the encoding `src/` tree and the non-encoding `packages/` tree
    reach this double's real method on their first call attempt -- neither
    tree's `_call` needs to fall back to its bare-`method(**kwargs)`
    TypeError branch.
    """

    def __init__(self) -> None:
        self.put_item_calls: list[dict[str, Any]] = []
        self.update_item_calls: list[dict[str, Any]] = []

    def put_item(self, **kwargs: Any) -> dict[str, Any]:
        self.put_item_calls.append(kwargs)
        return {}

    def update_item(self, **kwargs: Any) -> dict[str, Any]:
        self.update_item_calls.append(kwargs)
        return {}


def _assert_put_item_carries_no_governance_fields(item: dict[str, Any]) -> None:
    for field in GOVERNANCE_FIELD_NAMES:
        assert field not in item, f"unexpected governance field {field!r} present in PutItem Item"


def _assert_update_item_carries_no_governance_fields(names: dict[str, str]) -> None:
    mapped_field_names = set(names.values())
    for field in GOVERNANCE_FIELD_NAMES:
        assert field not in mapped_field_names, (
            f"unexpected governance field {field!r} mapped in ExpressionAttributeNames"
        )


def _assert_expression_attribute_values_carries_no_governance_keys(
    values: dict[str, Any],
) -> None:
    for field in GOVERNANCE_FIELD_NAMES:
        assert field not in values, (
            f"unexpected governance field {field!r} present as an ExpressionAttributeValues key"
        )


def _assert_update_expression_carries_no_governance_field_names(update_expression: str) -> None:
    for field in GOVERNANCE_FIELD_NAMES:
        assert field not in update_expression, (
            f"unexpected governance field {field!r} present in the literal "
            f"UpdateExpression string: {update_expression!r}"
        )


# ---------------------------------------------------------------------------
# Category 6 -- AuditMetadata (items 4a-4g). Explicitly excluded from
# custody-field treatment (Technical Design Section 18.1).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo_cls", _REPO_CLASSES, ids=_REPO_IDS)
def test_put_audit_metadata_once_carries_no_governance_fields(repo_cls: type) -> None:
    client = _RecordingDynamoClient()
    repo = repo_cls("table", client)

    item = {
        "PK": "CLIENT#c1",
        "SK": "AUDIT#a1",
        "client_id": "c1",
        "audit_id": "a1",
        "lifecycle_state": "DRAFT",
        "created_at": "2026-07-21T00:00:00Z",
        "updated_at": "2026-07-21T00:00:00Z",
    }

    repo.put_audit_metadata_once(item)

    assert len(client.put_item_calls) == 1
    _assert_put_item_carries_no_governance_fields(client.put_item_calls[0]["Item"])


@pytest.mark.parametrize("repo_cls", _REPO_CLASSES, ids=_REPO_IDS)
def test_update_for_force_recreate_carries_no_governance_fields(repo_cls: type) -> None:
    client = _RecordingDynamoClient()
    repo = repo_cls("table", client)

    item = {
        "client_id": "c1",
        "audit_id": "a1",
        "lifecycle_state": "DRAFT",
        "updated_at": "2026-07-21T00:00:00Z",
        "config_hash": "hash123",
        "config_version": "v1",
        "force_history_entry": {"event": "force_recreate", "at": "2026-07-21T00:00:00Z"},
    }

    repo.update_for_force_recreate(item)

    assert len(client.update_item_calls) == 1
    kwargs = client.update_item_calls[0]
    _assert_update_item_carries_no_governance_fields(kwargs.get("ExpressionAttributeNames", {}))
    _assert_expression_attribute_values_carries_no_governance_keys(
        kwargs.get("ExpressionAttributeValues", {})
    )


@pytest.mark.parametrize("repo_cls", _REPO_CLASSES, ids=_REPO_IDS)
def test_append_lifecycle_transition_carries_no_governance_fields(repo_cls: type) -> None:
    client = _RecordingDynamoClient()
    repo = repo_cls("table", client)

    repo.append_lifecycle_transition(
        client_id="c1",
        audit_id="a1",
        expected_current_state="DRAFT",
        next_state="SCHEDULED",
        history_entry={"event": "scheduled", "at": "2026-07-21T00:00:00Z"},
    )

    assert len(client.update_item_calls) == 1
    kwargs = client.update_item_calls[0]
    # This method's UpdateExpression/ExpressionAttributeValues are entirely
    # hardcoded (:next_state, :updated_at, :empty, :entry, :expected_state)
    # -- there is no ExpressionAttributeNames dict at all, and no dynamic
    # field-name construction of any kind. Because there is no
    # ExpressionAttributeNames dict, the one place a governance field name
    # could actually appear for this method is the literal UpdateExpression
    # string itself (e.g. a hypothetical regression hardcoding
    # "SET ttl_disposal_at = :ttl, ..."): ExpressionAttributeValues' keys
    # are always placeholder-style value names (:next_state, etc.), never
    # real attribute names, so checking only those keys would silently miss
    # exactly that regression. Both checks are retained: the
    # ExpressionAttributeValues check documents that no governance name
    # leaks in as a value-placeholder key (defense in depth, harmless if
    # redundant), and the UpdateExpression check is the one that actually
    # inspects the sole place a governance field name could appear in this
    # method's hardcoded request shape.
    _assert_expression_attribute_values_carries_no_governance_keys(
        kwargs.get("ExpressionAttributeValues", {})
    )
    _assert_update_expression_carries_no_governance_field_names(kwargs.get("UpdateExpression", ""))


@pytest.mark.parametrize("repo_cls", _REPO_CLASSES, ids=_REPO_IDS)
def test_set_schedules_carries_no_governance_fields(repo_cls: type) -> None:
    client = _RecordingDynamoClient()
    repo = repo_cls("table", client)

    repo.set_schedules("c1", "a1", [{"cron": "0 0 * * *", "timezone": "UTC"}])

    assert len(client.update_item_calls) == 1
    kwargs = client.update_item_calls[0]
    _assert_update_item_carries_no_governance_fields(kwargs.get("ExpressionAttributeNames", {}))


@pytest.mark.parametrize("repo_cls", _REPO_CLASSES, ids=_REPO_IDS)
def test_update_execution_counters_carries_no_governance_fields(repo_cls: type) -> None:
    client = _RecordingDynamoClient()
    repo = repo_cls("table", client)

    repo.update_execution_counters("c1", "a1", {"completed_runs": 3, "failed_runs": 0})

    assert len(client.update_item_calls) == 1
    kwargs = client.update_item_calls[0]
    _assert_update_item_carries_no_governance_fields(kwargs.get("ExpressionAttributeNames", {}))


@pytest.mark.parametrize("repo_cls", _REPO_CLASSES, ids=_REPO_IDS)
def test_record_finalization_carries_no_governance_fields(repo_cls: type) -> None:
    client = _RecordingDynamoClient()
    repo = repo_cls("table", client)

    repo.record_finalization("c1", "a1", {"final_status": "COMPLETE", "run_count": 5})

    assert len(client.update_item_calls) == 1
    kwargs = client.update_item_calls[0]
    _assert_update_item_carries_no_governance_fields(kwargs.get("ExpressionAttributeNames", {}))


@pytest.mark.parametrize("repo_cls", _REPO_CLASSES, ids=_REPO_IDS)
def test_record_cleanup_errors_carries_no_governance_fields(repo_cls: type) -> None:
    client = _RecordingDynamoClient()
    repo = repo_cls("table", client)

    repo.record_cleanup_errors("c1", "a1", [{"error": "timeout", "at": "2026-07-21T00:00:00Z"}])

    assert len(client.update_item_calls) == 1
    kwargs = client.update_item_calls[0]
    _assert_update_item_carries_no_governance_fields(kwargs.get("ExpressionAttributeNames", {}))


# ---------------------------------------------------------------------------
# Category 3 -- operational coordination metadata (items 4h-4k):
# AggregationJobIntent / ScheduleOccurrenceClaim. Permanently excluded from
# custody-field treatment (Technical Design Section 18.1).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("repo_cls", _REPO_CLASSES, ids=_REPO_IDS)
def test_put_aggregation_job_intent_once_carries_no_governance_fields(repo_cls: type) -> None:
    client = _RecordingDynamoClient()
    repo = repo_cls("table", client)

    item = {
        "PK": "CLIENT#c1",
        "SK": "AUDIT#a1#AGGJOBINTENT#w1",
        "client_id": "c1",
        "audit_id": "a1",
        "window_id": "w1",
        "status": "PENDING",
        "created_at": "2026-07-21T00:00:00Z",
    }

    repo.put_aggregation_job_intent_once(item)

    assert len(client.put_item_calls) == 1
    _assert_put_item_carries_no_governance_fields(client.put_item_calls[0]["Item"])


@pytest.mark.parametrize("repo_cls", _REPO_CLASSES, ids=_REPO_IDS)
def test_update_aggregation_job_intent_carries_no_governance_fields(repo_cls: type) -> None:
    client = _RecordingDynamoClient()
    repo = repo_cls("table", client)

    key = {"PK": "CLIENT#c1", "SK": "AUDIT#a1#AGGJOBINTENT#w1"}
    updates = {"status": "CLAIMED", "claimed_at": "2026-07-21T00:00:00Z"}

    repo.update_aggregation_job_intent(key, updates)

    assert len(client.update_item_calls) == 1
    kwargs = client.update_item_calls[0]
    _assert_update_item_carries_no_governance_fields(kwargs.get("ExpressionAttributeNames", {}))


@pytest.mark.parametrize("repo_cls", _REPO_CLASSES, ids=_REPO_IDS)
def test_claim_occurrence_carries_no_governance_fields(repo_cls: type) -> None:
    client = _RecordingDynamoClient()
    repo = repo_cls("table", client)

    item = {
        "PK": "CLIENT#c1",
        "SK": "AUDIT#a1#OCCURRENCE#occ1",
        "client_id": "c1",
        "audit_id": "a1",
        "schedule_occurrence_id": "occ1",
        "claimed_at": "2026-07-21T00:00:00Z",
    }

    repo.claim_occurrence(item)

    assert len(client.put_item_calls) == 1
    _assert_put_item_carries_no_governance_fields(client.put_item_calls[0]["Item"])


@pytest.mark.parametrize("repo_cls", _REPO_CLASSES, ids=_REPO_IDS)
def test_update_occurrence_carries_no_governance_fields(repo_cls: type) -> None:
    client = _RecordingDynamoClient()
    repo = repo_cls("table", client)

    key = {"PK": "CLIENT#c1", "SK": "AUDIT#a1#OCCURRENCE#occ1"}
    updates = {"status": "COMPLETED", "completed_at": "2026-07-21T00:00:00Z"}

    repo.update_occurrence(key, updates)

    assert len(client.update_item_calls) == 1
    kwargs = client.update_item_calls[0]
    _assert_update_item_carries_no_governance_fields(kwargs.get("ExpressionAttributeNames", {}))
