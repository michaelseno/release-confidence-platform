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

from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldCoordinatedTransactionRunner,
    build_hold_version_condition_check_item,
    compute_ttl_disposal_at,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    encode_item,
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


def _parse_phase5_metadata_identity(item: dict[str, Any]) -> tuple[str, str]:
    """Parse (client_id, audit_id) from a trusted, internally-constructed
    IntelligenceMetadata item's PK/SK (Technical Design Section 20.6).

    This is not caller-input validation -- the item has already passed
    _assert_phase5_sk() by the time this is called. It exists solely to
    resolve the audit identity HoldCoordinatedTransactionRunner and
    HoldRepository.legal_hold_key() require.
    """
    pk, sk = item.get("PK", ""), item.get("SK", "")
    if not pk.startswith("CLIENT#") or not sk.startswith("AUDIT#"):
        raise StorageError(
            "IntelligenceMetadata item PK/SK does not match the expected "
            "CLIENT#{client_id}/AUDIT#{audit_id}#... shape; cannot resolve "
            "audit identity for legal-hold state resolution.",
            "STORAGE_ERROR",
        )
    client_id = pk[len("CLIENT#") :]
    audit_id = sk[len("AUDIT#") :].split("#", 1)[0]
    if not client_id or not audit_id:
        raise StorageError(
            "IntelligenceMetadata item PK/SK does not match the expected "
            "CLIENT#{client_id}/AUDIT#{audit_id}#... shape; cannot resolve "
            "audit identity for legal-hold state resolution.",
            "STORAGE_ERROR",
        )
    return client_id, audit_id


def _intelligence_governance_fields(
    hold_state: dict[str, Any] | None, custody_period_days: int
) -> dict[str, int | str]:
    """Compute custody_expires_at/ttl_disposal_at/evidence_class for a Phase 5
    governed IntelligenceMetadata write (Technical Design Section 20.6).

    Mirrors aggregation/repository.py::_aggregate_governance_fields exactly,
    with evidence_class fixed to "intelligence". custody_expires_at is
    always freshly computed; ttl_disposal_at is omitted if and only if this
    attempt's own hold_state read observed an ACTIVE hold.
    """
    now_epoch_seconds = int(datetime.now(UTC).timestamp())
    custody_expires_at = now_epoch_seconds + custody_period_days * 86400
    fields: dict[str, int | str] = {
        "custody_expires_at": custody_expires_at,
        "evidence_class": "intelligence",
    }
    ttl_disposal_at = compute_ttl_disposal_at(hold_state, custody_expires_at)
    if ttl_disposal_at is not None:
        fields["ttl_disposal_at"] = ttl_disposal_at
    return fields


class IntelligenceRepository:
    """Phase 4 consumer reads and Phase 5 artifact writes for Reliability Intelligence."""

    def __init__(
        self,
        table_name: str,
        dynamodb_client: Any,
        hold_repository: HoldRepository | None = None,
        *,
        custody_period_days: int | None = None,
    ) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client
        self._hold_repository = hold_repository
        self._custody_period_days = custody_period_days

    def _governance_preflight(self) -> None:
        """Write-entry governance preflight (ADR Invariant 31; Technical
        Design Section 20.4). Mandatory first action of every governed
        write method, before any hold-state read, transaction-item
        construction, or AWS mutation. Order is load-bearing: hold
        coordination presence, then custody-duration presence, then
        custody-duration validity (Boolean rejected before the int check,
        since bool is an int subclass).
        """
        if self._hold_repository is None:
            raise StorageError(
                "Hold coordination is not configured", "HOLD_COORDINATION_NOT_CONFIGURED"
            )
        if self._custody_period_days is None:
            raise StorageError(
                "Custody period configuration was not provided to this repository instance",
                "CUSTODY_PERIOD_CONFIG_MISSING",
            )
        if (
            isinstance(self._custody_period_days, bool)
            or not isinstance(self._custody_period_days, int)
            or self._custody_period_days <= 0
        ):
            raise StorageError(
                "Custody period configuration is invalid", "CUSTODY_PERIOD_CONFIG_MISSING"
            )

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
        """Write an IntelligenceMetadata record as a hold-coordinated
        TransactWriteItems call (first generation) -- the existing
        conditional Put (attribute_not_exists(PK) AND attribute_not_exists(SK))
        plus the appended LegalHold.hold_version ConditionCheck (Technical
        Design Section 20.6).

        Used only when no existing IntelligenceMetadata exists for the combination.
        A ConditionalWriteError indicates a concurrent generation attempt or race
        between a check and a put; the engine handles this by reading the existing record.

        Raises:
            StorageError: ``HOLD_COORDINATION_NOT_CONFIGURED`` if this
                instance has no HoldRepository; ``CUSTODY_PERIOD_CONFIG_MISSING``
                if no valid custody-period duration was injected -- both fail
                closed before any hold-state read, transact-item
                construction, or AWS request; ``HOLD_STATE_CONCURRENCY_EXCEEDED``
                on bounded hold-version retry exhaustion.
            ConditionalWriteError: If the record's own condition failed (an
                existing item at this key) -- never masked behind a
                hold-version retry.
        """
        self._governance_preflight()
        _assert_phase5_sk(item.get("SK", ""))
        client_id, audit_id = _parse_phase5_metadata_identity(item)
        base_item = dict(item)  # shallow copy -- NEVER sanitize() a persistence-bound item
        hold_key = self._hold_repository.legal_hold_key(client_id, audit_id)

        def build_transact_items(
            hold_state: dict[str, Any] | None,
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            item_with_governance = {
                **base_item,
                **_intelligence_governance_fields(hold_state, self._custody_period_days),
            }
            put_transact_item = {
                "Put": {
                    "TableName": self.table_name,
                    "Item": encode_item(item_with_governance),
                    "ConditionExpression": (
                        "attribute_not_exists(PK) AND attribute_not_exists(SK)"
                    ),
                }
            }
            hold_condition_item = build_hold_version_condition_check_item(
                self.table_name, hold_key, hold_state
            )
            return [put_transact_item], hold_condition_item

        def _raise_conditional_write_error(reasons: list[dict[str, Any]]) -> None:
            del reasons
            raise ConditionalWriteError()

        runner = HoldCoordinatedTransactionRunner(self.dynamodb_client, self._hold_repository)
        runner.run(
            client_id,
            audit_id,
            build_transact_items,
            on_governed_condition_failed=_raise_conditional_write_error,
        )

    def update_intelligence_metadata(self, item: dict[str, Any]) -> None:
        """Overwrite an existing IntelligenceMetadata record (force
        re-generation / retry) as a hold-coordinated TransactWriteItems call
        -- the Put itself remains unconditioned (preserving the existing
        "entire item is replaced" force-regeneration semantics), with the
        appended LegalHold.hold_version ConditionCheck as the only condition
        in the transaction (Technical Design Section 20.6).

        Used when an IntelligenceMetadata record already exists (from a prior generation
        attempt, regardless of status). Writes the full item without condition, preserving
        the original created_at timestamp. Does not delete fields; the entire item is
        replaced to ensure all fields reflect the current generation state.

        Args:
            item: Full IntelligenceMetadata item dict (must include PK/SK).

        Raises:
            StorageError: ``HOLD_COORDINATION_NOT_CONFIGURED`` if this
                instance has no HoldRepository; ``CUSTODY_PERIOD_CONFIG_MISSING``
                if no valid custody-period duration was injected --
                both fail closed before any hold-state read, transact-item
                construction, or AWS request; ``HOLD_STATE_CONCURRENCY_EXCEEDED``
                on bounded hold-version retry exhaustion.
        """
        self._governance_preflight()
        _assert_phase5_sk(item.get("SK", ""))
        client_id, audit_id = _parse_phase5_metadata_identity(item)
        base_item = dict(item)  # shallow copy -- NEVER sanitize() a persistence-bound item
        hold_key = self._hold_repository.legal_hold_key(client_id, audit_id)

        def build_transact_items(
            hold_state: dict[str, Any] | None,
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            item_with_governance = {
                **base_item,
                **_intelligence_governance_fields(hold_state, self._custody_period_days),
            }
            put_transact_item = {
                "Put": {
                    "TableName": self.table_name,
                    "Item": encode_item(item_with_governance),
                }
            }
            hold_condition_item = build_hold_version_condition_check_item(
                self.table_name, hold_key, hold_state
            )
            return [put_transact_item], hold_condition_item

        runner = HoldCoordinatedTransactionRunner(self.dynamodb_client, self._hold_repository)
        runner.run(client_id, audit_id, build_transact_items)

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
                Item=item,
                ConditionExpression="attribute_not_exists(PK) AND attribute_not_exists(SK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConditionalWriteError() from exc
            raise

    def _update_item(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        names = {f"#f{i}": field_name for i, field_name in enumerate(updates)}
        values = {f":v{i}": value for i, value in enumerate(updates.values())}
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
