"""Unit tests for apps.backend.handlers.evidence_disposal_recorder_handler
(A1.4a Increment 4 -- closing the QA-identified TC-H2-H6 gap).

Covers the QA plan (docs/qa/a1_4a_disposal_recorder_test_plan.md) Section
3.8 Area (h) -- Batch/Retry/Bisection Contract, TC-H2 through TC-H6
(TC-H1/TC-H7 are static infra-configuration checks and already live in
test_infra_configuration.py; they are not duplicated here). Also closes
Section 2 item 13's own acceptance-criteria mapping ("Partial-batch/
bisection contract -- 5 sub-assertions (a)-(e) ... plus item 13's own
trailing 'And, unchanged:' sentence on same-batch redelivery of
already-successful records").

`docs/qa/a1_4a_disposal_recorder_test_report.md` Section 4.1 found these
five test cases did not exist anywhere in the repository -- a BLOCKING gap,
since item 13 is one of the corrected, load-bearing behavioral contracts of
this subphase (TD Section 22.10's corrected interaction between
`ReportBatchItemFailures` and `BisectBatchOnFunctionError`).

These are simulated-event-source-mapping-behavior unit tests, per the QA
plan's own Validation Method for item 13 -- they exercise
`EvidenceDisposalRecorderHandler.handle()` (the public entrypoint dispatching
to `_handle_dynamodb_streams_batch`) directly against multi-record batches,
and simulate what a real DynamoDB Streams event-source mapping would deliver
across successive invocations (redelivery from the checkpoint boundary
onward) by constructing and invoking a second batch by hand -- this module
does not attempt to fake AWS's own ESM runtime, only the handler's
observable contract with it (its returned `batchItemFailures` shape) and the
documented `ReportBatchItemFailures` semantics that shape exists to satisfy.
"""

from __future__ import annotations

from typing import Any

from apps.backend.handlers.evidence_disposal_recorder_handler import (
    EvidenceDisposalRecorderHandler,
)
from release_confidence_platform.evidence_retention.constants import (
    DISPOSAL_RECORD_RECORD_TYPE,
)
from release_confidence_platform.evidence_retention.disposal_repository import (
    ConditionalWriteError,
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


def _good_record(*, sequence_number: str, event_id: str) -> dict[str, Any]:
    """A well-formed DynamoDB Streams REMOVE record that deterministically
    resolves to DISPOSITION_RECORDABLE on first delivery (or
    DISPOSITION_CONFIRMED_DUPLICATE if redelivered against a repository that
    already holds it) -- never one of this handler's retry-worthy
    dispositions.
    """
    return {
        "eventID": event_id,
        "eventName": "REMOVE",
        "eventSourceARN": _EXPECTED_STREAM_ARN,
        "userIdentity": {"type": "Service", "principalId": "dynamodb.amazonaws.com"},
        "dynamodb": {
            "ApproximateCreationDateTime": 1735689600.0,
            "SequenceNumber": sequence_number,
            "OldImage": encode_item(_old_image()),
        },
    }


def _poison_record(*, sequence_number: str, event_id: str) -> dict[str, Any]:
    """A DynamoDB Streams REMOVE record missing `OldImage` -- deterministically
    resolves to DISPOSITION_MALFORMED_TARGET_PROVENANCE (element 4 of
    `validate_dynamodb_provenance`), one of this handler's two retry-worthy
    dispositions (`_RETRY_DISPOSITIONS`), on every invocation, with no
    dependency on repository state. This is the "poison record" fixture
    convention used throughout this module -- a record that fails
    identically and deterministically no matter how many times it is
    redelivered, so tests can isolate the handler's batch-reporting/
    retry-boundary behavior from duplicate-conflict-verification mechanics
    (covered separately, and exercised on the "good" record path below).
    """
    return {
        "eventID": event_id,
        "eventName": "REMOVE",
        "eventSourceARN": _EXPECTED_STREAM_ARN,
        "userIdentity": {"type": "Service", "principalId": "dynamodb.amazonaws.com"},
        "dynamodb": {
            "ApproximateCreationDateTime": 1735689600.0,
            "SequenceNumber": sequence_number,
            # OldImage deliberately omitted.
        },
    }


class _InMemoryDisposalRepository:
    """A stateful `DisposalRepository` double that behaves like the real
    conditional-write store across multiple handler invocations.

    Unlike `test_disposal_recorder.py`'s `_FakeRepository` (which is
    pre-seeded with a single canned conflict/existing-item outcome, suitable
    for single-call duplicate-verification tests), this double actually
    retains state across successive `handle()` calls -- the first
    `put_disposal_record` for a given (client_id, audit_id, disposal_id)
    succeeds and is retained; any subsequent `put_disposal_record` for the
    identical key raises `ConditionalWriteError`, exactly mirroring
    DynamoDB's own `attribute_not_exists(PK) AND attribute_not_exists(SK)`
    condition-expression semantics (`DisposalRepository._put_once`). This is
    what makes TC-H4/TC-H6's "next invocation redelivers an already-recorded
    record" scenario a genuine exercise of `verify_duplicate_or_collision`'s
    real comparison surface, not a pre-canned double.
    """

    def __init__(self) -> None:
        self._items: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.put_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []
        self.successful_put_count = 0

    @staticmethod
    def _key(client_id: str, audit_id: str, disposal_id: str) -> tuple[str, str, str]:
        return (client_id, audit_id, disposal_id)

    def put_disposal_record(self, **kwargs: Any) -> None:
        self.put_calls.append(kwargs)
        key = self._key(kwargs["client_id"], kwargs["audit_id"], kwargs["disposal_id"])
        if key in self._items:
            raise ConditionalWriteError()
        item = {
            "PK": f"CLIENT#{kwargs['client_id']}",
            "SK": f"AUDIT#{kwargs['audit_id']}#DISPOSAL#{kwargs['disposal_id']}",
            "record_type": DISPOSAL_RECORD_RECORD_TYPE,
            **kwargs,
        }
        self._items[key] = item
        self.successful_put_count += 1

    def get_disposal_record(
        self,
        client_id: str,
        audit_id: str,
        disposal_id: str,
        *,
        consistent_read: bool = False,
    ) -> dict[str, Any] | None:
        self.get_calls.append(
            {
                "client_id": client_id,
                "audit_id": audit_id,
                "disposal_id": disposal_id,
                "consistent_read": consistent_read,
            }
        )
        return self._items.get(self._key(client_id, audit_id, disposal_id))


def _make_handler(repository: _InMemoryDisposalRepository) -> EvidenceDisposalRecorderHandler:
    return EvidenceDisposalRecorderHandler(
        repository=repository,
        expected_stream_arn=_EXPECTED_STREAM_ARN,
        expected_account_id=_EXPECTED_ACCOUNT_ID,
        expected_bucket_name=_EXPECTED_BUCKET,
    )


# ---------------------------------------------------------------------------
# Area (h) -- Batch/Retry/Bisection Contract (TC-H2-H6)
# QA plan Section 3.8; Section 2 item 13.
# ---------------------------------------------------------------------------


def test_tc_h2_mixed_batch_reports_failing_sequence_numbers_as_checkpoint_boundary() -> None:
    """TC-H2: a batch mixing succeeding and failing records -- assert the
    handler's returned `batchItemFailures` correctly identifies the failing
    record(s)' own sequence numbers, and that this is what becomes the
    checkpoint/retry boundary per AWS's own `ReportBatchItemFailures`
    contract: the LOWEST sequence number among all returned failures is what
    the real ESM uses as the checkpoint boundary. With more than one failing
    record present, the returned list's minimum must be the true earliest
    failing sequence number -- not a single-poison-record simplification.
    """
    repo = _InMemoryDisposalRepository()
    handler = _make_handler(repo)
    records = [
        _good_record(sequence_number="100", event_id="evt-100"),
        _poison_record(sequence_number="200", event_id="evt-200"),
        _good_record(sequence_number="300", event_id="evt-300"),
        # Earlier than "200" but later than "100" -- proves the checkpoint
        # boundary is genuinely computed as a minimum, not just "the first
        # failing record encountered in iteration order".
        _poison_record(sequence_number="150", event_id="evt-150"),
    ]

    response = handler.handle({"Records": records})

    failed_ids = {item["itemIdentifier"] for item in response["batchItemFailures"]}
    assert failed_ids == {"200", "150"}
    # The good records were never reported as failures.
    assert "100" not in failed_ids
    assert "300" not in failed_ids

    # Simulate the real ESM's own checkpoint-boundary computation directly
    # against the handler's returned list (AWS's documented
    # ReportBatchItemFailures contract: lowest returned sequence number is
    # the checkpoint boundary).
    checkpoint_boundary = min(failed_ids, key=int)
    assert checkpoint_boundary == "150"


def test_tc_h3_multi_poison_batch_reports_every_failing_record_identity() -> None:
    """TC-H3: a MULTI-poison-record batch (not a single isolated bad record)
    -- assert the handler correctly identifies ALL genuinely-failing
    records' own sequence numbers/identities in its response, not merely a
    count. Also constructs the simulated "next invocation" payload the real
    ESM would redeliver (every record at-or-after the checkpoint boundary)
    and asserts its actual record-identity content matches exactly -- the
    boundary-onward records, not a simplified single-poison-record model
    (QA plan Section 2 item 13(b)/(c)).
    """
    repo = _InMemoryDisposalRepository()
    handler = _make_handler(repo)
    records = [
        _good_record(sequence_number="10", event_id="evt-10"),
        _poison_record(sequence_number="20", event_id="evt-20"),
        _good_record(sequence_number="30", event_id="evt-30"),
        _poison_record(sequence_number="40", event_id="evt-40"),
        _poison_record(sequence_number="50", event_id="evt-50"),
        _good_record(sequence_number="60", event_id="evt-60"),
    ]

    response = handler.handle({"Records": records})

    failed_ids = [item["itemIdentifier"] for item in response["batchItemFailures"]]
    # Every failing record's own identity is present -- a set-equality
    # assertion, plus an explicit length check, so a hypothetical
    # implementation that folded distinct failures into a single reported
    # identifier (or a count) would fail this assertion, not merely produce
    # a differently-shaped but still-passing result.
    assert set(failed_ids) == {"20", "40", "50"}
    assert len(failed_ids) == 3

    checkpoint_boundary = min(failed_ids, key=int)
    assert checkpoint_boundary == "20"

    # The real ESM redelivery behavior this test simulates: the next
    # invocation's batch is every record whose SequenceNumber is >= the
    # checkpoint boundary -- actual record content/identities, not a
    # simplified single-record model.
    next_batch = [
        record
        for record in records
        if int(record["dynamodb"]["SequenceNumber"]) >= int(checkpoint_boundary)
    ]
    next_batch_event_ids = [record["eventID"] for record in next_batch]
    assert next_batch_event_ids == ["evt-20", "evt-30", "evt-40", "evt-50", "evt-60"]


def test_tc_h4_next_invocation_resolves_success_via_duplicate_and_repeats_failure() -> None:
    """TC-H4: same-shard blocking, both resolution paths. Simulate a first
    invocation's batch, then a second invocation representing what the ESM
    would redeliver from the checkpoint boundary onward (same-shard
    records) -- assert (a) the record that already succeeded before the
    retry resolves via duplicate-verification (confirmed idempotent
    duplicate, no re-write, no error) when redelivered in this second
    batch, and (b) a record that fails a SECOND time is again correctly
    reported in `batchItemFailures`. Both resolution paths --
    checkpoint-advance (success) and continued-failure (still blocked) --
    proven from the same-shard record's perspective.
    """
    repo = _InMemoryDisposalRepository()
    handler = _make_handler(repo)

    first_batch = [
        _poison_record(sequence_number="10", event_id="evt-10"),
        _good_record(sequence_number="20", event_id="evt-20"),
    ]
    first_response = handler.handle({"Records": first_batch})

    assert [item["itemIdentifier"] for item in first_response["batchItemFailures"]] == ["10"]
    assert repo.successful_put_count == 1
    first_put_calls = len(repo.put_calls)

    # Second invocation: the ESM redelivers everything from the checkpoint
    # boundary ("10") onward on this same shard -- the still-failing poison
    # record plus the already-successful good record.
    second_batch = [
        _poison_record(sequence_number="10", event_id="evt-10"),
        _good_record(sequence_number="20", event_id="evt-20"),
    ]
    second_response = handler.handle({"Records": second_batch})

    # (a) the already-successful record resolves via duplicate-verification
    # -- confirmed idempotent duplicate: exactly one *attempted* re-put
    # (mirroring DynamoDB's own conditional-put behavior of always
    # attempting, then failing the condition) but no second successful
    # write, and the duplicate-verification read-back genuinely happened.
    assert repo.successful_put_count == 1
    assert len(repo.put_calls) == first_put_calls + 1
    assert repo.get_calls[-1]["consistent_read"] is True
    assert repo.get_calls[-1]["client_id"] == _CLIENT_ID

    # (b) the poison record fails a second time and is again reported.
    assert [item["itemIdentifier"] for item in second_response["batchItemFailures"]] == ["10"]


def test_tc_h5_per_record_failure_reporting_is_independent_of_unrelated_records() -> None:
    """TC-H5: cross-shard independence.

    What this test CAN prove at the unit level: DynamoDB Streams' actual
    per-shard delivery model means a single Lambda invocation's `Records`
    list is always sourced from ONE shard -- it is the event-source mapping
    itself (via `ParallelizationFactor`), not this handler, that fans
    separate shards out to separate, independently-invoked Lambda
    executions. No DynamoDB Streams record-level field (`eventID`,
    `eventSourceARN`, `dynamodb.SequenceNumber`) names which shard a given
    record within one `Records` list came from -- shard identity is not
    part of the per-record payload shape at all. This means a single unit
    test cannot construct a fixture that is genuinely "two different
    shards' records delivered in one batch" the way TC-H4's same-shard
    fixture genuinely represents same-shard redelivery across two
    invocations.

    What IS testable, and what this test asserts instead: per-record
    independence of the failure-reporting loop inside
    `_handle_dynamodb_streams_batch` -- an unrelated, independently
    succeeding record's outcome is never altered, dropped, or folded into a
    failing record's `batchItemFailures` entry merely because it shares a
    batch with that failing record. This is a necessary (but not
    sufficient) unit-level precondition for true cross-shard independence:
    if per-record handling were NOT independent within one batch,
    cross-shard independence -- which additionally depends on the ESM's own
    separate-invocation-per-shard runtime behavior, something no unit test
    can exercise -- could not hold either. The genuinely cross-shard claim
    (that a stalled shard's retry exhaustion never blocks a different,
    concurrently-invoked shard's own checkpoint progress) is real AWS
    Lambda/DynamoDB Streams runtime behavior, out of reach for this Gate 6
    offline/unit test; closing it fully would require a real multi-shard
    staging behavioral proof (Gate 7), consistent with this project's own
    discipline against overclaiming behavioral proof from unit-level tests.
    """
    repo = _InMemoryDisposalRepository()
    handler = _make_handler(repo)
    records = [
        _poison_record(sequence_number="900", event_id="evt-unrelated-poison"),
        _good_record(sequence_number="10", event_id="evt-unrelated-independent-success"),
    ]

    response = handler.handle({"Records": records})

    failed_ids = {item["itemIdentifier"] for item in response["batchItemFailures"]}
    assert failed_ids == {"900"}
    # The unrelated, independently-succeeding record was actually written --
    # its outcome was not suppressed, altered, or bundled into the failing
    # record's reported identity merely by batch co-membership.
    assert repo.successful_put_count == 1
    assert repo.put_calls[0]["source_event_id"] == "evt-unrelated-independent-success"


def test_tc_h6_later_already_successful_record_resolves_despite_earlier_new_failure() -> None:
    """TC-H6: same-batch/next-invocation redelivery of an already-successful
    record. A batch where a LATER record (by sequence number) was already
    successfully recorded in a PRIOR invocation, and is redelivered in a
    subsequent batch alongside an EARLIER record that's newly failing --
    assert the already-successful later record resolves via
    duplicate-verification (category e, confirmed idempotent duplicate),
    never a duplicate write or error, even though it is "ahead of" the
    currently-failing record in the batch (QA plan Section 2 item 13's own
    trailing "And, unchanged:" sentence on same-batch redelivery of
    already-successful records).
    """
    repo = _InMemoryDisposalRepository()
    handler = _make_handler(repo)

    # Prior invocation: only the later-sequence-number record was present
    # and succeeded.
    prior_batch = [_good_record(sequence_number="500", event_id="evt-500")]
    prior_response = handler.handle({"Records": prior_batch})
    assert prior_response["batchItemFailures"] == []
    assert repo.successful_put_count == 1

    # Subsequent batch: an earlier-sequence-number record that is newly
    # failing, redelivered alongside the already-successful later record.
    subsequent_batch = [
        _poison_record(sequence_number="300", event_id="evt-300"),
        _good_record(sequence_number="500", event_id="evt-500"),
    ]
    response = handler.handle({"Records": subsequent_batch})

    assert [item["itemIdentifier"] for item in response["batchItemFailures"]] == ["300"]
    # The later, already-successful record resolves via duplicate-
    # verification -- no second successful write, and the consistent
    # read-back genuinely occurred.
    assert repo.successful_put_count == 1
    assert repo.get_calls[-1]["consistent_read"] is True
    assert repo.get_calls[-1]["client_id"] == _CLIENT_ID
