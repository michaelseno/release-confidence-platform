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
        self, client_id: str, audit_id: str, hold_id: str
    ) -> dict[str, str]:
        """Build the PK/SK key dict for a LegalHoldEvent record."""
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#LEGALHOLD#{hold_id}",
        }

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_legal_hold(self, client_id: str, audit_id: str) -> dict[str, Any] | None:
        """Read the current-state LegalHold record for an audit identity.

        Returns the record dict if found, or None if no hold was ever placed.
        """
        return self._get_item(self.legal_hold_key(client_id, audit_id))

    def get_legal_hold_event(
        self, client_id: str, audit_id: str, hold_id: str
    ) -> dict[str, Any] | None:
        """Read a single LegalHoldEvent record by its hold_id.

        Returns the record dict if found, or None if absent.
        """
        return self._get_item(self.legal_hold_event_key(client_id, audit_id, hold_id))

    # ------------------------------------------------------------------
    # Writes — LegalHoldEvent (immutable log)
    # ------------------------------------------------------------------

    def write_hold_event(
        self,
        client_id: str,
        audit_id: str,
        hold_id: str,
        action: str,
        actor: str,
        reason: str,
        timestamp: str,
        s3_versions_retagged_count: int,
        dynamodb_items_updated_count: int,
    ) -> None:
        """Write a new LegalHoldEvent record (conditional, write-once).

        Raises:
            AssertionError: If the computed SK is not a retention SK.
            ConditionalWriteError: If an event with this hold_id already exists.
            StorageError: On DynamoDB client or request failure.
        """
        key = self.legal_hold_event_key(client_id, audit_id, hold_id)
        _assert_retention_sk(key["SK"])
        item = {
            **key,
            "record_type": LEGAL_HOLD_EVENT_RECORD_TYPE,
            "hold_id": hold_id,
            "client_id": client_id,
            "audit_id": audit_id,
            "action": action,
            "actor": actor,
            "reason": reason,
            "timestamp": timestamp,
            "s3_versions_retagged_count": s3_versions_retagged_count,
            "dynamodb_items_updated_count": dynamodb_items_updated_count,
        }
        self._put_once(item)

    # ------------------------------------------------------------------
    # Writes — LegalHold (current-state record)
    # ------------------------------------------------------------------

    def upsert_hold(
        self,
        client_id: str,
        audit_id: str,
        status: str,
        hold_id: str,
        placed_at: str,
        placed_by: str,
        reason: str,
        hold_count: int,
        released_at: str | None = None,
        released_by: str | None = None,
    ) -> None:
        """Write or update the authoritative LegalHold current-state record.

        PutItem overwrites any existing record for the same audit identity —
        analogous to CertificationMetadata's write_cert_metadata_complete in
        audit_platform_integrity/repository.py. The first placement and every
        subsequent place/release cycle both go through this same method; the
        caller (RetentionService, out of scope for A1.1) is responsible for
        computing hold_count and deciding placed_at/released_at semantics
        across cycles.

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
            "placed_at": placed_at,
            "placed_by": placed_by,
            "reason": reason,
            "hold_count": hold_count,
            "released_at": released_at,
            "released_by": released_by,
        }
        self._put_item(item)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_item(self, key: dict[str, str]) -> dict[str, Any] | None:
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
