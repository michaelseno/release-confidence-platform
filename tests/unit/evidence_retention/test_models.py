"""Unit tests for evidence_retention Workstream A1.1 Pydantic models.

Covers construction and (de)serialization for LegalHold, LegalHoldEvent, and
DisposalRecord, mirroring the fixture-based test style established in
audit_platform_integrity/test_models.py (MOD-01..MOD-19).
"""

from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from release_confidence_platform.evidence_retention.identity import (
    generate_disposal_id,
    generate_hold_id,
)
from release_confidence_platform.evidence_retention.models import (
    DisposalRecord,
    LegalHold,
    LegalHoldEvent,
)

_CLIENT_ID = "client1"
_AUDIT_ID = "audit1"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _valid_legal_hold_data(**overrides: Any) -> dict[str, Any]:
    hold_id = generate_hold_id()
    data = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#LEGALHOLD",
        "record_type": "legal_hold",
        "client_id": _CLIENT_ID,
        "audit_id": _AUDIT_ID,
        "status": "ACTIVE",
        "hold_id": hold_id,
        "hold_version": 1,
        "sweep_status": "PENDING",
        "placed_at": "2026-07-18T00:00:00.000Z",
        "placed_by": "operator_a",
        "reason": "litigation hold",
        "hold_count": 1,
    }
    data.update(overrides)
    return data


def _valid_legal_hold_event_data(**overrides: Any) -> dict[str, Any]:
    hold_id = generate_hold_id()
    hold_version = overrides.get("hold_version", 1)
    data = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#LEGALHOLD#{hold_id}#{hold_version}",
        "record_type": "legal_hold_event",
        "hold_id": hold_id,
        "hold_version": hold_version,
        "client_id": _CLIENT_ID,
        "audit_id": _AUDIT_ID,
        "action": "PLACE",
        "actor": "operator_a",
        "reason": "litigation hold",
        "timestamp": "2026-07-18T00:00:00.000Z",
        "s3_versions_retagged_count": 4,
        "dynamodb_items_updated_count": 2,
    }
    data.update(overrides)
    return data


def _valid_disposal_record_data(**overrides: Any) -> dict[str, Any]:
    disposal_id = generate_disposal_id()
    data = {
        "PK": f"CLIENT#{_CLIENT_ID}",
        "SK": f"AUDIT#{_AUDIT_ID}#DISPOSAL#{disposal_id}",
        "record_type": "disposal_record",
        "disposal_id": disposal_id,
        "client_id": _CLIENT_ID,
        "audit_id": _AUDIT_ID,
        "evidence_class": "raw_evidence",
        "disposal_mechanism": "DYNAMODB_TTL",
        "disposed_identity_ref": f"CLIENT#{_CLIENT_ID}#AUDIT#{_AUDIT_ID}#RUN#run1",
        "disposed_at": "2026-07-18T00:00:00.000Z",
        "recorded_at": "2026-07-18T00:05:00.000Z",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# LegalHold
# ---------------------------------------------------------------------------


def test_legal_hold_valid_construction():
    hold = LegalHold(**_valid_legal_hold_data())
    assert hold.status == "ACTIVE"
    assert hold.hold_count == 1
    assert hold.released_at is None
    assert hold.released_by is None


def test_legal_hold_valid_released_construction():
    hold = LegalHold(
        **_valid_legal_hold_data(
            status="RELEASED",
            released_at="2026-07-19T00:00:00.000Z",
            released_by="operator_b",
            hold_count=1,
        )
    )
    assert hold.status == "RELEASED"
    assert hold.released_at == "2026-07-19T00:00:00.000Z"


def test_legal_hold_rejects_unknown_status():
    data = _valid_legal_hold_data(status="ON_HOLD")
    with pytest.raises(ValidationError):
        LegalHold(**data)


def test_legal_hold_rejects_unknown_record_type():
    data = _valid_legal_hold_data(record_type="something_else")
    with pytest.raises(ValidationError):
        LegalHold(**data)


def test_legal_hold_rejects_released_without_released_at():
    data = _valid_legal_hold_data(status="RELEASED", released_by="operator_b")
    with pytest.raises(ValidationError):
        LegalHold(**data)


def test_legal_hold_rejects_released_without_released_by():
    data = _valid_legal_hold_data(status="RELEASED", released_at="2026-07-19T00:00:00.000Z")
    with pytest.raises(ValidationError):
        LegalHold(**data)


def test_legal_hold_rejects_hold_count_below_one():
    data = _valid_legal_hold_data(hold_count=0)
    with pytest.raises(ValidationError):
        LegalHold(**data)


# ---------------------------------------------------------------------------
# LegalHold — hold_version / sweep_status (Legal-Hold Correction B1;
# Technical Design Section 19.1; ADR Non-Negotiable Invariants 12/23)
# ---------------------------------------------------------------------------


def test_legal_hold_accepts_all_bounded_sweep_statuses():
    for sweep_status in ("PENDING", "IN_PROGRESS", "COMPLETE", "FAILED"):
        hold = LegalHold(**_valid_legal_hold_data(sweep_status=sweep_status))
        assert hold.sweep_status == sweep_status


def test_legal_hold_rejects_unknown_sweep_status():
    data = _valid_legal_hold_data(sweep_status="DONE")
    with pytest.raises(ValidationError):
        LegalHold(**data)


def test_legal_hold_rejects_hold_version_below_one():
    data = _valid_legal_hold_data(hold_version=0)
    with pytest.raises(ValidationError):
        LegalHold(**data)


def test_legal_hold_status_and_sweep_status_are_independent_fields():
    """Required behavior 7/8: status=ACTIVE with sweep_status still PENDING
    must construct validly -- status is never derived from sweep_status or
    vice versa, and ACTIVE alone must not be conflated with fully enforced."""
    hold = LegalHold(**_valid_legal_hold_data(status="ACTIVE", sweep_status="PENDING"))
    assert hold.status == "ACTIVE"
    assert hold.sweep_status == "PENDING"


def test_legal_hold_marker_fields_default_to_none():
    """B1 plumbing default -- B2 (S3 canary marker) is the only mechanism
    that ever sets these to a non-None value."""
    hold = LegalHold(**_valid_legal_hold_data())
    assert hold.marker_s3_key is None
    assert hold.marker_confirmed_last_modified is None


def test_legal_hold_to_dict_returns_plain_dict():
    hold = LegalHold(**_valid_legal_hold_data())
    result = hold.to_dict()
    assert isinstance(result, dict)
    assert result["status"] == "ACTIVE"
    assert result["PK"] == f"CLIENT#{_CLIENT_ID}"


def test_legal_hold_construction_does_not_mutate_input():
    data = _valid_legal_hold_data()
    original = copy.deepcopy(data)
    LegalHold(**data)
    assert data == original


# ---------------------------------------------------------------------------
# LegalHoldEvent
# ---------------------------------------------------------------------------


def test_legal_hold_event_valid_construction():
    event = LegalHoldEvent(**_valid_legal_hold_event_data())
    assert event.action == "PLACE"
    assert event.s3_versions_retagged_count == 4


def test_legal_hold_event_valid_release_action():
    event = LegalHoldEvent(**_valid_legal_hold_event_data(action="RELEASE"))
    assert event.action == "RELEASE"


def test_legal_hold_event_rejects_unknown_action():
    data = _valid_legal_hold_event_data(action="MODIFY")
    with pytest.raises(ValidationError):
        LegalHoldEvent(**data)


def test_legal_hold_event_rejects_unknown_record_type():
    data = _valid_legal_hold_event_data(record_type="legal_hold")
    with pytest.raises(ValidationError):
        LegalHoldEvent(**data)


def test_legal_hold_event_rejects_negative_s3_count():
    data = _valid_legal_hold_event_data(s3_versions_retagged_count=-1)
    with pytest.raises(ValidationError):
        LegalHoldEvent(**data)


def test_legal_hold_event_rejects_negative_dynamodb_count():
    data = _valid_legal_hold_event_data(dynamodb_items_updated_count=-1)
    with pytest.raises(ValidationError):
        LegalHoldEvent(**data)


# ---------------------------------------------------------------------------
# LegalHoldEvent — hold_version / marker_* (Legal-Hold Correction B1; ADR
# Non-Negotiable Invariant 25; Technical Design Section 19.5.1)
# ---------------------------------------------------------------------------


def test_legal_hold_event_rejects_hold_version_below_one():
    data = _valid_legal_hold_event_data(hold_version=0)
    with pytest.raises(ValidationError):
        LegalHoldEvent(**data)


def test_legal_hold_event_marker_status_defaults_to_pending():
    event = LegalHoldEvent(**_valid_legal_hold_event_data())
    assert event.marker_status == "PENDING"
    assert event.marker_s3_key is None
    assert event.marker_confirmed_last_modified is None


def test_legal_hold_event_accepts_all_bounded_marker_statuses():
    for marker_status in ("PENDING", "CONFIRMED", "FAILED"):
        event = LegalHoldEvent(**_valid_legal_hold_event_data(marker_status=marker_status))
        assert event.marker_status == marker_status


def test_legal_hold_event_rejects_unknown_marker_status():
    data = _valid_legal_hold_event_data(marker_status="UNKNOWN")
    with pytest.raises(ValidationError):
        LegalHoldEvent(**data)


def test_legal_hold_event_place_and_release_of_same_hold_id_have_distinct_hold_version():
    """Required behavior 2/4: PLACE and its paired RELEASE share hold_id but
    must carry distinct hold_version values, and therefore distinct SKs."""
    hold_id = generate_hold_id()
    place = LegalHoldEvent(
        **_valid_legal_hold_event_data(hold_id=hold_id, hold_version=1, action="PLACE")
    )
    release = LegalHoldEvent(
        **_valid_legal_hold_event_data(hold_id=hold_id, hold_version=2, action="RELEASE")
    )
    assert place.hold_id == release.hold_id
    assert place.hold_version != release.hold_version
    assert place.SK != release.SK


def test_legal_hold_event_to_dict_returns_plain_dict():
    event = LegalHoldEvent(**_valid_legal_hold_event_data())
    result = event.to_dict()
    assert isinstance(result, dict)
    assert result["action"] == "PLACE"


# ---------------------------------------------------------------------------
# DisposalRecord
# ---------------------------------------------------------------------------


def test_disposal_record_valid_construction():
    record = DisposalRecord(**_valid_disposal_record_data())
    assert record.disposal_mechanism == "DYNAMODB_TTL"
    assert record.evidence_class == "raw_evidence"
    assert record.source_created_at is None
    assert record.custody_period_days_applied is None


def test_disposal_record_valid_s3_mechanism_construction():
    record = DisposalRecord(
        **_valid_disposal_record_data(
            evidence_class="report",
            disposal_mechanism="S3_LIFECYCLE_EXPIRATION",
            disposed_identity_ref="reports/client1/audit1/artifact.json",
            custody_period_days_applied=90,
            source_created_at="2026-01-01T00:00:00.000Z",
        )
    )
    assert record.disposal_mechanism == "S3_LIFECYCLE_EXPIRATION"
    assert record.custody_period_days_applied == 90


def test_disposal_record_valid_noncurrent_version_mechanism():
    record = DisposalRecord(
        **_valid_disposal_record_data(
            disposal_mechanism="S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION",
        )
    )
    assert record.disposal_mechanism == "S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION"


def test_disposal_record_rejects_unknown_evidence_class():
    data = _valid_disposal_record_data(evidence_class="unknown_class")
    with pytest.raises(ValidationError):
        DisposalRecord(**data)


def test_disposal_record_rejects_unknown_disposal_mechanism():
    data = _valid_disposal_record_data(disposal_mechanism="MANUAL_DELETE")
    with pytest.raises(ValidationError):
        DisposalRecord(**data)


def test_disposal_record_rejects_unknown_record_type():
    data = _valid_disposal_record_data(record_type="legal_hold")
    with pytest.raises(ValidationError):
        DisposalRecord(**data)


def test_disposal_record_rejects_negative_custody_period_days():
    data = _valid_disposal_record_data(custody_period_days_applied=-1)
    with pytest.raises(ValidationError):
        DisposalRecord(**data)


def test_disposal_record_rejects_recorded_at_before_disposed_at():
    data = _valid_disposal_record_data(
        disposed_at="2026-07-18T00:10:00.000Z",
        recorded_at="2026-07-18T00:00:00.000Z",
    )
    with pytest.raises(ValidationError):
        DisposalRecord(**data)


def test_disposal_record_accepts_recorded_at_equal_to_disposed_at():
    data = _valid_disposal_record_data(
        disposed_at="2026-07-18T00:00:00.000Z",
        recorded_at="2026-07-18T00:00:00.000Z",
    )
    record = DisposalRecord(**data)
    assert record.recorded_at == record.disposed_at


def test_disposal_record_to_dict_returns_plain_dict():
    record = DisposalRecord(**_valid_disposal_record_data())
    result = record.to_dict()
    assert isinstance(result, dict)
    assert result["disposal_mechanism"] == "DYNAMODB_TTL"


# ---------------------------------------------------------------------------
# Identity generation
# ---------------------------------------------------------------------------


def test_generate_hold_id_has_correct_prefix():
    hold_id = generate_hold_id()
    assert hold_id.startswith("hold_")


def test_generate_disposal_id_has_correct_prefix():
    disposal_id = generate_disposal_id()
    assert disposal_id.startswith("disp_")


def test_generate_hold_id_unique_on_repeated_calls():
    ids = {generate_hold_id() for _ in range(20)}
    assert len(ids) == 20


def test_generate_disposal_id_unique_on_repeated_calls():
    ids = {generate_disposal_id() for _ in range(20)}
    assert len(ids) == 20
