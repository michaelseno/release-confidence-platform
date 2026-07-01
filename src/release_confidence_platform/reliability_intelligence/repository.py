"""DynamoDB repository for Phase 5 Reliability Intelligence.

Two responsibilities:
  (a) Phase 4 consumer reads — read-only, never writes to Phase 4 SK namespaces.
  (b) Phase 5 writes — targets exclusively Phase 5 SK namespaces (#INTJOB# and #INTEL#).

Phase 4 sort key namespace write prohibition is unconditional. All write methods in this
class target only:
  - AUDIT#{audit_id}#INTJOB#{intelligence_job_id}
  - AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{agg_ver}#INTEL#{intel_ver}#META

Any write to a Phase 4 sort key namespace from this class is a programming error. This
invariant is enforced by the SK assertion in every write method and covered by
tests/unit/reliability_intelligence/test_engine_no_phase4_mutation.py.
"""

from __future__ import annotations

from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.sanitization.sanitizer import sanitize
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    storage_error_from_dynamodb_client_error,
    storage_error_from_dynamodb_request_error,
)

# Phase 5-exclusive SK segment markers. Any write targeting these patterns is permitted.
_PHASE5_SK_MARKERS = ("#INTJOB#", "#INTEL#")

# Phase 4-exclusive SK segments that must never appear in Phase 5 write paths.
_PHASE4_PROHIBITED_SK_MARKERS = (
    "#AGGJOB#",
    "#EXECUTION_ID",
    "#ENDPOINT#",
    "#LINEAGE#",
    "#RUN#",
    "#SET",
    "#AUDIT",
    "#FAILURE_CLASSIFICATION",
)


def _assert_phase5_sk(sk: str) -> None:
    """Assert that an SK is in Phase 5 namespace before any write.

    Raises AssertionError if the SK does not contain a Phase 5 marker, or if it
    contains any Phase 4 prohibited marker. This is a programming-error guard,
    not a user-facing validation.
    """
    has_phase5_marker = any(marker in sk for marker in _PHASE5_SK_MARKERS)
    has_phase4_marker = any(marker in sk for marker in _PHASE4_PROHIBITED_SK_MARKERS)
    if not has_phase5_marker or has_phase4_marker:
        raise AssertionError(
            f"Phase 5 write attempted to prohibited SK namespace: {sk!r}. "
            "Phase 5 writes must target only #INTJOB# or #INTEL# SK patterns."
        )


class ConditionalWriteError(StorageError):
    def __init__(self, message: str = "Conditional write failed"):
        super().__init__(message, "CONDITIONAL_WRITE_FAILED")


class IntelligenceRepository:
    """Phase 4 consumer reads and Phase 5 artifact writes for Reliability Intelligence."""

    def __init__(self, table_name: str, dynamodb_client: Any) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client

    # ------------------------------------------------------------------
    # Key construction helpers
    # ------------------------------------------------------------------

    def intelligence_job_keys(
        self, client_id: str, audit_id: str, job_id: str
    ) -> dict[str, str]:
        """Build PK/SK for an IntelligenceJob record."""
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#INTJOB#{job_id}",
        }

    def intelligence_metadata_keys(
        self,
        client_id: str,
        audit_id: str,
        exec_id: str,
        cfg: str,
        agg_ver: str,
        intel_ver: str,
    ) -> dict[str, str]:
        """Build PK/SK for an IntelligenceMetadata record."""
        return {
            "PK": f"CLIENT#{client_id}",
            "SK": (
                f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}"
                f"#AGG#{agg_ver}#INTEL#{intel_ver}#META"
            ),
        }

    # ------------------------------------------------------------------
    # Phase 4 consumer reads (read-only; never writes to Phase 4 records)
    # ------------------------------------------------------------------

    def get_aggregate_set_completion(
        self,
        client_id: str,
        audit_id: str,
        exec_id: str,
        cfg: str,
        agg_ver: str,
    ) -> dict[str, Any] | None:
        """Read the Phase 4 AggregateSetCompletion marker (prerequisite gate).

        This is a read-only operation. The result is used only to gate intelligence
        generation; the record is never mutated by Phase 5.

        Args:
            client_id: Validated client identifier.
            audit_id: Validated audit identifier.
            exec_id: Durable execution identity.
            cfg: Configuration version.
            agg_ver: Aggregation version (e.g., agg_v1).

        Returns:
            AggregateSetCompletion dict, or None if not found.
        """
        key = {
            "PK": f"CLIENT#{client_id}",
            "SK": f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{agg_ver}#SET",
        }
        return self._get_item(key)

    def list_phase4_aggregate_records(
        self,
        client_id: str,
        audit_id: str,
        exec_id: str,
        cfg: str,
        agg_ver: str,
    ) -> list[dict[str, Any]]:
        """Query all Phase 4 aggregate records for the given execution identity.

        Returns AuditAggregate, all EndpointAggregate records, all
        FailureClassificationAggregate records, and the AggregateSetCompletion marker.
        Lineage manifest records are included but typically filtered out by the engine.

        This query uses the Phase 4 consumer contract access pattern:
          SK begins_with AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{agg_ver}#

        The #INTEL# suffix used by Phase 5 IntelligenceMetadata records is NOT
        matched by this prefix, so Phase 5 records are never returned here.

        Args:
            client_id: Validated client identifier.
            audit_id: Validated audit identifier.
            exec_id: Durable execution identity.
            cfg: Configuration version.
            agg_ver: Aggregation version.

        Returns:
            List of Phase 4 aggregate records.
        """
        pk = f"CLIENT#{client_id}"
        sk_prefix = f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{agg_ver}#"
        return self._query_begins(pk=pk, sk_prefix=sk_prefix)

    # ------------------------------------------------------------------
    # Phase 5 reads
    # ------------------------------------------------------------------

    def get_intelligence_metadata(self, filters: Any) -> dict[str, Any] | None:
        """Read the IntelligenceMetadata record for the given filter combination.

        Accepts a duck-typed filters object with attributes: client_id, audit_id,
        audit_execution_id, config_version, aggregation_version, intelligence_version.
        This matches the IntelligenceFilter dataclass from dtypes.py.

        Used by both IntelligenceRetrievalService (read-only) and IntelligenceEngine
        (idempotency check before generation).

        Args:
            filters: Object with .client_id, .audit_id, .audit_execution_id,
                     .config_version, .aggregation_version, .intelligence_version.

        Returns:
            IntelligenceMetadata dict, or None if not found.
        """
        key = self.intelligence_metadata_keys(
            client_id=filters.client_id,
            audit_id=filters.audit_id,
            exec_id=filters.audit_execution_id,
            cfg=filters.config_version,
            agg_ver=filters.aggregation_version,
            intel_ver=filters.intelligence_version,
        )
        return self._get_item(key)

    # ------------------------------------------------------------------
    # Phase 5 writes — IntelligenceJob
    # ------------------------------------------------------------------

    def put_intelligence_job_once(self, item: dict[str, Any]) -> None:
        """Write an IntelligenceJob record with conditional put (attribute_not_exists).

        Used at invocation start for each new intelligence_job_id. Since the job_id
        is freshly generated, a ConditionalWriteError here indicates a UUID collision
        (extremely unlikely) or a programming error.

        Raises:
            ConditionalWriteError: If the record already exists.
            StorageError: On DynamoDB client or request failure.
        """
        _assert_phase5_sk(item.get("SK", ""))
        self._put_once(item)

    def update_intelligence_job(
        self, key: dict[str, str], updates: dict[str, Any]
    ) -> None:
        """Update fields on an existing IntelligenceJob record.

        Used for IN_PROGRESS, COMPLETE, and FAILED status transitions. Requires the
        record to already exist (ConditionExpression: attribute_exists(PK)).

        Args:
            key: PK/SK dict from intelligence_job_keys().
            updates: Dict of field name → new value to set.

        Raises:
            StorageError: On DynamoDB failure.
        """
        _assert_phase5_sk(key.get("SK", ""))
        self._update_item(key, updates)

    # ------------------------------------------------------------------
    # Phase 5 writes — IntelligenceMetadata
    # ------------------------------------------------------------------

    def put_intelligence_metadata_once(self, item: dict[str, Any]) -> None:
        """Write an IntelligenceMetadata record with conditional put (first generation).

        Used only when no existing IntelligenceMetadata exists for the combination.
        A ConditionalWriteError indicates a concurrent generation attempt or race
        between a check and a put; the engine handles this by reading the existing record.

        Raises:
            ConditionalWriteError: If the record already exists.
            StorageError: On DynamoDB client or request failure.
        """
        _assert_phase5_sk(item.get("SK", ""))
        self._put_once(item)

    def update_intelligence_metadata(self, item: dict[str, Any]) -> None:
        """Overwrite an existing IntelligenceMetadata record (force re-generation / retry).

        Used when an IntelligenceMetadata record already exists (from a prior generation
        attempt, regardless of status). Writes the full item without condition, preserving
        the original created_at timestamp. Does not delete fields; the entire item is
        replaced to ensure all fields reflect the current generation state.

        Args:
            item: Full IntelligenceMetadata item dict (must include PK/SK).

        Raises:
            StorageError: On DynamoDB failure.
        """
        _assert_phase5_sk(item.get("SK", ""))
        sanitized = sanitize(item)
        try:
            self._call(
                "put_item",
                Item=sanitized,
            )
        except ClientError as exc:
            raise storage_error_from_dynamodb_client_error(exc, operation="put_item") from exc
        except Exception as exc:
            raise storage_error_from_dynamodb_request_error(exc, operation="put_item") from exc

    def update_intelligence_metadata_fields(
        self, key: dict[str, str], updates: dict[str, Any]
    ) -> None:
        """Update specific fields on an existing IntelligenceMetadata record.

        Used for status transitions (PENDING → IN_PROGRESS → COMPLETE/FAILED) after
        the record already exists. Does not require the record to have been created
        in this invocation (safe for concurrent writes).

        Args:
            key: PK/SK dict from intelligence_metadata_keys().
            updates: Dict of field name → new value to set.

        Raises:
            StorageError: On DynamoDB failure.
        """
        _assert_phase5_sk(key.get("SK", ""))
        self._update_item(key, updates)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_item(self, key: dict[str, str]) -> dict[str, Any] | None:
        response = self._call("get_item", Key=key)
        return response.get("Item")

    def _query_begins(
        self, pk: str, sk_prefix: str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {
            "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk_prefix)",
            "ExpressionAttributeValues": {":pk": pk, ":sk_prefix": sk_prefix},
        }
        items: list[dict[str, Any]] = []
        while True:
            response = self._call("query", **kwargs)
            items.extend(response.get("Items", []))
            last_key = response.get("LastEvaluatedKey")
            if not last_key or (limit is not None and len(items) >= limit):
                break
            kwargs["ExclusiveStartKey"] = last_key
        return items

    def _put_once(self, item: dict[str, Any]) -> None:
        try:
            self._call(
                "put_item",
                preserve_client_error_codes={"ConditionalCheckFailedException"},
                Item=sanitize(item),
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConditionalWriteError() from exc
            raise

    def _update_item(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        sanitized_updates = sanitize(updates)
        names = {f"#f{i}": field_name for i, field_name in enumerate(sanitized_updates)}
        values = {f":v{i}": value for i, value in enumerate(sanitized_updates.values())}
        assignments = ", ".join(f"{name} = :v{i}" for i, name in enumerate(names))
        self._call(
            "update_item",
            Key=key,
            UpdateExpression="SET " + assignments,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )

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
