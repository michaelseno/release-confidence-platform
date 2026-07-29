"""DynamoDB-backed Phase 4 aggregation repository."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from botocore.exceptions import ClientError

from release_confidence_platform.aggregation.constants import (
    CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA_ENV_VAR,
    MAX_AGGREGATE_ITEM_BYTES,
    MAX_AGGREGATE_RECORDS,
    MAX_AGGREGATE_TRANSACTION_BYTES,
)
from release_confidence_platform.core.exceptions import StorageError
from release_confidence_platform.evidence_retention.hold_coordination import (
    HoldCoordinatedTransactionRunner,
    build_hold_version_condition_check_item,
    compute_ttl_disposal_at,
)
from release_confidence_platform.evidence_retention.hold_repository import HoldRepository
from release_confidence_platform.sanitization.sanitizer import sanitize
from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    encode_item,
    storage_error_from_dynamodb_client_error,
    storage_error_from_dynamodb_request_error,
)

# Evidence Governance Workstream A1.3c.1 (Technical Design Section 19.16.1):
# the exact, message-first wording Product Strategy required for the
# deterministic, client-side item-count/byte-budget rejection -- must not
# suggest an unauthorized remediation (transaction splitting is explicitly
# not authorized).
_AGGREGATE_SET_TOO_LARGE_MESSAGE = (
    "Aggregate set exceeds the governed atomic-transaction limit. Reduce the "
    "configured endpoint scope or obtain a separately reviewed architecture "
    "decision."
)

_SECONDS_PER_DAY = 86400


class ConditionalWriteError(StorageError):
    def __init__(self, message: str = "Conditional write failed"):
        super().__init__(message, "CONDITIONAL_WRITE_FAILED")


def _resolve_aggregate_metadata_custody_period_days() -> int:
    """Read a positive-integer custody-period-days value from the environment.

    Evidence Governance Workstream A1.3c.1 (Technical Design Section 19.16.5;
    ADR Decision 5 amendment / Non-Negotiable Invariant 26). Mirrors
    packages/storage/dynamodb_client.py::_resolve_custody_period_days_env's
    exact logic: read fresh from the environment on every call, so a
    later-populated environment variable takes effect without a code change
    -- never assumes or hardcodes a duration value, and never borrows another
    evidence class's configured value.

    Raises:
        StorageError: ``CUSTODY_PERIOD_CONFIG_MISSING`` if the variable is
            unset, empty, non-numeric, or not a positive integer -- the
            caller must fail closed rather than write a governed record
            without custody_expires_at/ttl_disposal_at.
    """
    raw_value = os.environ.get(CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA_ENV_VAR)
    if raw_value is not None:
        try:
            parsed = int(raw_value)
        except ValueError:
            parsed = None
        if parsed is not None and parsed > 0:
            return parsed
    raise StorageError(
        "Custody-period configuration is unresolvable at runtime (environment "
        f"variable {CUSTODY_PERIOD_DAYS_AGGREGATE_METADATA_ENV_VAR} is unset, empty, or "
        "not a positive integer); refusing to write a governed record without "
        "custody_expires_at/ttl_disposal_at rather than silently omitting them or "
        "assuming a duration.",
        "CUSTODY_PERIOD_CONFIG_MISSING",
    )


def _aggregate_governance_fields(
    hold_state: dict[str, Any] | None, custody_period_days: int
) -> dict[str, int | str]:
    """Compute custody_expires_at/ttl_disposal_at/evidence_class for a Phase 4
    governed record (Technical Design Section 19.4 step 2, Section 19.16.5).

    custody_expires_at is always freshly computed, independent of hold state.
    ttl_disposal_at is omitted (compute_ttl_disposal_at returns None) if and
    only if this attempt's own hold_state read observed an ACTIVE hold;
    otherwise it equals custody_expires_at. evidence_class is a fixed
    constant, included here so the caller's merge
    (`{**item, **_aggregate_governance_fields(...)}`) both establishes the
    governed fields atomically and guarantees the fixed values always win
    over any same-named key the caller's item might already contain.
    """
    now_epoch_seconds = int(datetime.now(UTC).timestamp())
    custody_expires_at = now_epoch_seconds + custody_period_days * _SECONDS_PER_DAY
    fields: dict[str, int | str] = {
        "custody_expires_at": custody_expires_at,
        "evidence_class": "aggregate_metadata",
    }
    ttl_disposal_at = compute_ttl_disposal_at(hold_state, custody_expires_at)
    if ttl_disposal_at is not None:
        fields["ttl_disposal_at"] = ttl_disposal_at
    return fields


def _measure_item_bytes(encoded_item: dict[str, Any]) -> int:
    """Deterministic, conservative measurement of one encoded DynamoDB item
    (Technical Design Section 19.16.2/19.16.3) -- evaluated post-augmentation
    (after governance-field merge) and post-encoding (wire format), never
    before either."""
    return len(json.dumps(encoded_item, sort_keys=True, default=str).encode("utf-8"))


def _measure_transaction_bytes(transact_items: list[dict[str, Any]]) -> int:
    """Deterministic, conservative measurement of the complete, final
    transact-item list -- every Put and the appended LegalHold ConditionCheck
    together (Technical Design Section 19.16.3) -- via one canonical
    serialization, so repeated evaluation of the identical input always
    yields the identical measurement. This is an RCP-owned conservative
    preflight guard, not a reproduction of AWS's own internal
    TransactWriteItems byte-accounting (Section 19.16.3)."""
    return len(json.dumps(transact_items, sort_keys=True, default=str).encode("utf-8"))


# Evidence Governance Workstream A1.3b (Technical Design Section 18.7). This
# is a rejection guard, not a full allowlist of update_job's legitimate
# field vocabulary -- AggregationJob is Category 3 (operational coordination
# metadata, Technical Design Section 18.1) and is permanently excluded from
# custody-field treatment. update_job's generic `dict[str, Any]` -> dynamic
# UpdateExpression construction has no field allowlist otherwise, so nothing
# else stops a future caller from smuggling either retention-governed field
# through it. Tactical and local to this specific gap -- see Section 18.7's
# own clarification that this is not a precedent for retrofitting similar
# guards onto other update methods.
_RETENTION_GOVERNED_FIELD_NAMES = frozenset({"ttl_disposal_at", "custody_expires_at"})


class AggregationRepository:
    def __init__(
        self,
        table_name: str,
        dynamodb_client: Any,
        hold_repository: HoldRepository | None = None,
    ):
        # Evidence Governance Workstream A1.3c.1 (Technical Design Section
        # 19.4, 19.16): `hold_repository` is additive and optional --
        # `dynamodb_client` keeps its existing role, already the low-level
        # client `put_records_once`/`put_lineage_page_once` call
        # `transact_write_items` on directly (no Table-resource split, unlike
        # RunMetadata's DynamoDBMetadataClient). HoldCoordinatedTransactionRunner
        # is constructed from this SAME client -- there is no second
        # transact_dynamodb_client parameter here. When `hold_repository` is
        # omitted, the two governed write methods fail closed
        # (HOLD_COORDINATION_NOT_CONFIGURED) rather than writing without ever
        # having checked legal-hold state.
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client
        self._hold_repository = hold_repository

    def audit_keys(self, client_id: str, audit_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"}

    def execution_identity_keys(self, client_id: str, audit_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#EXECUTION_ID"}

    def job_keys(self, client_id: str, audit_id: str, job_id: str) -> dict[str, str]:
        return {"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}#AGGJOB#{job_id}"}

    def aggregate_prefix(
        self, client_id: str, audit_id: str, exec_id: str, cfg: str, ver: str
    ) -> str:
        return f"AUDIT#{audit_id}#EXEC#{exec_id}#CFG#{cfg}#AGG#{ver}"

    def get_audit_metadata(self, client_id: str, audit_id: str) -> dict[str, Any]:
        response = self._call("get_item", Key=self.audit_keys(client_id, audit_id))
        if "Item" not in response:
            raise StorageError("Audit metadata not found", "AUDIT_NOT_FOUND")
        return response["Item"]

    def get_audit_execution_identity(self, client_id: str, audit_id: str) -> dict[str, Any] | None:
        return self._call("get_item", Key=self.execution_identity_keys(client_id, audit_id)).get(
            "Item"
        )

    def put_audit_execution_identity_once(self, item: dict[str, Any]) -> None:
        self._put_once(item)

    def put_job_once(self, item: dict[str, Any]) -> None:
        self._put_once(item)

    def put_lineage_page_once(
        self, item: dict[str, Any], *, client_id: str, audit_id: str
    ) -> None:
        """Write one lineage-manifest page as a hold-coordinated, two-item
        TransactWriteItems call (Technical Design Section 19.4, 19.16.5):
        one governed Put + the appended LegalHold.hold_version ConditionCheck.

        Raises:
            StorageError: ``HOLD_COORDINATION_NOT_CONFIGURED`` if this
                instance has no HoldRepository; ``CUSTODY_PERIOD_CONFIG_MISSING``
                if the aggregate_metadata custody-period environment variable
                is unresolvable -- both fail closed before any hold-state
                read, transact-item construction, or AWS request;
                ``AGGREGATE_SET_TOO_LARGE`` if the item exceeds
                MAX_AGGREGATE_ITEM_BYTES post-governance-merge, or the final
                two-item transaction exceeds MAX_AGGREGATE_TRANSACTION_BYTES;
                ``HOLD_STATE_CONCURRENCY_EXCEEDED`` on bounded hold-version
                retry exhaustion.
            ConditionalWriteError: If the governed item's own condition
                failed (an existing page at this key) -- never masked behind
                a hold-version retry, per Section 19.4 step 4's precedence.
        """
        if self._hold_repository is None:
            raise StorageError(
                "Hold coordination is not configured", "HOLD_COORDINATION_NOT_CONFIGURED"
            )
        custody_period_days = _resolve_aggregate_metadata_custody_period_days()
        sanitized_item = sanitize(item)
        hold_key = self._hold_repository.legal_hold_key(client_id, audit_id)

        def build_transact_items(
            hold_state: dict[str, Any] | None,
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            # Governance fields merged LAST -- fixed values always win over
            # any same-named key the caller's item might already contain,
            # and are recomputed fresh from this attempt's own hold_state
            # read (never carried forward from a prior attempt).
            item_with_governance = {
                **sanitized_item,
                **_aggregate_governance_fields(hold_state, custody_period_days),
            }
            encoded_item = encode_item(item_with_governance)
            if _measure_item_bytes(encoded_item) > MAX_AGGREGATE_ITEM_BYTES:
                raise StorageError(_AGGREGATE_SET_TOO_LARGE_MESSAGE, "AGGREGATE_SET_TOO_LARGE")
            put_transact_item = {
                "Put": {
                    "TableName": self.table_name,
                    "Item": encoded_item,
                    "ConditionExpression": (
                        "attribute_not_exists(PK) AND attribute_not_exists(SK)"
                    ),
                }
            }
            hold_condition_item = build_hold_version_condition_check_item(
                self.table_name, hold_key, hold_state
            )
            if (
                _measure_transaction_bytes([put_transact_item, hold_condition_item])
                > MAX_AGGREGATE_TRANSACTION_BYTES
            ):
                raise StorageError(_AGGREGATE_SET_TOO_LARGE_MESSAGE, "AGGREGATE_SET_TOO_LARGE")
            return [put_transact_item], hold_condition_item

        def _raise_conditional_write_error(reasons: list[dict[str, Any]]) -> None:
            # Section 19.4 step 4's explicit precedence: the governed item's
            # own condition failure always wins, regardless of whether the
            # hold ConditionCheck also failed in the same attempt.
            del reasons
            raise ConditionalWriteError()

        runner = HoldCoordinatedTransactionRunner(self.dynamodb_client, self._hold_repository)
        runner.run(
            client_id,
            audit_id,
            build_transact_items,
            on_governed_condition_failed=_raise_conditional_write_error,
        )

    def get_lineage_page(self, key: dict[str, str]) -> dict[str, Any] | None:
        return self._call("get_item", Key=key).get("Item")

    def update_job(self, key: dict[str, str], updates: dict[str, Any]) -> None:
        forbidden = _RETENTION_GOVERNED_FIELD_NAMES & updates.keys()
        if forbidden:
            raise AssertionError(
                "AggregationJob.update_job must never set retention-governed "
                f"fields {sorted(forbidden)!r}; AggregationJob is Category 3 "
                "(operational coordination metadata) and is permanently "
                "excluded from custody-field treatment."
            )
        names = {f"#f{i}": key for i, key in enumerate(updates)}
        values = {f":v{i}": value for i, value in enumerate(sanitize(updates).values())}
        assignments = ", ".join(f"{name} = :v{i}" for i, name in enumerate(names))
        self._call(
            "update_item",
            Key=key,
            UpdateExpression="SET " + assignments,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
            ConditionExpression="attribute_exists(PK) AND attribute_exists(SK)",
        )

    def get_job(self, key: dict[str, str]) -> dict[str, Any] | None:
        return self._call("get_item", Key=key).get("Item")

    def list_completed_runs(self, client_id: str, audit_id: str) -> list[dict[str, Any]]:
        response = self._call(
            "query",
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={
                ":pk": f"CLIENT#{client_id}",
                ":sk_prefix": f"AUDIT#{audit_id}#RUN#",
            },
        )
        runs = []
        for item in response.get("Items", []):
            if (
                item.get("status") == "COMPLETED"
                and item.get("raw_result_version") == "v1"
                and item.get("raw_result_s3_key")
            ):
                runs.append(item)
        return sorted(runs, key=lambda item: item.get("SK", ""))

    def aggregate_set_exists(
        self, client_id: str, audit_id: str, exec_id: str, cfg: str, ver: str
    ) -> bool:
        pk = f"CLIENT#{client_id}"
        prefix = self.aggregate_prefix(client_id, audit_id, exec_id, cfg, ver)
        marker = self._call("get_item", Key={"PK": pk, "SK": f"{prefix}#SET"}).get("Item")
        if not marker or marker.get("completion_status") != "COMPLETE":
            return False
        required_sort_keys = [
            f"{prefix}#LINEAGE#audit",
            f"{prefix}#AUDIT",
            f"{prefix}#FAILURE_CLASSIFICATION",
        ]
        endpoint_count = marker.get("endpoint_aggregate_count")
        aggregate_count = marker.get("aggregate_record_count")
        if not isinstance(endpoint_count, int) or not isinstance(aggregate_count, int):
            return False
        found_aggregates = 0
        for sk in required_sort_keys:
            if "Item" not in self._call("get_item", Key={"PK": pk, "SK": sk}):
                return False
            found_aggregates += 1 if not sk.endswith("LINEAGE#audit") else 0
        response = self._call(
            "query",
            KeyConditionExpression="PK = :pk AND begins_with(SK, :sk_prefix)",
            ExpressionAttributeValues={":pk": pk, ":sk_prefix": f"{prefix}#ENDPOINT#"},
        )
        endpoint_records = [
            item for item in response.get("Items", []) if item.get("record_kind") == "aggregate"
        ]
        endpoint_aggregates = [
            item
            for item in endpoint_records
            if item.get("aggregate_type") == "endpoint"
        ]
        if len(endpoint_aggregates) != endpoint_count:
            return False
        found_aggregates += len(endpoint_records)
        return found_aggregates == aggregate_count

    def put_records_once(
        self, records: list[dict[str, Any]], *, client_id: str, audit_id: str
    ) -> None:
        """Write the aggregate set's `4 + 3N` governed records (N = distinct
        endpoint count) as one hold-coordinated TransactWriteItems call,
        with the appended LegalHold.hold_version ConditionCheck as the
        transaction's final item (Technical Design Section 19.4, 19.16).

        Raises:
            StorageError: ``HOLD_COORDINATION_NOT_CONFIGURED`` if this
                instance has no HoldRepository; ``CUSTODY_PERIOD_CONFIG_MISSING``
                if the aggregate_metadata custody-period environment variable
                is unresolvable -- both fail closed before any hold-state
                read, transact-item construction, or AWS request;
                ``AGGREGATE_SET_TOO_LARGE`` if the governed-item count exceeds
                MAX_AGGREGATE_RECORDS (checked before any hold read), any
                individual item exceeds MAX_AGGREGATE_ITEM_BYTES
                post-governance-merge, or the final transaction exceeds
                MAX_AGGREGATE_TRANSACTION_BYTES; ``HOLD_STATE_CONCURRENCY_EXCEEDED``
                on bounded hold-version retry exhaustion.
            ConditionalWriteError: If any governed record's own condition
                failed (e.g. a duplicate aggregate-set write) -- never masked
                behind a hold-version retry, per Section 19.4 step 4's
                precedence.
        """
        if self._hold_repository is None:
            raise StorageError(
                "Hold coordination is not configured", "HOLD_COORDINATION_NOT_CONFIGURED"
            )
        # Resolved before the item-count check (Technical Design Section
        # 19.16.5) -- a missing/invalid custody-period configuration must
        # fail closed regardless of aggregate-set size.
        custody_period_days = _resolve_aggregate_metadata_custody_period_days()
        sanitized_records = [sanitize(item) for item in records]
        # Item-count check happens before any hold read and before
        # HoldCoordinatedTransactionRunner.run() is ever invoked -- zero
        # hold reads, zero AWS calls on rejection (Technical Design Section
        # 19.16.1).
        if len(sanitized_records) > MAX_AGGREGATE_RECORDS:
            raise StorageError(_AGGREGATE_SET_TOO_LARGE_MESSAGE, "AGGREGATE_SET_TOO_LARGE")
        hold_key = self._hold_repository.legal_hold_key(client_id, audit_id)

        def build_transact_items(
            hold_state: dict[str, Any] | None,
        ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
            # Governance fields merged LAST onto every record, recomputed
            # fresh from this attempt's own hold_state read -- fixed values
            # always win over any same-named key a caller-supplied record
            # might already contain, and never carry forward across retries.
            governance_fields = _aggregate_governance_fields(hold_state, custody_period_days)
            governed_items: list[dict[str, Any]] = []
            for item in sanitized_records:
                item_with_governance = {**item, **governance_fields}
                encoded_item = encode_item(item_with_governance)
                # Post-augmentation per-item size validation (Technical
                # Design Section 19.16.2) -- a pre-merge check is
                # insufficient; an item just under the ceiling before
                # augmentation can be pushed over it by the added
                # attributes.
                if _measure_item_bytes(encoded_item) > MAX_AGGREGATE_ITEM_BYTES:
                    raise StorageError(
                        _AGGREGATE_SET_TOO_LARGE_MESSAGE, "AGGREGATE_SET_TOO_LARGE"
                    )
                governed_items.append(
                    {
                        "Put": {
                            "TableName": self.table_name,
                            "Item": encoded_item,
                            "ConditionExpression": (
                                "attribute_not_exists(PK) AND attribute_not_exists(SK)"
                            ),
                        }
                    }
                )
            hold_condition_item = build_hold_version_condition_check_item(
                self.table_name, hold_key, hold_state
            )
            # Deterministic conservative transaction-size measurement over
            # the final wire-format transact-item list -- every Put and the
            # appended ConditionCheck together (Technical Design Section
            # 19.16.3).
            if (
                _measure_transaction_bytes(governed_items + [hold_condition_item])
                > MAX_AGGREGATE_TRANSACTION_BYTES
            ):
                raise StorageError(_AGGREGATE_SET_TOO_LARGE_MESSAGE, "AGGREGATE_SET_TOO_LARGE")
            return governed_items, hold_condition_item

        def _raise_conditional_write_error(reasons: list[dict[str, Any]]) -> None:
            # Section 19.4 step 4's explicit precedence: a governed record's
            # own condition failure always wins, regardless of whether the
            # hold ConditionCheck also failed in the same attempt.
            del reasons
            raise ConditionalWriteError()

        runner = HoldCoordinatedTransactionRunner(self.dynamodb_client, self._hold_repository)
        runner.run(
            client_id,
            audit_id,
            build_transact_items,
            on_governed_condition_failed=_raise_conditional_write_error,
        )

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
            if exc.response.get("Error", {}).get("Code") in (preserve_client_error_codes or set()):
                raise
            raise storage_error_from_dynamodb_client_error(exc, operation=method_name) from exc
        except Exception as exc:
            raise storage_error_from_dynamodb_request_error(exc, operation=method_name) from exc
