"""Tests for CustodySweepClient's operation-shape guard
(_assert_custody_field_only_update), structural no-put/delete-capability
guarantees, cross-phase ttl_disposal_at removal/restoration, and the S3
per-version legal-hold tagging sweep.

Mirrors the test style of test_hold_repository.py / test_disposal_repository.py
(patch.object on internal dispatch helpers rather than simulating full
low-level boto3 response shapes for most cases), plus direct tests of the
new operation-shape guard function itself.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from release_confidence_platform.evidence_retention.custody_sweep_client import (
    CustodySweepClient,
    _assert_custody_field_only_update,
)

_TABLE = "test-table"
_BUCKET = "test-bucket"
_CLIENT_ID = "client1"
_AUDIT_ID = "audit1"


def _make_client() -> CustodySweepClient:
    return CustodySweepClient(_TABLE, MagicMock(), _BUCKET, MagicMock())


# ---------------------------------------------------------------------------
# _assert_custody_field_only_update direct tests
# ---------------------------------------------------------------------------


def test_assert_custody_field_only_update_accepts_ttl_only_update_on_run_metadata_sk():
    """A ttl_disposal_at-only update targeting an ordinary other-phase SK
    (e.g. RunMetadata) must not raise."""
    sk = f"AUDIT#{_AUDIT_ID}#RUN#run1"
    _assert_custody_field_only_update(sk, {"#ttl": "ttl_disposal_at"})  # must not raise


def test_assert_custody_field_only_update_accepts_ttl_only_update_on_report_metadata_sk():
    sk = f"AUDIT#{_AUDIT_ID}#EXEC#exec1#CFG#cfg1#AGG#agg1#INTEL#intel1#RPT#rpt1#META"
    _assert_custody_field_only_update(sk, {"#ttl": "ttl_disposal_at"})  # must not raise


def test_assert_custody_field_only_update_rejects_legal_hold_current_state_sk():
    bad_sk = f"AUDIT#{_AUDIT_ID}#LEGALHOLD"
    with pytest.raises(AssertionError) as exc_info:
        _assert_custody_field_only_update(bad_sk, {"#ttl": "ttl_disposal_at"})
    assert "prohibited SK namespace" in str(exc_info.value)


def test_assert_custody_field_only_update_rejects_legal_hold_event_sk():
    bad_sk = f"AUDIT#{_AUDIT_ID}#LEGALHOLD#hold_abc"
    with pytest.raises(AssertionError):
        _assert_custody_field_only_update(bad_sk, {"#ttl": "ttl_disposal_at"})


def test_assert_custody_field_only_update_rejects_disposal_sk():
    bad_sk = f"AUDIT#{_AUDIT_ID}#DISPOSAL#disp_abc"
    with pytest.raises(AssertionError) as exc_info:
        _assert_custody_field_only_update(bad_sk, {"#ttl": "ttl_disposal_at"})
    assert "prohibited SK namespace" in str(exc_info.value)


def test_assert_custody_field_only_update_rejects_non_ttl_attribute():
    """Attempting to update any attribute other than ttl_disposal_at must
    raise, even on an otherwise-valid (non-guarded) SK."""
    sk = f"AUDIT#{_AUDIT_ID}#RUN#run1"
    with pytest.raises(AssertionError) as exc_info:
        _assert_custody_field_only_update(sk, {"#f0": "status"})
    assert "ttl_disposal_at" in str(exc_info.value)


def test_assert_custody_field_only_update_rejects_ttl_plus_other_attribute():
    """An UpdateExpression touching ttl_disposal_at AND another attribute
    must still be rejected -- the guard requires the touched-attribute set
    to be exactly {ttl_disposal_at}, not merely a superset containing it."""
    sk = f"AUDIT#{_AUDIT_ID}#RUN#run1"
    with pytest.raises(AssertionError):
        _assert_custody_field_only_update(
            sk, {"#ttl": "ttl_disposal_at", "#f0": "status"}
        )


def test_assert_custody_field_only_update_rejects_sk_with_both_prohibited_markers():
    bad_sk = f"AUDIT#{_AUDIT_ID}#LEGALHOLD#DISPOSAL#disp_abc"
    with pytest.raises(AssertionError):
        _assert_custody_field_only_update(bad_sk, {"#ttl": "ttl_disposal_at"})


# ---------------------------------------------------------------------------
# Structural guard: no put_object / delete_object / PutItem / DeleteItem
# capability exists on this class.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attribute_name",
    ["put_object", "delete_object", "PutItem", "DeleteItem", "put_item", "delete_item"],
)
def test_custody_sweep_client_has_no_write_or_delete_capable_method(attribute_name):
    assert not hasattr(CustodySweepClient, attribute_name)


def test_call_dynamodb_rejects_disallowed_method_name():
    client = _make_client()
    with pytest.raises(AssertionError) as exc_info:
        client._call_dynamodb("put_item", Item={})
    assert "disallowed DynamoDB operation" in str(exc_info.value)


def test_call_dynamodb_rejects_delete_item():
    client = _make_client()
    with pytest.raises(AssertionError):
        client._call_dynamodb("delete_item", Key={})


def test_call_s3_rejects_disallowed_method_name():
    client = _make_client()
    with pytest.raises(AssertionError) as exc_info:
        client._call_s3("put_object", Key="raw-results/x")
    assert "disallowed S3 operation" in str(exc_info.value)


def test_call_s3_rejects_delete_object():
    client = _make_client()
    with pytest.raises(AssertionError):
        client._call_s3("delete_object", Key="raw-results/x")


# ---------------------------------------------------------------------------
# remove_ttl_disposal_at
# ---------------------------------------------------------------------------


def test_remove_ttl_disposal_at_updates_only_items_carrying_the_attribute():
    client = _make_client()
    items = [
        {"PK": f"CLIENT#{_CLIENT_ID}", "SK": f"AUDIT#{_AUDIT_ID}#RUN#run1", "ttl_disposal_at": 100},
        {"PK": f"CLIENT#{_CLIENT_ID}", "SK": f"AUDIT#{_AUDIT_ID}#RUN#run2"},
        {
            "PK": f"CLIENT#{_CLIENT_ID}",
            "SK": f"AUDIT#{_AUDIT_ID}#EXEC#exec1#CFG#c1#AGG#a1#SET",
            "ttl_disposal_at": 200,
        },
    ]
    calls = []

    def fake_remove(client_id, sk):
        calls.append((client_id, sk))

    with patch.object(client, "_query_audit_items", return_value=iter(items)):
        with patch.object(client, "_remove_ttl_disposal_at_item", side_effect=fake_remove):
            updated = client.remove_ttl_disposal_at(_CLIENT_ID, _AUDIT_ID)

    assert updated == 2
    assert calls == [
        (_CLIENT_ID, f"AUDIT#{_AUDIT_ID}#RUN#run1"),
        (_CLIENT_ID, f"AUDIT#{_AUDIT_ID}#EXEC#exec1#CFG#c1#AGG#a1#SET"),
    ]


def test_remove_ttl_disposal_at_returns_zero_when_no_items_carry_the_attribute():
    client = _make_client()
    items = [{"PK": f"CLIENT#{_CLIENT_ID}", "SK": f"AUDIT#{_AUDIT_ID}#RUN#run1"}]
    with patch.object(client, "_query_audit_items", return_value=iter(items)):
        with patch.object(client, "_remove_ttl_disposal_at_item") as fake_remove:
            updated = client.remove_ttl_disposal_at(_CLIENT_ID, _AUDIT_ID)
    assert updated == 0
    fake_remove.assert_not_called()


def test_remove_ttl_disposal_at_item_builds_remove_expression_and_asserts_guard():
    client = _make_client()
    captured = {}

    def fake_call_dynamodb(method_name, **kwargs):
        captured["method_name"] = method_name
        captured["kwargs"] = kwargs
        return {}

    with patch.object(client, "_call_dynamodb", side_effect=fake_call_dynamodb):
        client._remove_ttl_disposal_at_item(_CLIENT_ID, f"AUDIT#{_AUDIT_ID}#RUN#run1")

    assert captured["method_name"] == "update_item"
    assert captured["kwargs"]["UpdateExpression"] == "REMOVE #ttl"
    assert captured["kwargs"]["ExpressionAttributeNames"] == {"#ttl": "ttl_disposal_at"}
    assert captured["kwargs"]["Key"] == {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#RUN#run1",
    }


def test_remove_ttl_disposal_at_item_raises_on_legal_hold_sk():
    """Defense-in-depth: even if a #LEGALHOLD#-shaped item somehow carried
    ttl_disposal_at, the guard must still block the write."""
    client = _make_client()
    with patch.object(client, "_call_dynamodb") as fake_call:
        with pytest.raises(AssertionError):
            client._remove_ttl_disposal_at_item(_CLIENT_ID, f"AUDIT#{_AUDIT_ID}#LEGALHOLD")
    fake_call.assert_not_called()


# ---------------------------------------------------------------------------
# restore_ttl_disposal_at
# ---------------------------------------------------------------------------


def test_restore_ttl_disposal_at_clamps_to_now_when_custody_already_elapsed():
    client = _make_client()
    items = [
        {
            "PK": f"CLIENT#{_CLIENT_ID}",
            "SK": f"AUDIT#{_AUDIT_ID}#RUN#run1",
            "custody_expires_at": 100,
        },
    ]
    captured = {}

    def fake_restore(client_id, sk, value):
        captured["value"] = value

    with patch.object(client, "_query_audit_items", return_value=iter(items)):
        with patch.object(client, "_restore_ttl_disposal_at_item", side_effect=fake_restore):
            updated = client.restore_ttl_disposal_at(_CLIENT_ID, _AUDIT_ID, now_epoch_seconds=500)

    assert updated == 1
    assert captured["value"] == 500  # clamped to now, since custody (100) already elapsed


def test_restore_ttl_disposal_at_uses_custody_expires_at_when_not_yet_elapsed():
    client = _make_client()
    items = [
        {
            "PK": f"CLIENT#{_CLIENT_ID}",
            "SK": f"AUDIT#{_AUDIT_ID}#RUN#run1",
            "custody_expires_at": 900,
        },
    ]
    captured = {}

    def fake_restore(client_id, sk, value):
        captured["value"] = value

    with patch.object(client, "_query_audit_items", return_value=iter(items)):
        with patch.object(client, "_restore_ttl_disposal_at_item", side_effect=fake_restore):
            client.restore_ttl_disposal_at(_CLIENT_ID, _AUDIT_ID, now_epoch_seconds=500)

    assert captured["value"] == 900  # custody_expires_at not yet elapsed; not clamped


def test_restore_ttl_disposal_at_skips_items_without_custody_expires_at():
    client = _make_client()
    items = [{"PK": f"CLIENT#{_CLIENT_ID}", "SK": f"AUDIT#{_AUDIT_ID}#RUN#run1"}]
    with patch.object(client, "_query_audit_items", return_value=iter(items)):
        with patch.object(client, "_restore_ttl_disposal_at_item") as fake_restore:
            updated = client.restore_ttl_disposal_at(_CLIENT_ID, _AUDIT_ID, now_epoch_seconds=500)
    assert updated == 0
    fake_restore.assert_not_called()


def test_restore_ttl_disposal_at_skips_items_that_already_carry_ttl_disposal_at():
    """Idempotent re-invocation: an item already restored (or never held)
    must not be touched again."""
    client = _make_client()
    items = [
        {
            "PK": f"CLIENT#{_CLIENT_ID}",
            "SK": f"AUDIT#{_AUDIT_ID}#RUN#run1",
            "custody_expires_at": 900,
            "ttl_disposal_at": 900,
        }
    ]
    with patch.object(client, "_query_audit_items", return_value=iter(items)):
        with patch.object(client, "_restore_ttl_disposal_at_item") as fake_restore:
            updated = client.restore_ttl_disposal_at(_CLIENT_ID, _AUDIT_ID, now_epoch_seconds=500)
    assert updated == 0
    fake_restore.assert_not_called()


def test_restore_ttl_disposal_at_item_builds_set_expression_and_asserts_guard():
    client = _make_client()
    captured = {}

    def fake_call_dynamodb(method_name, **kwargs):
        captured["method_name"] = method_name
        captured["kwargs"] = kwargs
        return {}

    with patch.object(client, "_call_dynamodb", side_effect=fake_call_dynamodb):
        client._restore_ttl_disposal_at_item(_CLIENT_ID, f"AUDIT#{_AUDIT_ID}#RUN#run1", 500)

    assert captured["method_name"] == "update_item"
    assert captured["kwargs"]["UpdateExpression"] == "SET #ttl = :v"
    assert captured["kwargs"]["ExpressionAttributeNames"] == {"#ttl": "ttl_disposal_at"}
    assert captured["kwargs"]["ExpressionAttributeValues"] == {":v": 500}


def test_restore_ttl_disposal_at_item_raises_on_disposal_sk():
    client = _make_client()
    with patch.object(client, "_call_dynamodb") as fake_call:
        with pytest.raises(AssertionError):
            client._restore_ttl_disposal_at_item(
                _CLIENT_ID, f"AUDIT#{_AUDIT_ID}#DISPOSAL#disp_abc", 500
            )
    fake_call.assert_not_called()


# ---------------------------------------------------------------------------
# _query_audit_items (pagination)
# ---------------------------------------------------------------------------


def test_query_audit_items_uses_correct_key_condition():
    client = _make_client()
    captured = {}

    def fake_call_dynamodb(method_name, **kwargs):
        captured["method_name"] = method_name
        captured["kwargs"] = kwargs
        return {"Items": []}

    with patch.object(client, "_call_dynamodb", side_effect=fake_call_dynamodb):
        list(client._query_audit_items(_CLIENT_ID, _AUDIT_ID))

    assert captured["method_name"] == "query"
    assert captured["kwargs"]["ExpressionAttributeValues"] == {
        ":pk": f"CLIENT#{_CLIENT_ID}",
        ":sk_prefix": f"AUDIT#{_AUDIT_ID}",
    }
    assert "begins_with(SK, :sk_prefix)" in captured["kwargs"]["KeyConditionExpression"]


def test_query_audit_items_paginates_via_last_evaluated_key():
    client = _make_client()
    responses = [
        {"Items": [{"SK": "AUDIT#a#RUN#1"}], "LastEvaluatedKey": {"PK": "x", "SK": "y"}},
        {"Items": [{"SK": "AUDIT#a#RUN#2"}]},
    ]
    calls = []

    def fake_call_dynamodb(method_name, **kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    with patch.object(client, "_call_dynamodb", side_effect=fake_call_dynamodb):
        items = list(client._query_audit_items(_CLIENT_ID, _AUDIT_ID))

    assert [item["SK"] for item in items] == ["AUDIT#a#RUN#1", "AUDIT#a#RUN#2"]
    assert len(calls) == 2
    assert "ExclusiveStartKey" not in calls[0]
    assert calls[1]["ExclusiveStartKey"] == {"PK": "x", "SK": "y"}


# ---------------------------------------------------------------------------
# retag_s3_versions
# ---------------------------------------------------------------------------


def test_retag_s3_versions_covers_all_four_evidence_class_prefixes():
    client = _make_client()
    prefixes_seen = []

    def fake_list_versions(prefix):
        prefixes_seen.append(prefix)
        return iter([])

    with patch.object(client, "_list_object_versions", side_effect=fake_list_versions):
        retagged = client.retag_s3_versions(_CLIENT_ID, _AUDIT_ID, legal_hold=True)

    assert retagged == 0
    assert prefixes_seen == [
        f"raw-results/{_CLIENT_ID}/{_AUDIT_ID}/",
        f"intelligence/{_CLIENT_ID}/{_AUDIT_ID}/",
        f"reports/{_CLIENT_ID}/{_AUDIT_ID}/",
        f"integrity/{_CLIENT_ID}/{_AUDIT_ID}/",
    ]


def test_retag_s3_versions_retags_every_returned_version():
    client = _make_client()
    versions = [("raw-results/c/a/run1.json", "v1"), ("raw-results/c/a/run1.json", "v2")]
    retag_calls = []

    def fake_list_versions(prefix):
        if prefix.startswith("raw-results/"):
            return iter(versions)
        return iter([])

    def fake_retag(key, version_id, new_value):
        retag_calls.append((key, version_id, new_value))

    with patch.object(client, "_list_object_versions", side_effect=fake_list_versions):
        with patch.object(client, "_retag_object_version", side_effect=fake_retag):
            retagged = client.retag_s3_versions(_CLIENT_ID, _AUDIT_ID, legal_hold=True)

    assert retagged == 2
    assert retag_calls == [
        ("raw-results/c/a/run1.json", "v1", "true"),
        ("raw-results/c/a/run1.json", "v2", "true"),
    ]


def test_retag_s3_versions_uses_false_value_on_release():
    client = _make_client()

    def fake_list_versions(prefix):
        if prefix.startswith("raw-results/"):
            return iter([("raw-results/c/a/run1.json", "v1")])
        return iter([])

    retag_calls = []
    with patch.object(client, "_list_object_versions", side_effect=fake_list_versions):
        with patch.object(
            client, "_retag_object_version", side_effect=lambda k, v, nv: retag_calls.append(nv)
        ):
            client.retag_s3_versions(_CLIENT_ID, _AUDIT_ID, legal_hold=False)

    assert retag_calls == ["false"]


def test_retag_object_version_merges_and_preserves_existing_tags():
    client = _make_client()
    captured = {}

    def fake_call_s3(method_name, **kwargs):
        if method_name == "get_object_tagging":
            return {"TagSet": [{"Key": "rcp-evidence-class", "Value": "raw_evidence"}]}
        captured["method_name"] = method_name
        captured["kwargs"] = kwargs
        return {}

    with patch.object(client, "_call_s3", side_effect=fake_call_s3):
        client._retag_object_version("raw-results/c/a/run1.json", "v1", "true")

    assert captured["method_name"] == "put_object_tagging"
    tag_set = {tag["Key"]: tag["Value"] for tag in captured["kwargs"]["Tagging"]["TagSet"]}
    assert tag_set == {"rcp-evidence-class": "raw_evidence", "rcp-legal-hold": "true"}
    assert captured["kwargs"]["Key"] == "raw-results/c/a/run1.json"
    assert captured["kwargs"]["VersionId"] == "v1"


def test_list_object_versions_yields_key_version_pairs_and_paginates():
    client = _make_client()
    responses = [
        {
            "Versions": [{"Key": "k1", "VersionId": "v1"}],
            "IsTruncated": True,
            "NextKeyMarker": "k1",
            "NextVersionIdMarker": "v1",
        },
        {"Versions": [{"Key": "k2", "VersionId": "v2"}], "IsTruncated": False},
    ]
    calls = []

    def fake_call_s3(method_name, **kwargs):
        calls.append(kwargs)
        return responses.pop(0)

    with patch.object(client, "_call_s3", side_effect=fake_call_s3):
        result = list(client._list_object_versions("raw-results/c/a/"))

    assert result == [("k1", "v1"), ("k2", "v2")]
    assert calls[0].get("KeyMarker") is None
    assert calls[1]["KeyMarker"] == "k1"
    assert calls[1]["VersionIdMarker"] == "v1"


def test_list_object_versions_skips_delete_markers():
    """DeleteMarkers carry no content and cannot be tagged; only entries
    under the "Versions" key are yielded."""
    client = _make_client()
    response = {
        "Versions": [{"Key": "k1", "VersionId": "v1"}],
        "DeleteMarkers": [{"Key": "k1", "VersionId": "dm1"}],
        "IsTruncated": False,
    }
    with patch.object(client, "_call_s3", return_value=response):
        result = list(client._list_object_versions("raw-results/c/a/"))
    assert result == [("k1", "v1")]
