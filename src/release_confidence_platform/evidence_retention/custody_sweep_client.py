"""S3 legal-hold tagging sweep and cross-phase ttl_disposal_at removal /
restoration for evidence_retention Workstream A1.2/A1.3.

CustodySweepClient is the second, differently-scoped access path
RetentionService needs alongside HoldRepository (Technical Design Section
5.2/6, amended post-A1.1 to name this component). It performs two
operations, neither of which is SK-guarded in the sense HoldRepository /
DisposalRepository are, because both operations must legitimately reach SKs
outside any single namespace:

  (a) The S3 per-version legal-hold tagging sweep across every
      evidence-class prefix under an audit identity (ListObjectVersions /
      GetObjectTagging / PutObjectTagging only -- this class has no
      put_object or delete_object method, so it cannot write or delete
      evidence content by construction, not merely by IAM restriction).
  (b) The cross-phase DynamoDB ttl_disposal_at attribute removal (on legal
      hold placement) and restoration (on release), reached via Query
      (PK=CLIENT#{client_id}, SK begins_with AUDIT#{audit_id}) + per-item
      UpdateItem against *other phases'* records (RunMetadata,
      AggregationJob/aggregate records, IntelligenceMetadata,
      ReportMetadata, CertificationMetadata, etc.).

Safety boundary, enforced by operation shape rather than SK shape:
_assert_custody_field_only_update() is called before every UpdateItem and
raises AssertionError if the target SK contains #LEGALHOLD# or #DISPOSAL#,
or if the UpdateExpression (via its ExpressionAttributeNames placeholders)
would touch any attribute other than ttl_disposal_at. Those two SK
namespaces remain exclusively HoldRepository's and DisposalRepository's
respectively (see hold_repository.py::_assert_retention_sk and
disposal_repository.py::_assert_disposal_sk) -- CustodySweepClient must
never touch them either, even though it may legitimately touch every other
phase's SK. An SK-shape guard like the other two classes' would be the
wrong tool here and would incorrectly reject this class's normal operation
-- that mismatch is exactly what the Technical Design Section 5.2 amendment
corrected (see the module docstring history in hold_repository.py).

This class must never gain a put_object, delete_object, PutItem, or
DeleteItem-capable method. The internal DynamoDB and S3 call-dispatch
helpers below are additionally restricted to a fixed allowlist of method
names -- a second, code-level enforcement layer beyond "the method doesn't
exist as a named attribute."

Backlog migration (bringing pre-Workstream-A evidence under enforcement) is
explicitly out of scope for this class -- see companion ADR Decision 6 /
Technical Design Section 15/17. No method here scans or migrates evidence
outside an explicit (client_id, audit_id) legal-hold operation; there is no
"sweep everything" entry point.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.constants import (
    CUSTODY_EXPIRES_AT_ATTRIBUTE,
    DISPOSAL_SK_MARKER,
    LEGAL_HOLD_TAG_KEY,
    LEGAL_HOLD_TAG_VALUE_FALSE,
    LEGAL_HOLD_TAG_VALUE_TRUE,
    LEGALHOLD_SK_MARKER,
    S3_EVIDENCE_CLASS_PREFIXES,
    TTL_DISPOSAL_AT_ATTRIBUTE,
)
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    storage_error_from_dynamodb_client_error,
    storage_error_from_dynamodb_request_error,
)

# Namespaces exclusively owned by HoldRepository (#LEGALHOLD#) and
# DisposalRepository (#DISPOSAL#). CustodySweepClient must never write to
# either, even though it legitimately writes to every other SK namespace
# under an audit identity's partition.
_PROHIBITED_SK_MARKERS = (LEGALHOLD_SK_MARKER, DISPOSAL_SK_MARKER)

# The only DynamoDB attribute CustodySweepClient's UpdateItem calls may touch.
_ALLOWED_CUSTODY_ATTRIBUTE = TTL_DISPOSAL_AT_ATTRIBUTE

# Structural allowlists (Technical Design Section 5.2/12): this class has no
# put_object, delete_object, PutItem, or DeleteItem capability. These
# allowlists are a second, code-level enforcement layer beyond "the method
# doesn't exist" -- they block the internal dispatch helpers themselves from
# ever being asked to perform anything outside this class's read/tag/
# update-one-attribute operation shape, even by a future code change to this
# same file.
_ALLOWED_DYNAMODB_METHODS = frozenset({"query", "update_item"})
_ALLOWED_S3_METHODS = frozenset(
    {"list_object_versions", "get_object_tagging", "put_object_tagging"}
)


def _assert_custody_field_only_update(
    sk: str, expression_attribute_names: dict[str, str]
) -> None:
    """Assert an UpdateItem call is a ttl_disposal_at-only update that never
    reaches the #LEGALHOLD# or #DISPOSAL# SK namespaces.

    Raises AssertionError if the target SK contains either prohibited
    namespace marker, or if the UpdateExpression -- inspected via its
    ExpressionAttributeNames placeholder values, which are the actual
    attribute names the expression will touch -- names any attribute other
    than ttl_disposal_at. This is a programming-error guard, not a
    user-facing validation, modeled on _assert_retention_sk() /
    _assert_disposal_sk() but guarding by operation shape rather than SK
    shape (see module docstring for why an SK-shape guard is the wrong tool
    for this class).
    """
    if any(marker in sk for marker in _PROHIBITED_SK_MARKERS):
        raise AssertionError(
            f"CustodySweepClient update attempted against prohibited SK "
            f"namespace: {sk!r}. CustodySweepClient must never write to "
            "#LEGALHOLD# or #DISPOSAL# SK patterns; those namespaces are "
            "exclusively owned by HoldRepository and DisposalRepository "
            "respectively."
        )
    touched_attributes = set(expression_attribute_names.values())
    if touched_attributes != {_ALLOWED_CUSTODY_ATTRIBUTE}:
        raise AssertionError(
            f"CustodySweepClient UpdateItem attempted to touch attribute(s) "
            f"{sorted(touched_attributes)!r}; only "
            f"{_ALLOWED_CUSTODY_ATTRIBUTE!r} may be touched by this class's "
            "UpdateItem calls."
        )


class CustodySweepClient:
    """S3 legal-hold tagging sweep + cross-phase ttl_disposal_at mutation.

    Not a "repository" in the SK-guarded sense of HoldRepository /
    DisposalRepository -- see module docstring. RetentionService (A1.2/A1.3,
    out of scope for this class itself) is the intended caller for both
    place_legal_hold() and release_legal_hold() orchestration.
    """

    def __init__(
        self,
        table_name: str,
        dynamodb_client: Any,
        bucket_name: str,
        s3_client: Any,
    ) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client
        self.bucket_name = bucket_name
        self.s3_client = s3_client

    # ------------------------------------------------------------------
    # Cross-phase DynamoDB ttl_disposal_at removal / restoration
    # ------------------------------------------------------------------

    def remove_ttl_disposal_at(self, client_id: str, audit_id: str) -> int:
        """Remove ttl_disposal_at from every other-phase item under this
        audit identity that currently carries it (legal hold placement).

        Items with no ttl_disposal_at attribute are skipped (nothing to
        remove); this makes the operation safely re-invocable (Technical
        Design Section 10.5 -- place/release must be safely re-runnable to
        resume/complete an interrupted sweep).

        Returns the number of items updated.

        Raises:
            AssertionError: Via _assert_custody_field_only_update(), if a
                queried item's SK is #LEGALHOLD#/#DISPOSAL#-shaped (should
                never occur -- those record types never carry
                ttl_disposal_at per ADR Non-Negotiable Invariant 1).
            StorageError: On DynamoDB client or request failure.
        """
        updated = 0
        for item in self._query_audit_items(client_id, audit_id):
            sk = item.get("SK", "")
            if TTL_DISPOSAL_AT_ATTRIBUTE not in item:
                continue
            self._remove_ttl_disposal_at_item(client_id, sk)
            updated += 1
        return updated

    def restore_ttl_disposal_at(
        self, client_id: str, audit_id: str, now_epoch_seconds: int
    ) -> int:
        """Restore ttl_disposal_at = MAX(custody_expires_at, now) on every
        other-phase item under this audit identity that has a recorded
        custody_expires_at but no current ttl_disposal_at (legal hold
        release).

        Clamping to now_epoch_seconds ensures already-elapsed custody
        becomes immediately eligible for disposal rather than silently
        skipped (AC-A1-4), and custody_expires_at itself is never mutated
        (Technical Design Section 10.3 -- only ttl_disposal_at is mutated by
        hold state changes).

        Items that already carry ttl_disposal_at are skipped (nothing to
        restore -- not currently held, or already restored by a prior
        invocation of this same operation), making the operation safely
        re-invocable.

        Returns the number of items updated.

        Raises:
            AssertionError: Via _assert_custody_field_only_update().
            StorageError: On DynamoDB client or request failure.
        """
        updated = 0
        for item in self._query_audit_items(client_id, audit_id):
            sk = item.get("SK", "")
            custody_expires_at = item.get(CUSTODY_EXPIRES_AT_ATTRIBUTE)
            if custody_expires_at is None:
                continue
            if TTL_DISPOSAL_AT_ATTRIBUTE in item:
                continue
            restored_value = max(custody_expires_at, now_epoch_seconds)
            self._restore_ttl_disposal_at_item(client_id, sk, restored_value)
            updated += 1
        return updated

    def _query_audit_items(self, client_id: str, audit_id: str) -> Iterator[dict[str, Any]]:
        """Query every item under PK=CLIENT#{client_id}, SK begins_with
        AUDIT#{audit_id}, paginating via LastEvaluatedKey.

        This necessarily returns items across every phase's SK shape under
        the audit identity's partition (RunMetadata, AggregationJob/
        aggregate records, IntelligenceMetadata, ReportMetadata,
        CertificationMetadata, LegalHold/LegalHoldEvent, DisposalRecord) --
        the caller (remove_ttl_disposal_at / restore_ttl_disposal_at) is
        responsible for skipping items that are not eligible, and
        _assert_custody_field_only_update() is the final guard before any
        write.
        """
        pk = f"CLIENT#{client_id}"
        sk_prefix = f"AUDIT#{audit_id}"
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
            "ExpressionAttributeValues": {":pk": pk, ":sk_prefix": sk_prefix},
        }
        while True:
            response = self._call_dynamodb("query", **kwargs)
            yield from response.get("Items", [])
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                break
            kwargs["ExclusiveStartKey"] = last_key

    def _remove_ttl_disposal_at_item(self, client_id: str, sk: str) -> None:
        names = {"#ttl": TTL_DISPOSAL_AT_ATTRIBUTE}
        _assert_custody_field_only_update(sk, names)
        key = {"PK": f"CLIENT#{client_id}", "SK": sk}
        self._call_dynamodb(
            "update_item",
            Key=key,
            UpdateExpression="REMOVE #ttl",
            ExpressionAttributeNames=names,
        )

    def _restore_ttl_disposal_at_item(self, client_id: str, sk: str, value: int) -> None:
        names = {"#ttl": TTL_DISPOSAL_AT_ATTRIBUTE}
        _assert_custody_field_only_update(sk, names)
        key = {"PK": f"CLIENT#{client_id}", "SK": sk}
        self._call_dynamodb(
            "update_item",
            Key=key,
            UpdateExpression="SET #ttl = :v",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues={":v": value},
        )

    # ------------------------------------------------------------------
    # S3 per-version legal-hold tagging sweep
    # ------------------------------------------------------------------

    def retag_s3_versions(self, client_id: str, audit_id: str, legal_hold: bool) -> int:
        """Set rcp-legal-hold={true|false} on every extant S3 object version
        under this audit identity's key prefixes, across all evidence-class
        prefixes (raw-results/, intelligence/, reports/, integrity/).

        Every other tag already present on a version (in particular
        rcp-evidence-class) is preserved -- this is a tag-merge, not a
        tag-replace, since PutObjectTagging replaces a version's entire tag
        set. Delete markers (which carry no content and cannot be tagged)
        are skipped.

        Returns the number of object versions retagged.

        Raises:
            StorageError: On any S3 API failure.
        """
        new_value = LEGAL_HOLD_TAG_VALUE_TRUE if legal_hold else LEGAL_HOLD_TAG_VALUE_FALSE
        retagged = 0
        for prefix_root in S3_EVIDENCE_CLASS_PREFIXES:
            prefix = f"{prefix_root}/{client_id}/{audit_id}/"
            for key, version_id in self._list_object_versions(prefix):
                self._retag_object_version(key, version_id, new_value)
                retagged += 1
        return retagged

    def _list_object_versions(self, prefix: str) -> Iterator[tuple[str, str]]:
        kwargs: dict[str, Any] = {"Bucket": self.bucket_name, "Prefix": prefix}
        while True:
            response = self._call_s3("list_object_versions", **kwargs)
            for version in response.get("Versions", []) or []:
                key = version.get("Key")
                version_id = version.get("VersionId")
                if key is not None and version_id is not None:
                    yield key, version_id
            if not response.get("IsTruncated"):
                break
            next_key_marker = response.get("NextKeyMarker")
            if next_key_marker is None:
                break
            kwargs["KeyMarker"] = next_key_marker
            next_version_marker = response.get("NextVersionIdMarker")
            if next_version_marker is not None:
                kwargs["VersionIdMarker"] = next_version_marker

    def _retag_object_version(self, key: str, version_id: str, new_legal_hold_value: str) -> None:
        existing = self._call_s3(
            "get_object_tagging", Bucket=self.bucket_name, Key=key, VersionId=version_id
        )
        merged_tags = {tag["Key"]: tag["Value"] for tag in existing.get("TagSet", []) or []}
        merged_tags[LEGAL_HOLD_TAG_KEY] = new_legal_hold_value
        new_tag_set = [
            {"Key": tag_key, "Value": tag_value} for tag_key, tag_value in merged_tags.items()
        ]
        self._call_s3(
            "put_object_tagging",
            Bucket=self.bucket_name,
            Key=key,
            VersionId=version_id,
            Tagging={"TagSet": new_tag_set},
        )

    # ------------------------------------------------------------------
    # Internal dispatch helpers (allowlisted -- see module docstring)
    # ------------------------------------------------------------------

    def _call_dynamodb(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
        if method_name not in _ALLOWED_DYNAMODB_METHODS:
            raise AssertionError(
                f"CustodySweepClient attempted disallowed DynamoDB operation "
                f"{method_name!r}; only {sorted(_ALLOWED_DYNAMODB_METHODS)!r} "
                "are permitted on this class."
            )
        method = getattr(self.dynamodb_client, method_name)
        try:
            return decode_dynamodb_response(
                method(TableName=self.table_name, **encode_dynamodb_call_kwargs(kwargs))
            )
        except TypeError:
            return decode_dynamodb_response(method(**kwargs))
        except ClientError as exc:
            raise storage_error_from_dynamodb_client_error(exc, operation=method_name) from exc
        except Exception as exc:
            raise storage_error_from_dynamodb_request_error(exc, operation=method_name) from exc

    def _call_s3(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
        if method_name not in _ALLOWED_S3_METHODS:
            raise AssertionError(
                f"CustodySweepClient attempted disallowed S3 operation "
                f"{method_name!r}; only {sorted(_ALLOWED_S3_METHODS)!r} are "
                "permitted on this class."
            )
        method = getattr(self.s3_client, method_name)
        try:
            return method(**kwargs)
        except ClientError as exc:
            raise StorageError(
                f"CustodySweepClient S3 {method_name} failed: {exc}",
                "S3_CUSTODY_SWEEP_FAILURE",
            ) from exc
        except Exception as exc:
            raise StorageError(
                f"CustodySweepClient S3 {method_name} failed: {exc}",
                "S3_CUSTODY_SWEEP_FAILURE",
            ) from exc
