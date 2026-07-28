"""DynamoDB repository for evidence_retention legal hold records (Workstream A1.1).

Single responsibility: read/write access to the LegalHold (current-state) and
LegalHoldEvent (immutable log) records only. Targets exclusively the
#LEGALHOLD# SK namespace.

Sort key write prohibition: every write method calls _assert_retention_sk()
before the DynamoDB call. This is a programming-error guard modeled directly
on _assert_phase7_sk() in audit_platform_integrity/repository.py:49, and is
the code-level enforcement of the companion ADR's Non-Negotiable Invariant 6:
HoldRepository must never construct a #DISPOSAL#-shaped write. The symmetric
guard for disposal records (_assert_disposal_sk()) lives in
disposal_repository.py; the two guards are mutually exclusive by design.

Scope note (A1.1): this repository is scoped strictly to the LegalHold /
LegalHoldEvent record CRUD described in Technical Design Section 7.1/7.2.
The cross-cutting operations Technical Design Section 10.4 depicts as part
of RetentionService.place_legal_hold()/release_legal_hold() — querying and
UpdateItem-ing *other* phases' existing DynamoDB records to remove/restore
ttl_disposal_at, and the S3 object-version re-tagging sweep — necessarily
touch SKs outside the #LEGALHOLD# namespace (e.g. RunMetadata, ReportMetadata
SKs) and S3, respectively. Those operations cannot be added to this
guarded repository without weakening or bypassing _assert_retention_sk(), so
they are deferred to whichever later subphase (A1.2/A1.3) implements
RetentionService; that implementation will need its own, differently-scoped
access path for those operations. See the A1.1 implementation report for the
full rationale.

Scope note (Legal-Hold Correction B1): this repository gains the
hold_version / sweep_status / marker_* fields Technical Design Section 19.1
and Section 19.5.1 require on LegalHold, and hold_version / marker_* on
LegalHoldEvent, plus the required LegalHoldEvent SK correction (ADR
Non-Negotiable Invariant 25; Technical Design Section 19.5.1's "Required
consequence", Section 19.5.2): the SK is now
AUDIT#{audit_id}#LEGALHOLD#{hold_id}#{hold_version}, not hold_id alone —
hold_id is held constant across a PLACE/RELEASE episode pair (ADR Invariant
21), so hold_id alone would make RELEASE's event write collide with its
paired PLACE's at the identical key. legal_hold_event_key(),
get_legal_hold_event(), and write_hold_event() all gain a required
hold_version parameter as a direct result. This remains strict CRUD only —
still no S3 access, no cross-phase DynamoDB access, and _assert_retention_sk()
is unchanged. The PLACE/RELEASE transition *sequencing* that decides what
hold_id/hold_version/sweep_status value to pass into these CRUD methods on a
given invocation (Technical Design Section 19.2/19.3) lives in
hold_transitions.py, not here, preserving this module's existing "CRUD only"
scope.
"""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.constants import (
    DISPOSAL_SK_MARKER,
    LEGAL_HOLD_EVENT_RECORD_TYPE,
    LEGAL_HOLD_RECORD_TYPE,
    LEGALHOLD_SK_MARKER,
    MARKER_STATUS_PENDING,
)
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    storage_error_from_dynamodb_client_error,
    storage_error_from_dynamodb_request_error,
)

# Retention-exclusive SK segment marker. Any write targeting this pattern is permitted.
_RETENTION_SK_MARKERS = (LEGALHOLD_SK_MARKER,)

# Exclusively non-retention record type markers that must never appear in a
# HoldRepository write path.
_PROHIBITED_SK_MARKERS = (DISPOSAL_SK_MARKER,)


def _assert_retention_sk(sk: str) -> None:
    """Assert that an SK is in the #LEGALHOLD# namespace before any write.

    Raises AssertionError if the SK does not contain the retention marker, or
    if it contains the disposal marker. This is a programming-error guard,
    not a user-facing validation.
    """
    has_retention_marker = any(marker in sk for marker in _RETENTION_SK_MARKERS)
    has_prohibited = any(marker in sk for marker in _PROHIBITED_SK_MARKERS)
    if not has_retention_marker or has_prohibited:
        raise AssertionError(
            f"Legal hold write attempted to prohibited SK namespace: {sk!r}. "
            f"HoldRepository writes must target only {LEGALHOLD_SK_MARKER!r} "
            "SK patterns."
        )


class ConditionalWriteError(StorageError):
    def __init__(self, message: str = "Conditional write failed"):
        super().__init__(message, "CONDITIONAL_WRITE_FAILED")


class HoldRepository:
    """DynamoDB read/write access for LegalHold and LegalHoldEvent records only."""

    def __init__(self, table_name: str, dynamodb_client: Any) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client

    # ------------------------------------------------------------------
    # Key construction helpers
    # ------------------------------------------------------------------

    def legal_hold_key(self, client_id: str, audit_id: str) -> dict[str, str]:
        """Build the PK/SK key dict for the LegalHold current-state record."""
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#LEGALHOLD",
        }

    def legal_hold_event_key(
        self, client_id: str, audit_id: str, hold_id: str, hold_version: int
    ) -> dict[str, str]:
        """Build the PK/SK key dict for a LegalHoldEvent record.

        hold_version is a required per-transition discriminator (ADR
        Non-Negotiable Invariant 25) — hold_id alone is insufficient once
        Invariant 21 holds it constant across a PLACE/RELEASE episode pair.
        """
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#LEGALHOLD#{hold_id}#{hold_version}",
        }

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_legal_hold(
        self, client_id: str, audit_id: str, *, consistent_read: bool = False
    ) -> dict[str, Any] | None:
        """Read the current-state LegalHold record for an audit identity.

        Returns the record dict if found, or None if no hold was ever placed.

        `consistent_read` (Legal-Hold Correction A1.LH3; Technical Design
        Section 19.5.4): defaults to False (DynamoDB's own default,
        eventually consistent) so every existing caller (HoldTransitions,
        RetentionService, HoldCoordinatedTransactionRunner's own DynamoDB-leg
        read) is behaviorally unchanged -- Section 19.5.4 confirms
        eventually-consistent reads are harmless on the DynamoDB write path
        specifically, because TransactWriteItems' own ConditionCheck
        re-verifies the actual current hold_version at commit time regardless
        of how stale the preceding read was. Pass `consistent_read=True`
        only for a write path with no such transactional backstop -- today,
        exclusively the S3 raw-evidence write path
        (packages/storage/s3_client.py::write_raw_results_once), per Section
        19.5.4's explicit, narrowly-scoped requirement. When False (the
        default), `ConsistentRead` is omitted from the underlying GetItem
        call entirely rather than explicitly passed as False, so the exact
        kwargs sent are byte-identical to pre-A1.LH3 behavior.
        """
        key = self.legal_hold_key(client_id, audit_id)
        if consistent_read:
            return self._get_item(key, consistent_read=True)
        return self._get_item(key)

    def get_legal_hold_event(
        self, client_id: str, audit_id: str, hold_id: str, hold_version: int
    ) -> dict[str, Any] | None:
        """Read a single LegalHoldEvent record by its (hold_id, hold_version).

        Returns the record dict if found, or None if absent.
        """
        return self._get_item(
            self.legal_hold_event_key(client_id, audit_id, hold_id, hold_version)
        )

    # ------------------------------------------------------------------
    # Writes — LegalHoldEvent (immutable log)
    # ------------------------------------------------------------------

    def write_hold_event(
        self,
        client_id: str,
        audit_id: str,
        hold_id: str,
        hold_version: int,
        action: str,
        actor: str,
        reason: str,
        timestamp: str,
        s3_versions_retagged_count: int,
        dynamodb_items_updated_count: int,
        marker_s3_key: str | None = None,
        marker_status: str = MARKER_STATUS_PENDING,
        marker_confirmed_last_modified: str | None = None,
    ) -> None:
        """Write a new LegalHoldEvent record (conditional, write-once).

        hold_version is a required per-transition SK discriminator (ADR
        Non-Negotiable Invariant 25) — see legal_hold_event_key(). Every
        PLACE and every RELEASE of a given audit identity must pass a
        distinct hold_version (ADR Invariant 12's monotonicity is what makes
        this write-once-per-key guarantee hold across an entire episode,
        including a PLACE/RELEASE pair sharing one hold_id, per Invariant 21).

        marker_s3_key/marker_status/marker_confirmed_last_modified are
        additive plumbing for the S3 canary-marker mechanism (Technical
        Design Section 19.5.1; Legal-Hold Correction B2, not part of B1).
        Callers in B1's own scope never pass a value other than the
        defaults.

        Raises:
            AssertionError: If the computed SK is not a retention SK.
            ConditionalWriteError: If an event with this
                (hold_id, hold_version) already exists.
            StorageError: On DynamoDB client or request failure.
        """
        key = self.legal_hold_event_key(client_id, audit_id, hold_id, hold_version)
        _assert_retention_sk(key["SK"])
        item = {
            **key,
            "record_type": LEGAL_HOLD_EVENT_RECORD_TYPE,
            "hold_id": hold_id,
            "hold_version": hold_version,
            "client_id": client_id,
            "audit_id": audit_id,
            "action": action,
            "actor": actor,
            "reason": reason,
            "timestamp": timestamp,
            "s3_versions_retagged_count": s3_versions_retagged_count,
            "dynamodb_items_updated_count": dynamodb_items_updated_count,
            "marker_s3_key": marker_s3_key,
            "marker_status": marker_status,
            "marker_confirmed_last_modified": marker_confirmed_last_modified,
        }
        self._put_once(item)

    def update_hold_event_marker_fields(
        self,
        client_id: str,
        audit_id: str,
        hold_id: str,
        hold_version: int,
        marker_s3_key: str | None,
        marker_status: str,
        marker_confirmed_last_modified: str | None,
    ) -> None:
        """Update only the marker_s3_key/marker_status/
        marker_confirmed_last_modified fields on an already-written
        LegalHoldEvent record (Legal-Hold Correction B2; Technical Design
        Section 19.5.3 steps 2-3, Section 19.5.6; ADR Non-Negotiable
        Invariant 24).

        write_hold_event() is write-once (conditional PutItem,
        attribute_not_exists(PK) AND attribute_not_exists(SK)) -- a given
        transition's LegalHoldEvent is written exactly once, at the moment
        HoldTransitions decides on a genuine new episode or a resumption
        (hold_transitions.py). The canary marker's own establishment and
        confirmation happens afterward, as a separate step (RetentionService,
        Technical Design Section 19.5.3), so calling write_hold_event() again
        to record that outcome would hit its own conditional-write guard and
        raise ConditionalWriteError. This dedicated, narrowly-scoped
        UpdateItem-based method is how that later step durably records the
        marker outcome without re-writing (and thereby risking a spurious
        failure against) the event's own write-once fields
        (action/actor/reason/timestamp/counts) — mirroring the discipline
        CustodySweepClient's _assert_custody_field_only_update() enforces
        for its own single-attribute-only UpdateItem calls, applied here to
        exactly these three marker fields and no others.

        Callers pass marker_status=CONFIRMED with the verified
        marker_confirmed_last_modified once the marker's identity and
        LastModified have actually been confirmed (never merely "the
        PutObject call didn't throw"), or marker_status=FAILED with
        marker_confirmed_last_modified=None on marker-establishment failure
        (Technical Design Section 19.5.6). Once CONFIRMED, ADR Invariant 24
        requires this value be treated as immutable by every caller — this
        method itself does not enforce that (RetentionService's own
        marker_status-gated call pattern is where that invariant is
        enforced, per Technical Design Section 19.5.3 step 2: it must never
        call this method again for a transition already read back as
        CONFIRMED).

        Raises:
            AssertionError: If the computed SK is not a retention SK.
            StorageError: On DynamoDB failure.
        """
        key = self.legal_hold_event_key(client_id, audit_id, hold_id, hold_version)
        _assert_retention_sk(key["SK"])
        names = {
            "#mk": "marker_s3_key",
            "#ms": "marker_status",
            "#mlm": "marker_confirmed_last_modified",
        }
        values = {
            ":mk": marker_s3_key,
            ":ms": marker_status,
            ":mlm": marker_confirmed_last_modified,
        }
        self._call(
            "update_item",
            Key=key,
            UpdateExpression="SET #mk = :mk, #ms = :ms, #mlm = :mlm",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

    # ------------------------------------------------------------------
    # Writes — LegalHold (current-state record)
    # ------------------------------------------------------------------

    def upsert_hold(
        self,
        client_id: str,
        audit_id: str,
        status: str,
        hold_id: str,
        hold_version: int,
        sweep_status: str,
        placed_at: str,
        placed_by: str,
        reason: str,
        hold_count: int,
        released_at: str | None = None,
        released_by: str | None = None,
        marker_s3_key: str | None = None,
        marker_confirmed_last_modified: str | None = None,
    ) -> None:
        """Write or update the authoritative LegalHold current-state record.

        PutItem overwrites any existing record for the same audit identity —
        analogous to CertificationMetadata's write_cert_metadata_complete in
        audit_platform_integrity/repository.py. This remains a plain,
        unconditional PutItem (Technical Design Section 19.1's "effective
        ordering" reasoning does not require a condition here — the
        TransactWriteItems ConditionCheck mechanism, Technical Design Section
        19.4, protects *other* governed records' writes against this record's
        hold_version, not this record's own PLACE/RELEASE transition).

        hold_version / sweep_status (ADR Non-Negotiable Invariant 12; ADR
        Decision 9; Technical Design Section 19.1) are now required, explicit
        parameters — every call must state them, with no default, so a
        caller cannot accidentally omit incrementing hold_version or resetting
        sweep_status on a transition. The caller (hold_transitions.py's
        HoldTransitions, or eventually RetentionService) is responsible for
        computing hold_version/hold_count and deciding
        placed_at/released_at semantics across cycles.

        marker_s3_key/marker_confirmed_last_modified are additive plumbing
        for the current transition's S3 canary marker (Technical Design
        Section 19.5.1; Legal-Hold Correction B2, not part of B1). Callers in
        B1's own scope never pass a non-None value.

        Raises:
            AssertionError: If the computed SK is not a retention SK.
            StorageError: On DynamoDB failure.
        """
        key = self.legal_hold_key(client_id, audit_id)
        _assert_retention_sk(key["SK"])
        item = {
            **key,
            "record_type": LEGAL_HOLD_RECORD_TYPE,
            "client_id": client_id,
            "audit_id": audit_id,
            "status": status,
            "hold_id": hold_id,
            "hold_version": hold_version,
            "sweep_status": sweep_status,
            "placed_at": placed_at,
            "placed_by": placed_by,
            "reason": reason,
            "hold_count": hold_count,
            "released_at": released_at,
            "released_by": released_by,
            "marker_s3_key": marker_s3_key,
            "marker_confirmed_last_modified": marker_confirmed_last_modified,
        }
        self._put_item(item)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_item(
        self, key: dict[str, str], *, consistent_read: bool = False
    ) -> dict[str, Any] | None:
        if consistent_read:
            response = self._call("get_item", Key=key, ConsistentRead=True)
        else:
            response = self._call("get_item", Key=key)
        return response.get("Item")

    def _put_once(self, item: dict[str, Any]) -> None:
        try:
            self._call(
                "put_item",
                preserve_client_error_codes={"ConditionalCheckFailedException"},
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConditionalWriteError() from exc
            raise

    def _put_item(self, item: dict[str, Any]) -> None:
        self._call("put_item", Item=item)

    def _call(
        self,
        method_name: str,
        *,
        preserve_client_error_codes: set[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        method = getattr(self.dynamodb_client, method_name)
        try:
            return decode_dynamodb_response(
                method(TableName=self.table_name, **encode_dynamodb_call_kwargs(kwargs))
            )
        except TypeError:
            return decode_dynamodb_response(method(**kwargs))
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in (
                preserve_client_error_codes or set()
            ):
                raise
            raise storage_error_from_dynamodb_client_error(
                exc, operation=method_name
            ) from exc
        except Exception as exc:
            raise storage_error_from_dynamodb_request_error(
                exc, operation=method_name
            ) from exc
