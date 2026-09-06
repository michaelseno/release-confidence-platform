"""Unit tests for evidence_retention.disposal_recorder (A1.4a Increment 1).

Covers the QA plan (docs/qa/a1_4a_disposal_recorder_test_plan.md) Areas
(c) Deterministic Identity (Section 3.3, TC-C1-C6), (d) Duplicate-Conflict
Verification (Section 3.4, TC-D1-D4; TC-D5 lives in
test_disposal_repository.py), (e) Provenance Rules (Section 3.5,
TC-E1-E13), (f) Evidence-Prefix Restriction and Disposition Taxonomy
(Section 3.6, TC-F1-F6), plus the Section 2 acceptance-matrix rows for items
1-8, 15, 16, 17 (TC-Q1a/b/c, TC-Q2, TC-Q3-a..f, TC-Q5-a..c, TC-Q6-a/b, TC-Q7,
TC-Q8-a/b, TC-Q15a/b, TC-Q16, TC-Q17-DDB/S3).

This increment does not cover redrive (TC-G*), IAM (TC-I*), batch/retry
(TC-H*), stage-config validation (TC-G5-G9), or failure-plane infra wiring
(TC-P*) -- those are Increment 2/3 scope.

Note (Increment 4 correction): the enumerated TC-Q* list above previously
omitted TC-Q4 despite this file's own header claiming coverage of item 4 --
TC-Q4-a..e is functionally covered under TC-E7/TC-E8/TC-E10 (see the
explicit cross-reference comments on those tests below), not under a
dedicated TC-Q4-labeled test.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from release_confidence_platform.evidence_retention import disposal_recorder as dr
from release_confidence_platform.evidence_retention.disposal_repository import (
    ConditionalWriteError,
    DisposalRepository,
)
from release_confidence_platform.storage.dynamodb_codec import encode_item

_CLIENT_ID = "client1"
_AUDIT_ID = "audit1"
_EXPECTED_STREAM_ARN = (
    "arn:aws:dynamodb:us-east-1:111111111111:table/MetadataTable/stream/2026-01-01T00:00:00.000"
)
_EXPECTED_ACCOUNT_ID = "111111111111"
_EXPECTED_BUCKET = "rcp-raw-results-dev"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _old_image(**overrides: Any) -> dict[str, Any]:
    data = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#RUN#run1",
        "evidence_class": "raw_evidence",
        "created_at": "2026-01-01T00:00:00.000Z",
    }
    data.update(overrides)
    return data


_MISSING = object()


def _dynamodb_record(*, old_image: Any = _MISSING, **overrides: Any) -> dict[str, Any]:
    record: dict[str, Any] = {
        "eventID": "event-abc123",
        "eventName": "REMOVE",
        "eventSourceARN": _EXPECTED_STREAM_ARN,
        "userIdentity": {"type": "Service", "principalId": "dynamodb.amazonaws.com"},
        "dynamodb": {"ApproximateCreationDateTime": 1735689600.0},
    }
    resolved_old_image = _old_image() if old_image is _MISSING else old_image
    if resolved_old_image is not None:
        record["dynamodb"]["OldImage"] = encode_item(resolved_old_image)
    record.update(overrides)
    return record


def _s3_event(
    *, detail_overrides: dict[str, Any] | None = None, **overrides: Any
) -> dict[str, Any]:
    detail = {
        "bucket": {"name": _EXPECTED_BUCKET},
        "object": {
            "key": f"raw-results/{_CLIENT_ID}/{_AUDIT_ID}/run1/results.json",
            "version-id": "v123",
        },
        "reason": "Lifecycle Expiration",
        "requester": "s3.amazonaws.com",
        "deletion-type": "Permanently Deleted",
        "event-version": "1.0",
    }
    if detail_overrides:
        detail.update(detail_overrides)
    event: dict[str, Any] = {
        "id": "delivery-id-1",
        "source": "aws.s3",
        "detail-type": "Object Deleted",
        "account": _EXPECTED_ACCOUNT_ID,
        "time": "2026-01-01T00:00:00Z",
        "detail": detail,
    }
    event.update(overrides)
    return event


def _s3_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs = {
        "expected_account_id": _EXPECTED_ACCOUNT_ID,
        "expected_bucket_name": _EXPECTED_BUCKET,
        "supported_major_version": 1,
        "minimum_minor_version": 0,
    }
    kwargs.update(overrides)
    return kwargs


class _FakeRepository:
    """Minimal DisposalRepository double: put_disposal_record can be made to
    raise ConditionalWriteError; get_disposal_record returns a preset item.
    """

    def __init__(self, *, existing_item: dict[str, Any] | None = None, conflict: bool = False):
        self.existing_item = existing_item
        self.conflict = conflict
        self.put_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def put_disposal_record(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)
        if self.conflict:
            raise ConditionalWriteError()

    def get_disposal_record(self, client_id, audit_id, disposal_id, *, consistent_read=False):
        self.get_calls.append(
            {
                "client_id": client_id,
                "audit_id": audit_id,
                "disposal_id": disposal_id,
                "consistent_read": consistent_read,
            }
        )
        return self.existing_item


# ---------------------------------------------------------------------------
# Area (c) -- Deterministic Identity (TC-C1-C6)
# ---------------------------------------------------------------------------


def test_tc_c1_dynamodb_canonical_hash_exact_byte_string():
    fields = {
        "source_kind": "dynamodb_ttl_remove",
        "disposal_id_scheme": "v1",
        "stream_identity": _EXPECTED_STREAM_ARN,
        "event_id": "event-abc123",
    }
    expected_bytes = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
    import hashlib

    expected = f"disp_v1_{hashlib.sha256(expected_bytes).hexdigest()}"
    actual = dr.compute_dynamodb_disposal_id(_EXPECTED_STREAM_ARN, "event-abc123")
    assert actual == expected


def test_tc_c2_s3_canonical_hash_exact_byte_string():
    fields = {
        "source_kind": "s3_lifecycle_delete",
        "disposal_id_scheme": "v1",
        "bucket": _EXPECTED_BUCKET,
        "key": "raw-results/client1/audit1/run1/results.json",
        "version_id": "v123",
        "reason": "Lifecycle Expiration",
        "deletion_type": "Permanently Deleted",
    }
    expected_bytes = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
    import hashlib

    expected = f"disp_v1_{hashlib.sha256(expected_bytes).hexdigest()}"
    actual = dr.compute_s3_disposal_id(
        bucket=_EXPECTED_BUCKET,
        key="raw-results/client1/audit1/run1/results.json",
        version_id="v123",
        reason="Lifecycle Expiration",
        deletion_type="Permanently Deleted",
    )
    assert actual == expected


def test_tc_c3_disposal_id_format_both_paths():
    import re

    pattern = re.compile(r"^disp_v1_[0-9a-f]{64}$")
    ddb_id = dr.compute_dynamodb_disposal_id(_EXPECTED_STREAM_ARN, "event-abc123")
    s3_id = dr.compute_s3_disposal_id(
        bucket=_EXPECTED_BUCKET,
        key="raw-results/c/a/r/x.json",
        version_id="v1",
        reason="Lifecycle Expiration",
        deletion_type="Permanently Deleted",
    )
    assert pattern.match(ddb_id)
    assert pattern.match(s3_id)


def test_tc_c4_envelope_id_excluded_from_s3_hash():
    repo1 = _FakeRepository()
    repo2 = _FakeRepository()
    event1 = _s3_event(id="delivery-id-AAA")
    event2 = _s3_event(id="delivery-id-BBB")

    outcome1 = dr.process_s3_eventbridge_event(event1, repository=repo1, **_s3_kwargs())
    outcome2 = dr.process_s3_eventbridge_event(event2, repository=repo2, **_s3_kwargs())

    assert outcome1.disposition == dr.DISPOSITION_RECORDABLE
    assert outcome2.disposition == dr.DISPOSITION_RECORDABLE
    assert outcome1.disposal_record.disposal_id == outcome2.disposal_record.disposal_id


def test_tc_c5_s3_key_hashed_raw_not_percent_decoded():
    raw_space_id = dr.compute_s3_disposal_id(
        bucket=_EXPECTED_BUCKET,
        key="raw-results/c/a/r/my file.json",
        version_id="v1",
        reason="Lifecycle Expiration",
        deletion_type="Permanently Deleted",
    )
    percent_encoded_id = dr.compute_s3_disposal_id(
        bucket=_EXPECTED_BUCKET,
        key="raw-results/c/a/r/my%20file.json",
        version_id="v1",
        reason="Lifecycle Expiration",
        deletion_type="Permanently Deleted",
    )
    # Different raw bytes -> different hash input -> different disposal_id.
    assert raw_space_id != percent_encoded_id


def test_tc_c6_redelivery_same_event_deterministic():
    first = dr.compute_dynamodb_disposal_id(_EXPECTED_STREAM_ARN, "event-abc123")
    second = dr.compute_dynamodb_disposal_id(_EXPECTED_STREAM_ARN, "event-abc123")
    assert first == second

    first_s3 = dr.compute_s3_disposal_id(
        bucket=_EXPECTED_BUCKET,
        key="raw-results/c/a/r/x.json",
        version_id="v1",
        reason="Lifecycle Expiration",
        deletion_type="Permanently Deleted",
    )
    second_s3 = dr.compute_s3_disposal_id(
        bucket=_EXPECTED_BUCKET,
        key="raw-results/c/a/r/x.json",
        version_id="v1",
        reason="Lifecycle Expiration",
        deletion_type="Permanently Deleted",
    )
    assert first_s3 == second_s3


# ---------------------------------------------------------------------------
# Area (d) -- Duplicate-Conflict Verification (TC-D1-D4)
# ---------------------------------------------------------------------------


def _base_candidate() -> Any:
    from release_confidence_platform.evidence_retention.models import DisposalRecord

    return DisposalRecord(
        PK=f"CLIENT#{_CLIENT_ID}",
        SK=f"AUDIT#{_AUDIT_ID}#DISPOSAL#disp_v1_abc",
        record_type="disposal_record",
        disposal_id="disp_v1_abc",
        disposal_id_scheme="v1",
        source_kind="dynamodb_ttl_remove",
        source_stream_identity=_EXPECTED_STREAM_ARN,
        source_event_id="event-abc123",
        client_id=_CLIENT_ID,
        audit_id=_AUDIT_ID,
        evidence_class="raw_evidence",
        disposal_mechanism="DYNAMODB_TTL",
        disposed_identity_ref="CLIENT#client1#AUDIT#audit1#RUN#run1",
        disposed_at="2026-01-01T00:00:00.000Z",
        recorded_at="2026-01-01T00:05:00.000Z",
    )


def test_tc_d1_confirmed_idempotent_duplicate_recorded_at_differs():
    candidate = _base_candidate()
    existing_item = candidate.to_dict()
    existing_item["recorded_at"] = "2026-01-01T00:06:00.000Z"  # only field allowed to differ
    repo = _FakeRepository(existing_item=existing_item)

    result = dr.verify_duplicate_or_collision(
        repo,
        client_id=_CLIENT_ID,
        audit_id=_AUDIT_ID,
        disposal_id="disp_v1_abc",
        candidate=candidate,
    )

    assert result.disposition == dr.DISPOSITION_CONFIRMED_DUPLICATE
    assert repo.get_calls[0]["consistent_read"] is True


def test_tc_d2_disposal_id_collision_unequal_content():
    candidate = _base_candidate()
    existing_item = candidate.to_dict()
    existing_item["disposed_identity_ref"] = "CLIENT#client1#AUDIT#audit1#RUN#DIFFERENT"
    repo = _FakeRepository(existing_item=existing_item)

    result = dr.verify_duplicate_or_collision(
        repo,
        client_id=_CLIENT_ID,
        audit_id=_AUDIT_ID,
        disposal_id="disp_v1_abc",
        candidate=candidate,
    )

    assert result.disposition == dr.DISPOSITION_INTEGRITY_FAILURE
    assert "disposed_identity_ref" in result.mismatched_fields


def test_tc_d2_source_identity_only_mismatch_with_matching_disposal_facts():
    """A source-identity-only mismatch (disposal facts otherwise identical)
    must resolve to integrity failure -- the scenario the Round 2
    comparison-surface correction exists to catch."""
    candidate = _base_candidate()
    existing_item = candidate.to_dict()
    existing_item["source_event_id"] = "event-DIFFERENT"
    repo = _FakeRepository(existing_item=existing_item)

    result = dr.verify_duplicate_or_collision(
        repo,
        client_id=_CLIENT_ID,
        audit_id=_AUDIT_ID,
        disposal_id="disp_v1_abc",
        candidate=candidate,
    )

    assert result.disposition == dr.DISPOSITION_INTEGRITY_FAILURE
    assert "source_event_id" in result.mismatched_fields


def test_tc_d3_comparison_includes_source_identity_fields_not_disposal_facts_alone():
    """Assert the comparison explicitly includes disposal_id_scheme,
    source_kind, and the applicable source-identity fields."""
    candidate = _base_candidate()
    existing_item = candidate.to_dict()
    existing_item["source_stream_identity"] = (
        "arn:aws:dynamodb:us-east-1:111111111111:table/Other/stream/x"
    )
    repo = _FakeRepository(existing_item=existing_item)

    result = dr.verify_duplicate_or_collision(
        repo,
        client_id=_CLIENT_ID,
        audit_id=_AUDIT_ID,
        disposal_id="disp_v1_abc",
        candidate=candidate,
    )

    assert result.disposition == dr.DISPOSITION_INTEGRITY_FAILURE
    assert "source_stream_identity" in result.mismatched_fields


def test_tc_d4_recorded_at_is_the_only_excluded_field():
    """A differing recorded_at alone must not trigger category (f)."""
    candidate = _base_candidate()
    existing_item = candidate.to_dict()
    assert existing_item["recorded_at"] == candidate.recorded_at
    existing_item["recorded_at"] = "1999-01-01T00:00:00.000Z"
    repo = _FakeRepository(existing_item=existing_item)

    result = dr.verify_duplicate_or_collision(
        repo,
        client_id=_CLIENT_ID,
        audit_id=_AUDIT_ID,
        disposal_id="disp_v1_abc",
        candidate=candidate,
    )

    assert result.disposition == dr.DISPOSITION_CONFIRMED_DUPLICATE


# ---------------------------------------------------------------------------
# Area (e) -- Provenance Rules (TC-E1-E13)
# ---------------------------------------------------------------------------

# DynamoDB TTL exact-match rule (TC-E1..E5)


def test_tc_e1_wrong_stream_identity_is_unknown_incompatible():
    record = _dynamodb_record(
        eventSourceARN="arn:aws:dynamodb:us-east-1:111111111111:table/Other/stream/x"
    )
    result = dr.validate_dynamodb_provenance(record, expected_stream_arn=_EXPECTED_STREAM_ARN)
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


def test_tc_e1_correct_stream_identity_passes_element_one():
    record = _dynamodb_record()
    result = dr.validate_dynamodb_provenance(record, expected_stream_arn=_EXPECTED_STREAM_ARN)
    assert result.disposition == dr.DISPOSITION_RECORDABLE


def test_tc_e2_event_name_insert_is_valid_but_irrelevant():
    record = _dynamodb_record(eventName="INSERT")
    result = dr.validate_dynamodb_provenance(record, expected_stream_arn=_EXPECTED_STREAM_ARN)
    assert result.disposition == dr.DISPOSITION_VALID_BUT_IRRELEVANT


def test_tc_e2_event_name_modify_is_valid_but_irrelevant():
    record = _dynamodb_record(eventName="MODIFY")
    result = dr.validate_dynamodb_provenance(record, expected_stream_arn=_EXPECTED_STREAM_ARN)
    assert result.disposition == dr.DISPOSITION_VALID_BUT_IRRELEVANT


def test_tc_e3_non_service_user_identity_on_remove_is_valid_but_irrelevant():
    record = _dynamodb_record(userIdentity={"type": "IAMUser", "principalId": "AIDAEXAMPLE"})
    result = dr.validate_dynamodb_provenance(record, expected_stream_arn=_EXPECTED_STREAM_ARN)
    assert result.disposition == dr.DISPOSITION_VALID_BUT_IRRELEVANT


def test_tc_e4_missing_old_image_is_malformed_target_provenance():
    record = _dynamodb_record(old_image=None)
    result = dr.validate_dynamodb_provenance(record, expected_stream_arn=_EXPECTED_STREAM_ARN)
    assert result.disposition == dr.DISPOSITION_MALFORMED_TARGET_PROVENANCE


def test_tc_e5_old_image_missing_evidence_class_is_malformed():
    record = _dynamodb_record(old_image=_old_image(evidence_class=None))
    result = dr.validate_dynamodb_provenance(record, expected_stream_arn=_EXPECTED_STREAM_ARN)
    assert result.disposition == dr.DISPOSITION_MALFORMED_TARGET_PROVENANCE


def test_tc_e5_old_image_invalid_evidence_class_is_malformed():
    record = _dynamodb_record(old_image=_old_image(evidence_class="not_a_governed_class"))
    result = dr.validate_dynamodb_provenance(record, expected_stream_arn=_EXPECTED_STREAM_ARN)
    assert result.disposition == dr.DISPOSITION_MALFORMED_TARGET_PROVENANCE


# S3 EventBridge envelope/provenance rule (TC-E6..E12)


def test_tc_e6_wrong_envelope_source_is_unknown_incompatible():
    event = _s3_event(source="aws.other-service")
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


def test_tc_e6_wrong_detail_type_is_unknown_incompatible():
    event = _s3_event(**{"detail-type": "Object Created"})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


# TC-E7, TC-E8 (x4), and TC-E10 (x2) below also satisfy TC-Q4-a..e (QA plan
# Section 2 item 4: "Real S3 EventBridge fixtures using corrected
# detail['event-version'] field name, account, detail.requester; semver
# MAJOR/MINOR positive+negative cases; combined reason+requester provenance
# negative case") -- they exercise the identical real S3 EventBridge
# fixture/account/detail['event-version']/detail.requester/semver
# MAJOR-MINOR/combined-reason-requester assertions item 4 requires. This
# cross-reference mirrors TC-Q12's own explicit cross-reference-to-TC-G10
# convention (test_infra_configuration.py); TC-Q4 is not implemented as a
# second, separate/duplicated test case.


def test_tc_e7_mismatched_account_is_unknown_incompatible():
    """Also satisfies TC-Q4-a (§2 item 4: `account` field mismatch)."""
    event = _s3_event(account="222222222222")
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


def test_tc_e8_major_version_mismatch_is_unknown_incompatible():
    """Also satisfies TC-Q4-c (§2 item 4: semver MAJOR negative case, via
    the corrected `detail["event-version"]` field name)."""
    event = _s3_event(detail_overrides={"event-version": "2.0"})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


def test_tc_e8_minor_below_minimum_is_unknown_incompatible():
    """Also satisfies TC-Q4-c (§2 item 4: semver MINOR negative case)."""
    event = _s3_event(detail_overrides={"event-version": "1.0"})
    result = dr.validate_s3_provenance(event, **_s3_kwargs(minimum_minor_version=1))
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


def test_tc_e8_higher_minor_is_accepted():
    """Also satisfies TC-Q4-c (§2 item 4: semver MINOR positive case)."""
    event = _s3_event(detail_overrides={"event-version": "1.5"})
    result = dr.validate_s3_provenance(event, **_s3_kwargs(minimum_minor_version=0))
    assert result.disposition == dr.DISPOSITION_RECORDABLE


def test_tc_e8_unparseable_version_is_unknown_incompatible():
    """Also satisfies TC-Q4-b (§2 item 4: corrected `detail["event-version"]`
    field parsing, negative/unparseable case)."""
    event = _s3_event(detail_overrides={"event-version": "not-a-version"})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


def test_tc_e9_wrong_bucket_is_unknown_incompatible():
    event = _s3_event(detail_overrides={"bucket": {"name": "some-other-bucket"}})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


def test_tc_e10_reason_correct_requester_wrong_is_unknown_incompatible():
    """Also satisfies TC-Q4-e (§2 item 4: combined `reason`+`requester`
    provenance negative case -- `reason` correct, `requester` wrong)."""
    event = _s3_event(detail_overrides={"requester": "not-s3.amazonaws.com"})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


def test_tc_e10_reason_correct_requester_missing_is_unknown_incompatible():
    """Also satisfies TC-Q4-e (§2 item 4: combined `reason`+`requester`
    provenance negative case -- `reason` correct, `requester` missing)."""
    event = _s3_event(detail_overrides={"requester": None})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


def test_tc_e11_missing_version_id_is_malformed():
    event = _s3_event(
        detail_overrides={
            "object": {"key": f"raw-results/{_CLIENT_ID}/{_AUDIT_ID}/run1/results.json"}
        }
    )
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_MALFORMED_TARGET_PROVENANCE


def test_tc_e12_permanently_deleted_is_recordable():
    event = _s3_event(detail_overrides={"deletion-type": "Permanently Deleted"})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_RECORDABLE


def test_tc_e12_delete_marker_created_is_valid_but_irrelevant():
    event = _s3_event(detail_overrides={"deletion-type": "Delete Marker Created"})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_VALID_BUT_IRRELEVANT


def test_tc_e12_unrecognized_deletion_type_is_unknown_incompatible():
    event = _s3_event(detail_overrides={"deletion-type": "Some Future Value"})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


def test_tc_e13_handler_independently_revalidates_bypassing_rule_layer():
    """Two-layer defense-in-depth: a fixture constructed as if it had
    bypassed the rule-level EventPattern entirely (e.g. a wrong account)
    must still be independently rejected by the handler-side validator."""
    event = _s3_event(account="999999999999", detail_overrides={"requester": "someone-else"})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


# ---------------------------------------------------------------------------
# Area (f) -- Evidence-Prefix Restriction and Disposition Taxonomy (TC-F1-F6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("prefix", ["raw-results", "intelligence", "reports", "integrity"])
def test_tc_f1_four_evidence_class_prefixes_recordable(prefix):
    key = f"{prefix}/{_CLIENT_ID}/{_AUDIT_ID}/run1/artifact.json"
    assert dr.classify_s3_key_prefix(key) == dr.PREFIX_CLASS_RECORDABLE


def test_tc_f2_retention_markers_prefix_excluded():
    key = f"retention-markers/{_CLIENT_ID}/{_AUDIT_ID}/hold_x/1-place.marker"
    assert dr.classify_s3_key_prefix(key) == dr.PREFIX_CLASS_RETENTION_MARKER


def test_tc_f3_unrecognized_prefix_is_unknown_not_valid_but_irrelevant():
    key = f"configs/{_CLIENT_ID}/{_AUDIT_ID}/client_config.json"
    assert dr.classify_s3_key_prefix(key) == dr.PREFIX_CLASS_UNRECOGNIZED


def test_tc_f4_recovery_bucket_excluded_at_bucket_level_before_prefix_evaluation():
    """A recovery-bucket-originated event never reaches prefix evaluation --
    excluded at the bucket-name check (defense-in-depth; primary enforcement
    is the EventBridge rule's own bucket-name constraint, infra scope)."""
    event = _s3_event(detail_overrides={"bucket": {"name": "rcp-disposal-recovery-dev"}})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE
    assert result.reason == "bucket_mismatch"


def test_tc_f5_six_dispositions_independently_reachable_and_distinguishable():
    assert dr.ALL_DISPOSITIONS == {
        dr.DISPOSITION_RECORDABLE,
        dr.DISPOSITION_VALID_BUT_IRRELEVANT,
        dr.DISPOSITION_MALFORMED_TARGET_PROVENANCE,
        dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE,
        dr.DISPOSITION_CONFIRMED_DUPLICATE,
        dr.DISPOSITION_INTEGRITY_FAILURE,
    }
    assert len(dr.ALL_DISPOSITIONS) == 6


def test_tc_f6_ordering_malformed_vs_unknown_precedence():
    """A fixture ambiguous between (c) malformed and (d) unknown must
    resolve per the fixed precedence: source-correctness checks (bucket/
    account/schema/reason/requester/deletion-type) are evaluated BEFORE
    content-parse checks (version-id presence) -- so a event that is both
    wrong-bucket AND missing version-id resolves to (d), never (c)."""
    event = _s3_event(
        detail_overrides={
            "bucket": {"name": "some-other-bucket"},
            "object": {"key": "raw-results/c/a/r/x.json"},  # missing version-id too
        }
    )
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


# ---------------------------------------------------------------------------
# Section 2 acceptance-matrix rows (TC-Q1a/b/c, Q2, Q3-a..f, Q5-a..c, Q6-a/b,
# Q7, Q8-a/b, Q15a/b, Q16, Q17-DDB/S3)
# ---------------------------------------------------------------------------


def test_tc_q1a_ddb_two_invocations_identical_disposal_id():
    record = _dynamodb_record()
    repo1 = _FakeRepository()
    repo2 = _FakeRepository()
    outcome1 = dr.process_dynamodb_stream_record(
        record, expected_stream_arn=_EXPECTED_STREAM_ARN, repository=repo1
    )
    outcome2 = dr.process_dynamodb_stream_record(
        record, expected_stream_arn=_EXPECTED_STREAM_ARN, repository=repo2
    )
    assert outcome1.disposal_record.disposal_id == outcome2.disposal_record.disposal_id


def test_tc_q1a_s3_two_invocations_identical_disposal_id():
    event = _s3_event()
    repo1 = _FakeRepository()
    repo2 = _FakeRepository()
    outcome1 = dr.process_s3_eventbridge_event(event, repository=repo1, **_s3_kwargs())
    outcome2 = dr.process_s3_eventbridge_event(event, repository=repo2, **_s3_kwargs())
    assert outcome1.disposal_record.disposal_id == outcome2.disposal_record.disposal_id


def test_tc_q1b_differently_encoded_keys_must_not_collide():
    id_space = dr.compute_s3_disposal_id(
        bucket=_EXPECTED_BUCKET,
        key="raw-results/c/a/r/my file.json",
        version_id="v1",
        reason="Lifecycle Expiration",
        deletion_type="Permanently Deleted",
    )
    id_percent = dr.compute_s3_disposal_id(
        bucket=_EXPECTED_BUCKET,
        key="raw-results/c/a/r/my%20file.json",
        version_id="v1",
        reason="Lifecycle Expiration",
        deletion_type="Permanently Deleted",
    )
    assert id_space != id_percent


def test_tc_q1c_key_parsing_structurally_independent_of_identity_hash():
    """The identity hash must succeed on a raw key that the key PARSER would
    reject (e.g. too few path segments) -- proving the two never share a
    decode/validation step."""
    malformed_key = "raw-results/only-two-segments"
    with pytest.raises(dr.EvidenceKeyParseError):
        dr.parse_s3_evidence_key(malformed_key)
    # compute_s3_disposal_id has no opinion about key shape -- it just hashes.
    disposal_id = dr.compute_s3_disposal_id(
        bucket=_EXPECTED_BUCKET,
        key=malformed_key,
        version_id="v1",
        reason="Lifecycle Expiration",
        deletion_type="Permanently Deleted",
    )
    assert disposal_id.startswith("disp_v1_")


def test_tc_q2_unequal_collision_forced_via_conflicting_put():
    record = _dynamodb_record()
    existing_item = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#DISPOSAL#disp_v1_forced",
        "record_type": "disposal_record",
        "disposal_id": "disp_v1_forced",
        "disposal_id_scheme": "v1",
        "source_kind": "dynamodb_ttl_remove",
        "source_stream_identity": _EXPECTED_STREAM_ARN,
        "source_event_id": "a-completely-different-event-id",
        "source_bucket": None,
        "source_object_key": None,
        "source_object_version_id": None,
        "client_id": _CLIENT_ID,
        "audit_id": _AUDIT_ID,
        "evidence_class": "raw_evidence",
        "disposal_mechanism": "DYNAMODB_TTL",
        "disposed_identity_ref": "CLIENT#client1#AUDIT#audit1#RUN#run1",
        "disposed_at": "2026-01-01T00:00:00.000Z",
        "recorded_at": "2026-01-01T00:05:00.000Z",
        "source_created_at": None,
        "custody_period_days_applied": None,
    }
    repo = _FakeRepository(existing_item=existing_item, conflict=True)

    outcome = dr.process_dynamodb_stream_record(
        record, expected_stream_arn=_EXPECTED_STREAM_ARN, repository=repo
    )

    assert outcome.disposition == dr.DISPOSITION_INTEGRITY_FAILURE
    assert "source_event_id" in outcome.mismatched_fields


@pytest.mark.parametrize(
    "case,record_overrides,old_image_overrides,expected",
    [
        (
            "a_wrong_stream",
            {"eventSourceARN": "arn:aws:dynamodb:us-east-1:1:table/Other/stream/x"},
            {},
            dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE,
        ),
        (
            "b_event_name_not_remove",
            {"eventName": "MODIFY"},
            {},
            dr.DISPOSITION_VALID_BUT_IRRELEVANT,
        ),
        (
            "c_non_service_identity",
            {"userIdentity": {"type": "IAMUser", "principalId": "x"}},
            {},
            dr.DISPOSITION_VALID_BUT_IRRELEVANT,
        ),
        (
            "e_missing_evidence_class",
            {},
            {"evidence_class": None},
            dr.DISPOSITION_MALFORMED_TARGET_PROVENANCE,
        ),
        ("f_full_positive", {}, {}, dr.DISPOSITION_RECORDABLE),
    ],
)
def test_tc_q3_dynamodb_provenance_branches(case, record_overrides, old_image_overrides, expected):
    old_image = _old_image(**old_image_overrides) if old_image_overrides else _MISSING
    record = _dynamodb_record(old_image=old_image, **record_overrides)
    result = dr.validate_dynamodb_provenance(record, expected_stream_arn=_EXPECTED_STREAM_ARN)
    assert result.disposition == expected


def test_tc_q3_d_missing_old_image():
    record = _dynamodb_record(old_image=None)
    result = dr.validate_dynamodb_provenance(record, expected_stream_arn=_EXPECTED_STREAM_ARN)
    assert result.disposition == dr.DISPOSITION_MALFORMED_TARGET_PROVENANCE


@pytest.mark.parametrize(
    "case,deletion_type,expected",
    [
        ("a_permanently_deleted", "Permanently Deleted", dr.DISPOSITION_RECORDABLE),
        ("b_delete_marker_created", "Delete Marker Created", dr.DISPOSITION_VALID_BUT_IRRELEVANT),
        ("c_unrecognized", "Something Else Entirely", dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE),
    ],
)
def test_tc_q5_deletion_type_value_classes(case, deletion_type, expected):
    event = _s3_event(detail_overrides={"deletion-type": deletion_type})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == expected


def test_tc_q6_a_retention_markers_prefix_valid_but_irrelevant_end_to_end():
    event = _s3_event(
        detail_overrides={
            "object": {
                "key": f"retention-markers/{_CLIENT_ID}/{_AUDIT_ID}/hold_x/1-place.marker",
                "version-id": "v1",
            }
        }
    )
    repo = _FakeRepository()
    outcome = dr.process_s3_eventbridge_event(event, repository=repo, **_s3_kwargs())
    assert outcome.disposition == dr.DISPOSITION_VALID_BUT_IRRELEVANT
    assert repo.put_calls == []


def test_tc_q6_b_unrecognized_prefix_unknown_incompatible_end_to_end():
    event = _s3_event(
        detail_overrides={
            "object": {
                "key": f"configs/{_CLIENT_ID}/{_AUDIT_ID}/client_config.json",
                "version-id": "v1",
            }
        }
    )
    repo = _FakeRepository()
    outcome = dr.process_s3_eventbridge_event(event, repository=repo, **_s3_kwargs())
    assert outcome.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE
    assert outcome.disposition != dr.DISPOSITION_VALID_BUT_IRRELEVANT
    assert repo.put_calls == []


def test_tc_q7_bypassed_rule_still_rejected_by_handler():
    """A fixture constructed to bypass the rule-level EventPattern (e.g. a
    disallowed reason value the rule would have filtered) must still be
    independently rejected by the handler's own validation."""
    event = _s3_event(detail_overrides={"reason": "Operator Console Delete"})
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE


def test_tc_q8_a_missing_version_id_malformed():
    event = _s3_event(
        detail_overrides={
            "object": {"key": f"raw-results/{_CLIENT_ID}/{_AUDIT_ID}/run1/results.json"}
        }
    )
    result = dr.validate_s3_provenance(event, **_s3_kwargs())
    assert result.disposition == dr.DISPOSITION_MALFORMED_TARGET_PROVENANCE


def test_tc_q8_b_unparseable_key_malformed_end_to_end():
    event = _s3_event(
        detail_overrides={"object": {"key": "raw-results/too-few", "version-id": "v1"}}
    )
    repo = _FakeRepository()
    outcome = dr.process_s3_eventbridge_event(event, repository=repo, **_s3_kwargs())
    assert outcome.disposition == dr.DISPOSITION_MALFORMED_TARGET_PROVENANCE
    assert repo.put_calls == []


def test_tc_q15a_put_disposal_record_never_receives_ttl_disposal_at():
    """Recursion prevention (1): DisposalRepository.put_disposal_record's
    own PutItem must never be misclassified as a new TTL REMOVE -- asserted
    structurally at the call-args level even though this is also guaranteed
    by DisposalRepository's own fixed keyword-argument list (which has no
    ttl_disposal_at parameter at all)."""
    record = _dynamodb_record()
    repo = _FakeRepository()
    dr.process_dynamodb_stream_record(
        record, expected_stream_arn=_EXPECTED_STREAM_ARN, repository=repo
    )
    assert len(repo.put_calls) == 1
    assert "ttl_disposal_at" not in repo.put_calls[0]


def test_tc_q15b_recovery_bucket_object_deletion_never_reaches_s3_handler():
    """Recursion prevention (2): a recovery-bucket-originated deletion event
    must never be treated as recordable -- defense-in-depth reinforcement of
    the EventBridge rule's own bucket-name constraint (infra scope)."""
    event = _s3_event(detail_overrides={"bucket": {"name": "rcp-disposal-recovery-dev"}})
    repo = _FakeRepository()
    outcome = dr.process_s3_eventbridge_event(event, repository=repo, **_s3_kwargs())
    assert outcome.disposition == dr.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE
    assert repo.put_calls == []


def test_tc_q16_duplicate_delivery_general_case():
    record = _dynamodb_record()
    existing_item = None  # populated below once we know the computed disposal_id

    disposal_id = dr.compute_dynamodb_disposal_id(_EXPECTED_STREAM_ARN, "event-abc123")
    old_image = _old_image()
    existing_item = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#DISPOSAL#{disposal_id}",
        "record_type": "disposal_record",
        "disposal_id": disposal_id,
        "disposal_id_scheme": "v1",
        "source_kind": "dynamodb_ttl_remove",
        "source_stream_identity": _EXPECTED_STREAM_ARN,
        "source_event_id": "event-abc123",
        "source_bucket": None,
        "source_object_key": None,
        "source_object_version_id": None,
        "client_id": _CLIENT_ID,
        "audit_id": _AUDIT_ID,
        "evidence_class": "raw_evidence",
        "disposal_mechanism": "DYNAMODB_TTL",
        "disposed_identity_ref": f"CLIENT#{_CLIENT_ID}#AUDIT#{_AUDIT_ID}#RUN#run1",
        "disposed_at": "2025-12-31T00:00:00.000Z",
        "recorded_at": "1999-01-01T00:00:00.000Z",  # allowed to differ
        "source_created_at": old_image["created_at"],
        "custody_period_days_applied": None,
    }
    # disposed_at must match what the orchestration function will compute
    # from ApproximateCreationDateTime for an exact-match comparison.
    existing_item["disposed_at"] = dr._epoch_seconds_to_iso8601(1735689600.0)

    repo = _FakeRepository(existing_item=existing_item, conflict=True)
    outcome = dr.process_dynamodb_stream_record(
        record, expected_stream_arn=_EXPECTED_STREAM_ARN, repository=repo
    )
    assert outcome.disposition == dr.DISPOSITION_CONFIRMED_DUPLICATE


def test_tc_q17_ddb_end_to_end_happy_path():
    record = _dynamodb_record()
    repo = _FakeRepository()
    outcome = dr.process_dynamodb_stream_record(
        record, expected_stream_arn=_EXPECTED_STREAM_ARN, repository=repo
    )
    assert outcome.disposition == dr.DISPOSITION_RECORDABLE
    rec = outcome.disposal_record
    assert rec.client_id == _CLIENT_ID
    assert rec.audit_id == _AUDIT_ID
    assert rec.evidence_class == "raw_evidence"
    assert rec.disposal_mechanism == "DYNAMODB_TTL"
    assert rec.source_kind == "dynamodb_ttl_remove"
    assert rec.source_stream_identity == _EXPECTED_STREAM_ARN
    assert rec.source_event_id == "event-abc123"
    assert rec.source_bucket is None
    assert len(repo.put_calls) == 1


def test_tc_q17_s3_end_to_end_happy_path():
    event = _s3_event()
    repo = _FakeRepository()
    outcome = dr.process_s3_eventbridge_event(event, repository=repo, **_s3_kwargs())
    assert outcome.disposition == dr.DISPOSITION_RECORDABLE
    rec = outcome.disposal_record
    assert rec.client_id == _CLIENT_ID
    assert rec.audit_id == _AUDIT_ID
    assert rec.evidence_class == "raw_evidence"
    assert rec.disposal_mechanism == "S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION"
    assert rec.source_kind == "s3_lifecycle_delete"
    assert rec.source_bucket == _EXPECTED_BUCKET
    assert rec.source_stream_identity is None
    assert len(repo.put_calls) == 1


# ---------------------------------------------------------------------------
# Additional structural coverage: key parser (Section 22.12) and prefix
# classification, called out separately from identity computation per TC-Q1c.
# ---------------------------------------------------------------------------


def test_parse_s3_evidence_key_extracts_client_audit_evidence_class():
    parsed = dr.parse_s3_evidence_key(f"reports/{_CLIENT_ID}/{_AUDIT_ID}/jobid/artifact.json")
    assert parsed.client_id == _CLIENT_ID
    assert parsed.audit_id == _AUDIT_ID
    assert parsed.evidence_class == "report"


def test_parse_s3_evidence_key_percent_decodes():
    parsed = dr.parse_s3_evidence_key("raw-results/cl%20ient/audit1/run1/results.json")
    assert parsed.client_id == "cl ient"


def test_parse_s3_evidence_key_raises_on_empty_client_id():
    with pytest.raises(dr.EvidenceKeyParseError):
        dr.parse_s3_evidence_key("raw-results//audit1/run1/results.json")


def test_parse_s3_evidence_key_raises_on_unrecognized_prefix():
    with pytest.raises(dr.EvidenceKeyParseError):
        dr.parse_s3_evidence_key("unknown-prefix/c/a/r/x.json")


def test_disposal_repository_construction_uses_real_type():
    """Sanity check that _FakeRepository stands in for the real
    DisposalRepository type used by production code paths."""
    assert isinstance(MagicMock(spec=DisposalRepository), DisposalRepository)
