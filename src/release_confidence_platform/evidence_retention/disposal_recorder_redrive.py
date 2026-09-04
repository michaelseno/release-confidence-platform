"""`rcp retention disposal-recorder redrive` command logic (A1.4a Increment 2).

ADR Decision 13 (`docs/architecture/adr_evidence_retention_disposal_enforcement.md`,
Non-Negotiable Invariant 45/51); Technical Design Section 22.9.3 (redrive
entrypoint contract) / 22.9.5 (deployment-to-CLI identity configuration
contract this module's six runtime checks validate against).

Scope, precisely: this module owns (a) the construction-time recovery-bucket
guarantee (the bucket name passed to `GetObject` is always resolved from
`StageConfig.disposal_recovery_bucket_name` -- this module's own
`redrive_disposal_recorder()` function signature has no `bucket` parameter
at all, by construction, so no CLI argument or caller-suppliable value can
ever reach the `GetObject` call's `Bucket` parameter); (b) the six numbered
runtime envelope/provenance checks (Technical Design Section 22.9.3), all
required, none optional, evaluated in order, any failure rejecting fail-
closed before shared per-record processing is ever invoked; and (c)
invocation of Increment 1's shared `disposal_recorder.py` per-record
processing function for each recovered record once all six checks pass --
never a parallel, reimplemented processing path.

This module does not parse CLI arguments and does not construct AWS
clients/StageConfig itself -- `evidence_retention/commands.py` owns the
argparse parser/dispatch shape (mirroring `build_retention_hold_parser`),
and `operator_cli/main.py` owns `AwsClientFactory`/`StageConfigLoader`
construction and the `validate_disposal_recorder_config()` call that must
happen before either (Technical Design Section 22.9.5's "Ordering"
paragraph; TC-G5/TC-G5-pos).

Credential model (ADR Non-Negotiable Invariant 47; Technical Design Section
22.9.3's "Reading the recovery object" paragraph): the `s3_client` this
module's function receives is always constructed from the operator's own
resolved `AwsClientFactory` credentials by the caller (`operator_cli/main.py`)
-- never from `EvidenceDisposalRecorderLambdaRole`, and never a second,
dedicated IAM role this design does not provision. This module never
constructs its own boto3 client and never imports `AwsClientFactory`.

Post-redrive artifact retention (Technical Design Section 22.9.3): the
recovery object is never deleted on success -- this module never calls
`s3_client.delete_object` anywhere, by construction (TC-G4). The object is
left in place for the recovery bucket's own purpose-limited Lifecycle rule
to eventually dispose of, regardless of redrive outcome.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.config.stage_config import StageConfig
from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.evidence_retention import disposal_recorder as _disposal_recorder
from release_confidence_platform.evidence_retention.disposal_repository import DisposalRepository

# The documented native `OnFailure`-destination key convention (Technical
# Design Section 22.9.3, check 1): `aws/lambda/{event-source-mapping-uuid}/...`.
# Only the fixed prefix through the UUID segment is asserted -- the exact
# remaining path structure (date/time components AWS appends) is flagged in
# the Technical Design as a lower-risk detail pending staging-time
# confirmation, not depended on here.
_RECOVERY_OBJECT_KEY_PREFIX_TEMPLATE = "aws/lambda/{uuid}/"

# The native `OnFailure`-destination invocation record's own top-level
# `version` field (Technical Design Section 22.9.3, check 3) -- a
# structurally distinct field from the S3 EventBridge "Object Deleted"
# envelope's `detail["event-version"]`, never to be confused with it.
_SUPPORTED_REDRIVE_ENVELOPE_VERSIONS: frozenset[str] = frozenset({"1.0"})

# Dispositions that keep this redrive invocation's overall exit code non-zero
# (Technical Design Section 22.9.3's "Output contract"): "success (0)
# requires every record in the batch to have resolved to recordable,
# valid-but-irrelevant, or confirmed-duplicate" -- malformed-target-
# provenance, unknown/incompatible, and disposal_id-collision/integrity-
# failure dispositions all keep the overall result non-zero.
_FAILING_DISPOSITIONS: frozenset[str] = frozenset(
    {
        _disposal_recorder.DISPOSITION_MALFORMED_TARGET_PROVENANCE,
        _disposal_recorder.DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE,
        _disposal_recorder.DISPOSITION_INTEGRITY_FAILURE,
    }
)

# Distinct, named outcome values for DisposalRedriveResult.outcome.
REDRIVE_OUTCOME_REJECTED = "envelope_validation_rejected"
REDRIVE_OUTCOME_PROCESSED = "processed"


@dataclass(frozen=True)
class DisposalRedriveRecordOutcome:
    """One reprocessed record's disposition, for operator-facing correlation
    (Technical Design Section 22.9.3's "Output contract": "per record
    processed: disposition reached... and a per-record identifier for
    correlation").
    """

    record_identifier: str
    disposition: str
    reason: str


@dataclass(frozen=True)
class DisposalRedriveResult:
    """Structured result of one `rcp retention disposal-recorder redrive`
    invocation (Technical Design Section 22.9.3's "Output contract",
    mirroring `HoldOperationResult`'s existing sanitized text/JSON rendering
    convention, Technical Design Section 21.9).

    `outcome` is exactly one of REDRIVE_OUTCOME_REJECTED (the construction-
    time bucket-name guarantee failed at the AWS layer -- i.e. `GetObject`
    itself failed -- or any of the six numbered runtime checks failed;
    shared per-record processing was never invoked) or
    REDRIVE_OUTCOME_PROCESSED (all six checks passed and shared per-record
    processing ran for every record in the recovered batch).
    `rejection_reason` is populated only when `outcome ==
    REDRIVE_OUTCOME_REJECTED` -- a short, named reason code, never a raw AWS
    error body, stack trace, or the object's own unvalidated content
    (Technical Design Section 22.9.3's sanitization requirement).
    `record_outcomes` is populated only when `outcome ==
    REDRIVE_OUTCOME_PROCESSED`.

    `exit_code` is 0 only when `outcome == REDRIVE_OUTCOME_PROCESSED` and
    every record resolved to a recordable, valid-but-irrelevant, or
    confirmed-duplicate disposition; 1 otherwise (rejection, or any record
    resolving to malformed-target-provenance, unknown/incompatible, or
    integrity-failure) -- partial success is reported explicitly via
    `success_count`/`failure_count`/`record_outcomes`, never collapsed into
    an undifferentiated overall failure.
    """

    recovery_object_key: str
    outcome: str
    rejection_reason: str | None
    record_outcomes: tuple[DisposalRedriveRecordOutcome, ...]
    record_count: int
    success_count: int
    failure_count: int
    exit_code: int


def _rejected(recovery_object_key: str, reason: str) -> DisposalRedriveResult:
    return DisposalRedriveResult(
        recovery_object_key=recovery_object_key,
        outcome=REDRIVE_OUTCOME_REJECTED,
        rejection_reason=reason,
        record_outcomes=(),
        record_count=0,
        success_count=0,
        failure_count=0,
        exit_code=1,
    )


def _looks_like_dynamodb_streams_payload(payload: Any) -> bool:
    """Check 5 (Technical Design Section 22.9.3): `payload` exists and
    parses as a genuine DynamoDB Streams event shape -- not arbitrary JSON
    that happens to be valid. Fails closed by construction on any shape not
    recognized, mirroring `disposal_recorder.py`'s own parser discipline
    (Technical Design Section 22.12). An empty or missing `payload`/`Records`
    is rejected here, never silently treated as zero records.
    """
    if not isinstance(payload, dict):
        return False
    records = payload.get("Records")
    if not isinstance(records, list) or not records:
        return False
    for record in records:
        if not isinstance(record, dict):
            return False
        if "eventSourceARN" not in record or "eventName" not in record or "eventID" not in record:
            return False
    return True


def redrive_disposal_recorder(
    *,
    recovery_object_key: str,
    stage_config: StageConfig,
    s3_client: Any,
    repository: DisposalRepository,
    now_fn: Callable[[], str] = utc_now_iso,
) -> DisposalRedriveResult:
    """Read, validate, and (on success) reprocess one recovery-bucket object.

    Construction-time guarantee: the bucket name is always
    `stage_config.disposal_recovery_bucket_name` -- there is no `bucket`
    parameter on this function's own signature, so no caller-suppliable
    value can ever reach `GetObject`'s `Bucket` argument. The actual
    enforcement boundary against a misconfigured `disposal_recovery_bucket_name`
    is the operator's own narrowly-scoped IAM (Technical Design Section
    22.9.3/22.11) -- a misconfiguration fails closed with `AccessDenied` at
    the AWS layer, caught below and surfaced as a rejected
    `DisposalRedriveResult`, never a crash or silent fallback to another
    bucket (TC-I6(b)).

    Six numbered runtime checks (Technical Design Section 22.9.3), all
    required, evaluated in order, any failure rejecting fail-closed before
    shared per-record processing is ever invoked (TC-G9):
      1. Recovery object key matches `aws/lambda/{esm-uuid}/...`, UUID
         matched against `stage_config.disposal_recorder_event_source_mapping_uuid`.
      2. Object body's `requestContext.functionArn` matches
         `stage_config.disposal_recorder_function_arn`.
      3. Object's own envelope `version` field is a supported value.
      4. Object's `DDBStreamBatchInfo.streamArn` matches
         `stage_config.metadata_table_stream_arn`.
      5. Object's `payload` field exists and parses as a genuine DynamoDB
         Streams event shape.
      6. Every recovered record's own `eventSourceARN` within `payload`
         matches the same expected stream ARN as check 4.
    """
    try:
        response = s3_client.get_object(
            Bucket=stage_config.disposal_recovery_bucket_name,
            Key=recovery_object_key,
        )
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "ClientError")
        return _rejected(recovery_object_key, f"recovery_object_read_failed:{error_code}")

    body_stream = response.get("Body") if isinstance(response, dict) else None
    raw_body = (
        body_stream.read() if body_stream is not None and hasattr(body_stream, "read") else b""
    )
    try:
        body = json.loads(raw_body)
    except (TypeError, ValueError):
        return _rejected(recovery_object_key, "recovery_object_body_not_valid_json")

    if not isinstance(body, dict):
        return _rejected(recovery_object_key, "recovery_object_body_not_json_object")

    # Check 1: object key's own esm-uuid segment.
    expected_prefix = _RECOVERY_OBJECT_KEY_PREFIX_TEMPLATE.format(
        uuid=stage_config.disposal_recorder_event_source_mapping_uuid
    )
    if not recovery_object_key.startswith(expected_prefix):
        return _rejected(recovery_object_key, "recovery_object_key_esm_uuid_mismatch")

    # Check 2: requestContext.functionArn.
    request_context = body.get("requestContext")
    function_arn = request_context.get("functionArn") if isinstance(request_context, dict) else None
    if function_arn != stage_config.disposal_recorder_function_arn:
        return _rejected(recovery_object_key, "function_arn_mismatch")

    # Check 3: envelope version.
    if body.get("version") not in _SUPPORTED_REDRIVE_ENVELOPE_VERSIONS:
        return _rejected(recovery_object_key, "unsupported_envelope_version")

    # Check 4: DDBStreamBatchInfo.streamArn.
    batch_info = body.get("DDBStreamBatchInfo")
    expected_stream_arn = stage_config.metadata_table_stream_arn
    stream_arn = batch_info.get("streamArn") if isinstance(batch_info, dict) else None
    if stream_arn != expected_stream_arn:
        return _rejected(recovery_object_key, "stream_arn_mismatch")

    # Check 5: payload exists and parses as a genuine DynamoDB Streams shape.
    payload = body.get("payload")
    if not _looks_like_dynamodb_streams_payload(payload):
        return _rejected(recovery_object_key, "payload_missing_or_malformed_dynamodb_streams_shape")
    records = payload["Records"]

    # Check 6: every record's own eventSourceARN matches the same expected
    # stream ARN as check 4 -- a distinct, per-record check, never redundant
    # with check 4's once-per-object check.
    if any(record.get("eventSourceARN") != expected_stream_arn for record in records):
        return _rejected(recovery_object_key, "per_record_event_source_arn_mismatch")

    # All six checks passed -- invoke Increment 1's shared per-record
    # processing for every recovered record. Duplicate-conflict verification
    # (disposal_recorder.py's own §22.3 mechanism, invoked transitively by
    # process_dynamodb_stream_record) resolves any already-recorded record
    # as a confirmed duplicate, never a re-write (TC-G3).
    outcomes: list[DisposalRedriveRecordOutcome] = []
    for index, record in enumerate(records):
        disposition_outcome = _disposal_recorder.process_dynamodb_stream_record(
            record,
            expected_stream_arn=expected_stream_arn,
            repository=repository,
            now_fn=now_fn,
        )
        record_identifier = record.get("eventID") or f"record_{index}"
        outcomes.append(
            DisposalRedriveRecordOutcome(
                record_identifier=record_identifier,
                disposition=disposition_outcome.disposition,
                reason=disposition_outcome.reason,
            )
        )

    failure_count = sum(1 for outcome in outcomes if outcome.disposition in _FAILING_DISPOSITIONS)
    success_count = len(outcomes) - failure_count
    return DisposalRedriveResult(
        recovery_object_key=recovery_object_key,
        outcome=REDRIVE_OUTCOME_PROCESSED,
        rejection_reason=None,
        record_outcomes=tuple(outcomes),
        record_count=len(outcomes),
        success_count=success_count,
        failure_count=failure_count,
        exit_code=1 if failure_count else 0,
    )


__all__ = [
    "REDRIVE_OUTCOME_REJECTED",
    "REDRIVE_OUTCOME_PROCESSED",
    "DisposalRedriveRecordOutcome",
    "DisposalRedriveResult",
    "redrive_disposal_recorder",
]
