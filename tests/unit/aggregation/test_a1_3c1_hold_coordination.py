"""Evidence Governance Workstream A1.3c.1 — dedicated coverage for
AggregationRepository.put_records_once / put_lineage_page_once's legal-hold
coordination, custody-field computation, and the corrected transaction
item/byte budget (Technical Design Section 19.4, 19.16; ADR Decision 5
amendment / Non-Negotiable Invariant 26).
"""

from __future__ import annotations

import json

import pytest

import release_confidence_platform.aggregation.repository as repository_module
from release_confidence_platform.aggregation.repository import (
    AggregationRepository,
    ConditionalWriteError,
    _measure_item_bytes,
)
from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldStateConcurrencyExceededError,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.storage.dynamodb_codec import encode_item
from tests.unit.aggregation._hold_coordination_double import (
    RecordingHoldAwareClient,
    place_hold,
    release_hold,
)

CLIENT_ID = "client"
AUDIT_ID = "audit"


def _make_repo(client: RecordingHoldAwareClient | None = None):
    client = client or RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)
    return repo, hold_repository, client


def _record(n: int = 0) -> dict:
    return {"PK": f"CLIENT#{CLIENT_ID}", "SK": f"AUDIT#{AUDIT_ID}#REC#{n}", "value": n}


def _lineage_page(n: int = 0) -> dict:
    return {
        "PK": f"CLIENT#{CLIENT_ID}",
        "SK": f"AUDIT#{AUDIT_ID}#LINEAGE#page{n}",
        "page_hash": "hash-abc",
    }


# ---------------------------------------------------------------------------
# Fail-closed: hold_repository not configured
# ---------------------------------------------------------------------------


def test_put_records_once_fails_closed_when_hold_repository_missing():
    client = RecordingHoldAwareClient()
    repo = AggregationRepository("metadata-table", client)  # no hold_repository

    with pytest.raises(StorageError) as exc_info:
        repo.put_records_once([_record()], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"
    assert client.get_item_calls == []
    assert client.transact_calls == []


def test_put_lineage_page_once_fails_closed_when_hold_repository_missing():
    client = RecordingHoldAwareClient()
    repo = AggregationRepository("metadata-table", client)  # no hold_repository

    with pytest.raises(StorageError) as exc_info:
        repo.put_lineage_page_once(_lineage_page(), client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"
    assert client.get_item_calls == []
    assert client.transact_calls == []


# ---------------------------------------------------------------------------
# Custody-period resolution — fail-closed on missing/invalid configuration,
# for both governed write methods, before any hold read / transact-item
# construction / AWS request.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_value", [None, "", "not-a-number", "0", "-1", "-100"])
def test_put_records_once_custody_period_fails_closed(monkeypatch, bad_value):
    if bad_value is None:
        monkeypatch.delenv("CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA", raising=False)
    else:
        monkeypatch.setenv("CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA", bad_value)
    repo, hold_repository, client = _make_repo()

    with pytest.raises(StorageError) as exc_info:
        repo.put_records_once([_record()], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert exc_info.value.error_type == "CUSTODY_PERIOD_CONFIG_MISSING"
    assert client.get_item_calls == [], "no hold-state read before failing closed"
    assert client.transact_calls == [], "no AWS transact request before failing closed"


@pytest.mark.parametrize("bad_value", [None, "", "not-a-number", "0", "-1", "-100"])
def test_put_lineage_page_once_custody_period_fails_closed(monkeypatch, bad_value):
    if bad_value is None:
        monkeypatch.delenv("CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA", raising=False)
    else:
        monkeypatch.setenv("CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA", bad_value)
    repo, hold_repository, client = _make_repo()

    with pytest.raises(StorageError) as exc_info:
        repo.put_lineage_page_once(_lineage_page(), client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert exc_info.value.error_type == "CUSTODY_PERIOD_CONFIG_MISSING"
    assert client.get_item_calls == [], "no hold-state read before failing closed"
    assert client.transact_calls == [], "no AWS transact request before failing closed"


def test_custody_period_config_missing_checked_before_hold_repository_none_is_irrelevant(
    monkeypatch,
):
    """Ordering: hold_repository=None is checked first (unconditionally),
    then custody-period resolution -- both fail before item-count / hold
    reads. This test pins that hold_repository=None wins when both are
    simultaneously true."""
    monkeypatch.delenv("CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA", raising=False)
    client = RecordingHoldAwareClient()
    repo = AggregationRepository("metadata-table", client)

    with pytest.raises(StorageError) as exc_info:
        repo.put_records_once([_record()], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert exc_info.value.error_type == "HOLD_COORDINATION_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# Governance-field override / caller-dict immutability
# ---------------------------------------------------------------------------


def test_put_records_once_silently_overrides_caller_supplied_governance_fields():
    repo, hold_repository, client = _make_repo()
    original = {
        "PK": f"CLIENT#{CLIENT_ID}",
        "SK": f"AUDIT#{AUDIT_ID}#REC#0",
        "custody_expires_at": 1,
        "ttl_disposal_at": 2,
        "evidence_class": "not_aggregate_metadata",
    }
    original_copy = dict(original)

    repo.put_records_once([original], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    # Caller's original dict object must be untouched.
    assert original == original_copy

    persisted = client.storage[(f"CLIENT#{CLIENT_ID}", f"AUDIT#{AUDIT_ID}#REC#0")]
    assert persisted["evidence_class"]["S"] == "aggregate_metadata"
    # custody_expires_at/ttl_disposal_at are NOT the caller-supplied 1/2.
    from boto3.dynamodb.types import TypeDeserializer

    deser = TypeDeserializer()
    assert int(deser.deserialize(persisted["custody_expires_at"])) != 1
    assert int(deser.deserialize(persisted["ttl_disposal_at"])) != 2


def test_put_lineage_page_once_silently_overrides_caller_supplied_governance_fields():
    repo, hold_repository, client = _make_repo()
    original = {**_lineage_page(), "custody_expires_at": 1, "evidence_class": "wrong"}
    original_copy = dict(original)

    repo.put_lineage_page_once(original, client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert original == original_copy
    persisted = client.storage[(original["PK"], original["SK"])]
    assert persisted["evidence_class"]["S"] == "aggregate_metadata"


# ---------------------------------------------------------------------------
# Hold-transition races — both directions, both methods
# ---------------------------------------------------------------------------


def test_put_records_once_no_hold_to_active_race_bounded_success():
    """A hold is placed concurrently between attempt 1's read and its
    commit. Attempt 1's ConditionCheck (attribute_not_exists(PK)) must fail
    because the LegalHold record now exists; attempt 2 must re-read fresh,
    observe ACTIVE, and correctly omit ttl_disposal_at on the record that
    actually commits."""
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)

    real_get_item = client.get_item
    calls = {"n": 0}

    def get_item_with_side_effect(*args, **kwargs):
        calls["n"] += 1
        result = real_get_item(*args, **kwargs)
        if calls["n"] == 1:
            # Simulate a concurrent PLACE landing right after this read
            # returns its (now-stale) snapshot but before the transaction
            # commits.
            place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
        return result

    client.get_item = get_item_with_side_effect

    repo.put_records_once([_record()], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert calls["n"] == 2, "exactly one fresh hold read per attempt, two attempts total"
    assert len(client.transact_calls) == 2, "first attempt cancelled, second committed"
    persisted = client.storage[(f"CLIENT#{CLIENT_ID}", f"AUDIT#{AUDIT_ID}#REC#0")]
    assert "ttl_disposal_at" not in persisted, (
        "the successful attempt observed ACTIVE -- ttl_disposal_at must be omitted"
    )


def test_put_records_once_active_to_released_race_bounded_success():
    """A hold is released concurrently between attempt 1's read (observing
    ACTIVE, hold_version=1) and its commit. Attempt 1's ConditionCheck must
    fail (hold_version now 2); attempt 2 re-reads fresh, observes RELEASED,
    and correctly includes ttl_disposal_at."""
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)
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

    repo.put_records_once([_record()], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert calls["n"] == 2
    assert len(client.transact_calls) == 2
    persisted = client.storage[(f"CLIENT#{CLIENT_ID}", f"AUDIT#{AUDIT_ID}#REC#0")]
    assert "ttl_disposal_at" in persisted, (
        "the successful attempt observed RELEASED -- ttl_disposal_at must be present"
    )


def test_put_lineage_page_once_no_hold_to_active_race_bounded_success():
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)

    real_get_item = client.get_item
    calls = {"n": 0}

    def get_item_with_side_effect(*args, **kwargs):
        calls["n"] += 1
        result = real_get_item(*args, **kwargs)
        if calls["n"] == 1:
            place_hold(hold_repository, CLIENT_ID, AUDIT_ID, hold_version=1)
        return result

    client.get_item = get_item_with_side_effect

    repo.put_lineage_page_once(_lineage_page(), client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert calls["n"] == 2
    persisted = client.storage[
        (f"CLIENT#{CLIENT_ID}", f"AUDIT#{AUDIT_ID}#LINEAGE#page0")
    ]
    assert "ttl_disposal_at" not in persisted


def test_put_lineage_page_once_active_to_released_race_bounded_success():
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)
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

    repo.put_lineage_page_once(_lineage_page(), client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert calls["n"] == 2
    persisted = client.storage[
        (f"CLIENT#{CLIENT_ID}", f"AUDIT#{AUDIT_ID}#LINEAGE#page0")
    ]
    assert "ttl_disposal_at" in persisted


def test_put_records_once_hold_race_retry_exhaustion_fails_closed():
    """The hold ConditionCheck fails on every attempt (a sustained,
    never-resolving race) -- retries are bounded at 3, and exhaustion raises
    HOLD_STATE_CONCURRENCY_EXCEEDED, never an unconditioned fallback write."""
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)

    real_get_item = client.get_item
    calls = {"n": 0}

    def get_item_with_side_effect(*args, **kwargs):
        calls["n"] += 1
        # Every read observes "no hold" (None) -- but force the hold
        # ConditionCheck (last item) to fail on every attempt, simulating a
        # hold that is always placed a moment after each read.
        return real_get_item(*args, **kwargs)

    client.get_item = get_item_with_side_effect
    client.force_fail_indices_by_attempt = {1: {1}, 2: {1}, 3: {1}}

    with pytest.raises(HoldStateConcurrencyExceededError) as exc_info:
        repo.put_records_once([_record()], client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert exc_info.value.error_type == "HOLD_STATE_CONCURRENCY_EXCEEDED"
    assert calls["n"] == 3, "exactly 3 bounded attempts, one fresh read each"
    assert len(client.transact_calls) == 3
    assert (f"CLIENT#{CLIENT_ID}", f"AUDIT#{AUDIT_ID}#REC#0") not in client.storage, (
        "no partial/unconditioned write ever commits on exhaustion"
    )


def test_put_lineage_page_once_hold_race_retry_exhaustion_fails_closed():
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)
    client.force_fail_indices_by_attempt = {1: {1}, 2: {1}, 3: {1}}

    with pytest.raises(HoldStateConcurrencyExceededError):
        repo.put_lineage_page_once(_lineage_page(), client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert len(client.transact_calls) == 3
    assert (
        f"CLIENT#{CLIENT_ID}",
        f"AUDIT#{AUDIT_ID}#LINEAGE#page0",
    ) not in client.storage


# ---------------------------------------------------------------------------
# Governed-condition vs. hold-condition precedence (cancellation-index tests)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 10, 31])
@pytest.mark.parametrize("position", ["first", "middle", "last"])
def test_governed_failure_wins_over_hold_check_regardless_of_position(n, position):
    """A governed record's own condition failure must surface as
    ConditionalWriteError, never masked behind a hold-version retry, at
    every governed index position and every tested transaction size."""
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)
    records = [_record(i) for i in range(n)]

    index_map = {"first": 0, "middle": n // 2, "last": n - 1}
    governed_index = index_map[position]
    # Also force the hold-check (final index, n) to fail in the SAME
    # attempt -- governed failure must still win per Section 19.4 step 4.
    client.force_fail_indices_by_attempt = {1: {governed_index, n}}

    with pytest.raises(ConditionalWriteError):
        repo.put_records_once(records, client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert len(client.transact_calls) == 1, "governed failure must never trigger a retry"


@pytest.mark.parametrize("n", [1, 10, 31])
def test_hold_check_alone_failing_enters_bounded_retry(n):
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)
    records = [_record(i) for i in range(n)]

    # Fail only the hold-check index (n) on attempt 1; succeed on attempt 2.
    client.force_fail_indices_by_attempt = {1: {n}}

    repo.put_records_once(records, client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert len(client.transact_calls) == 2, "hold-only failure retries, then succeeds"


# ---------------------------------------------------------------------------
# Item-count budget (repository-level, synthetic record lists)
# ---------------------------------------------------------------------------


def test_put_records_once_accepts_exactly_99_governed_records():
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)
    records = [_record(i) for i in range(99)]

    repo.put_records_once(records, client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert len(client.transact_calls[-1]) == 100, "99 governed Puts + 1 ConditionCheck"


def test_put_records_once_rejects_100_governed_records_before_any_aws_call():
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)
    records = [_record(i) for i in range(100)]

    with pytest.raises(StorageError) as exc_info:
        repo.put_records_once(records, client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert exc_info.value.error_type == "AGGREGATE_SET_TOO_LARGE"
    assert exc_info.value.message == (
        "Aggregate set exceeds the governed atomic-transaction limit. Reduce the "
        "configured endpoint scope or obtain a separately reviewed architecture "
        "decision."
    )
    assert client.get_item_calls == [], "zero hold reads on item-count rejection"
    assert client.transact_calls == [], "zero AWS calls on item-count rejection"


# ---------------------------------------------------------------------------
# Byte boundaries — exact equality, post-augmentation, real encode/measure
# ---------------------------------------------------------------------------


def _encoded_single_record_item_bytes(hold_state=None, custody_days=90) -> int:
    """Compute the real, post-governance-merge encoded byte size of one
    minimal record, via the actual production helpers (never hand-rolled),
    so boundary constants can be set to an exact, real value."""
    governance = repository_module._aggregate_governance_fields(hold_state, custody_days)
    merged = {**_record(0), **governance}
    return _measure_item_bytes(encode_item(merged))


def test_put_records_once_item_byte_boundary_exact_equality(monkeypatch):
    exact_size = _encoded_single_record_item_bytes()
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)

    monkeypatch.setattr(repository_module, "MAX_AGGREGATE_ITEM_BYTES", exact_size)
    repo.put_records_once([_record(0)], client_id=CLIENT_ID, audit_id="audit-ok")

    monkeypatch.setattr(repository_module, "MAX_AGGREGATE_ITEM_BYTES", exact_size - 1)
    with pytest.raises(StorageError) as exc_info:
        repo.put_records_once([_record(0)], client_id=CLIENT_ID, audit_id="audit-reject")
    assert exc_info.value.error_type == "AGGREGATE_SET_TOO_LARGE"


def test_put_lineage_page_once_item_byte_boundary_exact_equality(monkeypatch):
    governance = repository_module._aggregate_governance_fields(None, 90)
    merged = {**_lineage_page(0), **governance}
    exact_size = _measure_item_bytes(encode_item(merged))

    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)

    monkeypatch.setattr(repository_module, "MAX_AGGREGATE_ITEM_BYTES", exact_size)
    repo.put_lineage_page_once(_lineage_page(0), client_id=CLIENT_ID, audit_id="a-ok")

    monkeypatch.setattr(repository_module, "MAX_AGGREGATE_ITEM_BYTES", exact_size - 1)
    with pytest.raises(StorageError) as exc_info:
        repo.put_lineage_page_once(_lineage_page(0), client_id=CLIENT_ID, audit_id="a-reject")
    assert exc_info.value.error_type == "AGGREGATE_SET_TOO_LARGE"


def test_put_records_once_pre_merge_safe_item_becomes_post_merge_unsafe(monkeypatch):
    """A record whose pre-governance-merge size is under the ceiling can be
    pushed over it by the added custody/evidence_class attributes -- proving
    the guard evaluates post-augmentation, never pre-augmentation."""
    pre_merge_size = len(
        json.dumps(encode_item(_record(0)), sort_keys=True, default=str).encode("utf-8")
    )
    post_merge_size = _encoded_single_record_item_bytes()
    assert post_merge_size > pre_merge_size, "sanity: governance fields add real bytes"

    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)

    # Ceiling set strictly between the two sizes: a pre-merge check would
    # accept; the required post-merge check must reject.
    monkeypatch.setattr(repository_module, "MAX_AGGREGATE_ITEM_BYTES", post_merge_size - 1)
    with pytest.raises(StorageError) as exc_info:
        repo.put_records_once([_record(0)], client_id=CLIENT_ID, audit_id=AUDIT_ID)
    assert exc_info.value.error_type == "AGGREGATE_SET_TOO_LARGE"


def test_put_lineage_page_once_pre_merge_safe_item_becomes_post_merge_unsafe(monkeypatch):
    """A lineage-page item whose pre-governance-merge size is under the
    ceiling can be pushed over it by the added custody/evidence_class
    attributes -- proving the guard evaluates post-augmentation, never
    pre-augmentation, for put_lineage_page_once too (Technical Design
    Section 19.16.2, which applies this requirement identically to both
    governed write paths)."""
    pre_merge_size = len(
        json.dumps(encode_item(_lineage_page(0)), sort_keys=True, default=str).encode("utf-8")
    )
    governance = repository_module._aggregate_governance_fields(None, 90)
    merged = {**_lineage_page(0), **governance}
    post_merge_size = _measure_item_bytes(encode_item(merged))
    assert post_merge_size > pre_merge_size, "sanity: governance fields add real bytes"

    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)

    # Ceiling set strictly between the two sizes: a pre-merge check would
    # accept; the required post-merge check must reject.
    monkeypatch.setattr(repository_module, "MAX_AGGREGATE_ITEM_BYTES", post_merge_size - 1)
    with pytest.raises(StorageError) as exc_info:
        repo.put_lineage_page_once(_lineage_page(0), client_id=CLIENT_ID, audit_id=AUDIT_ID)
    assert exc_info.value.error_type == "AGGREGATE_SET_TOO_LARGE"


def test_put_records_once_transaction_byte_boundary_exact_equality(monkeypatch):
    from release_confidence_platform.evidence_retention.hold_coordination import (
        build_hold_version_condition_check_item,
    )

    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)
    records = [_record(i) for i in range(3)]

    # Compute the exact expected transaction size deterministically, via the
    # same governance-merge -> encode -> construct -> measure sequence the
    # repository itself performs (never a separate/approximate
    # calculation), so the boundary constant can be set to a real,
    # exactly-matching value without needing a prior probe write (which
    # would collide with the accept call's identical records).
    governance = repository_module._aggregate_governance_fields(None, 90)
    put_items = [
        {
            "Put": {
                "TableName": "metadata-table",
                "Item": encode_item({**r, **governance}),
                "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
            }
        }
        for r in records
    ]
    hold_condition_item = build_hold_version_condition_check_item(
        "metadata-table", hold_repository.legal_hold_key(CLIENT_ID, AUDIT_ID), None
    )
    exact_size = repository_module._measure_transaction_bytes(put_items + [hold_condition_item])

    monkeypatch.setattr(repository_module, "MAX_AGGREGATE_TRANSACTION_BYTES", exact_size)
    repo.put_records_once(records, client_id=CLIENT_ID, audit_id=AUDIT_ID)

    # Same records, now already persisted -- but the byte-budget rejection
    # below is deterministically raised BEFORE any AWS call, so re-using the
    # identical records causes no duplicate-write interference.
    monkeypatch.setattr(repository_module, "MAX_AGGREGATE_TRANSACTION_BYTES", exact_size - 1)
    reads_before = len(client.get_item_calls)
    with pytest.raises(StorageError) as exc_info:
        repo.put_records_once(records, client_id=CLIENT_ID, audit_id=AUDIT_ID)
    assert exc_info.value.error_type == "AGGREGATE_SET_TOO_LARGE"
    # Byte-size rejection reads the hold exactly once for this attempt, then
    # rejects before any transact_write_items call.
    assert len(client.get_item_calls) == reads_before + 1


def test_put_lineage_page_once_transaction_byte_boundary_exact_equality(monkeypatch):
    from release_confidence_platform.evidence_retention.hold_coordination import (
        build_hold_version_condition_check_item,
    )

    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)
    page = _lineage_page(0)

    # Compute the exact expected transaction size deterministically, via the
    # same governance-merge -> encode -> construct -> measure sequence the
    # repository itself performs (never a separate/approximate
    # calculation), so the boundary constant can be set to a real,
    # exactly-matching value without needing a prior probe write (which
    # would collide with the accept call's identical item). Mirrors
    # test_put_records_once_transaction_byte_boundary_exact_equality,
    # adapted for put_lineage_page_once's fixed two-item (Put +
    # ConditionCheck) transaction shape rather than a variable-length list.
    governance = repository_module._aggregate_governance_fields(None, 90)
    put_transact_item = {
        "Put": {
            "TableName": "metadata-table",
            "Item": encode_item({**page, **governance}),
            "ConditionExpression": "attribute_not_exists(PK) AND attribute_not_exists(SK)",
        }
    }
    hold_condition_item = build_hold_version_condition_check_item(
        "metadata-table", hold_repository.legal_hold_key(CLIENT_ID, AUDIT_ID), None
    )
    exact_size = repository_module._measure_transaction_bytes(
        [put_transact_item, hold_condition_item]
    )

    monkeypatch.setattr(repository_module, "MAX_AGGREGATE_TRANSACTION_BYTES", exact_size)
    repo.put_lineage_page_once(page, client_id=CLIENT_ID, audit_id=AUDIT_ID)

    # Same page, already persisted -- but the byte-budget rejection below is
    # deterministically raised BEFORE any AWS call, so re-using the
    # identical item causes no duplicate-write interference.
    monkeypatch.setattr(repository_module, "MAX_AGGREGATE_TRANSACTION_BYTES", exact_size - 1)
    reads_before = len(client.get_item_calls)
    with pytest.raises(StorageError) as exc_info:
        repo.put_lineage_page_once(page, client_id=CLIENT_ID, audit_id=AUDIT_ID)
    assert exc_info.value.error_type == "AGGREGATE_SET_TOO_LARGE"
    # Byte-size rejection reads the hold exactly once for this attempt, then
    # rejects before any transact_write_items call.
    assert len(client.get_item_calls) == reads_before + 1


def test_put_records_once_transaction_byte_rejection_reads_hold_exactly_once(monkeypatch):
    client = RecordingHoldAwareClient()
    hold_repository = HoldRepository("metadata-table", client)
    repo = AggregationRepository("metadata-table", client, hold_repository)
    records = [_record(i) for i in range(3)]

    monkeypatch.setattr(repository_module, "MAX_AGGREGATE_TRANSACTION_BYTES", 1)

    with pytest.raises(StorageError) as exc_info:
        repo.put_records_once(records, client_id=CLIENT_ID, audit_id=AUDIT_ID)

    assert exc_info.value.error_type == "AGGREGATE_SET_TOO_LARGE"
    assert len(client.get_item_calls) == 1, "exactly one hold read before byte-size rejection"
    assert client.transact_calls == [], "zero writes on byte-size rejection"


def test_transaction_byte_measurement_is_deterministic():
    a = repository_module._measure_transaction_bytes(
        [{"Put": {"Item": {"a": {"S": "1"}}}}, {"ConditionCheck": {"Key": {"b": {"S": "2"}}}}]
    )
    b = repository_module._measure_transaction_bytes(
        [{"Put": {"Item": {"a": {"S": "1"}}}}, {"ConditionCheck": {"Key": {"b": {"S": "2"}}}}]
    )
    assert a == b


def test_transaction_byte_measurement_includes_condition_check_contribution():
    put_only = repository_module._measure_transaction_bytes(
        [{"Put": {"Item": {"a": {"S": "1"}}}}]
    )
    with_condition_check = repository_module._measure_transaction_bytes(
        [
            {"Put": {"Item": {"a": {"S": "1"}}}},
            {"ConditionCheck": {"Key": {"b": {"S": "2"}}}},
        ]
    )
    assert with_condition_check > put_only
