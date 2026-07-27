"""S3 canary-marker store for evidence_retention Workstream A1 (Legal-Hold
Correction B2; companion ADR Decision 9 amendments, Non-Negotiable
Invariants 15-24; Technical Design Section 19.5, "S3 Concurrency and
Reconciliation Protocol -- Canary-Marker Mechanism").

Single responsibility: construct, validate, atomically create, and
authoritatively confirm the small governance-metadata marker object that
anchors the S3-side reconciliation pass's boundary (Technical Design
Section 19.5.5) in the same clock domain (S3's own) as the evidence it
protects -- eliminating cross-service (Lambda-vs-S3) clock skew as the
primary correctness argument for the S3 leg (ADR Invariant 15).

Deliberately NOT part of CustodySweepClient: that class's no-put_object/
no-head_object/no-get_object invariant (Section 5.2/18.3, its own module
docstring) is fully preserved by keeping this responsibility in a separate,
narrowly-scoped component, exactly as Technical Design Section 19.5.9
specifies ("The marker write is deliberately not added to
CustodySweepClient... RetentionService... is the component that performs
the marker write, via a narrow, dedicated helper distinct from both
existing classes."). MarkerStore has no DynamoDB dependency of any kind --
persisting the confirmed outcome onto LegalHoldEvent/LegalHold is
RetentionService's job (retention_service.py), coordinating this class with
HoldRepository.

Key mechanics implemented here, all traceable to Technical Design Section
19.5:

  - Marker key construction/validation (19.5.1, 19.5.2) -- build_marker_key(),
    _assert_marker_key(). Non-collision between any two transitions is
    proved by hold_version's monotonicity alone (ADR Invariant 21/12), not
    by hold_id changing per transition -- see hold_transitions.py and
    hold_repository.py for the identity model this key format depends on.
  - Deterministic marker content (19.5.1) -- build_marker_content().
  - Atomic, first-write-wins conditional creation via PutObject with
    If-None-Match: "*" -- NEVER a HeadObject-then-PutObject check-then-write
    sequence (ADR Invariant 19; Technical Design Section 19.5.7's fix for
    the check-then-write TOCTOU an earlier revision had).
  - Orphan-marker / conflict recovery (19.5.7): on a 412 Precondition Failed
    response, read back and VALIDATE the existing marker's content against
    the current transition's expected identity before ever trusting it --
    never blindly assumed to be either safe to reuse or a collision.
  - Authoritative LastModified capture via a dedicated HeadObject read-back
    (19.5.3 step 3) -- PutObject's own response is never trusted for this.
  - Bounded retry + a shared wall-clock budget across the ENTIRE
    establish_marker() call, spanning both the PutObject/precondition phase
    and the HeadObject read-back phase (Technical Design Section 19.5.6's
    architecture + security review correction: a retry-count cap alone is
    insufficient, the sequence must also be capped by total wall-clock time,
    not attempts alone).
  - _assert_marker_key() structural guard (ADR Invariant 20), called before
    every S3 operation this component performs, mirroring
    hold_repository.py::_assert_retention_sk /
    disposal_repository.py::_assert_disposal_sk /
    custody_sweep_client.py::_assert_custody_field_only_update.

What this module deliberately does NOT do (RetentionService's job instead,
Technical Design Section 19.5.3 step 2 / ADR Invariant 24): check
LegalHoldEvent.marker_status before deciding whether to call
establish_marker() at all. That check happens durably in DynamoDB, entirely
independent of whether the marker object still exists in S3 -- this module
has no DynamoDB dependency and is never itself the authority for "has this
transition's marker already been confirmed." Every call to
establish_marker() unconditionally attempts the S3-side sequence; the
caller (RetentionService) is responsible for skipping that call entirely
once LegalHoldEvent.marker_status already reads CONFIRMED.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.constants import (
    HOLD_MARKER_ESTABLISHMENT_FAILED_CODE,
    HOLD_MARKER_INTEGRITY_VIOLATION_CODE,
    MARKER_ESTABLISHMENT_WALL_CLOCK_BUDGET_SECONDS,
    MARKER_SCHEMA_VERSION,
    MARKER_STATUS_CONFIRMED,
    MAX_HOLD_COORDINATION_RETRY_ATTEMPTS,
    RETENTION_MARKER_KEY_PREFIX,
)

# S3's documented response code for an If-None-Match precondition failure
# (an object already exists at the target key). Some S3-compatible
# implementations/older botocore surfaces report this as the bare "412"
# status code string rather than the named error code -- both are treated
# identically here.
_PRECONDITION_FAILED_CODES = frozenset({"PreconditionFailed", "412"})

# Structural allowlist (mirrors custody_sweep_client.py's
# _ALLOWED_S3_METHODS / _ALLOWED_DYNAMODB_METHODS pattern): this class may
# only ever call these three S3 operations, scoped strictly to the
# retention-markers/ prefix (Technical Design Section 19.5.9's IAM logical
# scope -- s3:PutObject/s3:HeadObject/s3:GetObject only). No put_object call
# here is ever unconditional (see _put_marker_conditional).
_ALLOWED_S3_METHODS = frozenset({"put_object", "head_object", "get_object"})

# The five identity fields whose exact match is required for an existing
# marker (found on conditional-write conflict) to be accepted as authoritative
# for the CURRENT transition, per Technical Design Section 19.5.7 / ADR
# Invariant 21's non-collision guarantee. schema_version and the derived
# transition_id field are intentionally excluded from this comparison --
# they are metadata about the payload, not part of the identity tuple itself.
_MARKER_IDENTITY_FIELDS = ("client_id", "audit_id", "hold_id", "hold_version", "transition")


def build_marker_key(
    client_id: str, audit_id: str, hold_id: str, hold_version: int, transition: str
) -> str:
    """Construct the canary marker S3 key (Technical Design Section 19.5.1).

    Required shape:
      retention-markers/{client_id}/{audit_id}/{hold_id}/{hold_version}-{transition}.marker

    Non-collision between PLACE and RELEASE of the same episode -- and
    between any two transitions across any two episodes -- is proved by
    hold_version's monotonicity alone (never reused, never reset; ADR
    Invariant 12), independent of hold_id, which is held constant across a
    PLACE/RELEASE pair (ADR Invariant 21). {transition} is included as a
    self-describing, human-readable redundancy, not a second load-bearing
    uniqueness source (Technical Design Section 19.5.2).
    """
    return (
        f"{RETENTION_MARKER_KEY_PREFIX}/{client_id}/{audit_id}/{hold_id}/"
        f"{hold_version}-{transition}.marker"
    )


def build_marker_content(
    client_id: str, audit_id: str, hold_id: str, hold_version: int, transition: str
) -> dict[str, Any]:
    """Construct the deterministic canary marker JSON payload (Technical
    Design Section 19.5.1).

    Deterministic given the same inputs -- two independent computations of
    the same (client_id, audit_id, hold_id, hold_version, transition) tuple
    always produce byte-identical JSON when serialized with sort_keys=True
    (see _serialize_marker_content()), which is what makes the idempotent-
    replay property (Technical Design Section 19.5.2 property 2) directly
    verifiable rather than merely asserted.

    Fields, exactly:
      - client_id, audit_id, hold_id, hold_version, transition: the full
        identity tuple the marker key itself already encodes, carried
        redundantly in the content per Technical Design Section 19.5.1
        ("enough to make an orphaned marker self-describing without a
        lookup, and redundant with the key's own components for
        defense-in-depth").
      - transition_id: a single combined identity/event field
        (f"{hold_id}#{hold_version}#{transition}") a reader can use to
        identify exactly which LegalHoldEvent this marker corresponds to
        without ambiguity -- deliberately identical in shape to
        HoldRepository.legal_hold_event_key()'s own SK discriminator
        (AUDIT#{audit_id}#LEGALHOLD#{hold_id}#{hold_version}), so the two
        records are directly cross-referenceable by construction, not by
        convention alone.
      - schema_version: MARKER_SCHEMA_VERSION, so a future change to this
        payload's shape is detectable by any reader, including an orphaned
        marker read back long after the code that wrote it may have
        changed.

    Naming note (documented choice, not a silent deviation): Technical
    Design Section 19.5.1's own worked JSON example uses the key name
    "action" for PLACE/RELEASE. This module uses "transition" instead, for
    consistency with the parameter name used throughout this module, the
    rest of the ADR/Technical Design's own prose (e.g. "{hold_version}-
    {transition}.marker", ADR Invariant 20's "the transition supplied by the
    caller"), and this codebase's marker-related call signatures generally.
    This is a field-naming choice only; the semantic content
    (PLACE|RELEASE) is identical.
    """
    return {
        "schema_version": MARKER_SCHEMA_VERSION,
        "client_id": client_id,
        "audit_id": audit_id,
        "hold_id": hold_id,
        "hold_version": hold_version,
        "transition": transition,
        "transition_id": f"{hold_id}#{hold_version}#{transition}",
    }


def _serialize_marker_content(content: dict[str, Any]) -> bytes:
    return json.dumps(content, sort_keys=True).encode("utf-8")


def _assert_marker_key(
    key: str,
    client_id: str,
    audit_id: str,
    hold_id: str,
    hold_version: int,
    transition: str,
) -> None:
    """Structural guard (ADR Non-Negotiable Invariant 20): assert the
    supplied key is EXACTLY the reconstructed key for the given identity
    tuple and transition -- called before every S3 operation MarkerStore
    performs, mirroring hold_repository.py::_assert_retention_sk /
    disposal_repository.py::_assert_disposal_sk /
    custody_sweep_client.py::_assert_custody_field_only_update.

    This is an exact-match assertion, not a namespace-membership check the
    way the other three guards are (those only need to confirm broad
    namespace membership across many possible items; a marker's full
    identity is always known at each call site, per Technical Design
    Section 19.5.9, so exact-match validation is both possible and the
    correct level of rigor here). This closes the same class of gap those
    guards close for their own namespaces: a future code change cannot
    accidentally construct a write outside the retention-markers/ prefix,
    under a mismatched identity tuple, or against the wrong transition's
    own marker (e.g. a PLACE key accepted when RELEASE was expected, or
    vice versa), without an immediate, loud failure.

    Raises:
        AssertionError: If `key` does not exactly equal the key
            reconstructed from the supplied identity tuple and transition.
    """
    expected = build_marker_key(client_id, audit_id, hold_id, hold_version, transition)
    if key != expected:
        raise AssertionError(
            "Canary marker key assertion failed: expected "
            f"{expected!r} for (client_id={client_id!r}, audit_id={audit_id!r}, "
            f"hold_id={hold_id!r}, hold_version={hold_version!r}, "
            f"transition={transition!r}), got {key!r}."
        )


def format_s3_timestamp(value: Any) -> str:
    """Format an S3-returned LastModified value (a `datetime.datetime`, per
    boto3's automatic timestamp parsing, or already a string in test doubles)
    as this codebase's standard UTC ISO-8601 "Z"-suffixed string (matching
    release_confidence_platform.core.time.utc_now_iso()'s own format), for
    durable persistence on LegalHoldEvent/LegalHold.
    """
    if isinstance(value, str):
        return value
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")
    raise TypeError(f"Cannot format S3 LastModified value of type {type(value)!r}")


def parse_s3_timestamp(value: Any) -> datetime:
    """Parse a marker_confirmed_last_modified value (a "Z"-suffixed ISO-8601
    string, this module's own persisted form) or a raw S3-returned
    `datetime.datetime` (e.g. a version's LastModified from
    ListObjectVersions) into a timezone-aware UTC datetime, for the
    reconciliation pass's boundary comparison (custody_sweep_client.py::
    reconcile_versions, Technical Design Section 19.5.5).
    """
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError(f"Cannot parse S3 timestamp value of type {type(value)!r}")


class MarkerEstablishmentFailedError(StorageError):
    """Technical Design Section 19.5.6 / 19.15.

    Raised when the canary marker's PutObject (or the subsequent HeadObject
    read-back) fails on every attempt up to the bounded retry limit, OR the
    combined wall-clock budget for the entire establish_marker() sequence
    (both phases) is exhausted first -- whichever trigger fires first (the
    two caps are independent; either one ends the attempt sequence). Never a
    silent fallback to proceeding without a confirmed marker (ADR Invariant
    14/18).
    """

    def __init__(self, message: str = "Canary marker establishment failed"):
        super().__init__(message, HOLD_MARKER_ESTABLISHMENT_FAILED_CODE)


class MarkerIntegrityError(StorageError):
    """Technical Design Section 19.5.7.

    Raised when a conditional-write conflict (412 Precondition Failed) is
    found to be a GENUINE collision -- an existing marker at this exact key
    whose content does not match the current transition's expected identity
    tuple. Structurally very hard to reach given the key already encodes the
    full identity tuple (Technical Design Section 19.5.2's non-collision
    proof), but checked and handled deterministically, never assumed
    impossible and never silently ignored.
    """

    def __init__(self, message: str = "Canary marker integrity violation"):
        super().__init__(message, HOLD_MARKER_INTEGRITY_VIOLATION_CODE)


@dataclass(frozen=True)
class MarkerEstablishmentResult:
    """Outcome of a confirmed canary marker (Technical Design Section
    19.5.3 steps 2-3). marker_status is always MARKER_STATUS_CONFIRMED --
    MarkerStore never returns a result for a FAILED attempt, it raises
    instead (see MarkerEstablishmentFailedError/MarkerIntegrityError)."""

    marker_s3_key: str
    marker_status: str
    marker_confirmed_last_modified: str


class MarkerStore:
    """Atomic canary-marker creation/confirmation (Technical Design Section
    19.5.1-19.5.7). No DynamoDB dependency; no CustodySweepClient dependency.
    RetentionService (retention_service.py) is the sole intended caller,
    coordinating this class with HoldRepository per Technical Design Section
    19.5.3/19.5.9.
    """

    def __init__(
        self,
        bucket_name: str,
        s3_client: Any,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_attempts: int = MAX_HOLD_COORDINATION_RETRY_ATTEMPTS,
        wall_clock_budget_seconds: float = MARKER_ESTABLISHMENT_WALL_CLOCK_BUDGET_SECONDS,
    ) -> None:
        self._bucket_name = bucket_name
        self._s3_client = s3_client
        self._clock = clock
        self._max_attempts = max_attempts
        self._wall_clock_budget_seconds = wall_clock_budget_seconds

    def establish_marker(
        self,
        client_id: str,
        audit_id: str,
        hold_id: str,
        hold_version: int,
        transition: str,
    ) -> MarkerEstablishmentResult:
        """Establish and confirm the canary marker for one transition
        (Technical Design Section 19.5.3 steps 2-3, 19.5.6, 19.5.7).

        Unconditionally attempts the full S3-side sequence every call --
        the caller (RetentionService) is responsible for skipping this call
        entirely once LegalHoldEvent.marker_status already reads CONFIRMED
        for this transition (ADR Invariant 24; this module has no
        DynamoDB dependency and cannot perform that check itself).

        Sequence:
          1. Compute and structurally assert the marker key
             (_assert_marker_key -- ADR Invariant 20).
          2. Attempt an atomic conditional PutObject (If-None-Match: "*"),
             never a HeadObject-then-PutObject check-then-write (ADR
             Invariant 19). On a 412 precondition failure, read back and
             VALIDATE the existing marker's content against this
             transition's expected identity (Technical Design Section
             19.5.7) -- accept it if it matches, raise MarkerIntegrityError
             if it does not.
          3. Perform a dedicated HeadObject read-back to capture the
             authoritative LastModified -- PutObject's own response is
             never trusted for this (Technical Design Section 19.5.3 step 3).

        Both phases share ONE wall-clock deadline, measured from the start
        of this call (Technical Design Section 19.5.6's architecture +
        security review correction) -- each phase also has its own bounded
        retry-count cap. Either cap being exceeded, in either phase, raises
        MarkerEstablishmentFailedError; a genuine identity mismatch
        (MarkerIntegrityError) is never retried and propagates immediately.

        Raises:
            MarkerEstablishmentFailedError: Retry-count or wall-clock budget
                exhausted in either phase.
            MarkerIntegrityError: An existing marker was found at this exact
                key whose content does not match this transition's expected
                identity tuple.
        """
        key = build_marker_key(client_id, audit_id, hold_id, hold_version, transition)
        _assert_marker_key(key, client_id, audit_id, hold_id, hold_version, transition)
        content = build_marker_content(client_id, audit_id, hold_id, hold_version, transition)
        body = _serialize_marker_content(content)

        deadline_start = self._clock()

        def _deadline_exceeded() -> bool:
            return (self._clock() - deadline_start) >= self._wall_clock_budget_seconds

        # Phase 1: atomic conditional creation, or validated reuse of an
        # already-existing marker for this exact (hold_id, hold_version,
        # transition) -- Technical Design Section 19.5.7.
        attempts = 0
        while True:
            if attempts >= self._max_attempts or _deadline_exceeded():
                raise MarkerEstablishmentFailedError(
                    f"Canary marker creation exhausted for key {key!r} after "
                    f"{attempts} attempt(s)"
                )
            attempts += 1
            try:
                self._attempt_put_or_reuse(
                    key, body, client_id, audit_id, hold_id, hold_version, transition
                )
                break
            except MarkerIntegrityError:
                raise
            except Exception:
                # Any transient failure (S3 client/request error, including
                # one surfaced from the validate-existing-marker read-back
                # path) -- retry the whole attempt (a fresh PutObject next
                # time), bounded by the same caps above.
                continue

        # Phase 2: authoritative LastModified capture via a dedicated
        # HeadObject read-back -- PutObject's own response is never trusted
        # for this (Technical Design Section 19.5.3 step 3). Shares the same
        # wall-clock deadline as phase 1; its own retry-count cap resets.
        attempts = 0
        while True:
            if attempts >= self._max_attempts or _deadline_exceeded():
                raise MarkerEstablishmentFailedError(
                    f"Canary marker HeadObject read-back exhausted for key "
                    f"{key!r} after {attempts} attempt(s)"
                )
            attempts += 1
            try:
                response = self._call_s3("head_object", Bucket=self._bucket_name, Key=key)
                last_modified = response.get("LastModified")
                if last_modified is None:
                    raise ValueError("HeadObject response missing LastModified")
                return MarkerEstablishmentResult(
                    marker_s3_key=key,
                    marker_status=MARKER_STATUS_CONFIRMED,
                    marker_confirmed_last_modified=format_s3_timestamp(last_modified),
                )
            except Exception:
                continue

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _attempt_put_or_reuse(
        self,
        key: str,
        body: bytes,
        client_id: str,
        audit_id: str,
        hold_id: str,
        hold_version: int,
        transition: str,
    ) -> None:
        try:
            self._call_s3(
                "put_object",
                Bucket=self._bucket_name,
                Key=key,
                Body=body,
                ContentType="application/json",
                IfNoneMatch="*",
            )
            return
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code not in _PRECONDITION_FAILED_CODES:
                raise
        # Precondition failed: a marker for this exact (hold_id,
        # hold_version, transition) already exists -- either from an
        # earlier attempt of THIS invocation being resumed, or a genuinely
        # concurrent overlapping invocation that won the race (Technical
        # Design Section 19.5.2 properties 2/4, Section 19.5.7). Read it
        # back and validate identity -- never assume success or failure
        # blindly.
        self._validate_existing_marker(key, client_id, audit_id, hold_id, hold_version, transition)

    def _validate_existing_marker(
        self,
        key: str,
        client_id: str,
        audit_id: str,
        hold_id: str,
        hold_version: int,
        transition: str,
    ) -> None:
        response = self._call_s3("get_object", Bucket=self._bucket_name, Key=key)
        body = response["Body"].read()
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        existing_content = json.loads(body)
        expected_content = build_marker_content(
            client_id, audit_id, hold_id, hold_version, transition
        )
        mismatched = {
            field: (existing_content.get(field), expected_content.get(field))
            for field in _MARKER_IDENTITY_FIELDS
            if existing_content.get(field) != expected_content.get(field)
        }
        if mismatched:
            raise MarkerIntegrityError(
                f"Existing canary marker at {key!r} does not match the current "
                f"transition's expected identity: {mismatched!r}"
            )

    def _call_s3(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
        if method_name not in _ALLOWED_S3_METHODS:
            raise AssertionError(
                f"MarkerStore attempted disallowed S3 operation {method_name!r}; "
                f"only {sorted(_ALLOWED_S3_METHODS)!r} are permitted on this class."
            )
        method = getattr(self._s3_client, method_name)
        return method(**kwargs)


__all__ = [
    "MarkerEstablishmentFailedError",
    "MarkerEstablishmentResult",
    "MarkerIntegrityError",
    "MarkerStore",
    "build_marker_content",
    "build_marker_key",
    "format_s3_timestamp",
    "parse_s3_timestamp",
]
