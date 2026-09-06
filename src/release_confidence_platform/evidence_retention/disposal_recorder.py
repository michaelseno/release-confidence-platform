"""Shared disposal-recorder logic for `evidenceDisposalRecorder` (A1.4a).

ADR Decision 13 (`docs/architecture/adr_evidence_retention_disposal_enforcement.md`,
Non-Negotiable Invariants 38-51); Technical Design Section 22
(`docs/architecture/evidence_governance_workstream_a1_retention_enforcement_technical_design.md`).

This module is the **shared logic** both the live Lambda handler
(`apps/backend/handlers/evidence_disposal_recorder_handler.py`, Increment 2)
and the redrive command (`disposal_recorder_redrive.py`, Increment 2) call
per record/event -- it contains no Lambda entrypoint and no CLI wiring
itself (A1.4a Increment 1 scope only).

Provides, per the Increment 1 implementation plan:
  (a) deterministic `disposal_id` computation for both source paths
      (`compute_dynamodb_disposal_id` / `compute_s3_disposal_id`), Technical
      Design Section 22.2, ADR Invariant 38/49/50.
  (b) DynamoDB Streams provenance validation (`validate_dynamodb_provenance`),
      Technical Design Section 22.4, ADR Invariant 40.
  (c) S3 EventBridge envelope/provenance validation (`validate_s3_provenance`),
      Technical Design Section 22.5/22.5.1-22.5.3, ADR Invariant 41.
  (d) evidence-prefix restriction (`classify_s3_key_prefix`) and key parsing
      (`parse_s3_evidence_key`), kept structurally separate from identity-hash
      computation -- the identity hash always uses the raw, undecoded key;
      the parser may percent-decode. Technical Design Section 22.6/22.12,
      ADR Invariant 42/48/50.
  (e) the six-category event-disposition taxonomy (`DISPOSITION_*` constants),
      Technical Design Section 22.7, ADR Invariant 43.
  (f) duplicate-conflict verification (`verify_duplicate_or_collision`),
      Technical Design Section 22.3, ADR Invariant 39/49.
  (g) per-record/per-event processing orchestration
      (`process_dynamodb_stream_record` / `process_s3_eventbridge_event`)
      tying (a)-(f) together, Technical Design Section 22 in full.

`generate_disposal_id()` (`identity.py`) is NOT reused or extended by this
module -- per the implementation plan, `disposal_id` computation here is new,
dedicated logic, never an extension of that existing random-UUID generator
(ADR Decision 13's "Deterministic, versioned disposal identity" paragraph).

No custody-duration value is selected, read, or assumed anywhere in this
module -- `custody_period_days_applied` is always populated as `None` by the
orchestration functions below, consistent with this increment's required
implementation controls.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

from release_confidence_platform.core.time import utc_now_iso
from release_confidence_platform.evidence_retention.constants import (
    DISPOSAL_ID_PREFIX,
    DISPOSAL_MECHANISM_DYNAMODB_TTL,
    DISPOSAL_MECHANISM_S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION,
    DISPOSAL_RECORD_RECORD_TYPE,
    EVIDENCE_CLASSES,
    RETENTION_MARKER_KEY_PREFIX,
    S3_EVIDENCE_CLASS_PREFIXES,
)
from release_confidence_platform.evidence_retention.disposal_repository import (
    ConditionalWriteError,
    DisposalRepository,
)
from release_confidence_platform.evidence_retention.models import DisposalRecord

# ---------------------------------------------------------------------------
# (a) Deterministic, versioned disposal identity
# (ADR Decision 13, Invariants 38/49/50; Technical Design Section 22.2)
# ---------------------------------------------------------------------------

# Duplicated verbatim from models.py's own SOURCE_KIND_* constants rather
# than imported, to avoid a circular import (models.py has no dependency on
# this module; this module depends on models.py for DisposalRecord).
DISPOSAL_ID_SCHEME_V1 = "v1"
SOURCE_KIND_DYNAMODB_TTL_REMOVE = "dynamodb_ttl_remove"
SOURCE_KIND_S3_LIFECYCLE_DELETE = "s3_lifecycle_delete"


def _canonical_disposal_id(fields: dict[str, str]) -> str:
    """Compute `disp_v1_{sha256_hex}` over a canonical JSON serialization.

    `json.dumps(fields, sort_keys=True, separators=(",", ":"))` -- a fixed
    field list, fixed field order (via sort_keys), no floating-point fields,
    no field ever omitted or reordered within a given `disposal_id_scheme`
    (Technical Design Section 22.2's canonicalization contract; ADR
    Invariant 50). Never Lambda invocation time, wall-clock, event delivery
    order, or any other non-reproducible input.
    """
    hash_input = json.dumps(fields, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(hash_input).hexdigest()
    return f"{DISPOSAL_ID_PREFIX}{DISPOSAL_ID_SCHEME_V1}_{digest}"


def compute_dynamodb_disposal_id(stream_identity: str, event_id: str) -> str:
    """Compute `disposal_id` for the DynamoDB TTL path (Technical Design
    Section 22.2's "Canonicalization contract -- DynamoDB TTL path").

    `stream_identity` is the disposing record's own `eventSourceARN`;
    `event_id` is its own `eventID` -- both hashed as received, never
    normalized or re-derived.
    """
    fields = {
        "source_kind": SOURCE_KIND_DYNAMODB_TTL_REMOVE,
        "disposal_id_scheme": DISPOSAL_ID_SCHEME_V1,
        "stream_identity": stream_identity,
        "event_id": event_id,
    }
    return _canonical_disposal_id(fields)


def compute_s3_disposal_id(
    *, bucket: str, key: str, version_id: str, reason: str, deletion_type: str
) -> str:
    """Compute `disposal_id` for the S3 Lifecycle path (Technical Design
    Section 22.2's "Canonicalization contract -- S3 Lifecycle path").

    `key` is hashed EXACTLY as received from the EventBridge event -- no
    percent-decoding -- per ADR Invariant 50 (TC-C5 / TC-Q1c). The
    EventBridge envelope's own top-level `id` (delivery ID) is deliberately
    excluded from this hash input (TC-C4) -- a redelivery of the same
    underlying S3 permanent deletion could arrive under a different
    EventBridge `id`, which would defeat determinism if hashed.
    """
    fields = {
        "source_kind": SOURCE_KIND_S3_LIFECYCLE_DELETE,
        "disposal_id_scheme": DISPOSAL_ID_SCHEME_V1,
        "bucket": bucket,
        "key": key,
        "version_id": version_id,
        "reason": reason,
        "deletion_type": deletion_type,
    }
    return _canonical_disposal_id(fields)


# ---------------------------------------------------------------------------
# (e) Six-category event-disposition taxonomy
# (ADR Decision 13, Invariant 43; Technical Design Section 22.7)
# ---------------------------------------------------------------------------

DISPOSITION_RECORDABLE = "recordable_governed_disposal"
DISPOSITION_VALID_BUT_IRRELEVANT = "valid_but_irrelevant"
DISPOSITION_MALFORMED_TARGET_PROVENANCE = "malformed_target_provenance"
DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE = "unknown_incompatible_source"
DISPOSITION_CONFIRMED_DUPLICATE = "confirmed_idempotent_duplicate"
DISPOSITION_INTEGRITY_FAILURE = "disposal_id_collision_integrity_failure"

ALL_DISPOSITIONS: frozenset[str] = frozenset(
    {
        DISPOSITION_RECORDABLE,
        DISPOSITION_VALID_BUT_IRRELEVANT,
        DISPOSITION_MALFORMED_TARGET_PROVENANCE,
        DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE,
        DISPOSITION_CONFIRMED_DUPLICATE,
        DISPOSITION_INTEGRITY_FAILURE,
    }
)


# ---------------------------------------------------------------------------
# (b) DynamoDB Streams TTL provenance rule
# (ADR Decision 13, Invariant 40; Technical Design Section 22.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DynamoDbProvenanceResult:
    """Result of `validate_dynamodb_provenance`.

    `disposition` is always one of DISPOSITION_RECORDABLE (all five elements
    passed), DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE (element 1 failed),
    DISPOSITION_VALID_BUT_IRRELEVANT (element 2 or 3 failed), or
    DISPOSITION_MALFORMED_TARGET_PROVENANCE (element 4 or 5 failed, given
    1-3 already passed). `old_image` is populated (decoded, plain-Python
    dict) only when `disposition == DISPOSITION_RECORDABLE`.
    """

    disposition: str
    reason: str
    old_image: dict[str, Any] | None = None


def validate_dynamodb_provenance(
    record: dict[str, Any], *, expected_stream_arn: str
) -> DynamoDbProvenanceResult:
    """The corrected exact-match rule -- every element required, no partial
    match accepted (Technical Design Section 22.4, ADR Invariant 40).

    `record` is a single DynamoDB Streams record as delivered by the Lambda
    event-source mapping -- `eventSourceARN`/`eventName`/`eventID`/
    `userIdentity` are plain top-level fields; `record["dynamodb"]["OldImage"]`
    (when present) is the raw, low-level DynamoDB AttributeValue-wrapped
    shape (e.g. `{"S": "..."}`), decoded here via the same
    `storage/dynamodb_codec.py::decode_item` helper `DisposalRepository`
    itself uses for response decoding, for consistency with the rest of this
    codebase's DynamoDB-item handling.

    Element ordering, and its disposition consequence, is load-bearing
    (Technical Design Section 22.4's "Disposition on failure" table) --
    element 1 failing is category (d), never (b); elements 2/3 failing are
    category (b); elements 4/5 failing, given 1-3 already passed, are
    category (c).
    """
    # Local import to avoid importing boto3's TypeDeserializer machinery at
    # module load time for callers that never touch the DynamoDB path.
    from release_confidence_platform.storage.dynamodb_codec import decode_item

    # Element 1: expected stream identity.
    event_source_arn = record.get("eventSourceARN")
    if event_source_arn != expected_stream_arn:
        return DynamoDbProvenanceResult(
            DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE, "stream_identity_mismatch"
        )

    # Element 2: eventName == "REMOVE" exactly.
    if record.get("eventName") != "REMOVE":
        return DynamoDbProvenanceResult(DISPOSITION_VALID_BUT_IRRELEVANT, "not_a_remove_event")

    # Element 3: DynamoDB service-origin identity.
    user_identity = record.get("userIdentity") or {}
    if (
        user_identity.get("type") != "Service"
        or user_identity.get("principalId") != "dynamodb.amazonaws.com"
    ):
        return DynamoDbProvenanceResult(
            DISPOSITION_VALID_BUT_IRRELEVANT, "non_service_origin_user_identity"
        )

    # Element 4: OLD_IMAGE present.
    dynamodb_section = record.get("dynamodb") or {}
    raw_old_image = dynamodb_section.get("OldImage")
    if not raw_old_image:
        return DynamoDbProvenanceResult(
            DISPOSITION_MALFORMED_TARGET_PROVENANCE, "missing_old_image"
        )
    old_image = decode_item(raw_old_image)

    # Element 5: OLD_IMAGE represents a valid governed (Category 1/2) record
    # -- PK/SK present, evidence_class a member of the governed bounded set
    # (the same EVIDENCE_CLASSES set DisposalRecord.evidence_class itself is
    # validated against), and a usable creation-timestamp-equivalent field.
    #
    # Assumption requiring confirmation (Increment 1, narrowly scoped -- does
    # not affect the disposition taxonomy, identity computation, or
    # duplicate-verification mechanics this increment's QA coverage
    # emphasizes): Technical Design Section 22.4 element 5 requires "a usable
    # creation-timestamp-equivalent field" without naming one exact key
    # across the four structurally different governed record shapes
    # (Section 18.1 Category 1/2). This implementation looks for a
    # `created_at` field. If a future governed record type uses a
    # differently-named creation-timestamp field, this check would need to
    # be extended to recognize it.
    if not old_image.get("PK") or not old_image.get("SK"):
        return DynamoDbProvenanceResult(
            DISPOSITION_MALFORMED_TARGET_PROVENANCE, "old_image_missing_pk_or_sk"
        )
    if old_image.get("evidence_class") not in EVIDENCE_CLASSES:
        return DynamoDbProvenanceResult(
            DISPOSITION_MALFORMED_TARGET_PROVENANCE,
            "old_image_missing_or_invalid_evidence_class",
        )
    if not old_image.get("created_at"):
        return DynamoDbProvenanceResult(
            DISPOSITION_MALFORMED_TARGET_PROVENANCE,
            "old_image_missing_creation_timestamp",
        )

    return DynamoDbProvenanceResult(
        DISPOSITION_RECORDABLE, "valid_ttl_disposal", old_image=old_image
    )


# ---------------------------------------------------------------------------
# (c) S3 EventBridge envelope, provenance, and permanence rule
# (ADR Decision 13, Invariant 41; Technical Design Section 22.5/22.5.1-22.5.3)
# ---------------------------------------------------------------------------

_S3_ENVELOPE_SOURCE = "aws.s3"
_S3_ENVELOPE_DETAIL_TYPE = "Object Deleted"
_S3_LIFECYCLE_REASON = "Lifecycle Expiration"
_S3_LIFECYCLE_REQUESTER = "s3.amazonaws.com"
_S3_DELETION_TYPE_PERMANENT = "Permanently Deleted"
_S3_DELETION_TYPE_MARKER = "Delete Marker Created"


@dataclass(frozen=True)
class S3ProvenanceResult:
    """Result of `validate_s3_provenance`.

    `detail` is populated only when `disposition == DISPOSITION_RECORDABLE`,
    carrying exactly the raw content fields `compute_s3_disposal_id` and the
    orchestration layer need (`bucket`, `key`, `version_id`, `reason`,
    `deletion_type`) -- the raw, undecoded key, never percent-decoded here.
    """

    disposition: str
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)


def _is_compatible_event_version(
    version: Any, *, supported_major_version: int, minimum_minor_version: int
) -> bool:
    """Semver-style compatibility per Technical Design Section 22.5: MAJOR
    must match exactly; MINOR must be >= a configured minimum. A version
    string that does not parse as `{MAJOR}.{MINOR}` is incompatible.
    """
    if not isinstance(version, str):
        return False
    parts = version.split(".")
    if len(parts) != 2:
        return False
    major_str, minor_str = parts
    if not major_str.isdigit() or not minor_str.isdigit():
        return False
    return int(major_str) == supported_major_version and int(minor_str) >= minimum_minor_version


def validate_s3_provenance(
    event: dict[str, Any],
    *,
    expected_account_id: str,
    expected_bucket_name: str,
    supported_major_version: int,
    minimum_minor_version: int,
) -> S3ProvenanceResult:
    """Handler-side defense-in-depth validation -- Layer Two (Technical
    Design Section 22.5.3). Never trusts the EventBridge rule-level
    `EventPattern` alone; re-validates every element independently.

    Check ordering mirrors Technical Design Section 22.5's own field
    ordering (envelope -> account -> schema version -> bucket -> reason+
    requester corroboration -> version-id presence -> deletion-type).
    """
    source_ok = event.get("source") == _S3_ENVELOPE_SOURCE
    detail_type_ok = event.get("detail-type") == _S3_ENVELOPE_DETAIL_TYPE
    if not source_ok or not detail_type_ok:
        return S3ProvenanceResult(DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE, "envelope_mismatch")

    if event.get("account") != expected_account_id:
        return S3ProvenanceResult(DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE, "account_mismatch")

    detail = event.get("detail") or {}

    event_version = detail.get("event-version")
    if not _is_compatible_event_version(
        event_version,
        supported_major_version=supported_major_version,
        minimum_minor_version=minimum_minor_version,
    ):
        return S3ProvenanceResult(
            DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE, "unsupported_event_version"
        )

    bucket_name = (detail.get("bucket") or {}).get("name")
    if bucket_name != expected_bucket_name:
        return S3ProvenanceResult(DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE, "bucket_mismatch")

    reason = detail.get("reason")
    requester = detail.get("requester")
    if reason != _S3_LIFECYCLE_REASON or requester != _S3_LIFECYCLE_REQUESTER:
        return S3ProvenanceResult(
            DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE, "provenance_corroboration_failed"
        )

    object_detail = detail.get("object") or {}
    version_id = object_detail.get("version-id")
    if not version_id:
        return S3ProvenanceResult(DISPOSITION_MALFORMED_TARGET_PROVENANCE, "missing_version_id")

    deletion_type = detail.get("deletion-type")
    if deletion_type == _S3_DELETION_TYPE_MARKER:
        # Invariant 41 / Section 22.5.1: a delete marker leaves the addressed
        # object version physically present -- never recordable, and NEVER
        # produces a DisposalRecord under any condition.
        return S3ProvenanceResult(DISPOSITION_VALID_BUT_IRRELEVANT, "delete_marker_created")
    if deletion_type != _S3_DELETION_TYPE_PERMANENT:
        # Section 22.5.1: any deletion-type value other than the two known
        # literals fails closed as unknown/incompatible -- never silently
        # folded into valid-but-irrelevant.
        return S3ProvenanceResult(
            DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE, "unrecognized_deletion_type"
        )

    key = object_detail.get("key")
    return S3ProvenanceResult(
        DISPOSITION_RECORDABLE,
        "valid_permanent_deletion",
        detail={
            "bucket": bucket_name,
            "key": key,
            "version_id": version_id,
            "reason": reason,
            "deletion_type": deletion_type,
        },
    )


# ---------------------------------------------------------------------------
# (d) Evidence-prefix restriction and key parsing
# (ADR Decision 13, Invariant 42/48; Technical Design Section 22.6/22.12)
#
# Deliberately two structurally separate functions, per the implementation
# plan and Technical Design Section 22.12: `classify_s3_key_prefix` operates
# on the RAW key (prefix-dispatch, checked before any positional parsing is
# attempted); `parse_s3_evidence_key` percent-decodes and positionally
# extracts client_id/audit_id/evidence_class. Neither function is ever
# called by, or shares any code path with, `compute_s3_disposal_id` above --
# identity-hash input and human-meaningful-field extraction never share a
# decode step (TC-Q1c).
# ---------------------------------------------------------------------------

PREFIX_CLASS_RECORDABLE = "recordable"
PREFIX_CLASS_RETENTION_MARKER = "retention_marker"
PREFIX_CLASS_UNRECOGNIZED = "unrecognized"

# S3 evidence-class prefix -> DisposalRecord.evidence_class value. Confirmed
# against Technical Design Section 18.1's Category 1/2 table: RunMetadata
# (raw-results/) -> raw_evidence; IntelligenceMetadata (intelligence/) ->
# intelligence; ReportMetadata (reports/) -> report; CertificationMetadata
# (integrity/) -> certificate.
_S3_PREFIX_TO_EVIDENCE_CLASS: dict[str, str] = {
    "raw-results": "raw_evidence",
    "intelligence": "intelligence",
    "reports": "report",
    "integrity": "certificate",
}


class EvidenceKeyParseError(ValueError):
    """Raised by `parse_s3_evidence_key` (and, for the DynamoDB path, the
    internal governed-key extraction helper) on any malformed or unexpected
    key/PK/SK shape. Per ADR Invariant 48: fails closed by construction,
    raising rather than returning a sentinel value the caller might silently
    accept.
    """


def classify_s3_key_prefix(key: str) -> str:
    """Prefix-dispatch classification on the RAW key, checked before any
    positional parsing is attempted (Technical Design Section 22.6/22.12).

    Returns PREFIX_CLASS_RETENTION_MARKER for the one explicitly recognized,
    non-evidentiary exclusion (`retention-markers/`); PREFIX_CLASS_RECORDABLE
    for any of the four evidence-class prefixes; PREFIX_CLASS_UNRECOGNIZED
    otherwise -- an unrecognized prefix is NOT valid-but-irrelevant (ADR
    Invariant 42's Round 2 correction) and must fail closed as
    unknown/incompatible by the caller.
    """
    if key.startswith(f"{RETENTION_MARKER_KEY_PREFIX}/"):
        return PREFIX_CLASS_RETENTION_MARKER
    for prefix in S3_EVIDENCE_CLASS_PREFIXES:
        if key.startswith(f"{prefix}/"):
            return PREFIX_CLASS_RECORDABLE
    return PREFIX_CLASS_UNRECOGNIZED


@dataclass(frozen=True)
class ParsedEvidenceKey:
    client_id: str
    audit_id: str
    evidence_class: str


def parse_s3_evidence_key(key: str) -> ParsedEvidenceKey:
    """Dedicated key-parsing and validation logic (ADR Invariant 48;
    Technical Design Section 22.12) -- NOT a reuse of
    `finalization_gate.py::_extract_run_id_from_s3_key` or any other
    permissive, empty-string-on-failure parser. Validates segment count and
    non-emptiness for every extracted component and RAISES
    `EvidenceKeyParseError` on any malformed or unexpected shape, rather
    than returning a sentinel a caller might fail to check.

    Percent-decodes the key for extraction purposes only -- this decoded
    value is never used for identity-hash computation (`compute_s3_disposal_id`
    always hashes the raw key).

    Handles all four structurally different evidence-class key shapes
    (`raw-results/{client_id}/{audit_id}/{run_id}/results.json`;
    `intelligence/{client_id}/{audit_id}/{audit_execution_id}/...`;
    `reports/{client_id}/{audit_id}/.../{report_job_id}/artifact.json`;
    `integrity/{client_id}/{audit_id}/.../{certjob_id}/artifact.json`) via
    one shared structural rule: prefix, then `client_id`, then `audit_id`,
    then at least one further non-empty segment, with the final segment
    itself non-empty and no empty intermediate segment.
    """
    decoded_key = unquote(key)
    parts = decoded_key.split("/")
    if len(parts) < 4:
        raise EvidenceKeyParseError(f"key has too few path segments: {key!r}")

    prefix = parts[0]
    if prefix not in _S3_PREFIX_TO_EVIDENCE_CLASS:
        raise EvidenceKeyParseError(f"key has unrecognized evidence-class prefix: {key!r}")

    client_id, audit_id = parts[1], parts[2]
    if not client_id or not audit_id:
        raise EvidenceKeyParseError(f"key is missing client_id/audit_id segment: {key!r}")

    remaining_segments = parts[3:]
    if not remaining_segments or any(not segment for segment in remaining_segments):
        raise EvidenceKeyParseError(f"key has an empty or missing trailing path segment: {key!r}")

    return ParsedEvidenceKey(
        client_id=client_id,
        audit_id=audit_id,
        evidence_class=_S3_PREFIX_TO_EVIDENCE_CLASS[prefix],
    )


def _extract_client_audit_from_governed_keys(pk: str, sk: str) -> tuple[str, str]:
    """Extract (client_id, audit_id) from a governed DynamoDB record's own
    PK/SK (`PK=CLIENT#{client_id}`, `SK=AUDIT#{audit_id}#...`) -- the
    DynamoDB-path counterpart to `parse_s3_evidence_key` above, subject to
    the identical fail-closed-by-construction discipline (ADR Invariant 48).
    """
    if not pk.startswith("CLIENT#") or not sk.startswith("AUDIT#"):
        raise EvidenceKeyParseError(
            f"OLD_IMAGE PK/SK do not match the expected governed-record shape: PK={pk!r}, SK={sk!r}"
        )
    client_id = pk[len("CLIENT#") :]
    audit_id = sk[len("AUDIT#") :].split("#", 1)[0]
    if not client_id or not audit_id:
        raise EvidenceKeyParseError(
            f"OLD_IMAGE PK/SK carry an empty client_id/audit_id segment: PK={pk!r}, SK={sk!r}"
        )
    return client_id, audit_id


# ---------------------------------------------------------------------------
# (f) Duplicate-conflict verification, not duplicate assumption
# (ADR Decision 13, Invariant 39/49; Technical Design Section 22.3)
# ---------------------------------------------------------------------------

# recorded_at is the ONLY field excluded from the duplicate-conflict
# comparison (processing-time, expected to differ between the original write
# and this verification read-back). Every other field on DisposalRecord --
# including all seven source-identity fields -- participates.
_DUPLICATE_COMPARISON_EXCLUDED_FIELDS: frozenset[str] = frozenset({"recorded_at"})


@dataclass(frozen=True)
class DuplicateVerificationResult:
    """Result of `verify_duplicate_or_collision`.

    `disposition` is always DISPOSITION_CONFIRMED_DUPLICATE (exact match on
    every compared field) or DISPOSITION_INTEGRITY_FAILURE (any mismatch).
    `mismatched_fields` is populated only for the integrity-failure case.
    """

    disposition: str
    mismatched_fields: tuple[str, ...] = ()


def verify_duplicate_or_collision(
    repository: DisposalRepository,
    *,
    client_id: str,
    audit_id: str,
    disposal_id: str,
    candidate: DisposalRecord,
) -> DuplicateVerificationResult:
    """On a `ConditionalCheckFailedException` from `put_disposal_record`,
    perform the strongly consistent read-back and field-by-field comparison
    Technical Design Section 22.3 requires -- a `ConditionalCheckFailedException`
    is only proof a record already exists at the computed key, never proof
    of a duplicate delivery by itself.

    Compares every field of `candidate` (the freshly computed new attempt)
    against the existing persisted item, excluding only `recorded_at`. This
    necessarily includes `record_type`, `client_id`, `audit_id`, `disposal_id`
    (the identity fields the read was keyed on, compared anyway as a
    structural sanity check per Section 22.3), `disposal_id_scheme`,
    `source_kind`, and whichever source-identity fields apply -- the
    corrected comparison surface (ADR Invariant 49) -- plus every other
    immutable disposal fact.

    An exact match is a confirmed idempotent duplicate. Any single-field
    mismatch -- including a source-identity-only mismatch with matching
    disposal facts -- is a `disposal_id` collision with unequal immutable
    content: a distinct integrity failure, never silently accepted.

    If the read-back itself finds nothing (the existing record vanished
    between the conditional-put conflict and this read -- not expected for
    a write-once, never-deleted record type, but not structurally
    impossible), this fails closed as an integrity failure rather than
    assuming anything about the missing record.
    """
    existing_item = repository.get_disposal_record(
        client_id, audit_id, disposal_id, consistent_read=True
    )
    if existing_item is None:
        return DuplicateVerificationResult(
            DISPOSITION_INTEGRITY_FAILURE, mismatched_fields=("<missing_on_readback>",)
        )

    candidate_dict = candidate.to_dict()
    mismatched = tuple(
        field_name
        for field_name in candidate_dict
        if field_name not in _DUPLICATE_COMPARISON_EXCLUDED_FIELDS
        and existing_item.get(field_name) != candidate_dict.get(field_name)
    )
    if mismatched:
        return DuplicateVerificationResult(
            DISPOSITION_INTEGRITY_FAILURE, mismatched_fields=mismatched
        )
    return DuplicateVerificationResult(DISPOSITION_CONFIRMED_DUPLICATE)


# ---------------------------------------------------------------------------
# (g) Per-record / per-event processing orchestration
# (Technical Design Section 22 in full)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DispositionOutcome:
    """The result of processing one DynamoDB Streams record or one S3
    EventBridge event through the full (a)-(f) pipeline.

    `disposition` is always one of the six ALL_DISPOSITIONS values.
    `disposal_record` is populated only for DISPOSITION_RECORDABLE (a
    successful new write) and, for debuggability, for
    DISPOSITION_CONFIRMED_DUPLICATE / DISPOSITION_INTEGRITY_FAILURE (the
    candidate record that was compared against the existing one).
    `mismatched_fields` is populated only when `disposition ==
    DISPOSITION_INTEGRITY_FAILURE` as a result of duplicate-conflict
    verification.
    """

    disposition: str
    reason: str
    disposal_record: DisposalRecord | None = None
    mismatched_fields: tuple[str, ...] = ()


def _epoch_seconds_to_iso8601(value: float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


def _attempt_write(repository: DisposalRepository, candidate: DisposalRecord) -> DispositionOutcome:
    """Shared write-attempt + duplicate-conflict-verification tail, common
    to both the DynamoDB and S3 orchestration paths below.
    """
    try:
        repository.put_disposal_record(
            client_id=candidate.client_id,
            audit_id=candidate.audit_id,
            disposal_id=candidate.disposal_id,
            evidence_class=candidate.evidence_class,
            disposal_mechanism=candidate.disposal_mechanism,
            disposed_identity_ref=candidate.disposed_identity_ref,
            disposed_at=candidate.disposed_at,
            recorded_at=candidate.recorded_at,
            disposal_id_scheme=candidate.disposal_id_scheme,
            source_kind=candidate.source_kind,
            source_stream_identity=candidate.source_stream_identity,
            source_event_id=candidate.source_event_id,
            source_bucket=candidate.source_bucket,
            source_object_key=candidate.source_object_key,
            source_object_version_id=candidate.source_object_version_id,
            source_created_at=candidate.source_created_at,
            custody_period_days_applied=candidate.custody_period_days_applied,
        )
    except ConditionalWriteError:
        verification = verify_duplicate_or_collision(
            repository,
            client_id=candidate.client_id,
            audit_id=candidate.audit_id,
            disposal_id=candidate.disposal_id,
            candidate=candidate,
        )
        return DispositionOutcome(
            disposition=verification.disposition,
            reason="duplicate_conflict_verification",
            disposal_record=candidate,
            mismatched_fields=verification.mismatched_fields,
        )
    return DispositionOutcome(
        disposition=DISPOSITION_RECORDABLE, reason="written", disposal_record=candidate
    )


def process_dynamodb_stream_record(
    record: dict[str, Any],
    *,
    expected_stream_arn: str,
    repository: DisposalRepository,
    now_fn: Callable[[], str] = utc_now_iso,
) -> DispositionOutcome:
    """Full per-record pipeline for one DynamoDB Streams record: provenance
    validation (b) -> identity computation (a) -> conditional write, with
    duplicate-conflict verification (f) on conflict.

    `disposal_mechanism` is always `DYNAMODB_TTL` on this path.
    """
    provenance = validate_dynamodb_provenance(record, expected_stream_arn=expected_stream_arn)
    if provenance.disposition != DISPOSITION_RECORDABLE:
        return DispositionOutcome(disposition=provenance.disposition, reason=provenance.reason)

    old_image = provenance.old_image or {}
    stream_identity = record.get("eventSourceARN", "")
    event_id = record.get("eventID", "")

    try:
        client_id, audit_id = _extract_client_audit_from_governed_keys(
            old_image["PK"], old_image["SK"]
        )
    except EvidenceKeyParseError as exc:
        return DispositionOutcome(
            disposition=DISPOSITION_MALFORMED_TARGET_PROVENANCE, reason=str(exc)
        )

    disposal_id = compute_dynamodb_disposal_id(stream_identity, event_id)

    approximate_creation = (record.get("dynamodb") or {}).get("ApproximateCreationDateTime")
    disposed_at = (
        _epoch_seconds_to_iso8601(approximate_creation)
        if isinstance(approximate_creation, (int, float))
        else now_fn()
    )

    candidate = DisposalRecord(
        PK=f"CLIENT#{client_id}",
        SK=f"AUDIT#{audit_id}#DISPOSAL#{disposal_id}",
        record_type=DISPOSAL_RECORD_RECORD_TYPE,
        disposal_id=disposal_id,
        disposal_id_scheme=DISPOSAL_ID_SCHEME_V1,
        source_kind=SOURCE_KIND_DYNAMODB_TTL_REMOVE,
        source_stream_identity=stream_identity,
        source_event_id=event_id,
        source_bucket=None,
        source_object_key=None,
        source_object_version_id=None,
        client_id=client_id,
        audit_id=audit_id,
        evidence_class=old_image["evidence_class"],
        disposal_mechanism=DISPOSAL_MECHANISM_DYNAMODB_TTL,
        disposed_identity_ref=f"{old_image['PK']}#{old_image['SK']}",
        disposed_at=disposed_at,
        recorded_at=now_fn(),
        source_created_at=old_image.get("created_at"),
        custody_period_days_applied=None,
    )
    return _attempt_write(repository, candidate)


def process_s3_eventbridge_event(
    event: dict[str, Any],
    *,
    expected_account_id: str,
    expected_bucket_name: str,
    supported_major_version: int,
    minimum_minor_version: int,
    repository: DisposalRepository,
    now_fn: Callable[[], str] = utc_now_iso,
) -> DispositionOutcome:
    """Full per-event pipeline for one S3 EventBridge "Object Deleted"
    event: envelope/provenance validation (c) -> prefix restriction and key
    parsing (d) -> identity computation (a) -> conditional write, with
    duplicate-conflict verification (f) on conflict.

    `disposal_mechanism` is always
    `S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION` on this path -- reasoned
    from Technical Design Section 22.5.1 directly, not assumed: for a
    versioned bucket, the Lifecycle `Expiration` action never itself
    produces a "Permanently Deleted" event (it only inserts a delete
    marker, per Section 22.5.1); under this design's two-action Lifecycle
    rule shape (ADR Decision 1), a "Permanently Deleted" event is always
    produced by the subsequent `NoncurrentVersionExpiration` action acting
    on what became the noncurrent version.
    """
    provenance = validate_s3_provenance(
        event,
        expected_account_id=expected_account_id,
        expected_bucket_name=expected_bucket_name,
        supported_major_version=supported_major_version,
        minimum_minor_version=minimum_minor_version,
    )
    if provenance.disposition != DISPOSITION_RECORDABLE:
        return DispositionOutcome(disposition=provenance.disposition, reason=provenance.reason)

    detail = provenance.detail
    raw_key = detail["key"]

    prefix_class = classify_s3_key_prefix(raw_key)
    if prefix_class == PREFIX_CLASS_RETENTION_MARKER:
        return DispositionOutcome(
            disposition=DISPOSITION_VALID_BUT_IRRELEVANT, reason="retention_marker_prefix"
        )
    if prefix_class == PREFIX_CLASS_UNRECOGNIZED:
        return DispositionOutcome(
            disposition=DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE, reason="unrecognized_prefix"
        )

    try:
        parsed = parse_s3_evidence_key(raw_key)
    except EvidenceKeyParseError as exc:
        return DispositionOutcome(
            disposition=DISPOSITION_MALFORMED_TARGET_PROVENANCE, reason=str(exc)
        )

    disposal_id = compute_s3_disposal_id(
        bucket=detail["bucket"],
        key=raw_key,
        version_id=detail["version_id"],
        reason=detail["reason"],
        deletion_type=detail["deletion_type"],
    )

    disposed_at = event.get("time") or now_fn()

    candidate = DisposalRecord(
        PK=f"CLIENT#{parsed.client_id}",
        SK=f"AUDIT#{parsed.audit_id}#DISPOSAL#{disposal_id}",
        record_type=DISPOSAL_RECORD_RECORD_TYPE,
        disposal_id=disposal_id,
        disposal_id_scheme=DISPOSAL_ID_SCHEME_V1,
        source_kind=SOURCE_KIND_S3_LIFECYCLE_DELETE,
        source_stream_identity=None,
        source_event_id=None,
        source_bucket=detail["bucket"],
        source_object_key=raw_key,
        source_object_version_id=detail["version_id"],
        client_id=parsed.client_id,
        audit_id=parsed.audit_id,
        evidence_class=parsed.evidence_class,
        disposal_mechanism=DISPOSAL_MECHANISM_S3_LIFECYCLE_NONCURRENT_VERSION_EXPIRATION,
        disposed_identity_ref=f"{raw_key}#{detail['version_id']}",
        disposed_at=disposed_at,
        recorded_at=now_fn(),
        source_created_at=None,
        custody_period_days_applied=None,
    )
    return _attempt_write(repository, candidate)


__all__ = [
    "DISPOSAL_ID_SCHEME_V1",
    "SOURCE_KIND_DYNAMODB_TTL_REMOVE",
    "SOURCE_KIND_S3_LIFECYCLE_DELETE",
    "DISPOSITION_RECORDABLE",
    "DISPOSITION_VALID_BUT_IRRELEVANT",
    "DISPOSITION_MALFORMED_TARGET_PROVENANCE",
    "DISPOSITION_UNKNOWN_INCOMPATIBLE_SOURCE",
    "DISPOSITION_CONFIRMED_DUPLICATE",
    "DISPOSITION_INTEGRITY_FAILURE",
    "ALL_DISPOSITIONS",
    "compute_dynamodb_disposal_id",
    "compute_s3_disposal_id",
    "DynamoDbProvenanceResult",
    "validate_dynamodb_provenance",
    "S3ProvenanceResult",
    "validate_s3_provenance",
    "PREFIX_CLASS_RECORDABLE",
    "PREFIX_CLASS_RETENTION_MARKER",
    "PREFIX_CLASS_UNRECOGNIZED",
    "classify_s3_key_prefix",
    "ParsedEvidenceKey",
    "parse_s3_evidence_key",
    "EvidenceKeyParseError",
    "DuplicateVerificationResult",
    "verify_duplicate_or_collision",
    "DispositionOutcome",
    "process_dynamodb_stream_record",
    "process_s3_eventbridge_event",
]
