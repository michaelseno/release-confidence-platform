"""DynamoDB repository for evidence_retention disposal records (Workstream A1.1).

Single responsibility: write (and read, for testability/idempotency-checking)
access to DisposalRecord only. Targets exclusively the #DISPOSAL# SK
namespace. Used exclusively by the future evidenceDisposalRecorder Lambda
handler (disposal_recorder.py, out of scope for A1.1) — RetentionService
never imports this class (ADR Non-Negotiable Invariant 6).

Sort key write prohibition: every write method calls _assert_disposal_sk()
before the DynamoDB call. This is the symmetric counterpart to
_assert_retention_sk() in hold_repository.py, both modeled directly on
_assert_phase7_sk() in audit_platform_integrity/repository.py:49. The two
guards are mutually exclusive by design: a #LEGALHOLD#-shaped SK is rejected
here, and a #DISPOSAL#-shaped SK is rejected by _assert_retention_sk().
"""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.constants import (
    DISPOSAL_RECORD_RECORD_TYPE,
    DISPOSAL_SK_MARKER,
    LEGALHOLD_SK_MARKER,
)
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    storage_error_from_dynamodb_client_error,
    storage_error_from_dynamodb_request_error,
)

# Disposal-exclusive SK segment marker. Any write targeting this pattern is permitted.
_DISPOSAL_SK_MARKERS = (DISPOSAL_SK_MARKER,)

# Exclusively non-disposal record type markers that must never appear in a
# DisposalRepository write path.
_PROHIBITED_SK_MARKERS = (LEGALHOLD_SK_MARKER,)


def _assert_disposal_sk(sk: str) -> None:
    """Assert that an SK is in the #DISPOSAL# namespace before any write.

    Raises AssertionError if the SK does not contain the disposal marker, or
    if it contains the retention (legal hold) marker. This is a
    programming-error guard, not a user-facing validation.
    """
    has_disposal_marker = any(marker in sk for marker in _DISPOSAL_SK_MARKERS)
    has_prohibited = any(marker in sk for marker in _PROHIBITED_SK_MARKERS)
    if not has_disposal_marker or has_prohibited:
        raise AssertionError(
            f"Disposal write attempted to prohibited SK namespace: {sk!r}. "
            f"DisposalRepository writes must target only {DISPOSAL_SK_MARKER!r} "
            "SK patterns."
        )


class ConditionalWriteError(StorageError):
    def __init__(self, message: str = "Conditional write failed"):
        super().__init__(message, "CONDITIONAL_WRITE_FAILED")


class DisposalRepository:
    """DynamoDB read/write access for DisposalRecord only."""

    def __init__(self, table_name: str, dynamodb_client: Any) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client

    # ------------------------------------------------------------------
    # Key construction helpers
    # ------------------------------------------------------------------

    def disposal_record_key(
        self, client_id: str, audit_id: str, disposal_id: str
    ) -> dict[str, str]:
        """Build the PK/SK key dict for a DisposalRecord."""
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#DISPOSAL#{disposal_id}",
        }

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_disposal_record(
        self,
        client_id: str,
        audit_id: str,
        disposal_id: str,
        *,
        consistent_read: bool = False,
    ) -> dict[str, Any] | None:
        """Read a single DisposalRecord by its disposal_id.

        Returns the record dict if found, or None if absent.

        `consistent_read` (ADR Decision 13, Non-Negotiable Invariant 39;
        Technical Design Section 22.3): defaults to False (DynamoDB's own
        default, eventually consistent) so every existing caller remains
        behaviorally unchanged -- mirrors HoldRepository.get_legal_hold's
        exact pattern. `evidenceDisposalRecorder`'s duplicate-conflict
        verification (Section 22.3) is the first caller requiring
        `consistent_read=True`: a `ConditionalCheckFailedException` read-back
        may immediately follow a conflicting write by another concurrent
        invocation, and an eventually-consistent read has no transactional
        backstop to catch staleness on this path. When False (the default),
        `ConsistentRead` is omitted from the underlying GetItem call entirely
        rather than explicitly passed as False.
        """
        key = self.disposal_record_key(client_id, audit_id, disposal_id)
        if consistent_read:
            return self._get_item(key, consistent_read=True)
        return self._get_item(key)

    # ------------------------------------------------------------------
    # Writes — DisposalRecord (write-once, append-only)
    # ------------------------------------------------------------------

    def put_disposal_record(
        self,
        client_id: str,
        audit_id: str,
        disposal_id: str,
        evidence_class: str,
        disposal_mechanism: str,
        disposed_identity_ref: str,
        disposed_at: str,
        recorded_at: str,
        disposal_id_scheme: str,
        source_kind: str,
        source_stream_identity: str | None = None,
        source_event_id: str | None = None,
        source_bucket: str | None = None,
        source_object_key: str | None = None,
        source_object_version_id: str | None = None,
        source_created_at: str | None = None,
        custody_period_days_applied: int | None = None,
    ) -> None:
        """Write a new DisposalRecord (conditional, write-once).

        The conditional put (attribute_not_exists(PK) AND attribute_not_exists(SK))
        makes redelivery of at-least-once DynamoDB Streams / EventBridge events
        idempotent, matching the existing _put_once pattern in
        audit_platform_integrity/repository.py and
        deterministic_reporting/repository.py per Technical Design Section 13.

        Never sets a ttl_disposal_at attribute on the written item (ADR
        Non-Negotiable Invariant 1).

        `disposal_id_scheme`, `source_kind`, and the five source-identity
        fields (ADR Non-Negotiable Invariant 49; Technical Design Section
        7.3/22.2/22.3, A1.4a implementation scope) are persisted verbatim --
        the identical raw values `disposal_recorder.py` hashed into
        `disposal_id` -- so Section 22.3's duplicate-conflict verification
        can compare source identity directly without re-deriving it. This
        method does not itself enforce the source-kind-conditional field
        shape (which of the five fields must be present/absent for a given
        `source_kind`) -- that is `DisposalRecord`'s own model-level
        validator (models.py); callers are expected to construct a valid
        `DisposalRecord` first and pass its fields through.

        Raises:
            AssertionError: If the computed SK is not a disposal SK.
            ConditionalWriteError: If a record with this disposal_id already exists.
            StorageError: On DynamoDB client or request failure.
        """
        key = self.disposal_record_key(client_id, audit_id, disposal_id)
        _assert_disposal_sk(key["SK"])
        item = {
            **key,
            "record_type": DISPOSAL_RECORD_RECORD_TYPE,
            "disposal_id": disposal_id,
            "disposal_id_scheme": disposal_id_scheme,
            "source_kind": source_kind,
            "client_id": client_id,
            "audit_id": audit_id,
            "evidence_class": evidence_class,
            "disposal_mechanism": disposal_mechanism,
            "disposed_identity_ref": disposed_identity_ref,
            "source_stream_identity": source_stream_identity,
            "source_event_id": source_event_id,
            "source_bucket": source_bucket,
            "source_object_key": source_object_key,
            "source_object_version_id": source_object_version_id,
            "disposed_at": disposed_at,
            "recorded_at": recorded_at,
            "source_created_at": source_created_at,
            "custody_period_days_applied": custody_period_days_applied,
        }
        self._put_once(item)

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
