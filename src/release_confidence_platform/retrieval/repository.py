"""RetrievalRepository — read-only storage provider interactions.

This class is the ONLY place that touches DynamoDB for retrieval operations.
It never writes, updates, or deletes records.
"""

from __future__ import annotations

from typing import Any

from release_confidence_platform.storage.dynamodb_codec import (
    decode_dynamodb_response,
    encode_dynamodb_call_kwargs,
    storage_error_from_dynamodb_client_error,
    storage_error_from_dynamodb_request_error,
)


class RetrievalRepository:
    """Read-only DynamoDB repository for the Engineering Retrieval Layer."""

    def __init__(self, table_name: str, dynamodb_client: Any) -> None:
        self.table_name = table_name
        self.dynamodb_client = dynamodb_client

    # ------------------------------------------------------------------
    # Audit-level reads
    # ------------------------------------------------------------------

    def get_audit_metadata(self, client_id: str, audit_id: str) -> dict[str, Any] | None:
        return self._get_item({"PK": f"CLIENT#{client_id}", "SK": f"AUDIT#{audit_id}"})

    # ------------------------------------------------------------------
    # Aggregation job reads
    # ------------------------------------------------------------------

    def list_aggregation_jobs(self, client_id: str, audit_id: str) -> list[dict[str, Any]]:
        return self._query_begins(
            pk=f"CLIENT#{client_id}",
            sk_prefix=f"AUDIT#{audit_id}#AGGJOB#",
        )

    def get_latest_aggregation_job(
        self, client_id: str, audit_id: str
    ) -> dict[str, Any] | None:
        jobs = self.list_aggregation_jobs(client_id, audit_id)
        if not jobs:
            return None
        return max(jobs, key=lambda j: j.get("started_at") or j.get("SK") or "")

    # ------------------------------------------------------------------
    # Aggregate records
    # ------------------------------------------------------------------

    def list_aggregate_records(
        self, client_id: str, audit_id: str
    ) -> list[dict[str, Any]]:
        """Return all items whose SK begins with AUDIT#{audit_id}#EXEC# — aggregate set."""
        return self._query_begins(
            pk=f"CLIENT#{client_id}",
            sk_prefix=f"AUDIT#{audit_id}#EXEC#",
        )

    def get_aggregate_set_completion(
        self, client_id: str, audit_id: str
    ) -> dict[str, Any] | None:
        records = self.list_aggregate_records(client_id, audit_id)
        for record in records:
            if record.get("aggregate_type") == "aggregate_set_completion":
                return record
        return None

    # ------------------------------------------------------------------
    # Lifecycle history
    # ------------------------------------------------------------------

    def list_lifecycle_history(
        self, client_id: str, audit_id: str
    ) -> list[dict[str, Any]]:
        return self._query_begins(
            pk=f"CLIENT#{client_id}",
            sk_prefix=f"AUDIT#{audit_id}#LIFECYCLE#",
        )

    # ------------------------------------------------------------------
    # Full audit item scan
    # ------------------------------------------------------------------

    def list_all_audit_items(
        self, client_id: str, audit_id: str
    ) -> list[dict[str, Any]]:
        """Return all items under PK=CLIENT#{client_id}, SK begins_with AUDIT#{audit_id}#."""
        return self._query_begins(
            pk=f"CLIENT#{client_id}",
            sk_prefix=f"AUDIT#{audit_id}#",
        )

    # ------------------------------------------------------------------
    # Lineage manifests
    # ------------------------------------------------------------------

    def list_lineage_manifests(
        self, client_id: str, audit_id: str
    ) -> list[dict[str, Any]]:
        records = self.list_aggregate_records(client_id, audit_id)
        return [r for r in records if r.get("record_kind") == "lineage_manifest"]

    # ------------------------------------------------------------------
    # Completed runs
    # ------------------------------------------------------------------

    def list_completed_runs(
        self, client_id: str, audit_id: str
    ) -> list[dict[str, Any]]:
        items = self._query_begins(
            pk=f"CLIENT#{client_id}",
            sk_prefix=f"AUDIT#{audit_id}#RUN#",
        )
        return [
            item
            for item in items
            if item.get("status") == "COMPLETED" and item.get("raw_result_s3_key")
        ]

    # ------------------------------------------------------------------
    # Private helpers — read-only only
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

    def _call(self, method_name: str, **kwargs: Any) -> dict[str, Any]:
        method = getattr(self.dynamodb_client, method_name)
        try:
            return decode_dynamodb_response(
                method(TableName=self.table_name, **encode_dynamodb_call_kwargs(kwargs))
            )
        except TypeError:
            return decode_dynamodb_response(method(**kwargs))
        except Exception as exc:  # noqa: BLE001
            from botocore.exceptions import ClientError  # noqa: PLC0415

            if isinstance(exc, ClientError):
                raise storage_error_from_dynamodb_client_error(
                    exc, operation=method_name
                ) from exc
            raise storage_error_from_dynamodb_request_error(
                exc, operation=method_name
            ) from exc
