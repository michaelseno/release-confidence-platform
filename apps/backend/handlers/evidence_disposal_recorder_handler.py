"""Thin Lambda entrypoint for `evidenceDisposalRecorder` (A1.4a Increment 2).

ADR Decision 13 (`docs/architecture/adr_evidence_retention_disposal_enforcement.md`);
Technical Design Section 22 in full
(`docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`).

This module is the thin entrypoint only -- all identity computation,
provenance validation, disposition classification, and the conditional
write live in Increment 1's `evidence_retention/disposal_recorder.py`
shared module, which this handler calls per record/event and never
reimplements (Technical Design Section 22.9.3's "Shared processing logic,
not a parallel code path" paragraph -- the redrive command,
`disposal_recorder_redrive.py`, calls the identical shared functions this
handler does).

This single Lambda function is invoked from two structurally different AWS
event sources this design defines (Technical Design Section 22.1/22.4/22.5):
  - a DynamoDB Streams event-source mapping delivering a **batch** shaped
    `{"Records": [...]}`, each record a raw DynamoDB Streams record; and
  - an S3 EventBridge "Object Deleted" notification rule delivering **one**
    event at a time, shaped `{"source": "aws.s3", "detail-type": ..., ...}`.
`handle()` dispatches on the presence of a top-level `Records` list to tell
these two shapes apart -- an EventBridge event never carries a top-level
`Records` key.

Retry/failure-destination routing (Technical Design Section 22.7's six-
category disposition taxonomy; Section 22.8's five separate failure
planes): only `DISPOSITION_MALFORMED_TARGET_PROVENANCE` ("routed for
retry/recovery, never silently dropped as valid-but-irrelevant" -- Section
22.13 item 8) and `DISPOSITION_INTEGRITY_FAILURE` (a disposal_id collision
with unequal immutable content -- Section 22.3's "never silently accepted"
requirement) are treated as retry-worthy by this handler. The other four
dispositions (recordable, valid-but-irrelevant, unknown/incompatible,
confirmed-duplicate) are terminal outcomes this handler does not retry --
in particular, `DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE` is not retried,
since retrying an event whose source identity does not match this
recorder's own configured stream/bucket can never resolve by retrying.

Assumption requiring confirmation (documented per this increment's
Assumption Policy -- does not change any disposition, identity computation,
or duplicate-verification mechanic Increment 1 already covers, but does
affect Lambda batch/async-invoke retry semantics, which is why it is
flagged explicitly rather than treated as self-evidently correct): the exact
retry-worthy disposition set above. Technical Design Section 22.13 item 8
only explicitly names malformed-target-provenance as retry-worthy;
inclusion of integrity-failure here is this implementation's own judgment
call, made so a disposal_id collision is not silently swallowed as a
successful invocation. Full TC-H* batch/retry-bisection coverage (Technical
Design Section 22.10/22.13 item 13) is out of this increment's own required
scope (Increment 2 covers Area (g) redrive/recovery and Area (i) IAM only,
per this increment's own task briefing) and remains a Increment 3 / future
QA closure item.

`ReportBatchItemFailures` response shape (DynamoDB Streams path only, per
Technical Design Section 22.10's `FunctionResponseTypes: [ReportBatchItemFailures]`
configuration expectation, itself Increment 3/infra scope): this handler
returns `{"batchItemFailures": [{"itemIdentifier": <SequenceNumber>}, ...]}`
per AWS's own documented contract for this response shape.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

from release_confidence_platform.core.logging import StructuredLogger
from release_confidence_platform.evidence_retention import disposal_recorder as _disposal_recorder
from release_confidence_platform.evidence_retention.disposal_repository import DisposalRepository

# ---------------------------------------------------------------------------
# Startup import validation -- fail fast on missing critical modules
# ---------------------------------------------------------------------------
try:
    from release_confidence_platform.evidence_retention import (
        disposal_recorder as _startup_check,  # noqa: F401, E501
    )
    from release_confidence_platform.storage import (
        dynamodb_codec as _startup_codec_check,  # noqa: F401
    )
except ImportError as _exc:  # pragma: no cover
    import logging as _logging

    _logging.critical("STARTUP_IMPORT_FAILURE: %s", _exc)
    raise


class DisposalRecorderHandlerError(RuntimeError):
    """Raised to surface a retry-worthy disposition (S3 EventBridge path
    only) to Lambda's own native async-invoke `OnFailure` destination --
    never caught or swallowed internally, and never raised for a terminal
    disposition (recordable/valid-but-irrelevant/unknown-incompatible/
    confirmed-duplicate)."""


# Dispositions treated as retry-worthy -- see module docstring's "Assumption
# requiring confirmation" note above.
_RETRY_DISPOSITIONS: frozenset[str] = frozenset(
    {
        _disposal_recorder.DISPOSITION_MALFORMED_TARGET_PROVENANCE,
        _disposal_recorder.DISPOSITION_INTEGRITY_FAILURE,
    }
)


class EvidenceDisposalRecorderHandler:
    def __init__(
        self,
        *,
        repository: DisposalRepository,
        expected_stream_arn: str,
        expected_account_id: str,
        expected_bucket_name: str,
        supported_major_version: int = 1,
        minimum_minor_version: int = 0,
        logger: StructuredLogger | None = None,
    ) -> None:
        self.repository = repository
        self.expected_stream_arn = expected_stream_arn
        self.expected_account_id = expected_account_id
        self.expected_bucket_name = expected_bucket_name
        self.supported_major_version = supported_major_version
        self.minimum_minor_version = minimum_minor_version
        self.logger = logger or StructuredLogger()

    def handle(self, event: dict[str, Any]) -> dict[str, Any]:
        if isinstance(event, dict) and isinstance(event.get("Records"), list):
            return self._handle_dynamodb_streams_batch(event)
        return self._handle_s3_eventbridge_event(event)

    def _handle_dynamodb_streams_batch(self, event: dict[str, Any]) -> dict[str, Any]:
        batch_item_failures: list[dict[str, str]] = []
        for record in event.get("Records", []):
            outcome = _disposal_recorder.process_dynamodb_stream_record(
                record,
                expected_stream_arn=self.expected_stream_arn,
                repository=self.repository,
            )
            self._log_disposition("evidenceDisposalRecorder_dynamodb_record", outcome)
            if outcome.disposition in _RETRY_DISPOSITIONS:
                sequence_number = (record.get("dynamodb") or {}).get("SequenceNumber")
                if sequence_number:
                    batch_item_failures.append({"itemIdentifier": sequence_number})
        return {"batchItemFailures": batch_item_failures}

    def _handle_s3_eventbridge_event(self, event: dict[str, Any]) -> dict[str, Any]:
        outcome = _disposal_recorder.process_s3_eventbridge_event(
            event,
            expected_account_id=self.expected_account_id,
            expected_bucket_name=self.expected_bucket_name,
            supported_major_version=self.supported_major_version,
            minimum_minor_version=self.minimum_minor_version,
            repository=self.repository,
        )
        self._log_disposition("evidenceDisposalRecorder_s3_event", outcome)
        if outcome.disposition in _RETRY_DISPOSITIONS:
            raise DisposalRecorderHandlerError(
                f"disposal-recorder S3 event failed with disposition={outcome.disposition!r}: "
                f"{outcome.reason}"
            )
        return {"disposition": outcome.disposition, "reason": outcome.reason}

    def _log_disposition(self, message: str, outcome: Any) -> None:
        self.logger.log(message, disposition=outcome.disposition, reason=outcome.reason)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:  # noqa: ARG001
    dynamodb_client = boto3.client("dynamodb")
    repository = DisposalRepository(os.environ["METADATA_TABLE"], dynamodb_client)
    return EvidenceDisposalRecorderHandler(
        repository=repository,
        expected_stream_arn=os.environ["METADATA_TABLE_STREAM_ARN"],
        expected_account_id=os.environ["AWS_ACCOUNT_ID"],
        expected_bucket_name=os.environ["RAW_RESULTS_BUCKET"],
    ).handle(event)
